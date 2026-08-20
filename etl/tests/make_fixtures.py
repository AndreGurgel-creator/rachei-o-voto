"""Gera ZIPs de teste que imitam o formato real do TSE (mesmas colunas,
mesmo separador ';', mesmo encoding latin-1) pra validar o parser
sem depender de acesso à rede do TSE."""
import csv
import io
import zipfile
import os

OUT = os.path.join(os.path.dirname(__file__), "fixtures")
os.makedirs(OUT, exist_ok=True)

CAND_COLS = [
    "SG_UF","NR_CANDIDATO","NM_URNA_CANDIDATO","NM_CANDIDATO","SG_PARTIDO",
    "DS_CARGO","DS_SITUACAO_CANDIDATURA","NR_CPF_CANDIDATO","NM_MUNICIPIO",
    "NR_TURNO","NM_FEDERACAO","DS_COMPOSICAO_COLIGACAO"
]
CAND_ROWS = [
    ["RO","45123","ANA FERREIRA","ANA BEATRIZ FERREIRA","PARTIDO A","DEPUTADO FEDERAL","DEFERIDO","11111111111","PORTO VELHO","1","FEDERAÇÃO RENOVA",""],
    ["RO","13456","CARLOS MATOS","CARLOS EDUARDO MATOS","PARTIDO B","DEPUTADO FEDERAL","DEFERIDO","22222222222","ARIQUEMES","1","",""],
    ["RO","77021","JU PASSOS","JULIANA PASSOS LIMA","PARTIDO C","DEPUTADO ESTADUAL","DEFERIDO","33333333333","PORTO VELHO","1","FEDERAÇÃO FRENTE AMPLA",""],
    ["RO","22890","PAULO ROCHA","PAULO ROCHA SILVA","PARTIDO D","VEREADOR","DEFERIDO","44444444444","ARIQUEMES","1","",""],  # cargo municipal - deve ser filtrado em 2026
    ["SP","13010","MARIA SOUZA","MARIA SOUZA COSTA","PARTIDO B","DEPUTADO FEDERAL","DEFERIDO","55555555555","SAO PAULO","1","",""],
    ["RO","99999","JOAO SEM PATRIMONIO","JOAO SILVA","PARTIDO E","GOVERNADOR","INDEFERIDO","66666666666","PORTO VELHO","1","",""],
]

BENS_COLS = ["NR_CPF_CANDIDATO","VR_BEM_CANDIDATO","DS_BEM_CANDIDATO"]
BENS_ROWS = [
    ["11111111111","500000,00","Apartamento"],
    ["11111111111","350000,00","Veiculo"],
    ["22222222222","2100000,00","Fazenda"],
    ["33333333333","410000,00","Casa"],
    ["55555555555","1450000,00","Imoveis diversos"],
    # candidato 44444444444 (vereador) e 66666666666 (sem bens) propositalmente sem entrada
]

def write_zip(path, cols, rows):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(cols)
    w.writerows(rows)
    data = buf.getvalue().encode("latin-1")
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("dados.csv", data)

write_zip(os.path.join(OUT, "consulta_cand_2026.zip"), CAND_COLS, CAND_ROWS)
write_zip(os.path.join(OUT, "bem_candidato_2026.zip"), BENS_COLS, BENS_ROWS)
print("Fixtures geradas em", OUT)
