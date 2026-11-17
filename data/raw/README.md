# Dados brutos

Os arquivos menores já estão aqui (Censo, limites do GeoSampa, ocorrências da Defesa Civil e INMET). Três fontes ficaram fora do repositório pelo tamanho; baixe-as e coloque nas pastas indicadas antes de rodar o pipeline.

| Pasta | O que baixar | Onde | Usado na etapa |
|---|---|---|---|
| `sp156/` | `arquivo-final-4-trim-25.csv` e `arquivo-final-1-trim-26.csv` (4º TRI 2025 e 1º TRI 2026), cerca de 230 MB | [Dados do SP156 — Portal de Dados Abertos](https://dados.prefeitura.sp.gov.br/dataset/dados-do-sp156) | 01 e 03 |
| `geosampa/` | Camada **Rede de Drenagem** (grupo Hidrografia), em shapefile, salva como `drenagem.shp` (com `.dbf`, `.shx`, `.prj`), cerca de 77 MB | [GeoSampa](https://novogeosampa.prefeitura.sp.gov.br/) | 05 |
| `relevo/` | Quatro folhas do TOPODATA (altitude e declividade) | Links em [`relevo/README.md`](relevo/README.md) | 05 |

Os CSVs do SP156 trazem número do imóvel e CEP dos chamados. O pipeline descarta esses campos (LGPD), e por isso eles não são republicados aqui.
