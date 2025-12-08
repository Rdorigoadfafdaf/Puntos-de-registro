import os
import unicodedata
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

# -------------------------
# Utilidades de normalización
# -------------------------

def normalizar(texto: str) -> str:
    """Convierte texto a minúsculas, sin tildes ni espacios extra."""
    if texto is None:
        return ""
    t = str(texto).strip().lower()
    t = "".join(
        c for c in unicodedata.normalize("NFD", t)
        if unicodedata.category(c) != "Mn"
    )
    return t

# Imagen de la planta para el mapa de calor (RGBA para transparencia)
imagen_planta = Image.open("planta.png").convert("RGBA")

# Puntos de la planta: coordenadas + color (RGBA), claves normalizadas
PUNTOS = {
    # esquina inferior izquierda hacia la derecha, según tu imagen marcada
    normalizar("Ventanas"): {
        "coord": (195, 608),
        "color": (0, 255, 0, 180),        # verde
    },
    normalizar("Faja 2"): {
        "coord": (252, 587),
        "color": (255, 105, 180, 180),    # rosado
    },
    normalizar("Chancado Primario"): {
        "coord": (330, 560),
        "color": (160, 32, 240, 180),     # morado
    },
    normalizar("Chancado Secundario"): {
        "coord": (388, 533),
        "color": (0, 191, 255, 180),      # celeste
    },
    normalizar("Cuarto Control"): {
        "coord": (650, 760),
        "color": (255, 255, 255, 200),    # blanco
    },
    normalizar("Filtro Zn"): {
        "coord": (455, 409),
        "color": (255, 255, 0, 180),      # amarillo
    },
    normalizar("Flotacion Zn"): {
        "coord": (623, 501),
        "color": (255, 165, 0, 180),      # naranja
    },
    normalizar("Flotacion Pb"): {
        "coord": (691, 423),
        "color": (255, 0, 0, 180),        # rojo
    },
    normalizar("Tripper"): {
        "coord": (766, 452),
        "color": (0, 128, 0, 180),        # verde más oscuro
    },
    normalizar("Molienda"): {
        "coord": (802, 480),
        "color": (30, 144, 255, 180),     # azul
    },
    normalizar("Nido de Ciclones 4"): {
        "coord": (811, 307),
        "color": (0, 0, 0, 200),          # negro
    },
}

def obtener_meta_punto(p_norm: str):
    """
    Devuelve un dict con coord y color para un punto normalizado.
    Usa coincidencia exacta o parcial (contiene).
    """
    # 1) Coincidencia exacta
    if p_norm in PUNTOS:
        return PUNTOS[p_norm]

    # 2) Coincidencia flexible, por si el texto viene con algo más
    for key, meta in PUNTOS.items():
        if key in p_norm or p_norm in key:
            return meta

    return None

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
    """Dibuja el mapa con los colores de cada punto sobre planta.png."""
    base = imagen_planta.copy()
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Filtrar por persona si se seleccionó una
    if selected_person and selected_person != "Todos":
        df = df[df["nombre"] == selected_person]

    if df.empty:
        return base.convert("RGB")

    # Normalizar nombres de punto
    df = df.copy()
    df["punto_norm"] = df["punto"].apply(normalizar)

    # Contar registros por punto normalizado
    counts = df["punto_norm"].value_counts()

    for p_norm, n in counts.items():
        meta = obtener_meta_punto(p_norm)
        if meta is None:
            continue

        x, y = meta["coord"]
        color = meta["color"]  # RGBA

        # Radio proporcional a cantidad de registros
        r = min(70, 18 + n * 6)

        # Círculo semi-transparente sobre overlay
        draw.ellipse(
            (x - r, y - r, x + r, y + r),
            fill=color,
            outline=(255, 255, 255, 220),  # borde blanco para resaltar
            width=2,
        )

    combinado = Image.alpha_composite(base, overlay)
    return combinado.convert("RGB")

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
        st.info("Aún no hay registros...")
        return

    # (Opcional) Debug para ver qué puntos hay realmente
    # st.write("Puntos detectados en registros:", df["punto"].unique())

    # ---- Mapa de calor ----
    st.markdown("---")
    st.subheader("Mapa de colores por punto en la planta")

    personas = ["Todos"] + sorted(df["nombre"].dropna().unique().tolist())
    persona_sel = st.selectbox(
        "Filtrar por persona:",
        personas,
        key="persona_mapa",
    )

    mapa_img = generar_heatmap(df, persona_sel)
    st.image(mapa_img, use_container_width=True)

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
    punto_sel = st.selectbox("Filtrar por punto", puntos, key="punto_tabla")

    df_filtrado = df.copy()
    if punto_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado["punto"] == punto_sel]

    st.subheader("Registros detallados")
    st.dataframe(
        df_filtrado.sort_values("timestamp", ascending=False),
        use_container_width=True,
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


