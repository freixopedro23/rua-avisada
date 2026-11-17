"""
Rua Avisada — Etapa 4: dimensões territoriais e calendário
===========================================================

Monta a cadeia do Snowflake  dim_distrito -> dim_subprefeitura -> dim_zona
e a dim_data (calendário), e confere se as chaves usadas na fato existem.

Entradas (geradas nas etapas 2 e 3):
  data/staging/distritos.csv
  data/staging/subprefeituras.csv
  data/modelo/fato_solicitacao.csv

Saídas em data/modelo/:
  dim_zona.csv            sk_zona, nm_zona                      (5 zonas)
  dim_subprefeitura.csv   sk_subprefeitura, nm, sigla, sk_zona   (32)
  dim_distrito.csv        sk_distrito, nm, sigla, sk_subprefeitura, área, população... (96)
  dim_data.csv            sk_data (AAAAMMDD), data, ano, mês, dia da semana, temporada_chuva

Observação: as colunas de relevo/córregos/índice de propensão (etapa 5) e a
estação do INMET (etapa 6) serão acrescentadas à dim_distrito nessas etapas.

Como rodar (na pasta do projeto):
  python scripts/04_dimensoes_territoriais.py

Requisito: pandas
"""

from pathlib import Path

import pandas as pd

PASTA_STAGING = Path("data/staging")
PASTA_MODELO = Path("data/modelo")

# Calendário: cobre a temporada e as datas de finalização/ocorrências até set/2026
INICIO_CALENDARIO = "2025-10-01"
FIM_CALENDARIO = "2026-09-30"

# Meses da temporada de chuvas (outubro a março)
MESES_CHUVA = [10, 11, 12, 1, 2, 3]

NOMES_MES = {1: "jan", 2: "fev", 3: "mar", 4: "abr", 5: "mai", 6: "jun",
             7: "jul", 8: "ago", 9: "set", 10: "out", 11: "nov", 12: "dez"}
NOMES_DIA = {0: "seg", 1: "ter", 2: "qua", 3: "qui", 4: "sex", 5: "sáb", 6: "dom"}


def conferir(condicao, mensagem):
    print(("  [OK]      " if condicao else "  [ATENÇÃO] ") + mensagem)


# ---------------------------------------------------------------------------
# Território
# ---------------------------------------------------------------------------

def montar_territorio():
    distritos = pd.read_csv(PASTA_STAGING / "distritos.csv")
    subpref = pd.read_csv(PASTA_STAGING / "subprefeituras.csv")

    # dim_zona: as 5 zonas que vêm do GeoSampa (Centro, Leste, Norte, Oeste, Sul)
    dim_zona = (pd.DataFrame({"nm_zona": sorted(subpref["zona"].unique())}))
    dim_zona.insert(0, "sk_zona", range(1, len(dim_zona) + 1))

    # dim_subprefeitura: chave = código oficial do GeoSampa
    dim_sub = subpref.merge(dim_zona, left_on="zona", right_on="nm_zona")
    dim_sub = dim_sub.rename(columns={"cd_subprefeitura": "sk_subprefeitura"})
    dim_sub = dim_sub[["sk_subprefeitura", "nm_subprefeitura", "sg_subprefeitura", "sk_zona"]]
    dim_sub = dim_sub.sort_values("sk_subprefeitura")

    # dim_distrito: chave = código oficial do GeoSampa; zona NÃO fica aqui
    # (no Snowflake ela é alcançada via subprefeitura)
    dim_dist = distritos.rename(columns={"cd_distrito": "sk_distrito",
                                         "cd_subprefeitura": "sk_subprefeitura"})
    dim_dist = dim_dist[["sk_distrito", "nm_distrito", "sg_distrito", "sk_subprefeitura",
                         "regiao_8", "area_km2", "populacao", "pop_60_mais",
                         "pct_idosos", "densidade_hab_km2"]].sort_values("sk_distrito")

    # Conferência de coerência: a zona do distrito (GeoSampa) bate com a da subprefeitura?
    zona_dist = distritos.set_index("cd_distrito")["zona"]
    zona_via_sub = (dim_dist.merge(dim_sub, on="sk_subprefeitura")
                    .merge(dim_zona, on="sk_zona").set_index("sk_distrito")["nm_zona"])
    divergentes = (zona_dist.sort_index() != zona_via_sub.sort_index()).sum()
    return dim_zona, dim_sub, dim_dist, divergentes


# ---------------------------------------------------------------------------
# Calendário
# ---------------------------------------------------------------------------

def montar_dim_data():
    datas = pd.date_range(INICIO_CALENDARIO, FIM_CALENDARIO, freq="D")
    dim = pd.DataFrame({"data": datas})
    dim.insert(0, "sk_data", dim["data"].dt.strftime("%Y%m%d").astype(int))
    dim["ano"] = dim["data"].dt.year
    dim["mes"] = dim["data"].dt.month
    dim["nome_mes"] = dim["mes"].map(NOMES_MES)
    dim["ano_mes"] = dim["data"].dt.strftime("%Y-%m")
    dim["trimestre"] = dim["data"].dt.quarter
    dim["dia"] = dim["data"].dt.day
    dim["dia_semana"] = dim["data"].dt.day_of_week.map(NOMES_DIA)
    dim["fim_de_semana"] = (dim["data"].dt.day_of_week >= 5).map({True: "S", False: "N"})
    dim["temporada_chuva"] = dim["mes"].isin(MESES_CHUVA).map({True: "S", False: "N"})
    dim["data"] = dim["data"].dt.date
    return dim


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dim_zona, dim_sub, dim_dist, divergentes = montar_territorio()
    dim_data = montar_dim_data()

    fato = pd.read_csv(PASTA_MODELO / "fato_solicitacao.csv")

    print("Conferências:")
    conferir(len(dim_zona) == 5, f"zonas: {len(dim_zona)} ({', '.join(dim_zona['nm_zona'])})")
    conferir(len(dim_sub) == 32, f"subprefeituras: {len(dim_sub)}")
    conferir(len(dim_dist) == 96, f"distritos: {len(dim_dist)}")
    conferir(divergentes == 0, f"distritos cuja zona difere da zona da subprefeitura: {divergentes}")

    # Integridade referencial: toda chave da fato existe na dimensão?
    def orfaos(coluna, dimensao, chave):
        valores = fato[coluna].dropna().astype(int)
        return int((~valores.isin(dimensao[chave])).sum())

    conferir(orfaos("sk_distrito", dim_dist, "sk_distrito") == 0,
             f"fato -> dim_distrito: {orfaos('sk_distrito', dim_dist, 'sk_distrito')} chaves sem par")
    conferir(orfaos("sk_data_abertura", dim_data, "sk_data") == 0,
             f"fato -> dim_data (abertura): {orfaos('sk_data_abertura', dim_data, 'sk_data')} chaves sem par")
    conferir(orfaos("sk_data_finalizacao", dim_data, "sk_data") == 0,
             f"fato -> dim_data (finalização): {orfaos('sk_data_finalizacao', dim_data, 'sk_data')} chaves sem par")
    for dim_nome in ["dim_servico", "dim_status"]:
        dim = pd.read_csv(PASTA_MODELO / f"{dim_nome}.csv")
        chave = "sk_" + dim_nome.split("_")[1]
        n = orfaos(chave, dim, chave)
        conferir(n == 0, f"fato -> {dim_nome}: {n} chaves sem par")

    dim_zona.to_csv(PASTA_MODELO / "dim_zona.csv", index=False, encoding="utf-8")
    dim_sub.to_csv(PASTA_MODELO / "dim_subprefeitura.csv", index=False, encoding="utf-8")
    dim_dist.to_csv(PASTA_MODELO / "dim_distrito.csv", index=False, encoding="utf-8")
    dim_data.to_csv(PASTA_MODELO / "dim_data.csv", index=False, encoding="utf-8")
    print(f"\nDimensões salvas em {PASTA_MODELO}/ "
          f"(calendário de {INICIO_CALENDARIO} a {FIM_CALENDARIO}: {len(dim_data)} dias)")
