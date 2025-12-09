import os
import unicodedata
from datetime import datetime

import pandas as pd
import pytz
import streamlit as st
from PIL import Image, ImageDraw, ImageFilter
import gspread
from google.oauth2.service_account import Credentials


# -------------------------
# RUTAS
# -------------------------

RUTA_ARCHIVO = "registros.csv"
RUTA_PERSONAS = "personas.csv"


# -------------------------
# NORMALIZAR TEXTO
# -------------------------

def normalizar(texto: str) -> str:
    if texto is None:
        return ""
    t = str(texto).strip().lower()
    t = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
    return t


# -------------------------
# IMAGEN BASE
# -------------------------

imagen_planta = Image.open("planta.png").convert("RGBA")


# -------------------------
# COORDENADAS DE PUNTOS
# -------------------------

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


# -------------------------
# GOOGLE SHEETS
# -------------------------

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


# -------------------------
# CARGA DE DATOS
# -------------------------

def cargar_personas():
    if os.path.exists(RUTA_PERSONAS):
        df = pd.read_csv(RUTA_PERSONAS, sep=";", engine="python")
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
    if os.path.exists(RUTA_ARCHIVO):
        try:
            return pd.read_csv(RUTA_ARCHIVO, sep=";", engine="python")
        except Exception:
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
        ws.append_row([timestamp, fecha, hora, nombre, punto], value_input_option="USER_ENTERED")
    except Exception as e:
        st.write("⚠ No se pudo guardar en Google Sheets:", e)


# -------------------------
# COLORES DEL HEATMAP
# -------------------------

def color_por_registros(n: int) -> tuple:
    if n <= 1:
        r, g, b = (80, 255, 80)
    elif n <= 3:
        r, g, b = (173, 255, 47)
    elif n <= 5:
        r, g, b = (255, 255, 0)
    elif n <= 7:
        r, g, b = (255, 165, 0)
    else:
        r, g, b = (255, 0, 0)

    n_clamped = max(1, min(n, 10))
    t = (n_clamped - 1) / 9.0
    alpha = int(130 + 120 * t)

    return (r, g, b, alpha)


# -------------------------
# GENERAR MAPA (PUNTOS o HEATMAP)
# -------------------------

def generar_heatmap(df, selected_person=None, debug=False):

    img = imagen_planta.copy().convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    if selected_person and selected_person != "Todos":
        df = df[df["nombre"] == selected_person]

    if df.empty:
        return img

    df = df.copy()
    df["punto_norm"] = df["punto"].apply(normalizar)

    counts = df["punto_norm"].value_counts()

    for punto_norm, n in counts.items():
        if punto_norm not in PUNTOS_COORDS:
            continue

        x, y = PUNTOS_COORDS[punto_norm]

        # --- MODO PUNTOS EXACTOS ---
        if debug:
            draw.ellipse(
                (x - 15, y - 15, x + 15, y + 15),
                fill=(255, 0, 0, 255),
                outline=(255, 255, 255, 255),
                width=2
            )
        else:
            # --- HEATMAP REAL ---
            color = color_por_registros(int(n))
            heat = Image.new("RGBA", img.size, (0, 0, 0, 0))
            hdraw = ImageDraw.Draw(heat, "RGBA")

            base_radius = 70
            blur_amount = 25

            hdraw.ellipse(
                (x - base_radius, y - base_radius, x + base_radius, y + base_radius),
                fill=color
            )

            heat = heat.filter(ImageFilter.GaussianBlur(blur_amount))
            img = Image.alpha_composite(img, heat)

    return img


# -------------------------
# VISTA DE REGISTRO
# -------------------------

def vista_registro():

    # Expira en 2 minutos
    st.markdown("""
    <script>
    setTimeout(function() {
        document.body.innerHTML = `
        <div style="display:flex;height:100vh;justify-content:center;align-items:center;background:black;color:white;font-size:28px;">
            ⛔ Este enlace ha expirado. Escanee nuevamente el QR.
        </div>`;
    }, 2 * 60 * 1000);
    </script>
    """, unsafe_allow_html=True)

    params = st.query_params
    punto = params.get("punto", "SIN_PUNTO")
    if isinstance(punto, list):
        punto = punto[0]

    st.title("Control de Presencia por QR")
    st.subheader(f"Punto de control: {punto}")

    st.write("Seleccione su nombre:")

    personas = cargar_personas()
    if personas.empty:
        st.error("No hay personas registradas.")
        return

    nombres = sorted(personas["nombre"].tolist())
    nombre_sel = st.selectbox("Nombre:", ["-- Selecciona --"] + nombres)

    if st.button("Registrar presencia", use_container_width=True):
        if nombre_sel == "-- Selecciona --":
            st.error("Debe seleccionar un nombre.")
        else:
            guardar_registro(nombre_sel, punto)
            st.success("Registro exitoso.")


# -------------------------
# VISTA PANEL
# -------------------------

def vista_panel():

    # Auto-expiración 2 minutos
    st.markdown("""
    <script>
    setTimeout(function() {
        document.body.innerHTML = `
        <div style="display:flex;height:100vh;justify-content:center;align-items:center;background:black;color:white;font-size:28px;">
            ⛔ La sesión ha expirado. Escanee nuevamente el QR.
        </div>`;
    }, 2 * 60 * 1000);
    </script>
    """, unsafe_allow_html=True)

    st.title("Panel de Control - QR")

    df = cargar_datos()
    if df.empty:
        st.info("No hay registros.")
        return

    personas = ["Todos"] + sorted(df["nombre"].unique().tolist())
    persona_sel = st.selectbox("Filtrar por persona:", personas)

    col1, col2 = st.columns([1, 1])

    with col1:
        st.subheader("Mapa con puntos exactos")
        m1 = generar_heatmap(df, persona_sel, debug=True)
        st.image(m1, use_container_width=True)

    with col2:
        st.subheader("Mapa de calor")
        m2 = generar_heatmap(df, persona_sel, debug=False)
        st.image(m2, use_container_width=True)

    st.markdown("---")

    st.subheader("Registros detallados")
    st.dataframe(df.sort_values("timestamp", ascending=False), use_container_width=True)


# -------------------------
# MAIN
# -------------------------

def main():
    st.set_page_config(page_title="Control de Presencia QR", layout="wide")
    modo = st.query_params.get("modo", "registro")

    if isinstance(modo, list):
        modo = modo[0]

    if modo == "panel":
        vista_panel()
    else:
        vista_registro()


if __name__ == "__main__":
    main()

