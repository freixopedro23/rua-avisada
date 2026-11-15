"""
Rua Avisada — Etapa 5: relevo + córregos -> índice de propensão (0–100)
========================================================================

O que este script faz:
  1. Junta as folhas do TOPODATA (altitude "ZN" e declividade "SN") em um mapa
     só, recortado na cidade.
  2. "Pinta" cada pixel do mapa com o código do distrito em que ele cai e calcula,
     por distrito: altitude média, declividade média e % da área quase plana.
  3. Com a Rede de Drenagem do GeoSampa, calcula por distrito: densidade de
     córregos (km de córrego por km²) e % da área a até 200 m de um córrego.
  4. Índice de propensão = média de 4 componentes (25% cada), cada um convertido
     em POSIÇÃO RELATIVA entre os 96 distritos (100 = mais propenso, 0 = menos):
        - área quase plana (quanto MAIS, mais propenso)
        - declividade média (quanto MENOS, mais propenso)
        - altitude média (quanto MENOS, mais propenso — fundos de vale)
        - área perto de córrego (quanto MAIS, mais propenso)
  5. Validação: compara o índice com as ocorrências de alagamento/inundação da
     Defesa Civil por km² (correlação de Spearman = correlação entre posições).
  6. Acrescenta as colunas novas à data/modelo/dim_distrito.csv.

Entradas:
  data/raw/relevo/*ZN.tif e *SN.tif           (TOPODATA / INPE)
  data/raw/geosampa/drenagem.shp              (Rede de Drenagem / GeoSampa)
  data/staging/distritos.gpkg                 (etapa 2)
  data/staging/ocorrencias_defesa_civil.csv   (etapa 2)
  data/modelo/dim_distrito.csv                (etapa 4)

Saídas:
  data/modelo/dim_distrito.csv     (com as colunas de relevo, córregos e índice)
  data/staging/relevo_distritos.csv
  data/staging/relatorio_etapa5.md

Como rodar (na pasta do projeto):
  python scripts/05_indice_propensao.py

Requisitos: pandas, geopandas, rasterio
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.merge import merge

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------

PASTA_RELEVO = Path("data/raw/relevo")
ARQ_DRENAGEM = Path("data/raw/geosampa/drenagem.shp")
ARQ_DISTRITOS_GEO = Path("data/staging/distritos.gpkg")
ARQ_OCORRENCIAS = Path("data/staging/ocorrencias_defesa_civil.csv")
ARQ_DIM_DISTRITO = Path("data/modelo/dim_distrito.csv")
PASTA_STAGING = Path("data/staging")

SEM_DADO = -9999            # valor de "sem dado" do TOPODATA
LIMITE_PLANO_PCT = 2.0      # declividade abaixo disto = área quase plana (%)
DISTANCIA_CORREGO_M = 200   # faixa de proximidade de córrego (metros)
CRS_METROS = "EPSG:31983"   # SIRGAS 2000 / UTM 23S

# Componentes do índice: coluna -> True se "quanto MAIOR, mais propenso"
COMPONENTES = {
    "pct_area_plana": True,
    "declividade_media_pct": False,
    "altitude_media_m": False,
    "pct_area_perto_corrego": True,
}

# Colunas que este script acrescenta à dim_distrito (apagadas antes, se já existirem)
COLUNAS_NOVAS = ["altitude_media_m", "amplitude_altitude_m", "declividade_media_pct",
                 "pct_area_plana", "densidade_corregos_km_km2", "pct_area_perto_corrego",
                 "indice_propensao"]


# ---------------------------------------------------------------------------
# 1) Relevo: mosaico + estatística por distrito
# ---------------------------------------------------------------------------

def mosaico(sufixo, limites):
    """Junta todas as folhas com o sufixo (ZN ou SN), recortando nos limites."""
    arquivos = sorted(PASTA_RELEVO.glob(f"*{sufixo}.tif"))
    if not arquivos:
        raise FileNotFoundError(f"Nenhum arquivo *{sufixo}.tif em {PASTA_RELEVO}")
    print(f"  {sufixo}: {', '.join(a.name for a in arquivos)}")
    fontes = [rasterio.open(a) for a in arquivos]
    dados, transformacao = merge(fontes, bounds=limites, nodata=SEM_DADO)
    crs = fontes[0].crs
    for f in fontes:
        f.close()
    banda = dados[0].astype("float64")
    banda[banda <= SEM_DADO] = np.nan
    return banda, transformacao, crs


def relevo_por_distrito(distritos):
    # CRS das folhas (o TOPODATA usa lat/long)
    with rasterio.open(next(PASTA_RELEVO.glob("*ZN.tif"))) as f:
        crs_raster = f.crs
    dist_raster = distritos.to_crs(crs_raster)
    margem = 0.01  # ~1 km de folga em graus
    minx, miny, maxx, maxy = dist_raster.total_bounds
    limites = (minx - margem, miny - margem, maxx + margem, maxy + margem)

    altitude, transf, _ = mosaico("ZN", limites)
    declividade, transf_sn, _ = mosaico("SN", limites)
    if altitude.shape != declividade.shape:
        raise ValueError("Altitude e declividade vieram com tamanhos diferentes.")

    # Cada pixel recebe o código do distrito (0 = fora da cidade)
    rotulos = rasterize(
        ((geom, int(cd)) for geom, cd in zip(dist_raster.geometry, dist_raster["cd_distrito"])),
        out_shape=altitude.shape, transform=transf, fill=0, dtype="int32",
    )

    pixels = pd.DataFrame({"cd_distrito": rotulos.ravel(),
                           "altitude": altitude.ravel(),
                           "declividade": declividade.ravel()})
    pixels = pixels[(pixels["cd_distrito"] > 0)]
    sem_dado = pixels[["altitude", "declividade"]].isna().any(axis=1).mean()
    pixels = pixels.dropna()
    pixels["plano"] = pixels["declividade"] < LIMITE_PLANO_PCT

    grupo = pixels.groupby("cd_distrito")
    relevo = pd.DataFrame({
        "altitude_media_m": grupo["altitude"].mean().round(1),
        "amplitude_altitude_m": (grupo["altitude"].quantile(0.95)
                                 - grupo["altitude"].quantile(0.05)).round(1),
        "declividade_media_pct": grupo["declividade"].mean().round(2),
        "pct_area_plana": (100 * grupo["plano"].mean()).round(2),
        "n_pixels": grupo.size(),
    }).reset_index()
    return relevo, sem_dado


# ---------------------------------------------------------------------------
# 2) Córregos (Rede de Drenagem)
# ---------------------------------------------------------------------------

def corregos_por_distrito(distritos):
    dren = gpd.read_file(ARQ_DRENAGEM)[["nm_tipo_cu", "geometry"]].to_crs(CRS_METROS)
    # trechos dentro de lagos/represas não são córregos
    dren = dren[~dren["nm_tipo_cu"].fillna("").str.contains("lago", case=False)]
    dist = distritos[["cd_distrito", "geometry"]].to_crs(CRS_METROS)
    area_m2 = dist.set_index("cd_distrito").geometry.area

    # km de córrego dentro de cada distrito
    pedacos = gpd.overlay(dren[["geometry"]], dist, how="intersection", keep_geom_type=True)
    km = pedacos.assign(km=pedacos.geometry.length / 1000).groupby("cd_distrito")["km"].sum()

    # faixa de 200 m em volta de todos os córregos (unida num único polígono)
    faixa = dren.geometry.buffer(DISTANCIA_CORREGO_M)
    faixa = faixa.union_all() if hasattr(faixa, "union_all") else faixa.unary_union
    perto_m2 = dist.set_index("cd_distrito").geometry.intersection(faixa).area

    return pd.DataFrame({
        "densidade_corregos_km_km2": (km.reindex(area_m2.index, fill_value=0)
                                      / (area_m2 / 1e6)).round(2),
        "pct_area_perto_corrego": (100 * perto_m2 / area_m2).round(2),
    }).reset_index(), len(dren)


# ---------------------------------------------------------------------------
# 3) Índice e validação
# ---------------------------------------------------------------------------

def calcular_indice(tabela):
    """Cada componente vira posição relativa 0–100 (100 = mais propenso);
    o índice é a média simples dos componentes."""
    partes = []
    for coluna, maior_e_pior in COMPONENTES.items():
        posicao = tabela[coluna].rank(pct=True, ascending=maior_e_pior)
        partes.append(100 * posicao)
    tabela["indice_propensao"] = pd.concat(partes, axis=1).mean(axis=1).round(1)
    return tabela


def validar(tabela, area_km2):
    oc = pd.read_csv(ARQ_OCORRENCIAS)
    contagem = oc.groupby("cd_distrito").size()
    v = tabela[["cd_distrito", "indice_propensao"]].copy()
    v["ocorrencias"] = v["cd_distrito"].map(contagem).fillna(0)
    v["ocorrencias_km2"] = v["ocorrencias"] / v["cd_distrito"].map(area_km2)
    spearman = v["indice_propensao"].rank().corr(v["ocorrencias_km2"].rank())
    com = v.loc[v["ocorrencias"] > 0, "indice_propensao"].mean()
    sem = v.loc[v["ocorrencias"] == 0, "indice_propensao"].mean()
    return spearman, com, sem, (v["ocorrencias"] > 0).sum(), len(oc)


def diagnostico(tabela, dim):
    """Correlação de Spearman de CADA variável com as ocorrências (por km² e
    por 10 mil hab.), para entender qual componente "acerta" e qual "erra"."""
    oc = pd.read_csv(ARQ_OCORRENCIAS)
    contagem = oc.groupby("cd_distrito").size()
    d = tabela.merge(dim[["sk_distrito", "area_km2", "populacao", "densidade_hab_km2"]],
                     left_on="cd_distrito", right_on="sk_distrito")
    d["ocorrencias"] = d["cd_distrito"].map(contagem).fillna(0)
    alvos = {"por km²": d["ocorrencias"] / d["area_km2"],
             "por 10 mil hab.": 10_000 * d["ocorrencias"] / d["populacao"],
             "total": d["ocorrencias"]}
    variaveis = ["indice_propensao", "pct_area_plana", "declividade_media_pct",
                 "altitude_media_m", "pct_area_perto_corrego",
                 "densidade_corregos_km_km2", "amplitude_altitude_m", "densidade_hab_km2"]
    linhas = ["| Variável | " + " | ".join(alvos) + " |", "|---" * (len(alvos) + 1) + "|"]
    for var in variaveis:
        valores = [f"{d[var].rank().corr(a.rank()):+.2f}" for a in alvos.values()]
        linhas.append(f"| {var} | " + " | ".join(valores) + " |")
    return linhas


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    distritos = gpd.read_file(ARQ_DISTRITOS_GEO)
    dim = pd.read_csv(ARQ_DIM_DISTRITO)

    print("Relevo (TOPODATA) ...")
    relevo, pct_sem_dado = relevo_por_distrito(distritos)
    print("Córregos (Rede de Drenagem) ... (pode levar alguns minutos)")
    corregos, n_trechos = corregos_por_distrito(distritos)

    tabela = relevo.merge(corregos, on="cd_distrito", how="outer")
    tabela = calcular_indice(tabela)
    area_km2 = dim.set_index("sk_distrito")["area_km2"]
    spearman, media_com, media_sem, n_com, n_oc = validar(tabela, area_km2)

    # Atualiza a dim_distrito (sem duplicar colunas se rodar de novo)
    dim = dim.drop(columns=[c for c in COLUNAS_NOVAS if c in dim.columns])
    dim = dim.merge(tabela.rename(columns={"cd_distrito": "sk_distrito"})[["sk_distrito"] + COLUNAS_NOVAS],
                    on="sk_distrito", how="left")
    dim.to_csv(ARQ_DIM_DISTRITO, index=False, encoding="utf-8")
    tabela.to_csv(PASTA_STAGING / "relevo_distritos.csv", index=False, encoding="utf-8")

    # Relatório
    nomes = dim.set_index("sk_distrito")["nm_distrito"]
    top = tabela.sort_values("indice_propensao", ascending=False)
    linhas = [
        "# Etapa 5 — índice de propensão", "",
        "## Conferências",
        f"- Distritos com relevo calculado: {relevo['cd_distrito'].nunique()} de 96 "
        f"(mínimo de {relevo['n_pixels'].min()} pixels por distrito)",
        f"- Pixels da cidade sem dado no TOPODATA: {100 * pct_sem_dado:.2f}%",
        f"- Trechos de córrego usados: {n_trechos:,}".replace(",", "."),
        f"- Distritos sem índice: {int(dim['indice_propensao'].isna().sum())}", "",
        "## Validação com a Defesa Civil (2026)",
        f"- Ocorrências de alagamento + inundação: {n_oc}, em {n_com} distritos",
        f"- Correlação de Spearman (índice × ocorrências por km²): **{spearman:.2f}** "
        "(0 = nenhuma relação; 1 = mesma ordem; acima de ~0,3 já indica relação)",
        f"- Índice médio dos distritos COM ocorrência: {media_com:.1f} · SEM ocorrência: {media_sem:.1f}", "",
        "## 10 distritos mais propensos", "",
        "| Distrito | Índice | Declividade média (%) | Área plana (%) | Altitude (m) | Perto de córrego (%) |",
        "|---|---|---|---|---|---|",
    ]
    for _, r in top.head(10).iterrows():
        linhas.append(f"| {nomes[int(r['cd_distrito'])]} | {r['indice_propensao']} | "
                      f"{r['declividade_media_pct']} | {r['pct_area_plana']} | "
                      f"{r['altitude_media_m']} | {r['pct_area_perto_corrego']} |")
    linhas += ["", "## Diagnóstico: correlação de cada variável com as ocorrências", "",
               "(sinal + = quanto maior a variável, mais ocorrências)", ""]
    linhas += diagnostico(tabela, dim)
    linhas += ["", "## 5 menos propensos", ""]
    linhas += [f"- {nomes[int(r['cd_distrito'])]}: {r['indice_propensao']}" for _, r in top.tail(5).iterrows()]
    relatorio = "\n".join(linhas)
    (PASTA_STAGING / "relatorio_etapa5.md").write_text(relatorio, encoding="utf-8")
    print("\n" + relatorio)
    print(f"\ndim_distrito atualizada em {ARQ_DIM_DISTRITO}")
