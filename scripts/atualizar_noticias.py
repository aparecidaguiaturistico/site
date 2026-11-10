#!/usr/bin/env python3
"""
Coletor de notícias de Aparecida (SP) para o ticker do site.

Roda no GitHub Actions (a cada poucas horas), busca feeds RSS, filtra o que
interessa para quem visita Aparecida e grava `noticias.json` na raiz do repositório.
Só usa a biblioteca padrão do Python (nada para instalar).

Para ajustar o que entra no ticker, edite as listas FEEDS, EXCLUI_TEMAS e
EXCLUI_LOCAIS logo abaixo.
"""
import json
import re
import sys
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

SAIDA = Path(__file__).resolve().parent.parent / "noticias.json"
DIAS_MAX = 10      # ignora notícias mais antigas que isso
MAX_ITENS = 12     # quantas notícias ficam no arquivo


def google_news(busca):
    params = {"q": f"{busca} when:{DIAS_MAX}d", "hl": "pt-BR", "gl": "BR", "ceid": "BR:pt-419"}
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode(params)


# Fontes. Para acrescentar um site que tenha RSS, é só colar o endereço do feed aqui.
FEEDS = [
    google_news('"Santuário Nacional" Aparecida'),
    google_news('"Basílica de Aparecida"'),
    google_news('"Aparecida (SP)" turismo OR romeiros OR evento OR festa'),
    google_news("Prefeitura de Aparecida SP"),
]

# Cidades/assuntos homônimos que não têm a ver com Aparecida (SP)
EXCLUI_LOCAIS = ["aparecida de goiania", "goiania", "aparecida do taboado", "aparecida d'oeste",
                 "aparecida do rio negro", "aparecida de minas"]

# O título precisa ter pelo menos uma destas expressões (já sem acento e em minúsculas)
RELEVANTE = ["aparecida", "santuario nacional", "romeiro", "padroeira"]

# Temas que não combinam com um guia turístico (crimes, mortes, acidentes...)
EXCLUI_TEMAS = ["assassin", "homicid", "morto", "morre", "morreu", "morte", "preso", "presa", "presos",
                "policia", "policial", "tiroteio", "roubo", "furto", "estupro", "trafico", "acidente",
                "atropel", "afogad", "suicid", "corpo", "esfaquead", "baleado", "tiros", "velorio",
                "luto", "sequestr", "golpe", "prisao", "feminicid", "cadaver", "overdose"]


def normalizar(txt):
    txt = unicodedata.normalize("NFKD", txt or "")
    txt = "".join(c for c in txt if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", txt.lower()).strip()


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


def serve(item, limite):
    if item["data"] < limite:
        return False
    t = normalizar(item["texto"])
    if not any(x in t for x in RELEVANTE):
        return False
    if any(x in t for x in EXCLUI_LOCAIS):
        return False
    if any(x in t for x in EXCLUI_TEMAS):
        return False
    return True


def chave_titulo(item):
    # Remove o " - Fonte" do fim e compara só o começo, para juntar a mesma matéria vinda de feeds diferentes
    base = re.sub(r"\s+[-–|]\s+[^-–|]+$", "", item["texto"])
    return normalizar(base)[:60]


def main():
    limite = datetime.now(timezone.utc) - timedelta(days=DIAS_MAX)
    todos, feeds_ok = [], 0
    for url in FEEDS:
        try:
            todos.extend(ler_feed(baixar(url)))
            feeds_ok += 1
        except Exception as e:  # um feed fora do ar não derruba os outros
            print(f"[aviso] feed falhou ({type(e).__name__}: {e}) -> {url[:90]}", file=sys.stderr)

    if feeds_ok == 0:
        print("Nenhum feed respondeu; mantendo o noticias.json atual.")
        return 0

    vistos, finais = set(), []
    for it in sorted((i for i in todos if serve(i, limite)), key=lambda i: i["data"], reverse=True):
        k = chave_titulo(it)
        if k in vistos:
            continue
        vistos.add(k)
        finais.append({"texto": it["texto"], "link": it["link"],
                       "data": it["data"].strftime("%Y-%m-%dT%H:%M:%SZ"), "fonte": it["fonte"]})
        if len(finais) >= MAX_ITENS:
            break

    novo = json.dumps(finais, ensure_ascii=False, indent=2) + "\n"
    antigo = SAIDA.read_text(encoding="utf-8") if SAIDA.exists() else ""
    if novo != antigo:
        SAIDA.write_text(novo, encoding="utf-8")
    print(f"{feeds_ok}/{len(FEEDS)} feeds ok | {len(todos)} lidas | {len(finais)} publicadas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
