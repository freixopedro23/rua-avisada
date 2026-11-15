"""
Rua Avisada — Etapa 3: tratamento do SP156 -> fato_solicitacao + dimensões
===========================================================================

O que este script faz:
  1. Lê os CSVs do SP156 em blocos e guarda só os serviços de DRENAGEM
     (listas SERVICOS_MANUTENCAO e SERVICOS_ALAGAMENTO, abaixo).
  2. Recorta a temporada de chuvas (out/2025–mar/2026) pela data de abertura.
  3. Define o distrito de cada chamado, em 3 tentativas:
       a) pelo nome do campo "Distrito" (comparado sem acento com os 96 do GeoSampa);
       b) se vazio/desconhecido: pela latitude/longitude (em qual distrito o ponto cai);
       c) se nada funcionar: fica "sem distrito" (a subprefeitura vem pelo distrito,
          na dim_distrito, então não guardamos o campo "Prefeitura Operacional").
  4. Calcula os dias até a conclusão (descarta conclusão antes da abertura).
  5. Monta as tabelas do modelo e salva em data/modelo/:
       fato_solicitacao.csv, dim_servico.csv, dim_assunto.csv, dim_tema.csv, dim_status.csv
  6. Salva um relatório de qualidade em data/staging/relatorio_etapa3.md.

LGPD: número do imóvel e CEP NÃO entram no modelo (só logradouro e coordenadas).

Como rodar (na pasta do projeto, depois da etapa 2):
  python scripts/03_tratar_sp156.py data/raw/sp156/arquivo-final-4-trim-25.csv data/raw/sp156/arquivo-final-1-trim-26.csv

Requisitos: pandas e geopandas
"""

import sys
import unicodedata
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configurações
# ---------------------------------------------------------------------------

INICIO_TEMPORADA = pd.Timestamp("2025-10-01")
FIM_TEMPORADA = pd.Timestamp("2026-03-31")

# Serviços que entram no BACKLOG de drenagem (pedidos de manutenção)
SERVICOS_MANUTENCAO = [
    "Solicitar limpeza de bueiros, boca de lobo e poços de visita",
    "Drenagem de água da chuva - Bueiros e bocas de lobo",
    "Reformar galerias de águas de chuvas (pluviais)",
    "Rompimento de galeria de águas pluviais",
    "Microdrenagem",
    "Córrego - solicitar limpeza",
]
# Serviço que é RECLAMAÇÃO de alagamento feita pelo cidadão (fora do backlog)
SERVICOS_ALAGAMENTO = ["Alagamento"]

# Grupo de cada status do SP156
GRUPO_STATUS = {
    "FINALIZADA": "finalizado",
    "ABERTO": "pendente",
    "EM ANDAMENTO": "pendente",
    "CANCELADA": "cancelado",
}

# Colunas do CSV original -> nomes que usamos no script
COLUNAS = {
    "Data de Abertura": "data_abertura",
    "Data de Finalização": "data_finalizacao",
    "Tema": "tema",
    "Assunto": "assunto",
    "Serviço": "servico",
    "Status": "status",
    "Logradouro": "logradouro",
    "Latitude": "latitude",
    "Longitude": "longitude",
    "Distrito": "distrito_origem",
}

PASTA_STAGING = Path("data/staging")
PASTA_MODELO = Path("data/modelo")
ARQ_DISTRITOS_CSV = PASTA_STAGING / "distritos.csv"
ARQ_DISTRITOS_GEO = PASTA_STAGING / "distritos.gpkg"

TAMANHO_BLOCO = 200_000


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def normalizar(texto):
    """'São Miguel' -> 'SAO MIGUEL'; também troca - / ' por espaço."""
    if pd.isna(texto):
        return ""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    for sinal in ["'", "-", "/"]:
        texto = texto.replace(sinal, " ")
    return " ".join(texto.upper().split())


def para_numero(serie):
    """Converte coordenadas em número aceitando vírgula decimal ('-23,55')."""
    return pd.to_numeric(serie.astype(str).str.replace(",", ".", regex=False), errors="coerce")


def fmt(n):
    """12345 -> '12.345' (ponto de milhar, padrão brasileiro)."""
    return f"{int(n):,}".replace(",", ".")


def coordenada_valida(lat, lon):
    """Limites aproximados do município: descarta (0, 0), vazios e lat/long trocadas."""
    return lat.between(-24.1, -23.3) & lon.between(-46.9, -46.3)


def pct(parte, total):
    return f"{100 * parte / total:.1f}%" if total else "—"


# ---------------------------------------------------------------------------
# 1) Leitura + filtro de drenagem
# ---------------------------------------------------------------------------

def ler_drenagem(arquivos):
    alvo_manut = {normalizar(s) for s in SERVICOS_MANUTENCAO}
    alvo_alag = {normalizar(s) for s in SERVICOS_ALAGAMENTO}
    partes, total_lido = [], 0

    for arq in arquivos:
        print(f"Lendo {arq} ...")
        leitor = pd.read_csv(arq, sep=";", encoding="latin-1", dtype=str,
                             usecols=list(COLUNAS), chunksize=TAMANHO_BLOCO)
        for bloco in leitor:
            total_lido += len(bloco)
            bloco = bloco.rename(columns=COLUNAS)
            serv = bloco["servico"].map(normalizar)
            bloco["categoria_drenagem"] = None
            bloco.loc[serv.isin(alvo_manut), "categoria_drenagem"] = "manutencao"
            bloco.loc[serv.isin(alvo_alag), "categoria_drenagem"] = "alagamento_cidadao"
            bloco = bloco[bloco["categoria_drenagem"].notna()].copy()
            bloco["arquivo_origem"] = Path(arq).name
            partes.append(bloco)

    df = pd.concat(partes, ignore_index=True)
    print(f"  linhas lidas: {fmt(total_lido)} · de drenagem: {fmt(len(df))}")
    return df, total_lido


# ---------------------------------------------------------------------------
# 2) Datas e recorte da temporada
# ---------------------------------------------------------------------------

def tratar_datas(df):
    df["data_abertura"] = pd.to_datetime(df["data_abertura"], dayfirst=True, errors="coerce")
    df["data_finalizacao"] = pd.to_datetime(df["data_finalizacao"], dayfirst=True, errors="coerce")

    df = df[df["data_abertura"].between(INICIO_TEMPORADA, FIM_TEMPORADA)].copy()

    # Conclusão antes da abertura é erro de registro: não usamos essa data
    invalida = df["data_finalizacao"] < df["data_abertura"]
    df["flag_conclusao_invalida"] = invalida.astype(int)
    df.loc[invalida, "data_finalizacao"] = pd.NaT
    return df


# ---------------------------------------------------------------------------
# 3) Distrito: nome -> coordenada -> sem distrito
# ---------------------------------------------------------------------------

def distrito_pelo_nome(df, distritos):
    mapa = dict(zip(distritos["nm_distrito_norm"], distritos["cd_distrito"]))
    df["cd_distrito"] = df["distrito_origem"].map(normalizar).map(mapa)
    df["origem_distrito"] = df["cd_distrito"].notna().map({True: "campo_distrito", False: None})
    # nomes preenchidos que não casaram com nenhum dos 96 (para o relatório)
    nao_casou = df.loc[df["cd_distrito"].isna() & df["distrito_origem"].notna(), "distrito_origem"]
    return df, nao_casou.value_counts()


def distrito_pela_coordenada(df):
    """Junção espacial só para quem ficou sem distrito e tem lat/long."""
    import geopandas as gpd

    df["lat"] = para_numero(df["latitude"])
    df["lon"] = para_numero(df["longitude"])
    coord_ok = coordenada_valida(df["lat"], df["lon"])
    precisa = df["cd_distrito"].isna() & coord_ok
    if precisa.sum() == 0:
        return df

    pontos = gpd.GeoDataFrame(
        df.loc[precisa, []],
        geometry=gpd.points_from_xy(df.loc[precisa, "lon"], df.loc[precisa, "lat"]),
        crs="EPSG:4326",
    )
    mapa_geo = gpd.read_file(ARQ_DISTRITOS_GEO)[["cd_distrito", "geometry"]]
    pontos = pontos.to_crs(mapa_geo.crs)
    junta = gpd.sjoin(pontos, mapa_geo, how="left", predicate="within")
    junta = junta[~junta.index.duplicated()]   # ponto na divisa: fica com o primeiro

    achou = junta["cd_distrito"].dropna()
    df.loc[achou.index, "cd_distrito"] = achou
    df.loc[achou.index, "origem_distrito"] = "coordenada"
    return df


# ---------------------------------------------------------------------------
# 4) Dimensões e fato
# ---------------------------------------------------------------------------

def montar_dimensoes(df):
    for col in ["tema", "assunto", "servico", "status"]:
        df[col] = df[col].fillna("(não informado)").str.strip()

    dim_tema = (df[["tema"]].drop_duplicates().sort_values("tema").reset_index(drop=True)
                .rename(columns={"tema": "nm_tema"}))
    dim_tema.insert(0, "sk_tema", range(1, len(dim_tema) + 1))

    dim_assunto = df[["tema", "assunto"]].drop_duplicates().sort_values(["tema", "assunto"])
    dim_assunto = dim_assunto.merge(dim_tema, left_on="tema", right_on="nm_tema")
    dim_assunto = dim_assunto.rename(columns={"assunto": "nm_assunto"}).reset_index(drop=True)
    dim_assunto.insert(0, "sk_assunto", range(1, len(dim_assunto) + 1))
    dim_assunto = dim_assunto[["sk_assunto", "nm_assunto", "sk_tema", "tema"]]

    # Um serviço pertence a um assunto; a chave é a combinação tema+assunto+serviço
    dim_servico = (df[["tema", "assunto", "servico", "categoria_drenagem"]]
                   .drop_duplicates(subset=["tema", "assunto", "servico"])
                   .sort_values(["tema", "assunto", "servico"]))
    dim_servico = dim_servico.merge(dim_assunto, left_on=["tema", "assunto"],
                                    right_on=["tema", "nm_assunto"])
    dim_servico = dim_servico.rename(columns={"servico": "nm_servico"}).reset_index(drop=True)
    dim_servico.insert(0, "sk_servico", range(1, len(dim_servico) + 1))
    chave_servico = dim_servico[["sk_servico", "tema", "assunto", "nm_servico"]]
    dim_servico = dim_servico[["sk_servico", "nm_servico", "categoria_drenagem", "sk_assunto"]]

    dim_status = (df[["status"]].drop_duplicates().sort_values("status").reset_index(drop=True)
                  .rename(columns={"status": "nm_status"}))
    dim_status.insert(0, "sk_status", range(1, len(dim_status) + 1))
    dim_status["grupo_status"] = dim_status["nm_status"].map(normalizar).map(GRUPO_STATUS).fillna("outro")

    dim_tema = dim_tema[["sk_tema", "nm_tema"]]
    dim_assunto = dim_assunto[["sk_assunto", "nm_assunto", "sk_tema"]]
    return dim_tema, dim_assunto, dim_servico, dim_status, chave_servico


def sk_data(serie):
    """Data -> chave inteira AAAAMMDD (ligação com a dim_data). Vazio fica vazio."""
    return pd.to_numeric(serie.dt.strftime("%Y%m%d"), errors="coerce").astype("Int64")


def montar_fato(df, chave_servico, dim_status):
    fato = df.merge(chave_servico, left_on=["tema", "assunto", "servico"],
                    right_on=["tema", "assunto", "nm_servico"], how="left")
    fato = fato.merge(dim_status[["sk_status", "nm_status", "grupo_status"]],
                      left_on="status", right_on="nm_status", how="left")

    fato = fato.sort_values(["data_abertura", "arquivo_origem"]).reset_index(drop=True)
    fato.insert(0, "id_solicitacao", range(1, len(fato) + 1))  # o CSV não traz protocolo

    fato["sk_data_abertura"] = sk_data(fato["data_abertura"])
    # data de finalização só vale para chamados finalizados
    fato.loc[fato["grupo_status"] != "finalizado", "data_finalizacao"] = pd.NaT
    fato["sk_data_finalizacao"] = sk_data(fato["data_finalizacao"])
    fato["dias_ate_conclusao"] = (fato["data_finalizacao"] - fato["data_abertura"]).dt.days.astype("Int64")
    fato["flag_finalizado"] = (fato["grupo_status"] == "finalizado").astype(int)
    fato["qtd"] = 1
    fato["sk_distrito"] = fato["cd_distrito"].astype("Int64")
    fato["origem_distrito"] = fato["origem_distrito"].fillna("sem_distrito")
    # coordenadas: só as válidas (dentro do município); as demais ficam vazias
    lat, lon = para_numero(fato["latitude"]), para_numero(fato["longitude"])
    valida = coordenada_valida(lat, lon)
    fato["latitude"] = lat.where(valida).round(6)
    fato["longitude"] = lon.where(valida).round(6)

    colunas = ["id_solicitacao", "sk_data_abertura", "sk_data_finalizacao", "sk_distrito",
               "sk_servico", "sk_status", "dias_ate_conclusao", "flag_finalizado",
               "flag_conclusao_invalida", "qtd", "origem_distrito",
               "logradouro", "latitude", "longitude"]
    return fato[colunas]


# ---------------------------------------------------------------------------
# 5) Relatório de qualidade
# ---------------------------------------------------------------------------

def montar_relatorio(total_lido, n_drenagem, fato, dim_servico, nomes_dist):
    n = len(fato)
    serv = fato.merge(dim_servico, on="sk_servico")
    linhas = ["# Etapa 3 — tratamento do SP156", "",
              f"- Linhas lidas: {fmt(total_lido)}",
              f"- Chamados de drenagem (todas as datas): {fmt(n_drenagem)}",
              f"- Na temporada {INICIO_TEMPORADA:%d/%m/%Y}–{FIM_TEMPORADA:%d/%m/%Y}: **{fmt(n)}**",
              "", "## Por categoria", ""]
    for cat, qtd in serv["categoria_drenagem"].value_counts().items():
        linhas.append(f"- {cat}: {fmt(qtd)}")

    linhas += ["", "## Como o distrito foi definido", "", "| Categoria | Origem | Chamados | % |", "|---|---|---|---|"]
    for (cat, origem), qtd in serv.groupby(["categoria_drenagem", "origem_distrito"]).size().items():
        tot = (serv["categoria_drenagem"] == cat).sum()
        linhas.append(f"| {cat} | {origem} | {fmt(qtd)} | {pct(qtd, tot)} |")
    sem = fato["origem_distrito"] == "sem_distrito"
    linhas += ["", f"- Sem distrito: {fmt(sem.sum())} ({pct(sem.sum(), n)}) — ficam na fato com sk_distrito vazio."]

    linhas += ["", "## Atendimento", ""]
    fin = fato["flag_finalizado"] == 1
    linhas.append(f"- Finalizados: {fmt(fin.sum())} ({pct(fin.sum(), n)})")
    linhas.append(f"- Mediana de dias até a conclusão (finalizados): {fato.loc[fin, 'dias_ate_conclusao'].median()}")
    linhas.append(f"- Conclusão antes da abertura (descartada): {int(fato['flag_conclusao_invalida'].sum())}")

    linhas += ["", "## Nomes que não casaram (conferir!)", "", "Distrito:"]
    linhas += [f"- {k}: {v}" for k, v in nomes_dist.head(20).items()] or ["- nenhum"]
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    arquivos = sys.argv[1:]
    if not arquivos:
        print("Uso: python scripts/03_tratar_sp156.py arquivo1.csv [arquivo2.csv ...]")
        sys.exit(1)
    PASTA_MODELO.mkdir(parents=True, exist_ok=True)

    distritos = pd.read_csv(ARQ_DISTRITOS_CSV)

    df, total_lido = ler_drenagem(arquivos)
    n_drenagem = len(df)
    df = tratar_datas(df)
    df, nomes_dist = distrito_pelo_nome(df, distritos)
    df = distrito_pela_coordenada(df)

    dim_tema, dim_assunto, dim_servico, dim_status, chave_servico = montar_dimensoes(df)
    fato = montar_fato(df, chave_servico, dim_status)

    fato.to_csv(PASTA_MODELO / "fato_solicitacao.csv", index=False, encoding="utf-8")
    dim_servico.to_csv(PASTA_MODELO / "dim_servico.csv", index=False, encoding="utf-8")
    dim_assunto.to_csv(PASTA_MODELO / "dim_assunto.csv", index=False, encoding="utf-8")
    dim_tema.to_csv(PASTA_MODELO / "dim_tema.csv", index=False, encoding="utf-8")
    dim_status.to_csv(PASTA_MODELO / "dim_status.csv", index=False, encoding="utf-8")

    relatorio = montar_relatorio(total_lido, n_drenagem, fato, dim_servico, nomes_dist)
    (PASTA_STAGING / "relatorio_etapa3.md").write_text(relatorio, encoding="utf-8")
    print("\n" + relatorio)
    print(f"\nModelo salvo em {PASTA_MODELO}/ · relatório em {PASTA_STAGING}/relatorio_etapa3.md")
