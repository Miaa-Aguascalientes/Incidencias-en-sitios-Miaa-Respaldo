import streamlit as st
import pandas as pd
import geopandas as gpd
from sqlalchemy import create_engine
from datetime import datetime
import pytz
from streamlit_folium import st_folium
import folium
from folium.plugins import Fullscreen
from folium.features import DivIcon
from shapely import wkt
import re
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from sqlalchemy.exc import OperationalError

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
    .logo-container { display: flex; justify-content: center; margin-bottom: 0px; }
    .header-wrapper { display: flex; justify-content: center; align-items: center; gap: 0px; margin-bottom: 5px; }
    .title-text { color: white; font-size: 20px !important; margin: 0 !important; }
    .card { background: #111827; padding: 5px; border-radius: 12px; border-left: 6px solid; margin-bottom: 5px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3); }
    .label { font-size: 10px; color: #9ca3af; text-transform: uppercase; }
    .value { font-size: 14px; color: #f3f4f6; font-weight: 500; }
    </style>
""", unsafe_allow_html=True)

# Conexiones
@st.cache_resource
def get_engine():
    db = st.secrets["mysql_scada"]
    return create_engine(f"mysql+pymysql://{db['user']}:{db['password']}@{db['host']}/{db['database']}", 
                         pool_pre_ping=True, pool_recycle=3600)

@st.cache_resource
def get_engine_telemetria():
    db = st.secrets["mysql_telemetria"]
    return create_engine(f"mysql+pymysql://{db['user']}:{db['password']}@{db['host']}/{db['database']}", 
                         pool_pre_ping=True, pool_recycle=3600)

@retry(
    stop=stop_after_attempt(3), 
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError),
    reraise=True
)
@st.cache_data(ttl=60)
def get_data():
    return pd.read_sql("SELECT * FROM vw_incidencias_en_pozos ORDER BY FECHA_HORA_INICIO DESC", get_engine())

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

@st.fragment
def dibujar_mapa(gdf, color, num_pozo, inicio):
    # 1. Creamos el mapa base. 
    # Usamos 'tiles=None' para que el mapa inicie vacío y nosotros controlemos la capa base.
    m = folium.Map(
        location=[gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()], 
        zoom_start=13, 
        tiles=None,
        attribution_control=False
    )
    
    # 2. Agregamos la capa de "Calles" (OpenStreetMap) primero
    folium.TileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", 
        name="Calles", 
        attr="&copy; OpenStreetMap contributors"
    ).add_to(m)
    
    # 3. Agregamos la capa de "Satélite"
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}", 
        name="Satélite", 
        attr="Esri"
    ).add_to(m)

    # 4. Agregamos "CartoDB dark_matter" al final, como pediste
    folium.TileLayer(
        "CartoDB dark_matter", 
        name="CartoDB dark_matter", 
        attr="&copy; CartoDB"
    ).add_to(m)


    # 3. Capa de incidencia
    folium.GeoJson(
        gdf, 
        style_function=lambda x: {'fillColor': color, 'color': color, 'weight': 2, 'fillOpacity': 0.4}
    ).add_to(m)
    
    # 4. Etiquetas
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
        
    st_folium(m, height=300, use_container_width=True, key=f"map_{num_pozo}")

def format_supervisor(text):
    wa_icon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="white" style="vertical-align: middle; margin-right: 4px;"><path d="M12.01 2c-5.51 0-9.99 4.48-9.99 9.99 0 1.76.46 3.48 1.33 5l-1.33 4.88 5-1.31c1.47.8 3.16 1.22 4.87 1.22 5.51 0 9.99-4.48 9.99-9.99S17.52 2 12.01 2zm0 18c-1.46 0-2.88-.41-4.11-1.18l-.29-.18-3.05.8.81-2.97-.18-.3C3.65 14.88 3.23 13.43 3.23 11.99 3.23 7.02 7.04 3.2 12.01 3.2s8.78 3.82 8.78 8.79-3.95 8.79-8.78 8.79zM16.48 15.5c-.27-.13-1.61-.79-1.86-.88s-.43-.13-.61.13c-.18.26-.69.88-.85 1.06-.16.18-.32.2-.59.07s-1.14-.42-2.17-1.34c-.8-.71-1.34-1.59-1.5-1.86s-.01-.43.11-.57c.12-.13.27-.34.4-.51.13-.17.17-.3.26-.51.09-.2.04-.37-.02-.51s-.61-1.48-.84-2.03c-.22-.53-.45-.46-.61-.46-.16 0-.34-.01-.51-.01s-.44.06-.67.31c-.23.25-.88.86-.88 2.09s.6 2.42.69 2.55c.09.13 1.73 2.64 4.19 3.7c.59.25 1.05.4 1.41.51.59.19 1.13.16 1.56.1.48-.07 1.51-.62 1.72-1.21.21-.59.21-1.1.15-1.21-.06-.11-.23-.17-.5-.3z"/></svg>'
    tel_icon = '<svg width="16" height="16" viewBox="0 0 24 24" fill="white" style="vertical-align: middle; margin-right: 4px;"><path d="M20.01 15.38c-1.23 0-2.42-.19-3.53-.55-.35-.11-.74-.03-1.01.24l-1.57 1.97c-2.83-1.35-5.48-3.9-6.89-6.83l1.95-1.66c.27-.28.35-.67.24-1.02-.36-1.11-.55-2.3-.55-3.53 0-.55-.45-1-1-1H4c-.55 0-1 .45-1 1 0 9.39 7.61 17 17 17 .55 0 1-.45 1-1v-3.49c0-.55-.45-1-1-1z"/></svg>'
    
    match = re.search(r'(\d{3})\D?(\d{3})\D?(\d{2})\D?(\d{2})', text)
    if match:
        num = f"{match.group(1)}{match.group(2)}{match.group(3)}{match.group(4)}"
        tel_full = f"52{num}"
        return text.replace(match.group(0), f"<strong>{match.group(0)}</strong>") + f"""
            <div style='margin-top: 8px; display: flex; gap: 10px;'>
                <a href='tel:+52{num}' style='text-decoration: none; background: #10b981; color: white; padding: 6px 40px; border-radius: 5px; font-size: 12px; display: inline-flex; align-items: center;'>{tel_icon} Llamar</a>
                <a href='https://wa.me/{tel_full}' target='_blank' style='text-decoration: none; background: #25d366; color: white; padding: 6px 28px; border-radius: 5px; font-size: 12px; display: inline-flex; align-items: center;'>{wa_icon} WhatsApp</a>
            </div>"""
    return text

def render_card(row, color):
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
        gdf = get_geometries(row.get('NUM_POZO'))
        if gdf is not None and not gdf.empty:
            st.markdown(f"<div style='font-size: 12px; color: #9ca3af;'><strong>Colonias:</strong> {', '.join(gdf['Col_atl'].unique())}</div>", unsafe_allow_html=True)
            dibujar_mapa(gdf, color, row.get('NUM_POZO'), inicio)
            sectores = ', '.join(gdf['Sector'].dropna().unique())
            distritos = ', '.join(gdf['Distrito'].dropna().unique())
            raw_supervisores = gdf['Supervisor'].dropna().unique()
            supervisores_list = []
            for item in raw_supervisores:
                items = [s.strip() for s in item.split(',') if s.strip()]
                supervisores_list.extend([format_supervisor(s) for s in items])
            supervisores_html = "".join([f"<div style='margin-bottom: 15px; border-bottom: 1px solid #1f2937; padding-bottom: 10px;'>• {s}</div>" for s in supervisores_list])
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
                        <div style='margin-top: 0px;'>{supervisores_html if supervisores_list else 'N/A'}</div>
                    </div>   
                </div>
            """, unsafe_allow_html=True)

# LÓGICA PRINCIPAL
st.markdown("""<div class="logo-container"><img src="https://raw.githubusercontent.com/Miaa-Aguascalientes/Logos/38504978c8f77a4dac38ad476f74dbdee6af2cad/LogoMIAA.svg" width="200"></div>""", unsafe_allow_html=True)
st.markdown("""<div class="header-wrapper"><img src="https://github.com/Miaa-Aguascalientes/Logos/blob/main/procesodelpecado.gif?raw=true" width="60"><h1 class="title-text">Registro de Incidencias</h1></div>""", unsafe_allow_html=True)

try:
    df = get_data()
    df['FECHA_HORA_INICIO'] = pd.to_datetime(df['FECHA_HORA_INICIO'])
    df['FECHA_HORA_FIN'] = pd.to_datetime(df['FECHA_HORA_FIN'])
    hoy = get_now_mexico().date()
    activas = df[~df['ESTATUS'].str.contains('CERRADA', case=False, na=False)]
    cerradas_hoy = df[(df['ESTATUS'].str.contains('CERRADA', case=False, na=False)) & (df['FECHA_HORA_FIN'].dt.date == hoy)]
    historico = df[(df['ESTATUS'].str.contains('CERRADA', case=False, na=False)) & (df['FECHA_HORA_FIN'].dt.date != hoy)]
    
    n_procesos = len(activas[activas['ESTATUS'].str.contains('PROCESO', case=False, na=False)])
    n_pendientes = len(activas[activas['ESTATUS'].str.contains('PENDIENTE', case=False, na=False)])
    n_cerradas = len(cerradas_hoy)
    
    st.markdown(f"""
        <div style="display: flex; justify-content: space-between; gap: 10px; margin-bottom: 20px;">
            <div style="flex: 1; background-color: #FFD7001A; padding: 10px; border-radius: 8px; border-top: 3px solid #FFD700; text-align: center;">
                <div style="color: #FFD700; font-weight: bold; font-size: 9px; text-transform: uppercase;">En Proceso</div>
                <div style="font-size: 20px; color: white; font-weight: bold;">{n_procesos}</div>
            </div>
            <div style="flex: 1; background-color: #FF4C4C1A; padding: 10px; border-radius: 8px; border-top: 3px solid #FF4C4C; text-align: center;">
                <div style="color: #FF4C4C; font-weight: bold; font-size: 9px; text-transform: uppercase;">Pendiente</div>
                <div style="font-size: 20px; color: white; font-weight: bold;">{n_pendientes}</div>
            </div>
            <div style="flex: 1; background-color: #28a7451A; padding: 10px; border-radius: 8px; border-top: 3px solid #28a745; text-align: center;">
                <div style="color: #28a745; font-weight: bold; font-size: 9px; text-transform: uppercase;">Cerrada</div>
                <div style="font-size: 20px; color: white; font-weight: bold;">{n_cerradas}</div>
            </div>
        </div>
    """, unsafe_allow_html=True)
    
    for _, row in pd.concat([activas, cerradas_hoy]).iterrows():
        status = str(row['ESTATUS']).upper()
        color = "#FFD700" if "PROCESO" in status else ("#FF4C4C" if "PENDIENTE" in status else "#28a745")
        render_card(row, color)
        
    st.markdown("---")
    st.subheader("📅 Histórico")
    if not historico.empty:
        opciones_raw = sorted(historico['FECHA_HORA_INICIO'].dt.strftime('%Y-%m').unique(), reverse=True)
        MESES_ES = {'01': 'Enero', '02': 'Febrero', '03': 'Marzo', '04': 'Abril', '05': 'Mayo', '06': 'Junio', '07': 'Julio', '08': 'Agosto', '09': 'Septiembre', '10': 'Octubre', '11': 'Noviembre', '12': 'Diciembre'}
        mapa_opciones = {f"{MESES_ES[o.split('-')[1]]} {o.split('-')[0]}": o for o in opciones_raw}
        seleccion = st.selectbox("Seleccionar mes:", options=list(mapa_opciones.keys()))
        for _, row in historico[historico['FECHA_HORA_INICIO'].dt.strftime('%Y-%m') == mapa_opciones[seleccion]].iterrows():
            render_card(row, "#6c757d")
except Exception as e:
    st.error("Error al cargar la aplicación. Reintentando conexión con la base de datos...")
