"""
ETL — Rachei o Voto
Baixa os dados oficiais do TSE (Portal de Dados Abertos), processa e
gera um JSON leve por UF em /data/candidatos/{UF}.json, pronto pro
app consumir via fetch().

Fontes oficiais:
- Candidatos:        https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2026.zip
- Patrimônio (bens):  https://cdn.tse.jus.br/estatistica/sead/odsele/bem_candidato/bem_candidato_2026.zip
- Prestação de contas: portal DivulgaCandContas (endpoint consultado à parte, ver seção final)

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

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "candidatos")

# Cargos que existem na eleição geral de 2026 (sem vereador/prefeito —
# esses só voltam em 2028, eleição municipal). Deixe mapeado agora
# pra não precisar mexer no ETL quando a próxima eleição chegar.
CARGOS_ELEICAO_GERAL = {
    "PRESIDENTE", "VICE-PRESIDENTE", "GOVERNADOR", "VICE-GOVERNADOR",
    "SENADOR", "1º SUPLENTE", "2º SUPLENTE",
    "DEPUTADO FEDERAL", "DEPUTADO ESTADUAL", "DEPUTADO DISTRITAL",
}
CARGOS_ELEICAO_MUNICIPAL = {"PREFEITO", "VICE-PREFEITO", "VEREADOR"}

# Define qual conjunto vale para o ANO configurado acima. 2026 é
# eleição geral -> só CARGOS_ELEICAO_GERAL entra. Quando 2028 (eleição
# municipal) chegar, troca ANO pra 2028 e este mapa já resolve sozinho
# qual filtro usar — não precisa mexer no resto do script.
CARGOS_POR_TIPO_ELEICAO = {
    "geral": CARGOS_ELEICAO_GERAL,
    "municipal": CARGOS_ELEICAO_MUNICIPAL,
}
ANOS_ELEICAO_MUNICIPAL = {2020, 2024, 2028, 2032}
TIPO_ELEICAO_ANO = "municipal" if ANO in ANOS_ELEICAO_MUNICIPAL else "geral"
CARGOS_VALIDOS = CARGOS_POR_TIPO_ELEICAO[TIPO_ELEICAO_ANO]


def baixar_zip(url: str) -> zipfile.ZipFile:
    req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(req) as resp:
        buf = io.BytesIO(resp.read())
    return zipfile.ZipFile(buf)


def ler_csv_do_zip(zf: zipfile.ZipFile, sufixo: str = ".csv"):
    """Lê o primeiro CSV do zip (ou o único), tratando encoding/; do TSE."""
    nomes = [n for n in zf.namelist() if n.lower().endswith(sufixo)]
    for nome in nomes:
        with zf.open(nome) as f:
            wrapper = io.TextIOWrapper(f, encoding="latin-1", newline="")
            reader = csv.DictReader(wrapper, delimiter=";")
            for row in reader:
                yield row


def processar_candidatos():
    """
    Baixa consulta_cand_2026.zip e monta um dict {UF: [candidatos]}.
    Campos principais confirmados no leiaute oficial do TSE:
    SG_UF, NR_CANDIDATO, NM_URNA_CANDIDATO, NM_CANDIDATO, SG_PARTIDO,
    DS_CARGO, DS_SITUACAO_CANDIDATURA, NR_CPF_CANDIDATO, NM_MUNICIPIO,
    NR_TURNO, DS_COMPOSICAO_COLIGACAO / NM_FEDERACAO.
    """
    print("Baixando consulta_cand_2026.zip...")
    zf = baixar_zip(URL_CANDIDATOS)

    por_uf = defaultdict(list)
    for row in ler_csv_do_zip(zf):
        cargo = row.get("DS_CARGO", "").strip().upper()
        # Filtra pelo tipo de eleição do ANO configurado (geral ou
        # municipal) — evita vazar cargo que não existe neste pleito.
        if cargo not in CARGOS_VALIDOS:
            continue

        uf = row.get("SG_UF", "").strip()
        if not uf:
            continue

        candidato = {
            "cpf": row.get("NR_CPF_CANDIDATO", "").strip(),
            "nomeUrna": row.get("NM_URNA_CANDIDATO", "").strip(),
            "nomeCompleto": row.get("NM_CANDIDATO", "").strip(),
            "numero": row.get("NR_CANDIDATO", "").strip(),
            "partido": row.get("SG_PARTIDO", "").strip(),
            "cargo": cargo.title(),
            "situacao": row.get("DS_SITUACAO_CANDIDATURA", "").strip(),
            "municipio": row.get("NM_MUNICIPIO", "").strip(),
            "coligacao": row.get("NM_FEDERACAO", "").strip() or row.get("DS_COMPOSICAO_COLIGACAO", "").strip(),
            # preenchidos depois, no cruzamento com bens/prestação de contas
            "patrimonio": None,
            "arrecadacao": None,
            "gastos": None,
            "doadores": None,
            # foto: monta o padrão de URL, mas confirma existência depois
            "fotoUrl": None,
        }
        por_uf[uf].append(candidato)

    return por_uf


def processar_bens(por_uf):
    """Cruza patrimônio declarado pelo CPF do candidato."""
    print("Baixando bem_candidato_2026.zip...")
    zf = baixar_zip(URL_BENS)

    soma_por_cpf = defaultdict(float)
    for row in ler_csv_do_zip(zf):
        cpf = row.get("NR_CPF_CANDIDATO", "").strip()
        valor_str = row.get("VR_BEM_CANDIDATO", "0").replace(",", ".")
        try:
            valor = float(valor_str)
        except ValueError:
            valor = 0.0
        soma_por_cpf[cpf] += valor

    for uf, candidatos in por_uf.items():
        for c in candidatos:
            c["patrimonio"] = round(soma_por_cpf.get(c["cpf"], 0.0), 2)

    return por_uf


def processar_prestacao_contas(por_uf):
    """
    Arrecadação, gastos e nº de doadores vêm da prestação de contas,
    disponibilizada no DivulgaCandContas. Requer endpoint/arquivo
    específico (varia conforme o corte de dados que o TSE publicar
    pro ano corrente) — implementar aqui seguindo o mesmo padrão dos
    dois métodos acima assim que o dataset estiver disponível para
    2026. Por enquanto, deixa como None (o app trata null como
    "ainda não disponível").
    """
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
    dados = processar_candidatos()
    dados = processar_bens(dados)
    dados = processar_prestacao_contas(dados)
    salvar(dados)
    print("Concluído.")
