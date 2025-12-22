import os
import unicodedata
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st
from PIL import Image, ImageDraw, ImageFilter
import gspread
from google.oauth2.service_account import Credentials

# ---------------------------------------------------------
# CONFIGURACIÓN
# ---------------------------------------------------------
RUTA_ARCHIVO = "registros.csv"
RUTA_PERSONAS = "personas.csv"
MINUTOS_BLOQUEO = 4

# ---------------------------------------------------------
# NORMALIZAR TEXTO
# ---------------------------------------------------------
def normalizar(texto: str) -> str:
    if texto is None:
        return ""
    t = str(texto).strip().lower()
    t = "".join(
        c for c in unicodedata.normalize("NFD", t)
        if unicodedata.category(c) != "Mn"
    )
    return t

# ---------------------------------------------------------
# IMAGEN BASE
# ---------------------------------------------------------
imagen_planta = Image.open("planta.png").convert("RGBA")

PUNTOS_COORDS = {
    normalizar("Ventanas"): (195, 608),
    normalizar("Faja 2"): (252, 587),
    normalizar("Chancado Primario"): (300, 560),
    normalizar("Chancado Secundario"): (388, 533),
    normalizar("Cuarto Control"): (435, 465),
    normalizar("Filtro Zn"): (455, 409),
    normalizar("Flotacion Zn"): (623, 501),
    normalizar("Flotacion Pb"): (691, 423),
    normalizar("Tripper"): (766, 452),
    normalizar("Molienda"): (802, 480),
    normalizar("Nido de Ciclones N°3"): (811, 307),
}

# ---------------------------------------------------------
# GOOGLE SHEETS
# ---------------------------------------------------------
def get_worksheet():
    creds_info = st.secrets["gcp_service_account"]
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
    client = gspread.authorize(creds)
    sheet_id = st.secrets["sheets"]["sheet_id"]
    sh = client.open_by_key(sheet_id)
    return sh.sheet1

# ---------------------------------------------------------
# CARGA DE DATOS
# ---------------------------------------------------------
def cargar_personas():
    if os.path.exists(RUTA_PERSONAS):
        df = pd.read_csv(RUTA_PERSONAS, sep=";")
        df["activo"] = df.get("activo", 1)
        return df[df["activo"] == 1]
    return pd.DataFrame(columns=["nombre", "activo"])

def cargar_datos():
    if os.path.exists(RUTA_ARCHIVO):
        return pd.read_csv(RUTA_ARCHIVO, sep=";")
    return pd.DataFrame(columns=["timestamp", "fecha", "hora", "nombre", "punto"])

# ---------------------------------------------------------
# VALIDACIÓN DE TIEMPO (4 MIN)
# ---------------------------------------------------------
def puede_registrar(nombre):
    df = cargar_datos()
    if df.empty:
        return True, None

    df_p = df[df["nombre"] == nombre]
    if df_p.empty:
        return True, None

    lima = pytz.timezone("America/Lima")
    ahora = datetime.now(lima)
    ultimo = datetime.strptime(df_p.iloc[-1]["timestamp"], "%Y-%m-%d %H:%M:%S")
    ultimo = lima.localize(ultimo)

    diff = (ahora - ultimo).total_seconds() / 60
    if diff < MINUTOS_BLOQUEO:
        return False, round(MINUTOS_BLOQUEO - diff, 1)

    return True, None

def guardar_registro(nombre, punto):
    lima = pytz.timezone("America/Lima")
    ahora = datetime.now(lima)

    fila = {
        "timestamp": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "fecha": ahora.strftime("%Y-%m-%d"),
        "hora": ahora.strftime("%H:%M:%S"),
        "nombre": nombre,
        "punto": punto,
    }

    df = cargar_datos()
    df = pd.concat([df, pd.DataFrame([fila])], ignore_index=True)
    df.to_csv(RUTA_ARCHIVO, index=False, sep=";")

    try:
        ws = get_worksheet()
        ws.append_row(list(fila.values()), value_input_option="USER_ENTERED")
    except Exception:
        pass

# ---------------------------------------------------------
# VISTA REGISTRO (QR FÍSICO BLOQUEADO)
# ---------------------------------------------------------
def vista_registro():
    # 🔒 BLOQUEO DE REFRESH / REUSO
    if "registrado" not in st.session_state:
        st.session_state.registrado = False

    if st.session_state.registrado:
        st.error("Esta página ya fue utilizada.")
        st.info("Cierra esta pestaña y vuelve a escanear el QR físico.")
        st.stop()

    punto = st.query_params.get("punto", "SIN_PUNTO")
    if isinstance(punto, list):
        punto = punto[0]

    st.title("Registro de Asistencia")
    st.subheader(f"Punto: {punto}")

    personas = cargar_personas()
    nombres = ["-- Selecciona --"] + sorted(personas["nombre"].tolist())
    sel = st.selectbox("Selecciona tu nombre:", nombres)

    if st.button("Registrar", use_container_width=True):
        if sel == "-- Selecciona --":
            st.error("Selecciona un nombre válido.")
            return

        permitido, restante = puede_registrar(sel)
        if not permitido:
            st.warning(f"Espera aproximadamente {restante} minutos.")
            return

        guardar_registro(sel, punto)

        # 🔥 MATAR PÁGINA
        st.session_state.registrado = True
        st.success("Asistencia registrada correctamente.")
        st.info("Cierra esta pestaña y vuelve a escanear el QR físico.")
        st.stop()

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    st.set_page_config(page_title="Control QR", layout="centered")
    vista_registro()

if __name__ == "__main__":
    main()
