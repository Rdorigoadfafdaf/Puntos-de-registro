import streamlit as st
import pandas as pd
from datetime import datetime
import os

RUTA_ARCHIVO = "registros.csv"
RUTA_PERSONAS = "personas.csv"


# ==============================
# FUNCIONES DE DATOS
# ==============================

def cargar_personas():
    """Lee la lista de personas autorizadas desde personas.csv"""
    if os.path.exists(RUTA_PERSONAS):
        df = pd.read_csv(
            RUTA_PERSONAS,
            sep=None,
            engine="python"
        )

        # Normalizamos columnas esperadas
        if "activo" in df.columns:
            df["activo"] = df["activo"].fillna(0).astype(int)
        else:
            df["activo"] = 1

        if "pin" not in df.columns:
            df["pin"] = ""

        if "nombre" not in df.columns:
            df["nombre"] = ""

        df["nombre"] = df["nombre"].astype(str).str.strip()
        df["pin"] = df["pin"].astype(str).str.strip()

        # Filtramos solo activos
        df = df[df["activo"] == 1]

        return df
    else:
        return pd.DataFrame(columns=["nombre", "pin", "activo"])


def cargar_datos():
    """Lee el archivo de registros, si existe."""
    if os.path.exists(RUTA_ARCHIVO):
        try:
            return pd.read_csv(RUTA_ARCHIVO, sep=None, engine="python")
        except Exception:
            return pd.DataFrame(columns=[
                "timestamp", "fecha", "hora",
                "nombre", "punto"
            ])
    else:
        return pd.DataFrame(columns=[
            "timestamp", "fecha", "hora",
            "nombre", "punto"
        ])


def guardar_registro(nombre, punto):
    """Agrega un registro nuevo al archivo registros.csv."""
    df = cargar_datos()

    ahora = datetime.now()
    fecha = ahora.strftime("%Y-%m-%d")
    hora = ahora.strftime("%H:%M:%S")
    timestamp = ahora.strftime("%Y-%m-%d %H:%M:%S")

    nuevo = pd.DataFrame([{
        "timestamp": timestamp,
        "fecha": fecha,
        "hora": hora,
        "nombre": nombre,
        "punto": punto,
    }])

    df = pd.concat([df, nuevo], ignore_index=True)

    df.to_csv(RUTA_ARCHIVO, index=False, sep=";")


def validar_credenciales(nombre, pin):
    """
    Devuelve True si nombre + pin son válidos; si no, False.
    """
    personas = cargar_personas()
    if personas.empty:
        return False

    nombre = str(nombre).strip()
    pin = str(pin).strip()

    personas["nombre"] = personas["nombre"].astype(str).str.strip()
    personas["pin"] = personas["pin"].astype(str).str.strip()

    fila = personas[
        (personas["nombre"] == nombre) &
        (personas["pin"] == pin)
    ]

    return not fila.empty


# ==============================
# VISTAS
# ==============================

def vista_registro():
    params = st.query_params
    punto = params.get("punto", "SIN_PUNTO")
    if isinstance(punto, list):
        punto = punto[0]

    st.title("Control de Presencia por QR")
    st.subheader(f"Punto de control: {punto}")

    st.markdown(
        """
        <p style="color: #bbb; font-size: 14px;">
        Selecciona tu nombre de la lista e ingresa tu <b>PIN</b> personal.
        El sistema validará tus credenciales y registrará tu presencia.
        </p>
        """,
        unsafe_allow_html=True
    )

    personas = cargar_personas()
    if personas.empty:
        st.error("No hay personas cargadas en personas.csv o ninguna está activa.")
        return

    nombres = sorted(personas["nombre"].dropna().unique().tolist())

    nombre_sel = st.selectbox("Selecciona tu nombre", ["-- Selecciona --"] + nombres)

    pin = st.text_input("PIN", type="password", max_chars=10)

    credenciales_ok = False
    if nombre_sel != "-- Selecciona --" and pin.strip() != "":
        credenciales_ok = validar_credenciales(nombre_sel, pin)
        if credenciales_ok:
            st.success(f"Credenciales válidas. Usuario: {nombre_sel}")
        else:
            st.error("❌ Nombre o PIN incorrectos.")

    if st.button("Registrar presencia", use_container_width=True):
        if nombre_sel == "-- Selecciona --":
            st.error("Por favor selecciona tu nombre.")
        elif pin.strip() == "":
            st.error("Por favor ingresa tu PIN.")
        else:
            if validar_credenciales(nombre_sel, pin):
                guardar_registro(
                    nombre=nombre_sel,
                    punto=punto,
                )
                st.success(f"✅ Registro exitoso. Hola, {nombre_sel}.")
                st.info("Puedes cerrar esta ventana.")
            else:
                st.error("❌ Nombre o PIN incorrectos. No se puede registrar.")


def vista_panel():
    st.title("Panel de Control - QR")

    df = cargar_datos()

    if df.empty:
        st.info("Aún no hay registros. Cuando empiecen a escanear los QR, verás la información aquí.")
        return

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total de registros", len(df))
    with col2:
        st.metric("Puntos únicos", df["punto"].nunique())
    with col3:
        st.metric("Personas únicas", df["nombre"].nunique())

    st.markdown("---")

    puntos = ["Todos"] + sorted(df["punto"].dropna().unique().tolist())
    punto_sel = st.selectbox("Filtrar por punto", puntos)

    df_filtrado = df.copy()
    if punto_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado["punto"] == punto_sel]

    st.subheader("Registros detallados")
    st.dataframe(
        df_filtrado.sort_values("timestamp", ascending=False),
        use_container_width=True
    )

    st.markdown("---")
    st.subheader("Registros por punto")

    conteo = df.groupby("punto")["nombre"].count().reset_index()
    conteo.rename(columns={"nombre": "registros"}, inplace=True)

    st.bar_chart(conteo.set_index("punto")["registros"])


# ==============================
# MAIN / ENRUTADOR
# ==============================

def main():
    st.set_page_config(
        page_title="Control de Presencia por QR",
        layout="centered"
    )

    params = st.query_params
    modo = params.get("modo", "registro")
    if isinstance(modo, list):
        modo = modo[0]

    if modo == "panel":
        vista_panel()
    else:
        vista_registro()


if __name__ == "__main__":
    main()
