# Etapa 5 — índice de propensão

## Conferências
- Distritos com relevo calculado: 96 de 96 (mínimo de 2516 pixels por distrito)
- Pixels da cidade sem dado no TOPODATA: 0.06%
- Trechos de córrego usados: 25.952
- Distritos sem índice: 0

## Validação com a Defesa Civil (2026)
- Ocorrências de alagamento + inundação: 586, em 72 distritos
- Correlação de Spearman (índice × ocorrências por km²): **-0.09** (0 = nenhuma relação; 1 = mesma ordem; acima de ~0,3 já indica relação)
- Índice médio dos distritos COM ocorrência: 47.9 · SEM ocorrência: 58.5

## 10 distritos mais propensos

| Distrito | Índice | Declividade média (%) | Área plana (%) | Altitude (m) | Perto de córrego (%) |
|---|---|---|---|---|---|
| JARDIM HELENA | 92.6 | 3.25 | 28.59 | 736.4 | 85.37 |
| VILA LEOPOLDINA | 82.0 | 5.22 | 9.14 | 733.3 | 73.74 |
| BOM RETIRO | 80.5 | 4.8 | 9.28 | 732.9 | 70.8 |
| LAPA | 79.8 | 7.23 | 6.65 | 746.8 | 85.36 |
| BARRA FUNDA | 79.4 | 5.32 | 7.58 | 731.3 | 71.49 |
| CAMBUCI | 78.1 | 6.84 | 6.32 | 748.9 | 83.07 |
| PARI | 74.2 | 4.15 | 12.68 | 730.3 | 18.33 |
| BRAS | 73.7 | 4.08 | 14.33 | 736.2 | 12.57 |
| ITAIM BIBI | 71.6 | 6.68 | 8.18 | 737.2 | 61.7 |
| BELEM | 70.7 | 4.87 | 9.75 | 740.1 | 24.75 |

## Diagnóstico: correlação de cada variável com as ocorrências

(sinal + = quanto maior a variável, mais ocorrências)

| Variável | por km² | por 10 mil hab. | total |
|---|---|---|---|
| indice_propensao | -0.09 | -0.10 | -0.22 |
| pct_area_plana | +0.01 | -0.01 | -0.09 |
| declividade_media_pct | +0.08 | +0.16 | +0.26 |
| altitude_media_m | +0.12 | +0.12 | +0.26 |
| pct_area_perto_corrego | +0.02 | +0.09 | +0.14 |
| densidade_corregos_km_km2 | -0.00 | +0.09 | +0.12 |
| amplitude_altitude_m | -0.09 | +0.01 | +0.11 |
| densidade_hab_km2 | +0.36 | +0.07 | +0.17 |

## 5 menos propensos

- BELA VISTA: 26.3
- CONSOLACAO: 25.5
- VILA ANDRADE: 22.9
- JARAGUA: 19.0
- PERUS: 17.7