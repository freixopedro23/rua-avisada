"""
Rua Avisada — Etapa 6: chuva (INMET) + fato_distrito_dia com backlog diário
===========================================================================

O que este script faz:
  1. Lê os CSVs das estações automáticas do INMET (chuva hora a hora), converte
     o horário de UTC para Brasília (-3 h) e soma a chuva por dia.
  2. Cria a dim_estacao_inmet e liga cada distrito à estação mais próxima
     (coluna nova sk_estacao_inmet na dim_distrito).
  3. Monta a fato_distrito_dia (grão: distrito x dia da temporada) com:
       chuva_mm, chuva_max_hora_mm   (da estação do distrito)
       chamados_abertos              (manutenção de drenagem aberta no dia)
       chamados_concluidos           (manutenção finalizada no dia)
       backlog_drenagem              (pendentes no fim do dia)
       alagamentos_sp156             (reclamações "Alagamento" do cidadão no dia)
       ocorrencias_alagamento / ocorrencias_inundacao (Defesa Civil; vazio antes de 2026)
  4. Confere os números e salva.

Regras:
  - Cancelados ficam FORA de abertos/concluídos/backlog (não sabemos a data do cancelamento).
  - Backlog = abertos acumulados - concluídos acumulados, por distrito.
    Como só temos chamados abertos a partir de 01/10/2025, o backlog começa em zero
    nessa data (chamados mais antigos ainda pendentes não aparecem): limitação a declarar.
  - Defesa Civil: só temos 2026; antes de 01/01/2026 a coluna fica vazia (sem dado), não zero.

Entradas:
  data/raw/inmet/*.CSV                      (INMET, 1 arquivo por estação e ano)
  data/staging/distritos.gpkg               (etapa 2)
  data/staging/ocorrencias_defesa_civil.csv (etapa 2)
  data/modelo/fato_solicitacao.csv, dim_servico.csv, dim_status.csv, dim_distrito.csv

Saídas:
  data/modelo/fato_distrito_dia.csv
  data/modelo/dim_estacao_inmet.csv
  data/modelo/dim_distrito.csv              (+ sk_estacao_inmet, distancia_estacao_km)
  data/staging/chuva_diaria_estacao.csv

Como rodar (na pasta do projeto):
  python scripts/06_fato_distrito_dia.py

Requisitos: pandas, numpy, geopandas
"""

from pathlib import Path

import numpy as np
import pandas as pd

PASTA_INMET = Path("data/raw/inmet")
PASTA_STAGING = Path("data/staging")
PASTA_MODELO = Path("data/modelo")

INICIO_TEMPORADA = pd.Timestamp("2025-10-01")
FIM_TEMPORADA = pd.Timestamp("2026-03-31")
INICIO_DEFESA_CIVIL = pd.Timestamp("2026-01-01")   # antes disso não temos ocorrências

FUSO_HORAS = -3          # Brasília = UTC-3 (sem horário de verão desde 2019)
SEM_DADO_INMET = -9999


def conferir(condicao, mensagem):
    print(("  [OK]      " if condicao else "  [ATENÇÃO] ") + mensagem)


# ---------------------------------------------------------------------------
# 1) INMET
# ---------------------------------------------------------------------------

def ler_metadados(arquivo):
    """As 8 primeiras linhas do CSV do INMET têm os dados da estação."""
    meta = {}
    with open(arquivo, encoding="latin-1") as f:
        for _ in range(8):
            chave, valor = f.readline().strip().split(";")[:2]
            meta[chave.rstrip(":")] = valor
    return {
        "cd_wmo": meta["CODIGO (WMO)"],
        "nm_estacao": meta["ESTACAO"],
        "latitude": float(meta["LATITUDE"].replace(",", ".")),
        "longitude": float(meta["LONGITUDE"].replace(",", ".")),
        "altitude_m": float(meta["ALTITUDE"].replace(",", ".")),
    }


def ler_chuva(arquivo, cd_wmo):
    """Chuva horária (mm) com horário de Brasília."""
    df = pd.read_csv(arquivo, sep=";", encoding="latin-1", skiprows=8, decimal=",",
                     usecols=[0, 1, 2])
    df.columns = ["data", "hora", "chuva_mm"]
    df["momento"] = (pd.to_datetime(df["data"] + " " + df["hora"].str[:4], format="%Y/%m/%d %H%M")
                     + pd.Timedelta(hours=FUSO_HORAS))
    df.loc[df["chuva_mm"] <= SEM_DADO_INMET, "chuva_mm"] = np.nan
    df["cd_wmo"] = cd_wmo
    return df[["cd_wmo", "momento", "chuva_mm"]]


def carregar_inmet():
    arquivos = sorted(PASTA_INMET.glob("*.CSV")) + sorted(PASTA_INMET.glob("*.csv"))
    arquivos = list(dict.fromkeys(arquivos))  # sem repetir (Windows não diferencia maiúsculas)
    if not arquivos:
        raise FileNotFoundError(f"Nenhum CSV do INMET em {PASTA_INMET}")
    estacoes, horas = {}, []
    for arq in arquivos:
        meta = ler_metadados(arq)
        estacoes[meta["cd_wmo"]] = meta
        horas.append(ler_chuva(arq, meta["cd_wmo"]))
        print(f"  {arq.name}: {meta['cd_wmo']} {meta['nm_estacao']}")

    dim_est = pd.DataFrame(estacoes.values()).sort_values("cd_wmo").reset_index(drop=True)
    dim_est.insert(0, "sk_estacao_inmet", range(1, len(dim_est) + 1))

    horas = pd.concat(horas, ignore_index=True).drop_duplicates(["cd_wmo", "momento"])
    horas["data"] = horas["momento"].dt.normalize()
    diaria = (horas.groupby(["cd_wmo", "data"])
              .agg(chuva_mm=("chuva_mm", "sum"),            # soma das horas com dado
                   chuva_max_hora_mm=("chuva_mm", "max"),
                   horas_com_dado=("chuva_mm", "count"))
              .reset_index())
    diaria.loc[diaria["horas_com_dado"] == 0, ["chuva_mm", "chuva_max_hora_mm"]] = np.nan
    diaria = diaria.merge(dim_est[["cd_wmo", "sk_estacao_inmet"]], on="cd_wmo")
    return dim_est, diaria


# ---------------------------------------------------------------------------
# 2) Distrito -> estação mais próxima
# ---------------------------------------------------------------------------

def centro_dos_distritos():
    """Um ponto dentro de cada distrito, em lat/long."""
    import geopandas as gpd
    dist = gpd.read_file(PASTA_STAGING / "distritos.gpkg")
    pontos = dist.geometry.representative_point().to_crs("EPSG:4326")
    return pd.DataFrame({"sk_distrito": dist["cd_distrito"].astype(int),
                         "lat": pontos.y, "lon": pontos.x})


def distancia_km(lat1, lon1, lat2, lon2):
    """Distância em km entre pontos (fórmula de haversine)."""
    lat1, lon1, lat2, lon2 = map(np.radians, [lat1, lon1, lat2, lon2])
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 6371 * 2 * np.arcsin(np.sqrt(a))


def estacao_mais_proxima(centros, dim_est):
    dist = np.column_stack([
        distancia_km(centros["lat"].values, centros["lon"].values, e.latitude, e.longitude)
        for e in dim_est.itertuples()
    ])
    mais_proxima = dist.argmin(axis=1)
    return pd.DataFrame({
        "sk_distrito": centros["sk_distrito"].values,
        "sk_estacao_inmet": dim_est["sk_estacao_inmet"].values[mais_proxima],
        "distancia_estacao_km": dist.min(axis=1).round(1),
    })


# ---------------------------------------------------------------------------
# 3) Fato distrito x dia
# ---------------------------------------------------------------------------

def data_de_sk(serie):
    return pd.to_datetime(serie.astype("Int64").astype(str), format="%Y%m%d", errors="coerce")


def contar_por_dia(df, coluna_data, nome):
    return (df.dropna(subset=[coluna_data])
            .groupby(["sk_distrito", coluna_data]).size()
            .rename(nome).reset_index().rename(columns={coluna_data: "data"}))


def montar_fato(ligacao, diaria):
    fato_sol = pd.read_csv(PASTA_MODELO / "fato_solicitacao.csv")
    servico = pd.read_csv(PASTA_MODELO / "dim_servico.csv")
    status = pd.read_csv(PASTA_MODELO / "dim_status.csv")
    sol = (fato_sol.merge(servico[["sk_servico", "categoria_drenagem"]], on="sk_servico")
                   .merge(status[["sk_status", "grupo_status"]], on="sk_status"))
    sol = sol[sol["sk_distrito"].notna()].copy()
    sol["sk_distrito"] = sol["sk_distrito"].astype(int)
    sol["abertura"] = data_de_sk(sol["sk_data_abertura"])
    sol["finalizacao"] = data_de_sk(sol["sk_data_finalizacao"])

    manut = sol[(sol["categoria_drenagem"] == "manutencao") & (sol["grupo_status"] != "cancelado")]
    alag = sol[sol["categoria_drenagem"] == "alagamento_cidadao"]

    # Grade completa: todo distrito em todo dia (dias sem chamado = 0)
    dias = pd.date_range(INICIO_TEMPORADA, FIM_TEMPORADA, freq="D")
    grade = pd.MultiIndex.from_product([ligacao["sk_distrito"], dias],
                                       names=["sk_distrito", "data"]).to_frame(index=False)

    for parte in [contar_por_dia(manut, "abertura", "chamados_abertos"),
                  contar_por_dia(manut, "finalizacao", "chamados_concluidos"),
                  contar_por_dia(alag, "abertura", "alagamentos_sp156")]:
        grade = grade.merge(parte, on=["sk_distrito", "data"], how="left")
    contagens = ["chamados_abertos", "chamados_concluidos", "alagamentos_sp156"]
    grade[contagens] = grade[contagens].fillna(0).astype(int)

    # Backlog = abertos acumulados - concluídos acumulados (por distrito, em ordem de data)
    grade = grade.sort_values(["sk_distrito", "data"])
    acum = grade.groupby("sk_distrito")[["chamados_abertos", "chamados_concluidos"]].cumsum()
    grade["backlog_drenagem"] = acum["chamados_abertos"] - acum["chamados_concluidos"]

    # Defesa Civil (vazio antes de 2026 = sem dado)
    oc = pd.read_csv(PASTA_STAGING / "ocorrencias_defesa_civil.csv")
    oc = oc[oc["cd_distrito"].notna()].copy()
    oc["sk_distrito"] = oc["cd_distrito"].astype(int)
    oc["data"] = pd.to_datetime(oc["data_ocorrencia"])
    oc["tipo"] = oc["tipo"].str.upper().str.strip()
    for tipo, nome in [("ALAGAMENTO", "ocorrencias_alagamento"), ("INUNDACAO", "ocorrencias_inundacao")]:
        grade = grade.merge(contar_por_dia(oc[oc["tipo"] == tipo], "data", nome),
                            on=["sk_distrito", "data"], how="left")
        grade[nome] = grade[nome].fillna(0).astype("Int64")
        grade.loc[grade["data"] < INICIO_DEFESA_CIVIL, nome] = pd.NA

    # Chuva da estação do distrito
    grade = grade.merge(ligacao[["sk_distrito", "sk_estacao_inmet"]], on="sk_distrito")
    grade = grade.merge(diaria[["sk_estacao_inmet", "data", "chuva_mm", "chuva_max_hora_mm"]],
                        on=["sk_estacao_inmet", "data"], how="left")
    grade[["chuva_mm", "chuva_max_hora_mm"]] = grade[["chuva_mm", "chuva_max_hora_mm"]].round(1)

    grade["sk_data"] = grade["data"].dt.strftime("%Y%m%d").astype(int)
    colunas = ["sk_distrito", "sk_data", "chuva_mm", "chuva_max_hora_mm",
               "chamados_abertos", "chamados_concluidos", "backlog_drenagem",
               "alagamentos_sp156", "ocorrencias_alagamento", "ocorrencias_inundacao"]
    return grade[colunas].sort_values(["sk_distrito", "sk_data"]).reset_index(drop=True), manut, alag


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("Lendo INMET ...")
    dim_est, diaria = carregar_inmet()

    print("Ligando distritos às estações ...")
    ligacao = estacao_mais_proxima(centro_dos_distritos(), dim_est)

    print("Montando fato_distrito_dia ...")
    fato, manut, alag = montar_fato(ligacao, diaria)

    # ---------------- Conferências ----------------
    n_dias = (FIM_TEMPORADA - INICIO_TEMPORADA).days + 1
    temporada = diaria[diaria["data"].between(INICIO_TEMPORADA, FIM_TEMPORADA)]
    manut_temp = manut[manut["abertura"].between(INICIO_TEMPORADA, FIM_TEMPORADA)]
    print("\nConferências:")
    conferir(len(fato) == 96 * n_dias, f"linhas: {len(fato):,} (esperado {96 * n_dias:,} = 96 × {n_dias} dias)".replace(",", "."))
    conferir(not fato.duplicated(["sk_distrito", "sk_data"]).any(), "sem linhas repetidas (distrito × dia)")
    conferir(fato["backlog_drenagem"].min() >= 0, f"backlog mínimo: {fato['backlog_drenagem'].min()} (não pode ser negativo)")
    conferir(fato["chamados_abertos"].sum() == len(manut_temp),
             f"chamados abertos na fato: {fato['chamados_abertos'].sum():,} = manutenção não cancelada na fato_solicitacao: {len(manut_temp):,}".replace(",", "."))
    conferir(fato["alagamentos_sp156"].sum() == len(alag),
             f"reclamações de alagamento (SP156): {fato['alagamentos_sp156'].sum()}")
    sem_chuva = fato["chuva_mm"].isna().sum()
    conferir(sem_chuva == 0, f"linhas sem chuva: {sem_chuva}")
    for e in dim_est.itertuples():
        t = temporada[temporada["sk_estacao_inmet"] == e.sk_estacao_inmet]
        n_dist = (ligacao["sk_estacao_inmet"] == e.sk_estacao_inmet).sum()
        print(f"  {e.cd_wmo} {e.nm_estacao}: {t['chuva_mm'].sum():.1f} mm na temporada; "
              f"{int((t['horas_com_dado'] < 24).sum())} dias com hora faltando; {n_dist} distritos ligados")
    ultimo = fato[fato["sk_data"] == fato["sk_data"].max()]
    print(f"  Backlog da cidade em {FIM_TEMPORADA:%d/%m/%Y}: {int(ultimo['backlog_drenagem'].sum()):,} chamados pendentes".replace(",", "."))
    pico = fato.groupby("sk_data")["backlog_drenagem"].sum()
    print(f"  Maior backlog da cidade na temporada: {int(pico.max()):,} em {str(pico.idxmax())[6:]}/{str(pico.idxmax())[4:6]}/{str(pico.idxmax())[:4]}".replace(",", "."))

    # ---------------- Salvando ----------------
    fato.to_csv(PASTA_MODELO / "fato_distrito_dia.csv", index=False, encoding="utf-8")
    dim_est.to_csv(PASTA_MODELO / "dim_estacao_inmet.csv", index=False, encoding="utf-8")
    diaria.to_csv(PASTA_STAGING / "chuva_diaria_estacao.csv", index=False, encoding="utf-8")

    dim_dist = pd.read_csv(PASTA_MODELO / "dim_distrito.csv")
    dim_dist = dim_dist.drop(columns=[c for c in ["sk_estacao_inmet", "distancia_estacao_km"] if c in dim_dist])
    dim_dist = dim_dist.merge(ligacao, on="sk_distrito", how="left")
    dim_dist.to_csv(PASTA_MODELO / "dim_distrito.csv", index=False, encoding="utf-8")
    print(f"\nSalvo em {PASTA_MODELO}/: fato_distrito_dia.csv, dim_estacao_inmet.csv, dim_distrito.csv (atualizada)")
