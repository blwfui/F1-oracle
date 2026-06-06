"""F1 Oracle — Streamlit Dashboard."""

import sys
import time
from pathlib import Path

_t0 = time.perf_counter()

# Ensure src/dashboard/ is on sys.path so 'common' and 'views' are importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib

import streamlit as st

from common import _get_years, _query_stats

_t_imports = time.perf_counter()

st.set_page_config(page_title="F1 Oracle", page_icon="🏎️", layout="wide")

if "css_injected" not in st.session_state:
    st.session_state.css_injected = True
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

* { font-family: 'Inter', sans-serif; }

.stApp { background-color: #FAFAFA; }

[data-testid="stAppViewContainer"] .block-container {
    max-width: 960px !important;
    margin-left: auto !important;
    margin-right: auto !important;
    padding-left: 2rem !important;
    padding-right: 2rem !important;
}

section[data-testid="stSidebar"] {
    position: fixed !important;
    left: 0 !important;
    top: 0 !important;
    height: 100vh !important;
    z-index: 200 !important;
    background-color: #E10600;
    border-right: none;
    width: 18vw !important;
    min-width: 200px !important;
    max-width: 300px !important;
    flex: none !important;
    transform: translateX(calc(-100% + 6px));
    transition: transform 0.25s ease;
    overflow-y: auto;
}
section[data-testid="stSidebar"]:hover {
    transform: translateX(0);
}
section[data-testid="stSidebar"] > div:first-child {
    width: 100% !important;
}
[data-testid="stSidebar"] h1 { color: #FFFFFF !important; font-weight: 700; font-size: 1.6rem; }
[data-testid="stSidebar"] .stCaption { color: rgba(255,255,255,0.75) !important; }
[data-testid="stSidebar"] [data-testid="stSelectbox"] label { color: #FFFFFF; }

h1 { color: #1A1A1A !important; font-weight: 700; }
h2 { color: #1A1A1A !important; border-left: 4px solid #E10600; padding-left: 14px; font-weight: 600; }
h3 { color: #444444 !important; font-weight: 600; }

[data-testid="stMetric"] { background-color: #FFFFFF; border-radius: 10px; padding: 16px; border-top: 3px solid #E10600; border: 1px solid #E8E8E8; }
[data-testid="stMetricValue"] { color: #1A1A1A; font-weight: 700; font-size: 1.4rem; white-space: nowrap; }
[data-testid="stMetricLabel"] { color: #888888; font-size: 0.8rem; font-weight: 500; }

div[data-testid="stDataFrame"] td,
div[data-testid="stDataFrame"] th,
div[data-testid="stTable"] td,
div[data-testid="stTable"] th { text-align: center !important; }
[data-testid="stDataFrame"] th, [data-testid="stTable"] th { background-color: #E10600 !important; color: #FFFFFF !important; font-weight: 600; border: none !important; }
[data-testid="stDataFrame"] td, [data-testid="stTable"] td { background-color: #FFFFFF; color: #333333; border-bottom: 1px solid #EEEEEE !important; }
[data-testid="stDataFrame"] tr:hover td, [data-testid="stTable"] tr:hover td { background-color: #FFF0F0 !important; }

[data-testid="stSelectbox"] label { color: #333333; }
label { color: #555555; }

.stCaption, .st-emotion-cache-13wylk3 { color: #999999; }
[data-testid="stAlert"] { background-color: #FFF5F5; border-left: 4px solid #E10600; }

::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: #F0F0F0; }
::-webkit-scrollbar-thumb { background: #CCCCCC; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #E10600; }

[data-testid="stSidebar"] [data-testid="stButton"] button {
    border-radius: 0;
    border: none;
    font-weight: 600;
    padding: 16px 20px;
    text-align: left;
    margin: 0;
    font-size: 1.15rem;
    transition: background-color 0.15s ease;
    box-shadow: none;
    border-bottom: 1px solid rgba(255,255,255,0.12);
}
[data-testid="stSidebar"] [data-testid="stButton"]:last-of-type button {
    border-bottom: none;
}
[data-testid="stSidebar"] button[kind="primary"] {
    background-color: #8B0000;
    color: #FFFFFF;
}
[data-testid="stSidebar"] button[kind="secondary"] {
    background-color: #E10600;
    color: #FFFFFF;
}
[data-testid="stSidebar"] button[kind="secondary"]:hover {
    background-color: #C80000;
    color: #FFFFFF;
}
</style>
""", unsafe_allow_html=True)

_t_css = time.perf_counter()

# ═══════════════════════════════════════════════════════════
# Sidebar
# ═══════════════════════════════════════════════════════════
st.sidebar.title("🏎️ F1 Oracle")

years = _get_years()
year = st.sidebar.selectbox("赛季", years, index=0)
st.sidebar.caption(f"{year} 赛季数据仓库")

if "page" not in st.session_state:
    st.session_state.page = "赛季总览"


def _set_page(name):
    st.session_state.page = name


nav_pages = [
    ("📊", "赛季总览"),
    ("🔍", "分站详情"),
    ("👤", "车手档案"),
    ("🏁", "赛道分析"),
    ("💬", "AI 问答"),
]
for i, (icon, name) in enumerate(nav_pages):
    active = st.session_state.page == name
    st.sidebar.button(
        f"{icon}  {name}",
        key=f"nav_{i}",
        use_container_width=True,
        type="primary" if active else "secondary",
        on_click=_set_page,
        args=(name,),
    )

_t_sidebar = time.perf_counter()

# ═══════════════════════════════════════════════════════════
# Page routing — lazy-import; current page renders first,
# Python caches subsequent imports so repeat switches are instant
# ═══════════════════════════════════════════════════════════
_page_map = {
    "赛季总览": "01_赛季总览",
    "分站详情": "02_分站详情",
    "车手档案": "03_车手档案",
    "赛道分析": "04_赛道分析",
    "AI 问答": "05_AI问答",
}

mod = importlib.import_module(f"views.{_page_map[st.session_state.page]}")
_t_import_page = time.perf_counter()

mod.render(year)
_t_render = time.perf_counter()

# Timing probe — shows where time is spent each rerun
st.sidebar.divider()
with st.sidebar.expander("⏱ 性能探针", expanded=False):
    st.caption(f"导入: {(_t_imports - _t0)*1000:.0f}ms")
    st.caption(f"CSS:  {(_t_css - _t_imports)*1000:.0f}ms")
    st.caption(f"侧栏: {(_t_sidebar - _t_css)*1000:.0f}ms")
    st.caption(f"加载页面: {(_t_import_page - _t_sidebar)*1000:.0f}ms")
    st.caption(f"渲染: {(_t_render - _t_import_page)*1000:.0f}ms")
    st.caption(f"**总计: {(_t_render - _t0)*1000:.0f}ms**")
    misses, sql_ms = _query_stats()
    st.caption(f"SQL 实际执行: {misses}次 / {sql_ms:.0f}ms")
