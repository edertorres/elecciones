#!/usr/bin/env python3
"""
Elecciones Risaralda — Dashboard Electoral
NiceGUI + Plotly + core.py
"""

import asyncio
import json
import os
import unicodedata
from io import StringIO

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from nicegui import app, run, ui
from core import (
    PDF_DIR,
    compile_pdf,
    compute_curules_from_df,
    generate_typst_pro,
    generate_typst_national_dept_table,
    generate_web_html,
    get_cache_info,
    get_cache_info,
    load_cache,
    scrape_official_data,
)

# ---------------------------------------------------------------------------
# Constantes / helpers
# ---------------------------------------------------------------------------

# Lista estática de departamentos de Colombia para no depender de nomencladores externos.
DEPT_OPTS = {
    "NACIONAL": {"code": "00", "name": "NACIONAL"},
    "ANTIOQUIA": {"code": "0100", "name": "ANTIOQUIA"},
    "ATLANTICO": {"code": "0300", "name": "ATLANTICO"},
    "BOGOTA D.C.": {"code": "1600", "name": "BOGOTA D.C."},
    "BOLIVAR": {"code": "0500", "name": "BOLIVAR"},
    "BOYACA": {"code": "0700", "name": "BOYACA"},
    "CALDAS": {"code": "0900", "name": "CALDAS"},
    "CAQUETA": {"code": "1100", "name": "CAQUETA"},
    "CAUCA": {"code": "1300", "name": "CAUCA"},
    "CESAR": {"code": "1500", "name": "CESAR"},
    "CORDOBA": {"code": "1700", "name": "CORDOBA"},
    "CUNDINAMARCA": {"code": "1900", "name": "CUNDINAMARCA"},
    "CHOCO": {"code": "2100", "name": "CHOCO"},
    "HUILA": {"code": "2300", "name": "HUILA"},
    "LA GUAJIRA": {"code": "4400", "name": "LA GUAJIRA"},
    "MAGDALENA": {"code": "2500", "name": "MAGDALENA"},
    "META": {"code": "2700", "name": "META"},
    "NARIÑO": {"code": "2900", "name": "NARIÑO"},
    "N. DE SANTANDER": {"code": "3100", "name": "N. DE SANTANDER"},
    "QUINDIO": {"code": "2600", "name": "QUINDIO"},
    "RISARALDA": {"code": "2400", "name": "RISARALDA"},
    "SANTANDER": {"code": "3300", "name": "SANTANDER"},
    "SUCRE": {"code": "3500", "name": "SUCRE"},
    "TOLIMA": {"code": "3700", "name": "TOLIMA"},
    "VALLE": {"code": "3900", "name": "VALLE"},
    "ARAUCA": {"code": "4800", "name": "ARAUCA"},
    "CASANARE": {"code": "5000", "name": "CASANARE"},
    "PUTUMAYO": {"code": "5200", "name": "PUTUMAYO"},
    "SAN ANDRES": {"code": "5400", "name": "SAN ANDRES"},
    "AMAZONAS": {"code": "5600", "name": "AMAZONAS"},
    "GUAINIA": {"code": "5800", "name": "GUAINIA"},
    "GUAVIARE": {"code": "6000", "name": "GUAVIARE"},
    "VAUPES": {"code": "6400", "name": "VAUPES"},
    "VICHADA": {"code": "6800", "name": "VICHADA"},
    "CONSULADOS": {"code": "8800", "name": "CONSULADOS"},
}


APP_TITLE = "Elecciones — Dashboard Electoral"


def _strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    )


# ---------------------------------------------------------------------------
# CSS — tema claro profesional
# ---------------------------------------------------------------------------
LIGHT_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
body, .q-page, .nicegui-content { font-family: 'Inter', sans-serif !important; background: #f5f7fa !important; }
.q-drawer { border-right: 1px solid #e2e8f0 !important; }
.metric-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 18px 20px;
    text-align: center;
    border: 1px solid #e2e8f0;
    box-shadow: 0 1px 3px rgba(0,0,0,.06);
}
.metric-value { font-size: 1.7rem; font-weight: 700; color: #1d4ed8; }
.metric-label { font-size: .75rem; font-weight: 500; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }
.brand-title { font-size: 1.15rem; font-weight: 700; letter-spacing: -.02em; }
.status-badge {
    display: inline-block;
    padding: 3px 12px;
    border-radius: 20px;
    font-size: .72rem;
    font-weight: 600;
    background: #dbeafe;
    color: #1d4ed8;
}
.report-info {
    background: #1e293b;
    color: #f8fafc;
    padding: 8px 16px;
    border-radius: 8px;
    font-weight: 800;
    font-size: 1.1rem;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
}
</style>
"""

# ---------------------------------------------------------------------------
# Gráficos Plotly (tema claro)
# ---------------------------------------------------------------------------


def build_party_bar(df: pd.DataFrame, municipio: str | None = None) -> go.Figure:
    src = df if municipio is None else df[df["Municipio"] == municipio]
    party_votes = (
        src.groupby("Partido")["Votos"]
        .sum()
        .sort_values(ascending=True)
        .tail(10)
        .reset_index()
    )
    fig = px.bar(
        party_votes,
        x="Votos",
        y="Partido",
        orientation="h",
        color="Votos",
        color_continuous_scale="Blues",
        text="Votos",
    )
    fig.update_layout(
        margin=dict(l=0, r=10, t=10, b=0),
        paper_bgcolor="white",
        plot_bgcolor="white",
        font_color="#1e293b",
        showlegend=False,
        coloraxis_showscale=False,
        xaxis=dict(showgrid=False, visible=False),
        yaxis=dict(showgrid=False),
        height=380,
    )
    fig.update_traces(texttemplate="%{text:,}", textposition="outside")
    return fig


# ---------------------------------------------------------------------------
# Página principal
# ---------------------------------------------------------------------------
@ui.page("/")
async def index():
    state = app.storage.user
    state.setdefault("df_full_json", None)
    state.setdefault("stats_json", None)
    state.setdefault("etype", "Presidencia")
    state.setdefault("dept_sel", "RISARALDA")
    state.setdefault("circ_sel", "** TODAS LAS CIRCUNSCRIPCIONES **")
    state.setdefault("muni_sel", "Todo el Ámbito")
    state.setdefault("source", "Portal Descargas (Medios)")
    state.setdefault("admin_user", "")
    state.setdefault("admin_pass", "")

    ui.dark_mode(False)
    ui.add_head_html(LIGHT_CSS)

    def get_df() -> pd.DataFrame | None:
        raw = state.get("df_full_json") or state.get("df_json")
        if not raw:
            return None
        df = pd.read_json(StringIO(raw), orient="records")
        circ = state.get("circ_sel")
        if (
            circ
            and circ != "** TODAS LAS CIRCUNSCRIPCIONES **"
            and "Circunscripcion" in df.columns
        ):
            df = df[df["Circunscripcion"] == circ]
        return df

    def get_stats() -> dict:
        raw = state.get("stats_json")
        return json.loads(raw) if raw else {}

    # ---- HEADER ----
    with ui.header(elevated=False).classes(
        "bg-white text-slate-900 border-b py-2 px-6 items-center justify-between"
    ):
        with ui.row().classes("items-center gap-4"):
            ui.button(on_click=lambda: left_drawer.toggle(), icon="menu").props(
                "flat round color=primary"
            )
            ui.label("ELECTION DASHBOARD").classes("brand-title text-primary")
            status_label = ui.label("Sin datos").classes("status-badge")

        # Area muy visible para el Boletín
        with ui.row().classes("items-center gap-2"):
            report_label = ui.label("Borrador").classes("report-info")

            async def download_original_pdf_shortcut():
                etype_name = "Presidencia"
                etype_code = "PR"
                dept_name = dept_select.value
                dept_code = DEPT_OPTS.get(dept_name, {}).get("code", "2400")
                stats_map = get_stats()
                b_num = stats_map.get("__REPORTE__", {}).get("boletin", "---")

                if b_num == "---":
                    ui.notify(
                        "No hay un boletín cargado para descargar el PDF",
                        type="warning",
                    )
                    return

                fname = f"boletin_{etype_code}_{dept_code}_{b_num}.pdf"
                local_path = os.path.join(PDF_DIR, fname)

                if os.path.exists(local_path):
                    ui.download(local_path)
                    ui.notify(f"Descargando PDF original: {fname}", type="positive")
                else:
                    ui.notify(
                        f"El PDF original no se encuentra en el servidor ({fname}). Intenta 'Obtener datos' de nuevo.",
                        type="warning",
                    )

            ui.button(
                on_click=download_original_pdf_shortcut, icon="picture_as_pdf"
            ).props("flat round color=white").classes("bg-primary shadow-sm").tooltip(
                "Descargar PDF Original (Registraduría)"
            )

    # ---- SIDEBAR ----
    with (
        ui.left_drawer(value=True)
        .classes("bg-white p-4")
        .props("width=280 bordered") as left_drawer
    ):
        ui.label("Configuración").classes(
            "text-xs text-slate-400 uppercase tracking-widest mb-4"
        )

        ui.label("Ámbito / Departamento").classes("text-xs text-slate-400 mb-1")
        initial_dept = state.get("dept_sel", "RISARALDA")
        if initial_dept not in DEPT_OPTS:
            # Fallback a RISARALDA o al primer disponible
            initial_dept = (
                "RISARALDA" if "RISARALDA" in DEPT_OPTS else list(DEPT_OPTS.keys())[0]
            )

        dept_select = (
            ui.select(
                options={k: k for k in DEPT_OPTS.keys()},
                value=initial_dept,
                with_input=True,
            )
            .classes("w-full mb-4")
            .props("outlined dense")
        )

        ui.label("Elecciones Presidenciales").classes(
            "text-xs font-bold text-slate-500 mb-4 mt-2 tracking-widest uppercase"
        )

        ui.label("Fuente de Datos").classes("text-xs text-slate-400 mb-1")
        source_select = (
            ui.select(
                ["Portal Descargas (Medios)"],
                value="Portal Descargas (Medios)",
            )
            .classes("w-full mb-2")
            .props("outlined dense")
        )
        source_select.on_value_change(lambda e: state.update({"source": e.value}))
        state.update({"source": "Portal Descargas (Medios)"})

        with ui.expansion("Credenciales (Medios)", icon="key").classes(
            "w-full mb-4 border rounded"
        ):
            ui.label("Override Opcional").classes("text-[10px] text-slate-400 mb-2")
            user_input = ui.input("Usuario").props("dense outlined").classes("mb-2")
            user_input.on_value_change(lambda e: state.update({"admin_user": e.value}))
            pass_input = ui.input("Contraseña").props("dense outlined password")
            pass_input.on_value_change(lambda e: state.update({"admin_pass": e.value}))
            ui.label("Se usarán valores del servidor si se deja vacío").classes(
                "text-[10px] text-slate-400 mt-1"
            )

        scrape_btn = (
            ui.button("Obtener datos", icon="cloud_download")
            .classes("w-full mb-2")
            .props("color=primary no-caps")
        )

        cache_btn = (
            ui.button("Cargar caché local", icon="folder_open")
            .classes("w-full mb-2")
            .props("color=teal no-caps outline")
        )

        # Indicador de estado del caché
        cache_info_label = ui.label("").classes("text-xs text-slate-400 mb-4")

        def _update_cache_badge():
            """Actualiza la etiqueta de caché según el ámbito seleccionado."""
            dept_name = dept_select.value
            dept_code = DEPT_OPTS[dept_name]["code"]
            info = get_cache_info(dept_code)
            if info:
                from datetime import datetime, timezone

                ts = datetime.fromisoformat(info["timestamp"])
                local_str = ts.astimezone().strftime("%d/%m/%Y %H:%M")
                cache_info_label.set_text(
                    f"💾 Caché: {info['records']} registros · {local_str}"
                )
                cache_btn.props(remove="disable")
            else:
                cache_info_label.set_text("Sin caché local disponible")
                cache_btn.props("disable")

        _update_cache_badge()

        def _on_dept_change(e):
            _update_cache_badge()
            state.update({"dept_sel": e.value})
            # Si no es nacional y estamos en Senado, avisar? o dejarlo asi.

        dept_select.on_value_change(_on_dept_change)

        ui.separator().classes("my-2")
        ui.label("Filtro").classes(
            "text-xs text-slate-400 uppercase tracking-widest mb-2 mt-2"
        )

        muni_select = (
            ui.select(
                options=["Todo el Ámbito"],
                value="Todo el Ámbito",
                label="Filtrar por Ubicación",
            )
            .classes("w-full")
            .props("outlined dense")
        )

        circ_select = (
            ui.select(
                options=[
                    "TERRITORIAL DEPARTAMENTAL",
                    "NACIONAL",
                    "** TODAS LAS CIRCUNSCRIPCIONES **",
                ],
                value=state.get("circ_sel", "TERRITORIAL DEPARTAMENTAL"),
                label="Circunscripción",
            )
            .classes("w-full mt-2")
            .props("outlined dense")
        )

        ui.separator().classes("my-2")
        ui.label("v3.2 — filtros dinámicos").classes("text-xs text-slate-300 mt-4")

    # ---- MAIN ----
    main_container = ui.column().classes("w-full p-6 gap-4")
    metrics_row = None
    tabs_container = None

    # ---- Render functions ----
    def _get_filt(df_in: pd.DataFrame, m_in: str) -> pd.DataFrame:
        if df_in.empty:
            return df_in.copy()

        if m_in == "Todo el Ámbito":
            # Excluir el registro de consolidado para no duplicar votos en el total
            return df_in[df_in["Municipio"] != "** CONSOLIDADO **"].copy()

        elif m_in == "** CONSOLIDADO **":
            # Si el registro de consolidado ya viene del scraper, usarlo directamente
            if "** CONSOLIDADO **" in df_in["Municipio"].values:
                return df_in[df_in["Municipio"] == "** CONSOLIDADO **"].copy()

            # Si no existe (fallback), agrupar manualmente
            groups = ["Partido", "Candidato"]
            if "Circunscripcion" in df_in.columns:
                groups.append("Circunscripcion")
            f = df_in.groupby(groups, dropna=False).agg({"Votos": "sum"}).reset_index()
            p_totals = f.groupby("Partido")["Votos"].sum()
            f["Partido_Votos"] = f["Partido"].map(p_totals)
            f["P"] = (
                (f["Votos"] / f["Partido_Votos"] * 100)
                .fillna(0)
                .map(lambda x: f"{x:.2f}%")
            )
            f["Partido_P"] = "0%"
            f["Municipio"] = "** CONSOLIDADO **"
            return f.sort_values(
                by=["Partido_Votos", "Votos"], ascending=[False, False]
            )

        return df_in[df_in["Municipio"] == m_in].copy()

    def render_metrics(df: pd.DataFrame, muni: str):
        nonlocal metrics_row
        if metrics_row:
            metrics_row.clear()
        else:
            with main_container:
                metrics_row = ui.row().classes("w-full gap-4")

        filt = _get_filt(df, muni)

        # Intentar obtener total de votos válidos oficiales para la circunscripción
        stats = get_stats()
        circ_sel = state.get("circ_sel")
        total_votos = 0
        if stats and muni in stats:
            by_circ = stats[muni].get("by_circ", {})
            if circ_sel in by_circ:
                total_votos = int(by_circ[circ_sel].get("validos", 0))

        if total_votos == 0:
            total_votos = int(filt["Votos"].sum())

        n_candidatos = filt["Candidato"].nunique() if not filt.empty else 0
        n_partidos = filt["Partido"].nunique() if not filt.empty else 0
        n_units = filt["Municipio"].nunique() if not filt.empty else 0

        is_national = dept_select.value == "NACIONAL"
        unit_label = "Departamentos" if is_national else "Municipios"

        items = [
            ("Votos Totales", f"{total_votos:,}".replace(",", "."), "ballot"),
            ("Candidatos", str(n_candidatos), "people"),
            ("Partidos", str(n_partidos), "groups"),
            (unit_label, str(n_units), "location_city"),
        ]
        with metrics_row:
            for label, value, icon in items:
                with ui.column().classes("metric-card flex-1"):
                    ui.icon(icon, size="xs").classes("text-blue-600/60 mb-1")
                    ui.label(value).classes("metric-value")
                    ui.label(label).classes("metric-label")

    def render_tabs(df: pd.DataFrame, stats: dict, muni: str, etype_name: str):
        nonlocal tabs_container
        if tabs_container:
            tabs_container.clear()
        else:
            with main_container:
                tabs_container = ui.column().classes("w-full")

        filt = _get_filt(df, muni)
        etype_code = "PR"

        is_national = dept_select.value == "NACIONAL"
        unit_sub_label = "Departamentos" if is_national else "Municipios"

        with tabs_container:
            with (
                ui.tabs()
                .classes("w-full")
                .props(
                    "dense align=left active-color=primary indicator-color=primary"
                ) as tabs
            ):
                tab_resumen = ui.tab("Resumen", icon="bar_chart")
                tab_data = ui.tab("Datos", icon="table_chart")
                tab_export = ui.tab("Exportar", icon="download")

            with ui.tab_panels(tabs, value=tab_resumen).classes("w-full"):
                # ---- RESUMEN ----
                if tab_resumen:
                    with ui.tab_panel(tab_resumen):
                        ui.label("Top 10 Partidos").classes(
                            "text-sm font-semibold text-slate-500 mb-2 text-center"
                        )
                        bar_muni = (
                            muni
                            if muni not in ("Todo el Ámbito", "** CONSOLIDADO **")
                            else None
                        )
                        bar_fig = build_party_bar(df, bar_muni)
                        ui.plotly(bar_fig).classes(
                            "w-full rounded-xl border border-slate-200"
                        )

                # ---- DATOS ----
                with ui.tab_panel(tab_data):
                    # Summary header
                    if stats and muni in stats:
                        s = stats[muni]
                        circ_sel = state.get("circ_sel")

                        # Priorizar estadísticas por circunscripción para VÁLIDOS y BLANCOS
                        v_val = s.get("validos", 0)
                        v_bla = s.get("blancos", 0)
                        if "by_circ" in s and circ_sel in s["by_circ"]:
                            cs = s["by_circ"][circ_sel]
                            v_val = cs.get("validos", v_val)
                            v_bla = cs.get("blancos", v_bla)

                        with ui.row().classes(
                            "w-full bg-slate-50 p-3 rounded-lg border border-slate-200 mb-4 gap-12 items-center"
                        ):
                            with ui.column().classes("items-center"):
                                ui.label("VOTANTES").classes(
                                    "text-[10px] text-slate-500 font-bold"
                                )
                                ui.label(
                                    f"{s.get('votantes', 0):,}".replace(",", ".")
                                ).classes("text-sm font-bold text-slate-700")
                            with ui.column().classes("items-center"):
                                ui.label("VÁLIDOS").classes(
                                    "text-[10px] text-slate-500 font-bold"
                                )
                                ui.label(f"{v_val:,}".replace(",", ".")).classes(
                                    "text-sm font-bold text-slate-700"
                                )
                            with ui.column().classes("items-center"):
                                ui.label("MESAS").classes(
                                    "text-[10px] text-slate-500 font-bold"
                                )
                                ui.label(
                                    f"{s.get('mesas_info', '')} ({s.get('pmesas', '')})"
                                ).classes("text-sm font-bold text-slate-700")
                            ui.element("div").classes("flex-grow")
                            with ui.column().classes("items-end"):
                                ui.label("AVANCE").classes(
                                    "text-[10px] text-slate-500 font-bold"
                                )
                                ui.label(s.get("pmesas", "0%")).classes(
                                    "text-lg font-black text-blue-600"
                                )

                    display_df = filt.copy()
                    if muni != "Todo el Ámbito" and muni != "** CONSOLIDADO **":
                        display_df = display_df.drop(
                            columns=["Municipio"], errors="ignore"
                        )

                    columns_def = []
                    for col in display_df.columns:
                        label = col
                        if col == "Municipio":
                            label = "Ubicación"
                        columns_def.append(
                            {
                                "name": col,
                                "label": label,
                                "field": col,
                                "sortable": True,
                                "align": "right"
                                if col in ("Votos", "Partido_Votos")
                                else "left",
                            }
                        )

                    rows = display_df.to_dict("records")
                    tbl = ui.table(
                        columns=columns_def,
                        rows=rows,
                        row_key="Candidato",
                        pagination={
                            "rowsPerPage": 25,
                            "sortBy": "Votos",
                            "descending": True,
                        },
                    ).classes("w-full")
                    tbl.props("dense flat bordered separator=cell")
                    tbl.add_slot(
                        "top-right",
                        '<q-input borderless dense debounce="300" v-model="props.filter" placeholder="Buscar...">'
                        '<template v-slot:append><q-icon name="search" /></template>'
                        "</q-input>",
                    )
                    tbl.props('filter=""')

                # ---- EXPORTAR ----
                with ui.tab_panel(tab_export):
                    all_units = sorted(df["Municipio"].unique().tolist())

                    # --- Selector de unidades para exportar ---
                    ui.label(
                        f"Seleccionar {unit_sub_label.lower()} para el reporte"
                    ).classes("text-sm font-semibold text-slate-500 mb-1")
                    export_select = (
                        ui.select(
                            options=all_units,
                            value=all_units
                            if muni in ("Todo el Ámbito", "** CONSOLIDADO **")
                            else [muni],
                            label=unit_sub_label,
                            multiple=True,
                        )
                        .classes("w-full mb-4")
                        .props("outlined dense use-chips")
                    )

                    with ui.row().classes("w-full gap-2 mb-4"):

                        def _select_all():
                            export_select.value = all_units
                            export_select.update()

                        def _select_none():
                            export_select.value = []
                            export_select.update()

                        ui.button(
                            "Todos", on_click=_select_all, icon="select_all"
                        ).props("flat dense no-caps size=sm")
                        ui.button(
                            "Ninguno", on_click=_select_none, icon="deselect"
                        ).props("flat dense no-caps size=sm")

                    ui.separator().classes("mb-4")

                    # --- Opciones de reporte ---
                    ui.label("Opciones del reporte").classes(
                        "text-sm font-semibold text-slate-500 mb-1"
                    )
                    exclude_zero = ui.switch(
                        "Excluir candidatos con 0 votos",
                        value=False,
                    ).classes("mb-2")

                    with ui.row().classes("w-full items-center gap-2 mb-4"):
                        top_n_switch = ui.switch(
                            "Limitar candidatos por partido",
                            value=False,
                        )
                        top_n_input = (
                            ui.number(
                                label="Top N",
                                value=5,
                                min=1,
                                max=100,
                                step=1,
                            )
                            .classes("w-24")
                            .props("outlined dense")
                        )
                        top_n_input.bind_enabled_from(top_n_switch, "value")

                    dept_table_switch = ui.switch(
                        "Cuadro Consolidado (filas=Dptos. o Mpios., columnas=candidatos)",
                        value=False,
                    ).classes("mb-4")

                    ui.separator().classes("mb-4")

                    ui.label("Diseño de la tabla").classes(
                        "text-sm font-semibold text-slate-500 mb-1"
                    )
                    with ui.row().classes("w-full items-center gap-4 mb-4 flex-wrap"):
                        page_width_input = (
                            ui.number(
                                label="Ancho (cm)",
                                value=8.5,
                                min=5.0,
                                max=30.0,
                                step=0.1,
                                format="%.1f",
                            )
                            .classes("w-28")
                            .props("outlined dense")
                        )
                        row_radius_input = (
                            ui.number(
                                label="Radio zebra (pt)",
                                value=2,
                                min=0,
                                max=20,
                                step=0.5,
                                format="%.1f",
                            )
                            .classes("w-28")
                            .props("outlined dense")
                        )
                        row_inset_input = (
                            ui.number(
                                label="Interlineado (pt)",
                                value=2,
                                min=1,
                                max=20,
                                step=0.5,
                                format="%.1f",
                            )
                            .classes("w-28")
                            .props("outlined dense")
                        )

                    with ui.row().classes("w-full gap-6 flex-wrap"):
                        # -- PDF --
                        with ui.card().classes("flex-1 min-w-[260px]"):
                            ui.label("Reporte PDF").classes(
                                "text-lg font-semibold mb-2"
                            )
                            ui.label(
                                "Una página por municipio, o cuadro nacional por deptos (switch arriba)"
                            ).classes("text-sm text-slate-400 mb-4")

                            async def download_pdf():
                                df_curr = get_df()
                                stats_curr = get_stats()
                                sel = export_select.value
                                if not sel or df_curr is None:
                                    ui.notify(
                                        "Seleccione municipios y asegúrese de tener datos cargados",
                                        type="warning",
                                    )
                                    return
                                df_exp = df_curr[df_curr["Municipio"].isin(sel)]
                                stats_pass = {
                                    m: stats_curr.get(m)
                                    for m in sel
                                    if stats_curr.get(m)
                                }
                                suffix = (
                                    sel[0].lower().replace(" ", "_")
                                    if len(sel) == 1
                                    else "multi"
                                )
                                fname = f"reporte_{etype_code.lower()}_{suffix}.typ"
                                top_n = (
                                    int(top_n_input.value)
                                    if top_n_switch.value
                                    else None
                                )
                                if dept_table_switch.value:
                                    generate_typst_national_dept_table(
                                        df_exp,
                                        fname,
                                        stats=stats_pass,
                                        top_n=top_n,
                                        exclude_zero_votes=exclude_zero.value,
                                        circ_sel=state.get("circ_sel"),
                                        row_radius=float(row_radius_input.value or 2),
                                        row_inset_y=float(row_inset_input.value or 4),
                                        page_width=float(
                                            page_width_input.value or 8.5
                                        ),
                                        row_label="DEPARTAMENTO"
                                        if dept_select.value == "NACIONAL"
                                        else "MUNICIPIO",
                                    )
                                else:
                                    generate_typst_pro(
                                        df_exp,
                                        "",
                                        fname,
                                        stats=stats_pass,
                                        etype_label=etype_name.upper(),
                                        exclude_zero_votes=exclude_zero.value,
                                        top_n=top_n,
                                        circ_sel=state.get("circ_sel"),
                                        row_radius=float(row_radius_input.value or 2),
                                        row_inset_y=float(row_inset_input.value or 4),
                                        page_width=float(
                                            page_width_input.value or 8.5
                                        ),
                                    )
                                pdf = compile_pdf(fname)
                                if pdf.endswith(".pdf") and os.path.exists(pdf):
                                    ui.notify(
                                        f"PDF generado: {len(sel)} página(s)",
                                        type="positive",
                                    )
                                    ui.download(pdf)
                                else:
                                    ui.notify(f"Error: {pdf}", type="negative")

                            ui.button(
                                "Generar y descargar PDF",
                                icon="picture_as_pdf",
                                on_click=download_pdf,
                            ).props("color=primary no-caps").classes("w-full")

                        # -- PDF ORIGINAL REGISTRADURÍA --
                        with ui.card().classes(
                            "flex-1 min-w-[260px] bg-slate-50 border-dashed"
                        ):
                            ui.label("PDF Original (Registraduría)").classes(
                                "text-lg font-semibold mb-2"
                            )
                            ui.label("Documento oficial descargado del portal").classes(
                                "text-sm text-slate-400 mb-4"
                            )

                            async def download_original_pdf():
                                etype_name = "Presidencia"
                                etype_code = "PR"
                                dept_name = dept_select.value
                                dept_code = DEPT_OPTS.get(dept_name, {}).get(
                                    "code", "2400"
                                )
                                stats_map = get_stats()
                                b_num = stats_map.get("__REPORTE__", {}).get(
                                    "boletin", "---"
                                )

                                if b_num == "---":
                                    ui.notify(
                                        "Cargue datos primero para habilitar esta descarga",
                                        type="warning",
                                    )
                                    return

                                fname = f"boletin_{etype_code}_{dept_code}_{b_num}.pdf"
                                local_path = os.path.join(PDF_DIR, fname)

                                if os.path.exists(local_path):
                                    ui.download(local_path)
                                    ui.notify(f"Descargando {fname}", type="positive")
                                else:
                                    ui.notify(
                                        "Archivo no encontrado en el servidor. Intente un nuevo scrape.",
                                        type="negative",
                                    )

                            ui.button(
                                "Descargar PDF Original",
                                icon="cloud_download",
                                on_click=download_original_pdf,
                            ).props("color=blue-grey no-caps").classes("w-full")

                        # -- CSV --
                        with ui.card().classes("flex-1 min-w-[260px]"):
                            ui.label("Datos CSV").classes("text-lg font-semibold mb-2")
                            ui.label(f"{len(filt)} registros").classes(
                                "text-sm text-slate-400 mb-4"
                            )

                            async def download_csv():
                                sel = export_select.value
                                if not sel:
                                    ui.notify(
                                        "Seleccione al menos un municipio",
                                        type="warning",
                                    )
                                    return
                                df_exp = df[df["Municipio"].isin(sel)].copy()
                                suffix = (
                                    sel[0].lower().replace(" ", "_")
                                    if len(sel) == 1
                                    else "multi"
                                )

                                if dept_table_switch.value:
                                    if exclude_zero.value:
                                        df_exp = df_exp[df_exp["Votos"] > 0]

                                    circ_sel = state.get("circ_sel")
                                    if (
                                        circ_sel
                                        and circ_sel
                                        != "** TODAS LAS CIRCUNSCRIPCIONES **"
                                        and "Circunscripcion" in df_exp.columns
                                    ):
                                        df_exp = df_exp[
                                            df_exp["Circunscripcion"] == circ_sel
                                        ]

                                    if top_n_switch.value:
                                        top_val = int(top_n_input.value)
                                        top_cands = (
                                            df_exp.groupby("Candidato")["Votos"]
                                            .sum()
                                            .nlargest(top_val)
                                            .index
                                        )
                                        df_exp = df_exp[
                                            df_exp["Candidato"].isin(top_cands)
                                        ]

                                    # Exclude consolidated placeholder rows
                                    df_exp = df_exp[
                                        df_exp["Municipio"] != "** CONSOLIDADO **"
                                    ]

                                    # Label for the row index
                                    row_index_label = (
                                        "DEPARTAMENTO"
                                        if dept_select.value == "NACIONAL"
                                        else "MUNICIPIO"
                                    )

                                    # Pivot: rows = Municipio (depts or munis), cols = candidates
                                    pivot = df_exp.pivot_table(
                                        index="Municipio",
                                        columns="Candidato",
                                        values="Votos",
                                        aggfunc="sum",
                                        fill_value=0,
                                    )
                                    pivot.index.name = row_index_label
                                    # Drop pseudo-candidate if present
                                    if "Votos por Partido" in pivot.columns:
                                        pivot = pivot.drop(
                                            columns=["Votos por Partido"]
                                        )
                                    pivot["TOTAL"] = pivot.sum(axis=1)
                                    pivot.loc["TOTAL GENERAL"] = pivot.sum(axis=0)

                                    # Save CSV (always works, no extra dependency)
                                    csv_path = (
                                        f"matriz_{etype_code.lower()}_{suffix}.csv"
                                    )
                                    pivot.to_csv(csv_path, encoding="utf-8")
                                    ui.download(csv_path)

                                    # Also try Excel if openpyxl available
                                    try:
                                        xlsx_path = (
                                            f"matriz_{etype_code.lower()}_{suffix}.xlsx"
                                        )
                                        pivot.to_excel(xlsx_path, engine="openpyxl")
                                        ui.download(xlsx_path)
                                        ui.notify(
                                            "Consolidado descargado (CSV + Excel)",
                                            type="positive",
                                        )
                                    except Exception:
                                        ui.notify(
                                            "Consolidado descargado (CSV)",
                                            type="positive",
                                        )
                                else:
                                    csv_path = (
                                        f"datos_{etype_code.lower()}_{suffix}.csv"
                                    )
                                    df_exp.to_csv(
                                        csv_path, index=False, encoding="utf-8"
                                    )
                                    ui.download(csv_path)
                                    ui.notify("CSV descargado", type="positive")

                            ui.button(
                                "Descargar CSV / Excel",
                                icon="table_chart",
                                on_click=download_csv,
                            ).props("color=teal no-caps").classes("w-full")

                        # -- TYP --
                        with ui.card().classes("flex-1 min-w-[260px]"):
                            ui.label("Fuente Typst (.typ)").classes(
                                "text-lg font-semibold mb-2"
                            )
                            ui.label("Archivo fuente editable").classes(
                                "text-sm text-slate-400 mb-4"
                            )

                            async def download_typ():
                                df_curr = get_df()
                                stats_curr = get_stats()
                                sel = export_select.value
                                if not sel or df_curr is None:
                                    ui.notify(
                                        "Seleccione municipios y asegúrese de tener datos cargados",
                                        type="warning",
                                    )
                                    return
                                df_exp = df_curr[df_curr["Municipio"].isin(sel)]
                                stats_pass = {
                                    m: stats_curr.get(m)
                                    for m in sel
                                    if stats_curr.get(m)
                                }
                                suffix = (
                                    sel[0].lower().replace(" ", "_")
                                    if len(sel) == 1
                                    else "multi"
                                )
                                fname = f"reporte_{etype_code.lower()}_{suffix}.typ"
                                top_n = (
                                    int(top_n_input.value)
                                    if top_n_switch.value
                                    else None
                                )
                                if dept_table_switch.value:
                                    generate_typst_national_dept_table(
                                        df_exp,
                                        fname,
                                        stats=stats_pass,
                                        top_n=top_n,
                                        exclude_zero_votes=exclude_zero.value,
                                        circ_sel=state.get("circ_sel"),
                                        row_radius=float(row_radius_input.value or 2),
                                        row_inset_y=float(row_inset_input.value or 4),
                                        page_width=float(
                                            page_width_input.value or 8.5
                                        ),
                                        row_label="DEPARTAMENTO"
                                        if dept_select.value == "NACIONAL"
                                        else "MUNICIPIO",
                                    )
                                else:
                                    is_national = dept_select.value == "NACIONAL"
                                    generate_typst_pro(
                                        df_exp,
                                        "",
                                        fname,
                                        stats=stats_pass,
                                        etype_label=etype_name.upper(),
                                        exclude_zero_votes=exclude_zero.value,
                                        top_n=top_n,
                                        circ_sel=state.get("circ_sel"),
                                        is_national=is_national,
                                        row_radius=float(row_radius_input.value or 2),
                                        row_inset_y=float(row_inset_input.value or 4),
                                        page_width=float(
                                            page_width_input.value or 8.5
                                        ),
                                    )
                                ui.download(fname)
                                ui.notify("Archivo .typ descargado", type="positive")

                            ui.button(
                                "Descargar .typ", icon="code", on_click=download_typ
                            ).props("color=purple no-caps").classes("w-full")

                        # -- HTML interactivo --
                        with ui.card().classes("flex-1 min-w-[260px]"):
                            ui.label("Web interactiva").classes(
                                "text-lg font-semibold mb-2"
                            )
                            ui.label("HTML autónomo con filtros y color").classes(
                                "text-sm text-slate-400 mb-4"
                            )

                            async def download_html():
                                df_curr = get_df()
                                stats_curr = get_stats()
                                sel = export_select.value
                                if not sel or df_curr is None:
                                    ui.notify("Seleccione municipios", type="warning")
                                    return
                                df_exp = df_curr[df_curr["Municipio"].isin(sel)]
                                stats_pass = {
                                    m: stats_curr.get(m)
                                    for m in sel
                                    if stats_curr.get(m)
                                }
                                suffix = (
                                    sel[0].lower().replace(" ", "_")
                                    if len(sel) == 1
                                    else "multi"
                                )
                                fname = f"resultados_{etype_code.lower()}_{suffix}.html"
                                top_n = (
                                    int(top_n_input.value)
                                    if top_n_switch.value
                                    else None
                                )
                                n_seats_val = 1
                                thr_val = 0.0
                                generate_web_html(
                                    df_exp,
                                    fname,
                                    stats=stats_pass,
                                    etype_label=etype_name.upper(),
                                    exclude_zero_votes=exclude_zero.value,
                                    top_n=top_n,
                                    n_seats=n_seats_val,
                                    threshold_pct=thr_val,
                                    circ_sel=state.get("circ_sel"),
                                )
                                ui.download(fname)
                                ui.notify(
                                    "HTML interactivo descargado", type="positive"
                                )

                            ui.button(
                                "Descargar HTML",
                                icon="language",
                                on_click=download_html,
                            ).props("color=deep-orange no-caps").classes("w-full")

    # ---- Diálogo de progreso ----
    progress_dialog = ui.dialog().props("persistent")
    with progress_dialog, ui.card().classes("w-[420px] items-center py-8 px-6"):
        ui.spinner("dots", size="60px", color="primary").classes("mb-4")
        progress_title = ui.label("Conectando con la Registraduría…").classes(
            "text-lg font-semibold text-slate-700 mb-2"
        )
        progress_detail = ui.label("Preparando conexión…").classes(
            "text-sm text-slate-400 mb-4"
        )
        progress_bar = (
            ui.linear_progress(value=0, show_value=False)
            .classes("w-full rounded")
            .props("color=primary stripe animated")
        )
        progress_counter = ui.label("").classes("text-xs text-slate-400 mt-2")

    # ---- Helper: poblar UI con datos ----
    def _populate_ui(
        df_full: pd.DataFrame, stats_map: dict, etype_name: str, source: str
    ):
        """Actualiza estado, selectores, métricas y tabs con datos nuevos."""
        nonlocal metrics_row, tabs_container
        main_container.clear()
        metrics_row = None
        tabs_container = None
        dept_val = dept_select.value

        state["df_full_json"] = df_full.to_json(orient="records")
        state["stats_json"] = json.dumps(stats_map)
        state["etype"] = etype_name
        state["muni_sel"] = "Todo el Ámbito"

        # Actualizar opciones de circunscripción
        all_circs = (
            sorted(df_full["Circunscripcion"].unique().tolist())
            if "Circunscripcion" in df_full.columns
            else []
        )
        if all_circs:
            all_circs = ["** TODAS LAS CIRCUNSCRIPCIONES **"] + all_circs
        circ_select.options = all_circs

        # Default inteligente
        default_circ = (
            "TERRITORIAL DEPARTAMENTAL" if etype_name == "Cámara" else "NACIONAL"
        )
        if default_circ in all_circs:
            circ_select.value = default_circ
        elif all_circs:
            circ_select.value = all_circs[0]

        state["circ_sel"] = circ_select.value
        circ_select.update()

        # Obtener versión filtrada para la UI actual (ahora por circ_sel)
        df_view = get_df()
        if df_view is None:
            df_view = df_full  # safety

        units = ["Todo el Ámbito", "** CONSOLIDADO **"] + sorted(
            df_view["Municipio"].unique().tolist()
        )
        muni_select.options = units
        muni_select.value = "Todo el Ámbito"
        muni_select.update()

        if stats_map and "__REPORTE__" in stats_map:
            meta = stats_map["__REPORTE__"]
            b_num = meta.get("boletin", "---")
            b_hour = meta.get("hora", "---")
            # Reformatear hora si es HHMMSS
            if len(b_hour) == 6:
                b_hour = f"{b_hour[:2]}:{b_hour[2:4]}:{b_hour[4:]}"
            report_label.set_text(f"BOLETÍN #{b_num} — {b_hour}")
            status_label.set_text(
                f"{etype_name} · {dept_val} · ({meta.get('tipo', 'Data')})"
            )
        else:
            report_label.set_text("DATOS CARGADOS")
            status_label.set_text(f"{etype_name} · {dept_val} · ({source})")

        _update_cache_badge()

        render_metrics(df_view, "Todo el Ámbito")
        render_tabs(df_view, stats_map, "Todo el Ámbito", etype_name)

    async def do_load_cache():
        etype_name = "Presidencia"
        etype_code = "PR"
        dept_name = dept_select.value
        dept_code = DEPT_OPTS[dept_name]["code"]

        result, error = load_cache(dept_code)
        if error:
            ui.notify(f"No hay caché: {error}", type="warning")
            return

        df, stats_map, meta = result
        from datetime import datetime

        ts = datetime.fromisoformat(meta["timestamp"]).astimezone()
        local_str = ts.strftime("%d/%m/%Y %H:%M")

        _populate_ui(df, stats_map, etype_name, f"caché {local_str}")
        ui.notify(
            f"✓ Datos cargados desde caché local ({meta['records']} registros, {local_str})",
            type="positive",
        )

    cache_btn.on_click(do_load_cache)

    # ---- Scraping callback (descarga web) ----
    async def do_scrape():
        etype_name = "Presidencia"
        etype_code = "PR"
        dept_name = dept_select.value
        dept_code = DEPT_OPTS[dept_name]["code"]

        # Mostrar overlay de progreso
        progress_title.set_text(f"Obteniendo datos de {etype_name} ({dept_name})…")
        progress_detail.set_text("Conectando con la Registraduría…")
        progress_bar.set_value(0)
        progress_counter.set_text("")
        progress_dialog.open()
        scrape_btn.props("loading")
        status_label.set_text("Conectando…")

        # Cola para recibir actualizaciones de progreso desde el hilo
        progress_queue: asyncio.Queue = asyncio.Queue()

        def on_progress(step: str, current: int, total: int):
            progress_queue.put_nowait((step, current, total))

        source = state.get("source")
        user = state.get("admin_user") or os.getenv("REG_USER", "")
        pwd = state.get("admin_pass") or os.getenv("REG_PASS", "")

        def task_wrapper():
            return scrape_official_data(
                dept_code=dept_code, user=user, password=pwd, on_progress=on_progress
            )

        # Lanzar scraping en hilo separado para no bloquear la UI
        scrape_task = asyncio.get_event_loop().run_in_executor(None, task_wrapper)

        # Actualizar la UI mientras el scraping está en curso
        while not scrape_task.done():
            try:
                step, current, total = await asyncio.wait_for(
                    progress_queue.get(), timeout=0.15
                )
                if total > 1:
                    pct = current / total
                    progress_bar.set_value(pct)
                    progress_detail.set_text(step)
                    progress_counter.set_text(f"{current} de {total} municipios")
                    progress_title.set_text(f"Descargando {etype_name}…")
                else:
                    progress_detail.set_text(step)
            except asyncio.TimeoutError:
                pass

        # Drenar mensajes restantes en la cola
        while not progress_queue.empty():
            step, current, total = progress_queue.get_nowait()
            if total > 1:
                progress_bar.set_value(current / total)
                progress_detail.set_text(step)
                progress_counter.set_text(f"{current} de {total} municipios")

        result, error = scrape_task.result()

        # Cerrar overlay
        progress_bar.set_value(1.0)
        progress_detail.set_text("¡Listo! Datos guardados en caché local.")
        await asyncio.sleep(0.6)
        progress_dialog.close()
        scrape_btn.props(remove="loading")

        if error:
            ui.notify(f"Error: {error}", type="negative")
            status_label.set_text("Error")
            return

        df, stats_map = result
        _populate_ui(df, stats_map, etype_name, "web")
        ui.notify(
            f"✓ Datos descargados y cacheados: {len(df)} candidatos", type="positive"
        )

    scrape_btn.on_click(do_scrape)

    # ---- Callbacks de filtros ----
    def on_circ_change(e):
        state["circ_sel"] = e.value
        df = get_df()
        if df is not None:
            # Re-poblar municipios pues pueden cambiar segun circ
            units = ["Todo el Ámbito"] + sorted(df["Municipio"].unique().tolist())
            muni_select.options = units
            muni_select.value = "Todo el Ámbito"
            muni_select.update()

            muni = "Todo el Ámbito"
            stats = get_stats()
            etype_name = "Presidencia"
            dept_val = dept_select.value
            status_label.set_text(f"{etype_name} · {dept_val} · {muni}")
            render_metrics(df, muni)
            render_tabs(df, stats, muni, etype_name)

    circ_select.on_value_change(on_circ_change)

    def on_muni_change(e):
        df = get_df()
        if df is None:
            return
        muni = e.value
        stats = get_stats()
        etype_name = "Presidencia"
        state["muni_sel"] = muni
        dept_val = dept_select.value
        status_label.set_text(f"{etype_name} · {dept_val} · {muni}")
        render_metrics(df, muni)
        render_tabs(df, stats, muni, etype_name)

    muni_select.on_value_change(on_muni_change)

    # ---- Restore previous session or auto-load cache ----
    df = get_df()
    if df is not None and "Municipio" in df.columns:
        # Hay datos de una sesión previa en storage
        stats = get_stats()
        etype_name = "Presidencia"
        muni = state.get("muni_sel", "Todo el Ámbito")
        units = ["Todo el Ámbito"] + sorted(df["Municipio"].unique().tolist())
        muni_select.options = units
        muni_select.value = muni
        muni_select.update()
        dept_val = dept_select.value
        status_label.set_text(f"{etype_name} · {dept_val} · {len(df)} registros")
        render_metrics(df, muni)
        render_tabs(df, stats, muni, etype_name)
    else:
        # Intentar auto-cargar desde caché local
        etype_name = "Presidencia"
        etype_code = "PR"
        dept_name = dept_select.value
        dept_code = DEPT_OPTS[dept_name]["code"]
        cached, _err = load_cache(dept_code)
        if cached:
            cdf, cstats, cmeta = cached
            from datetime import datetime

            ts = datetime.fromisoformat(cmeta["timestamp"]).astimezone()
            local_str = ts.strftime("%d/%m/%Y %H:%M")
            _populate_ui(cdf, cstats, etype_name, f"caché {local_str}")
        else:
            with main_container:
                with ui.column().classes(
                    "items-center justify-center w-full mt-20 gap-4"
                ):
                    ui.icon("how_to_vote", size="80px").classes("text-blue-300")
                    ui.label("Bienvenido al Dashboard Electoral").classes(
                        "text-2xl font-bold text-slate-600"
                    )
                    ui.label(
                        "Seleccione el tipo de elección y presione «Obtener datos» para descargar,"
                    ).classes("text-sm text-slate-400")
                    ui.label(
                        "o «Cargar caché local» si ya descargó datos anteriormente."
                    ).classes("text-sm text-slate-400")


# ---------------------------------------------------------------------------
# Arranque
# ---------------------------------------------------------------------------
_prod = os.environ.get("PRODUCTION", "").lower() in ("1", "true", "yes")

ui.run(
    title=APP_TITLE,
    host="0.0.0.0" if _prod else "127.0.0.1",
    port=int(os.environ.get("PORT", 8081)),
    reload=not _prod,
    storage_secret=os.environ.get("STORAGE_SECRET", "elecciones-risaralda-2026"),
)
