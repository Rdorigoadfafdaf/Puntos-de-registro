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
# IMAGEN BASE DE LA PLANTA
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
        return df[df["activo"] == 1]
    return pd.DataFrame(columns=["nombre", "activo"])

def cargar_datos():
    if os.path.exists(RUTA_ARCHIVO):
        try:
            return pd.read_csv(RUTA_ARCHIVO, sep=";", engine="python")
        except Exception:
            pass
    return pd.DataFrame(columns=["timestamp", "fecha", "hora", "nombre", "punto"])

# ---------------------------------------------------------
# BLOQUEO DE REGISTRO POR TIEMPO (NUEVO)
# ---------------------------------------------------------
def puede_registrar(nombre, minutos=2):
    df = cargar_datos()
    if df.empty:
        return True, None

    df_persona = df[df["nombre"] == nombre]
    if df_persona.empty:
        return True, None

    lima = pytz.timezone("America/Lima")
    ahora = datetime.now(lima)

    ultimo_ts = df_persona["timestamp"].iloc[-1]
    ultimo_dt = lima.localize(datetime.strptime(ultimo_ts, "%Y-%m-%d %H:%M:%S"))

    diff_min = (ahora - ultimo_dt).total_seconds() / 60

    if diff_min < minutos:
        return False, round(minutos - diff_min, 1)

    return True, None

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
    except Exception:
        pass

# ---------------------------------------------------------
# COLORES PARA PERSONAS
# ---------------------------------------------------------
PALETA = [
    (255, 99, 132, 255),
    (54, 162, 235, 255),
    (255, 206, 86, 255),
    (75, 192, 192, 255),
    (153, 102, 255, 255),
    (255, 159, 64, 255),
]

def get_color(nombre, mapa):
    if nombre not in mapa:
        mapa[nombre] = PALETA[len(mapa) % len(PALETA)]
    return mapa[nombre]

# ---------------------------------------------------------
# MAPA DE PUNTOS
# ---------------------------------------------------------
def generar_mapa_puntos(df, persona_sel):
    img = imagen_planta.copy()
    draw = ImageDraw.Draw(img, "RGBA")

    if persona_sel != "Todos":
        df = df[df["nombre"] == persona_sel]

    if df.empty:
        return img

    df = df.copy()
    df["punto_norm"] = df["punto"].apply(normalizar)

    offsets = [
        (0, 0), (10, 0), (-10, 0),
        (0, 10), (0, -10),
        (7, 7), (7, -7), (-7, 7), (-7, -7),
    ]
    color_map = {}

    for p_norm, _ in df["punto_norm"].value_counts().items():
        if p_norm not in PUNTOS_COORDS:
            continue

        x0, y0 = PUNTOS_COORDS[p_norm]
        personas = df[df["punto_norm"] == p_norm]["nombre"].unique()

        for i, nombre in enumerate(personas):
            dx, dy = offsets[i % len(offsets)]
            color = get_color(nombre, color_map)

            draw.ellipse(
                (x0 + dx - 6, y0 + dy - 6, x0 + dx + 6, y0 + dy + 6),
                fill=color,
                outline=(255, 255, 255, 255),
                width=1
            )

    return img

# ---------------------------------------------------------
# HEATMAP
# ---------------------------------------------------------
def color_por_intensidad(n: int) -> tuple:
    n_clamped = max(1, min(n, 10))
    t = (n_clamped - 1) / 9.0

    if t < 0.5:
        u = t / 0.5
        r = int(u * 255)
        g = 255
    else:
        u = (t - 0.5) / 0.5
        r = 255
        g = int(255 * (1 - u))

    b = 0
    alpha = int(80 + t * 120)
    return (r, g, b, alpha)

def generar_heatmap(df, persona_sel):
    img = imagen_planta.copy().convert("RGBA")

    if persona_sel != "Todos":
        df = df[df["nombre"] == persona_sel]

    if df.empty:
        return img

    df = df.copy()
    df["punto_norm"] = df["punto"].apply(normalizar)
    counts = df["punto_norm"].value_counts()

    for punto_norm, n in counts.items():
        if punto_norm not in PUNTOS_COORDS:
            continue

        x, y = PUNTOS_COORDS[punto_norm]
        color = color_por_intensidad(int(n))

        capa = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(capa, "RGBA")

        draw.ellipse((x - 40, y - 40, x + 40, y + 40), fill=color)
        capa = capa.filter(ImageFilter.GaussianBlur(18))
        img = Image.alpha_composite(img, capa)

    return img

# ---------------------------------------------------------
# VISTAS
# ---------------------------------------------------------
def vista_registro():
    params = st.query_params
    punto = params.get("punto", "SIN_PUNTO")
    if isinstance(punto, list):
        punto = punto[0]

    st.title("Registro de Asistencia")
    st.subheader(f"Punto: {punto}")

    personas = cargar_personas()
    if personas.empty:
        st.error("No hay personas cargadas.")
        return

    nombres = ["-- Selecciona --"] + sorted(personas["nombre"].tolist())
    sel = st.selectbox("Selecciona tu nombre:", nombres)

    if st.button("Registrar", use_container_width=True):
        if sel == "-- Selecciona --":
            st.error("Selecciona un nombre válido.")
        else:
            permitido, restante = puede_registrar(sel, minutos=5)
            if not permitido:
                st.warning(
                    f"Ya registraste asistencia recientemente.\n\n"
                    f"Espera aproximadamente {restante} minutos."
                )
            else:
                guardar_registro(sel, punto)
                st.success(f"Asistencia registrada correctamente: {sel}")
                st.info("Ya puedes cerrar esta ventana.")

def vista_panel():
    st.title("Panel de Control - QR")

    df = cargar_datos()
    if df.empty:
        st.info("Aún no hay registros.")
        return

    personas = ["Todos"] + sorted(df["nombre"].dropna().unique().tolist())
    persona_sel = st.selectbox("Filtrar por persona:", personas)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Mapa de puntos")
        st.image(generar_mapa_puntos(df, persona_sel), use_container_width=True)

    with col2:
        st.subheader("Mapa de calor")
        st.image(generar_heatmap(df, persona_sel), use_container_width=True)

    st.markdown("---")
    st.dataframe(df.sort_values("timestamp", ascending=False), use_container_width=True)

# ---------------------------------------------------------
# MAIN
# ---------------------------------------------------------
def main():
    st.set_page_config(page_title="Control QR", layout="wide")
    modo = st.query_params.get("modo", "registro")
    if isinstance(modo, list):
        modo = modo[0]

    if modo == "panel":
        vista_panel()
    else:
        vista_registro()

if __name__ == "__main__":
    main()

