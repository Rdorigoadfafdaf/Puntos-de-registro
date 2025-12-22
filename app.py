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
# ARCHIVOS LOCALES
# ---------------------------------------------------------
RUTA_ARCHIVO = "registros.csv"
RUTA_PERSONAS = "personas.csv"

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
    sh = client.open_by_key(st.secrets["sheets"]["sheet_id"])
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
# BLOQUEO POR TIEMPO (4 MINUTOS)
# ---------------------------------------------------------
def puede_registrar(nombre, minutos=4):
    df = cargar_datos()
    if df.empty:
        return True, None

    df_p = df[df["nombre"] == nombre]
    if df_p.empty:
        return True, None

    lima = pytz.timezone("America/Lima")
    ahora = datetime.now(lima)

    ultimo = df_p.iloc[-1]["timestamp"]
    ultimo_dt = lima.localize(datetime.strptime(ultimo, "%Y-%m-%d %H:%M:%S"))

    diff = (ahora - ultimo_dt).total_seconds() / 60
    if diff < minutos:
        return False, round(minutos - diff, 1)

    return True, None

def guardar_registro(nombre, punto):
    lima = pytz.timezone("America/Lima")
    ahora = datetime.now(lima)

    nuevo = {
        "timestamp": ahora.strftime("%Y-%m-%d %H:%M:%S"),
        "fecha": ahora.strftime("%Y-%m-%d"),
        "hora": ahora.strftime("%H:%M:%S"),
        "nombre": nombre,
        "punto": punto,
    }

    df = cargar_datos()
    df = pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)
    df.to_csv(RUTA_ARCHIVO, index=False, sep=";")

    try:
        ws = get_worksheet()
        ws.append_row(list(nuevo.values()), value_input_option="USER_ENTERED")
    except:
        pass

# ---------------------------------------------------------
# MAPA DE PUNTOS
# ---------------------------------------------------------
def generar_mapa_puntos(df):
    img = imagen_planta.copy()
    draw = ImageDraw.Draw(img, "RGBA")

    df["punto_norm"] = df["punto"].apply(normalizar)
    color = (0, 150, 255, 220)

    for p in df["punto_norm"].unique():
        if p in PUNTOS_COORDS:
            x, y = PUNTOS_COORDS[p]
            draw.ellipse((x-6, y-6, x+6, y+6), fill=color)

    return img

# ---------------------------------------------------------
# MAPA DE CALOR
# ---------------------------------------------------------
def generar_heatmap(df):
    img = imagen_planta.copy().convert("RGBA")
    df["punto_norm"] = df["punto"].apply(normalizar)
    counts = df["punto_norm"].value_counts()

    for p, n in counts.items():
        if p in PUNTOS_COORDS:
            x, y = PUNTOS_COORDS[p]
            capa = Image.new("RGBA", img.size, (0,0,0,0))
            draw = ImageDraw.Draw(capa)
            draw.ellipse((x-40, y-40, x+40, y+40), fill=(255,0,0,120))
            capa = capa.filter(ImageFilter.GaussianBlur(18))
            img = Image.alpha_composite(img, capa)

    return img

# ---------------------------------------------------------
# VISTAS
# ---------------------------------------------------------
def vista_registro():
    punto = st.query_params.get("punto", "SIN_PUNTO")
    if isinstance(punto, list):
        punto = punto[0]

    st.title("Registro de Asistencia")
    st.subheader(f"Punto: {punto}")

    personas = cargar_personas()
    sel = st.selectbox("Selecciona tu nombre", ["--"] + personas["nombre"].tolist())

    if st.button("Registrar"):
        if sel == "--":
            st.error("Selecciona un nombre")
        else:
            ok, restante = puede_registrar(sel)
            if not ok:
                st.warning(f"Espera {restante} minutos para volver a registrar.")
            else:
                guardar_registro(sel, punto)
                st.success("Registro exitoso")

def vista_panel():
    st.title("Panel de Control")

    df = cargar_datos()
    if df.empty:
        st.info("Sin registros")
        return

    col1, col2 = st.columns(2)
    with col1:
        st.image(generar_mapa_puntos(df), caption="Mapa de puntos")
    with col2:
        st.image(generar_heatmap(df), caption="Mapa de calor")

    st.dataframe(df.sort_values("timestamp", ascending=False))

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    st.set_page_config(layout="wide")
    modo = st.query_params.get("modo", "registro")
    if isinstance(modo, list):
        modo = modo[0]

    if modo == "panel":
        vista_panel()
    else:
        vista_registro()

if __name__ == "__main__":
    main()
