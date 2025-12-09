import os
import unicodedata
from datetime import datetime
import time
import math  # 👈 para cos/sin en el mapa de puntos

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
    t = "".join(
        c for c in unicodedata.normalize("NFD", t)
        if unicodedata.category(c) != "Mn"
    )
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
    """
    Devuelve un color RGBA según cantidad de registros.
    1 = verde, 3 = verde amarillento, 5 = amarillo, 7 = naranja, 10+ = rojo.
    """
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
    t = (n_clamped - 1) / 9.0   # 1→0, 10→1
    alpha = int(130 + 120 * t)  # 130–250 aprox

    return (r, g, b, alpha)


# -------------------------
# GENERAR MAPA (PUNTOS o HEATMAP)
# -------------------------

def generar_heatmap(df, selected_person=None, debug=False):
    """
    debug=True  → puntos exactos por persona alrededor del QR (colores diferentes)
    debug=False → heatmap difuminado según número de registros
    """
    img = imagen_planta.copy().convert("RGBA")
    draw = ImageDraw.Draw(img, "RGBA")

    # Filtrar por persona si se seleccionó
    if selected_person and selected_person != "Todos":
        df = df[df["nombre"] == selected_person]

    if df.empty:
        return img

    df = df.copy()
    df["punto_norm"] = df["punto"].apply(normalizar)

    if debug:
        # ------------- MODO PUNTOS: CADA PERSONA UN COLOR ALREDEDOR DEL PUNTO -------------
        # Paleta de colores base (ciclada)
        PALETA = [
            (255, 99, 132, 255),   # rojo rosado
            (54, 162, 235, 255),   # azul
            (75, 192, 192, 255),   # turquesa
            (255, 206, 86, 255),   # amarillo
            (153, 102, 255, 255),  # violeta
            (255, 159, 64, 255),   # naranja
            (0, 200, 83, 255),     # verde
            (233, 30, 99, 255),    # magenta
        ]

        # Para cada punto (QR), tomamos los nombres únicos que han estado allí
        grupos = df.groupby("punto_norm")

        for punto_norm, grupo in grupos:
            if punto_norm not in PUNTOS_COORDS:
                continue

            base_x, base_y = PUNTOS_COORDS[punto_norm]

            # Nombres únicos en ese punto
            nombres_punto = sorted(grupo["nombre"].dropna().unique().tolist())
            num_personas = len(nombres_punto)
            if num_personas == 0:
                continue

            # Radio del "anillo" alrededor del QR donde pondremos los puntos
            cluster_radius = 18  # 👈 no muy lejos del punto
            # Radio de cada puntito
            point_radius = 5     # 👈 más pequeño que antes

            for idx, nombre in enumerate(nombres_punto):
                # Ángulo para distribuir en círculo
                angle = 2 * math.pi * idx / num_personas
                dx = cluster_radius * math.cos(angle)
                dy = cluster_radius * math.sin(angle)

                px = int(base_x + dx)
                py = int(base_y + dy)

                # Color asignado por nombre (ciclado en la paleta)
                color = PALETA[idx % len(PALETA)]

                draw.ellipse(
                    (px - point_radius, py - point_radius, px + point_radius, py + point_radius),
                    fill=color,
                    outline=(255, 255, 255, 255),
                    width=1
                )

    else:
        # ------------- MODO HEATMAP (AGREGADO POR CANTIDAD) -------------
        counts = df["punto_norm"].value_counts()

        for punto_norm, n in counts.items():
            if punto_norm not in PUNTOS_COORDS:
                continue

            x, y = PUNTOS_COORDS[punto_norm]

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
# VISTA DE REGISTRO (expira a los 2 minutos)
# -------------------------

def vista_registro():
    # Control de tiempo por sesión (por pestaña)
    if "inicio_sesion" not in st.session_state:
        st.session_state["inicio_sesion"] = time.time()

    elapsed = time.time() - st.session_state["inicio_sesion"]

    if elapsed > 120:  # 2 minutos
        st.error("⛔ Este enlace ha expirado. Por favor vuelva a escanear el código QR.")
        st.stop()

    # Parámetro del punto desde la URL
    params = st.query_params
    punto = params.get("punto", "SIN_PUNTO")
    if isinstance(punto, list):
        punto = punto[0]

    st.title("Control de Presencia por QR")
    st.subheader(f"Punto de control: {punto}")

    st.markdown(
        """
        <p style="color: #bbb; font-size: 14px;">
        Selecciona tu nombre y presiona <b>Registrar presencia</b>.
        Tienes 2 minutos desde que se abrió esta página.
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
        # Vuelve a verificar el tiempo antes de registrar
        elapsed = time.time() - st.session_state["inicio_sesion"]
        if elapsed > 120:
            st.error("⛔ Tiempo excedido. Vuelva a escanear el código QR.")
            st.stop()

        if nombre_sel == "-- Selecciona --":
            st.error("Por favor selecciona tu nombre.")
        else:
            guardar_registro(nombre=nombre_sel, punto=punto)
            st.success(f"✅ Registro exitoso. Hola, {nombre_sel}.")
            st.info("Puedes cerrar esta ventana.")


# -------------------------
# VISTA PANEL
# -------------------------

def vista_panel():
    st.title("Panel de Control - QR")

    df = cargar_datos()

    if df.empty:
        st.info("Aún no hay registros...")
        return

    # Filtro persona
    personas = ["Todos"] + sorted(df["nombre"].dropna().unique().tolist())
    persona_sel = st.selectbox(
        "Filtrar por persona:",
        personas,
        key="persona_mapa",
    )

    col_puntos, col_heatmap = st.columns([1, 1])

    with col_puntos:
        st.subheader("Mapa con puntos exactos (por persona)")
        img_debug = generar_heatmap(df, persona_sel, debug=True)
        st.image(img_debug, use_column_width=True)

    with col_heatmap:
        st.subheader("Mapa de calor (intensidad por cantidad)")
        img_heat = generar_heatmap(df, persona_sel, debug=False)
        st.image(img_heat, use_column_width=True)

    st.markdown("---")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total de registros", len(df))
    with col2:
        st.metric("Puntos únicos", df["punto"].nunique())
    with col3:
        st.metric("Personas únicas", df["nombre"].nunique())

    st.markdown("---")
    st.subheader("Registros detallados")

    puntos = ["Todos"] + sorted(df["punto"].dropna().unique().tolist())
    punto_sel = st.selectbox("Filtrar por punto", puntos, key="punto_tabla")

    df_filtrado = df.copy()
    if punto_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado["punto"] == punto_sel]

    st.dataframe(
        df_filtrado.sort_values("timestamp", ascending=False),
        use_container_width=True,
    )

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
# MAIN
# -------------------------

def main():
    st.set_page_config(
        page_title="Control de Presencia por QR",
        layout="wide",
    )

    modo = st.query_params.get("modo", "registro")
    if isinstance(modo, list):
        modo = modo[0]

    if modo == "panel":
        vista_panel()
    else:
        vista_registro()


if __name__ == "__main__":
    main()
