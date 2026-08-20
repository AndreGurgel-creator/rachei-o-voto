"""
ETL — Rachei o Voto
Baixa os dados oficiais do TSE (Portal de Dados Abertos), processa e
gera um JSON leve por UF em /data/candidatos/{UF}.json, pronto pro
app consumir via fetch().

Fontes oficiais:
- Candidatos:          https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip
- Patrimônio (bens):   https://cdn.tse.jus.br/estatistica/sead/odsele/bem_candidato/bem_candidato_2026.zip
- Fotos (por UF):      https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes2026/fotos/foto_cand2026_{UF}_div.zip
- Prestação de contas: portal DivulgaCandContas (endpoint consultado à parte, ver seção final)

ATENÇÃO — bloqueio de IP: o TSE bloqueia (HTTP 403) requisições vindas
de IPs de datacenter/cloud, o que inclui os runners padrão do GitHub
Actions. Este script precisa rodar num runner self-hosted (computador
com IP residencial) — ver .github/workflows/update-data.yml.

IMPORTANTE: os CSVs do TSE vêm em encoding latin-1 (cp1252) e
separador ';'. Sempre confirmar o layout exato no arquivo leiame
que acompanha cada ZIP — o TSE pode ajustar nomes de coluna entre
atualizações.
"""

import csv
import io
import json
import os
import zipfile
from collections import defaultdict
from urllib.request import urlopen, Request

ANO = 2026
URL_CANDIDATOS = f"https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_{ANO}.zip"
URL_BENS = f"https://cdn.tse.jus.br/estatistica/sead/odsele/bem_candidato/bem_candidato_{ANO}.zip"
URL_FOTO_UF = f"https://cdn.tse.jus.br/estatistica/sead/eleicoes/eleicoes{ANO}/fotos/foto_cand{ANO}_{{uf}}_div.zip"

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "candidatos")
FOTOS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "fotos")

TODAS_UFS = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
    "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}

CARGOS_ELEICAO_GERAL = {
    "PRESIDENTE", "VICE-PRESIDENTE", "GOVERNADOR", "VICE-GOVERNADOR",
    "SENADOR", "1º SUPLENTE", "2º SUPLENTE",
    "DEPUTADO FEDERAL", "DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL",
}
CARGOS_ELEICAO_MUNICIPAL = {"PREFEITO", "VICE-PREFEITO", "VEREADOR"}

CARGOS_POR_TIPO_ELEICAO = {
    "geral": CARGOS_ELEICAO_GERAL,
    "municipal": CARGOS_ELEICAO_MUNICIPAL,
}
ANOS_ELEICAO_MUNICIPAL = {2020, 2024, 2028, 2032}
TIPO_ELEICAO_ANO = "municipal" if ANO in ANOS_ELEICAO_MUNICIPAL else "geral"
CARGOS_VALIDOS = CARGOS_POR_TIPO_ELEICAO[TIPO_ELEICAO_ANO]


def normalizar_cpf(valor: str) -> str:
    apenas_digitos = "".join(ch for ch in (valor or "") if ch.isdigit())
    return apenas_digitos.zfill(11) if apenas_digitos else ""


def baixar_zip(url: str) -> zipfile.ZipFile:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req) as resp:
        buf = io.BytesIO(resp.read())
    return zipfile.ZipFile(buf)


def ler_csv_do_zip(zf: zipfile.ZipFile, sufixo: str = ".csv"):
    nomes = [n for n in zf.namelist() if n.lower().endswith(sufixo)]
    for nome in nomes:
        with zf.open(nome) as f:
            wrapper = io.TextIOWrapper(f, encoding="latin-1", newline="")
            reader = csv.DictReader(wrapper, delimiter=";")
            for row in reader:
                yield row


def processar_candidatos():
    print("Baixando consulta_cand_2026.zip...")
    zf = baixar_zip(URL_CANDIDATOS)

    por_uf = defaultdict(list)
    for row in ler_csv_do_zip(zf):
        cargo = row.get("DS_CARGO", "").strip().upper()
        if cargo not in CARGOS_VALIDOS:
            continue

        uf = row.get("SG_UF", "").strip()
        if not uf:
            continue

        candidato = {
            "cpf": normalizar_cpf(row.get("NR_CPF_CANDIDATO", "")),
            "sqCandidato": row.get("SQ_CANDIDATO", "").strip(),
            "nomeUrna": row.get("NM_URNA_CANDIDATO", "").strip(),
            "nomeCompleto": row.get("NM_CANDIDATO", "").strip(),
            "numero": row.get("NR_CANDIDATO", "").strip(),
            "partido": row.get("SG_PARTIDO", "").strip(),
            "cargo": cargo.title(),
            "situacao": row.get("DS_SITUACAO_CANDIDATURA", "").strip(),
            "municipio": row.get("NM_MUNICIPIO", "").strip(),
            "coligacao": row.get("NM_FEDERACAO", "").strip() or row.get("DS_COMPOSICAO_COLIGACAO", "").strip(),
            "patrimonio": None,
            "arrecadacao": None,
            "gastos": None,
            "doadores": None,
            "fotoUrl": None,
        }
        por_uf[uf].append(candidato)

    return por_uf


def processar_bens(por_uf):
    print("Baixando bem_candidato_2026.zip...")
    zf = baixar_zip(URL_BENS)

    soma_por_sq = defaultdict(float)
    linhas_lidas = 0
    amostra = []
    for row in ler_csv_do_zip(zf):
        linhas_lidas += 1
        sq = row.get("SQ_CANDIDATO", "").strip()
        valor_str = row.get("VR_BEM_CANDIDATO", "0").replace(",", ".")
        try:
            valor = float(valor_str)
        except ValueError:
            valor = 0.0
        soma_por_sq[sq] += valor
        if len(amostra) < 5:
            amostra.append((sq, valor_str, row.get("DS_BEM_CANDIDATO", "")))

    if linhas_lidas == 0:
        print("  aviso: bem_candidato_2026.zip não retornou nenhuma linha — "
              "confirme se o dataset já está publicado para 2026.")
    else:
        print(f"  diagnóstico: {linhas_lidas} linhas lidas de bens. Amostra:")
        for sq, valor_str, desc in amostra:
            print(f"    SQ_CANDIDATO={sq!r}  valor={valor_str!r}  bem={desc!r}")
        sq_exemplo_candidato = None
        for uf, candidatos in por_uf.items():
            if candidatos:
                sq_exemplo_candidato = candidatos[0]["sqCandidato"]
                break
        print(f"  diagnóstico: SQ_CANDIDATO de exemplo em consulta_cand: {sq_exemplo_candidato!r}")

    for uf, candidatos in por_uf.items():
        for c in candidatos:
            c["patrimonio"] = round(soma_por_sq.get(c["sqCandidato"], 0.0), 2)

    return por_uf


def processar_fotos(por_uf, ufs=None):
    os.makedirs(FOTOS_DIR, exist_ok=True)
    alvo = ufs if ufs else por_uf.keys()

    for uf in alvo:
        if uf not in por_uf:
            continue
        url = URL_FOTO_UF.format(uf=uf)
        print(f"Baixando fotos de {uf}...")
        try:
            zf = baixar_zip(url)
        except Exception as e:
            print(f"  aviso: não consegui baixar fotos de {uf} ({e}) — pulando.")
            continue

        arquivos_por_stem = {}
        for nome in zf.namelist():
            if nome.lower().endswith((".jpg", ".jpeg", ".png")):
                stem = os.path.splitext(os.path.basename(nome))[0]
                arquivos_por_stem[stem] = nome

        pasta_uf = os.path.join(FOTOS_DIR, uf)
        os.makedirs(pasta_uf, exist_ok=True)

        encontrados = 0
        for c in por_uf[uf]:
            sq = c.get("sqCandidato", "")
            nome_no_zip = arquivos_por_stem.get(sq)
            if not nome_no_zip:
                continue
            ext = os.path.splitext(nome_no_zip)[1].lower()
            destino = os.path.join(pasta_uf, f"{sq}{ext}")
            with zf.open(nome_no_zip) as origem, open(destino, "wb") as saida:
                saida.write(origem.read())
            c["fotoUrl"] = f"data/fotos/{uf}/{sq}{ext}"
            encontrados += 1

        print(f"  {uf}: {encontrados}/{len(por_uf[uf])} fotos associadas")

    return por_uf


def processar_prestacao_contas(por_uf):
    return por_uf


def salvar(por_uf):
    os.makedirs(OUT_DIR, exist_ok=True)
    for uf, candidatos in por_uf.items():
        path = os.path.join(OUT_DIR, f"{uf}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(
                {"uf": uf, "atualizadoEm": None, "candidatos": candidatos},
                f, ensure_ascii=False, indent=None
            )
        print(f"  {uf}: {len(candidatos)} candidatos -> {path}")


if __name__ == "__main__":
    import sys

    dados = processar_candidatos()
    dados = processar_bens(dados)

    if "--fotos" in sys.argv:
        idx = sys.argv.index("--fotos")
        arg = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "todas"
        ufs = None if arg == "todas" else [u.strip().upper() for u in arg.split(",")]
        dados = processar_fotos(dados, ufs=ufs)

    dados = processar_prestacao_contas(dados)
    salvar(dados)
    print("Concluído.")
