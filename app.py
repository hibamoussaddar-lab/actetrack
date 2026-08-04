"""
ActeTrack — Historique et audit de l'État civil
Plateforme interactive d'analyse et de détection d'anomalies.
"""

import io
import time
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from sqlalchemy import create_engine, text
from urllib.parse import quote_plus
from datetime import datetime, timedelta
from fpdf import FPDF

# ==============================================================================
# DIAGNOSTIC PERF (temporaire) — mesure où passe le temps à chaque chargement de page
# ==============================================================================
_RENDER_START = time.perf_counter()
_QUERY_LOG = []  # rempli uniquement par run_query() quand une requête part vraiment vers MySQL (pas de cache)

# ==============================================================================
# CONFIGURATION DE LA PAGE
# ==============================================================================
st.set_page_config(
    page_title="ActeTrack",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ==============================================================================
# PALETTE DE COULEURS
# ==============================================================================
COLORS = {
    "bg": "#0B0E14",
    "surface": "#171B24",
    "surface2": "#1D2230",
    "border": "#2A2F3B",
    "text": "#F5F7FA",
    "text_muted": "#8B93A1",
    "blue": "#4FA8FF",
    "green": "#00E0A4",
    "coral": "#FF6B4A",
    "purple": "#C86BFF",
    "yellow": "#FFC24F",
    "pink": "#FF6B9D",
}
SEQ = [COLORS["blue"], COLORS["green"], COLORS["coral"], COLORS["purple"], COLORS["yellow"], COLORS["pink"]]

PLOTLY_TEMPLATE = go.layout.Template()
PLOTLY_TEMPLATE.layout = go.Layout(
    paper_bgcolor=COLORS["surface"],
    plot_bgcolor=COLORS["surface"],
    font=dict(color=COLORS["text"], family="sans-serif", size=12),
    colorway=SEQ,
    xaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"]),
    yaxis=dict(gridcolor=COLORS["border"], zerolinecolor=COLORS["border"]),
    margin=dict(l=10, r=10, t=40, b=10),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)

APP_NAME = "ActeTrack"
APP_TAGLINE = "Historique et audit de l'État civil"

# Logo — monogramme audit/vérification en SVG (aucune image externe requise)
LOGO_ICON = """
<svg width="58%" height="58%" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="10" cy="10" r="6.5" stroke="white" stroke-width="2"/>
  <path d="M7 10.3l2.1 2.1L13.5 8" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
  <line x1="14.8" y1="14.8" x2="21" y2="21" stroke="white" stroke-width="2.2" stroke-linecap="round"/>
</svg>
"""

NAV_ITEMS = [
    ("synthese", "🧭", "Synthèse"),
    ("apercu", "📊", "Vue d'ensemble"),
    ("temporel", "🕒", "Analyse temporelle"),
    ("comparer", "⚖️", "Comparer périodes"),
    ("champ", "🔎", "Par champ"),
    ("motifs", "🧩", "Motifs de correction"),
    ("acte", "📄", "Par acte"),
    ("delais", "🕓", "Délais de résolution"),
    ("agent", "👤", "Agent"),
    ("equipe", "👥", "Équipe"),
    ("qualite", "✅", "Qualité des données"),
    ("anomalies", "⚠️", "Anomalies"),
    ("export", "📤", "Export / Rapports"),
]

# ==============================================================================
# ÉTAT DE SESSION
# ==============================================================================
st.session_state.setdefault("entered", False)
st.session_state.setdefault("nav", "synthese")
st.session_state.setdefault("last_refresh", datetime.now())
st.session_state.setdefault("known_signature", None)
st.session_state.setdefault("gfilter_team", "Toutes les équipes")
st.session_state.setdefault("search_results", None)
st.session_state.setdefault("agent_prefill", "")
st.session_state.setdefault("acte_prefill", "")

# ==============================================================================
# CSS
# ==============================================================================
st.markdown(f"""
<style>
    #MainMenu, footer, header {{visibility: hidden;}}
    .block-container {{padding-top: 1.5rem; max-width: 1440px;}}
    section[data-testid="stSidebar"] {{ background: {COLORS['surface']}; border-right: 1px solid {COLORS['border']}; }}
    section[data-testid="stSidebar"] .block-container {{ padding-top: 1.2rem; }}

    @keyframes ct-pulse {{
        0% {{ box-shadow: 0 0 0 0 rgba(0,224,164,0.5); }}
        70% {{ box-shadow: 0 0 0 6px rgba(0,224,164,0); }}
        100% {{ box-shadow: 0 0 0 0 rgba(0,224,164,0); }}
    }}
    .ct-title {{ font-size: 24px; font-weight: 600; color: {COLORS['text']}; margin: 0; letter-spacing: -0.3px; }}
    .ct-subtitle {{ font-size: 13px; color: {COLORS['text_muted']}; margin: 3px 0 0; }}
    .ct-live-badge {{
        display: flex; align-items: center; gap: 8px;
        background: linear-gradient(180deg, {COLORS['surface2']}, {COLORS['surface']});
        border: 1px solid {COLORS['border']};
        border-radius: 8px; padding: 7px 14px; font-size: 12px; color: {COLORS['green']}; font-weight: 500;
    }}
    .ct-dot {{ width: 8px; height: 8px; border-radius: 50%; background: {COLORS['green']}; animation: ct-pulse 2s infinite; }}

    .ct-kpi {{
        background: {COLORS['surface']}; border: 1px solid {COLORS['border']};
        border-radius: 12px; padding: 14px 16px; position: relative; overflow: hidden;
    }}
    .ct-kpi-label {{ color: {COLORS['text_muted']}; font-size: 11px; margin: 0 0 6px; text-transform: uppercase; letter-spacing: 0.4px; }}
    .ct-kpi-value {{ color: {COLORS['text']}; font-size: 24px; font-weight: 600; margin: 0; letter-spacing: -0.3px; }}

    .ct-badge {{ font-size: 10px; padding: 3px 9px; border-radius: 6px; font-weight: 500; }}
    .ct-badge-high {{ background: #4A1B0C; color: #F0997B; }}
    .ct-badge-mid  {{ background: #412402; color: #EF9F27; }}
    .ct-badge-low  {{ background: #04342C; color: #5DCAA5; }}

    .ct-insight {{
        display: flex; align-items: flex-start; gap: 12px;
        background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-left: 3px solid {COLORS['blue']};
        border-radius: 8px; padding: 12px 14px; margin-bottom: 10px;
    }}
    .ct-insight-icon {{ font-size: 18px; line-height: 1.4; }}
    .ct-insight-text {{ color: {COLORS['text']}; font-size: 13.5px; line-height: 1.5; margin: 0; }}
    .ct-insight-text b {{ color: {COLORS['text']}; }}

    div[data-testid="stMetric"] {{ background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 10px; padding: 14px 16px; }}
    div[data-testid="stMetric"] label {{ color: {COLORS['text_muted']} !important; }}

    /* ---------- Sidebar logo ---------- */
    .ct-logo-wrap {{ display: flex; align-items: center; gap: 10px; padding: 4px 4px 18px; border-bottom: 1px solid {COLORS['border']}; margin-bottom: 14px; }}
    .ct-logo-mark {{
        width: 38px; height: 38px; border-radius: 10px; flex-shrink: 0;
        background: linear-gradient(135deg, {COLORS['blue']}, {COLORS['purple']});
        display: flex; align-items: center; justify-content: center;
        font-size: 18px; box-shadow: 0 0 18px rgba(79,168,255,0.35);
    }}
    .ct-logo-name {{ font-size: 16px; font-weight: 700; color: {COLORS['text']}; margin: 0; letter-spacing: -0.2px; }}
    .ct-logo-org {{ font-size: 10.5px; color: {COLORS['text_muted']}; margin: 0; text-transform: uppercase; letter-spacing: 0.5px; }}

    /* ---------- Sidebar nav buttons ---------- */
    section[data-testid="stSidebar"] .stButton button {{
        width: 100%; text-align: left; background: transparent; border: 1px solid transparent;
        color: {COLORS['text_muted']}; font-size: 13.5px; padding: 8px 12px; border-radius: 8px; margin-bottom: 2px;
        font-weight: 500; transition: none;
    }}
    section[data-testid="stSidebar"] .stButton button:hover {{
        background: {COLORS['surface2']}; color: {COLORS['text']}; border: 1px solid {COLORS['border']};
    }}
    section[data-testid="stSidebar"] .stButton button[kind="primary"] {{
        background: linear-gradient(90deg, rgba(79,168,255,0.18), rgba(79,168,255,0.02));
        color: {COLORS['blue']} !important; border: 1px solid rgba(79,168,255,0.35);
    }}

    .ct-alert-banner {{
        display: flex; align-items: center; justify-content: space-between; gap: 12px;
        background: linear-gradient(90deg, #3A1508, {COLORS['surface']});
        border: 1px solid #6B2C13; border-radius: 10px; padding: 10px 16px; margin-bottom: 16px;
    }}
    .ct-alert-text {{ color: #F0997B; font-size: 13px; margin: 0; font-weight: 500; }}

    .ct-nav-badge {{
        display: inline-block; background: {COLORS['coral']}; color: white; font-size: 10px; font-weight: 700;
        border-radius: 10px; padding: 1px 7px; margin-left: 6px;
    }}

    .stTabs [data-baseweb="tab-list"] {{ gap: 4px; }}
    .stTabs [data-baseweb="tab"] {{ background: transparent; color: {COLORS['text_muted']}; padding: 8px 16px; border-radius: 8px 8px 0 0; }}
    .stTabs [aria-selected="true"] {{ color: {COLORS['blue']} !important; border-bottom: 2px solid {COLORS['blue']} !important; }}

    /* ---------- Landing page ---------- */
    .ct-landing {{ display: flex; flex-direction: column; align-items: center; justify-content: center;
                   text-align: center; padding: 8vh 10px 4vh; }}
    .ct-landing-mark {{
        width: 84px; height: 84px; border-radius: 22px; margin-bottom: 22px;
        background: linear-gradient(135deg, {COLORS['blue']}, {COLORS['purple']});
        display: flex; align-items: center; justify-content: center; font-size: 40px;
        box-shadow: 0 0 50px rgba(79,168,255,0.35);
    }}
    .ct-landing-title {{ font-size: 40px; font-weight: 700; color: {COLORS['text']}; margin: 0; letter-spacing: -1px; }}
    .ct-landing-sub {{ font-size: 15px; color: {COLORS['text_muted']}; margin: 10px 0 6px; max-width: 560px; }}
    .ct-landing-org {{ font-size: 11.5px; color: {COLORS['blue']}; letter-spacing: 1.5px; text-transform: uppercase; margin-bottom: 40px; font-weight: 600; }}
    .ct-feature {{
        background: {COLORS['surface']}; border: 1px solid {COLORS['border']}; border-radius: 14px;
        padding: 20px 18px; height: 100%;
    }}
    .ct-feature-icon {{ font-size: 22px; margin-bottom: 10px; }}
    .ct-feature-title {{ font-size: 14px; font-weight: 600; color: {COLORS['text']}; margin: 0 0 6px; }}
    .ct-feature-text {{ font-size: 12.5px; color: {COLORS['text_muted']}; margin: 0; line-height: 1.5; }}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# CONNEXION BASE DE DONNÉES
# ==============================================================================
# Identifiants lus depuis .streamlit/secrets.toml (voir secrets.toml.example fourni).
# Repli sur les valeurs par défaut si le fichier n'existe pas encore, pour ne rien casser.
try:
    _db = st.secrets["db"]
    DB_USER, DB_PASSWORD, DB_HOST, DB_PORT = _db["user"], _db["password"], _db["host"], int(_db["port"])
except Exception:
    DB_USER, DB_PASSWORD, DB_HOST, DB_PORT = "root", "Ncr@1234", "localhost", 3306
PASSWORD_ENCODED = quote_plus(DB_PASSWORD)


@st.cache_resource
def get_engine():
    return create_engine(
        f"mysql+pymysql://{DB_USER}:{PASSWORD_ENCODED}@{DB_HOST}:{DB_PORT}/webman_tmp",
        pool_pre_ping=True,   # revalide la connexion avant usage -> évite les crashs après inactivité
        pool_recycle=1800,    # recycle les connexions avant le timeout MySQL (souvent 8h côté serveur, on marge large)
        pool_size=10,         # augmenté (5 -> 10) : plusieurs onglets/utilisateurs peuvent lancer des requêtes en parallèle
        max_overflow=15,
        pool_use_lifo=True,   # réutilise la connexion la plus "chaude" en priorité, un peu plus rapide sous charge légère
    )

# ------------------------------------------------------------------------------
# LEVIER DE VITESSE PRINCIPAL — INDEX MySQL recommandés (côté base, pas dans ce fichier) :
#   ALTER TABLE webman_tmp.tr_hist_change ADD INDEX idx_date (date_modif_acte);
#   ALTER TABLE webman_tmp.tr_hist_change ADD INDEX idx_acte (id_acte);
#   ALTER TABLE webman_tmp.tr_hist_change ADD INDEX idx_user (id_user);
#   ALTER TABLE webman_tmp.tr_hist_change ADD INDEX idx_col (col_name);
#   ALTER TABLE webman_tmp.tr_hist_change ADD INDEX idx_date_acte (date_modif_acte, id_acte);
# Sans ces index, chaque requête filtrée par période/agent/acte fait un scan complet de la table,
# ce qui domine largement le temps de réponse une fois la table volumineuse (bien plus que le
# cache ou le rendu des graphiques). À faire une seule fois côté DBA.
# ------------------------------------------------------------------------------

CACHE_TTL_SECONDS = 900  # cache principal (vitesse) — long car couvert par le bouton "Rafraîchir" + l'alerte de changement
PROBE_TTL_SECONDS = 300  # fréquence de vérification "y a-t-il du nouveau ?" — indépendant du cache principal, reste court


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False, max_entries=384)
def run_query(query: str, params: dict | None = None) -> pd.DataFrame:
    """Exécute une requête SQL paramétrée. Cache 15 min -> rapide ; voir _db_signature() pour la détection de changement."""
    t0 = time.perf_counter()
    try:
        df = pd.read_sql(text(query), get_engine(), params=params or {})
        _QUERY_LOG.append(time.perf_counter() - t0)  # n'arrive ici QUE si ce n'était pas déjà en cache
        return df
    except Exception as e:
        st.error(f"⚠️ Erreur de connexion à la base de données : {e}")
        st.stop()


@st.cache_data(ttl=PROBE_TTL_SECONDS, show_spinner=False)
def _db_signature() -> str:
    """Empreinte très légère (COUNT + MAX date) pour détecter un changement sans recharger toute la donnée."""
    row = pd.read_sql(
        text("SELECT COUNT(*) AS n, MAX(date_modif_acte) AS d FROM webman_tmp.tr_hist_change"),
        get_engine(),
    ).iloc[0]
    return f"{row['n']}-{row['d']}"


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Détection des rafales…")
def _detect_bursts(where_h: str, gp: dict, window_min: int, min_count: int) -> pd.DataFrame:
    """Détecte les rafales de corrections par agent (fenêtre glissante ancrée). Mis en cache dans son
    ensemble : sans ce cache, cette détection tournerait à chaque rerun (changement d'onglet, clic sur
    un bouton…) même quand les données sources n'ont pas changé.
    Version vectorisée : les timestamps sont convertis en entiers (ns) une seule fois par agent, puis on
    avance avec une recherche binaire (np.searchsorted) au lieu de comparer les paires de timestamps un
    par un en Python pur — même logique de détection, mais nettement plus rapide sur les gros volumes."""
    burst_raw = run_query(f"""
        SELECT u.full_name, h.date_modif_acte FROM webman_tmp.tr_hist_change h
        JOIN webman_users.tr_user u ON h.id_user = u.cin
        WHERE {where_h} ORDER BY u.full_name, h.date_modif_acte
    """, params=gp)
    bursts = []
    if not burst_raw.empty:
        burst_raw["date_modif_acte"] = pd.to_datetime(burst_raw["date_modif_acte"])
        window_ns = window_min * 60 * 1_000_000_000
        for name, grp in burst_raw.groupby("full_name", sort=False):
            ts = np.sort(grp["date_modif_acte"].values.astype("datetime64[ns]").view("int64"))
            i, n = 0, len(ts)
            while i < n:
                j = int(np.searchsorted(ts, ts[i] + window_ns, side="right")) - 1
                count = j - i + 1
                if count >= min_count:
                    bursts.append({"Agent": name, "Début": pd.Timestamp(ts[i]), "Fin": pd.Timestamp(ts[j]),
                                    "Nb corrections": count})
                i = j + 1
    return pd.DataFrame(bursts)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner="Détection des oscillations…")
def _detect_oscillations(where_h: str, gp: dict) -> pd.DataFrame:
    """Détecte les corrections oscillantes (A → B → A) par acte et par champ. Même logique de cache que
    _detect_bursts : on met en cache le résultat post-traité, pas seulement la requête SQL brute."""
    osc_raw = run_query(f"""
        SELECT h.id_acte, h.col_name, h.date_modif_acte, h.old_value, h.new_value,
               COALESCE(u.full_name, 'Non attribué') AS agent
        FROM webman_tmp.tr_hist_change h LEFT JOIN webman_users.tr_user u ON h.id_user = u.cin
        WHERE {where_h} AND h.type_action = 'UPDATE' AND h.old_value IS NOT NULL AND h.new_value IS NOT NULL
              AND h.old_value <> h.new_value
        ORDER BY h.id_acte, h.col_name, h.date_modif_acte
    """, params=gp)
    oscillations = []
    if not osc_raw.empty:
        osc_raw["date_modif_acte"] = pd.to_datetime(osc_raw["date_modif_acte"])
        # La requête SQL trie déjà par (id_acte, col_name, date_modif_acte) : groupby(sort=False) conserve
        # cet ordre chronologique par groupe, ce qui évite un second tri pandas coûteux sur chaque groupe.
        for (acte, champ), grp in osc_raw.groupby(["id_acte", "col_name"], sort=False):
            if len(grp) < 2:
                continue
            seq = list(grp["old_value"]) + [grp["new_value"].iloc[-1]]
            if len(set(seq)) < len(seq):
                oscillations.append({
                    "Acte": acte, "Champ": champ, "Agents impliqués": grp["agent"].nunique(),
                    "Nb changements": len(grp), "Séquence de valeurs": " → ".join(str(v) for v in seq),
                })
    return pd.DataFrame(oscillations)


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _compute_alert_count() -> int:
    """Calcule le nb d'alertes pour le badge du menu — tout le calcul (requête + stats pandas) est mis en
    cache d'un bloc, pour ne pas refaire ce travail à chaque navigation entre onglets.
    Bornée aux 180 derniers jours : ce badge s'affiche sur CHAQUE page, donc sans cette borne il ferait
    un scan complet de tr_hist_change à chaque expiration du cache, même une fois la table très volumineuse.
    180 jours suffit largement pour détecter un pic ou un agent à risque récent."""
    fenetre = "AND date_modif_acte >= DATE_SUB(NOW(), INTERVAL 180 DAY)"
    dist_alert = run_query(f"SELECT id_acte, COUNT(*) AS nb FROM webman_tmp.tr_hist_change WHERE 1=1 {fenetre} GROUP BY id_acte")
    m, s = dist_alert["nb"].mean(), dist_alert["nb"].std()
    n_anom = int((dist_alert["nb"] > (m + 2 * s)).sum()) if len(dist_alert) else 0

    ratio_alert = run_query(f"""
        SELECT u.full_name, COUNT(*) AS total FROM webman_tmp.tr_hist_change h
        JOIN webman_users.tr_user u ON h.id_user = u.cin WHERE 1=1 {fenetre} GROUP BY u.full_name HAVING total > 20
    """)
    n_risk = 0
    if not ratio_alert.empty:
        mt, st_ = ratio_alert["total"].mean(), ratio_alert["total"].std()
        n_risk = int((ratio_alert["total"] > (mt + st_)).sum())
    return n_anom + n_risk


def safe_div(a, b):
    return (a / b) if b else 0.0


@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _build_export_xlsx(extra_where: str, extra_params: dict, max_rows: int) -> bytes:
    """Requête + construction du classeur Excel, appelée seulement au clic (voir onglet 'temporel').
    Mise en cache : ré-cliquer avec les mêmes filtres ne relance ni la requête ni openpyxl."""
    export_df = run_query(f"""
        SELECT h.date_modif_acte AS "Date et heure", h.id_acte AS "Acte",
               COALESCE(u.full_name, 'Non attribué') AS "Agent",
               h.type_action AS "Action", h.col_name AS "Champ"
        FROM webman_tmp.tr_hist_change h
        LEFT JOIN webman_users.tr_user u ON h.id_user = u.cin
        WHERE h.date_modif_acte BETWEEN :d1 AND :d2 {extra_where}
        ORDER BY h.date_modif_acte DESC LIMIT {max_rows}
    """, params=extra_params)
    xbuf = io.BytesIO()
    with pd.ExcelWriter(xbuf, engine="openpyxl") as writer:
        export_df.to_excel(writer, sheet_name="Détail période", index=False)
    return xbuf.getvalue()


# ==============================================================================
# HELPERS D'AFFICHAGE
# ==============================================================================
def sparkline_svg(values, color=COLORS["blue"], width=140, height=32):
    values = list(values)
    if len(values) < 2:
        return ""
    vmin, vmax = min(values), max(values)
    rng = (vmax - vmin) or 1
    step = width / (len(values) - 1)
    pts = " ".join(f"{i*step:.1f},{height - ((v - vmin) / rng) * height:.1f}" for i, v in enumerate(values))
    return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" style="margin-top:6px;"><polyline points="{pts}" fill="none" stroke="{color}" stroke-width="2"/></svg>'


def kpi_card(label, value, delta_text, delta_color, values, accent):
    spark = sparkline_svg(values, color=accent)
    return f"""
    <div class="ct-kpi" style="border-top:3px solid {accent};">
        <p class="ct-kpi-label">{label}</p>
        <div style="display:flex;align-items:baseline;gap:8px;">
            <p class="ct-kpi-value">{value}</p>
            <span style="color:{delta_color};font-size:12px;">{delta_text}</span>
        </div>
        {spark}
    </div>
    """


def risk_badge(level: str) -> str:
    cls = {"Élevé": "ct-badge-high", "Moyen": "ct-badge-mid", "Faible": "ct-badge-low"}[level]
    return f'<span class="ct-badge {cls}">{level}</span>'


def insight_card(icon: str, html_text: str, accent=None) -> str:
    border = f"border-left: 3px solid {accent};" if accent else ""
    return f"""
    <div class="ct-insight" style="{border}">
        <span class="ct-insight-icon">{icon}</span>
        <p class="ct-insight-text">{html_text}</p>
    </div>
    """


def gauge_fig(value, title, color):
    fig = go.Figure(go.Indicator(
        mode="gauge+number",
        value=round(value, 1),
        number={"suffix": "%", "font": {"size": 22, "color": COLORS["text"]}},
        title={"text": title, "font": {"size": 12, "color": COLORS["text_muted"]}},
        gauge={
            "axis": {"range": [0, 100], "tickcolor": COLORS["text_muted"], "tickfont": {"size": 9}},
            "bar": {"color": color, "thickness": 0.75},
            "bgcolor": COLORS["surface2"],
            "borderwidth": 0,
        },
    ))
    fig.update_layout(paper_bgcolor=COLORS["surface"], font={"color": COLORS["text"]},
                       height=190, margin=dict(l=15, r=15, t=35, b=5))
    return fig


def gfilter_where(alias="h", team_alias=None):
    """Clause WHERE + params pour le filtre global (période, et équipe si un alias de groupe est fourni)."""
    conds = [f"{alias}.date_modif_acte BETWEEN :gd1 AND :gd2"]
    params = {"gd1": st.session_state["gfilter_start"], "gd2": st.session_state["gfilter_end"]}
    if team_alias and st.session_state["gfilter_team"] != "Toutes les équipes":
        conds.append(f"{team_alias}.grp_desc = :gteam")
        params["gteam"] = st.session_state["gfilter_team"]
    return " AND ".join(conds), params


# ==============================================================================
# BORNES DE DATES (pour les filtres) — indépendant du filtre global
# ==============================================================================
_bounds = run_query("SELECT MIN(date_modif_acte) AS mn, MAX(date_modif_acte) AS mx FROM webman_tmp.tr_hist_change").iloc[0]
# Période par défaut = 90 derniers jours de données, PAS tout l'historique.
# Avant : le filtre par défaut couvrait mn -> mx (des années de données), donc chaque onglet
# agrégeait la quasi-totalité des millions de lignes de tr_hist_change dès le premier chargement
# — un index sur date_modif_acte ne peut rien y faire si le filtre couvre 100% des dates.
# L'utilisateur peut toujours élargir la période manuellement via le sélecteur dans la sidebar.
DEFAULT_WINDOW_DAYS = 90
_default_start = max(_bounds["mn"].date(), _bounds["mx"].date() - timedelta(days=DEFAULT_WINDOW_DAYS))
st.session_state.setdefault("gfilter_start", _default_start)
st.session_state.setdefault("gfilter_end", _bounds["mx"].date())

_teams = run_query("SELECT DISTINCT grp_desc FROM webman_users.tr_grp ORDER BY grp_desc")

# ==============================================================================
# PAGE D'ACCUEIL
# ==============================================================================
if not st.session_state["entered"]:
    st.markdown(f"""
        <div class="ct-landing">
            <div class="ct-landing-mark">{LOGO_ICON}</div>
            <p class="ct-landing-title">{APP_NAME}</p>
            <p class="ct-landing-sub">{APP_TAGLINE} — une plateforme d'analyse pour suivre, comprendre et fiabiliser
            l'ensemble des corrections apportées aux actes d'état civil.</p>
        </div>
    """, unsafe_allow_html=True)

    _, c1, c2, c3, _ = st.columns([0.6, 1, 1, 1, 0.6])
    with c1:
        st.markdown("""
            <div class="ct-feature"><div class="ct-feature-icon">🧭</div>
            <p class="ct-feature-title">Synthèse instantanée</p>
            <p class="ct-feature-text">Les indicateurs et constats essentiels, lisibles en 30 secondes par un manager.</p></div>
        """, unsafe_allow_html=True)
    with c2:
        st.markdown("""
            <div class="ct-feature"><div class="ct-feature-icon">⚠️</div>
            <p class="ct-feature-title">Détection d'anomalies</p>
            <p class="ct-feature-text">Alertes automatiques sur les volumes anormaux, les agents à risque et les horaires atypiques.</p></div>
        """, unsafe_allow_html=True)
    with c3:
        st.markdown("""
            <div class="ct-feature"><div class="ct-feature-icon">📤</div>
            <p class="ct-feature-title">Rapports exportables</p>
            <p class="ct-feature-text">Génération de rapports Excel et PDF, prêts à partager avec la direction.</p></div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    _, cbtn, _ = st.columns([1.6, 1, 1.6])
    with cbtn:
        if st.button("Accéder au tableau de bord  →", use_container_width=True, type="primary"):
            st.session_state["entered"] = True
            st.rerun()
    st.stop()

# ==============================================================================
# SIDEBAR — LOGO, NAVIGATION, FILTRES GLOBAUX, RECHERCHE
# ==============================================================================
with st.sidebar:
    st.markdown(f"""
        <div class="ct-logo-wrap">
            <div class="ct-logo-mark">{LOGO_ICON}</div>
            <div>
                <p class="ct-logo-name">{APP_NAME}</p>
            </div>
        </div>
    """, unsafe_allow_html=True)

    # ---- alertes pour le badge du menu (calcul entier mis en cache, pas juste la requête) ----
    ALERT_COUNT = _compute_alert_count()

    st.markdown("<p style='font-size:10.5px;color:#8B93A1;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;'>Navigation</p>", unsafe_allow_html=True)
    for key, icon, label in NAV_ITEMS:
        badge = f'<span class="ct-nav-badge">{ALERT_COUNT}</span>' if key == "anomalies" and ALERT_COUNT else ""
        is_active = st.session_state["nav"] == key
        if st.button(f"{icon}  {label}", key=f"nav_{key}", use_container_width=True,
                     type="primary" if is_active else "secondary"):
            st.session_state["nav"] = key
            # Pas de st.rerun() ici : la sidebar est exécutée avant le corps de la page,
            # le nouvel onglet s'affiche donc dès ce passage. Cela divise par deux le
            # nombre d'exécutions du script à chaque clic de navigation.
        if badge:
            st.markdown(f"<div style='margin-top:-32px;margin-left:220px;position:relative;z-index:10;'>{badge}</div>", unsafe_allow_html=True)

    st.markdown("<hr style='border-color:#2A2F3B;margin:16px 0;'>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:10.5px;color:#8B93A1;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;'>Filtres globaux</p>", unsafe_allow_html=True)

    date_range = st.date_input("Période", value=(st.session_state["gfilter_start"], st.session_state["gfilter_end"]),
                                min_value=_bounds["mn"].date(), max_value=_bounds["mx"].date())
    if isinstance(date_range, tuple) and len(date_range) == 2:
        st.session_state["gfilter_start"], st.session_state["gfilter_end"] = date_range
    st.caption(f"Par défaut : {DEFAULT_WINDOW_DAYS} derniers jours (pour la vitesse). "
               "Élargissez la période ci-dessus si besoin — le chargement sera plus long sur de longues périodes.")

    team_options = ["Toutes les équipes"] + _teams["grp_desc"].tolist()
    st.session_state["gfilter_team"] = st.selectbox("Équipe", team_options,
                                                      index=team_options.index(st.session_state["gfilter_team"])
                                                      if st.session_state["gfilter_team"] in team_options else 0)
    st.caption("Le filtre équipe s'applique aux vues Équipe, Agent et Anomalies.")

    st.markdown("<hr style='border-color:#2A2F3B;margin:16px 0;'>", unsafe_allow_html=True)
    st.markdown("<p style='font-size:10.5px;color:#8B93A1;text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;'>Recherche rapide</p>", unsafe_allow_html=True)
    with st.form("global_search_form", clear_on_submit=False):
        q = st.text_input("Agent ou n° d'acte", placeholder="ex: Bourmi ou 402317", label_visibility="collapsed")
        searched = st.form_submit_button("Rechercher", use_container_width=True)
    if searched and q:
        agents_hit = run_query("""
            SELECT DISTINCT u.full_name, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
            JOIN webman_users.tr_user u ON h.id_user = u.cin
            WHERE u.full_name LIKE :p GROUP BY u.full_name ORDER BY nb DESC LIMIT 5
        """, params={"p": f"%{q}%"})
        actes_hit = pd.DataFrame()
        if q.isdigit():
            actes_hit = run_query("""
                SELECT id_acte, COUNT(*) AS nb FROM webman_tmp.tr_hist_change
                WHERE id_acte = :a GROUP BY id_acte
            """, params={"a": int(q)})
        st.session_state["search_results"] = {"agents": agents_hit, "actes": actes_hit, "query": q}

    st.markdown("<hr style='border-color:#2A2F3B;margin:16px 0;'>", unsafe_allow_html=True)
    if st.button("🔄  Rafraîchir maintenant", use_container_width=True, help=f"Les données sont mises en cache {CACHE_TTL_SECONDS // 60} min ; ce bouton force une lecture immédiate de la base."):
        st.cache_data.clear()
        st.session_state["last_refresh"] = datetime.now()
        st.session_state["known_signature"] = None
        st.rerun()

    st.markdown(f"""
        <div style="width:100%;margin-top:8px;">
            <div class="ct-live-badge" style="width:100%;box-sizing:border-box;">
                <span class="ct-dot"></span>Dernier rafraîchissement forcé — {st.session_state["last_refresh"].strftime('%H:%M:%S')}
            </div>
        </div>
    """, unsafe_allow_html=True)

# ==============================================================================
# ALERTE "NOUVELLES DONNÉES DISPONIBLES" (sondage léger, sans recharger la donnée)
# ==============================================================================
try:
    _current_sig = _db_signature()
    if st.session_state["known_signature"] is None:
        st.session_state["known_signature"] = _current_sig  # référence prise au premier chargement, pas d'alerte immédiate
    elif _current_sig != st.session_state["known_signature"]:
        with st.container(border=True):
            bcol1, bcol2 = st.columns([5, 1])
            bcol1.markdown("🔔 **De nouvelles modifications ont été détectées dans la base depuis votre dernier "
                            "rafraîchissement.** Les chiffres affichés ici peuvent être dépassés.")
            if bcol2.button("Rafraîchir", key="refresh_from_alert", use_container_width=True):
                st.cache_data.clear()
                st.session_state["last_refresh"] = datetime.now()
                st.session_state["known_signature"] = None
                st.rerun()
except Exception:
    pass  # le sondage ne doit jamais faire planter l'app — au pire, pas d'alerte affichée

# ==============================================================================
# RÉSULTATS DE RECHERCHE GLOBALE (affichés en haut, quelle que soit la page)
# ==============================================================================
if st.session_state["search_results"]:
    res = st.session_state["search_results"]
    with st.container(border=True):
        h1, h2 = st.columns([6, 1])
        h1.markdown(f"**🔍 Résultats pour « {res['query']} »**")
        if h2.button("Fermer", key="close_search"):
            st.session_state["search_results"] = None
            st.rerun()
        if res["agents"].empty and res["actes"].empty:
            st.caption("Aucun résultat.")
        cols = st.columns(len(res["agents"]) + len(res["actes"]) or 1)
        i = 0
        for r in res["agents"].itertuples():
            with cols[i]:
                st.caption("Agent")
                if st.button(f"👤 {r.full_name}\n{int(r.nb)} corrections", key=f"go_agent_{i}", use_container_width=True):
                    st.session_state["nav"] = "agent"
                    st.session_state["agent_prefill"] = r.full_name
                    st.session_state["search_results"] = None
                    st.rerun()
            i += 1
        for r in res["actes"].itertuples():
            with cols[i]:
                st.caption("Acte")
                if st.button(f"📄 #{r.id_acte}\n{int(r.nb)} corrections", key=f"go_acte_{i}", use_container_width=True):
                    st.session_state["nav"] = "acte"
                    st.session_state["acte_prefill"] = str(r.id_acte)
                    st.session_state["search_results"] = None
                    st.rerun()
            i += 1

# ==============================================================================
# EN-TÊTE DE PAGE
# ==============================================================================
current_label = next(f"{icon}  {label}" for key, icon, label in NAV_ITEMS if key == st.session_state["nav"])
col_title, col_badge = st.columns([4, 1])
with col_title:
    st.markdown(f"""
        <p class="ct-title">{current_label}</p>
        <p class="ct-subtitle">{APP_TAGLINE} · période du {st.session_state['gfilter_start']} au {st.session_state['gfilter_end']}</p>
    """, unsafe_allow_html=True)
with col_badge:
    st.markdown(f"""
        <div class="ct-live-badge"><span class="ct-dot"></span>{ALERT_COUNT} alerte(s) active(s)</div>
    """, unsafe_allow_html=True)

if ALERT_COUNT and st.session_state["nav"] != "anomalies":
    b1, b2 = st.columns([6, 1])
    with b1:
        st.markdown(f"""
            <div class="ct-alert-banner">
                <p class="ct-alert-text">🔴 {ALERT_COUNT} alerte(s) active(s) détectée(s) sur la période sélectionnée.</p>
            </div>
        """, unsafe_allow_html=True)
    with b2:
        if st.button("Voir →", key="goto_alerts"):
            st.session_state["nav"] = "anomalies"
            st.rerun()

st.markdown("<br>", unsafe_allow_html=True)
NAV = st.session_state["nav"]

# Plus d'auto-refresh périodique : il relançait tout le script (et donc tous les graphiques)
# toutes les 45 s. La détection de nouveautés se fait désormais uniquement au fil des
# interactions, via _db_signature() qui est une requête ultra-légère mise en cache.

# ==============================================================================
# SYNTHÈSE
# ==============================================================================
if NAV == "synthese":
    where_h, gp = gfilter_where("h")
    kpi = run_query(f"""
        SELECT COUNT(*) AS total, COUNT(DISTINCT id_acte) AS actes,
               SUM(type_action='UPDATE') AS n_update, SUM(type_action='DELETE') AS n_delete,
               SUM(type_action='INSERT') AS n_insert, SUM(id_user IS NULL) AS non_attribue
        FROM webman_tmp.tr_hist_change h WHERE {where_h}
    """, params=gp).iloc[0]
    total = int(kpi["total"]) or 1

    top_agent_global = run_query(f"""
        SELECT u.full_name, COUNT(*) AS nb
        FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
        WHERE {where_h} GROUP BY u.full_name ORDER BY nb DESC LIMIT 1
    """, params=gp)
    top_acte_global = run_query(f"""
        SELECT id_acte, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h WHERE {where_h}
        GROUP BY id_acte ORDER BY nb DESC LIMIT 1
    """, params=gp)
    dist_actes = run_query(f"""
        SELECT id_acte, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY id_acte
    """, params=gp)
    mean_d, std_d = dist_actes["nb"].mean(), dist_actes["nb"].std()
    nb_anomalies = int((dist_actes["nb"] > (mean_d + 2 * std_d)).sum()) if len(dist_actes) else 0
    hourly = run_query(f"""
        SELECT HOUR(h.date_modif_acte) AS heure, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
        WHERE {where_h} GROUP BY heure
    """, params=gp)
    pct_hors_horaires = 0.0
    if not hourly.empty:
        hors = hourly[(hourly["heure"] < 7) | (hourly["heure"] >= 20)]["nb"].sum()
        pct_hors_horaires = 100 * safe_div(hors, hourly["nb"].sum())

    daily = run_query(f"""
        SELECT DATE(h.date_modif_acte) AS jour, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
        WHERE {where_h} GROUP BY jour ORDER BY jour
    """, params=gp)
    trend_delta = ""
    if len(daily) >= 14:
        last7, prev7 = daily["nb"].tail(7).sum(), daily["nb"].tail(14).head(7).sum()
        variation = 100 * safe_div(last7 - prev7, prev7)
        trend_delta = f"{variation:+.0f}% vs 7 j. précédents"

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(kpi_card("Total corrections", f"{total:,}".replace(",", " "), trend_delta, COLORS["text_muted"],
                              daily["nb"].tail(14).tolist() or [0, 0], COLORS["blue"]), unsafe_allow_html=True)
    with c2:
        st.markdown(kpi_card("Actes concernés", f"{int(kpi['actes']):,}".replace(",", " "), "", "",
                              daily["nb"].tail(14).tolist() or [0, 0], COLORS["purple"]), unsafe_allow_html=True)
    with c3:
        st.markdown(kpi_card("Opérations non attribuées", f"{int(kpi['non_attribue']):,}".replace(",", " "),
                              f"{100*safe_div(kpi['non_attribue'], total):.0f}% du total",
                              COLORS["coral"] if kpi["non_attribue"] else COLORS["green"],
                              daily["nb"].tail(14).tolist() or [0, 0], COLORS["coral"]), unsafe_allow_html=True)
    with c4:
        st.markdown(kpi_card("Actes en anomalie de volume", f"{nb_anomalies:,}".replace(",", " "), "", "",
                              daily["nb"].tail(14).tolist() or [0, 0], COLORS["yellow"]), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    left, right = st.columns([1.6, 1])
    with left:
        st.markdown("##### Points clés")
        if not top_agent_global.empty:
            a = top_agent_global.iloc[0]
            ic1, ic2 = st.columns([5, 1])
            with ic1:
                st.markdown(insight_card("👤", f"L'agent le plus actif est <b>{a['full_name']}</b>, avec "
                                                f"<b>{int(a['nb'])}</b> corrections enregistrées.", COLORS["blue"]),
                            unsafe_allow_html=True)
            with ic2:
                if st.button("Voir →", key="drill_top_agent"):
                    st.session_state["agent_prefill"] = a["full_name"]
                    st.session_state["nav"] = "agent"
                    st.rerun()
        if not top_acte_global.empty:
            b = top_acte_global.iloc[0]
            ic3, ic4 = st.columns([5, 1])
            with ic3:
                st.markdown(insight_card("📄", f"L'acte le plus corrigé est <b>#{b['id_acte']}</b>, avec "
                                                f"<b>{int(b['nb'])}</b> corrections — à examiner en priorité.", COLORS["purple"]),
                            unsafe_allow_html=True)
            with ic4:
                if st.button("Voir →", key="drill_top_acte"):
                    st.session_state["acte_prefill"] = str(b["id_acte"])
                    st.session_state["nav"] = "acte"
                    st.rerun()
        st.markdown(insight_card("⚠️" if nb_anomalies else "✅",
                                  f"<b>{nb_anomalies}</b> acte(s) présentent un volume de corrections statistiquement "
                                  f"anormal (au-delà de 2 écarts-types de la moyenne)." if nb_anomalies else
                                  "Aucun acte ne dépasse le seuil d'anomalie de volume actuel.",
                                  COLORS["coral"] if nb_anomalies else COLORS["green"]), unsafe_allow_html=True)
        st.markdown(insight_card("🌙", f"<b>{pct_hors_horaires:.0f}%</b> des corrections ont lieu en dehors des "
                                        f"horaires de bureau (avant 7h ou après 20h).",
                                  COLORS["coral"] if pct_hors_horaires > 10 else COLORS["green"]),
                    unsafe_allow_html=True)
        st.markdown(insight_card("🔗", f"<b>{100*safe_div(kpi['non_attribue'], total):.0f}%</b> des opérations ne "
                                        f"peuvent pas être rattachées à un agent (essentiellement des suppressions "
                                        f"sans identifiant utilisateur).",
                                  COLORS["coral"] if kpi["non_attribue"] else COLORS["green"]), unsafe_allow_html=True)

    with right:
        action_counts = run_query(f"""
            SELECT type_action, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY type_action
        """, params=gp)
        fig = px.pie(action_counts, names="type_action", values="nb", hole=0.55, template=PLOTLY_TEMPLATE,
                     title="Répartition par type d'action", color="type_action",
                     color_discrete_map={"UPDATE": COLORS["green"], "DELETE": COLORS["coral"], "INSERT": COLORS["blue"]})
        fig.update_traces(textinfo="percent+label")
        fig.update_layout(height=340, showlegend=False)
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<br>", unsafe_allow_html=True)
    pred_col, cal_col = st.columns([1.3, 1])
    with pred_col:
        if len(daily) >= 10:
            d_pred = daily.copy()
            d_pred["jour"] = pd.to_datetime(d_pred["jour"])
            d_pred = d_pred.sort_values("jour").tail(30).reset_index(drop=True)
            x = np.arange(len(d_pred))
            slope, intercept = np.polyfit(x, d_pred["nb"], 1)
            resid_std = float(np.std(d_pred["nb"] - (slope * x + intercept)))
            future_x = np.arange(len(d_pred), len(d_pred) + 7)
            future_dates = pd.date_range(d_pred["jour"].iloc[-1] + pd.Timedelta(days=1), periods=7)
            future_y = np.clip(slope * future_x + intercept, 0, None)
            fig_pred = go.Figure()
            fig_pred.add_trace(go.Scatter(x=d_pred["jour"], y=d_pred["nb"], mode="lines", name="Observé",
                                           line=dict(color=COLORS["blue"], width=2)))
            fig_pred.add_trace(go.Scatter(x=future_dates, y=future_y, mode="lines", name="Projection",
                                           line=dict(color=COLORS["yellow"], width=2, dash="dash")))
            fig_pred.add_trace(go.Scatter(
                x=list(future_dates) + list(future_dates[::-1]),
                y=list(np.clip(future_y + resid_std, 0, None)) + list(np.clip(future_y - resid_std, 0, None)[::-1]),
                fill="toself", fillcolor="rgba(255,194,79,0.12)", line=dict(color="rgba(0,0,0,0)"),
                showlegend=False, hoverinfo="skip"))
            fig_pred.update_layout(template=PLOTLY_TEMPLATE, height=300, legend_title_text="",
                                    title="Tendance et projection à 7 jours (régression linéaire, 30 derniers jours)",
                                    yaxis_title="Corrections / jour", xaxis_title="")
            st.plotly_chart(fig_pred, use_container_width=True, config={"displayModeBar": False})
            st.caption("Projection indicative — régression linéaire simple, sensible aux ruptures de tendance récentes.")
        else:
            st.info("Historique insuffisant sur la période sélectionnée pour calculer une tendance (10 jours minimum).")
    with cal_col:
        if not daily.empty:
            cal = daily.copy()
            cal["jour"] = pd.to_datetime(cal["jour"])
            cal["semaine"] = cal["jour"].dt.strftime("%Y-W%U")
            cal["jour_sem"] = cal["jour"].dt.dayofweek
            jours_labels = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
            pivot_cal = cal.pivot_table(index="jour_sem", columns="semaine", values="nb", fill_value=0).reindex(range(7))
            fig_cal = go.Figure(go.Heatmap(
                z=pivot_cal.values, x=list(pivot_cal.columns), y=jours_labels,
                colorscale=[[0, COLORS["surface2"]], [1, COLORS["green"]]], showscale=False,
                hovertemplate="%{y} — %{x}<br>%{z} corrections<extra></extra>",
            ))
            fig_cal.update_layout(template=PLOTLY_TEMPLATE, height=300, title="Intensité des corrections — vue calendrier",
                                   xaxis_title="", yaxis_title="", xaxis=dict(showticklabels=False))
            st.plotly_chart(fig_cal, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<br>", unsafe_allow_html=True)
    top_col, acte_col = st.columns(2)
    with top_col:
        top5_agents = run_query(f"""
            SELECT u.full_name AS agent, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
            JOIN webman_users.tr_user u ON h.id_user = u.cin
            WHERE {where_h} GROUP BY agent ORDER BY nb DESC LIMIT 5
        """, params=gp)
        if not top5_agents.empty:
            fig_ta = px.bar(top5_agents.sort_values("nb"), x="nb", y="agent", orientation="h",
                             template=PLOTLY_TEMPLATE, title="Top 5 agents les plus actifs", text="nb",
                             color_discrete_sequence=[COLORS["blue"]])
            fig_ta.update_traces(textposition="outside")
            fig_ta.update_layout(height=260, yaxis_title="", xaxis_title="Corrections")
            st.plotly_chart(fig_ta, use_container_width=True, config={"displayModeBar": False})
    with acte_col:
        top5_actes = run_query(f"""
            SELECT id_acte AS acte, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
            WHERE {where_h} GROUP BY acte ORDER BY nb DESC LIMIT 5
        """, params=gp)
        if not top5_actes.empty:
            top5_actes["acte"] = top5_actes["acte"].astype(str)
            fig_tac = px.bar(top5_actes.sort_values("nb"), x="nb", y="acte", orientation="h",
                              template=PLOTLY_TEMPLATE, title="Top 5 actes les plus corrigés", text="nb",
                              color_discrete_sequence=[COLORS["purple"]])
            fig_tac.update_traces(textposition="outside")
            fig_tac.update_layout(height=260, yaxis_title="", xaxis_title="Corrections",
                                   yaxis=dict(type="category"))
            st.plotly_chart(fig_tac, use_container_width=True, config={"displayModeBar": False})

# ==============================================================================
# VUE D'ENSEMBLE
# ==============================================================================
elif NAV == "apercu":
    where_h, gp = gfilter_where("h")
    kpi = run_query(f"""
        SELECT COUNT(*) AS total, COUNT(DISTINCT id_acte) AS actes,
               SUM(type_action='UPDATE') AS n_update, SUM(type_action='DELETE') AS n_delete
        FROM webman_tmp.tr_hist_change h WHERE {where_h}
    """, params=gp).iloc[0]
    total = int(kpi["total"]) or 1

    daily = run_query(f"""
        SELECT DATE(h.date_modif_acte) AS jour, type_action, COUNT(*) AS nb
        FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY jour, type_action ORDER BY jour
    """, params=gp)
    daily_total = daily.groupby("jour")["nb"].sum().tail(14).tolist() if not daily.empty else [0, 0]

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(kpi_card("Total corrections", f"{total:,}".replace(",", " "), "", "", daily_total, COLORS["blue"]), unsafe_allow_html=True)
    with c2:
        st.markdown(kpi_card("Actes touchés", f"{int(kpi['actes']):,}".replace(",", " "), "", "", daily_total, COLORS["purple"]), unsafe_allow_html=True)
    with c3:
        st.markdown(kpi_card("% UPDATE", f"{100*safe_div(kpi['n_update'], total):.1f}%", "", "", daily_total, COLORS["green"]), unsafe_allow_html=True)
    with c4:
        st.markdown(kpi_card("% DELETE", f"{100*safe_div(kpi['n_delete'], total):.1f}%", "", "", daily_total, COLORS["coral"]), unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    left, right = st.columns([2, 1])
    with left:
        if not daily.empty:
            fig = px.area(daily, x="jour", y="nb", color="type_action", template=PLOTLY_TEMPLATE,
                           title="Volume de corrections dans le temps",
                           color_discrete_map={"UPDATE": COLORS["green"], "DELETE": COLORS["coral"], "INSERT": COLORS["blue"]})
            fig.update_layout(height=280, legend_title_text="")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        cal = daily.groupby("jour")["nb"].sum().reset_index()
        if not cal.empty:
            cal["jour"] = pd.to_datetime(cal["jour"])
            cal["semaine"] = cal["jour"].dt.isocalendar().week
            cal["jour_sem"] = cal["jour"].dt.weekday
            pivot = cal.pivot_table(index="jour_sem", columns="semaine", values="nb", fill_value=0)
            fig_cal = px.imshow(pivot, template=PLOTLY_TEMPLATE, aspect="auto",
                                 color_continuous_scale=[COLORS["surface2"], COLORS["blue"]],
                                 title="Heatmap calendrier — intensité d'activité (clair = calme, bleu vif = forte activité)",
                                 labels=dict(x="Semaine", y="Jour", color="Corrections"))
            fig_cal.update_layout(height=200, yaxis=dict(tickvals=list(range(7)),
                                   ticktext=["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]))
            st.plotly_chart(fig_cal, use_container_width=True, config={"displayModeBar": False})

    with right:
        action_counts = run_query(f"""
            SELECT type_action, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY type_action
        """, params=gp)
        fig = px.bar(action_counts.sort_values("nb"), x="nb", y="type_action", orientation="h",
                     template=PLOTLY_TEMPLATE, title="Volume par type d'action", text="nb",
                     color="type_action",
                     color_discrete_map={"UPDATE": COLORS["green"], "DELETE": COLORS["coral"], "INSERT": COLORS["blue"]})
        fig.update_traces(textposition="outside")
        fig.update_layout(height=160, showlegend=False, yaxis_title="", xaxis_title="")

        top_champs_mini = run_query(f"""
            SELECT col_name, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h WHERE {where_h}
            GROUP BY col_name ORDER BY nb DESC LIMIT 6
        """, params=gp)
        fig2 = px.bar(top_champs_mini.sort_values("nb"), x="nb", y="col_name", orientation="h",
                      template=PLOTLY_TEMPLATE, title="Top champs corrigés", text="nb",
                      color_discrete_sequence=[COLORS["purple"]])
        fig2.update_traces(textposition="outside")
        fig2.update_layout(height=260, yaxis_title="", xaxis_title="")

        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🗓️ Détail — 500 dernières corrections de la période")
    detail_periode = run_query(f"""
        SELECT h.date_modif_acte AS "Date et heure", h.id_acte AS "Acte",
               h.col_name AS "Champ", h.type_action AS "Action",
               COALESCE(u.full_name, 'Non attribué') AS "Agent"
        FROM webman_tmp.tr_hist_change h
        LEFT JOIN webman_users.tr_user u ON h.id_user = u.cin
        WHERE {where_h}
        ORDER BY h.date_modif_acte DESC LIMIT 500
    """, params=gp)
    st.dataframe(detail_periode, use_container_width=True, hide_index=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 📆 Vue mensuelle — historique complet")
    st.caption("Contrairement au reste de cet onglet, cette vue ignore le filtre de période global pour montrer "
               "la tendance de fond sur tout l'historique disponible.")
    monthly = run_query("""
        SELECT DATE_FORMAT(date_modif_acte, '%Y-%m') AS mois, COUNT(*) AS nb
        FROM webman_tmp.tr_hist_change GROUP BY mois ORDER BY mois
    """)
    if monthly.empty:
        st.info("Aucune donnée disponible pour la vue mensuelle.")
    else:
        fig_m = px.bar(monthly, x="mois", y="nb", template=PLOTLY_TEMPLATE,
                        title="Volume de corrections par mois (historique complet)",
                        color_discrete_sequence=[COLORS["blue"]])
        fig_m.update_layout(height=320, xaxis_title="", yaxis_title="Corrections")
        st.plotly_chart(fig_m, use_container_width=True, config={"displayModeBar": False})

        if monthly["mois"].nunique() >= 13:
            monthly_yoy = monthly.copy()
            monthly_yoy["annee"] = monthly_yoy["mois"].str[:4]
            monthly_yoy["mois_num"] = monthly_yoy["mois"].str[5:7]
            fig_yoy = px.line(monthly_yoy, x="mois_num", y="nb", color="annee", template=PLOTLY_TEMPLATE,
                               title="Comparaison mois par mois, année sur année", markers=True)
            fig_yoy.update_layout(height=320, xaxis_title="Mois", yaxis_title="Corrections", legend_title_text="Année")
            st.plotly_chart(fig_yoy, use_container_width=True, config={"displayModeBar": False})
        else:
            st.caption("Historique insuffisant (moins de 13 mois) pour une comparaison année sur année.")

# ==============================================================================
# ANALYSE TEMPORELLE — modifications sur une durée précise (id_acte + agents)
# ==============================================================================
elif NAV == "temporel":
    st.caption("Choisissez une durée précise (date **et** heure) pour lister les modifications effectuées, "
               "avec l'acte concerné et l'agent responsable.")

    MAX_TABLE_ROWS = 500       # lignes affichées à l'écran (comme les autres onglets)
    MAX_EXPORT_ROWS = 20000    # plafond de sécurité pour l'export Excel (évite le bug openpyxl sur les très gros classeurs)
    MAX_TIMELINE_POINTS = 3000 # au-delà, la frise chronologique point-par-point devient illisible et trop lourde

    now = datetime.now()
    st.session_state.setdefault("tmp_start_date", st.session_state["gfilter_start"])
    st.session_state.setdefault("tmp_start_time", datetime.min.time().replace(hour=0, minute=0))
    st.session_state.setdefault("tmp_end_date", st.session_state["gfilter_end"])
    st.session_state.setdefault("tmp_end_time", now.time().replace(second=0, microsecond=0))

    c1, c2, c3, c4 = st.columns(4)
    with c1:
        d1 = st.date_input("Date de début", key="tmp_start_date")
    with c2:
        t1 = st.time_input("Heure de début", key="tmp_start_time")
    with c3:
        d2 = st.date_input("Date de fin", key="tmp_end_date")
    with c4:
        t2 = st.time_input("Heure de fin", key="tmp_end_time")

    dt_start, dt_end = datetime.combine(d1, t1), datetime.combine(d2, t2)

    if dt_start >= dt_end:
        st.error("⚠️ La date/heure de début doit être antérieure à la date/heure de fin.")
    else:
        duration = dt_end - dt_start
        base_params = {"d1": dt_start, "d2": dt_end}
        st.markdown(
            f"<p style='color:{COLORS['text_muted']};font-size:12.5px;margin:-4px 0 12px;'>"
            f"Durée sélectionnée : <b style='color:{COLORS['text']}'>{duration}</b> "
            f"({dt_start:%d/%m/%Y %H:%M} → {dt_end:%d/%m/%Y %H:%M})</p>",
            unsafe_allow_html=True,
        )

        # ---- KPI globaux (agrégés en SQL — jamais de données brutes chargées ici) ----
        kpi_p = run_query("""
            SELECT COUNT(*) AS total, COUNT(DISTINCT h.id_acte) AS actes,
                   COUNT(DISTINCT h.id_user) AS agents, SUM(h.id_user IS NULL) AS non_attribue
            FROM webman_tmp.tr_hist_change h
            WHERE h.date_modif_acte BETWEEN :d1 AND :d2
        """, params=base_params).iloc[0]
        total_n = int(kpi_p["total"])

        if total_n == 0:
            st.info("Aucune modification enregistrée sur cette période précise.")
        else:
            nb_actes, nb_agents = int(kpi_p["actes"]), int(kpi_p["agents"])
            nb_non_attr = int(kpi_p["non_attribue"])

            k1, k2, k3, k4 = st.columns(4)
            with k1:
                st.markdown(kpi_card("Modifications", f"{total_n:,}".replace(",", " "), "", "", [], COLORS["blue"]), unsafe_allow_html=True)
            with k2:
                st.markdown(kpi_card("Actes concernés", f"{nb_actes:,}".replace(",", " "), "", "", [], COLORS["purple"]), unsafe_allow_html=True)
            with k3:
                st.markdown(kpi_card("Agents impliqués", f"{nb_agents:,}".replace(",", " "), "", "", [], COLORS["green"]), unsafe_allow_html=True)
            with k4:
                st.markdown(kpi_card("Non attribuées", f"{nb_non_attr:,}".replace(",", " "),
                                      f"{100*safe_div(nb_non_attr, total_n):.0f}% du total",
                                      COLORS["coral"] if nb_non_attr else COLORS["green"], [], COLORS["coral"]),
                            unsafe_allow_html=True)

            if total_n > 200000:
                st.warning(f"⚠️ **{total_n:,}**".replace(",", " ") + " modifications sur cette période : réduisez la "
                           "durée pour des analyses plus fines (les graphiques restent agrégés en base, mais le "
                           "détail ligne par ligne et l'export seront tronqués).")

            # ---- top acte / top agent (agrégés en SQL, LIMIT 1) ----
            top_agent_p = run_query("""
                SELECT u.full_name AS agent, COUNT(*) AS nb
                FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
                WHERE h.date_modif_acte BETWEEN :d1 AND :d2
                GROUP BY u.full_name ORDER BY nb DESC LIMIT 1
            """, params=base_params)
            top_acte_p = run_query("""
                SELECT h.id_acte, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
                WHERE h.date_modif_acte BETWEEN :d1 AND :d2
                GROUP BY h.id_acte ORDER BY nb DESC LIMIT 1
            """, params=base_params)

            st.markdown("<br>", unsafe_allow_html=True)
            if not top_agent_p.empty:
                r = top_agent_p.iloc[0]
                st.markdown(insight_card("👤", f"Agent le plus actif sur la période : <b>{r['agent']}</b> "
                                                f"avec <b>{int(r['nb'])}</b> modification(s).", COLORS["blue"]),
                            unsafe_allow_html=True)
            if not top_acte_p.empty:
                r = top_acte_p.iloc[0]
                st.markdown(insight_card("📄", f"Acte le plus modifié sur la période : <b>#{r['id_acte']}</b> "
                                                f"avec <b>{int(r['nb'])}</b> modification(s).", COLORS["purple"]),
                            unsafe_allow_html=True)

            # ---- frise chronologique — seulement si le volume reste lisible ----
            if total_n <= MAX_TIMELINE_POINTS:
                raw_tl = run_query("""
                    SELECT h.date_modif_acte AS date_modif, h.id_acte, h.col_name, h.type_action,
                           COALESCE(u.full_name, 'Non attribué') AS agent
                    FROM webman_tmp.tr_hist_change h
                    LEFT JOIN webman_users.tr_user u ON h.id_user = u.cin
                    WHERE h.date_modif_acte BETWEEN :d1 AND :d2
                    ORDER BY h.date_modif_acte
                """, params=base_params)
                raw_tl["date_modif"] = pd.to_datetime(raw_tl["date_modif"])
                top_agents_list = raw_tl["agent"].value_counts().head(8).index.tolist()
                raw_tl["agent_aff"] = raw_tl["agent"].where(raw_tl["agent"].isin(top_agents_list), "Autres agents")
                fig_timeline = px.scatter(
                    raw_tl, x="date_modif", y="agent_aff", color="type_action",
                    hover_data={"id_acte": True, "col_name": True, "agent": True, "agent_aff": False, "type_action": False},
                    template=PLOTLY_TEMPLATE, title="Frise chronologique des modifications (survolez un point pour l'acte et l'agent)",
                    color_discrete_map={"UPDATE": COLORS["green"], "DELETE": COLORS["coral"], "INSERT": COLORS["blue"]},
                )
                fig_timeline.update_traces(marker=dict(size=10, opacity=0.85, line=dict(width=0)))
                fig_timeline.update_layout(height=max(320, 34 * raw_tl["agent_aff"].nunique()),
                                            yaxis_title="", xaxis_title="Date et heure", legend_title_text="")
                st.plotly_chart(fig_timeline, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info(f"Frise chronologique masquée : **{total_n:,}**".replace(",", " ") +
                        f" modifications dépassent la limite de lisibilité ({MAX_TIMELINE_POINTS:,}".replace(",", " ") +
                        " points). Réduisez la durée sélectionnée pour l'afficher — le graphique de volume ci-dessous "
                        "reste, lui, disponible quelle que soit la taille.")

            # ---- volume par bucket temporel + répartition agent/action (100% agrégé en SQL) ----
            span_hours = duration.total_seconds() / 3600
            if span_hours <= 48:
                bucket_expr, bucket_label = "DATE_FORMAT(h.date_modif_acte, '%Y-%m-%d %H:00:00')", "heure"
            elif span_hours <= 24 * 60:
                bucket_expr, bucket_label = "DATE(h.date_modif_acte)", "jour"
            else:
                bucket_expr, bucket_label = "DATE(DATE_SUB(h.date_modif_acte, INTERVAL WEEKDAY(h.date_modif_acte) DAY))", "semaine"

            left, right = st.columns([1.4, 1])
            with left:
                vol = run_query(f"""
                    SELECT {bucket_expr} AS bucket, h.type_action, COUNT(*) AS nb
                    FROM webman_tmp.tr_hist_change h
                    WHERE h.date_modif_acte BETWEEN :d1 AND :d2
                    GROUP BY bucket, h.type_action ORDER BY bucket
                """, params=base_params)
                fig_vol = px.bar(vol, x="bucket", y="nb", color="type_action", template=PLOTLY_TEMPLATE,
                                  title=f"Volume de modifications par {bucket_label}",
                                  color_discrete_map={"UPDATE": COLORS["green"], "DELETE": COLORS["coral"], "INSERT": COLORS["blue"]})
                fig_vol.update_layout(height=320, legend_title_text="", xaxis_title="", yaxis_title="Modifications")
                st.plotly_chart(fig_vol, use_container_width=True, config={"displayModeBar": False})

                top_actes_period = run_query("""
                    SELECT h.id_acte, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
                    WHERE h.date_modif_acte BETWEEN :d1 AND :d2
                    GROUP BY h.id_acte ORDER BY nb DESC LIMIT 15
                """, params=base_params)
                fig_actes = px.bar(top_actes_period, x="nb", y="id_acte", orientation="h", template=PLOTLY_TEMPLATE,
                                    title="Actes les plus modifiés sur la période", color_discrete_sequence=[COLORS["purple"]])
                fig_actes.update_layout(height=380, yaxis=dict(type="category", autorange="reversed"),
                                         yaxis_title="", xaxis_title="Modifications")
                st.plotly_chart(fig_actes, use_container_width=True, config={"displayModeBar": False})

            with right:
                agent_action = run_query("""
                    SELECT COALESCE(u.full_name, 'Non attribué') AS agent, h.type_action, COUNT(*) AS nb
                    FROM webman_tmp.tr_hist_change h LEFT JOIN webman_users.tr_user u ON h.id_user = u.cin
                    WHERE h.date_modif_acte BETWEEN :d1 AND :d2
                    GROUP BY agent, h.type_action
                """, params=base_params)
                agent_totals = agent_action.groupby("agent")["nb"].sum().sort_values(ascending=False)
                top8 = agent_totals.head(8).index.tolist()
                agent_action["agent_aff"] = agent_action["agent"].where(agent_action["agent"].isin(top8), "Autres agents")
                sb = agent_action.groupby(["agent_aff", "type_action"])["nb"].sum().reset_index()
                order_aff = sb.groupby("agent_aff")["nb"].sum().sort_values().index.tolist()
                fig_sb = px.bar(sb, x="nb", y="agent_aff", color="type_action", orientation="h", barmode="stack",
                                 template=PLOTLY_TEMPLATE, title="Agent → type d'action (top 8 + reste)",
                                 category_orders={"agent_aff": order_aff},
                                 color_discrete_map={"UPDATE": COLORS["green"], "DELETE": COLORS["coral"], "INSERT": COLORS["blue"]})
                fig_sb.update_layout(height=340, yaxis_title="", xaxis_title="Modifications", legend_title_text="")
                st.plotly_chart(fig_sb, use_container_width=True, config={"displayModeBar": False})

                top_agents_bar = (agent_totals[agent_totals.index != "Non attribué"].head(10)
                                   .reset_index().rename(columns={"nb": "nb", "agent": "agent"}))
                fig_ta = px.bar(top_agents_bar.sort_values("nb"), x="nb", y="agent", orientation="h",
                                 template=PLOTLY_TEMPLATE, title="Agents les plus actifs sur la période",
                                 color_discrete_sequence=[COLORS["blue"]])
                fig_ta.update_layout(height=360, yaxis_title="", xaxis_title="Modifications")
                st.plotly_chart(fig_ta, use_container_width=True, config={"displayModeBar": False})

            # ---- détail : id_acte + nom des agents (filtres poussés en SQL, résultat plafonné) ----
            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("### 📋 Détail des modifications — actes et agents")

            agent_opts = run_query("""
                SELECT DISTINCT COALESCE(u.full_name, 'Non attribué') AS agent
                FROM webman_tmp.tr_hist_change h LEFT JOIN webman_users.tr_user u ON h.id_user = u.cin
                WHERE h.date_modif_acte BETWEEN :d1 AND :d2 ORDER BY agent
            """, params=base_params)["agent"].tolist()

            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                filt_agent = st.multiselect("Filtrer par agent", agent_opts)
            with fc2:
                filt_action = st.multiselect("Filtrer par type d'action", ["INSERT", "UPDATE", "DELETE"])
            with fc3:
                filt_acte = st.text_input("Filtrer par id_acte", placeholder="ex: 402317")

            extra_conds, extra_params = [], dict(base_params)
            if filt_agent:
                sub_conds = []
                if "Non attribué" in filt_agent:
                    sub_conds.append("h.id_user IS NULL")
                names = [a for a in filt_agent if a != "Non attribué"]
                for i, name in enumerate(names):
                    key = f"fa{i}"
                    sub_conds.append(f"u.full_name = :{key}")
                    extra_params[key] = name
                extra_conds.append("(" + " OR ".join(sub_conds) + ")")
            if filt_action:
                for i, act in enumerate(filt_action):
                    extra_params[f"fac{i}"] = act
                extra_conds.append("h.type_action IN (" + ", ".join(f":fac{i}" for i in range(len(filt_action))) + ")")
            if filt_acte and filt_acte.strip().isdigit():
                extra_conds.append("h.id_acte = :facte")
                extra_params["facte"] = int(filt_acte.strip())
            extra_where = (" AND " + " AND ".join(extra_conds)) if extra_conds else ""

            count_filtered = run_query(f"""
                SELECT COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
                LEFT JOIN webman_users.tr_user u ON h.id_user = u.cin
                WHERE h.date_modif_acte BETWEEN :d1 AND :d2 {extra_where}
            """, params=extra_params).iloc[0]["nb"]

            display_table = run_query(f"""
                SELECT h.date_modif_acte AS "Date et heure", h.id_acte AS "Acte",
                       COALESCE(u.full_name, 'Non attribué') AS "Agent",
                       h.type_action AS "Action", h.col_name AS "Champ"
                FROM webman_tmp.tr_hist_change h
                LEFT JOIN webman_users.tr_user u ON h.id_user = u.cin
                WHERE h.date_modif_acte BETWEEN :d1 AND :d2 {extra_where}
                ORDER BY h.date_modif_acte DESC LIMIT {MAX_TABLE_ROWS}
            """, params=extra_params)

            st.dataframe(display_table, use_container_width=True, hide_index=True)
            st.caption(f"{int(count_filtered):,}".replace(",", " ") + " ligne(s) correspondant aux filtres — "
                       f"affichage limité aux {MAX_TABLE_ROWS} plus récentes. Utilisez les filtres ci-dessus ou "
                       "l'export Excel pour un jeu plus large.")

            # ---- export Excel : calculé UNIQUEMENT sur clic, plus à chaque rendu de l'onglet ----
            # Avant : la requête (jusqu'à MAX_EXPORT_ROWS lignes) + la construction du classeur openpyxl
            # s'exécutaient à CHAQUE affichage de cet onglet (donc à chaque clic sur un filtre), même si
            # personne ne cliquait sur "Télécharger". C'était la dépense la plus coûteuse et la plus
            # inutile de la page la plupart du temps. Elle ne s'exécute désormais qu'au clic sur le bouton
            # ci-dessous, et le résultat est mis en cache (mêmes filtres -> pas de recalcul).
            if count_filtered == 0:
                st.info("Aucune ligne à exporter avec ces filtres.")
            elif st.button("📥 Préparer l'export Excel du détail", key="prep_export_temporel"):
                with st.spinner("Préparation de l'export…"):
                    xbuf = _build_export_xlsx(extra_where, extra_params, MAX_EXPORT_ROWS)
                if int(count_filtered) > MAX_EXPORT_ROWS:
                    st.caption(f"⚠️ Export plafonné à {MAX_EXPORT_ROWS:,}".replace(",", " ") +
                               f" lignes sur {int(count_filtered):,}".replace(",", " ") +
                               " au total — affinez les filtres pour un export complet.")
                st.download_button("Télécharger le fichier Excel", data=xbuf,
                                    file_name=f"actetrack_periode_{dt_start:%Y%m%d%H%M}_{dt_end:%Y%m%d%H%M}.xlsx",
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    use_container_width=True)

# ==============================================================================
# COMPARER PÉRIODES
# ==============================================================================
elif NAV == "comparer":
    st.caption("Comparez deux périodes côte à côte (ex: avant/après un changement, ce mois vs le mois dernier) "
               "sur les mêmes indicateurs — indépendamment du filtre de période global.")

    cA, cB = st.columns(2)
    with cA:
        st.markdown("**Période A**")
        pa_range = st.date_input("Dates — Période A",
                                  value=(st.session_state["gfilter_start"], st.session_state["gfilter_end"]),
                                  min_value=_bounds["mn"].date(), max_value=_bounds["mx"].date(), key="cmp_a")
    with cB:
        st.markdown("**Période B**")
        _span = st.session_state["gfilter_end"] - st.session_state["gfilter_start"]
        _default_b_end = max(st.session_state["gfilter_start"] - timedelta(days=1), _bounds["mn"].date())
        _default_b_start = max(_default_b_end - _span, _bounds["mn"].date())
        pb_range = st.date_input("Dates — Période B", value=(_default_b_start, _default_b_end),
                                  min_value=_bounds["mn"].date(), max_value=_bounds["mx"].date(), key="cmp_b")

    if not (isinstance(pa_range, tuple) and len(pa_range) == 2 and isinstance(pb_range, tuple) and len(pb_range) == 2):
        st.info("Sélectionnez une date de début et une date de fin pour chacune des deux périodes.")
    else:
        def _period_kpi(d1, d2):
            return run_query("""
                SELECT COUNT(*) AS total, COUNT(DISTINCT id_acte) AS actes, COUNT(DISTINCT id_user) AS agents,
                       SUM(type_action='UPDATE') AS n_update, SUM(type_action='DELETE') AS n_delete,
                       SUM(id_user IS NULL) AS non_attribue
                FROM webman_tmp.tr_hist_change WHERE date_modif_acte BETWEEN :d1 AND :d2
            """, params={"d1": d1, "d2": d2}).iloc[0]

        ka, kb = _period_kpi(*pa_range), _period_kpi(*pb_range)
        total_a, total_b = int(ka["total"]) or 1, int(kb["total"]) or 1

        def _fmt(v):
            return f"{v:.1f}%" if isinstance(v, float) else f"{v:,}".replace(",", " ")

        rows = [
            ("Total corrections", int(ka["total"]), int(kb["total"])),
            ("Actes concernés", int(ka["actes"]), int(kb["actes"])),
            ("Agents impliqués", int(ka["agents"]), int(kb["agents"])),
            ("% UPDATE", round(100 * safe_div(ka["n_update"], total_a), 1), round(100 * safe_div(kb["n_update"], total_b), 1)),
            ("% DELETE", round(100 * safe_div(ka["n_delete"], total_a), 1), round(100 * safe_div(kb["n_delete"], total_b), 1)),
            ("% non attribué", round(100 * safe_div(ka["non_attribue"], total_a), 1), round(100 * safe_div(kb["non_attribue"], total_b), 1)),
        ]

        for chunk_start in (0, 3):
            cols = st.columns(3)
            for col, (label, va, vb) in zip(cols, rows[chunk_start:chunk_start + 3]):
                with col:
                    dp = None if vb == 0 else 100 * (va - vb) / vb
                    delta_txt = f"{dp:+.0f}% vs période B" if dp is not None else ""
                    worsened = dp is not None and dp > 0 and label in ("% DELETE", "% non attribué")
                    delta_color = COLORS["coral"] if worsened else (COLORS["green"] if dp and dp > 0 else COLORS["text_muted"])
                    st.markdown(kpi_card(label, _fmt(va), delta_txt, delta_color, [vb, va],
                                          COLORS["blue"]), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        daily_a = run_query("""
            SELECT DATE(date_modif_acte) AS jour, COUNT(*) AS nb FROM webman_tmp.tr_hist_change
            WHERE date_modif_acte BETWEEN :d1 AND :d2 GROUP BY jour ORDER BY jour
        """, params={"d1": pa_range[0], "d2": pa_range[1]})
        daily_b = run_query("""
            SELECT DATE(date_modif_acte) AS jour, COUNT(*) AS nb FROM webman_tmp.tr_hist_change
            WHERE date_modif_acte BETWEEN :d1 AND :d2 GROUP BY jour ORDER BY jour
        """, params={"d1": pb_range[0], "d2": pb_range[1]})
        if not daily_a.empty and not daily_b.empty:
            daily_a = daily_a.reset_index(drop=True); daily_a["jour_rel"] = range(len(daily_a))
            daily_b = daily_b.reset_index(drop=True); daily_b["jour_rel"] = range(len(daily_b))
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=daily_b["jour_rel"], y=daily_b["nb"], mode="lines", name="Période B",
                                      line=dict(color=COLORS["text_muted"], width=2)))
            fig.add_trace(go.Scatter(x=daily_a["jour_rel"], y=daily_a["nb"], mode="lines", name="Période A",
                                      line=dict(color=COLORS["blue"], width=2)))
            fig.update_layout(template=PLOTLY_TEMPLATE, height=320, legend_title_text="",
                               title="Volume quotidien — jour 1, 2, 3… de chaque période (alignement relatif)",
                               xaxis_title="Jour depuis le début de la période", yaxis_title="Corrections")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        left_c, right_c = st.columns(2)
        with left_c:
            champs_a = run_query("""
                SELECT col_name, COUNT(*) AS nb FROM webman_tmp.tr_hist_change
                WHERE date_modif_acte BETWEEN :d1 AND :d2 GROUP BY col_name ORDER BY nb DESC LIMIT 8
            """, params={"d1": pa_range[0], "d2": pa_range[1]})
            if not champs_a.empty:
                fig_ca = px.bar(champs_a.sort_values("nb"), x="nb", y="col_name", orientation="h",
                                 template=PLOTLY_TEMPLATE, title="Top champs — Période A",
                                 color_discrete_sequence=[COLORS["blue"]])
                fig_ca.update_layout(height=300, yaxis_title="", xaxis_title="Corrections")
                st.plotly_chart(fig_ca, use_container_width=True, config={"displayModeBar": False})
        with right_c:
            champs_b = run_query("""
                SELECT col_name, COUNT(*) AS nb FROM webman_tmp.tr_hist_change
                WHERE date_modif_acte BETWEEN :d1 AND :d2 GROUP BY col_name ORDER BY nb DESC LIMIT 8
            """, params={"d1": pb_range[0], "d2": pb_range[1]})
            if not champs_b.empty:
                fig_cb = px.bar(champs_b.sort_values("nb"), x="nb", y="col_name", orientation="h",
                                 template=PLOTLY_TEMPLATE, title="Top champs — Période B",
                                 color_discrete_sequence=[COLORS["text_muted"]])
                fig_cb.update_layout(height=300, yaxis_title="", xaxis_title="Corrections")
                st.plotly_chart(fig_cb, use_container_width=True, config={"displayModeBar": False})

# ==============================================================================
# PAR CHAMP
# ==============================================================================
elif NAV == "champ":
    where_h, gp = gfilter_where("h")
    col_left, col_right = st.columns([1, 1])
    with col_left:
        top_champs = run_query(f"""
            SELECT col_name, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h WHERE {where_h}
            GROUP BY col_name ORDER BY nb DESC LIMIT 20
        """, params=gp)
        fig = px.bar(top_champs.sort_values("nb"), x="nb", y="col_name", orientation="h",
                     template=PLOTLY_TEMPLATE, title="Top 20 champs les plus corrigés",
                     color_discrete_sequence=[COLORS["blue"]])
        fig.update_layout(height=430, yaxis_title="", xaxis_title="Corrections")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
    with col_right:
        cross = run_query(f"""
            SELECT type_action, col_name, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
            WHERE {where_h} AND col_name IN (SELECT col_name FROM (
                SELECT col_name, COUNT(*) c FROM webman_tmp.tr_hist_change
                GROUP BY col_name ORDER BY c DESC LIMIT 10) t)
            GROUP BY type_action, col_name
        """, params=gp)
        if not cross.empty:
            fig = px.bar(cross, x="nb", y="col_name", color="type_action", orientation="h",
                         template=PLOTLY_TEMPLATE, title="Type d'action par champ (top 10)", barmode="stack",
                         color_discrete_map={"UPDATE": COLORS["green"], "DELETE": COLORS["coral"], "INSERT": COLORS["blue"]})
            fig.update_layout(height=430, yaxis_title="", xaxis_title="Nombre de corrections",
                               yaxis=dict(categoryorder="total ascending"), legend_title_text="")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<br>", unsafe_allow_html=True)
    col_left2, col_right2 = st.columns([1.3, 1])
    with col_left2:
        top6_names = top_champs.head(6)["col_name"].tolist() if not top_champs.empty else []
        if top6_names:
            ph_c = ", ".join(f":c{i}" for i in range(len(top6_names)))
            evo_params = {**gp, **{f"c{i}": n for i, n in enumerate(top6_names)}}
            evo_champs = run_query(f"""
                SELECT DATE_FORMAT(h.date_modif_acte, '%Y-%m') AS mois, h.col_name, COUNT(*) AS nb
                FROM webman_tmp.tr_hist_change h WHERE {where_h} AND h.col_name IN ({ph_c})
                GROUP BY mois, h.col_name ORDER BY mois
            """, params=evo_params)
            if not evo_champs.empty:
                fig_evo = px.line(evo_champs, x="mois", y="nb", color="col_name", markers=True,
                                   template=PLOTLY_TEMPLATE, color_discrete_sequence=SEQ,
                                   title="Évolution mensuelle des 6 champs les plus corrigés")
                fig_evo.update_layout(height=340, xaxis_title="", yaxis_title="Corrections", legend_title_text="")
                st.plotly_chart(fig_evo, use_container_width=True, config={"displayModeBar": False})
    with col_right2:
        rate_champ = run_query(f"""
            SELECT h.col_name AS champ, 100*AVG(h.type_action='DELETE') AS pct_delete, COUNT(*) AS nb
            FROM webman_tmp.tr_hist_change h WHERE {where_h}
            GROUP BY champ HAVING COUNT(*) >= 5 ORDER BY pct_delete DESC LIMIT 12
        """, params=gp)
        if not rate_champ.empty:
            fig_rate = px.bar(rate_champ.sort_values("pct_delete"), x="pct_delete", y="champ", orientation="h",
                               template=PLOTLY_TEMPLATE, title="Taux de suppression (DELETE) par champ",
                               color_discrete_sequence=[COLORS["coral"]])
            fig_rate.update_layout(height=340, yaxis_title="", xaxis_title="% DELETE")
            st.plotly_chart(fig_rate, use_container_width=True, config={"displayModeBar": False})

# ==============================================================================
# MOTIFS DE CORRECTION
# ==============================================================================
elif NAV == "motifs":
    where_h, gp = gfilter_where("h")
    st.caption("Regroupe les corrections par champ et par couple valeur avant → valeur après, pour repérer les "
               "erreurs de saisie récurrentes et les motifs systématiques — utile pour trouver la cause d'un "
               "problème, pas seulement son volume.")

    min_occ = st.number_input("Occurrences minimum", min_value=2, max_value=100, value=3, step=1)

    patterns = run_query(f"""
        SELECT h.col_name AS "Champ", h.old_value AS "Valeur avant", h.new_value AS "Valeur après",
               COUNT(*) AS "Occurrences"
        FROM webman_tmp.tr_hist_change h
        WHERE {where_h} AND h.type_action = 'UPDATE' AND h.old_value IS NOT NULL AND h.new_value IS NOT NULL
              AND h.old_value <> h.new_value
        GROUP BY h.col_name, h.old_value, h.new_value
        HAVING COUNT(*) >= :min_occ
        ORDER BY COUNT(*) DESC LIMIT 50
    """, params={**gp, "min_occ": int(min_occ)})

    if patterns.empty:
        st.info("Aucun motif de correction récurrent trouvé avec ce seuil sur cette période/équipe. "
                "Essayez de réduire le nombre d'occurrences minimum.")
    else:
        field_summary = (patterns.groupby("Champ")
                          .agg(**{"Motifs distincts": ("Occurrences", "count"), "Occurrences totales": ("Occurrences", "sum")})
                          .reset_index().sort_values("Occurrences totales", ascending=False))
        st.markdown("**Résumé par champ** — combien de motifs récurrents distincts par champ, et leur poids total")
        st.dataframe(field_summary, use_container_width=True, hide_index=True)

        st.markdown("<br>", unsafe_allow_html=True)
        left, right = st.columns([1.3, 1])
        with left:
            st.markdown("**Motifs de correction les plus fréquents** (détail champ + valeur avant → valeur après)")
            st.dataframe(patterns, use_container_width=True, hide_index=True)
        with right:
            by_field = run_query(f"""
                SELECT h.col_name AS champ, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
                WHERE {where_h} AND h.type_action = 'UPDATE' AND h.old_value <> h.new_value
                GROUP BY h.col_name ORDER BY nb DESC LIMIT 12
            """, params=gp)
            fig = px.bar(by_field, x="nb", y="champ", orientation="h", template=PLOTLY_TEMPLATE,
                         title="Volume de corrections effectives par champ", color_discrete_sequence=[COLORS["purple"]])
            fig.update_layout(height=430, yaxis=dict(categoryorder="total ascending"), yaxis_title="", xaxis_title="Corrections")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        st.markdown("<br>", unsafe_allow_html=True)
        top_pattern = patterns.iloc[0]
        st.markdown(insight_card("🧩", f"Motif le plus fréquent — champ <b>{top_pattern['Champ']}</b> : la valeur "
                                        f"« {top_pattern['Valeur avant']} » corrigée en « {top_pattern['Valeur après']} » "
                                        f"est apparue <b>{int(top_pattern['Occurrences'])}</b> fois. Si ce motif touche "
                                        f"plusieurs agents, la cause est probablement en amont (saisie, formulaire) "
                                        f"plutôt que côté agent.", COLORS["purple"]), unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("**Flux de correction (Sankey)** — transitions valeur avant → valeur après pour un champ donné")
        champ_choices = sorted(patterns["Champ"].unique())
        sankey_champ = st.selectbox("Champ à visualiser", champ_choices, key="motifs_sankey_champ")
        sankey_data = (patterns[patterns["Champ"] == sankey_champ]
                       .sort_values("Occurrences", ascending=False).head(20))
        if not sankey_data.empty:
            avant_labels = [f"{v}  (avant)" for v in sankey_data["Valeur avant"]]
            apres_labels = [f"{v}  (après)" for v in sankey_data["Valeur après"]]
            all_labels = list(dict.fromkeys(avant_labels + apres_labels))
            label_idx = {lbl: i for i, lbl in enumerate(all_labels)}
            fig_sankey = go.Figure(go.Sankey(
                arrangement="snap",
                node=dict(label=all_labels, pad=14, thickness=16, color=COLORS["blue"],
                          line=dict(color=COLORS["border"], width=0.5)),
                link=dict(source=[label_idx[a] for a in avant_labels],
                          target=[label_idx[b] for b in apres_labels],
                          value=sankey_data["Occurrences"].tolist(),
                          color="rgba(79,168,255,0.35)"),
            ))
            fig_sankey.update_layout(template=PLOTLY_TEMPLATE, height=430, font_size=12,
                                      title=f"Transitions de valeurs les plus fréquentes — champ « {sankey_champ} »")
            st.plotly_chart(fig_sankey, use_container_width=True, config={"displayModeBar": False})
            st.caption("Plus le flux est épais, plus la transition valeur avant → valeur après est fréquente. "
                       "Utile pour repérer d'un coup d'œil si les corrections convergent vers une même valeur "
                       "(erreur de saisie corrigée) ou se dispersent (instabilité).")
        else:
            st.caption("Pas assez de motifs pour ce champ avec le seuil actuel.")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**Corrections oscillantes** (un champ revient à une valeur déjà utilisée précédemment)")
    st.caption("Différent des motifs ci-dessus : ici on suit, acte par acte et champ par champ, la séquence complète "
               "des valeurs dans le temps. Un retour à une valeur antérieure (A → B → A) signale souvent un "
               "désaccord entre agents ou une instabilité de saisie — pas seulement une erreur ponctuelle.")
    OSC_ROW_LIMIT = 150000
    total_updates = run_query(
        f"SELECT COUNT(*) AS nb FROM webman_tmp.tr_hist_change h WHERE {where_h} AND h.type_action='UPDATE'",
        params=gp).iloc[0]["nb"]
    if total_updates > OSC_ROW_LIMIT:
        st.info(f"Détection désactivée : {int(total_updates):,} corrections UPDATE sur la période — réduisez "
                 f"la période pour l'activer (limite {OSC_ROW_LIMIT:,}).".replace(",", " "))
    else:
        osc_df = _detect_oscillations(where_h, gp)
        if not osc_df.empty:
            osc_df = osc_df.sort_values("Nb changements", ascending=False).head(20)
            st.dataframe(osc_df, use_container_width=True, hide_index=True)
        else:
            st.caption("Aucune correction oscillante détectée sur cette période/équipe.")

# ==============================================================================
# PAR ACTE
# ==============================================================================
elif NAV == "acte":
    where_h, gp = gfilter_where("h")
    sub_global, sub_top, sub_search = st.tabs(
        ["📊 Vue globale", "🚩 Actes à surveiller", "🔍 Rechercher un acte"]
    )

    # ------------------------------------------------------------------
    # Agrégats par acte (une seule requête, calculée côté MySQL)
    # ------------------------------------------------------------------
    dist = run_query(f"""
        SELECT h.id_acte, COUNT(*) AS nb_corrections,
               COUNT(DISTINCT h.col_name) AS champs,
               COUNT(DISTINCT h.id_user) AS agents,
               SUM(h.type_action='DELETE') AS nb_delete,
               MIN(h.date_modif_acte) AS debut, MAX(h.date_modif_acte) AS fin
        FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY h.id_acte
    """, params=gp)

    if dist.empty:
        st.info("Aucun acte corrigé sur la période sélectionnée.")
    else:
        dist["debut"] = pd.to_datetime(dist["debut"])
        dist["fin"] = pd.to_datetime(dist["fin"])
        dist["duree_jours"] = ((dist["fin"] - dist["debut"]).dt.total_seconds() / 86400).round(2)
        mean, std = dist["nb_corrections"].mean(), dist["nb_corrections"].std(ddof=0)
        seuil = mean + 2 * (std if pd.notna(std) else 0)
        dist["anomalie"] = dist["nb_corrections"] > seuil

        with sub_global:
            tot_actes = len(dist)
            tot_corr = int(dist["nb_corrections"].sum())
            multi = int((dist["agents"] > 1).sum())
            une_seule = int((dist["nb_corrections"] == 1).sum())

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Actes corrigés", f"{tot_actes:,}".replace(",", " "))
            k2.metric("Corrections", f"{tot_corr:,}".replace(",", " "))
            k3.metric("Moyenne / acte", f"{mean:.2f}", f"médiane {dist['nb_corrections'].median():.0f}")
            k4.metric("Actes multi-agents", f"{multi:,}".replace(",", " "),
                      f"{100*multi/tot_actes:.1f} % des actes")
            k5.metric("Actes au-dessus du seuil", int(dist["anomalie"].sum()),
                      f"seuil ≈ {seuil:.1f} corrections", delta_color="inverse")

            st.markdown(insight_card(
                "🧭",
                f"<b>{100*une_seule/tot_actes:.1f}%</b> des actes n'ont été corrigés qu'une seule fois. "
                f"À l'opposé, <b>{int(dist['anomalie'].sum())}</b> acte(s) dépassent le seuil statistique de "
                f"<b>{seuil:.1f}</b> corrections (moyenne + 2 écarts-types) et méritent un contrôle.",
                COLORS["blue"]), unsafe_allow_html=True)

            c1, c2 = st.columns([1.2, 1])
            with c1:
                fig = px.histogram(dist, x="nb_corrections", nbins=40, template=PLOTLY_TEMPLATE,
                                   title="Distribution du nombre de corrections par acte",
                                   color_discrete_sequence=[COLORS["blue"]])
                fig.add_vline(x=seuil, line_dash="dash", line_color=COLORS["coral"],
                              annotation_text="Seuil d'anomalie", annotation_font_color=COLORS["coral"])
                fig.update_layout(height=340, xaxis_title="Corrections par acte", yaxis_title="Nombre d'actes",
                                  bargap=0.05)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            with c2:
                buckets = pd.cut(dist["nb_corrections"], bins=[0, 1, 2, 5, 10, 10**9],
                                 labels=["1", "2", "3-5", "6-10", "> 10"])
                rep = buckets.value_counts().reindex(["1", "2", "3-5", "6-10", "> 10"]).reset_index()
                rep.columns = ["tranche", "nb_actes"]
                fig = px.pie(rep, names="tranche", values="nb_actes", hole=0.6, template=PLOTLY_TEMPLATE,
                             title="Actes par nombre de corrections", color_discrete_sequence=SEQ)
                fig.update_traces(textinfo="percent+label", textfont_size=11)
                fig.update_layout(height=340, showlegend=False)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            c3, c4 = st.columns(2)
            with c3:
                dfp = dist.sort_values("nb_corrections", ascending=False).reset_index(drop=True)
                dfp["cumul"] = 100 * dfp["nb_corrections"].cumsum() / dfp["nb_corrections"].sum()
                dfp["idx"] = range(1, len(dfp) + 1)
                step = max(1, len(dfp) // 400)
                dfs = dfp.iloc[::step]
                fig = go.Figure()
                fig.add_scatter(x=dfs["idx"], y=dfs["cumul"], mode="lines", name="% cumulé des corrections",
                                line=dict(color=COLORS["yellow"], width=2.5), fill="tozeroy",
                                fillcolor="rgba(255,194,79,0.08)")
                fig.add_hline(y=80, line_dash="dot", line_color=COLORS["coral"], annotation_text="80 %")
                fig.update_layout(template=PLOTLY_TEMPLATE, height=330,
                                  title="Concentration : peu d'actes, beaucoup de corrections ?",
                                  xaxis_title="Actes classés du plus corrigé au moins corrigé",
                                  yaxis_title="% cumulé")
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            with c4:
                sample = dist.sample(min(len(dist), 1500), random_state=0)
                fig = px.scatter(sample, x="nb_corrections", y="duree_jours", color="agents",
                                 template=PLOTLY_TEMPLATE,
                                 color_continuous_scale=[COLORS["blue"], COLORS["purple"], COLORS["coral"]],
                                 hover_name="id_acte", title="Corrections vs durée de traitement (couleur = nb d'agents)")
                fig.update_traces(marker=dict(size=8))
                fig.update_layout(height=330, xaxis_title="Corrections", yaxis_title="Durée (jours)",
                                  coloraxis_colorbar=dict(title="Agents", thickness=10))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            evo = run_query(f"""
                SELECT DATE_FORMAT(h.date_modif_acte, '%Y-%m') AS mois,
                       COUNT(DISTINCT h.id_acte) AS actes, COUNT(*) AS corrections
                FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY mois ORDER BY mois
            """, params=gp)
            if not evo.empty:
                evo["corr_par_acte"] = (evo["corrections"] / evo["actes"]).round(2)
                ev1, ev2 = st.columns(2)
                with ev1:
                    fig = px.bar(evo, x="mois", y="actes", template=PLOTLY_TEMPLATE,
                                 title="Actes corrigés par mois", color_discrete_sequence=[COLORS["blue"]])
                    fig.update_layout(height=300, xaxis_title="", yaxis_title="Actes corrigés")
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                with ev2:
                    fig = px.line(evo, x="mois", y="corr_par_acte", markers=True, template=PLOTLY_TEMPLATE,
                                  title="Intensité de correction par mois (corrections / acte)",
                                  color_discrete_sequence=[COLORS["green"]])
                    fig.update_layout(height=300, xaxis_title="", yaxis_title="Corr. / acte")
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            champs_acte = run_query(f"""
                SELECT h.col_name AS champ, h.type_action AS action, COUNT(*) AS nb
                FROM webman_tmp.tr_hist_change h WHERE {where_h}
                GROUP BY champ, action
            """, params=gp)
            if not champs_acte.empty:
                top_c = (champs_acte.groupby("champ")["nb"].sum().sort_values(ascending=False).head(12).index)
                sub_c = champs_acte[champs_acte["champ"].isin(top_c)]
                fig = px.bar(sub_c, x="nb", y="champ", color="action", orientation="h", barmode="stack",
                             template=PLOTLY_TEMPLATE, color_discrete_sequence=SEQ,
                             title="Champs des actes les plus corrigés, par type d'action")
                fig.update_layout(height=380, yaxis={"categoryorder": "total ascending"},
                                  yaxis_title="", xaxis_title="Corrections", legend_title_text="")
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

        # ==================================================================
        # ACTES À SURVEILLER
        # ==================================================================
        with sub_top:
            st.caption("Classement des actes les plus retouchés, avec le détail des signaux : nombre d'agents "
                       "impliqués, champs touchés, suppressions et durée de traitement.")
            f1, f2, f3 = st.columns(3)
            min_corr = f1.slider("Corrections minimum", 1, int(max(2, dist["nb_corrections"].max())), 2)
            only_multi = f2.checkbox("Uniquement les actes touchés par plusieurs agents", value=False)
            only_anom = f3.checkbox("Uniquement les actes au-dessus du seuil", value=False)

            flt = dist[dist["nb_corrections"] >= min_corr]
            if only_multi:
                flt = flt[flt["agents"] > 1]
            if only_anom:
                flt = flt[flt["anomalie"]]
            flt = flt.sort_values("nb_corrections", ascending=False)
            st.caption(f"**{len(flt):,}** acte(s) correspondent à ces critères.".replace(",", " "))

            if not flt.empty:
                t1, t2 = st.columns([1, 1])
                with t1:
                    top15 = flt.head(15).copy()
                    top15["id_acte_txt"] = top15["id_acte"].astype(str)
                    fig = px.bar(top15.iloc[::-1], x="nb_corrections", y="id_acte_txt", orientation="h",
                                 template=PLOTLY_TEMPLATE, title="Top 15 actes les plus corrigés",
                                 color="agents", color_continuous_scale=[COLORS["blue"], COLORS["coral"]],
                                 hover_data={"champs": True, "duree_jours": True})
                    fig.update_layout(height=430, yaxis_title="Acte", xaxis_title="Corrections",
                                      coloraxis_colorbar=dict(title="Agents", thickness=10))
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                with t2:
                    top15 = flt.head(15).copy()
                    top15["id_acte_txt"] = top15["id_acte"].astype(str)
                    fig = px.bar(top15.iloc[::-1], x="duree_jours", y="id_acte_txt", orientation="h",
                                 template=PLOTLY_TEMPLATE, title="Durée de traitement de ces mêmes actes",
                                 color_discrete_sequence=[COLORS["purple"]])
                    fig.update_layout(height=430, yaxis_title="", xaxis_title="Jours entre 1ère et dernière correction")
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                show = flt.head(500)[["id_acte", "nb_corrections", "agents", "champs", "nb_delete",
                                      "duree_jours", "debut", "fin", "anomalie"]]
                st.dataframe(show, use_container_width=True, hide_index=True, height=400,
                             column_config={
                                 "id_acte": st.column_config.NumberColumn("Acte", format="%d"),
                                 "nb_corrections": st.column_config.ProgressColumn(
                                     "Corrections", format="%d", min_value=0,
                                     max_value=int(flt["nb_corrections"].max())),
                                 "agents": "Agents", "champs": "Champs",
                                 "nb_delete": "Suppressions",
                                 "duree_jours": st.column_config.NumberColumn("Durée (j)", format="%.2f"),
                                 "debut": st.column_config.DatetimeColumn("Première", format="DD/MM/YYYY HH:mm"),
                                 "fin": st.column_config.DatetimeColumn("Dernière", format="DD/MM/YYYY HH:mm"),
                                 "anomalie": st.column_config.CheckboxColumn("Au-dessus du seuil"),
                             })
                st.download_button("⬇️ Exporter la sélection (CSV)",
                                   data=flt.to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"actetrack_actes_{datetime.now().strftime('%Y%m%d')}.csv",
                                   mime="text/csv", use_container_width=True)

        # ==================================================================
        # RECHERCHE D'UN ACTE
        # ==================================================================
        with sub_search:
            with st.form("recherche_acte_form"):
                id_acte_input = st.text_input("Entrez un id_acte", value=st.session_state["acte_prefill"],
                                              placeholder="ex: 402317")
                acte_submitted = st.form_submit_button("Rechercher")
            if st.session_state["acte_prefill"]:
                id_acte_input = st.session_state["acte_prefill"]
                acte_submitted = True
                st.session_state["acte_prefill"] = ""

            if acte_submitted and id_acte_input:
                detail = run_query("""
                    SELECT h.date_modif_acte, h.col_name, h.type_action, h.old_value, h.new_value,
                           COALESCE(u.full_name, 'Non identifié') AS full_name
                    FROM webman_tmp.tr_hist_change h
                    LEFT JOIN webman_users.tr_user u ON h.id_user = u.cin
                    WHERE h.id_acte = :id_acte ORDER BY h.date_modif_acte
                """, params={"id_acte": int(id_acte_input)}) if str(id_acte_input).isdigit() else pd.DataFrame()

                if detail.empty:
                    st.warning("Aucune correction trouvée pour cet id_acte.")
                else:
                    detail["date_modif_acte"] = pd.to_datetime(detail["date_modif_acte"])
                    duree = (detail["date_modif_acte"].max() - detail["date_modif_acte"].min())
                    m1, m2, m3, m4, m5 = st.columns(5)
                    m1.metric("Corrections", len(detail))
                    m2.metric("Agents impliqués", detail["full_name"].nunique())
                    m3.metric("Champs touchés", detail["col_name"].nunique())
                    m4.metric("Durée de traitement", f"{duree.days} j",
                              f"{duree.seconds // 3600} h supplémentaires")
                    m5.metric("Suppressions", int((detail["type_action"] == "DELETE").sum()),
                              delta_color="inverse")

                    rang = dist[dist["id_acte"] == int(id_acte_input)]
                    if not rang.empty and rang.iloc[0]["anomalie"]:
                        st.markdown(insight_card("⚠️", f"Cet acte dépasse le seuil statistique de "
                                                       f"<b>{seuil:.1f}</b> corrections : il fait partie des actes "
                                                       f"les plus retouchés de la période.", COLORS["coral"]),
                                    unsafe_allow_html=True)

                    fig = px.scatter(detail, x="date_modif_acte", y="col_name", color="full_name",
                                     symbol="type_action", template=PLOTLY_TEMPLATE,
                                     color_discrete_sequence=SEQ,
                                     title="Chronologie des corrections de l'acte",
                                     hover_data={"old_value": True, "new_value": True})
                    fig.update_traces(marker=dict(size=11, line=dict(width=1, color=COLORS["border"])))
                    fig.update_layout(height=380, xaxis_title="", yaxis_title="Champ", legend_title_text="")
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                    d1, d2 = st.columns(2)
                    with d1:
                        par_champ = detail["col_name"].value_counts().reset_index()
                        par_champ.columns = ["champ", "nb"]
                        fig = px.bar(par_champ.iloc[::-1], x="nb", y="champ", orientation="h",
                                     template=PLOTLY_TEMPLATE, title="Corrections par champ",
                                     color_discrete_sequence=[COLORS["blue"]])
                        fig.update_layout(height=320, yaxis_title="", xaxis_title="Corrections")
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                    with d2:
                        par_agent = detail["full_name"].value_counts().reset_index()
                        par_agent.columns = ["agent", "nb"]
                        fig = px.pie(par_agent, names="agent", values="nb", hole=0.6,
                                     template=PLOTLY_TEMPLATE, title="Répartition par agent",
                                     color_discrete_sequence=SEQ)
                        fig.update_traces(textinfo="percent", textfont_size=11)
                        fig.update_layout(height=320)
                        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                    st.dataframe(detail, use_container_width=True, hide_index=True, height=340)
                    st.download_button("⬇️ Exporter l'historique de l'acte (CSV)",
                                       data=detail.to_csv(index=False).encode("utf-8-sig"),
                                       file_name=f"actetrack_acte_{id_acte_input}.csv",
                                       mime="text/csv", use_container_width=True)
# ==============================================================================
# DÉLAIS DE RÉSOLUTION
# ==============================================================================
elif NAV == "delais":
    where_h, gp = gfilter_where("h")
    st.caption("Temps écoulé entre la première et la dernière correction enregistrée pour un même acte — un délai "
               "long peut signaler un acte complexe, un désaccord entre agents, ou un traitement qui traîne.")

    DELAI_ROW_LIMIT = 100000
    total_rows_delai = run_query(f"SELECT COUNT(*) AS nb FROM webman_tmp.tr_hist_change h WHERE {where_h}",
                                  params=gp).iloc[0]["nb"]
    if total_rows_delai > DELAI_ROW_LIMIT:
        st.info(f"Calcul désactivé : {int(total_rows_delai):,} lignes sur la période — réduisez la période pour "
                f"l'activer (limite {DELAI_ROW_LIMIT:,}).".replace(",", " "))
    else:
        span = run_query(f"""
            SELECT h.id_acte, MIN(h.date_modif_acte) AS premiere, MAX(h.date_modif_acte) AS derniere,
                   COUNT(*) AS nb_corrections
            FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY h.id_acte HAVING COUNT(*) >= 2
        """, params=gp)

        if span.empty:
            st.info("Aucun acte avec au moins deux corrections sur cette période — pas de délai à mesurer.")
        else:
            span["premiere"] = pd.to_datetime(span["premiere"])
            span["derniere"] = pd.to_datetime(span["derniere"])
            span["delai_j"] = (span["derniere"] - span["premiere"]).dt.total_seconds() / 86400

            c1, c2, c3 = st.columns(3)
            with c1:
                st.markdown(kpi_card("Délai médian", f"{span['delai_j'].median():.1f} j", "", "",
                                      [span['delai_j'].median()] * 2, COLORS["blue"]), unsafe_allow_html=True)
            with c2:
                st.markdown(kpi_card("Délai moyen", f"{span['delai_j'].mean():.1f} j", "", "",
                                      [span['delai_j'].mean()] * 2, COLORS["purple"]), unsafe_allow_html=True)
            with c3:
                lents = int((span["delai_j"] > span["delai_j"].quantile(0.9)).sum()) if len(span) >= 10 else 0
                st.markdown(kpi_card("Actes lents (> P90)", f"{lents:,}".replace(",", " "), "", "",
                                      [lents] * 2, COLORS["coral"]), unsafe_allow_html=True)

            st.markdown("<br>", unsafe_allow_html=True)
            left, right = st.columns([1.3, 1])
            with left:
                cap = span["delai_j"].quantile(0.98) if len(span) >= 10 else span["delai_j"].max()
                fig = px.histogram(span[span["delai_j"] <= cap], x="delai_j", nbins=30, template=PLOTLY_TEMPLATE,
                                    title="Distribution du délai de résolution (jours, 98e percentile exclu)",
                                    color_discrete_sequence=[COLORS["blue"]])
                fig.update_layout(height=340, xaxis_title="Jours entre 1ère et dernière correction",
                                   yaxis_title="Nombre d'actes")
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            with right:
                top_lents = span.sort_values("delai_j", ascending=False).head(15)[["id_acte", "nb_corrections", "delai_j"]].copy()
                top_lents.columns = ["Acte", "Corrections", "Délai (j)"]
                top_lents["Délai (j)"] = top_lents["Délai (j)"].round(1)
                st.markdown("**Actes les plus lents à se stabiliser**")
                st.dataframe(top_lents, use_container_width=True, hide_index=True)

            st.markdown("<br>", unsafe_allow_html=True)
            st.markdown("**Chronologie des actes les plus lents** (Gantt — de la 1ère à la dernière correction)")
            gantt_df = span.sort_values("delai_j", ascending=False).head(15).copy()
            gantt_df["Acte"] = gantt_df["id_acte"].astype(str)
            fig_gantt = px.timeline(gantt_df, x_start="premiere", x_end="derniere", y="Acte", color="delai_j",
                                     template=PLOTLY_TEMPLATE, title="Durée d'ouverture des 15 actes les plus lents",
                                     color_continuous_scale=[COLORS["blue"], COLORS["yellow"], COLORS["coral"]])
            fig_gantt.update_yaxes(categoryorder="total ascending", title="")
            fig_gantt.update_layout(height=430, xaxis_title="", coloraxis_colorbar=dict(title="Jours", thickness=10))
            st.plotly_chart(fig_gantt, use_container_width=True, config={"displayModeBar": False})
            st.caption("Chaque barre va de la première à la dernière correction enregistrée sur l'acte — une barre "
                       "longue signale un acte resté « ouvert » longtemps, pas forcément un volume élevé.")

            st.markdown("<br>", unsafe_allow_html=True)
            by_field = run_query(f"""
                SELECT h.id_acte, h.col_name, MIN(h.date_modif_acte) AS premiere, MAX(h.date_modif_acte) AS derniere
                FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY h.id_acte, h.col_name HAVING COUNT(*) >= 2
            """, params=gp)
            if not by_field.empty:
                by_field["premiere"] = pd.to_datetime(by_field["premiere"])
                by_field["derniere"] = pd.to_datetime(by_field["derniere"])
                by_field["delai_j"] = (by_field["derniere"] - by_field["premiere"]).dt.total_seconds() / 86400
                med_by_field = (by_field.groupby("col_name")["delai_j"].median()
                                 .sort_values(ascending=False).head(12).reset_index())
                fig2 = px.bar(med_by_field, x="delai_j", y="col_name", orientation="h", template=PLOTLY_TEMPLATE,
                              title="Délai médian de résolution par champ", color_discrete_sequence=[COLORS["yellow"]])
                fig2.update_layout(height=380, yaxis_title="", xaxis_title="Délai médian (jours)",
                                    yaxis=dict(categoryorder="total ascending"))
                st.plotly_chart(fig2, use_container_width=True, config={"displayModeBar": False})
            else:
                st.caption("Pas assez de données pour détailler le délai par champ.")

# ==============================================================================
# AGENT
# ==============================================================================
elif NAV == "agent":
    where_h, gp = gfilter_where("h")

    # ------------------------------------------------------------------
    # Données agrégées en SQL (rapide, mis en cache) — plus de chargement
    # de toutes les lignes brutes côté Python.
    # ------------------------------------------------------------------
    agents_overview = run_query(f"""
        SELECT u.full_name AS agent, MIN(u.id_user) AS id_user,
               COALESCE(MIN(g.grp_desc), 'Non affecté') AS equipe,
               COUNT(*) AS volume,
               COUNT(DISTINCT h.id_acte) AS actes,
               COUNT(DISTINCT h.col_name) AS champs,
               COUNT(DISTINCT DATE(h.date_modif_acte)) AS jours_actifs,
               100*AVG(h.type_action='UPDATE') AS pct_update,
               100*AVG(h.type_action='DELETE') AS pct_delete,
               100*AVG(HOUR(h.date_modif_acte) < 7 OR HOUR(h.date_modif_acte) >= 20) AS pct_hors,
               MIN(h.date_modif_acte) AS premiere,
               MAX(h.date_modif_acte) AS derniere
        FROM webman_tmp.tr_hist_change h
        JOIN webman_users.tr_user u ON h.id_user = u.cin
        LEFT JOIN webman_users.ta_user_grp ug ON u.id_user = ug.id_user
        LEFT JOIN webman_users.tr_grp g ON ug.id_grp = g.id_grp
        WHERE {where_h}
        GROUP BY u.full_name
    """, params=gp)

    if agents_overview.empty:
        st.info("Aucune activité d'agent sur la période sélectionnée.")
    else:
        agents_overview["corr_par_acte"] = (agents_overview["volume"] / agents_overview["actes"]).round(2)
        agents_overview["corr_par_jour"] = (agents_overview["volume"] / agents_overview["jours_actifs"].replace(0, 1)).round(1)
        agents_overview["part_pct"] = (100 * agents_overview["volume"] / agents_overview["volume"].sum()).round(2)
        agents_overview["rang"] = agents_overview["volume"].rank(ascending=False, method="min").astype(int)
        agents_overview = agents_overview.sort_values("volume", ascending=False)

        tab_all, tab_one, tab_cmp = st.tabs(
            ["👥 Tous les agents", "🪪 Fiche agent", "⚖️ Comparer des agents"]
        )

        # ==================================================================
        # 1) VUE D'ENSEMBLE DE TOUS LES AGENTS
        # ==================================================================
        with tab_all:
            tot_corr = int(agents_overview["volume"].sum())
            nb_agents = len(agents_overview)
            med = float(agents_overview["volume"].median())
            top_row = agents_overview.iloc[0]
            top3_share = round(100 * agents_overview["volume"].head(3).sum() / tot_corr, 1)

            k1, k2, k3, k4, k5 = st.columns(5)
            k1.metric("Agents actifs", f"{nb_agents:,}".replace(",", " "))
            k2.metric("Corrections", f"{tot_corr:,}".replace(",", " "))
            k3.metric("Médiane / agent", f"{med:,.0f}".replace(",", " "))
            k4.metric("Agent le plus actif", top_row["agent"], f"{int(top_row['volume'])} corrections")
            k5.metric("Poids du top 3", f"{top3_share} %", "concentration de l'activité")

            st.markdown(insight_card(
                "🧭",
                f"Les <b>3 agents</b> les plus actifs concentrent <b>{top3_share}%</b> des corrections. "
                f"L'agent médian en réalise <b>{med:,.0f}</b> sur la période, contre <b>{int(top_row['volume'])}</b> "
                f"pour <b>{top_row['agent']}</b>.".replace(",", " "),
                COLORS["blue"]), unsafe_allow_html=True)

            c1, c2 = st.columns([1.15, 1])
            with c1:
                top20 = agents_overview.head(20).iloc[::-1]
                fig = px.bar(top20, x="volume", y="agent", orientation="h", template=PLOTLY_TEMPLATE,
                             title="Top 20 agents — volume de corrections",
                             color="pct_hors", color_continuous_scale=[COLORS["blue"], COLORS["yellow"], COLORS["coral"]],
                             hover_data={"equipe": True, "actes": True, "pct_hors": ":.1f"})
                fig.update_layout(height=560, yaxis_title="", xaxis_title="Corrections",
                                  coloraxis_colorbar=dict(title="% hors<br>horaires", thickness=10))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            with c2:
                fig = px.scatter(agents_overview, x="actes", y="volume", size="champs", color="equipe",
                                 hover_name="agent", template=PLOTLY_TEMPLATE, size_max=34,
                                 title="Étendue (actes touchés) vs intensité (corrections)",
                                 color_discrete_sequence=SEQ)
                fig.update_layout(height=270, xaxis_title="Actes distincts", yaxis_title="Corrections",
                                  legend=dict(font=dict(size=9)), showlegend=False)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                team_vol = agents_overview.groupby("equipe")["volume"].sum().sort_values().reset_index()
                fig = px.bar(team_vol, x="volume", y="equipe", orientation="h", template=PLOTLY_TEMPLATE,
                             title="Volume total de corrections par équipe", color_discrete_sequence=[COLORS["purple"]])
                fig.update_layout(height=280, yaxis_title="", xaxis_title="Corrections")
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            c3, c4 = st.columns(2)
            with c3:
                fig = px.box(agents_overview, x="equipe", y="volume", points="outliers", template=PLOTLY_TEMPLATE,
                             color="equipe", color_discrete_sequence=SEQ, hover_name="agent",
                             title="Dispersion des volumes par équipe")
                fig.update_layout(height=330, showlegend=False, xaxis_title="", yaxis_title="Corrections")
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            with c4:
                dfp = agents_overview.sort_values("volume", ascending=False).copy()
                dfp["cumul"] = 100 * dfp["volume"].cumsum() / dfp["volume"].sum()
                dfp["idx"] = range(1, len(dfp) + 1)
                step = max(1, len(dfp) // 400)
                dfps = dfp.iloc[::step]
                fig = go.Figure()
                fig.add_scatter(x=dfps["idx"], y=dfps["cumul"], mode="lines", name="% cumulé des corrections",
                                line=dict(color=COLORS["yellow"], width=2.5), fill="tozeroy",
                                fillcolor="rgba(255,194,79,0.08)", hovertext=dfps["agent"])
                fig.add_hline(y=80, line_dash="dot", line_color=COLORS["coral"], annotation_text="80 %")
                fig.update_layout(template=PLOTLY_TEMPLATE, height=330, title="Concentration de l'activité (Pareto)",
                                  xaxis_title="Agents classés du plus actif au moins actif", yaxis_title="% cumulé")
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            st.markdown("#### 🗂️ Tableau complet des agents")
            table = agents_overview[["rang", "agent", "equipe", "volume", "part_pct", "actes", "champs",
                                     "jours_actifs", "corr_par_jour", "corr_par_acte", "pct_update",
                                     "pct_delete", "pct_hors", "derniere"]].copy()
            st.dataframe(
                table, use_container_width=True, hide_index=True, height=420,
                column_config={
                    "rang": st.column_config.NumberColumn("#", width="small"),
                    "agent": "Agent", "equipe": "Équipe",
                    "volume": st.column_config.ProgressColumn(
                        "Corrections", format="%d", min_value=0, max_value=int(table["volume"].max())),
                    "part_pct": st.column_config.NumberColumn("Part", format="%.2f %%"),
                    "actes": "Actes", "champs": "Champs", "jours_actifs": "Jours actifs",
                    "corr_par_jour": st.column_config.NumberColumn("Corr./jour", format="%.1f"),
                    "corr_par_acte": st.column_config.NumberColumn("Corr./acte", format="%.2f"),
                    "pct_update": st.column_config.NumberColumn("% UPDATE", format="%.1f %%"),
                    "pct_delete": st.column_config.NumberColumn("% DELETE", format="%.1f %%"),
                    "pct_hors": st.column_config.NumberColumn("% hors horaires", format="%.1f %%"),
                    "derniere": st.column_config.DatetimeColumn("Dernière action", format="DD/MM/YYYY HH:mm"),
                })
            st.download_button("⬇️ Exporter le tableau des agents (CSV)",
                               data=table.to_csv(index=False).encode("utf-8-sig"),
                               file_name=f"actetrack_agents_{datetime.now().strftime('%Y%m%d')}.csv",
                               mime="text/csv", use_container_width=True)

        # ==================================================================
        # 2) FICHE DÉTAILLÉE D'UN AGENT
        # ==================================================================
        with tab_one:
            noms = agents_overview["agent"].tolist()
            default_idx = noms.index(st.session_state["agent_prefill"]) if st.session_state["agent_prefill"] in noms else 0
            st.session_state["agent_prefill"] = ""
            selected_name = st.selectbox("Agent", noms, index=default_idx,
                                         help="Tapez les premières lettres pour filtrer la liste.")

            ar = agents_overview[agents_overview["agent"] == selected_name].iloc[0]
            initials = "".join([p[0] for p in str(selected_name).split()[:2]]).upper()

            # --- séries de l'agent, agrégées en SQL ---
            a_params = {**gp, "agent": selected_name}
            daily_a = run_query(f"""
                SELECT DATE(h.date_modif_acte) AS jour, COUNT(*) AS nb,
                       SUM(h.type_action='DELETE') AS nb_delete
                FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
                WHERE {where_h} AND u.full_name = :agent GROUP BY jour ORDER BY jour
            """, params=a_params)
            heat_a = run_query(f"""
                SELECT WEEKDAY(h.date_modif_acte) AS jsem, HOUR(h.date_modif_acte) AS heure, COUNT(*) AS nb
                FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
                WHERE {where_h} AND u.full_name = :agent GROUP BY jsem, heure
            """, params=a_params)
            champs_a = run_query(f"""
                SELECT h.col_name AS champ, COUNT(*) AS nb
                FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
                WHERE {where_h} AND u.full_name = :agent GROUP BY champ ORDER BY nb DESC LIMIT 12
            """, params=a_params)
            actions_a = run_query(f"""
                SELECT h.type_action AS action, COUNT(*) AS nb
                FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
                WHERE {where_h} AND u.full_name = :agent GROUP BY action
            """, params=a_params)
            actes_a = run_query(f"""
                SELECT h.id_acte, COUNT(*) AS nb, COUNT(DISTINCT h.col_name) AS champs,
                       MIN(h.date_modif_acte) AS debut, MAX(h.date_modif_acte) AS fin
                FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
                WHERE {where_h} AND u.full_name = :agent
                GROUP BY h.id_acte ORDER BY nb DESC LIMIT 15
            """, params=a_params)
            last_a = run_query(f"""
                SELECT h.date_modif_acte, h.id_acte, h.col_name, h.type_action, h.old_value, h.new_value
                FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
                WHERE {where_h} AND u.full_name = :agent
                ORDER BY h.date_modif_acte DESC LIMIT 300
            """, params=a_params)

            # --- entête identité + KPI ---
            head_l, head_r = st.columns([1.1, 2.6])
            with head_l:
                st.markdown(f"""
                    <div class="ct-kpi" style="border-top:3px solid {COLORS['blue']};height:100%;">
                        <div style="display:flex;align-items:center;gap:12px;">
                            <div style="width:48px;height:48px;border-radius:50%;background:{COLORS['blue']};
                                        display:flex;align-items:center;justify-content:center;color:#042C53;
                                        font-weight:600;font-size:16px;">{initials}</div>
                            <div>
                                <p style="color:{COLORS['text']};font-size:15px;font-weight:600;margin:0;">{selected_name}</p>
                                <p style="color:{COLORS['text_muted']};font-size:11px;margin:2px 0 0 0;">
                                    {ar['equipe']} · id {ar['id_user']}</p>
                                <p style="color:{COLORS['text_muted']};font-size:11px;margin:2px 0 0 0;">
                                    Rang #{int(ar['rang'])} sur {nb_agents} agents</p>
                            </div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)
            with head_r:
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Corrections", int(ar["volume"]), f"{ar['part_pct']} % du total")
                m2.metric("Actes touchés", int(ar["actes"]), f"{ar['corr_par_acte']} corr./acte")
                m3.metric("Jours actifs", int(ar["jours_actifs"]), f"{ar['corr_par_jour']} / jour")
                m4.metric("Champs distincts", int(ar["champs"]),
                          f"dernier passage {pd.to_datetime(ar['derniere']).strftime('%d/%m %H:%M')}")

            g1, g2, g3 = st.columns(3)
            with g1:
                st.plotly_chart(gauge_fig(float(ar["pct_update"]), "% UPDATE", COLORS["green"]), use_container_width=True, config={"displayModeBar": False})
            with g2:
                st.plotly_chart(gauge_fig(float(ar["pct_delete"]), "% DELETE", COLORS["coral"]), use_container_width=True, config={"displayModeBar": False})
            with g3:
                st.plotly_chart(gauge_fig(float(ar["pct_hors"]), "% hors horaires", COLORS["yellow"]), use_container_width=True, config={"displayModeBar": False})

            hors_moy = agents_overview["pct_hors"].mean()
            if ar["pct_hors"] > hors_moy * 1.5 and ar["pct_hors"] > 5:
                st.markdown(insight_card("⚠️", f"<b>{selected_name}</b> réalise <b>{ar['pct_hors']:.1f}%</b> de ses "
                                               f"corrections hors horaires ouvrés, contre <b>{hors_moy:.1f}%</b> en "
                                               f"moyenne : à vérifier.", COLORS["coral"]), unsafe_allow_html=True)

            # --- activité dans le temps ---
            if not daily_a.empty:
                daily_a["jour"] = pd.to_datetime(daily_a["jour"])
                daily_a["moyenne_7j"] = daily_a["nb"].rolling(7, min_periods=1).mean().round(1)
                fig = go.Figure()
                fig.add_bar(x=daily_a["jour"], y=daily_a["nb"], name="Corrections/jour",
                            marker_color=COLORS["blue"], opacity=0.6)
                fig.add_scatter(x=daily_a["jour"], y=daily_a["moyenne_7j"], mode="lines", name="Tendance 7 jours",
                                line=dict(color=COLORS["green"], width=2.5))
                fig.update_layout(template=PLOTLY_TEMPLATE, height=330,
                                  title=f"Activité quotidienne de {selected_name}",
                                  yaxis_title="Corrections", xaxis_title="",
                                  legend=dict(orientation="h", y=1.13))
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            b1, b2 = st.columns([1.25, 1])
            with b1:
                if not heat_a.empty:
                    jours_lbl = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"]
                    grid = (heat_a.pivot_table(index="jsem", columns="heure", values="nb", aggfunc="sum")
                            .reindex(index=range(7), columns=range(24)).fillna(0))
                    fig = px.imshow(grid.values, x=[f"{h:02d}h" for h in range(24)], y=jours_lbl,
                                    color_continuous_scale=[COLORS["surface2"], COLORS["blue"], COLORS["green"]],
                                    aspect="auto", template=PLOTLY_TEMPLATE,
                                    title="Rythme de travail — jour de la semaine × heure")
                    fig.update_layout(height=330, coloraxis_colorbar=dict(title="Corr.", thickness=10),
                                      xaxis_title="", yaxis_title="")
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            with b2:
                if not actions_a.empty:
                    fig = px.pie(actions_a, names="action", values="nb", hole=0.62, template=PLOTLY_TEMPLATE,
                                 title="Répartition des types d'action",
                                 color_discrete_sequence=[COLORS["green"], COLORS["coral"], COLORS["purple"], COLORS["blue"]])
                    fig.update_traces(textinfo="percent+label", textfont_size=11)
                    fig.update_layout(height=330, showlegend=False)
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            b3, b4 = st.columns(2)
            with b3:
                if not champs_a.empty:
                    fig = px.bar(champs_a.iloc[::-1], x="nb", y="champ", orientation="h", template=PLOTLY_TEMPLATE,
                                 title="Champs les plus corrigés par l'agent",
                                 color="nb", color_continuous_scale=[COLORS["blue"], COLORS["purple"]])
                    fig.update_layout(height=360, yaxis_title="", xaxis_title="Corrections", coloraxis_showscale=False)
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
            with b4:
                if not actes_a.empty:
                    actes_a["id_acte_txt"] = actes_a["id_acte"].astype(str)
                    fig = px.bar(actes_a.iloc[::-1], x="nb", y="id_acte_txt", orientation="h",
                                 template=PLOTLY_TEMPLATE, title="Actes les plus retouchés par l'agent",
                                 color="champs", color_continuous_scale=[COLORS["yellow"], COLORS["coral"]],
                                 hover_data={"debut": True, "fin": True})
                    fig.update_layout(height=360, yaxis_title="", xaxis_title="Corrections",
                                      coloraxis_colorbar=dict(title="Champs", thickness=10))
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            # --- profil radar vs moyenne ---
            if len(agents_overview) >= 2:
                def _norm(v, series):
                    mx = series.max()
                    return round(100 * v / mx, 1) if mx else 0.0
                axes = ["Volume", "Actes distincts", "Champs distincts", "% hors-horaires", "% UPDATE", "Corr./acte"]
                agent_vals = [_norm(ar["volume"], agents_overview["volume"]),
                              _norm(ar["actes"], agents_overview["actes"]),
                              _norm(ar["champs"], agents_overview["champs"]),
                              round(float(ar["pct_hors"]), 1), round(float(ar["pct_update"]), 1),
                              _norm(ar["corr_par_acte"], agents_overview["corr_par_acte"])]
                avg_vals = [_norm(agents_overview["volume"].mean(), agents_overview["volume"]),
                            _norm(agents_overview["actes"].mean(), agents_overview["actes"]),
                            _norm(agents_overview["champs"].mean(), agents_overview["champs"]),
                            round(agents_overview["pct_hors"].mean(), 1),
                            round(agents_overview["pct_update"].mean(), 1),
                            _norm(agents_overview["corr_par_acte"].mean(), agents_overview["corr_par_acte"])]
                r1, r2 = st.columns([1, 1])
                with r1:
                    fig_radar = go.Figure()
                    fig_radar.add_trace(go.Scatterpolar(r=avg_vals + avg_vals[:1], theta=axes + axes[:1],
                                                        fill="toself", name="Moyenne des agents",
                                                        line=dict(color=COLORS["text_muted"]), opacity=0.55))
                    fig_radar.add_trace(go.Scatterpolar(r=agent_vals + agent_vals[:1], theta=axes + axes[:1],
                                                        fill="toself", name=selected_name,
                                                        line=dict(color=COLORS["blue"])))
                    fig_radar.update_layout(template=PLOTLY_TEMPLATE, height=380, showlegend=True,
                                            title="Profil de l'agent vs moyenne (axes normalisés)",
                                            legend=dict(orientation="h", y=-0.08),
                                            polar=dict(bgcolor=COLORS["surface"],
                                                       radialaxis=dict(visible=True, range=[0, 100],
                                                                       showticklabels=False, gridcolor=COLORS["border"]),
                                                       angularaxis=dict(gridcolor=COLORS["border"])))
                    st.plotly_chart(fig_radar, use_container_width=True, config={"displayModeBar": False})
                with r2:
                    pos = agents_overview.reset_index(drop=True)
                    pos["est_agent"] = pos["agent"] == selected_name
                    fig_pos = px.scatter(pos, x="volume", y="pct_hors", size="actes", color="est_agent",
                                         hover_name="agent", template=PLOTLY_TEMPLATE, size_max=30,
                                         color_discrete_map={True: COLORS["coral"], False: COLORS["surface2"]},
                                         title="Positionnement : volume vs % hors horaires")
                    fig_pos.update_traces(marker=dict(line=dict(width=1, color=COLORS["border"])))
                    fig_pos.update_layout(height=380, showlegend=False, xaxis_title="Corrections",
                                          yaxis_title="% hors horaires")
                    st.plotly_chart(fig_pos, use_container_width=True, config={"displayModeBar": False})

            # --- journal détaillé ---
            with st.expander(f"🧾 Journal des 300 dernières actions de {selected_name}", expanded=False):
                st.dataframe(last_a, use_container_width=True, hide_index=True, height=380)
                st.download_button("⬇️ Exporter le journal (CSV)",
                                   data=last_a.to_csv(index=False).encode("utf-8-sig"),
                                   file_name=f"actetrack_journal_{str(selected_name).replace(' ', '_')}.csv",
                                   mime="text/csv", use_container_width=True)

            # --- fiche PDF ---
            try:
                pdf_a = FPDF()
                pdf_a.add_page()
                nom_pdf = str(selected_name).encode("latin-1", "replace").decode("latin-1")
                pdf_a.set_font("Helvetica", "B", 16)
                pdf_a.cell(0, 10, f"ActeTrack - Fiche agent : {nom_pdf}", ln=True)
                pdf_a.set_font("Helvetica", "", 10)
                pdf_a.cell(0, 8, f"Periode : {st.session_state['gfilter_start']} au {st.session_state['gfilter_end']}", ln=True)
                pdf_a.cell(0, 8, f"Genere le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True)
                pdf_a.ln(4)
                pdf_a.set_font("Helvetica", "B", 12)
                pdf_a.cell(0, 8, "Indicateurs cles", ln=True)
                pdf_a.set_font("Helvetica", "", 10)
                for lbl, val in [("Corrections totales", int(ar["volume"])),
                                 ("Actes distincts", int(ar["actes"])),
                                 ("Champs distincts", int(ar["champs"])),
                                 ("Jours actifs", int(ar["jours_actifs"])),
                                 ("Corrections / jour", ar["corr_par_jour"]),
                                 ("% UPDATE", f"{ar['pct_update']:.1f}%"),
                                 ("% DELETE", f"{ar['pct_delete']:.1f}%"),
                                 ("% hors horaires", f"{ar['pct_hors']:.1f}%"),
                                 ("Rang par volume", f"{int(ar['rang'])} / {nb_agents}")]:
                    pdf_a.cell(0, 7, f"- {lbl} : {val}", ln=True)
                pdf_a.ln(4)
                pdf_a.set_font("Helvetica", "B", 12)
                pdf_a.cell(0, 8, "Champs les plus corriges", ln=True)
                pdf_a.set_font("Helvetica", "", 10)
                for _, rowc in champs_a.head(10).iterrows():
                    champ_txt = str(rowc["champ"]).encode("latin-1", "replace").decode("latin-1")
                    pdf_a.cell(0, 7, f"- {champ_txt} : {int(rowc['nb'])} correction(s)", ln=True)
                pdf_bytes_a = bytes(pdf_a.output())
                st.download_button(f"📄 Exporter la fiche de {selected_name} (PDF)", data=pdf_bytes_a,
                                   file_name=f"actetrack_fiche_{str(selected_name).replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.pdf",
                                   mime="application/pdf", use_container_width=True)
            except Exception as e:
                st.error(f"⚠️ Impossible de générer la fiche PDF : {e}")

        # ==================================================================
        # 3) COMPARAISON MULTI-AGENTS
        # ==================================================================
        with tab_cmp:
            noms = agents_overview["agent"].tolist()
            picked = st.multiselect("Agents à comparer (2 à 5)", noms, default=noms[:3], max_selections=5)
            if len(picked) < 2:
                st.info("Sélectionnez au moins deux agents pour lancer la comparaison.")
            else:
                sub = agents_overview[agents_overview["agent"].isin(picked)]
                metric_cols = {"volume": "Corrections", "actes": "Actes", "champs": "Champs",
                               "corr_par_jour": "Corr./jour", "pct_update": "% UPDATE",
                               "pct_delete": "% DELETE", "pct_hors": "% hors horaires"}
                melted = sub.melt(id_vars="agent", value_vars=list(metric_cols),
                                  var_name="indicateur", value_name="valeur")
                melted["indicateur"] = melted["indicateur"].map(metric_cols)
                fig = px.bar(melted, x="indicateur", y="valeur", color="agent", barmode="group",
                             template=PLOTLY_TEMPLATE, color_discrete_sequence=SEQ,
                             title="Comparaison des indicateurs clés")
                fig.update_layout(height=380, xaxis_title="", yaxis_title="", legend_title_text="")
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                ph = ", ".join(f":a{i}" for i in range(len(picked)))
                cmp_params = {**gp, **{f"a{i}": n for i, n in enumerate(picked)}}
                cmp_daily = run_query(f"""
                    SELECT u.full_name AS agent, DATE(h.date_modif_acte) AS jour, COUNT(*) AS nb
                    FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
                    WHERE {where_h} AND u.full_name IN ({ph})
                    GROUP BY agent, jour ORDER BY jour
                """, params=cmp_params)
                if not cmp_daily.empty:
                    cmp_daily["jour"] = pd.to_datetime(cmp_daily["jour"])
                    fig = px.line(cmp_daily, x="jour", y="nb", color="agent", template=PLOTLY_TEMPLATE,
                                  color_discrete_sequence=SEQ, title="Activité quotidienne comparée")
                    fig.update_layout(height=340, xaxis_title="", yaxis_title="Corrections", legend_title_text="")
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                cmp_champs = run_query(f"""
                    SELECT u.full_name AS agent, h.col_name AS champ, COUNT(*) AS nb
                    FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
                    WHERE {where_h} AND u.full_name IN ({ph})
                    GROUP BY agent, champ
                """, params=cmp_params)
                if not cmp_champs.empty:
                    top_champs_cmp = (cmp_champs.groupby("champ")["nb"].sum()
                                      .sort_values(ascending=False).head(10).index)
                    grid = (cmp_champs[cmp_champs["champ"].isin(top_champs_cmp)]
                            .pivot_table(index="agent", columns="champ", values="nb", aggfunc="sum").fillna(0))
                    fig = px.imshow(grid.values, x=list(grid.columns), y=list(grid.index), text_auto=True,
                                    aspect="auto", template=PLOTLY_TEMPLATE,
                                    color_continuous_scale=[COLORS["surface2"], COLORS["blue"], COLORS["coral"]],
                                    title="Champs corrigés — agent × champ")
                    fig.update_layout(height=320, xaxis_title="", yaxis_title="",
                                      coloraxis_colorbar=dict(thickness=10))
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

# ==============================================================================
# ÉQUIPE
# ==============================================================================
elif NAV == "equipe":
    where_h, gp = gfilter_where("h", team_alias="g")
    st.caption("Les opérations DELETE sans agent identifié (id_user NULL) sont exclues de cette vue.")
    team_data = run_query(f"""
        SELECT h.type_action, g.grp_desc, u.full_name
        FROM webman_tmp.tr_hist_change h
        JOIN webman_users.tr_user u ON h.id_user = u.cin
        JOIN webman_users.ta_user_grp ug ON u.id_user = ug.id_user
        JOIN webman_users.tr_grp g ON ug.id_grp = g.id_grp
        WHERE {where_h}
    """, params=gp)
    if team_data.empty:
        st.info("Aucune correspondance équipe/agent trouvée pour les corrections enregistrées sur cette période.")
    else:
        left, right = st.columns([1, 1])
        with left:
            by_team = team_data.groupby("grp_desc").size().reset_index(name="nb").sort_values("nb", ascending=False)
            fig = px.bar(by_team, x="nb", y="grp_desc", orientation="h", template=PLOTLY_TEMPLATE,
                        title="Volume total de corrections par équipe", color_discrete_sequence=[COLORS["blue"]])
            fig.update_layout(height=400, yaxis=dict(autorange="reversed"), yaxis_title="", xaxis_title="Corrections")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        with right:
            per_agent = team_data.groupby(["grp_desc", "full_name"]).size().reset_index(name="nb")
            summary = per_agent.groupby("grp_desc")["nb"].agg(["mean", "std", "count"]).reset_index()
            summary["std"] = summary["std"].fillna(0)
            summary = summary.sort_values("mean", ascending=False)
            fig = px.bar(summary, x="mean", y="grp_desc", orientation="h", template=PLOTLY_TEMPLATE,
                         error_x="std", title="Moyenne de corrections par agent, par équipe (barre = écart-type)",
                         color_discrete_sequence=[COLORS["coral"]])
            fig.update_layout(height=400, yaxis_title="", xaxis_title="Corrections / agent (moyenne)")
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        st.caption("Une barre d'erreur longue signifie une forte disparité d'activité entre agents de la même équipe.")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("**Répartition hiérarchique — équipe puis agent**")
        fig_tree = px.treemap(per_agent, path=["grp_desc", "full_name"], values="nb", template=PLOTLY_TEMPLATE,
                               title="Volume de corrections par équipe puis par agent", color="nb",
                               color_continuous_scale=[COLORS["surface2"], COLORS["blue"], COLORS["coral"]])
        fig_tree.update_traces(textinfo="label+value", marker=dict(line=dict(color=COLORS["bg"], width=1)))
        fig_tree.update_layout(height=460, margin=dict(t=40, l=4, r=4, b=4), coloraxis_showscale=False)
        st.plotly_chart(fig_tree, use_container_width=True, config={"displayModeBar": False})
        st.caption("La taille de chaque case reflète le volume de corrections ; utile pour repérer en un clic "
                   "quelle équipe — puis quel agent dans cette équipe — concentre l'activité.")

        st.markdown("<br>", unsafe_allow_html=True)
        st.markdown("### 🎯 Score de risque composite par agent")
        st.caption("Combine plusieurs signaux normalisés en une note sur 100, pour prioriser qui examiner en premier "
                   "plutôt que de croiser les indicateurs séparément : volume relatif (30%), % hors-horaires (25%), "
                   "% DELETE (20%), actes partagés avec d'autres agents (25%).")
        risk_stats = run_query(f"""
            SELECT u.full_name AS agent, COALESCE(g.grp_desc, 'Non affecté') AS equipe, COUNT(*) AS volume,
                   100*AVG(HOUR(h.date_modif_acte) < 7 OR HOUR(h.date_modif_acte) >= 20) AS pct_hors,
                   100*AVG(h.type_action='DELETE') AS pct_delete
            FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
            LEFT JOIN webman_users.ta_user_grp ug ON u.id_user = ug.id_user
            LEFT JOIN webman_users.tr_grp g ON ug.id_grp = g.id_grp
            WHERE {where_h} GROUP BY u.full_name, g.grp_desc
        """, params=gp)
        shared = run_query(f"""
            SELECT u.full_name AS agent, COUNT(DISTINCT h.id_acte) AS actes_partages
            FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
            WHERE {where_h} AND h.id_acte IN (
                SELECT id_acte FROM webman_tmp.tr_hist_change
                WHERE date_modif_acte BETWEEN :gd1 AND :gd2 AND id_user IS NOT NULL
                GROUP BY id_acte HAVING COUNT(DISTINCT id_user) >= 2
            ) GROUP BY u.full_name
        """, params=gp)
        if risk_stats.empty:
            st.info("Pas assez de données sur la période pour calculer un score de risque.")
        else:
            merged = risk_stats.merge(shared, on="agent", how="left")
            merged["actes_partages"] = merged["actes_partages"].fillna(0)

            def _norm100(s):
                mx = s.max()
                return 100 * s / mx if mx else s * 0

            merged["score"] = (
                _norm100(merged["volume"]) * 0.30 + merged["pct_hors"].fillna(0) * 0.25
                + merged["pct_delete"].fillna(0) * 0.20 + _norm100(merged["actes_partages"]) * 0.25
            ).round(1)
            merged = merged.sort_values("score", ascending=False)

            left_r, right_r = st.columns([1, 1.2])
            with left_r:
                top10 = merged.head(10).iloc[::-1]
                fig_risk = px.bar(top10, x="score", y="agent", orientation="h", template=PLOTLY_TEMPLATE,
                                   title="Top 10 — score de risque", color="score",
                                   color_continuous_scale=[COLORS["blue"], COLORS["yellow"], COLORS["coral"]])
                fig_risk.update_layout(height=400, yaxis_title="", xaxis_title="Score / 100", coloraxis_showscale=False)
                st.plotly_chart(fig_risk, use_container_width=True, config={"displayModeBar": False})
            with right_r:
                display_cols = merged[["agent", "equipe", "volume", "pct_hors", "pct_delete", "actes_partages", "score"]].copy()
                display_cols.columns = ["Agent", "Équipe", "Volume", "% hors-horaires", "% DELETE", "Actes partagés", "Score"]
                display_cols["% hors-horaires"] = display_cols["% hors-horaires"].round(1)
                display_cols["% DELETE"] = display_cols["% DELETE"].round(1)
                st.dataframe(display_cols.head(15), use_container_width=True, hide_index=True)
            st.caption("Un score élevé n'est pas une preuve de faute — c'est un point de départ pour l'audit, "
                       "à croiser avec le contexte (charge de travail, type de poste, etc.).")

# ==============================================================================
# QUALITÉ DES DONNÉES
# ==============================================================================
elif NAV == "qualite":
    where_h, gp = gfilter_where("h")
    st.caption("Mesure la capacité à rattacher chaque correction à un agent identifié — un indicateur clé "
               "de fiabilité pour un audit.")

    global_q = run_query(f"""
        SELECT type_action, SUM(id_user IS NULL) AS non_attribue, COUNT(*) AS total
        FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY type_action
    """, params=gp)
    global_q["taux_attribution"] = 100 * (1 - global_q["non_attribue"] / global_q["total"])
    total_all = global_q["total"].sum()
    non_attr_all = global_q["non_attribue"].sum()
    score_global = 100 * safe_div(total_all - non_attr_all, total_all)

    c1, c2, c3 = st.columns([1, 1, 2])
    with c1:
        st.plotly_chart(gauge_fig(score_global, "Score global de traçabilité", COLORS["green"] if score_global > 80 else COLORS["yellow"]),
                         use_container_width=True, config={"displayModeBar": False})
    with c2:
        st.plotly_chart(gauge_fig(100 * safe_div(non_attr_all, total_all), "% non attribué", COLORS["coral"]),
                         use_container_width=True, config={"displayModeBar": False})
    with c3:
        fig = px.bar(global_q.sort_values("taux_attribution"), x="taux_attribution", y="type_action",
                     orientation="h", template=PLOTLY_TEMPLATE, title="Taux d'attribution par type d'action",
                     text=global_q.sort_values("taux_attribution")["taux_attribution"].round(1).astype(str) + "%",
                     color_discrete_sequence=[COLORS["blue"]])
        fig.update_traces(textposition="outside")
        fig.update_layout(height=280, xaxis_title="% attribué à un agent", yaxis_title="", xaxis_range=[0, 105])
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<br>", unsafe_allow_html=True)
    trend_q = run_query(f"""
        SELECT DATE(h.date_modif_acte) AS jour, SUM(id_user IS NULL) AS non_attribue, COUNT(*) AS total
        FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY jour ORDER BY jour
    """, params=gp)
    if not trend_q.empty:
        trend_q["taux_attribution"] = 100 * (1 - trend_q["non_attribue"] / trend_q["total"])
        fig = px.line(trend_q, x="jour", y="taux_attribution", template=PLOTLY_TEMPLATE,
                      title="Évolution du taux d'attribution dans le temps", color_discrete_sequence=[COLORS["green"]])
        fig.update_traces(fill="tozeroy", fillcolor="rgba(0,224,164,0.08)")
        fig.update_layout(height=280, yaxis_title="% attribué", yaxis_range=[0, 105])
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### Comparaison par équipe")
    team_q = run_query(f"""
        SELECT COALESCE(g.grp_desc, 'Non affecté') AS equipe, SUM(h.id_user IS NULL) AS non_attribue, COUNT(*) AS total
        FROM webman_tmp.tr_hist_change h
        LEFT JOIN webman_users.tr_user u ON h.id_user = u.cin
        LEFT JOIN webman_users.ta_user_grp ug ON u.id_user = ug.id_user
        LEFT JOIN webman_users.tr_grp g ON ug.id_grp = g.id_grp
        WHERE {where_h} GROUP BY equipe
    """, params=gp)
    if not team_q.empty and team_q["equipe"].nunique() > 1:
        team_q["taux_attribution"] = 100 * (1 - team_q["non_attribue"] / team_q["total"])
        fig_tq = px.bar(team_q.sort_values("taux_attribution"), x="taux_attribution", y="equipe", orientation="h",
                         template=PLOTLY_TEMPLATE, title="Taux d'attribution par équipe", color="taux_attribution",
                         color_continuous_scale=[COLORS["coral"], COLORS["green"]])
        fig_tq.update_layout(height=320, xaxis_title="% attribué à un agent", yaxis_title="",
                              xaxis_range=[0, 105], coloraxis_showscale=False)
        st.plotly_chart(fig_tq, use_container_width=True, config={"displayModeBar": False})
    else:
        st.caption("Une seule équipe identifiée sur cette période — pas de comparaison possible.")

# ==============================================================================
# ANOMALIES
# ==============================================================================
elif NAV == "anomalies":
    where_h, gp = gfilter_where("h")
    where_ht, gpt = gfilter_where("h", team_alias="g")
    st.caption("Première itération des règles de détection — à affiner selon vos retours métier.")

    unattributed = run_query(f"""
        SELECT type_action, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
        WHERE {where_h} AND id_user IS NULL GROUP BY type_action
    """, params=gp)
    if not unattributed.empty:
        st.warning(f"⚠️ **{int(unattributed['nb'].sum()):,}** opérations sans agent identifié (`id_user` NULL) sur la période — exclues des analyses par agent.")

    left, right = st.columns([1.3, 1])
    with left:
        outliers = run_query(f"""
            SELECT id_acte, COUNT(*) AS nb_corrections FROM webman_tmp.tr_hist_change h
            WHERE {where_h} GROUP BY id_acte HAVING nb_corrections > 5 ORDER BY nb_corrections DESC LIMIT 25
        """, params=gp)
        st.markdown("**Actes avec un nombre de corrections anormalement élevé**")
        st.dataframe(outliers, use_container_width=True, hide_index=True)
        if not outliers.empty:
            oc1, oc2 = st.columns([3, 1])
            with oc1:
                acte_to_inspect = st.selectbox("Examiner un acte de cette liste", outliers["id_acte"].tolist(),
                                                key="anom_acte_select", label_visibility="collapsed")
            with oc2:
                if st.button("Voir le détail →", key="drill_outlier_acte", use_container_width=True):
                    st.session_state["acte_prefill"] = str(acte_to_inspect)
                    st.session_state["nav"] = "acte"
                    st.rerun()

    with right:
        ratio_agents = run_query(f"""
            SELECT u.full_name, COUNT(*) AS total
            FROM webman_tmp.tr_hist_change h
            JOIN webman_users.tr_user u ON h.id_user = u.cin
            JOIN webman_users.ta_user_grp ug ON u.id_user = ug.id_user
            JOIN webman_users.tr_grp g ON ug.id_grp = g.id_grp
            WHERE {where_ht} GROUP BY u.full_name HAVING total > 20 ORDER BY total DESC LIMIT 8
        """, params=gpt)
        if not ratio_agents.empty:
            mean_t, std_t = ratio_agents["total"].mean(), ratio_agents["total"].std()
            def level(v):
                if v > mean_t + std_t:
                    return "Élevé"
                if v > mean_t:
                    return "Moyen"
                return "Faible"
            ratio_agents["risque"] = ratio_agents["total"].apply(level)
            st.markdown("**Agents à risque (volume d'activité)**")
            rows_html = "".join(
                f'<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;'
                f'border-bottom:1px solid {COLORS["border"]};">'
                f'<span style="color:{COLORS["text"]};font-size:13px;">{r.full_name}</span>{risk_badge(r.risque)}</div>'
                for r in ratio_agents.itertuples()
            )
            st.markdown(f'<div class="ct-kpi" style="border-top:3px solid {COLORS["coral"]};">{rows_html}</div>', unsafe_allow_html=True)
        else:
            st.info("Aucun agent à risque identifié sur cette période/équipe.")

    st.markdown("<br>", unsafe_allow_html=True)
    hourly = run_query(f"""
        SELECT HOUR(h.date_modif_acte) AS heure, COUNT(*) AS nb FROM webman_tmp.tr_hist_change h
        WHERE {where_h} GROUP BY heure ORDER BY heure
    """, params=gp)
    if not hourly.empty:
        hourly["hors_horaires"] = hourly["heure"].apply(lambda h: h < 7 or h >= 20)
        fig = px.bar(hourly, x="heure", y="nb", color="hors_horaires", template=PLOTLY_TEMPLATE,
                     title="Répartition des corrections par heure — nuit/soir en évidence",
                     color_discrete_map={True: COLORS["coral"], False: COLORS["blue"]})
        fig.update_layout(height=280, showlegend=False, xaxis_title="Heure de la journée", yaxis_title="Corrections")
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<br>", unsafe_allow_html=True)
    dowhour = run_query(f"""
        SELECT DAYOFWEEK(h.date_modif_acte) AS jour_sem, HOUR(h.date_modif_acte) AS heure, COUNT(*) AS nb
        FROM webman_tmp.tr_hist_change h WHERE {where_h} GROUP BY jour_sem, heure
    """, params=gp)
    if not dowhour.empty:
        jours_labels = {1: "Dim", 2: "Lun", 3: "Mar", 4: "Mer", 5: "Jeu", 6: "Ven", 7: "Sam"}
        pivot_dh = dowhour.pivot(index="jour_sem", columns="heure", values="nb").reindex(range(1, 8)).fillna(0)
        fig_dh = go.Figure(go.Heatmap(
            z=pivot_dh.values, x=list(pivot_dh.columns), y=[jours_labels[i] for i in pivot_dh.index],
            colorscale=[[0, COLORS["surface2"]], [1, COLORS["coral"]]], showscale=True,
            hovertemplate="%{y} %{x}h — %{z} corrections<extra></extra>",
        ))
        fig_dh.update_layout(template=PLOTLY_TEMPLATE, height=300,
                              title="Intensité des corrections — jour de semaine × heure",
                              xaxis_title="Heure", yaxis_title="")
        st.plotly_chart(fig_dh, use_container_width=True, config={"displayModeBar": False})

    st.markdown("<br>", unsafe_allow_html=True)
    left2, right2 = st.columns([1.2, 1])
    with left2:
        st.markdown("**Rafales de corrections** (plusieurs corrections rapprochées par le même agent)")
        total_period = run_query(f"SELECT COUNT(*) AS nb FROM webman_tmp.tr_hist_change h WHERE {where_h}",
                                  params=gp).iloc[0]["nb"]
        BURST_ROW_LIMIT, BURST_WINDOW_MIN, BURST_MIN_COUNT = 150000, 3, 5
        if total_period > BURST_ROW_LIMIT:
            st.info(f"Détection désactivée : {int(total_period):,} lignes sur la période — réduisez la "
                     f"période ou l'équipe pour l'activer (limite {BURST_ROW_LIMIT:,}).".replace(",", " "))
        else:
            burst_df = _detect_bursts(where_h, gp, BURST_WINDOW_MIN, BURST_MIN_COUNT)
            if not burst_df.empty:
                burst_df = burst_df.sort_values("Nb corrections", ascending=False)
                st.caption(f"≥ {BURST_MIN_COUNT} corrections en moins de {BURST_WINDOW_MIN} min par le même agent.")
                st.dataframe(burst_df.head(20), use_container_width=True, hide_index=True)
            else:
                st.caption("Aucune rafale de corrections détectée sur la période/équipe sélectionnée.")
    with right2:
        st.markdown("**Actes modifiés par plusieurs agents différents**")
        multi_agent = run_query(f"""
            SELECT h.id_acte AS "Acte", COUNT(DISTINCT h.id_user) AS "Agents distincts", COUNT(*) AS "Corrections"
            FROM webman_tmp.tr_hist_change h WHERE {where_h} AND h.id_user IS NOT NULL
            GROUP BY h.id_acte HAVING COUNT(DISTINCT h.id_user) >= 2
            ORDER BY COUNT(DISTINCT h.id_user) DESC, COUNT(*) DESC LIMIT 20
        """, params=gp)
        if not multi_agent.empty:
            st.caption("Un acte touché par plusieurs agents peut signaler un chevauchement ou des corrections en chaîne.")
            st.dataframe(multi_agent, use_container_width=True, hide_index=True)
        else:
            st.caption("Aucun acte n'a été corrigé par plusieurs agents différents sur cette période.")

# ==============================================================================
# EXPORT / RAPPORTS
# ==============================================================================
elif NAV == "export":
    where_h, gp = gfilter_where("h")
    st.markdown("Génère un rapport de synthèse pour la période et l'équipe actuellement filtrées "
                f"(**{st.session_state['gfilter_start']} → {st.session_state['gfilter_end']}**, "
                f"**{st.session_state['gfilter_team']}**).")

    kpi = run_query(f"""
        SELECT COUNT(*) AS total, COUNT(DISTINCT id_acte) AS actes,
               SUM(type_action='UPDATE') AS n_update, SUM(type_action='DELETE') AS n_delete,
               SUM(type_action='INSERT') AS n_insert, SUM(id_user IS NULL) AS non_attribue
        FROM webman_tmp.tr_hist_change h WHERE {where_h}
    """, params=gp).iloc[0]
    top_agents = run_query(f"""
        SELECT u.full_name AS "Agent", COUNT(*) AS "Corrections"
        FROM webman_tmp.tr_hist_change h JOIN webman_users.tr_user u ON h.id_user = u.cin
        WHERE {where_h} GROUP BY u.full_name ORDER BY "Corrections" DESC LIMIT 15
    """, params=gp)
    top_actes = run_query(f"""
        SELECT id_acte AS "Acte", COUNT(*) AS "Corrections" FROM webman_tmp.tr_hist_change h
        WHERE {where_h} GROUP BY id_acte ORDER BY "Corrections" DESC LIMIT 15
    """, params=gp)

    summary_df = pd.DataFrame({
        "Indicateur": ["Total corrections", "Actes concernés", "% UPDATE", "% DELETE", "% INSERT", "Opérations non attribuées"],
        "Valeur": [int(kpi["total"]), int(kpi["actes"]),
                   f"{100*safe_div(kpi['n_update'], kpi['total']):.1f}%",
                   f"{100*safe_div(kpi['n_delete'], kpi['total']):.1f}%",
                   f"{100*safe_div(kpi['n_insert'], kpi['total']):.1f}%",
                   int(kpi["non_attribue"])],
    })

    st.dataframe(summary_df, use_container_width=True, hide_index=True)

    c1, c2 = st.columns(2)
    with c1:
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            summary_df.to_excel(writer, sheet_name="Synthèse", index=False)
            top_agents.to_excel(writer, sheet_name="Top agents", index=False)
            top_actes.to_excel(writer, sheet_name="Top actes", index=False)
        st.download_button("📊 Télécharger le rapport Excel", data=buf.getvalue(),
                            file_name=f"actetrack_rapport_{datetime.now().strftime('%Y%m%d')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True)
    with c2:
        try:
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 10, "ActeTrack - Rapport de synthese", ln=True)
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 8, f"Periode : {st.session_state['gfilter_start']} au {st.session_state['gfilter_end']}", ln=True)
            pdf.cell(0, 8, f"Equipe : {st.session_state['gfilter_team']}", ln=True)
            pdf.cell(0, 8, f"Genere le : {datetime.now().strftime('%d/%m/%Y %H:%M')}", ln=True)
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, "Indicateurs cles", ln=True)
            pdf.set_font("Helvetica", "", 10)
            for _, row in summary_df.iterrows():
                indicateur = str(row["Indicateur"]).encode("latin-1", "replace").decode("latin-1")
                pdf.cell(0, 7, f"- {indicateur} : {row['Valeur']}", ln=True)
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 12)
            pdf.cell(0, 8, "Top 10 agents", ln=True)
            pdf.set_font("Helvetica", "", 10)
            for _, row in top_agents.head(10).iterrows():
                nom = str(row["Agent"]).encode("latin-1", "replace").decode("latin-1")
                pdf.cell(0, 7, f"- {nom} : {int(row['Corrections'])} corrections", ln=True)
            # fpdf2 récent : output() sans dest renvoie déjà un bytearray, pas besoin
            # (et incompatible avec) l'ancien dest="S" qui casse bytes() sans encodage.
            pdf_bytes = bytes(pdf.output())
            st.download_button("📄 Télécharger le rapport PDF", data=pdf_bytes,
                                file_name=f"actetrack_rapport_{datetime.now().strftime('%Y%m%d')}.pdf",
                                mime="application/pdf", use_container_width=True)
        except Exception as e:
            st.error(f"⚠️ Impossible de générer le PDF : {e}")

# ==============================================================================
# DIAGNOSTIC PERF (temporaire) — à retirer une fois le problème de lenteur résolu
# ==============================================================================
with st.sidebar:
    st.markdown("<hr style='border-color:#2A2F3B;margin:16px 0;'>", unsafe_allow_html=True)
    with st.expander("🔧 Diagnostic vitesse"):
        _total_render = time.perf_counter() - _RENDER_START
        st.caption(f"**Temps total de la page : {_total_render:.2f} s**")
        st.caption(f"Requêtes envoyées à MySQL (hors cache) : {len(_QUERY_LOG)}")
        if _QUERY_LOG:
            st.caption(f"Temps cumulé de ces requêtes MySQL : {sum(_QUERY_LOG):.2f} s")
            st.caption(f"Requête MySQL la plus lente : {max(_QUERY_LOG):.2f} s")
        else:
            st.caption("Aucune requête MySQL — tout venait du cache sur cette page.")
        st.caption("Si le temps MySQL est petit mais le temps total est grand -> le ralentissement "
                   "vient du rendu des graphiques ou de la connexion réseau au navigateur, pas de la base.")