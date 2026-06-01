# main.py — Dashboard de Acervo Criminal
# PyScript 2024 + pandas + Chart.js (via JS bridge)

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

import asyncio
import json
from datetime import date
from io import StringIO

import pandas as pd
from pyscript import document, fetch, window
from pyodide.ffi import create_proxy

TODAY = date.today()
TODAY_TS = pd.Timestamp(TODAY)

# Ordem de precedência para derivar a fase atual (mais avançada → mais inicial)
MARCOS = [
    ("Contrarrazões de Apelação", "Recursal (contrarrazões)"),
    ("Razões de Apelação",        "Recursal (apelação)"),
    ("Defesa Prévia",             "Instrução"),
    ("Denúncia",                  "Denunciado"),
    ("Relatório Final",           "Pós-relatório"),
    ("Distribuição",              "Recebido / em análise"),
]
FASE_LABELS = [m[1] for m in reversed(MARCOS)]

DATE_COLS = [
    "Distribuição", "Relatório Final", "Denúncia",
    "Defesa Prévia", "Razões de Apelação", "Contrarrazões de Apelação",
]

PAGE_SIZE = 50

# Estado global
df_global = None
df_filtered = None
current_page = 0


# ---------------------------------------------------------------------------
# Derivação de colunas
# ---------------------------------------------------------------------------

def calc_fase(row):
    for col, label in MARCOS:
        if pd.notna(row.get(col)):
            return label
    return "Recebido / em análise"


def enrich(df):
    for col in DATE_COLS:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    df["fase"] = df.apply(calc_fase, axis=1)
    df["dias_desde_distribuicao"] = (TODAY_TS - df["Distribuição"]).dt.days
    df["sem_denuncia"] = df["Denúncia"].isna()
    df["gargalo"] = df["sem_denuncia"] & (df["dias_desde_distribuicao"] > 365)
    return df


# ---------------------------------------------------------------------------
# Filtros
# ---------------------------------------------------------------------------

def _get_multi(el_id):
    el = document.getElementById(el_id)
    if not el:
        return []
    nodes = el.querySelectorAll("input")
    result = []
    for i in range(nodes.length):
        cb = nodes.item(i)
        if cb.checked:
            result.append(cb.value)
    return result


def _get_val(el_id, default=""):
    el = document.getElementById(el_id)
    return el.value if el else default


def get_filter_values():
    return {
        "localizacao": _get_multi("f-localizacao"),
        "vara":        _get_multi("f-vara"),
        "classe":      _get_multi("f-classe"),
        "fase":        _get_multi("f-fase"),
        "assunto":     _get_val("f-assunto").strip().lower(),
        "sigilo":      _get_val("f-sigilo", "todos"),
        "reu_preso":   _get_val("f-reu-preso", "todos"),
        "dist_de":     _get_val("f-dist-de"),
        "dist_ate":    _get_val("f-dist-ate"),
        "busca":       _get_val("f-busca").strip().lower(),
    }


def apply_df_filters(df, f):
    if f["localizacao"]:
        df = df[df["Localização Atual"].isin(f["localizacao"])]
    if f["vara"]:
        df = df[df["Vara"].isin(f["vara"])]
    if f["classe"]:
        df = df[df["Classe"].isin(f["classe"])]
    if f["fase"]:
        df = df[df["fase"].isin(f["fase"])]
    if f["assunto"]:
        df = df[df["Assunto"].str.lower().str.contains(f["assunto"], na=False)]
    if f["sigilo"] not in ("todos", ""):
        df = df[df["Sigilo"].str.lower() == f["sigilo"].lower()]
    if f["reu_preso"] == "preso":
        df = df[df["reu_preso"] == True]
    elif f["reu_preso"] == "solto":
        df = df[df["reu_preso"] == False]
    if f["dist_de"]:
        df = df[df["Distribuição"] >= pd.Timestamp(f["dist_de"])]
    if f["dist_ate"]:
        df = df[df["Distribuição"] <= pd.Timestamp(f["dist_ate"])]
    if f["busca"]:
        mask = (
            df["Número do Processo"].str.lower().str.contains(f["busca"], na=False)
            | df["Controle"].astype(str).str.lower().str.contains(f["busca"], na=False)
        )
        df = df[mask]
    return df


# ---------------------------------------------------------------------------
# KPIs
# ---------------------------------------------------------------------------

def update_kpis(df):
    total = len(df)
    presos    = int(df["reu_preso"].sum())
    sem_den   = int(df["sem_denuncia"].sum())
    garg_df   = df[df["gargalo"]]
    mais_ant  = int(garg_df["dias_desde_distribuicao"].max()) if len(garg_df) else 0
    recursal  = int(df["fase"].str.startswith("Recursal").sum())
    pct_rec   = round(100 * recursal / total, 1) if total else 0.0

    def _set(el_id, val):
        el = document.getElementById(el_id)
        if el:
            el.textContent = str(val)

    _set("kpi-total",      total)
    _set("kpi-presos",     presos)
    _set("kpi-sem-den",    sem_den)
    _set("kpi-mais-ant",   f"{mais_ant} d")
    _set("kpi-recursal",   f"{pct_rec}%")


# ---------------------------------------------------------------------------
# Charts (via JS bridge)
# ---------------------------------------------------------------------------

def _jcall(fn, *args):
    """Chama window.<fn>(...) passando args como strings JSON."""
    parts = [json.dumps(a) for a in args]
    window.callChartFn(fn, ", ".join(parts))


def update_charts(df):
    # 1. Funil de fases
    fase_counts = df["fase"].value_counts()
    labels = FASE_LABELS
    data   = [int(fase_counts.get(f, 0)) for f in labels]
    window.updateBarH("chart-fases", json.dumps(labels), json.dumps(data))

    # 2. Carga por Promotoria
    loc = df.groupby("Localização Atual").size().sort_values(ascending=False)
    loc_labels = [
        l.replace("Promotor de Justiça de Piracicaba", "PJ Piracicaba")
         .replace("º ", "º ")
        for l in loc.index.tolist()
    ]
    window.updateBarH("chart-promotoria", json.dumps(loc_labels), json.dumps(loc.values.tolist()))

    # 3. Composição por Classe (rosca)
    cls = df["Classe"].value_counts().head(10)
    window.updateDoughnut("chart-classe", json.dumps(cls.index.tolist()), json.dumps(cls.values.tolist()))

    # 4. Top 10 Assuntos
    ass = df["Assunto"].value_counts()
    top = ass.head(10)
    outros = int(ass.iloc[10:].sum()) if len(ass) > 10 else 0
    a_labels = top.index.tolist()
    a_data   = top.values.tolist()
    if outros:
        a_labels.append("Outros")
        a_data.append(outros)
    window.updateBarH("chart-assuntos", json.dumps(a_labels), json.dumps(a_data))

    # 5. Distribuições por ano
    by_year = df.groupby(df["Distribuição"].dt.year).size()
    window.updateLine(
        "chart-tempo",
        json.dumps([str(int(y)) for y in by_year.index.tolist()]),
        json.dumps(by_year.values.tolist()),
    )

    # 6. Aging de gargalos por Promotoria
    garg = (
        df[df["gargalo"]]
        .groupby("Localização Atual")["dias_desde_distribuicao"]
        .max()
        .sort_values(ascending=False)
        .head(10)
    )
    g_labels = [
        l.replace("Promotor de Justiça de Piracicaba", "PJ Piracicaba")
        for l in garg.index.tolist()
    ]
    window.updateBarH("chart-aging", json.dumps(g_labels), json.dumps(garg.values.tolist()))


# ---------------------------------------------------------------------------
# Tabela
# ---------------------------------------------------------------------------

def render_table(df, page=0):
    global current_page
    current_page = page
    total       = len(df)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    start = page * PAGE_SIZE
    end   = min(start + PAGE_SIZE, total)
    chunk = df.iloc[start:end]

    rows = []
    for _, r in chunk.iterrows():
        is_preso = bool(r["reu_preso"])
        is_garg  = bool(r.get("gargalo", False))
        row_cls  = ' class="row-preso"' if is_preso else (' class="row-gargalo"' if is_garg else "")
        dist = r["Distribuição"].strftime("%d/%m/%Y") if pd.notna(r["Distribuição"]) else "—"
        esaj = r.get("e-SAJ", "")
        link = f'<a href="{esaj}" target="_blank" rel="noopener" class="btn-esaj">e-SAJ</a>' if esaj and str(esaj) != "nan" else "—"
        badges = ""
        if is_preso:
            badges += '<span class="badge-preso">PRESO</span> '
        if is_garg:
            badges += '<span class="badge-gargalo">GARGALO</span>'
        rows.append(
            f'<tr{row_cls}>'
            f'<td class="td-proc">{r["Número do Processo"]}</td>'
            f'<td>{r["Localização Atual"]}</td>'
            f'<td>{r.get("Vara","—")}</td>'
            f'<td>{r.get("Classe","—")}</td>'
            f'<td class="td-assunto" title="{r.get("Assunto","")}">{r.get("Assunto","—")}</td>'
            f'<td>{dist}</td>'
            f'<td>{r["fase"]}</td>'
            f'<td>{badges}</td>'
            f'<td>{r.get("Sigilo","—")}</td>'
            f'<td>{link}</td>'
            f'</tr>'
        )

    prev_btn = '<button onclick="window.goPage(-1)">&#8592; Anterior</button>' if page > 0 else ""
    next_btn = f'<button onclick="window.goPage(1)">Próxima &#8594;</button>' if page < total_pages - 1 else ""

    html = (
        f'<div class="table-info">'
        f'Exibindo {start+1}–{end} de {total} feitos'
        f'<span class="pagination">{prev_btn} Pág. {page+1}/{total_pages} {next_btn}</span>'
        f'</div>'
        f'<div class="table-overflow">'
        f'<table class="data-table">'
        f'<thead><tr>'
        f'<th>Processo</th><th>Promotoria</th><th>Vara</th><th>Classe</th>'
        f'<th>Assunto</th><th>Distribuição</th><th>Fase</th>'
        f'<th>Situação</th><th>Sigilo</th><th>Link</th>'
        f'</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody>'
        f'</table></div>'
    )
    document.getElementById("table-container").innerHTML = html


# ---------------------------------------------------------------------------
# Motor de filtros — ponto de entrada principal
# ---------------------------------------------------------------------------

def apply_filters(*args):
    global df_filtered
    if df_global is None:
        return
    f = get_filter_values()
    df_filtered = apply_df_filters(df_global.copy(), f)
    update_kpis(df_filtered)
    update_charts(df_filtered)
    render_table(df_filtered, 0)


# Pagination callback (chamada de onclick no HTML)
def go_page(delta, *args):
    global df_filtered, current_page
    if df_filtered is None:
        return
    total_pages = max(1, (len(df_filtered) + PAGE_SIZE - 1) // PAGE_SIZE)
    new_page = max(0, min(total_pages - 1, current_page + int(delta)))
    render_table(df_filtered, new_page)


window.goPage = create_proxy(go_page)


# ---------------------------------------------------------------------------
# População dos dropdowns de filtro
# ---------------------------------------------------------------------------

def populate_filters(df):
    def fill_select(el_id, values):
        el = document.getElementById(el_id)
        if not el:
            return
        parts = []
        for v in sorted(str(x) for x in values if pd.notna(x)):
            v_esc = v.replace('"', "&quot;").replace("<", "&lt;")
            parts.append(
                f'<label class="cb-item">'
                f'<input type="checkbox" value="{v_esc}">'
                f'<span>{v_esc}</span></label>'
            )
        el.innerHTML = "".join(parts)

    fill_select("f-localizacao", df["Localização Atual"].unique())
    fill_select("f-vara",        df["Vara"].unique())
    fill_select("f-classe",      df["Classe"].unique())
    fill_select("f-fase",        FASE_LABELS)

    # Registrar listeners
    _apply = create_proxy(apply_filters)
    for fid in ["f-localizacao", "f-vara", "f-classe", "f-fase",
                "f-sigilo", "f-reu-preso"]:
        el = document.getElementById(fid)
        if el:
            el.addEventListener("change", _apply)

    for fid in ["f-assunto", "f-dist-de", "f-dist-ate", "f-busca"]:
        el = document.getElementById(fid)
        if el:
            el.addEventListener("input", _apply)

    # Botão limpar
    def clear_filters(*args):
        for fid in ["f-localizacao", "f-vara", "f-classe", "f-fase"]:
            el = document.getElementById(fid)
            if el:
                nodes = el.querySelectorAll("input")
                for i in range(nodes.length):
                    nodes.item(i).checked = False
        for fid in ["f-sigilo", "f-reu-preso"]:
            el = document.getElementById(fid)
            if el:
                el.value = "todos"
        for fid in ["f-assunto", "f-dist-de", "f-dist-ate", "f-busca"]:
            el = document.getElementById(fid)
            if el:
                el.value = ""
        apply_filters()

    btn = document.getElementById("btn-limpar")
    if btn:
        btn.addEventListener("click", create_proxy(clear_filters))

    # Toggle sidebar mobile
    def toggle_sidebar(*args):
        sb = document.getElementById("sidebar")
        if sb:
            if " open" in sb.className:
                sb.className = sb.className.replace(" open", "")
            else:
                sb.className += " open"

    btn_toggle = document.getElementById("btn-toggle-filters")
    if btn_toggle:
        btn_toggle.addEventListener("click", create_proxy(toggle_sidebar))


# ---------------------------------------------------------------------------
# Inicialização assíncrona
# ---------------------------------------------------------------------------

async def init():
    try:
        resp = await fetch("dados/relatorio.csv")
        text = await resp.text()

        df = pd.read_csv(StringIO(text))
        df = enrich(df)

        global df_global
        df_global = df

        populate_filters(df)
        window.initCharts()
        apply_filters()

        el_ref = document.getElementById("data-ref")
        if el_ref:
            el_ref.textContent = TODAY.strftime("%d/%m/%Y")

        document.getElementById("splash").style.display = "none"
        document.getElementById("app").style.display = "block"

    except Exception as exc:
        el = document.getElementById("splash-msg")
        if el:
            el.textContent = f"Erro ao carregar dados: {exc}"
        import traceback
        print(traceback.format_exc())


asyncio.ensure_future(init())
