"""
Rua Avisada — Etapa 7: indicadores, quadrantes e validação
===========================================================

O que este script faz (por distrito):
  1. Dívida de drenagem: média do backlog no FIM DO DIA ANTERIOR a cada dia de chuva
     forte (>= LIMITE_CHUVA_FORTE_MM na estação do distrito), por 10 mil habitantes.
     Taxa de pendência: nesses mesmos dias, % dos chamados abertos até a véspera que
     ainda estavam pendentes (base padrão do eixo "sujeira" — ver BASE_SUJEIRA).
  2. Tempo de atendimento (mediana de dias), % finalizados, chamados por 10 mil hab.
  3. Alagamentos por 10 mm de chuva (ocorrências da Defesa Civil, jan–mar/2026).
  4. Índice de subnotificação: ocorrências da Defesa Civil / (chamados de drenagem + 1),
     jan–mar/2026. Alto = "alaga e não se reclama". (+1 evita divisão por zero.)
  5. Quadrantes (corte em 50):
        propensão = indice_propensao (etapa 5, 0–100)
        sujeira   = posição relativa (0–100) da taxa de pendência (ou da dívida, conforme BASE_SUJEIRA)
        zona vermelha (propenso + sujo) · zeladoria (não propenso + sujo)
        estrutural (propenso + limpo)   · fora do modelo (não propenso + limpo)
  6. Prioridade (para ordenar a lista da zona vermelha) = média de propensão e sujeira.
  7. Validação: correlação de Spearman entre a dívida e as ocorrências da Defesa Civil.

Entradas: data/modelo/ (fato_distrito_dia, fato_solicitacao, dim_distrito, dim_servico,
          dim_status, dim_data) — etapas 3 a 6.
Saídas:
  data/modelo/agg_indicadores_distrito.csv   1 linha por distrito (chave sk_distrito)
  data/staging/kpis_cidade.csv               KPIs da cidade para o dashboard
  data/staging/relatorio_etapa7.md

Como rodar (na pasta do projeto):
  python scripts/07_indicadores_quadrantes.py

Requisito: pandas
"""

from pathlib import Path

import numpy as np
import pandas as pd

PASTA_MODELO = Path("data/modelo")
PASTA_STAGING = Path("data/staging")

LIMITE_CHUVA_FORTE_MM = 20     # dia de chuva forte
MIN_CHAMADOS_TAXA = 10         # mínimo de chamados acumulados para calcular a taxa de pendência

# Base do eixo "sujeira" dos quadrantes:
#   "taxa_pendencia"  -> % dos chamados abertos até a véspera que ainda estavam pendentes
#                        (mede o ATRASO do serviço, independe do volume de pedidos)
#   "divida_10mil_hab" -> pendentes na véspera por 10 mil moradores (mistura demanda e atraso;
#                        infla distritos com poucos moradores e muitos chamados, como o Centro)
BASE_SUJEIRA = "taxa_pendencia"
CORTE_QUADRANTE = 50
INICIO_DEFESA_CIVIL = 20260101  # sk_data: só temos ocorrências a partir daqui
FIM_TEMPORADA = 20260331

NOMES_QUADRANTE = {
    (True, True): "zona vermelha",
    (False, True): "zeladoria",
    (True, False): "estrutural",
    (False, False): "fora do modelo",
}


def fmt(n, casas=0):
    texto = f"{n:,.{casas}f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


def spearman(a, b):
    return a.rank().corr(b.rank())


# ---------------------------------------------------------------------------
# Leitura
# ---------------------------------------------------------------------------

def carregar():
    dia = pd.read_csv(PASTA_MODELO / "fato_distrito_dia.csv")
    sol = pd.read_csv(PASTA_MODELO / "fato_solicitacao.csv")
    dist = pd.read_csv(PASTA_MODELO / "dim_distrito.csv")
    serv = pd.read_csv(PASTA_MODELO / "dim_servico.csv")
    status = pd.read_csv(PASTA_MODELO / "dim_status.csv")
    sol = (sol.merge(serv[["sk_servico", "categoria_drenagem"]], on="sk_servico")
              .merge(status[["sk_status", "grupo_status"]], on="sk_status"))
    sol = sol[sol["sk_distrito"].notna()].copy()
    sol["sk_distrito"] = sol["sk_distrito"].astype(int)
    return dia, sol, dist


# ---------------------------------------------------------------------------
# Indicadores
# ---------------------------------------------------------------------------

def divida_drenagem(dia, dist):
    """Backlog no fim da véspera de cada dia de chuva forte, por 10 mil hab."""
    dia = dia.sort_values(["sk_distrito", "sk_data"]).copy()
    g = dia.groupby("sk_distrito")
    dia["backlog_vespera"] = g["backlog_drenagem"].shift(1)
    dia["abertos_ate_vespera"] = g["chamados_abertos"].cumsum() - dia["chamados_abertos"]
    forte = dia[(dia["chuva_mm"] >= LIMITE_CHUVA_FORTE_MM) & dia["backlog_vespera"].notna()].copy()
    forte["taxa"] = (100 * forte["backlog_vespera"] / forte["abertos_ate_vespera"]).where(
        forte["abertos_ate_vespera"] >= MIN_CHAMADOS_TAXA)
    resumo = forte.groupby("sk_distrito").agg(
        dias_chuva_forte=("sk_data", "size"),
        backlog_vespera_medio=("backlog_vespera", "mean"),
        taxa_pendencia_pct=("taxa", "mean"))
    resumo["taxa_pendencia_pct"] = resumo["taxa_pendencia_pct"].round(1)
    resumo["backlog_vespera_medio"] = resumo["backlog_vespera_medio"].round(1)
    resumo = resumo.reindex(dist["sk_distrito"]).fillna({"dias_chuva_forte": 0})
    pop = dist.set_index("sk_distrito")["populacao"]
    resumo["divida_drenagem_10mil_hab"] = (10_000 * resumo["backlog_vespera_medio"] / pop).round(2)
    return resumo.reset_index()


def atendimento(sol, dist):
    manut = sol[(sol["categoria_drenagem"] == "manutencao") & (sol["grupo_status"] != "cancelado")]
    g = manut.groupby("sk_distrito")
    res = pd.DataFrame({
        "chamados_manutencao": g.size(),
        "pct_finalizados": (100 * g["flag_finalizado"].mean()).round(1),
        "tempo_mediano_dias": g["dias_ate_conclusao"].median(),
    }).reindex(dist["sk_distrito"])
    res["chamados_manutencao"] = res["chamados_manutencao"].fillna(0).astype(int)
    pop = dist.set_index("sk_distrito")["populacao"]
    res["chamados_10mil_hab"] = (10_000 * res["chamados_manutencao"] / pop).round(1)
    return res.reset_index()


def alagamentos(dia, dist):
    """Jan–mar/2026: período em que temos ocorrências da Defesa Civil."""
    p = dia[(dia["sk_data"] >= INICIO_DEFESA_CIVIL) & (dia["sk_data"] <= FIM_TEMPORADA)]
    g = p.groupby("sk_distrito")
    res = pd.DataFrame({
        "ocorrencias_dc_jan_mar": (g["ocorrencias_alagamento"].sum() + g["ocorrencias_inundacao"].sum()).astype(int),
        "chuva_jan_mar_mm": g["chuva_mm"].sum().round(1),
        "chamados_drenagem_jan_mar": (g["chamados_abertos"].sum() + g["alagamentos_sp156"].sum()).astype(int),
    }).reindex(dist["sk_distrito"])
    res["alagamentos_por_10mm"] = (res["ocorrencias_dc_jan_mar"] / (res["chuva_jan_mar_mm"] / 10)).round(3)
    res["indice_subnotificacao"] = (res["ocorrencias_dc_jan_mar"] / (res["chamados_drenagem_jan_mar"] + 1)).round(3)
    return res.reset_index()


COLUNA_BASE = {"taxa_pendencia": "taxa_pendencia_pct", "divida_10mil_hab": "divida_drenagem_10mil_hab"}


def quadrantes(tab, base=BASE_SUJEIRA):
    tab = tab.copy()
    tab["score_sujeira"] = (100 * tab[COLUNA_BASE[base]].rank(pct=True)).round(1)
    propenso = tab["indice_propensao"] >= CORTE_QUADRANTE
    sujo = tab["score_sujeira"] >= CORTE_QUADRANTE
    tab["quadrante"] = [NOMES_QUADRANTE[(p, s)] for p, s in zip(propenso, sujo)]
    tab["prioridade"] = ((tab["indice_propensao"] + tab["score_sujeira"]) / 2).round(1)
    tab["rank_prioridade"] = tab["prioridade"].rank(ascending=False, method="first").astype(int)
    return tab


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    dia, sol, dist = carregar()
    if "indice_propensao" not in dist:
        raise SystemExit("A dim_distrito não tem indice_propensao: rode a etapa 5 antes.")

    tab = dist[["sk_distrito", "nm_distrito", "populacao", "area_km2", "indice_propensao"]].copy()
    for parte in [divida_drenagem(dia, dist), atendimento(sol, dist), alagamentos(dia, dist)]:
        tab = tab.merge(parte, on="sk_distrito", how="left")
    alternativa = "divida_10mil_hab" if BASE_SUJEIRA == "taxa_pendencia" else "taxa_pendencia"
    tab_alt = quadrantes(tab, alternativa)   # só para comparar no relatório
    tab = quadrantes(tab)

    # ---------------- Validação ----------------
    oc_km2 = tab["ocorrencias_dc_jan_mar"] / tab["area_km2"]
    oc_hab = 10_000 * tab["ocorrencias_dc_jan_mar"] / tab["populacao"]
    validacao = {
        "taxa de pendência × ocorrências por km²": spearman(tab["taxa_pendencia_pct"], oc_km2),
        "taxa de pendência × ocorrências por 10 mil hab.": spearman(tab["taxa_pendencia_pct"], oc_hab),
        "dívida de drenagem × ocorrências por km²": spearman(tab["divida_drenagem_10mil_hab"], oc_km2),
        "dívida de drenagem × ocorrências por 10 mil hab.": spearman(tab["divida_drenagem_10mil_hab"], oc_hab),
        "chamados por 10 mil hab. × ocorrências por 10 mil hab.": spearman(tab["chamados_10mil_hab"], oc_hab),
        "índice de propensão × ocorrências por km²": spearman(tab["indice_propensao"], oc_km2),
    }
    def resumo_quadrantes(t):
        return (t.assign(oc_10mil=oc_hab)
                .groupby("quadrante")
                .agg(distritos=("sk_distrito", "size"),
                     populacao=("populacao", "sum"),
                     ocorrencias_dc=("ocorrencias_dc_jan_mar", "sum"),
                     oc_por_10mil_hab_media=("oc_10mil", "mean"),
                     tempo_mediano=("tempo_mediano_dias", "median"))
                .reindex(["zona vermelha", "zeladoria", "estrutural", "fora do modelo"]))

    por_quadrante = resumo_quadrantes(tab)
    por_quadrante_alt = resumo_quadrantes(tab_alt)

    # ---------------- KPIs da cidade ----------------
    manut = sol[(sol["categoria_drenagem"] == "manutencao") & (sol["grupo_status"] != "cancelado")]
    backlog_cidade = dia.groupby("sk_data")["backlog_drenagem"].sum()
    pop_total = dist["populacao"].sum()
    kpis = pd.DataFrame([
        ("chamados_drenagem_temporada", len(manut)),
        ("reclamacoes_alagamento_sp156", int(dia["alagamentos_sp156"].sum())),
        ("pct_finalizados", round(100 * manut["flag_finalizado"].mean(), 1)),
        ("tempo_mediano_dias", manut["dias_ate_conclusao"].median()),
        ("backlog_pico", int(backlog_cidade.max())),
        ("data_backlog_pico", int(backlog_cidade.idxmax())),
        ("backlog_fim_temporada", int(backlog_cidade.iloc[-1])),
        ("divida_drenagem_cidade_10mil_hab", round(10_000 * tab["backlog_vespera_medio"].sum() / pop_total, 2)),
        ("ocorrencias_defesa_civil_jan_mar", int(tab["ocorrencias_dc_jan_mar"].sum())),
        ("taxa_pendencia_media_pct", round(float(tab["taxa_pendencia_pct"].mean()), 1)),
        ("distritos_zona_vermelha", int((tab["quadrante"] == "zona vermelha").sum())),
        ("populacao_zona_vermelha", int(tab.loc[tab["quadrante"] == "zona vermelha", "populacao"].sum())),
        ("pop_60_mais_zona_vermelha", int(dist.set_index("sk_distrito").loc[
            tab.loc[tab["quadrante"] == "zona vermelha", "sk_distrito"], "pop_60_mais"].sum())),
    ], columns=["kpi", "valor"], dtype=object)  # object: mantém inteiros como inteiros

    # ---------------- Salvando ----------------
    colunas = ["sk_distrito", "indice_propensao", "score_sujeira", "quadrante", "prioridade",
               "rank_prioridade", "taxa_pendencia_pct", "divida_drenagem_10mil_hab", "backlog_vespera_medio",
               "dias_chuva_forte", "chamados_manutencao", "chamados_10mil_hab",
               "pct_finalizados", "tempo_mediano_dias", "ocorrencias_dc_jan_mar",
               "chuva_jan_mar_mm", "chamados_drenagem_jan_mar", "alagamentos_por_10mm",
               "indice_subnotificacao"]
    tab[colunas].sort_values("sk_distrito").to_csv(
        PASTA_MODELO / "agg_indicadores_distrito.csv", index=False, encoding="utf-8")
    kpis.to_csv(PASTA_STAGING / "kpis_cidade.csv", index=False, encoding="utf-8")

    # ---------------- Relatório ----------------
    k = dict(zip(kpis["kpi"], kpis["valor"]))
    pico = str(k["data_backlog_pico"])
    linhas = ["# Etapa 7 — indicadores e quadrantes", "",
              "## KPIs da cidade (temporada out/2025–mar/2026)",
              f"- Chamados de manutenção de drenagem: {fmt(k['chamados_drenagem_temporada'])}",
              f"- Finalizados: {fmt(k['pct_finalizados'], 1)}% · mediana de {fmt(k['tempo_mediano_dias'], 1)} dias",
              f"- Backlog: pico de {fmt(k['backlog_pico'])} em {pico[6:]}/{pico[4:6]}/{pico[:4]}; "
              f"{fmt(k['backlog_fim_temporada'])} no fim da temporada",
              f"- Dívida de drenagem da cidade (véspera de chuva ≥ {LIMITE_CHUVA_FORTE_MM} mm): "
              f"{fmt(k['divida_drenagem_cidade_10mil_hab'], 2)} pendentes por 10 mil hab.",
              f"- Zona vermelha: {k['distritos_zona_vermelha']} distritos, {fmt(k['populacao_zona_vermelha'])} "
              f"moradores ({fmt(k['pop_60_mais_zona_vermelha'])} com 60+)",
              f"- Taxa de pendência média dos distritos (véspera de chuva forte): {fmt(tab['taxa_pendencia_pct'].mean(), 1)}%", ""]

    def tabela_quadrantes(resumo, titulo):
        out = [f"## {titulo}", "",
               "| Quadrante | Distritos | População | Ocorrências DC (jan–mar) | Ocorr./10 mil hab. (média) | Tempo mediano (dias) |",
               "|---|---|---|---|---|---|"]
        for q, r in resumo.iterrows():
            if pd.isna(r["distritos"]):
                out.append(f"| {q} | 0 | — | — | — | — |")
            else:
                out.append(f"| {q} | {int(r['distritos'])} | {fmt(r['populacao'])} | {int(r['ocorrencias_dc'])} | "
                           f"{fmt(r['oc_por_10mil_hab_media'], 2)} | {fmt(r['tempo_mediano'], 1)} |")
        return out + [""]

    linhas += tabela_quadrantes(por_quadrante, f"Quadrantes (sujeira = {BASE_SUJEIRA}) — USADOS NO MODELO")
    linhas += tabela_quadrantes(por_quadrante_alt, f"Comparação: quadrantes se a sujeira fosse {alternativa}")
    centro = tab["sk_distrito"].isin(dist.loc[dist["sk_subprefeitura"].isin(
        dist.loc[dist["nm_distrito"] == "SE", "sk_subprefeitura"]), "sk_distrito"])
    linhas.append(f"- Distritos da subprefeitura Sé na zona vermelha: {int((centro & (tab['quadrante'] == 'zona vermelha')).sum())} "
                  f"(com {alternativa}: {int((centro & (tab_alt['quadrante'] == 'zona vermelha')).sum())}) de {int(centro.sum())}")
    linhas += ["", "## Validação (correlação de Spearman entre distritos)", ""]
    linhas += [f"- {nome}: **{fmt(valor, 2)}**" for nome, valor in validacao.items()]
    linhas += ["  (0 = nenhuma relação; acima de ~0,3 já indica relação; negativo = relação inversa)"]
    linhas += ["", "## Zona vermelha — lista priorizada (top 15)", "",
               "| # | Distrito | Propensão | Sujeira | Pendência (%) | Dívida (pend./10 mil hab.) | Tempo mediano (dias) | Ocorr. DC |",
               "|---|---|---|---|---|---|---|---|"]
    verm = tab[tab["quadrante"] == "zona vermelha"].sort_values("prioridade", ascending=False)
    for i, r in enumerate(verm.head(15).itertuples(), 1):
        linhas.append(f"| {i} | {r.nm_distrito} | {r.indice_propensao} | {r.score_sujeira} | {r.taxa_pendencia_pct} | "
                      f"{r.divida_drenagem_10mil_hab} | {r.tempo_mediano_dias} | {r.ocorrencias_dc_jan_mar} |")
    linhas += ["", "## Subnotificação — onde se alaga e não se reclama (top 10, jan–mar/2026)", ""]
    sub = tab[tab["ocorrencias_dc_jan_mar"] > 0].sort_values("indice_subnotificacao", ascending=False)
    linhas += [f"- {r.nm_distrito}: {r.ocorrencias_dc_jan_mar} ocorrências DC × {r.chamados_drenagem_jan_mar} "
               f"chamados (índice {r.indice_subnotificacao})" for r in sub.head(10).itertuples()]
    relatorio = "\n".join(linhas)
    (PASTA_STAGING / "relatorio_etapa7.md").write_text(relatorio, encoding="utf-8")
    print(relatorio)
    print(f"\nSalvo: {PASTA_MODELO}/agg_indicadores_distrito.csv · {PASTA_STAGING}/kpis_cidade.csv")
