# Etapa 7 — indicadores e quadrantes

## KPIs da cidade (temporada out/2025–mar/2026)
- Chamados de manutenção de drenagem: 25.089
- Finalizados: 87,6% · mediana de 4,0 dias
- Backlog: pico de 6.286 em 25/03/2026; 5.256 no fim da temporada
- Dívida de drenagem da cidade (véspera de chuva ≥ 20 mm): 2,81 pendentes por 10 mil hab.
- Zona vermelha: 22 distritos, 1.664.891 moradores (333.072 com 60+)
- Taxa de pendência média dos distritos (véspera de chuva forte): 28,6%

## Quadrantes (sujeira = taxa_pendencia) — USADOS NO MODELO

| Quadrante | Distritos | População | Ocorrências DC (jan–mar) | Ocorr./10 mil hab. (média) | Tempo mediano (dias) |
|---|---|---|---|---|---|
| zona vermelha | 22 | 1.664.891 | 21 | 0,08 | 6,8 |
| zeladoria | 27 | 3.821.247 | 155 | 0,33 | 7,5 |
| estrutural | 24 | 2.308.333 | 144 | 0,44 | 3,0 |
| fora do modelo | 23 | 3.561.185 | 89 | 0,32 | 4,0 |

## Comparação: quadrantes se a sujeira fosse divida_10mil_hab

| Quadrante | Distritos | População | Ocorrências DC (jan–mar) | Ocorr./10 mil hab. (média) | Tempo mediano (dias) |
|---|---|---|---|---|---|
| zona vermelha | 30 | 2.128.760 | 36 | 0,13 | 6,0 |
| zeladoria | 19 | 2.160.845 | 90 | 0,41 | 7,5 |
| estrutural | 16 | 1.844.464 | 129 | 0,53 | 4,0 |
| fora do modelo | 31 | 5.221.587 | 154 | 0,27 | 4,0 |

- Distritos da subprefeitura Sé na zona vermelha: 5 (com divida_10mil_hab: 5) de 8

## Validação (correlação de Spearman entre distritos)

- taxa de pendência × ocorrências por km²: **0,01**
- taxa de pendência × ocorrências por 10 mil hab.: **-0,06**
- dívida de drenagem × ocorrências por km²: **-0,21**
- dívida de drenagem × ocorrências por 10 mil hab.: **-0,22**
- chamados por 10 mil hab. × ocorrências por 10 mil hab.: **-0,23**
- índice de propensão × ocorrências por km²: **-0,17**
  (0 = nenhuma relação; acima de ~0,3 já indica relação; negativo = relação inversa)

## Zona vermelha — lista priorizada (top 15)

| # | Distrito | Propensão | Sujeira | Pendência (%) | Dívida (pend./10 mil hab.) | Tempo mediano (dias) | Ocorr. DC |
|---|---|---|---|---|---|---|---|
| 1 | BOM RETIRO | 80.5 | 95.8 | 59.6 | 16.05 | 2.0 | 0 |
| 2 | CAMBUCI | 78.1 | 93.8 | 55.0 | 6.95 | 7.0 | 0 |
| 3 | SANTA CECILIA | 64.3 | 96.9 | 62.5 | 10.86 | 10.0 | 1 |
| 4 | ITAIM BIBI | 71.6 | 79.7 | 35.4 | 5.83 | 6.0 | 1 |
| 5 | PINHEIROS | 67.3 | 82.3 | 36.5 | 6.65 | 7.0 | 0 |
| 6 | SE | 54.9 | 94.8 | 59.4 | 16.1 | 2.5 | 0 |
| 7 | LIBERDADE | 54.6 | 92.7 | 52.5 | 7.04 | 12.0 | 0 |
| 8 | VILA LEOPOLDINA | 82.0 | 62.5 | 27.7 | 3.51 | 7.0 | 0 |
| 9 | VILA MEDEIROS | 63.2 | 75.0 | 34.1 | 3.7 | 4.0 | 1 |
| 10 | VILA GUILHERME | 70.6 | 66.7 | 29.4 | 4.63 | 8.0 | 0 |
| 11 | ERMELINO MATARAZZO | 50.5 | 85.9 | 37.5 | 1.93 | 9.5 | 6 |
| 12 | BARRA FUNDA | 79.4 | 54.2 | 26.0 | 4.79 | 8.0 | 0 |
| 13 | CANGAIBA | 61.7 | 69.8 | 30.5 | 1.91 | 6.0 | 1 |
| 14 | LAPA | 79.8 | 51.6 | 25.5 | 3.09 | 6.0 | 0 |
| 15 | PENHA | 60.4 | 70.8 | 30.9 | 3.17 | 6.0 | 2 |

## Subnotificação — onde se alaga e não se reclama (top 10, jan–mar/2026)

- MARSILAC: 3 ocorrências DC × 13 chamados (índice 0.214)
- ITAIM PAULISTA: 51 ocorrências DC × 293 chamados (índice 0.173)
- CAPAO REDONDO: 53 ocorrências DC × 344 chamados (índice 0.154)
- JARDIM HELENA: 51 ocorrências DC × 354 chamados (índice 0.144)
- PARELHEIROS: 15 ocorrências DC × 144 chamados (índice 0.103)
- SAO LUCAS: 13 ocorrências DC × 130 chamados (índice 0.099)
- ERMELINO MATARAZZO: 6 ocorrências DC × 69 chamados (índice 0.086)
- JARDIM SAO LUIS: 17 ocorrências DC × 213 chamados (índice 0.079)
- JABAQUARA: 20 ocorrências DC × 253 chamados (índice 0.079)
- CURSINO: 11 ocorrências DC × 154 chamados (índice 0.071)