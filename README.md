# Rua Avisada — Data Warehouse

Global Solution 2026.2 · FIAP · Tecnólogo em Data Science · Turma 2TSCOR
Grupo **Welcome to the DataFrame**: Bruno Gomide (RM 567017), Leonardo Assunção Loiola Lacerda (RM 567864), Pedro Henrique dos Santos Freixo (RM 567189), Vitor Yamashita Coppe (RM 567390).

Data warehouse (modelo Snowflake) sobre chamados de drenagem do SP156, chuva do INMET, relevo, córregos e Censo 2022, nos 96 distritos de São Paulo, temporada de chuvas out/2025–mar/2026.

## Conteúdo

| Pasta / arquivo | O que é |
| --- | --- |
| `GS_2TSCOR_DW_RuaAvisada_WelcomeToTheDataFrame.pdf` | Documento ilustrado do DW (tema, fontes, modelo Snowflake, papel do DW, dashboard, documentação) |
| `data/raw/` | Dados brutos das fontes (SP156, INMET, GeoSampa, Censo/TabNet), **exceto o relevo do TOPODATA** (ver abaixo) |
| `data/staging/` | Arquivos intermediários e relatórios de cada etapa |
| `data/modelo/` | O DW em CSV: 2 fatos, 9 dimensões e 1 tabela agregada (UTF-8, separador vírgula) |
| `dashboard/painel_rua_avisada.ipynb` | Painel em notebook Python (plotly), 3 páginas |
| `dashboard/painel_rua_avisada.html` | O mesmo painel exportado em HTML interativo (abre no navegador, sem internet) |
| `scripts/` | Pipeline em Python, etapas 01 a 07 |
| `sql/rua_avisada_ddl_oracle.sql` | DDL Oracle do modelo: tabelas em maiúsculas, colunas com prefixo do tipo de dado (sk_, nm_, ds_, qt_, vl_, pc_, fl_...), IDENTITY nas chaves substitutas, PK, FK, CHECK e comentários em todas as tabelas e colunas (cada comentário indica a coluna correspondente no CSV) |
| `sql/modelo_relacional_oracle.pdf` | Modelo relacional gerado no Oracle SQL Developer Data Modeler a partir do DDL |

## Tabelas do modelo (`data/modelo/`)

- Fatos: `fato_solicitacao` (1 chamado de drenagem; no Oracle, `FTO_SOLICITACAO`) e `fato_distrito_dia` (1 distrito × 1 dia; no Oracle, `FTO_DISTRITO_DIA`).
- Dimensões: `dim_data` (no Oracle, `DIM_TEMPO`), `dim_status`, `dim_servico` → `dim_assunto` → `dim_tema`, `dim_distrito` → `dim_subprefeitura` → `dim_zona`, `dim_distrito` → `dim_estacao_inmet`.
- Agregada: `agg_indicadores_distrito` (indicadores e quadrante por distrito).

## Fora do pacote: relevo do TOPODATA

Os rasters de altitude (ZN) e declividade (SN) das folhas 23S48 e 23S465 ficaram fora do .zip pelo tamanho (GeoTIFF praticamente não diminui ao zipar). Só a etapa 05 usa esses arquivos, e o resultado dela já está em `data/modelo/dim_distrito.csv` e `data/staging/relevo_distritos.csv`: as etapas 06 e 07 e o painel rodam sem eles. Para refazer a etapa 05 (ou a 04, que regrava `dim_distrito.csv` sem o relevo), baixe as quatro folhas em https://data.inpe.br/bdc/stac/v1/collections/topodata-1 para `data/raw/relevo/`.

## Como reproduzir

Requisitos: Python 3 com `pandas`, `geopandas`, `rasterio`, `plotly` e `jupyter`.

1. Os dados brutos já estão em `data/raw/`; falta só o TOPODATA em `data/raw/relevo/` (seção acima).
2. Rode, na pasta do projeto:
   ```
   python scripts/01_validar_sp156.py data/raw/sp156/arquivo-final-4-trim-25.csv data/raw/sp156/arquivo-final-1-trim-26.csv
   python scripts/02_bases_territoriais.py
   python scripts/03_tratar_sp156.py data/raw/sp156/arquivo-final-4-trim-25.csv data/raw/sp156/arquivo-final-1-trim-26.csv
   python scripts/04_dimensoes_territoriais.py
   python scripts/05_indice_propensao.py
   python scripts/06_fato_distrito_dia.py
   python scripts/07_indicadores_quadrantes.py
   ```
3. Abra `dashboard/painel_rua_avisada.ipynb` e use *Run All*.

Para ver só o resultado, não é preciso rodar nada: os CSVs do modelo e o painel em HTML já estão no pacote.
