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


# Imagen de la planta para el mapa de calor (RGBA para transparencias)
imagen_planta = Image.open("planta.png").convert("RGBA")

# Coordenadas aproximadas (en píxeles) de cada punto sobre la imagen
# Claves ya normalizadas para facilitar el match con los registros
PUNTOS_COORDS = {
    normalizar("Ventanas"): (195, 608),
    normalizar("Faja 2"): (252, 587),
    normalizar("Chancado Primario"): (330, 560),
    normalizar("Chancado Secundario"): (388, 533),
    normalizar("Cuarto Control"): (650, 760),
    normalizar("Filtro Zn"): (455, 409),
    normalizar("Flotacion Zn"): (623, 501),
    normalizar("Flotación Zn"): (623, 501),   # por si viene con tilde
    normalizar("Flotacion Pb"): (691, 423),
    normalizar("Flotación Pb"): (691, 423),
    normalizar("Tripper"): (766, 452),
    normalizar("Molienda"): (802, 480),
    normalizar("Nido de Ciclones 4"): (811, 307),
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
# Mapa de calor (escala térmica)
# -------------------------

def color_heat(value: float) -> tuple:
    """
    Devuelve un color RGBA según el valor normalizado 0-1.
    0   → completamente transparente (sin color)
    0.33→ verde
    0.66→ amarillo
    1   → rojo fuerte
    """
    v = max(0.0, min(1.0, value))

    # Si el valor es 0, devolvemos TRANSPARENTE (no se pinta nada)
    if v <= 0:
        return (0, 0, 0, 0)

    # Colores de la escala térmica
    if v < 1/3:  # azul → verde (pero con alpha bajo para valores pequeños)
        t = v / (1/3)
        r = 0
        g = int(255 * t)
        b = int(255 * (1 - t))
    elif v < 2/3:  # verde → amarillo
        t = (v - 1/3) / (1/3)
        r = int(255 * t)
        g = 255
        b = 0
    else:  # amarillo → rojo
        t = (v - 2/3) / (1/3)
        r = 255
        g = int(255 * (1 - t))
        b = 0

    # Alpha progresivo (más valor → más visible)
    alpha = int(255 * v)

    return (r, g, b, alpha)


def generar_heatmap(df, selected_person=None):
    """
    Genera un mapa de calor tipo 'heatmap de fútbol' sobre planta.png usando Pillow.
    - Puntos sin registros → ningún color (no se pinta nada).
    - 1 a 10 registros → escala térmica azul→verde→amarillo→rojo.
    """
    # Copiamos la imagen base
    img = imagen_planta.copy().convert("RGBA")

    # Capa en escala de grises donde pintamos intensidades (0–255)
    heat = Image.new("L", img.size, 0)
    draw = ImageDraw.Draw(heat)

    # Filtrar registros por persona (si se seleccionó una)
    if selected_person and selected_person != "Todos":
        df = df[df["nombre"] == selected_person]

    if df.empty:
        # No hay registros → devolvemos solo la imagen de la planta
        return img

    # Normalizar nombres de punto para que coincidan con las claves de PUNTOS_COORDS
    df = df.copy()
    df["punto_norm"] = df["punto"].apply(normalizar)

    # Conteo de registros por punto normalizado
    counts = df["punto_norm"].value_counts()

    # ESCALA FIJA:
    # 1 registro = mínimo visible
    # 10 registros = máximo calor
    ESCALA_MIN = 1
    ESCALA_MAX = 10

    for punto_norm, n in counts.items():
        if punto_norm not in PUNTOS_COORDS:
            continue

        x, y = PUNTOS_COORDS[punto_norm]

        # Normalizamos n a [0,1] según la escala fija
        n_clamped = max(ESCALA_MIN, min(n, ESCALA_MAX))
        t = (n_clamped - ESCALA_MIN) / (ESCALA_MAX - ESCALA_MIN)  # 0 → 1

        # Intensidad en la capa de grises (entre ~80 y 255) donde hay registros
        intensidad = int(80 + t * 175)  # 80 (pocos registros) → 255 (muchos registros)

        # Radio del “spot” (como las zonas del campo en un heatmap de fútbol)
        radius = 80

        draw.ellipse(
            (x - radius, y - radius, x + radius, y + radius),
            fill=intensidad
        )

    # Difuminamos fuerte para que las zonas se mezclen
    heat = heat.filter(ImageFilter.GaussianBlur(60))

    # ---- Aplicar colormap azul→verde→amarillo→rojo usando color_heat() ----
    # Precreamos LUTs (tablas) para R, G, B, A a partir de la escala 0–255 de la capa de grises
    lut_r, lut_g, lut_b, lut_a = [], [], [], []
    for i in range(256):
        r, g, b, a = color_heat(i / 255.0)  # i/255.0 → valor normalizado 0–1
        lut_r.append(r)
        lut_g.append(g)
        lut_b.append(b)
        lut_a.append(a)

    # Aplicamos las LUTs a la imagen en escala de grises
    r = heat.point(lut_r)
    g = heat.point(lut_g)
    b = heat.point(lut_b)
    a = heat.point(lut_a)

    heat_rgba = Image.merge("RGBA", (r, g, b, a))

    # Combinamos el heatmap coloreado con la imagen original
    final = Image.alpha_composite(img, heat_rgba)

    return final


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

    # ---- Mapa de calor ----
    st.markdown("---")
    st.subheader("Mapa de calor en la planta")

    personas = ["Todos"] + sorted(df["nombre"].dropna().unique().tolist())
    persona_sel = st.selectbox(
        "Filtrar por persona:",
        personas,
        key="persona_mapa",
    )

    mapa_img = generar_heatmap(df, persona_sel)
    st.image(mapa_img, use_container_width=True)  # ✅ cambiado

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
    st.subheader("Registros detallados")  # la sacamos fuera del if para que siempre aparezca

    puntos = ["Todos"] + sorted(df["punto"].dropna().unique().tolist())
    punto_sel = st.selectbox("Filtrar por punto", puntos, key="punto_tabla")

    df_filtrado = df.copy()
    if punto_sel != "Todos":
        df_filtrado = df_filtrado[df_filtrado["punto"] == punto_sel]

    st.dataframe(
        df_filtrado.sort_values("timestamp", ascending=False),
        use_container_width=True,  # ✅ cambiado
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
