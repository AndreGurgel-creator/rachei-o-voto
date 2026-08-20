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

# UFs válidas do Brasil — usado só pra saber quais ZIPs de foto buscar
# (o TSE publica um ZIP de foto por UF, não um nacional único).
TODAS_UFS = {
    "AC","AL","AP","AM","BA","CE","DF","ES","GO","MA","MT","MS","MG",
    "PA","PB","PR","PE","PI","RJ","RN","RS","RO","RR","SC","SP","SE","TO"
}

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


def normalizar_cpf(valor: str) -> str:
    """CPF só com dígitos, sem pontuação e sem zeros à esquerda
    perdidos — necessário porque consulta_cand e bem_candidato podem
    representar o mesmo CPF com formatação ligeiramente diferente
    entre os dois arquivos do TSE."""
    apenas_digitos = "".join(ch for ch in (valor or "") if ch.isdigit())
    return apenas_digitos.zfill(11) if apenas_digitos else ""


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
    """
    Cruza patrimônio declarado pelo SQ_CANDIDATO — não pelo CPF.
    O arquivo bem_candidato do TSE historicamente não traz o campo
    de CPF, só o sequencial do candidato (mesma chave usada nas
    fotos). Cruzar por CPF aqui sempre resultava em zero para todo
    mundo, porque o campo nem existe nesse arquivo.
    """
    print("Baixando bem_candidato_2026.zip...")
    zf = baixar_zip(URL_BENS)

    soma_por_sq = defaultdict(float)
    linhas_lidas = 0
    for row in ler_csv_do_zip(zf):
        linhas_lidas += 1
        sq = row.get("SQ_CANDIDATO", "").strip()
        valor_str = row.get("VR_BEM_CANDIDATO", "0").replace(",", ".")
        try:
            valor = float(valor_str)
        except ValueError:
            valor = 0.0
        soma_por_sq[sq] += valor

    if linhas_lidas == 0:
        print("  aviso: bem_candidato_2026.zip não retornou nenhuma linha — "
              "confirme se o dataset já está publicado para 2026.")

    for uf, candidatos in por_uf.items():
        for c in candidatos:
            c["patrimonio"] = round(soma_por_sq.get(c["sqCandidato"], 0.0), 2)

    return por_uf


def processar_fotos(por_uf, ufs=None):
    """
    Baixa o ZIP de fotos de cada UF (um ZIP por estado, não existe um
    nacional único) e extrai as imagens pra data/fotos/{UF}/{sq}.jpg,
    cruzando pelo SQ_CANDIDATO (sequencial), que é a chave que o TSE
    usa pra nomear os arquivos dentro do ZIP.

    ufs: lista opcional pra processar só algumas UFs por vez (os ZIPs
    de foto de SP/MG etc. são grandes — rodar estado por estado evita
    um download gigante de uma vez só, principalmente na primeira
    carga completa).
    """
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
            # Uma UF falhar (ex: ainda sem fotos publicadas) não pode
            # derrubar o processamento das outras.
            print(f"  aviso: não consegui baixar fotos de {uf} ({e}) — pulando.")
            continue

        # Monta um lookup nome-do-arquivo-sem-extensão -> nome real
        # dentro do zip, pra casar com o SQ_CANDIDATO de cada candidato.
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
            # Caminho relativo que o app vai usar no fetch/img src.
            c["fotoUrl"] = f"data/fotos/{uf}/{sq}{ext}"
            encontrados += 1

        print(f"  {uf}: {encontrados}/{len(por_uf[uf])} fotos associadas")

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
    import sys

    dados = processar_candidatos()
    dados = processar_bens(dados)

    # Fotos: opcional via linha de comando, porque os ZIPs por UF somam
    # bastante peso — dá pra rodar aos poucos.
    # Ex.: python etl/build_data.py --fotos RO,SP
    #      python etl/build_data.py --fotos todas
    if "--fotos" in sys.argv:
        idx = sys.argv.index("--fotos")
        arg = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "todas"
        ufs = None if arg == "todas" else [u.strip().upper() for u in arg.split(",")]
        dados = processar_fotos(dados, ufs=ufs)

    dados = processar_prestacao_contas(dados)
    salvar(dados)
    print("Concluído.")
