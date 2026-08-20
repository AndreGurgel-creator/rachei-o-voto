# Rachei o Voto — pipeline de dados reais

## Como funciona

1. `etl/build_data.py` baixa os arquivos oficiais do Portal de Dados
   Abertos do TSE, filtra e cruza os dados, e grava um JSON por UF em
   `data/candidatos/{UF}.json`.
2. `.github/workflows/update-data.yml` roda esse script automaticamente
   4x por dia (GitHub Actions, grátis) e commita o resultado no repositório.
3. O app (frontend) faz `fetch('data/candidatos/RO.json')` direto do
   GitHub Pages ou Vercel — sem servidor próprio, sem custo.

## Antes de rodar pela primeira vez

1. **Confirme o leiaute exato.** O TSE publica um "leiame" em PDF junto
   de cada ZIP com o nome de cada coluna daquele ano — os nomes usados
   no script (`NR_CPF_CANDIDATO`, `NM_URNA_CANDIDATO` etc.) são os
   documentados publicamente, mas vale checar antes do primeiro deploy:
   https://dadosabertos.tse.jus.br/dataset/candidatos-2026
2. **Prestação de contas (arrecadação/gastos/doadores)** ainda não está
   implementada no ETL — o dataset de contas de campanha 2026 precisa
   ser localizado e mapeado do mesmo jeito que patrimônio. Ver
   `processar_prestacao_contas()` no script.
3. **Fotos oficiais** vêm em ZIPs separados por UF
   (`foto_cand2026_{UF}_div.zip`). Ainda não incluído no script —
   é o próximo passo depois de validar candidatos + patrimônio.

## Rodando localmente

```bash
python etl/build_data.py
```

Gera os arquivos em `data/candidatos/`.

## Pendências conhecidas

- [ ] Mapear dataset de prestação de contas 2026
- [ ] Baixar e associar fotos oficiais por UF
- [ ] Definir cadência real de publicação (4x/dia bate com o TSE, mas
      pode ser ajustada no cron do workflow)
- [ ] Cargos municipais (prefeito/vice/vereador) já estão mapeados no
      script para 2028, mas o filtro está fechado só nos cargos de 2026
      até lá
