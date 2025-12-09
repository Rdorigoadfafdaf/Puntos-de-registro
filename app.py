import os
import unicodedata
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st
from PIL import Image, ImageDraw
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
# IMAGEN BASE DE LA PLANTA
# ---------------------------------------------------------
imagen_planta = Image.open("planta.png").convert("RGBA")

# Coordenadas ajustadas
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
# CARGA DE PERSONAS Y REGISTROS
# ---------------------------------------------------------
def cargar_personas():
    if os.path.exists(RUTA_PERSONAS):
        df = pd.read_csv(RUTA_PERSONAS, sep=";", engine="python")
        if "nombre" not in df.columns:
            df["nombre"] = ""
        if "activo" not in df.columns:
            df["activo"] = 1
        df["activo"] = df["activo"].fillna(0).astype(int)
        df["nombre"] = df["nombre"].astype(str).str.strip()
        df = df[df["activo"] == 1]
        return df

    return pd.DataFrame(columns=["nombre", "activo"])


def cargar_datos():
    if os.path.exists(RUTA_ARCHIVO):
        try:
            return pd.read_csv(RUTA_ARCHIVO, sep=";", engine="python")
        except:
            pass
    return pd.DataFrame(columns=["timestamp", "fecha", "hora", "nombre", "punto"])


def guardar_registro(nombre, punto):
    df = cargar_datos()

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

    df = pd.concat([df, nuevo], ignore_index=True)
    df.to_csv(RUTA_ARCHIVO, index=False, sep=";")

    try:
        ws = get_worksheet()
        ws.append_row([timestamp, fecha, hora, nombre, punto],
                      value_input_option="USER_ENTERED")
    except Exception as e:
        st.write("⚠ No se pudo guardar en Google Sheets:", e)


# ---------------------------------------------------------
# ASIGNAR COLORES A PERSONAS
# ---------------------------------------------------------
PALETA = [
    (255, 99, 132, 255),
    (54, 162, 235, 255),
    (75, 192, 192, 255),
    (255, 206, 86, 255),
    (153, 102, 255, 255),
    (255, 159, 64, 255),
    (0, 200, 83, 255),
    (233, 30, 99, 255),
]


def get_color_for_person(nombre, mapa_colores):
    if nombre not in mapa_colores:
        mapa_colores[nombre] = PALETA[len(mapa_colores) % len(PALETA)]
    return mapa_colores[nombre]


# ---------------------------------------------------------
# GENERAR MAPA DE PUNTOS EXACTOS
# ---------------------------------------------------------
def generar_mapa_puntos(df, persona_sel):
    img = imagen_planta.copy().convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    if persona_sel != "Todos":
        df = df[df["nombre"] == persona_sel]

    if df.empty:
        return img

    df = df.copy()
    df["punto_norm"] = df["punto"].apply(normalizar)

    counts = df["punto_norm"].value_counts()
    mapa_colores = {}

    # desplazamientos pequeños alrededor del punto original
    offsets = [
        (0, 0), (12, 0), (-12, 0), (0, 12), (0, -12),
        (8, 8), (8, -8), (-8, 8), (-8, -8),
    ]

    for idx, (punto_norm, n) in enumerate(counts.items()):
        if punto_norm not in PUNTOS_COORDS:
            continue

        base_x, base_y = PUNTOS_COORDS[punto_norm]

        personas_en_punto = df[df["punto_norm"] == punto_norm]["nombre"].unique().tolist()

        for i, nombre in enumerate(personas_en_punto):
            color = get_color_for_person(nombre, mapa_colores)
            dx, dy = offsets[i % len(offsets)]
            x = base_x + dx
            y = base_y + dy

            draw.ellipse(
                (x - 6, y - 6, x + 6, y + 6),
                fill=color,
                outline=(255, 255, 255, 255),
                width=1
            )

    return img


# ---------------------------------------------------------
# LEYENDA
# ---------------------------------------------------------
def mostrar_leyenda(df, persona_sel):
    st.markdown("### Leyenda de colores")

    mapa_colores = {}
    personas = df["nombre"].unique().tolist() if persona_sel == "Todos" else [persona_sel]

    for nombre in personas:
        color = get_color_for_person(nombre, mapa_colores)
        r, g, b, a = color
        st.markdown(
            f"""
            <div style='display:flex; align-items:center; margin-bottom:4px;'>
                <div style='width:16px; height:16px; border-radius:50%; background-color:rgba({r},{g},{b},1); margin-right:8px;'></div>
                <span>{nombre}</span>
            </div>
            """,
            unsafe_allow_html=True
        )


# ---------------------------------------------------------
# VISTA REGISTRO
# ---------------------------------------------------------
def vista_registro():
    params = st.query_params
    punto = params.get("punto", "SIN_PUNTO")
    if isinstance(punto, list):
        punto = punto[0]

    st.title("Control de Presencia por QR")
    st.subheader(f"Punto de control: {punto}")

    personas = cargar_personas()
    if personas.empty:
        st.error("No hay personas cargadas.")
        return

    nombres = sorted(personas["nombre"].tolist())
    nombre_sel = st.selectbox("Selecciona tu nombre", ["-- Selecciona --"] + nombres)

    if st.button("Registrar presencia", use_container_width=True):
        if nombre_sel == "-- Selecciona --":
            st.error("Selecciona un nombre válido.")
        else:
            guardar_registro(nombre_sel, punto)
            st.success(f"Registro exitoso, {nombre_sel}.")
            st.info("Ya puedes cerrar esta ventana.")


# ---------------------------------------------------------
# VISTA PANEL
# ---------------------------------------------------------
def vista_panel():
    st.title("Panel de Control - QR")

    df = cargar_datos()
    if df.empty:
        st.info("Aún no hay registros.")
        return

    st.markdown("---")
    st.subheader("Mapa de puntos exactos")

    personas = ["Todos"] + sorted(df["nombre"].unique().tolist())
    persona_sel = st.selectbox("Filtrar por persona:", personas)

    col1, col2 = st.columns([3, 1])

    with col1:
        img_debug = generar_mapa_puntos(df, persona_sel)
        st.image(img_debug, use_column_width=True)

    with col2:
        mostrar_leyenda(df, persona_sel)

    st.markdown("---")
    st.subheader("Registros detallados")
    st.dataframe(df.sort_values("timestamp", ascending=False), use_container_width=True)


# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    st.set_page_config(page_title="Control de Presencia por QR", layout="wide")

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
