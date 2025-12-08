import os
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st
from PIL import Image, ImageDraw
import gspread
from google.oauth2.service_account import Credentials

# -------------------------
# Rutas de archivos locales
# -------------------------
RUTA_ARCHIVO = "registros.csv"
RUTA_PERSONAS = "personas.csv"

# Imagen de la planta para el mapa de calor
imagen_planta = Image.open("planta.png")

# Coordenadas aproximadas de cada punto sobre la imagen
# (si algún punto se ve corrido, luego ajustamos X, Y)
PUNTOS_COORDS = {
    "Ventanas": (195, 608),
    "Faja 2": (252, 587),
    "Chancado Primario": (330, 560),
    "Chancado Secundario": (388, 533),
    "Cuarto Control": (650, 760),
    "Filtro Zn": (455, 409),
    "Flotación Zn": (623, 501),
    "Flotación Pb": (691, 423),
    "Tripper": (766, 452),
    "Molienda": (802, 480),
    "Nido de Ciclones 4": (811, 307),
}

# -------------------------
# Google Sheets
# -------------------------

def get_worksheet():
    """Devuelve la hoja de cálculo de Google Sheets donde se guardan los registros."""
    creds_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    client = gspread.authorize(creds)

    # OJO: aquí asumo que tienes una sección [sheets] con sheet_id
    # Si pusiste sheet_id dentro de [gcp_service_account], cambia esta línea a:
    # sheet_id = st.secrets["gcp_service_account"]["sheet_id"]
    sheet_id = st.secrets["sheets"]["sheet_id"]

    sh = client.open_by_key(sheet_id)
    return sh.sheet1  # primera hoja


# -------------------------
# Funciones de datos
# -------------------------

def cargar_personas():
    """Lee la lista de personas autorizadas desde personas.csv."""
    if os.path.exists(RUTA_PERSONAS):
        df = pd.read_csv(
            RUTA_PERSONAS,
            sep=";",
            engine="python",
        )

        if "nombre" not in df.columns:
            df["nombre"] = ""
        if "activo" in df.columns:
            df["activo"] = df["activo"].fillna(0).astype(int)
        else:
            df["activo"] = 1

        df["nombre"] = df["nombre"].astype(str).str.strip()
        df = df[df["activo"] == 1]

        return df

    return pd.DataFrame(columns=["nombre", "activo"])


def cargar_datos():
    """Lee el archivo de registros local, si existe."""
    if os.path.exists(RUTA_ARCHIVO):
        try:
            return pd.read_csv(RUTA_ARCHIVO, sep=";", engine="python")
        except Exception:
            pass

    return pd.DataFrame(columns=["timestamp", "fecha", "hora", "nombre", "punto"])


def guardar_registro(nombre, punto):
    """Agrega un registro nuevo al archivo local y a Google Sheets."""
    df = cargar_datos()

    # Hora de Perú
    lima = pytz.timezone("America/Lima")
    ahora = datetime.now(lima)

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

    # 1) Guardar en CSV local (para el panel)
    df = pd.concat([df, nuevo], ignore_index=True)
    df.to_csv(RUTA_ARCHIVO, index=False, sep=";")

    # 2) Guardar automáticamente en Google Sheets
    try:
        ws = get_worksheet()
        ws.append_row(
            [timestamp, fecha, hora, nombre, punto],
            value_input_option="USER_ENTERED",
        )
    except Exception as e:
        # No rompemos la app si falla Sheets; solo mostramos aviso
        st.write("⚠ No se pudo guardar en Google Sheets:", e)


# -------------------------
# Mapa de calor
# -------------------------

def generar_heatmap(df, selected_person=None):
    """Dibuja el mapa de calor sobre planta.png usando los registros."""
    img = imagen_planta.copy()
    draw = ImageDraw.Draw(img)

    # Filtrar por persona si se seleccionó una
    if selected_person and selected_person != "Todos":
        df = df[df["nombre"] == selected_person]

    if df.empty:
        return img

    # Contar registros por punto
    counts = df["punto"].value_counts()

    for punto, n in counts.items():
        if punto not in PUNTOS_COORDS:
            continue

        x, y = PUNTOS_COORDS[punto]
        # Radio proporcional a cantidad de registros (ajustable)
        r = min(60, 15 + n * 5)

        # Círculo rojo semi-transparente
        draw.ellipse(
            (x - r, y - r, x + r, y + r),
            fill=(255, 0, 0, 120),
            outline=(255, 255, 255, 200),
            width=2,
        )

    return img


# -------------------------
# Vistas
# -------------------------

def vista_registro():
    # Obtenemos el punto desde la URL ?punto=...
    params = st.query_params
    punto = params.get("punto", "SIN_PUNTO")
    if isinstance(punto, list):
        punto = punto[0]

    st.title("Control de Presencia por QR")
    st.subheader(f"Punto de control: {punto}")

    st.markdown(
        """
        <p style="color: #bbb; font-size: 14px;">
        Selecciona tu nombre de la lista y presiona <b>Registrar presencia</b>.
        El sistema registrará tu nombre, el punto de control, la fecha y la hora.
        </p>
        """,
        unsafe_allow_html=True,
    )

    personas = cargar_personas()
    if personas.empty:
        st.error("No hay personas cargadas en personas.csv o ninguna está activa.")
        return

    nombres = sorted(personas["nombre"].dropna().unique().tolist())
    nombre_sel = st.selectbox("Selecciona tu nombre", ["-- Selecciona --"] + nombres)

    if st.button("Registrar presencia", use_container_width=True):
        if nombre_sel == "-- Selecciona --":
            st.error("Por favor selecciona tu nombre.")
        else:
            guardar_registro(nombre=nombre_sel, punto=punto)
            st.success(f"✅ Registro exitoso. Hola, {nombre_sel}.")
            st.info("Puedes cerrar esta ventana.")


def vista_panel():
    st.title("Panel de Control - QR")

    # Cargar datos primero
    df = cargar_datos()

    if df.empty:
        st.info(
            "Aún no hay registros. Cuando empiecen a escanear los QR, "
            "verás la información aquí."
        )
        return

    # ---- Mapa de calor ----
    st.markdown("---")
    st.subheader("Mapa de calor en la planta")

    personas = ["Todos"] + sorted(df["nombre"].dropna().unique().tolist())
    persona_sel = st.selectbox("Filtrar por persona:", personas)

    mapa_img = generar_heatmap(df, persona_sel)
    st.image(mapa_img, use_column_width=True)

    # ---- Métricas principales ----
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total de registros", len(df))
    with col2:
        st.metric("Puntos únicos", df["punto"].nunique())
    with col3:
        st.metric("Personas únicas", df["nombre"].nunique())

    # ---- Tabla de registros ----
    st.markdown("---")
    puntos = ["Todos"] + sorted(df["punto"].dropna().unique().tolist())
    punto_sel = st.selectbox("Filtrar por punto", puntos)

    df_filtrado = df.copy()
    if punto_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado["punto"] == punto_sel]

    st.subheader("Registros detallados")
    st.dataframe(
        df_filtrado.sort_values("timestamp", ascending=False),
        use_column_width=True,
    )

    # ---- Descarga de CSV ----
    st.markdown("---")
    st.subheader("Descargar historial completo")
    csv_bytes = df.to_csv(index=False, sep=";").encode("utf-8")
    st.download_button(
        label="⬇ Descargar registros.csv",
        data=csv_bytes,
        file_name="registros.csv",
        mime="text/csv",
        use_container_width=True,
    )


# -------------------------
# Main
# -------------------------

def main():
    st.set_page_config(
        page_title="Control de Presencia por QR",
        layout="centered",
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

