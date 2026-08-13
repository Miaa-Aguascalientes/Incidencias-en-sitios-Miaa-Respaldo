import streamlit as st
import pandas as pd
import geopandas as gpd
from sqlalchemy import create_engine
from datetime import datetime, timedelta
import pytz
from streamlit_folium import st_folium
import folium
from folium.plugins import Fullscreen
from folium.features import DivIcon
from shapely import wkt
import re
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sqlalchemy.exc import OperationalError, InterfaceError

# Configuración
mexico_tz = pytz.timezone('America/Mexico_City')
def get_now_mexico(): return datetime.now(mexico_tz)

st.set_page_config(page_title="Incidencias MIAA", layout="wide", initial_sidebar_state="collapsed")

# Estilos CSS
st.markdown("""
    <style>
    .stApp { background-color: #050a10 !important; }
    #MainMenu, header, footer { visibility: hidden !important; height: 0 !important; }
    .block-container { padding-top: 0rem !important; margin-top: -10px !important; }
    .top-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; gap: 10px; }
    .top-logo-group { display: flex; align-items: center; gap: 12px; }
    .top-title-text { color: #ffffff; font-size: 13px; font-weight: 600; line-height: 1.2; margin: 0; }
    .section-header { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
    .section-title { color: white; font-size: 18px !important; font-weight: bold; margin: 0 !important; }
    .card { background: #111827; padding: 5px; border-radius: 12px; border-left: 6px solid; margin-bottom: 5px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3); }
    .label { font-size: 10px; color: #9ca3af; text-transform: uppercase; }
    .value { font-size: 14px; color: #f3f4f6; font-weight: 500; }
    
    /* Recuadro de color blanco más delgado envolviendo al botón de los detalles */
    div[data-testid="stExpander"] {
        border: 1px solid #ffffff !important;
        border-radius: 8px !important;
        background-color: #111827 !important;
        overflow: hidden;
    }

    /* Forzar texto en el Expander (Ver Detalles), Colonias y Supervisores */
    div[data-testid="stExpander"] summary p, 
    div[data-testid="stExpander"] summary span, 
    div[data-testid="stExpander"] summary {
        color: #ffffff !important;
        font-weight: 600 !important;
    }

    /* Forzar color azul brillante en el texto y elementos del toggle */
    div[data-testid="stToggle"] label p,
    div[data-testid="stToggle"] label span,
    .stToggle p,
    .stToggle span {
        color: #00bfff !important;
        font-weight: 700 !important;
    }

    /* Forzar el color azul brillante en el fondo del interruptor cuando está activado */
    div[data-testid="stToggle"] div[data-baseweb="checkbox"] input:checked + div {
        background-color: #00bfff !important;
    }
    
    div[data-testid="stToggle"] span[data-baseweb="tag"],
    div[data-testid="stToggle"] div[class*="st-ae"] {
        background-color: #00bfff !important;
    }

    /* Forzar texto blanco súper brillante en títulos Markdown e inputs de texto/labels en dispositivos móviles y web */
    h3, .stMarkdown h3, div[data-testid="stMarkdownContainer"] h3 {
        color: #ffffff !important;
        font-weight: 700 !important;
    }

    label, .stSelectbox label, div[data-baseweb="select"] span, .stTextInput label {
        color: #ffffff !important;
        font-weight: 600 !important;
    }
    </style>
""", unsafe_allow_html=True)

# Conexiones con timeout explícito de conexión
@st.cache_resource
def get_engine():
    db = st.secrets["mysql_scada"]
    return create_engine(
        f"mysql+pymysql://{db['user']}:{db['password']}@{db['host']}/{db['database']}", 
        pool_pre_ping=True, 
        pool_recycle=3600,
        connect_args={'connect_timeout': 15}
    )

@st.cache_resource
def get_engine_telemetria():
    db = st.secrets["mysql_telemetria"]
    return create_engine(
        f"mysql+pymysql://{db['user']}:{db['password']}@{db['host']}/{db['database']}", 
        pool_pre_ping=True, 
        pool_recycle=3600,
        connect_args={'connect_timeout': 15}
    )

@retry(
    stop=stop_after_attempt(5), 
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_exception_type((OperationalError, InterfaceError)),
    reraise=True
)
@st.cache_data(ttl=60)
def get_data():
    return pd.read_sql("SELECT * FROM vw_incidencias_en_pozos ORDER BY FECHA_HORA_INICIO DESC", get_engine())

@retry(
    stop=stop_after_attempt(3), 
    wait=wait_exponential(multiplier=1, min=1, max=5),
    retry=retry_if_exception_type((OperationalError, InterfaceError)),
    reraise=True
)
@st.cache_data(ttl=60)
def get_geometries(num_pozo):
    query = f"SELECT ST_AsText(geom) as geom_wkt, Col_atl, Sector, Distrito, Supervisor FROM Diccionario_colonias WHERE Pozos LIKE '%%{num_pozo}%%'"
    try:
        df = pd.read_sql(query, get_engine_telemetria())
        if not df.empty and df['geom_wkt'].iloc[0] is not None:
            df['geometry'] = df['geom_wkt'].apply(wkt.loads)
            gdf = gpd.GeoDataFrame(df, geometry='geometry')
            gdf.set_crs(epsg=32613, inplace=True)
            return gdf.to_crs(epsg=4326)
    except Exception:
        return None
    return None

@st.cache_data(ttl=60)
def get_colonias_info(num_pozo):
    query = f"SELECT Col_atl, Sector, Distrito, Supervisor FROM Diccionario_colonias WHERE Pozos LIKE '%%{num_pozo}%%'"
    try:
        df = pd.read_sql(query, get_engine_telemetria())
        return df if not df.empty else None
    except Exception:
        return None

@st.cache_data(ttl=60)
def get_todas_colonias():
    query = "SELECT DISTINCT Col_atl FROM Diccionario_colonias WHERE Col_atl IS NOT NULL ORDER BY Col_atl ASC"
    try:
        df = pd.read_sql(query, get_engine_telemetria())
        return df['Col_atl'].tolist() if not df.empty else []
    except Exception:
        return []

@st.cache_data(ttl=60)
def buscar_afectacion_diccionario(nombre_colonia):
    query = f"SELECT Col_atl, Sector, Distrito, Pozos, Supervisor FROM Diccionario_colonias WHERE Col_atl LIKE '%%{nombre_colonia}%%'"
    try:
        df = pd.read_sql(query, get_engine_telemetria())
        return df if not df.empty else None
    except Exception:
        return None

@st.fragment
def dibujar_mapa(gdf, color, unique_key):
    m = folium.Map(
        location=[gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()], 
        zoom_start=13, 
        tiles=None,
        attribution_control=False
    )
    folium.TileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", name="Calles", attr="&copy; OpenStreetMap contributors").add_to(m)
    folium.TileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", name="Satélite", attr="Esri").add_to(m)
    folium.TileLayer("CartoDB dark_matter", name="CartoDB dark_matter", attr="&copy; CartoDB").add_to(m)
    folium.GeoJson(gdf, style_function=lambda x: {'fillColor': color, 'color': color, 'weight': 2, 'fillOpacity': 0.4}).add_to(m)
    
    for _, r in gdf.iterrows():
        folium.Marker(
            location=[r.geometry.centroid.y, r.geometry.centroid.x],
            icon=DivIcon(
                icon_anchor=(-5, 10), 
                html=f'<div style="font-size: 8px; color: white; background: rgba(0,0,0,0.7); padding: 2px; white-space: nowrap; border-radius: 3px;">{r["Col_atl"]}</div>'
            )
        ).add_to(m)

    Fullscreen(position='topright').add_to(m)
    folium.LayerControl(position='topleft').add_to(m)
    st_folium(m, height=300, use_container_width=True, key=unique_key)

def format_supervisor(text):
    wa_icon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="white" style="vertical-align: middle; margin-right: 4px;"><path d="M12.01 2c-5.51 0-9.99 4.48-9.99 9.99 0 1.76.46 3.48 1.33 5l-1.33 4.88 5-1.31c1.47.8 3.16 1.22 4.87 1.22 5.51 0 9.99-4.48 9.99-9.99S17.52 2 12.01 2zm0 18c-1.46 0-2.88-.41-4.11-1.18l-.29-.18-3.05.8.81-2.97-.18-.3C3.65 14.88 3.23 13.43 3.23 11.99 3.23 7.02 7.04 3.2 12.01 3.2s8.78 3.82 8.78 8.79-3.95 8.79-8.78 8.79zM16.48 15.5c-.27-.13-1.61-.79-1.86-.88s-.43-.13-.61.13c-.18.26-.69.88-.85 1.06-.16.18-.32.2-.59.07s-1.14-.42-2.17-1.34c-.8-.71-1.34-1.59-1.5-1.86s-.01-.43.11-.57c.12-.13.27-.34.4-.51.13-.17.17-.3.26-.51.09-.2.04-.37-.02-.51s-.61-1.48-.84-2.03c-.22-.53-.45-.46-.61-.46-.16 0-.34-.01-.51-.01s-.44.06-.67.31c-.23.25-.88.86-.88 2.09s.6 2.42.69 2.55c.09.13 1.73 2.64 4.19 3.7c.59.25 1.05.4 1.41.51.59.19 1.13.16 1.56.1.48-.07 1.51-.62 1.72-1.21.21-.59.21-1.1.15-1.21-.06-.11-.23-.17-.5-.3z"/></svg>'
    tel_icon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="white" style="vertical-align: middle; margin-right: 4px;"><path d="M20.01 15.38c-1.23 0-2.42-.19-3.53-.55-.35-.11-.74-.03-1.01.24l-1.57 1.97c-2.83-1.35-5.48-3.9-6.89-6.83l1.95-1.66c.27-.28.35-.67.24-1.02-.36-1.11-.55-2.3-.55-3.53 0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1 0 9.39 7.61 17 17 17 .55 0 1-.45 1-1v-3.49c0-.55-.45-1-1-1z"/></svg>'
    
    match = re.search(r'(\d{3})\D?(\d{3})\D?(\d{2})\D?(\d{2})', text)
    if match:
        num = f"{match.group(1)}{match.group(2)}{match.group(3)}{match.group(4)}"
        tel_full = f"52{num}"
        return text.replace(match.group(0), f"<strong style='color: #ffffff;'>{match.group(0)}</strong>") + f"""
            <div style='margin-top: 8px; display: flex; gap: 10px;'>
                <a href='tel:+52{num}' style='text-decoration: none; background: #10b981; color: white; padding: 6px 40px; border-radius: 5px; font-size: 12px; display: inline-flex; align-items: center;'>{tel_icon} Llamar</a>
                <a href='https://wa.me/{tel_full}' target='_blank' style='text-decoration: none; background: #25d366; color: white; padding: 6px 28px; border-radius: 5px; font-size: 12px; display: inline-flex; align-items: center;'>{wa_icon} WhatsApp</a>
            </div>"""
    return f"<span style='color: #ffffff;'>{text}</span>"

def render_card(row, color, unique_key, con_mapa=True):
    inicio = pd.to_datetime(row['FECHA_HORA_INICIO']).tz_localize(None).tz_localize('America/Mexico_City')
    fin_raw = row.get('FECHA_HORA_FIN')
    duracion = (pd.to_datetime(fin_raw).tz_localize(None).tz_localize('America/Mexico_City') - inicio) if pd.notnull(fin_raw) else (get_now_mexico() - inicio)
    
    st.markdown(f"""
    <div class='card' style='border-left-color: {color};'>
        <div style='display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;'>
            <div style='font-weight: bold; font-size: 16px; color: white;'>Pozo {row.get('NUM_POZO')}</div>
            <div style='background: {color}33; color: {color}; padding: 2px 8px; border-radius: 6px; font-size: 10px; font-weight: bold;'>{row['ESTATUS']}</div>
        </div>
        <div class='label'>Diagnóstico</div>
        <div class='value' style='margin-bottom: 12px;'>{row.get('DIAGNOSTICO_FALLA', 'Sin diagnóstico')}</div>
        <div style='display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px;'>
            <div><div class='label'>Inicio</div><div class='value'>{inicio.strftime('%d/%m %H:%M')}</div></div>
            <div><div class='label'>Cierre</div><div class='value'>{'N/A' if pd.isnull(fin_raw) else pd.to_datetime(fin_raw).strftime('%d/%m %H:%M')}</div></div>
            <div><div class='label'>Duración</div><div class='value' style='color: {color};'>{str(duracion).split('.')[0].replace('days', 'Días').replace('day', 'Día')}</div></div>
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    with st.expander("🌎 Ver Detalles"):
        if con_mapa:
            gdf = get_geometries(row.get('NUM_POZO'))
            if gdf is not None and not gdf.empty:
                st.markdown(f"<div style='font-size: 12px; color: #9ca3af;'><strong>Colonias:</strong> <span style='color: #ffffff; font-weight: 500;'>{', '.join(gdf['Col_atl'].unique())}</span></div>", unsafe_allow_html=True)
                dibujar_mapa(gdf, color, unique_key)
                sectores = ', '.join(gdf['Sector'].dropna().unique())
                distritos = ', '.join(gdf['Distrito'].dropna().unique())
                raw_supervisores = gdf['Supervisor'].dropna().unique()
                supervisores_list = []
                for item in raw_supervisores:
                    items = [s.strip() for s in item.split(',') if s.strip()]
                    supervisores_list.extend([format_supervisor(s) for s in items])
                supervisores_html = "".join([f"<div style='margin-bottom: 15px; border-bottom: 1px solid #1f2937; padding-bottom: 10px; color: #ffffff;'>• {s}</div>" for s in supervisores_list])
                st.markdown(f"""
                    <div style='display: flex; flex-direction: column; gap: 8px; margin-top: 10px;'>
                        <div style='padding: 8px; background: #050a10; border-radius: 5px; border: 1px solid #374151;'>
                            <div class='label'>Sector</div><div class='value'>{sectores if sectores else 'N/A'}</div>
                        </div>
                        <div style='padding: 8px; background: #050a10; border-radius: 5px; border: 1px solid #374151;'>
                            <div class='label'>Distrito</div><div class='value'>{distritos if distritos else 'N/A'}</div>
                        </div>
                        <div style='padding: 0px; margin-top: 15px;'>
                            <div class='label' style='margin-bottom: 10px;'>Supervisores (Contacto móvil)</div>
                            <div style='margin-top: 0px;'>{supervisores_html if supervisores_list else '<span style="color: #ffffff;">N/A</span>'}</div>
                        </div>   
                    </div>
                """, unsafe_allow_html=True)
        else:
            df_info = get_colonias_info(row.get('NUM_POZO'))
            if df_info is not None and not df_info.empty:
                colonias = ', '.join(df_info['Col_atl'].dropna().unique())
                sectores = ', '.join(df_info['Sector'].dropna().unique())
                distritos = ', '.join(df_info['Distrito'].dropna().unique())
                raw_supervisores = df_info['Supervisor'].dropna().unique()
                supervisores_list = []
                for item in raw_supervisores:
                    items = [s.strip() for s in item.split(',') if s.strip()]
                    supervisores_list.extend([format_supervisor(s) for s in items])
                supervisores_html = "".join([f"<div style='margin-bottom: 15px; border-bottom: 1px solid #1f2937; padding-bottom: 10px; color: #ffffff;'>• {s}</div>" for s in supervisores_list])
                
                st.markdown(f"""
                    <div style='display: flex; flex-direction: column; gap: 8px; margin-top: 10px;'>
                        <div style='font-size: 12px; color: #9ca3af;'><strong>Colonias:</strong> <span style='color: #ffffff; font-weight: 500;'>{colonias if colonias else 'N/A'}</span></div>
                        <div style='padding: 8px; background: #050a10; border-radius: 5px; border: 1px solid #374151;'>
                            <div class='label'>Sector</div><div class='value'>{sectores if sectores else 'N/A'}</div>
                        </div>
                        <div style='padding: 8px; background: #050a10; border-radius: 5px; border: 1px solid #374151;'>
                            <div class='label'>Distrito</div><div class='value'>{distritos if distritos else 'N/A'}</div>
                        </div>
                        <div style='padding: 0px; margin-top: 15px;'>
                            <div class='label' style='margin-bottom: 10px;'>Supervisores (Contacto móvil)</div>
                            <div style='margin-top: 0px;'>{supervisores_html if supervisores_list else '<span style="color: #ffffff;">N/A</span>'}</div>
                        </div>   
                    </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("<div style='font-size: 12px; color: #9ca3af;'>Sin información de colonias registrada.</div>", unsafe_allow_html=True)

# LÓGICA PRINCIPAL
st.markdown("""
    <div class="top-header">
        <div class="top-logo-group">
            <img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Logos/38504978c8f77a4dac38ad476f74dbdee6af2cad/LogoMIAA.svg" width="110">
            <div class="top-title-text">Modelo Integral de Aguas<br>de Aguascalientes</div>
        </div>
    </div>
""", unsafe_allow_html=True)

st.markdown("""
    <div class="section-header">
        <img src="https://github.com/Miaa-Aguascalientes/Logos/badge.svg?raw=true" width="40" onerror="this.style.display='none'">
        <h1 class="section-title">Registro de Incidencias</h1>
    </div>
""", unsafe_allow_html=True)

# Módulo de Búsqueda de Colonias controlado por un st.toggle con color azul brillante (#00bfff)
activar_busqueda = st.toggle("Buscador de colonias", value=False)

if activar_busqueda:
    st.markdown("### 🔍 Consultar Afectación por Colonia")
    lista_colonias = get_todas_colonias()
    colonia_input = st.selectbox(
        "Selecciona o escribe el nombre de la colonia:",
        options=[""] + lista_colonias,
        format_func=lambda x: "Selecciona una colonia..." if x == "" else x
    )

    if colonia_input:
        df_col_db = buscar_afectacion_diccionario(colonia_input)
        if df_col_db is None or df_col_db.empty:
            st.warning(f"No se encontró información registrada para la colonia: '{colonia_input}' en el diccionario.")
        else:
            try:
                df_incidencias = get_data()
                df_incidencias['FECHA_HORA_FIN'] = pd.to_datetime(df_incidencias['FECHA_HORA_FIN'])
                
                hoy = get_now_mexico().date()
                ayer = hoy - timedelta(days=1)
                
                df_activas_filtradas = df_incidencias[~df_incidencias['ESTATUS'].str.contains('CERRADA', case=False, na=False)]
                df_cerradas_recientes = df_incidencias[
                    df_incidencias['ESTATUS'].str.contains('CERRADA', case=False, na=False) & 
                    df_incidencias['FECHA_HORA_FIN'].notnull() & 
                    df_incidencias['FECHA_HORA_FIN'].dt.date.isin([hoy, ayer])
                ]
                
                pozos_asociados = set()
                for pozos_str in df_col_db['Pozos'].dropna():
                    tokens = re.findall(r'([A-Za-z]?\s*-?\s*\d+[A-Za-z]?)', str(pozos_str))
                    for t in tokens:
                        limpio = t.replace(' ', '').upper()
                        if limpio:
                            pozos_asociados.add(limpio)
                
                def coincide_pozo(val):
                    v_str = str(val).replace(' ', '').upper()
                    variants = {v_str, f"P-{v_str}", v_str.replace('P-', '')}
                    return bool(variants.intersection(pozos_asociados))

                # 1. Buscar en incidencias activas
                incidencias_en_zona = pd.DataFrame()
                if not df_activas_filtradas.empty and 'NUM_POZO' in df_activas_filtradas.columns:
                    mask = df_activas_filtradas['NUM_POZO'].apply(coincide_pozo)
                    incidencias_en_zona = df_activas_filtradas[mask]
                
                # 2. Buscar en incidencias cerradas de hoy o ayer
                cerradas_en_zona = pd.DataFrame()
                if not df_cerradas_recientes.empty and 'NUM_POZO' in df_cerradas_recientes.columns:
                    mask_cerradas = df_cerradas_recientes['NUM_POZO'].apply(coincide_pozo)
                    cerradas_en_zona = df_cerradas_recientes[mask_cerradas]

                # Renderizar resultados activos
                if not incidencias_en_zona.empty:
                    for _, inc in incidencias_en_zona.iterrows():
                        st.markdown(f"""
                            <div style='background: #1f2937; padding: 10px; border-radius: 8px; border-left: 4px solid #FF4C4C; margin-bottom: 8px;'>
                                <div style='color: white; font-weight: bold;'>Pozo {inc.get('NUM_POZO')} - Estatus: {inc.get('ESTATUS')}</div>
                                <div style='color: #9ca3af; font-size: 12px;'>Diagnóstico: {inc.get('DIAGNOSTICO_FALLA', 'Sin diagnóstico')}</div>
                                <div style='color: #9ca3af; font-size: 12px;'>Inicio: {inc.get('FECHA_HORA_INICIO')}</div>
                            </div>
                        """, unsafe_allow_html=True)
                
                # Renderizar resultados cerrados hoy o ayer con mensaje personalizado
                if not cerradas_en_zona.empty:
                    for _, inc in cerradas_en_zona.iterrows():
                        fecha_cierre_str = pd.to_datetime(inc.get('FECHA_HORA_FIN')).strftime('%d/%m/%Y a las %H:%M')
                        st.markdown(f"""
                            <div style='background: #1f2937; padding: 10px; border-radius: 8px; border-left: 4px solid #28a745; margin-bottom: 8px;'>
                                <div style='color: white; font-weight: bold;'>Pozo {inc.get('NUM_POZO')}</div>
                                <div style='color: #f3f4f6; font-size: 13px; margin-top: 4px;'>Tuvo una incidencia registrada pero ya está cerrada con fecha del <strong>{fecha_cierre_str}</strong>.</div>
                                <div style='color: #9ca3af; font-size: 12px; margin-top: 2px;'>Diagnóstico: {inc.get('DIAGNOSTICO_FALLA', 'Sin diagnóstico')}</div>
                            </div>
                        """, unsafe_allow_html=True)

                if incidencias_en_zona.empty and cerradas_en_zona.empty:
                    st.info(f"✅ **Sin afectación actual ni reciente.** La colonia está registrada, pero ninguno de sus pozos asociados tiene incidencias activas o cerradas recientemente (hoy o ayer).")
            except Exception as e:
                st.error(f"Error al validar pozos para la colonia: {e}")

st.markdown("---")

try:
    df = get_data()
    df['FECHA_HORA_INICIO'] = pd.to_datetime(df['FECHA_HORA_INICIO'])
    df['FECHA_HORA_FIN'] = pd.to_datetime(df['FECHA_HORA_FIN'])
    hoy = get_now_mexico().date()
    
    activas = df[~df['ESTATUS'].str.contains('CERRADA', case=False, na=False)]
    cerradas_hoy = df[(df['ESTATUS'].str.contains('CERRADA', case=False, na=False)) & (df['FECHA_HORA_FIN'].dt.date == hoy)]
    historico = df[df['ESTATUS'].str.contains('CERRADA', case=False, na=False) & df['FECHA_HORA_FIN'].notnull()].copy()
    
    n_procesos = len(activas[activas['ESTATUS'].str.contains('PROCESO', case=False, na=False)])
    n_pendientes = len(activas[activas['ESTATUS'].str.contains('PENDIENTE', case=False, na=False)])
    n_cerradas = len(cerradas_hoy)
    n_total = len(activas) + len(cerradas_hoy)
    
    st.markdown(f"""
        <div style="display: flex; justify-content: space-between; gap: 10px; margin-bottom: 20px;">
            <div style="flex: 1; background-color: #111827; padding: 10px; border-radius: 8px; border-top: 3px solid #FFD700; text-align: center;">
                <div style="color: #FFD700; font-weight: bold; font-size: 9px; text-transform: uppercase;">En Proceso</div>
                <div style="font-size: 20px; color: white; font-weight: bold;">{n_procesos}</div>
            </div>
            <div style="flex: 1; background-color: #111827; padding: 10px; border-radius: 8px; border-top: 3px solid #FF4C4C; text-align: center;">
                <div style="color: #FF4C4C; font-weight: bold; font-size: 9px; text-transform: uppercase;">Pendientes</div>
                <div style="font-size: 20px; color: white; font-weight: bold;">{n_pendientes}</div>
            </div>
            <div style="flex: 1; background-color: #111827; padding: 10px; border-radius: 8px; border-top: 3px solid #28a745; text-align: center;">
                <div style="color: #28a745; font-weight: bold; font-size: 9px; text-transform: uppercase;">Cerradas</div>
                <div style="font-size: 20px; color: white; font-weight: bold;">{n_cerradas}</div>
            </div>
            <div style="flex: 1; background-color: #111827; padding: 10px; border-radius: 8px; border-top: 3px solid #9ca3af; text-align: center;">
                <div style="color: #9ca3af; font-weight: bold; font-size: 9px; text-transform: uppercase;">Total</div>
                <div style="font-size: 20px; color: white; font-weight: bold;">{n_total}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    for idx, row in pd.concat([activas, cerradas_hoy]).iterrows():
        status = str(row['ESTATUS']).upper()
        color = "#FFD700" if "PROCESO" in status else ("#FF4C4C" if "PENDIENTE" in status else "#28a745")
        render_card(row, color, unique_key=f"card_hoy_{idx}", con_mapa=True)
        
    st.markdown("---")
    st.subheader("📅 Histórico")
    if not historico.empty:
        opciones_raw = sorted(historico['FECHA_HORA_FIN'].dt.strftime('%Y-%m').unique(), reverse=True)
        MESES_ES = {'01': 'Enero', '02': 'Febrero', '03': 'Marzo', '04': 'Abril', '05': 'Mayo', '06': 'Junio', '07': 'Julio', '08': 'Agosto', '09': 'Septiembre', '10': 'Octubre', '11': 'Noviembre', '12': 'Diciembre'}
        mapa_opciones = {f"{MESES_ES[o.split('-')[1]]} {o.split('-')[0]}": o for o in opciones_raw}
        seleccion = st.selectbox("Seleccionar mes:", options=list(mapa_opciones.keys()))
        
        for idx, row in historico[historico['FECHA_HORA_FIN'].dt.strftime('%Y-%m') == mapa_opciones[seleccion]].iterrows():
            render_card(row, "#6c757d", unique_key=f"card_hist_{idx}", con_mapa=False)
            
except Exception as e:
    st.error(f"Error de conexión con la base de datos: {e}. Reintentando automáticamente...")
