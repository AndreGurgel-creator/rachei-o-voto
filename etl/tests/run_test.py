"""Roda o pipeline real do build_data.py contra as fixtures locais,
sem tocar na rede — valida parsing, filtro de cargos e cruzamento
por CPF."""
import sys, os, json, zipfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import build_data as bd

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

# Substitui a função de download por leitura local
def fake_baixar_zip(url):
    if "consulta_cand" in url:
        return zipfile.ZipFile(os.path.join(FIX, "consulta_cand_2026.zip"))
    if "bem_candidato" in url:
        return zipfile.ZipFile(os.path.join(FIX, "bem_candidato_2026.zip"))
    raise ValueError("URL inesperada: " + url)

bd.baixar_zip = fake_baixar_zip
bd.OUT_DIR = os.path.join(os.path.dirname(__file__), "out_test")

dados = bd.processar_candidatos()
dados = bd.processar_bens(dados)
dados = bd.processar_prestacao_contas(dados)
bd.salvar(dados)

print("\n--- VALIDAÇÕES ---")
errors = []

# 1. Vereador (cargo municipal) não deve aparecer na eleição geral 2026
ro = dados.get("RO", [])
nomes_ro = [c["nomeUrna"] for c in ro]
if "PAULO ROCHA" in nomes_ro:
    errors.append("FALHA: candidato a Vereador (municipal) vazou pro filtro de 2026")
else:
    print("OK: cargo municipal (Vereador) corretamente filtrado fora de 2026")

# 2. Cruzamento de patrimônio por CPF (soma de múltiplos bens)
ana = next((c for c in ro if c["numero"] == "45123"), None)
if ana and ana["patrimonio"] == 850000.0:
    print(f"OK: patrimônio da Ana somado corretamente (500000 + 350000 = {ana['patrimonio']})")
else:
    errors.append(f"FALHA: patrimônio da Ana incorreto -> {ana['patrimonio'] if ana else 'candidato não encontrado'}")

# 3. Candidato sem patrimônio declarado deve ficar com 0, não quebrar
joao = next((c for c in ro if c["numero"] == "99999"), None)
if joao and joao["patrimonio"] == 0:
    print("OK: candidato sem bens declarados tratado como 0 (não quebrou)")
else:
    errors.append(f"FALHA: candidato sem bens não tratado corretamente -> {joao}")

# 4. Separação correta por UF
if set(dados.keys()) == {"RO", "SP"}:
    print("OK: candidatos separados corretamente por UF (RO, SP)")
else:
    errors.append(f"FALHA: UFs inesperadas -> {list(dados.keys())}")

# 5. Situação INDEFERIDO deve ser preservada (não filtrada, só marcada)
if joao and joao["situacao"] == "INDEFERIDO":
    print("OK: situação de candidatura (INDEFERIDO) preservada no dado")
else:
    errors.append("FALHA: situação de candidatura não preservada")

# 6. JSON final é válido e carregável
out_path = os.path.join(bd.OUT_DIR, "RO.json")
with open(out_path, encoding="utf-8") as f:
    parsed = json.load(f)
if parsed["uf"] == "RO" and len(parsed["candidatos"]) == 4:
    print(f"OK: RO.json válido com {len(parsed['candidatos'])} candidatos (Vereador excluído)")
else:
    errors.append(f"FALHA: RO.json inesperado -> {parsed}")

print("\n--- RESULTADO ---")
if errors:
    print(f"{len(errors)} problema(s) encontrado(s):")
    for e in errors:
        print(" -", e)
    sys.exit(1)
else:
    print("Todos os testes passaram.")
