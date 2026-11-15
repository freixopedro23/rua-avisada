"""
Rua Avisada — Etapa 2: bases territoriais (GeoSampa + Censo 2022)
==================================================================

O que este script faz:
  1. Lê os limites de DISTRITOS (96) e SUBPREFEITURAS (32) do GeoSampa.
  2. Padroniza os nomes (maiúsculas, sem acento) para casar com o SP156 e o TabNet.
  3. Descobre a subprefeitura de cada distrito pelo mapa: pega um ponto dentro do
     distrito e vê em qual subprefeitura ele cai.
  4. Lê a população do Censo 2022 por distrito e faixa etária (TabNet/SMS) e
     calcula população total, população com 60+ e % de idosos.
  5. Lê os pontos de ALAGAMENTO e INUNDAÇÃO da Defesa Civil (GeoSampa) e descobre
     o distrito de cada ponto (o campo distrito vem vazio nesses arquivos).
  6. Confere os números e salva tudo em data/staging/.

Entradas esperadas (ajuste os caminhos abaixo se precisar):
  data/raw/geosampa/distrito_municipal_v2.shp
  data/raw/geosampa/subprefeitura_v2.shp
  data/raw/geosampa/risco_ocorrencia_alagamento_v2.shp
  data/raw/geosampa/risco_ocorrencia_inundacao_v2.shp
  data/raw/censo/populacao_distrito_faixa_2022.csv   (exportado do TabNet)

Saídas:
  data/staging/distritos.csv            1 linha por distrito (atributos + população)
  data/staging/subprefeituras.csv       1 linha por subprefeitura
  data/staging/distritos.gpkg           mapa dos distritos (para junções e mapas)
  data/staging/distritos_wgs84.geojson  mesmo mapa em lat/long (para o dashboard)
  data/staging/ocorrencias_defesa_civil.csv  1 linha por ocorrência, com distrito

Como rodar (na pasta do projeto):
  python scripts/02_bases_territoriais.py

Requisitos: pandas e geopandas (pip install geopandas)
"""

import unicodedata
from pathlib import Path

import geopandas as gpd # type: ignore
import pandas as pd # type: ignore

# ---------------------------------------------------------------------------
# Caminhos (ajuste aqui se os seus arquivos tiverem outro nome/pasta)
# ---------------------------------------------------------------------------

PASTA_GEO = Path("data/raw/geosampa")
ARQ_DISTRITOS = PASTA_GEO / "distrito_municipal_v2.shp"
ARQ_SUBPREF = PASTA_GEO / "subprefeitura_v2.shp"
ARQ_ALAGAMENTO = PASTA_GEO / "risco_ocorrencia_alagamento_v2.shp"
ARQ_INUNDACAO = PASTA_GEO / "risco_ocorrencia_inundacao_v2.shp"
ARQ_POPULACAO = Path("data/raw/censo/populacao_distrito_faixa_2022.csv")

PASTA_SAIDA = Path("data/staging")

CRS_METROS = "EPSG:31983"   # SIRGAS 2000 / UTM 23S: coordenadas em metros (padrão do GeoSampa)
CRS_LATLON = "EPSG:4326"    # WGS84: latitude/longitude (padrão de mapas web e do SP156)

POPULACAO_TOTAL_ESPERADA = 11_355_656  # total do município no TabNet (Censo 2022)

# Faixas etárias do TabNet que somam a população idosa (60 anos ou mais)
FAIXAS_IDOSOS = ["60 a 64", "65 a 69", "70 a 79", "80 e mais"]


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def normalizar(texto):
    """'São Miguel' -> 'SAO MIGUEL'. Usado como chave de junção entre as fontes."""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = texto.replace("'", " ").replace("-", " ")
    return " ".join(texto.upper().split())


def conferir(condicao, mensagem):
    """Imprime OK ou ATENÇÃO para cada verificação (não interrompe o script)."""
    print(("  [OK]      " if condicao else "  [ATENÇÃO] ") + mensagem)


# ---------------------------------------------------------------------------
# 1) Distritos e subprefeituras
# ---------------------------------------------------------------------------

def carregar_distritos():
    gdf = gpd.read_file(ARQ_DISTRITOS).to_crs(CRS_METROS)
    gdf = gdf.rename(columns={
        "cd_distrit": "cd_distrito",
        "nm_distrit": "nm_distrito",
        "sg_distrit": "sg_distrito",
        "nm_regiao_": "zona",            # Centro, Leste, Norte, Oeste, Sul
        "nm_regiao0": "regiao_8",        # Leste 1, Leste 2, Norte 1 ... (8 regiões)
    })
    gdf["cd_distrito"] = gdf["cd_distrito"].astype(int)
    gdf["nm_distrito_norm"] = gdf["nm_distrito"].map(normalizar)
    gdf["area_km2"] = (gdf.geometry.area / 1_000_000).round(3)  # área calculada do polígono
    return gdf[["cd_distrito", "nm_distrito", "nm_distrito_norm", "sg_distrito",
                "zona", "regiao_8", "area_km2", "geometry"]]


def carregar_subprefeituras():
    gdf = gpd.read_file(ARQ_SUBPREF).to_crs(CRS_METROS)
    gdf = gdf.rename(columns={
        "cd_subpref": "cd_subprefeitura",
        "nm_subpref": "nm_subprefeitura",
        "sg_subpref": "sg_subprefeitura",
        "nm_regiao_": "zona",
    })
    gdf["cd_subprefeitura"] = gdf["cd_subprefeitura"].astype(int)
    gdf["nm_subprefeitura_norm"] = gdf["nm_subprefeitura"].map(normalizar)
    return gdf[["cd_subprefeitura", "nm_subprefeitura", "nm_subprefeitura_norm",
                "sg_subprefeitura", "zona", "geometry"]]


def ligar_distrito_subprefeitura(distritos, subpref):
    """Para cada distrito, um ponto garantidamente DENTRO dele
    (representative_point) e a subprefeitura que contém esse ponto."""
    pontos = distritos[["cd_distrito"]].copy()
    pontos = gpd.GeoDataFrame(pontos, geometry=distritos.geometry.representative_point(),
                              crs=CRS_METROS)
    junta = gpd.sjoin(pontos, subpref[["cd_subprefeitura", "geometry"]],
                      how="left", predicate="within")
    return junta[["cd_distrito", "cd_subprefeitura"]]


# ---------------------------------------------------------------------------
# 2) População (TabNet / Censo 2022)
# ---------------------------------------------------------------------------

def carregar_populacao():
    # O arquivo do TabNet tem 3 linhas de título antes do cabeçalho
    # e linhas de "Total" e "Fonte" no fim, que descartamos.
    pop = pd.read_csv(ARQ_POPULACAO, sep=";", encoding="latin-1", skiprows=3)
    pop = pop.rename(columns={pop.columns[0]: "nm_distrito_tabnet"})
    pop = pop[pd.to_numeric(pop["Total"], errors="coerce").notna()]   # tira a linha "Fonte"
    pop = pop[pop["nm_distrito_tabnet"].str.strip() != "Total"]       # tira o total geral
    for col in pop.columns[1:]:
        pop[col] = pd.to_numeric(pop[col]).astype(int)

    pop["nm_distrito_norm"] = pop["nm_distrito_tabnet"].map(normalizar)
    pop["populacao"] = pop["Total"]
    pop["pop_60_mais"] = pop[FAIXAS_IDOSOS].sum(axis=1)
    pop["pct_idosos"] = (100 * pop["pop_60_mais"] / pop["populacao"]).round(2)
    return pop[["nm_distrito_norm", "populacao", "pop_60_mais", "pct_idosos"]]


# ---------------------------------------------------------------------------
# 3) Ocorrências da Defesa Civil (alagamento e inundação)
# ---------------------------------------------------------------------------

def carregar_ocorrencias(distritos):
    partes = []
    for arquivo in [ARQ_ALAGAMENTO, ARQ_INUNDACAO]:
        if not arquivo.exists():
            print(f"  (arquivo não encontrado, pulando: {arquivo})")
            continue
        partes.append(gpd.read_file(arquivo).to_crs(CRS_METROS))
    oc = pd.concat(partes, ignore_index=True)
    oc = gpd.GeoDataFrame(oc, geometry="geometry", crs=CRS_METROS)

    oc = oc.rename(columns={"cd_identif": "id_ocorrencia", "dc_tipo_oc": "tipo",
                            "dt_ocorren": "data_ocorrencia", "nm_subpref": "subpref_origem",
                            "dt_carga": "data_carga"})
    oc["data_ocorrencia"] = pd.to_datetime(oc["data_ocorrencia"]).dt.date

    # Junção espacial: em qual distrito cai cada ponto?
    oc = gpd.sjoin(oc, distritos[["cd_distrito", "nm_distrito", "geometry"]],
                   how="left", predicate="within")

    # Coordenadas em lat/long (úteis para o mapa do dashboard)
    latlon = oc.geometry.to_crs(CRS_LATLON)
    oc["latitude"] = latlon.y.round(6)
    oc["longitude"] = latlon.x.round(6)

    return pd.DataFrame(oc[["id_ocorrencia", "tipo", "data_ocorrencia", "cd_distrito",
                            "nm_distrito", "subpref_origem", "latitude", "longitude",
                            "data_carga"]])


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    PASTA_SAIDA.mkdir(parents=True, exist_ok=True)

    print("Lendo distritos e subprefeituras ...")
    distritos = carregar_distritos()
    subpref = carregar_subprefeituras()
    ligacao = ligar_distrito_subprefeitura(distritos, subpref)
    distritos = distritos.merge(ligacao, on="cd_distrito", how="left")

    print("Lendo população (Censo 2022 / TabNet) ...")
    pop = carregar_populacao()
    distritos = distritos.merge(pop, on="nm_distrito_norm", how="left")
    distritos["densidade_hab_km2"] = (distritos["populacao"] / distritos["area_km2"]).round(1)

    print("Lendo ocorrências da Defesa Civil ...")
    ocorrencias = carregar_ocorrencias(distritos)

    # ---------------- Conferências ----------------
    print("\nConferências:")
    conferir(len(distritos) == 96, f"distritos: {len(distritos)} (esperado 96)")
    conferir(len(subpref) == 32, f"subprefeituras: {len(subpref)} (esperado 32)")
    sem_sub = distritos["cd_subprefeitura"].isna().sum()
    conferir(sem_sub == 0, f"distritos sem subprefeitura: {sem_sub}")
    sem_pop = distritos["populacao"].isna().sum()
    conferir(sem_pop == 0, f"distritos sem população (nome não casou): {sem_pop}")
    total = int(distritos["populacao"].sum())
    conferir(total == POPULACAO_TOTAL_ESPERADA,
             f"população total: {total:,} (esperado {POPULACAO_TOTAL_ESPERADA:,})".replace(",", "."))
    contagem = distritos.groupby("cd_subprefeitura").size()
    conferir(contagem.min() >= 1, f"distritos por subprefeitura: de {contagem.min()} a {contagem.max()}")
    sem_distrito = ocorrencias["cd_distrito"].isna().sum()
    conferir(sem_distrito == 0, f"ocorrências fora de algum distrito: {sem_distrito} de {len(ocorrencias)}")
    print("  Ocorrências por tipo e mês:")
    meses = pd.to_datetime(ocorrencias["data_ocorrencia"]).dt.to_period("M")
    print(pd.crosstab(meses, ocorrencias["tipo"]).to_string())

    # ---------------- Salvando ----------------
    colunas = ["cd_distrito", "nm_distrito", "nm_distrito_norm", "sg_distrito",
               "cd_subprefeitura", "zona", "regiao_8", "area_km2",
               "populacao", "pop_60_mais", "pct_idosos", "densidade_hab_km2"]
    distritos[colunas].sort_values("cd_distrito").to_csv(
        PASTA_SAIDA / "distritos.csv", index=False, encoding="utf-8")

    subpref.drop(columns="geometry").sort_values("cd_subprefeitura").to_csv(
        PASTA_SAIDA / "subprefeituras.csv", index=False, encoding="utf-8")

    distritos[colunas + ["geometry"]].to_file(PASTA_SAIDA / "distritos.gpkg", driver="GPKG")
    distritos[colunas + ["geometry"]].to_crs(CRS_LATLON).to_file(
        PASTA_SAIDA / "distritos_wgs84.geojson", driver="GeoJSON")

    ocorrencias.to_csv(PASTA_SAIDA / "ocorrencias_defesa_civil.csv", index=False, encoding="utf-8")

    print(f"\nArquivos salvos em {PASTA_SAIDA}/")
