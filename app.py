"""BudgetApp - control de gastos con estados de cuenta PDF (Santander/HSBC).

Ejecutar con:  .venv\\Scripts\\python.exe -m streamlit run app.py
(o doble clic en Ejecutar_BudgetApp.bat)
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

from budget.categorize import (CATEGORIA_DEFAULT, CATEGORIAS, agregar_regla,
                               borrar_regla, fijar_categoria, recategorizar_todo,
                               reglas)
from budget.db import (connect, df_movimientos, eliminar_movimiento,
                       guardar_movimientos, meses_disponibles, resumen,
                       stats_generales, tarjetas_disponibles)
from budget.importer import analizar_pdf, confirmar
from budget.parsers.base import Transaction

st.set_page_config(page_title="BudgetApp", page_icon="💳", layout="wide")

UPLOADS_DIR = Path(__file__).resolve().parent / "data" / "uploads"
BANCOS = ["Todos", "HSBC", "Santander", "Manual"]


def fmt(v) -> str:
    return f"$ {Decimal(v):,.2f}"


MESES_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
            "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def nombre_mes(m: str) -> str:
    """'2026-09' -> 'Septiembre 2026'."""
    try:
        y, mth = int(m[:4]), int(m[5:7])
        return f"{MESES_ES[mth - 1].capitalize()} {y}"
    except (ValueError, IndexError):
        return m


st.sidebar.title("💳 BudgetApp")
st.sidebar.caption("Control de gastos · datos 100% locales")
opcion = st.sidebar.radio("Menú", ["📥 Importar", "✍️ Gasto manual", "📋 Movimientos",
                                   "🧾 Categorías", "📊 Dashboard"],
                          label_visibility="collapsed")
con = connect()

stats = stats_generales(con)
st.sidebar.metric("Movimientos guardados", stats["movimientos"])
st.sidebar.caption(f"{stats['importaciones']} importaciones registradas")

# ================================================================ IMPORTAR

if opcion == "📥 Importar":
    st.header("📥 Importar estados de cuenta")
    st.caption("Arrastra los PDF mensuales de Santander o HSBC. El OCR tarda "
               "1-3 minutos por archivo. Los duplicados se ignoran.")

    paths: list[Path] = []
    ups = st.file_uploader("Estados de cuenta (PDF)", type=["pdf"],
                           accept_multiple_files=True)
    if ups:
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        for u in ups:
            dest = UPLOADS_DIR / u.name
            dest.write_bytes(u.getvalue())
            paths.append(dest)

    ruta = st.text_input("...o pega la ruta de un PDF:")
    col_a, _ = st.columns([1, 3])
    if col_a.button("Agregar ruta") and ruta.strip():
        p = Path(ruta.strip().strip('"'))
        if p.exists() and p.suffix.lower() == ".pdf":
            paths.append(p)
        else:
            st.error("La ruta no existe o no es un PDF")

    pendientes: list = st.session_state.setdefault("pendientes", [])
    importados = st.session_state.setdefault("importados", {})  # nombre -> resumen
    ya_en_cola = {Path(p.archivo).name for p in pendientes}

    for p in paths:
        if p.name in ya_en_cola or p.name in importados:
            continue
        with st.spinner(f"Analizando {p.name} (OCR)…"):
            pendientes.append(analizar_pdf(p))
        ya_en_cola.add(p.name)
    st.session_state["pendientes"] = pendientes

    if not pendientes:
        if importados:
            st.success("Importación guardada ✔ — los duplicados se ignoran "
                       "automáticamente si vuelves a subir el mismo PDF.")
            for nombre, resumen_imp in importados.items():
                st.caption(f"✅ **{nombre}** — {resumen_imp}")
        st.info("Aún no hay estados de cuenta en cola.")
        st.stop()

    hay_pendiente = False
    for previa in pendientes:
        with st.container(border=True):
            c1, c2, c3, c4 = st.columns([3, 1, 1, 2])
            nombre = Path(previa.archivo).name
            estado = "✅ guardado" if previa.guardado else (
                "✅ validado" if previa.validacion_ok else "⚠️ sin validar")
            c1.markdown(f"**{nombre}**  \n{previa.banco} · periodo {previa.periodo} · {estado}")
            if previa.guardado:
                c2.metric("Nuevos", previa.nuevos)
                c3.metric("Duplicados", previa.duplicados)
                c4.caption("ya está en la base de datos")
            else:
                hay_pendiente = True
                c2.metric("Movimientos", len(previa.transacciones))
                c3.metric("Rechazados", len(previa.rechazados))
                for m in previa.mensajes:
                    c4.caption(m)

            if previa.transacciones:
                df = pd.DataFrame([{
                    "fecha": t.fecha_operacion, "cargo": t.fecha_cargo,
                    "tarjeta": t.card_last4, "monto": float(t.monto),
                    "descripción": t.descripcion[:50],
                } for t in previa.transacciones])
                st.dataframe(
                    df, use_container_width=True, hide_index=True,
                    column_config={"monto": st.column_config.NumberColumn(
                        "monto", format="$ %.2f")})

    if hay_pendiente:
        if st.button("💾 Guardar en la base de datos", type="primary"):
            for previa in pendientes:
                if not previa.guardado:
                    confirmar(previa, con)
                    importados[Path(previa.archivo).name] = (
                        f"{previa.nuevos} nuevos · {previa.duplicados} duplicados")
            st.session_state["pendientes"] = []
            st.rerun()
    else:
        if st.button("Limpiar lista"):
            st.session_state["pendientes"] = []
            st.rerun()

# ================================================================ GASTO MANUAL

elif opcion == "✍️ Gasto manual":
    st.header("✍️ Registrar gasto manual")
    st.caption("Para gastos que no aparecen en los estados de cuenta "
               "(efectivo, comercios pequeños, etc.).")

    tarjetas = tarjetas_disponibles(con)
    fuentes = ["Efectivo"] + [f"{t['banco']} ····{t['tarjeta_ultimos4']}"
                              for t in tarjetas]

    with st.form("gasto_manual", border=True):
        c1, c2 = st.columns(2)
        fecha = c1.date_input("Fecha", value=date.today())
        monto = c1.number_input("Monto (MXN)", min_value=0.0, format="%.2f")
        desc = c2.text_input("Descripción", placeholder="p. ej. Gasolina Pemex")
        es_abono = c2.checkbox("Es un abono (pago, devolución, reembolso)")

        fuente = st.selectbox("Pagado con", fuentes)
        categoria = st.selectbox("Categoría", CATEGORIAS)

        if st.form_submit_button("💾 Guardar gasto", type="primary"):
            if not desc.strip() or monto <= 0:
                st.error("Captura una descripción y un monto mayor a cero.")
            else:
                ult4 = "EFECTIVO" if fuente == "Efectivo" else fuente.split("····")[-1].strip()
                t = Transaction(
                    bank="Manual", card_type="manual", card_last4=ult4,
                    section="manual",
                    fecha_operacion=fecha, fecha_cargo=fecha,
                    descripcion=desc.strip(),
                    monto=Decimal(f"{monto:.2f}") * (-1 if es_abono else 1),
                    statement_period=f"{fecha.year}-{fecha.month:02d}",
                    categoria=categoria,
                )
                n, _ = guardar_movimientos(con, [t])
                st.success(f"Gasto guardado ✔ {'(duplicado ignorado)' if n == 0 else ''}")

    st.subheader("Últimos gastos manuales")
    dfm = df_movimientos(con, banco="Manual").sort_values("id", ascending=False)
    if dfm.empty:
        st.info("Aún no hay gastos manuales.")
    else:
        vista = dfm.head(20)[["id", "mes", "fecha_operacion", "descripcion",
                              "monto_dec", "categoria"]].copy()
        vista["mes"] = vista["mes"].map(nombre_mes)
        vista = vista.rename(columns={"monto_dec": "monto"})
        st.dataframe(
            vista, use_container_width=True, hide_index=True,
            column_config={"monto": st.column_config.NumberColumn(
                "monto", format="$ %.2f")})
        del_id = st.number_input("ID a eliminar", min_value=0, step=1)
        if st.button("🗑 Eliminar movimiento"):
            if del_id:
                eliminar_movimiento(con, int(del_id))
                st.rerun()
            else:
                st.error("Captura el ID del movimiento a eliminar.")

# ================================================================ MOVIMIENTOS

elif opcion == "📋 Movimientos":
    st.header("📋 Movimientos")

    meses = meses_disponibles(con)
    tarjetas = ["Todas"] + [f"{t['banco']} ····{t['tarjeta_ultimos4']}"
                            for t in tarjetas_disponibles(con)]

    c1, c2, c3, c4, c5 = st.columns([1, 1, 1, 1.5, 1.5])
    sel_mes = c1.selectbox(
        "Mes (gasto real)", ["Todos"] + meses,
        format_func=lambda m: "Todos" if m == "Todos" else nombre_mes(m))
    sel_banco = c2.selectbox("Banco", BANCOS)
    sel_tarjeta = c3.selectbox("Tarjeta", tarjetas)
    sel_cat = c4.selectbox("Categoría", ["Todas"] + CATEGORIAS)
    texto = c5.text_input("Buscar descripción", placeholder="p. ej. AMAZON")

    df = df_movimientos(con, texto=texto, mes=sel_mes, banco=sel_banco,
                        categoria=sel_cat,
                        tarjeta=sel_tarjeta.split("····")[-1].strip()
                        if sel_tarjeta != "Todas" else None)

    if df.empty:
        st.info("Sin movimientos con esos filtros.")
        st.stop()

    gasto = df[(df["monto_dec"] > 0) & (df["cuenta_gasto"] == 1)]
    total_cargos = gasto["monto_dec"].sum()
    total_abonos = df[df["monto_dec"] < 0]["monto_dec"].sum()
    planes = df[(df["cuenta_gasto"] == 0)]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Movimientos", len(df))
    k2.metric("Gasto del mes" if sel_mes != "Todos" else "Gasto total",
              fmt(total_cargos))
    k3.metric("Total abonos", fmt(total_abonos))
    k4.metric("Neto", fmt(total_cargos + total_abonos))
    if not planes.empty:
        st.caption("ℹ️ Hay compras a meses cuyo plan es informativo; su "
                   "mensualidad se cobra como cargo regular cada mes.")

    vista = df.copy()
    vista["monto"] = vista["monto_dec"].astype(float)
    vista["cuota"] = vista.apply(
        lambda x: f"{x['msi_pago_num']}/{x['msi_pago_total']}"
        if x["msi_pago_num"] else "", axis=1)
    mostrar = vista[["id", "fecha_operacion", "fecha_cargo", "banco",
                     "tarjeta_ultimos4", "seccion", "descripcion",
                     "monto", "cuota", "categoria"]]

    editado = st.data_editor(
        mostrar, use_container_width=True, hide_index=True, height=460,
        column_config={
            "monto": st.column_config.NumberColumn("monto", format="$ %.2f"),
            "categoria": st.column_config.SelectboxColumn(
                "categoría", options=CATEGORIAS, required=True),
            "id": st.column_config.NumberColumn(disabled=True),
        },
        disabled=["id", "fecha_operacion", "fecha_cargo", "banco",
                  "tarjeta_ultimos4", "seccion", "descripcion", "monto",
                  "cuota"],
        key="editor_movs",
    )

    if st.button("💾 Guardar cambios de categoría"):
        cambios = 0
        orig = dict(zip(mostrar["id"], mostrar["categoria"]))
        for _, row in editado.iterrows():
            mid = int(row["id"])
            if row["categoria"] != orig.get(mid):
                fijar_categoria(con, mid, row["categoria"])
                cambios += 1
        st.success(f"{cambios} categoría(s) actualizadas ✔"
                   if cambios else "Sin cambios por guardar.")

    csv = mostrar.to_csv(index=False).encode("utf-8-sig")
    st.download_button("⬇ Exportar CSV", csv, "movimientos.csv", "text/csv")

# ================================================================ CATEGORIAS

elif opcion == "🧾 Categorías":
    st.header("🧾 Categorías y reglas")
    st.caption("Palabra clave → categoría. Se aplican en orden de creación a "
               "las descripciones de los movimientos. Al agregar o eliminar "
               "una regla se recategoriza todo el histórico al instante.")

    rls = reglas(con)
    df_r = pd.DataFrame([{"id": r["id"], "patrón": r["patron"],
                          "categoría": r["categoria"]} for r in rls])
    st.dataframe(df_r, use_container_width=True, hide_index=True, height=420)

    with st.form("nueva_regla", border=True):
        c1, c2, c3 = st.columns([2, 2, 1])
        patron = c1.text_input("Palabra clave (así aparece en el estado de cuenta)")
        categoria = c2.selectbox("Categoría", CATEGORIAS)
        if c3.form_submit_button("➕ Agregar regla"):
            if agregar_regla(con, categoria, patron):
                fijados = recategorizar_todo(con)
                st.success(f"Regla agregada; {fijados} movimientos recategorizados.")
            else:
                st.error("Esa palabra clave ya existe.")
            st.rerun()

    del_id = st.number_input("ID de regla a eliminar", min_value=0, step=1)
    if st.button("🗑 Eliminar regla"):
        if del_id:
            borrar_regla(con, int(del_id))
            fijados = recategorizar_todo(con)
            st.success(f"Regla eliminada; {fijados} movimientos recategorizados.")
            st.rerun()

    if st.button("♻️ Recategorizar todo con las reglas actuales"):
        fijados = recategorizar_todo(con)
        st.success(f"{fijados} movimientos recategorizados.")
        st.rerun()

# ================================================================ DASHBOARD

else:
    st.header("📊 Dashboard")

    meses = meses_disponibles(con)
    if not meses:
        st.info("Importa un estado de cuenta para ver el dashboard.")
        st.stop()

    # por defecto: el ultimo mes calendario real (no meses futuros de cuotas)
    hoy = date.today().strftime("%Y-%m")
    reales = [m for m in meses if m <= hoy]
    idx_default = meses.index(reales[0]) if reales else 0
    sel = st.selectbox("Mes de gasto", meses, index=idx_default,
                       format_func=nombre_mes)
    dfp = df_movimientos(con, mes=sel)

    r = resumen(con, sel)
    k1, k2, k3 = st.columns(3)
    k1.metric("Gasto del mes",
              fmt(dfp[(dfp["monto_dec"] > 0) & (dfp["cuenta_gasto"] == 1)]["monto_dec"].sum()))
    k2.metric("Abonos / pagos",
              fmt(dfp[dfp["monto_dec"] < 0]["monto_dec"].sum()))
    k3.metric("Movimientos", len(dfp))

    st.subheader("🥧 Distribución por categorías")
    gastos = dfp[(dfp["monto_dec"] > 0) & (dfp["cuenta_gasto"] == 1)].copy()
    gastos["monto_num"] = gastos["monto_dec"].astype(float)
    if gastos.empty:
        st.info("Sin gastos registrados en este mes.")
        st.stop()

    gasto_total = gastos["monto_num"].sum()
    por_cat = (gastos.groupby("categoria")["monto_num"]
               .agg(["sum", "count"])
               .reset_index()
               .rename(columns={"sum": "monto", "count": "movimientos"})
               .sort_values("monto", ascending=False))
    por_cat["% del gasto"] = (por_cat["monto"] / gasto_total * 100).round(1)

    fig = px.pie(por_cat, values="monto", names="categoria", hole=0.45)
    fig.update_traces(textposition="inside", texttemplate="%{label}<br>%{percent}")
    st.plotly_chart(fig, use_container_width=True)

    st.dataframe(
        por_cat[["categoria", "monto", "movimientos", "% del gasto"]],
        use_container_width=True, hide_index=True,
        column_config={"monto": st.column_config.NumberColumn(
            "monto", format="$ %.2f")})

    st.subheader("🛒 Comercios del mes")
    cargos = gastos.copy()
    cargos["comercio"] = cargos["descripcion"].str.slice(0, 30)
    tabla_comercios = (cargos.groupby("comercio")["monto_num"]
                       .agg(["sum", "count"])
                       .reset_index()
                       .rename(columns={"sum": "monto", "count": "movimientos"})
                       .sort_values("monto", ascending=False))
    st.dataframe(
        tabla_comercios,
        use_container_width=True, hide_index=True, height=360,
        column_config={"monto": st.column_config.NumberColumn(
            "monto", format="$ %.2f")})

    st.subheader("📈 Evolución mensual")
    df_all = df_movimientos(con)
    df_all = df_all[df_all["cuenta_gasto"] == 1]
    df_all["monto_num"] = df_all["monto_dec"].astype(float)
    st.line_chart(df_all[df_all["monto_num"] > 0]
                  .groupby("mes")["monto_num"].sum())
