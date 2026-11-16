
from pathlib import Path
import html
import sqlite3

import altair as alt
import folium
import geopandas as gpd
import pandas as pd
import pyogrio
import streamlit as st
from folium.plugins import Fullscreen
from shapely.geometry import Point
from streamlit_folium import st_folium

st.set_page_config(
    page_title="Visor de regímenes nivales por microcuenca",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="expanded"
)

DATOS = Path(__file__).resolve().parent / "datos"
BD = DATOS / "BD_CARACTERIZACION_NIEVE.sqlite"
MICRO = DATOS / "MICROCUENCAS_VISOR.gpkg"
NIEVE = DATOS / "TB_NIEVE_INTERSECCION.gpkg"

CAPA_MICRO = "MICROCUENCAS_VISOR"
CAPA_NIEVE = "TB_NIEVE_INTERSECCION"

for ruta in (BD, MICRO, NIEVE):
    if not ruta.exists():
        st.error(f"Archivo no encontrado: {ruta}")
        st.stop()

UH_NOMBRES = {
    1: "Huaura", 2: "Mantaro", 3: "Huaral",
    4: "Chillón", 5: "Rímac", 6: "Lurín",
    7: "Mala", 8: "Cañete", 9: "Alto Huallaga",
    10: "Perené", 11: "Pachitea"
}

CLASES = {
    1: "Tundra",
    2: "Boreal Forest",
    3: "Maritime",
    4: "Ephemeral",
    5: "Prairie",
    6: "Montane Forest",
    7: "Ice",
    8: "Ocean"
}

COLORES = {
    1: "#A5C9E7",
    2: "#558B75",
    3: "#367CB5",
    4: "#E9BC6A",
    5: "#C9A46C",
    6: "#738F65",
    7: "#B6E8F4",
    8: "#536D88"
}

TILES = {
    "Relieve topográfico (Esri)": (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        "Tiles © Esri"
    ),
    "CartoDB claro": ("CartoDB positron", "CartoDB"),
    "OpenStreetMap": ("OpenStreetMap", "OpenStreetMap"),
    "Sin mapa base": (None, None)
}

def crear_mapa(base):
    tiles, attr = TILES[base]
    mapa = folium.Map(
        location=[-11.3, -76.5],
        zoom_start=8,
        tiles=tiles,
        attr=attr,
        control_scale=True,
        prefer_canvas=True
    )
    Fullscreen(position="topright").add_to(mapa)
    return mapa

@st.cache_data(show_spinner="Cargando microcuencas...")
def inventario(path, mtime):
    g = pyogrio.read_dataframe(
        path, layer=CAPA_MICRO,
        columns=["ID_MICRO", "ID_UH"],
        read_geometry=False
    )
    g["ID_MICRO"] = g["ID_MICRO"].astype("int64")
    g["ID_UH"] = g["ID_UH"].astype("int64")
    return g

@st.cache_data(show_spinner=False, max_entries=12)
def microcuencas_uh(path, mtime, id_uh):
    g = pyogrio.read_dataframe(
        path,
        layer=CAPA_MICRO,
        where=f"ID_UH = {int(id_uh)}"
    )
    return g[["ID_MICRO", "geometry"]].to_crs(4326)

@st.cache_data(show_spinner=False, max_entries=100)
def microcuenca_detalle(path, mtime, mid):
    return pyogrio.read_dataframe(
        path,
        layer=CAPA_MICRO,
        where=f"ID_MICRO = {int(mid)}"
    )

@st.cache_data(show_spinner=False, max_entries=100)
def nieve_micro(path, mtime, mid):
    return pyogrio.read_dataframe(
        path,
        layer=CAPA_NIEVE,
        where=f"ID_MICRO = {int(mid)}"
    )

@st.cache_data(show_spinner=False, max_entries=100)
def resumen_micro(path, mtime, mid):
    with sqlite3.connect(path) as con:
        return pd.read_sql_query(
            """
            SELECT CLASE, DENOMINACION, DESCRIPCION,
                   AREA_NIEVE_KM2, PORCENTAJE
            FROM TB_NIEVE
            WHERE ID_MICRO = ?
            ORDER BY AREA_NIEVE_KM2 DESC
            """,
            con,
            params=(int(mid),)
        )

@st.cache_data(show_spinner=False, max_entries=100)
def control_micro(path, mtime, mid):
    with sqlite3.connect(path) as con:
        return pd.read_sql_query(
            "SELECT * FROM TB_CONTROL_NIEVE WHERE ID_MICRO = ?",
            con,
            params=(int(mid),)
        )

st.markdown("""
<style>
.block-container {
    padding-top: 1.25rem;
    padding-bottom: 2rem;
    max-width: 1550px;
}
[data-testid="stMetric"] {
    border: 1px solid rgba(140,150,150,.22);
    border-radius: 12px;
    padding: 12px 15px;
}
.legend-row {
    display:flex;
    align-items:center;
    gap:8px;
    margin:7px 0;
    font-size:.9rem;
}
.legend-swatch {
    width:14px;
    height:14px;
    border:1px solid #777;
    border-radius:2px;
    flex:none;
}
</style>
""", unsafe_allow_html=True)

st.title("Visor de regímenes nivales por microcuenca")
st.caption(
    "Clasificación NSIDC-0768 · 11 unidades hidrográficas · "
    "Áreas y porcentajes por microcuenca"
)

st.info(
    "Las clases representan regímenes nivales climatológicos, "
    "no superficies de nieve observadas en una fecha determinada. "
    "La clase Ice no sustituye un inventario glaciar y Ocean "
    "no representa cobertura nival."
)

try:
    micros = inventario(str(MICRO), MICRO.stat().st_mtime)
except Exception as exc:
    st.exception(exc)
    st.stop()

uhs = sorted(micros["ID_UH"].unique().tolist())

if "nieve_uh_actual" not in st.session_state:
    st.session_state.nieve_uh_actual = uhs[0]

if "nieve_id_actual" not in st.session_state:
    st.session_state.nieve_id_actual = None

if "nieve_vista_detalle" not in st.session_state:
    st.session_state.nieve_vista_detalle = False

with st.sidebar:
    st.header("Consulta")

    uh_id = st.selectbox(
        "Unidad hidrográfica",
        uhs,
        format_func=lambda v: UH_NOMBRES.get(v, str(v)),
        key="nieve_uh_actual"
    )

    uh = UH_NOMBRES.get(uh_id, str(uh_id))

    ids = sorted(
        micros.loc[
            micros.ID_UH == uh_id, "ID_MICRO"
        ].unique().tolist()
    )

    st.caption(f"{len(ids):,} microcuencas disponibles")

    buscar = st.text_input(
        "Buscar ID_MICRO",
        placeholder="Ej. 200005"
    )

    if st.button(
        "Buscar microcuenca",
        use_container_width=True
    ):
        try:
            mid_buscado = int(buscar.strip())
            if mid_buscado in ids:
                st.session_state.nieve_id_actual = mid_buscado
                st.session_state.nieve_vista_detalle = True
                st.rerun()
            else:
                st.warning(
                    "El ID no pertenece a la unidad "
                    "hidrográfica seleccionada."
                )
        except ValueError:
            st.warning("Introduce un identificador numérico.")

    if st.button(
        "Mostrar todas las microcuencas",
        use_container_width=True
    ):
        st.session_state.nieve_vista_detalle = False
        st.session_state.nieve_id_actual = None
        st.rerun()

    st.divider()
    st.subheader("Cartografía")

    base = st.selectbox(
        "Mapa base",
        list(TILES),
        index=0
    )

    st.caption(
        "Los mapas base requieren internet. "
        "La caracterización se consulta en archivos locales."
    )

    st.divider()
    st.caption(
        "Selecciona una microcuenca en el mapa "
        "o utiliza el buscador."
    )

if st.session_state.nieve_id_actual not in ids:
    st.session_state.nieve_id_actual = None
    st.session_state.nieve_vista_detalle = False

# ============================================================
# MAPA GENERAL
# ============================================================

if not st.session_state.nieve_vista_detalle:

    st.subheader(f"Microcuencas de {uh}")
    st.caption(
        "Haz clic dentro de una microcuenca "
        "para abrir su ficha de regímenes nivales."
    )

    try:
        general = microcuencas_uh(
            str(MICRO), MICRO.stat().st_mtime, uh_id
        )
    except Exception as exc:
        st.exception(exc)
        st.stop()

    mapa = crear_mapa(base)

    folium.GeoJson(
        general.to_json(),
        name="Microcuencas",
        style_function=lambda f: {
            "fillColor": "#6ea9a0",
            "fillOpacity": 0.25,
            "color": "#4d817c",
            "weight": 0.65
        },
        highlight_function=lambda f: {
            "fillColor": "#e6b85c",
            "fillOpacity": 0.60,
            "color": "#b67522",
            "weight": 2
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["ID_MICRO"],
            aliases=["ID_MICRO:"],
            sticky=True
        )
    ).add_to(mapa)

    minx, miny, maxx, maxy = general.total_bounds
    mapa.fit_bounds([[miny, minx], [maxy, maxx]])

    evento = st_folium(
        mapa,
        height=660,
        use_container_width=True,
        key=f"nieve_general_{uh_id}_{base}",
        returned_objects=["last_object_clicked"]
    )

    click = (
        evento.get("last_object_clicked")
        if evento else None
    )

    if click and "lat" in click and "lng" in click:
        punto = Point(click["lng"], click["lat"])
        posibles = general[
            general.geometry.intersects(punto)
        ]

        if not posibles.empty:
            st.session_state.nieve_id_actual = int(
                posibles.iloc[0]["ID_MICRO"]
            )
            st.session_state.nieve_vista_detalle = True
            st.rerun()

    st.caption(
        "Límites simplificados exclusivamente para visualización. "
        "Las geometrías originales se conservan."
    )

# ============================================================
# FICHA INDIVIDUAL
# ============================================================

else:

    mid = int(st.session_state.nieve_id_actual)

    try:
        micro = microcuenca_detalle(
            str(MICRO), MICRO.stat().st_mtime, mid
        )
        geom = nieve_micro(
            str(NIEVE), NIEVE.stat().st_mtime, mid
        )
        resumen = resumen_micro(
            str(BD), BD.stat().st_mtime, mid
        )
        control = control_micro(
            str(BD), BD.stat().st_mtime, mid
        )
    except Exception as exc:
        st.exception(exc)
        st.stop()

    if micro.empty:
        st.warning("No se encontró la microcuenca.")
        st.stop()

    if control.empty:
        st.warning(
            "No se encontró el control de superficies."
        )
        st.stop()

    area = float(
        control.iloc[0]["AREA_MICRO_KM2"]
    )

    cobertura = float(
        resumen["PORCENTAJE"].sum()
    ) if not resumen.empty else 0.0

    st.subheader(f"Microcuenca {mid} · {uh}")

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Área de microcuenca",
        f"{area:,.3f} km²"
    )
    c2.metric(
        "Regímenes nivales",
        f"{resumen['CLASE'].nunique():,}"
    )
    c3.metric(
        "Cobertura clasificada",
        f"{cobertura:.2f} %"
    )

    if cobertura < 99.99:
        st.info(
            "La clasificación presenta una pequeña diferencia "
            "de superficie respecto de la microcuenca. "
            "No se asigna una clase a la diferencia."
        )
    elif cobertura > 100.01:
        st.warning(
            "La suma de porcentajes supera el 100 %. "
            "Los valores originales no se normalizan."
        )

    resumen = resumen.copy()

    if not resumen.empty:
        resumen["COLOR"] = (
            resumen["CLASE"].map(COLORES)
        )
        resumen["CATEGORIA"] = (
            resumen["CLASE"].astype(str)
            + " · "
            + resumen["DENOMINACION"]
        )
        resumen["PORC_TEXTO"] = (
            resumen["PORCENTAJE"].map(
                lambda x: f"{x:.2f} %"
            )
        )

    mapa_col, datos_col = st.columns(
        [1.20, 1.15],
        gap="medium"
    )

    # --------------------------------------------------------
    # MAPA TEMÁTICO
    # --------------------------------------------------------

    with mapa_col:

        st.markdown("#### Mapa temático de regímenes nivales")

        mapa = crear_mapa(base)

        if not geom.empty:
            geom = geom.to_crs(4326)

            for _, r in geom.iterrows():

                clase = int(r["CLASE"])
                color = COLORES.get(clase, "#888888")

                denominacion = html.escape(
                    str(r["DENOMINACION"])
                )
                descripcion = html.escape(
                    str(r["DESCRIPCION"])
                )

                tooltip = (
                    f"<b>Clase:</b> {clase}<br>"
                    f"<b>Régimen:</b> {denominacion}<br>"
                    f"<b>Descripción:</b> {descripcion}<br>"
                    f"<b>Área del fragmento:</b> "
                    f"{float(r['AREA_KM2']):.4f} km²<br>"
                    f"<b>Porcentaje:</b> "
                    f"{float(r['PCT_MICRO']):.2f}%"
                )

                folium.GeoJson(
                    r.geometry.__geo_interface__,
                    style_function=lambda f, c=color: {
                        "fillColor": c,
                        "fillOpacity": 0.78,
                        "color": "#4a5358",
                        "weight": 0.7
                    },
                    highlight_function=lambda f: {
                        "weight": 2.2,
                        "color": "#172c43",
                        "fillOpacity": 0.92
                    },
                    tooltip=folium.Tooltip(
                        tooltip,
                        sticky=True
                    ),
                    popup=folium.Popup(
                        tooltip,
                        max_width=470
                    )
                ).add_to(mapa)

        limite = micro.to_crs(4326)

        for g in limite.geometry:
            folium.GeoJson(
                g.__geo_interface__,
                name="Límite de microcuenca",
                style_function=lambda f: {
                    "fillOpacity": 0,
                    "color": "#202f39",
                    "weight": 3
                },
                interactive=False
            ).add_to(mapa)

        minx, miny, maxx, maxy = limite.total_bounds
        dx = max(maxx - minx, 0.002)
        dy = max(maxy - miny, 0.002)

        mapa.fit_bounds([
            [miny - dy * 0.14, minx - dx * 0.14],
            [maxy + dy * 0.14, maxx + dx * 0.14]
        ])

        st_folium(
            mapa,
            height=625,
            use_container_width=True,
            key=f"nieve_detalle_{mid}_{base}",
            returned_objects=[]
        )

        st.caption(
            "Pasa el cursor sobre los polígonos "
            "para consultar la clase, el área y el porcentaje."
        )

    # --------------------------------------------------------
    # GRÁFICO Y LEYENDA
    # --------------------------------------------------------

    with datos_col:

        st.markdown(
            "#### Distribución de regímenes nivales"
        )

        if resumen.empty:
            st.info(
                "No hay registros de clasificación."
            )
        else:

            orden = resumen["CATEGORIA"].tolist()

            limite_x = max(
                113,
                float(resumen["PORCENTAJE"].max()) * 1.2 + 3
            )

            barras = alt.Chart(resumen).mark_bar(
                size=24,
                cornerRadiusEnd=3
            ).encode(
                x=alt.X(
                    "PORCENTAJE:Q",
                    title="Porcentaje de microcuenca (%)",
                    scale=alt.Scale(
                        domain=[0, limite_x]
                    )
                ),
                y=alt.Y(
                    "CATEGORIA:N",
                    sort=orden,
                    title=None,
                    axis=alt.Axis(labelLimit=240)
                ),
                color=alt.Color(
                    "CATEGORIA:N",
                    scale=alt.Scale(
                        domain=orden,
                        range=resumen["COLOR"].tolist()
                    ),
                    legend=None
                ),
                tooltip=[
                    alt.Tooltip(
                        "DENOMINACION:N",
                        title="Régimen"
                    ),
                    alt.Tooltip(
                        "DESCRIPCION:N",
                        title="Descripción"
                    ),
                    alt.Tooltip(
                        "AREA_NIEVE_KM2:Q",
                        format=".4f",
                        title="Área (km²)"
                    ),
                    alt.Tooltip(
                        "PORCENTAJE:Q",
                        format=".2f",
                        title="Porcentaje (%)"
                    )
                ]
            )

            etiquetas = alt.Chart(resumen).mark_text(
                align="left",
                baseline="middle",
                dx=7,
                fontSize=12,
                fontWeight="bold"
            ).encode(
                x=alt.X(
                    "PORCENTAJE:Q",
                    scale=alt.Scale(
                        domain=[0, limite_x]
                    )
                ),
                y=alt.Y(
                    "CATEGORIA:N",
                    sort=orden
                ),
                text="PORC_TEXTO:N",
                color=alt.value("#9AA7B4")
            )

            grafico = (
                barras + etiquetas
            ).properties(
                height=max(280, len(resumen) * 52)
            ).configure_view(
                strokeWidth=0
            )

            st.altair_chart(
                grafico,
                use_container_width=True
            )

            with st.expander(
                "Leyenda y distribución",
                expanded=True
            ):
                for _, r in resumen.iterrows():
                    nombre = html.escape(
                        str(r["CATEGORIA"])
                    )
                    descripcion = html.escape(
                        str(r["DESCRIPCION"])
                    )
                    color = r["COLOR"]

                    st.markdown(
                        '<div class="legend-row">'
                        f'<span class="legend-swatch" '
                        f'style="background:{color}"></span>'
                        f'<span><b>{nombre}</b> — '
                        f'{descripcion} — '
                        f'<b>{r["PORCENTAJE"]:.2f}%</b>'
                        '</span></div>',
                        unsafe_allow_html=True
                    )

    # --------------------------------------------------------
    # TABLA DE RESULTADOS
    # --------------------------------------------------------

    st.markdown(
        "##### Detalle de clasificación nival"
    )

    tabla = resumen[
        [
            "CLASE",
            "DENOMINACION",
            "DESCRIPCION",
            "AREA_NIEVE_KM2",
            "PORCENTAJE"
        ]
    ].copy()

    tabla.columns = [
        "Código",
        "Régimen nival",
        "Descripción",
        "Área (km²)",
        "% microcuenca"
    ]

    st.dataframe(
        tabla,
        hide_index=True,
        use_container_width=True
    )

    st.download_button(
        "Descargar distribución CSV",
        data=tabla.to_csv(
            index=False
        ).encode("utf-8-sig"),
        file_name=f"nieve_micro_{mid}.csv",
        mime="text/csv",
        use_container_width=True
    )

    st.caption(
        "Fuente: NSIDC-0768, Global Seasonal-Snow "
        "Classification v1. Las áreas proceden de "
        "la intersección espacial por microcuenca."
    )

    with st.expander(
        "Información técnica y control de calidad",
        expanded=False
    ):

        st.write(
            "La clasificación describe regímenes "
            "nivales climatológicos y no cobertura "
            "nival instantánea."
        )

        st.write(
            "Los porcentajes se conservan sin "
            "normalización ni redistribución."
        )

        st.dataframe(
            control,
            hide_index=True,
            use_container_width=True
        )

        st.write(
            f"Fragmentos espaciales visualizados: "
            f"{len(geom):,}"
        )



# FUENTES_NIEVE_NSIDC_0768
st.markdown("---")

with st.expander(
    "Fuente de datos y referencias bibliográficas",
    expanded=False
):
    st.markdown("""
**Producto:** Global Seasonal-Snow Classification,
Version 1 (NSIDC-0768).

**Resolución espacial original:** 10 segundos de arco
(aproximadamente 300 m).

**Período climático de referencia:** 1981–2019 (39 años).

**Fuente de datos:**

Liston, G. E., & Sturm, M. (2021).
*Global Seasonal-Snow Classification* (Version 1)
[Conjunto de datos].
NASA National Snow and Ice Data Center
Distributed Active Archive Center.

https://doi.org/10.5067/99FTCYYYLAQ0

**Referencia científica:**

Sturm, M., & Liston, G. E. (2021).
*Revisiting the global seasonal snow classification:
An updated dataset for Earth system applications*.
*Journal of Hydrometeorology, 22*(11), 2917–2938.

https://doi.org/10.1175/JHM-D-21-0070.1

**Nota metodológica:** La clasificación representa
regímenes nivales climatológicos, no la presencia de nieve
observada en una fecha específica. La información original
fue procesada y vectorizada para su caracterización
por microcuenca.

**Catálogo oficial:**
https://nsidc.org/data/nsidc-0768/versions/1
""")
