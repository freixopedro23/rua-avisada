"""
Rua Avisada — Etapa 1: validação do CSV do SP156
=================================================

O que este script faz:
  1. Descobre o encoding (utf-8 ou latin-1) e o separador (; , ou tab) de cada CSV.
  2. Lista todas as colunas.
  3. Procura os campos de que o modelo precisa: data de abertura, data de conclusão,
     serviço, assunto, tema, distrito, subprefeitura, status e latitude/longitude.
  4. Mede o preenchimento de cada campo e se as datas são válidas.
  5. Mostra os serviços de DRENAGEM encontrados e quantos caem na temporada
     configurada em INICIO_TEMPORADA / FIM_TEMPORADA (padrão: out/2025–mar/2026,
     que o portal publica nos arquivos 4º TRI 2025 e 1º TRI 2026).
  6. Imprime um diagnóstico e salva tudo em staging/validacao_sp156.md.

Como rodar (a temporada cruza dois trimestres, então passe os dois arquivos):
  python scripts/01_validar_sp156.py data/raw/sp156/sp156_2025_q4.csv data/raw/sp156/sp156_2026_q1.csv

Requisito: pandas (pip install pandas)
"""

import csv
import sys
import unicodedata
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configurações (ajuste aqui se precisar)
# ---------------------------------------------------------------------------

INICIO_TEMPORADA = pd.Timestamp("2025-10-01")
FIM_TEMPORADA = pd.Timestamp("2026-03-31 23:59:59")

TAMANHO_BLOCO = 200_000  # linhas lidas por vez (evita estourar a memória)

# Palavras que indicam um serviço de drenagem (comparadas SEM acento, em minúsculas)
PALAVRAS_DRENAGEM = [
    "bueiro", "boca de lobo", "boca-de-lobo", "galeria", "drenagem",
    "corrego", "alagamento", "piscinao", "ramal", "poco de visita",
]

# Para cada campo do modelo, os pedaços de nome de coluna que procuramos.
# A ordem importa: o primeiro que casar é o escolhido.
CAMPOS_ESPERADOS = {
    "data_abertura": ["data de abertura", "data abertura", "dt_abertura", "abertura"],
    "data_conclusao": ["data de conclusao", "conclusao", "encerramento",
                       "fechamento", "finalizacao", "data do parecer", "parecer"],
    "servico": ["servico"],
    "assunto": ["assunto"],
    "tema": ["tema"],
    "distrito": ["distrito"],
    "subprefeitura": ["subprefeitura"],
    "status": ["status", "situacao"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lon", "long"],
}

# Campos sem os quais o modelo muda (os demais são "bons de ter")
CAMPOS_CRITICOS = ["data_abertura", "data_conclusao", "servico", "distrito", "status"]


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def normalizar(texto):
    """Tira acentos, espaços extras e deixa minúsculo: 'Serviço ' -> 'servico'."""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return " ".join(texto.lower().strip().split())


def detectar_encoding_e_separador(caminho):
    """Tenta utf-8 (com e sem BOM); se falhar, usa latin-1 (que sempre abre)."""
    for encoding in ["utf-8-sig", "latin-1"]:
        try:
            with open(caminho, encoding=encoding) as f:
                amostra = f.read(100_000)
            break
        except UnicodeDecodeError:
            continue
    # O Sniffer olha a amostra e adivinha o separador
    try:
        separador = csv.Sniffer().sniff(amostra, delimiters=";,\t|").delimiter
    except csv.Error:
        separador = ";"  # padrão dos dados de governo
    return encoding, separador


def achar_colunas(colunas):
    """Liga cada campo esperado a uma coluna real do CSV (ou None se não achar)."""
    normalizadas = {normalizar(c): c for c in colunas}
    mapa = {}
    for campo, pistas in CAMPOS_ESPERADOS.items():
        mapa[campo] = None
        for pista in pistas:
            # pistas curtas (lat, lon) precisam casar com o nome inteiro
            if len(pista) <= 4:
                achou = [orig for norm, orig in normalizadas.items() if norm == pista]
            else:
                achou = [orig for norm, orig in normalizadas.items() if pista in norm]
            # não deixar a mesma coluna servir para dois campos de data
            achou = [c for c in achou if c not in mapa.values()]
            if achou:
                mapa[campo] = achou[0]
                break
    return mapa


def converter_data(serie):
    """Converte texto em data no padrão brasileiro (dia primeiro)."""
    return pd.to_datetime(serie, errors="coerce", dayfirst=True)


def fmt(n):
    """Formata número com ponto de milhar: 12345 -> '12.345'."""
    return f"{int(n):,}".replace(",", ".")


def eh_drenagem(texto):
    t = normalizar(texto)
    return any(p in t for p in PALAVRAS_DRENAGEM)


# ---------------------------------------------------------------------------
# Leitura e estatísticas
# ---------------------------------------------------------------------------

def analisar_arquivo(caminho):
    encoding, separador = detectar_encoding_e_separador(caminho)
    cabecalho = pd.read_csv(caminho, sep=separador, encoding=encoding, nrows=0)
    colunas = list(cabecalho.columns)
    mapa = achar_colunas(colunas)

    # Acumuladores
    stats = {
        "arquivo": Path(caminho).name, "encoding": encoding, "separador": separador,
        "colunas": colunas, "mapa": mapa, "linhas": 0,
        "preenchidos": {c: 0 for c in mapa},
        "datas_validas": {"data_abertura": 0, "data_conclusao": 0},
        "data_min": {}, "data_max": {},
        "servicos_drenagem": pd.Series(dtype="int64"),
        "status_valores": pd.Series(dtype="int64"),
        "drenagem_temporada": 0, "drenagem_temporada_com_conclusao": 0,
        "conclusao_antes_abertura": 0,
    }

    # Coluna usada para reconhecer drenagem: serviço; se não houver, assunto
    col_filtro = mapa["servico"] or mapa["assunto"]

    leitor = pd.read_csv(caminho, sep=separador, encoding=encoding, dtype=str,
                         chunksize=TAMANHO_BLOCO, on_bad_lines="warn")
    for bloco in leitor:
        stats["linhas"] += len(bloco)

        # 1) preenchimento de cada campo encontrado
        for campo, coluna in mapa.items():
            if coluna:
                preenchido = bloco[coluna].notna() & (bloco[coluna].str.strip() != "")
                stats["preenchidos"][campo] += int(preenchido.sum())

        # 2) datas: quantas são válidas e qual o intervalo
        datas = {}
        for campo in ["data_abertura", "data_conclusao"]:
            if mapa[campo]:
                d = converter_data(bloco[mapa[campo]])
                datas[campo] = d
                stats["datas_validas"][campo] += int(d.notna().sum())
                if d.notna().any():
                    stats["data_min"][campo] = min(stats["data_min"].get(campo, d.min()), d.min())
                    stats["data_max"][campo] = max(stats["data_max"].get(campo, d.max()), d.max())

        if "data_abertura" in datas and "data_conclusao" in datas:
            erro = datas["data_conclusao"] < datas["data_abertura"]
            stats["conclusao_antes_abertura"] += int(erro.sum())

        # 3) valores de status
        if mapa["status"]:
            stats["status_valores"] = stats["status_valores"].add(
                bloco[mapa["status"]].value_counts(), fill_value=0)

        # 4) serviços de drenagem e recorte da temporada
        if col_filtro:
            mascara = bloco[col_filtro].fillna("").map(eh_drenagem)
            stats["servicos_drenagem"] = stats["servicos_drenagem"].add(
                bloco.loc[mascara, col_filtro].value_counts(), fill_value=0)
            if "data_abertura" in datas:
                na_temporada = mascara & datas["data_abertura"].between(
                    INICIO_TEMPORADA, FIM_TEMPORADA)
                stats["drenagem_temporada"] += int(na_temporada.sum())
                if "data_conclusao" in datas:
                    stats["drenagem_temporada_com_conclusao"] += int(
                        (na_temporada & datas["data_conclusao"].notna()).sum())
    return stats


# ---------------------------------------------------------------------------
# Diagnóstico: o que falta e o que fazer
# ---------------------------------------------------------------------------

IMPACTO = {
    "data_abertura": ("Sem data de abertura não há série diária nem recorte da temporada. "
                      "Bloqueia o projeto.",
                      "Verificar o glossário: pode haver uma coluna 'Data' genérica ou o "
                      "protocolo pode codificar a data. Sem isso, trocar de fonte."),
    "data_conclusao": ("Sem data de conclusão não dá para calcular backlog diário "
                       "(pendentes em cada dia) nem tempo de atendimento.",
                       "(a) Usar 'Data do parecer' dos chamados finalizados como data de "
                       "fechamento aproximada. (b) Trocar o backlog por 'pressão de "
                       "demanda': chamados de drenagem abertos nos 30 dias anteriores por "
                       "10 mil hab. (c) Usar o status atual só como foto final (pendentes "
                       "na data da extração), sem série diária."),
    "servico": ("Sem serviço, o filtro de drenagem fica menos preciso.",
                "Filtrar por 'assunto' (ou 'tema') com as mesmas palavras-chave."),
    "distrito": ("Sem distrito não há cruzamento com Censo, relevo e o índice de "
                 "propensão, que são por distrito.",
                 "(a) Se houver latitude/longitude: junção espacial com os limites de "
                 "distritos do GeoSampa (geopandas.sjoin). (b) Se só houver "
                 "subprefeitura: rebaixar a análise para 32 subprefeituras."),
    "status": ("Sem status não se distingue pendente de finalizado.",
               "Considerar 'finalizado' todo chamado com data de conclusão preenchida."),
}


def montar_relatorio(lista_stats):
    linhas = ["# Validação do SP156 — Rua Avisada", ""]
    faltando_geral = {}  # campo -> lista de arquivos onde falta

    for s in lista_stats:
        linhas += [f"## Arquivo: {s['arquivo']}",
                   f"- Encoding: `{s['encoding']}` · separador: `{s['separador']}` · "
                   f"linhas: {fmt(s['linhas'])}", "",
                   "### Colunas do arquivo",
                   ", ".join(f"`{c}`" for c in s["colunas"]), "",
                   "### Campos do modelo", "",
                   "| Campo | Coluna encontrada | % preenchido |",
                   "|---|---|---|"]
        for campo, coluna in s["mapa"].items():
            pct = 100 * s["preenchidos"][campo] / s["linhas"] if s["linhas"] else 0
            if coluna:
                linhas.append(f"| {campo} | `{coluna}` | {pct:.1f}% |")
            else:
                linhas.append(f"| {campo} | **NÃO ENCONTRADA** | — |")
            # campo crítico ausente ou quase vazio (<= 50%) entra no diagnóstico
            if campo in CAMPOS_CRITICOS and (not coluna or pct <= 50):
                faltando_geral.setdefault(campo, []).append(s["arquivo"])

        linhas += ["", "### Datas"]
        for campo in ["data_abertura", "data_conclusao"]:
            if s["mapa"][campo]:
                validas = s["datas_validas"][campo]
                linhas.append(f"- {campo}: {fmt(validas)} datas válidas; de "
                              f"{s['data_min'].get(campo)} a {s['data_max'].get(campo)}")
        if s["conclusao_antes_abertura"]:
            linhas.append(f"- Atenção: {s['conclusao_antes_abertura']} chamados com "
                          "conclusão antes da abertura (descartar no tratamento).")
        if s["mapa"]["data_conclusao"] and "parecer" in normalizar(s["mapa"]["data_conclusao"]):
            linhas.append("- Obs.: a 'conclusão' encontrada é a data do PARECER. Serve como "
                          "fechamento aproximado: confirme no glossário.")

        linhas += ["", "### Status (valores encontrados)"]
        for valor, qtd in s["status_valores"].sort_values(ascending=False).head(15).items():
            linhas.append(f"- {valor}: {fmt(qtd)}")

        linhas += ["", "### Serviços que parecem de drenagem (confira a lista!)"]
        for valor, qtd in s["servicos_drenagem"].sort_values(ascending=False).head(30).items():
            linhas.append(f"- {valor}: {fmt(qtd)}")
        periodo = (f"{INICIO_TEMPORADA:%m/%Y}–{FIM_TEMPORADA:%m/%Y}")
        linhas += [f"", f"- Chamados de drenagem na temporada {periodo}: "
                   f"**{fmt(s['drenagem_temporada'])}** (com data de conclusão: "
                   f"{fmt(s['drenagem_temporada_com_conclusao'])})", ""]

    linhas += ["## Diagnóstico", ""]
    if not faltando_geral:
        linhas.append("Todos os campos críticos foram encontrados e estão preenchidos. "
                      "O modelo pode seguir como planejado.")
    for campo in CAMPOS_CRITICOS:
        if campo in faltando_geral:
            impacto, alternativa = IMPACTO[campo]
            linhas += [f"### Falta: {campo} (em: {', '.join(faltando_geral[campo])})",
                       f"- Impacto: {impacto}",
                       f"- Alternativa: {alternativa}", ""]
    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    arquivos = sys.argv[1:]
    if not arquivos:
        print("Uso: python scripts/01_validar_sp156.py arquivo1.csv [arquivo2.csv ...]")
        sys.exit(1)

    resultados = []
    for arq in arquivos:
        print(f"Lendo {arq} ...")
        resultados.append(analisar_arquivo(arq))

    relatorio = montar_relatorio(resultados)
    print("\n" + relatorio)

    saida = Path("data/raw/staging/validacao_sp156.md")
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(relatorio, encoding="utf-8")
    print(f"\nRelatório salvo em {saida}")
