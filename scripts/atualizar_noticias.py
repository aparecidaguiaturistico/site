#!/usr/bin/env python3
"""
Coletor de notícias do Guia Turístico de Aparecida (SP).

Roda no GitHub Actions e gera DOIS arquivos na raiz do repositório:

  noticias.json       -> ticker do topo do site (só Aparecida, voltado ao visitante)
  noticias_aba.json   -> aba "Notícias" (Aparecida, Igreja, Região, Brasil, Política, Entretenimento)

Só usa a biblioteca padrão do Python (nada para instalar).
Para ajustar o que entra, edite CATEGORIAS e as listas de bloqueio logo abaixo.
"""
import json
import re
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SAIDA_TICKER = RAIZ / "noticias.json"
SAIDA_ABA = RAIZ / "noticias_aba.json"

BASE_GN = "hl=pt-BR&gl=BR&ceid=BR:pt-419"


def busca(q, dias):
    """Feed do Google News para uma busca, limitado aos últimos `dias` dias."""
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(
        {"q": f"{q} when:{dias}d", "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"})


# ----------------------------------------------------------------------------
# Listas de filtro (sem acento, minúsculas). Edite à vontade.
# ----------------------------------------------------------------------------

# Cidades homônimas que não têm a ver com Aparecida (SP)
EXCLUI_LOCAIS = ["aparecida de goiania", "goiania", "aparecida do taboado", "aparecida d'oeste",
                 "aparecida do rio negro", "aparecida de minas"]

# Combina com um guia familiar: sem crimes, mortes, acidentes...
EXCLUI_TEMAS = ["assassin", "homicid", "morto", "morre", "morreu", "morte", "preso", "presa", "presos",
                "policia", "policial", "tiroteio", "roubo", "furto", "estupro", "trafico", "acidente",
                "atropel", "afogad", "suicid", "corpo", "esfaquead", "baleado", "tiros", "velorio",
                "luto", "sequestr", "golpe", "prisao", "feminicid", "cadaver", "overdose"]

# Para Brasil/Política/Entretenimento: só corta o que é muito pesado
EXCLUI_GRAFICO = ["estupro", "esfaquead", "feminicid", "cadaver", "suicid", "decapit", "abuso sexual"]

# Assuntos só da Igreja como instituição: ficam FORA do ticker (continuam na aba)
EXCLUI_ECLESIASTICO = ["documento de aparecida", "congresso", "bispo", "sinodo", "cnbb", "arcebispo",
                       "cardeal", "leao xiv", "papa leao", "assembleia", "seminario", "concilio",
                       "episcopado", "nunciatura", "encontro nacional", "conferencia"]

# O título precisa ter pelo menos uma destas expressões (categoria Aparecida)
RELEVANTE_APARECIDA = ["aparecida", "santuario nacional", "romeiro", "padroeira"]

CATEGORIAS = [
    {"id": "aparecida", "nome": "Aparecida", "dias": 10, "max": 15,
     "relevante": RELEVANTE_APARECIDA, "bloqueio": EXCLUI_TEMAS,
     "feeds": [busca('"Santuário Nacional" Aparecida', 10),
               busca('"Basílica de Aparecida"', 10),
               busca('"Aparecida (SP)" turismo OR romeiros OR evento OR festa', 10),
               busca("Prefeitura de Aparecida SP", 10)]},
    {"id": "igreja", "nome": "Igreja", "dias": 5, "max": 12,
     "relevante": None, "bloqueio": EXCLUI_TEMAS,
     "feeds": [busca('"Igreja Católica" OR CNBB OR Papa', 5)]},
    {"id": "regiao", "nome": "Região", "dias": 7, "max": 12,
     "relevante": None, "bloqueio": EXCLUI_TEMAS,
     "feeds": [busca('Guaratinguetá OR "Cachoeira Paulista" OR Lorena OR Potim OR Roseira OR "Vale do Paraíba"', 7)]},
    {"id": "brasil", "nome": "Brasil", "dias": 2, "max": 12,
     "relevante": None, "bloqueio": EXCLUI_GRAFICO,
     "feeds": [f"https://news.google.com/rss?{BASE_GN}"]},
    {"id": "politica", "nome": "Política", "dias": 2, "max": 12,
     "relevante": None, "bloqueio": EXCLUI_GRAFICO,
     "feeds": [busca("política OR Congresso OR Planalto OR STF", 2)]},
    {"id": "entretenimento", "nome": "Entretenimento", "dias": 3, "max": 12,
     "relevante": None, "bloqueio": EXCLUI_GRAFICO,
     "feeds": [f"https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?{BASE_GN}"]},
]

MAX_TICKER = 12


# ----------------------------------------------------------------------------
# Funções
# ----------------------------------------------------------------------------

def normalizar(txt):
    txt = unicodedata.normalize("NFKD", txt or "")
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", txt.lower()).strip()


def sem_fonte(titulo):
    """Tira o ' - Nome da Fonte' do fim do título."""
    return re.sub(r"\s+[-–|]\s+[^-–|]+$", "", titulo or "").strip()


def baixar(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; GuiaAparecidaBot/1.0)"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def ler_feed(xml_bytes):
    """Devolve lista de dicts {texto, link, data(datetime UTC), fonte}."""
    itens = []
    raiz = ET.fromstring(xml_bytes)
    for item in raiz.iter("item"):
        titulo = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate")
        fonte_el = item.find("source")
        fonte = (fonte_el.text or "").strip() if fonte_el is not None and fonte_el.text else ""
        if not titulo or not link.startswith("http") or not pub:
            continue
        try:
            data = parsedate_to_datetime(pub)
            if data.tzinfo is None:
                data = data.replace(tzinfo=timezone.utc)
            data = data.astimezone(timezone.utc)
        except (TypeError, ValueError):
            continue
        itens.append({"texto": titulo, "link": link, "data": data, "fonte": fonte})
    return itens


def serve(item, limite, relevante, bloqueio, extra_bloqueio=()):
    if item["data"] < limite:
        return False
    t = normalizar(sem_fonte(item["texto"]))
    if relevante and not any(x in t for x in relevante):
        return False
    if any(x in t for x in EXCLUI_LOCAIS):
        return False
    if any(x in t for x in bloqueio) or any(x in t for x in extra_bloqueio):
        return False
    return True


def chave_titulo(item):
    return normalizar(sem_fonte(item["texto"]))[:60]


def escolher(itens, limite, relevante, bloqueio, maximo, extra_bloqueio=()):
    vistos, finais = set(), []
    for it in sorted((i for i in itens if serve(i, limite, relevante, bloqueio, extra_bloqueio)),
                     key=lambda i: i["data"], reverse=True):
        k = chave_titulo(it)
        if k in vistos:
            continue
        vistos.add(k)
        finais.append({"texto": it["texto"], "link": it["link"],
                       "data": it["data"].strftime("%Y-%m-%dT%H:%M:%SZ"), "fonte": it["fonte"]})
        if len(finais) >= maximo:
            break
    return finais


def coletar(cat):
    """Baixa os feeds de uma categoria. Devolve (itens_brutos, feeds_ok)."""
    brutos, ok = [], 0
    for url in cat["feeds"]:
        try:
            brutos.extend(ler_feed(baixar(url)))
            ok += 1
        except Exception as e:  # um feed fora do ar não derruba os outros
            print(f"[aviso] {cat['id']}: feed falhou ({type(e).__name__}: {e}) -> {url[:80]}", file=sys.stderr)
        time.sleep(1)
    return brutos, ok


def gravar_se_mudou(caminho, conteudo):
    antigo = caminho.read_text(encoding="utf-8") if caminho.exists() else ""
    if conteudo != antigo:
        caminho.write_text(conteudo, encoding="utf-8")


def carregar_aba_anterior():
    try:
        dados = json.loads(SAIDA_ABA.read_text(encoding="utf-8"))
        return {c["id"]: c for c in dados.get("categorias", [])}
    except Exception:
        return {}


def main():
    agora = datetime.now(timezone.utc)
    anterior = carregar_aba_anterior()
    saida_aba, ticker, ok_total = [], None, 0

    for cat in CATEGORIAS:
        brutos, ok = coletar(cat)
        ok_total += ok
        if ok == 0 and cat["id"] in anterior:
            print(f"[aviso] {cat['id']}: nenhum feed respondeu; mantendo os itens anteriores.")
            saida_aba.append(anterior[cat["id"]])
            continue
        limite = agora - timedelta(days=cat["dias"])
        itens = escolher(brutos, limite, cat["relevante"], cat["bloqueio"], cat["max"])
        saida_aba.append({"id": cat["id"], "nome": cat["nome"], "itens": itens})
        print(f"{cat['id']}: {ok}/{len(cat['feeds'])} feeds | {len(brutos)} lidas | {len(itens)} na aba")

        if cat["id"] == "aparecida":
            ticker = escolher(brutos, limite, cat["relevante"], cat["bloqueio"], MAX_TICKER,
                              extra_bloqueio=EXCLUI_ECLESIASTICO)
            print(f"ticker: {len(ticker)} notícias")

    if ok_total == 0:
        print("Nenhum feed respondeu; mantendo os arquivos atuais.")
        return 0

    if ticker is not None:
        gravar_se_mudou(SAIDA_TICKER, json.dumps(ticker, ensure_ascii=False, indent=2) + "\n")
    gravar_se_mudou(SAIDA_ABA, json.dumps({"categorias": saida_aba}, ensure_ascii=False, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
