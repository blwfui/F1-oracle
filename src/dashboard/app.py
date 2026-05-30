"""F1 Oracle — Streamlit Dashboard."""

import sqlite3
from pathlib import Path

import pandas as pd
import plotly.express as px
import numpy as np
import streamlit as st

from names_cn import auto_cn_short, auto_cn_full

st.set_page_config(page_title="F1 Oracle", page_icon="🏎️", layout="wide")

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

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "f1_oracle.db"

NUM_CN = {1: "一", 2: "二", 3: "三", 4: "四", 5: "五", 6: "六", 7: "七", 8: "八",
           9: "九", 10: "十", 11: "十一", 12: "十二", 13: "十三", 14: "十四",
           15: "十五", 16: "十六", 17: "十七", 18: "十八", 19: "十九", 20: "二十",
            21: "二十一", 22: "二十二", 23: "二十三", 24: "二十四", 25: "二十五"}

STATUS_CN = {"Finished": "完赛", "Retired": "退赛", "Disqualified": "取消资格",
             "+1 Lap": "+1圈", "+2 Laps": "+2圈", "+6 Laps": "+6圈",
             "Collision": "碰撞退赛", "Collision damage": "碰撞受损",
             "Engine": "引擎故障", "Gearbox": "变速箱", "Brakes": "刹车故障",
             "Accident": "事故退赛", "Spun off": "打转退赛",
             "Undertray": "底板损伤", "Withdrew": "退赛",
             "Mechanical": "机械故障", "Power Unit": "动力单元",
             "Hydraulics": "液压故障", "Suspension": "悬挂故障",
             "Cooling system": "冷却系统", "Differential": "差速器",
             "Fuel leak": "燃油泄漏", "Fuel pressure": "燃油压力",
             "Fuel pump": "燃油泵", "Oil leak": "机油泄漏",
             "Power loss": "动力损失", "Turbo": "涡轮故障",
             "Vibrations": "震动故障", "Water leak": "漏水",
             "Water pressure": "水压故障", "Water pump": "水泵故障",
              "Front wing": "前翼损伤",
              "+3 Laps": "+3圈", "Damage": "车损退赛",
              "Driveshaft": "传动轴故障", "Electrical": "电气故障",
              "Illness": "身体不适", "Puncture": "爆胎退赛",
              "Rear wing": "尾翼损伤", "Wheel nut": "轮胎螺母故障",
              "+5 Laps": "+5圈", "Debris": "碎片损伤",
               "Electronics": "电子故障",
               "Overheating": "过热退赛", "Radiator": "散热器故障",
               "Transmission": "传动故障", "Wheel": "轮胎故障",
               "Out of fuel": "燃油耗尽", "Battery": "电池故障",
               "Steering": "转向故障", "Tyre": "轮胎问题",
                "Lapped": "被套圈", "Did not start": "未起步", "": "—"}

DRIVER_CN = {
    "ALB": "ALB 阿尔本", "ALO": "ALO 阿隆索", "ANT": "ANT 安东内利",
    "BEA": "BEA 比尔曼", "BOR": "BOR 博托莱托", "COL": "COL 科拉平托",
    "DOO": "DOO 杜汉", "GAS": "GAS 加斯利", "HAD": "HAD 哈贾尔",
    "HAM": "HAM 汉密尔顿", "HUL": "HUL 霍肯伯格", "LAW": "LAW 劳森",
    "LEC": "LEC 勒克莱尔", "NOR": "NOR 诺里斯", "OCO": "OCO 奥康",
    "PIA": "PIA 皮亚斯特里", "RUS": "RUS 拉塞尔", "SAI": "SAI 赛恩斯",
    "STR": "STR 斯特罗尔", "TSU": "TSU 角田裕毅", "VER": "VER 维斯塔潘",
    "DEV": "DEV 德弗里斯", "LAT": "LAT 拉提菲", "MSC": "MSC 米克·舒马赫",
    "VET": "VET 维特尔", "BOT": "BOT 博塔斯", "MAG": "MAG 马格努森", "PER": "PER 佩雷兹",
    "RIC": "RIC 里卡多", "SAR": "SAR 萨金特", "ZHO": "ZHO 周冠宇",
    "GIO": "GIO 吉奥维纳兹", "KUB": "KUB 库比卡", "MAZ": "MAZ 马泽平",
    "RAI": "RAI 莱科宁", "GRO": "GRO 格罗斯让", "KVY": "KVY 科维亚特",
    "AIT": "AIT 艾特肯", "FIT": "FIT 菲蒂帕尔迪",
    "ERI": "ERI 埃里克森", "HAR": "HAR 哈特利",
    "SIR": "SIR 斯洛特金", "VAN": "VAN 范多恩",
    "ARO": "ARO 阿龙", "BEG": "BEG 贝加诺维奇", "BRO": "BRO 布朗宁",
    "CRA": "CRA 克劳福德", "DRU": "DRU 德鲁戈维奇", "DUN": "DUN 邓恩",
    "FUO": "FUO 福科", "HIR": "HIR 平川亮", "IWA": "IWA 岩佐步梦",
    "LEL": "LEL 阿·勒克莱尔", "LIN": "LIN 林德布拉德", "MAR": "MAR 马丁斯",
    "OWA": "OWA 奥沃德", "SHI": "SHI 希尔兹", "VES": "VES 维斯蒂",
    "SHW": "SHW 施瓦茨曼",
    "BAD": "BAD 巴德", "BIL": "BIL 比尔", "CAM": "CAM 卡姆",
    "CHO": "CHO 乔", "GIU": "GIU 朱", "HED": "HED 赫德",
    "INT": "INT 因特", "JOH": "JOH 约翰", "LAC": "LAC 拉克",
    "TRA": "TRA 特拉", "UGO": "UGO 乌戈", "VOI": "VOI 沃伊",
    "WHA": "WHA 沃",
}

DRIVER_FULL_CN = {
    "ALB": "亚历山大·阿尔本", "ALO": "费尔南多·阿隆索", "ANT": "安德里亚·安东内利",
    "BEA": "奥利弗·比尔曼", "BOR": "加布里埃尔·博托莱托", "COL": "弗兰科·科拉平托",
    "DOO": "杰克·杜汉", "GAS": "皮埃尔·加斯利", "HAD": "伊萨克·哈贾尔",
    "HAM": "刘易斯·汉密尔顿", "HUL": "尼科·霍肯伯格", "LAW": "利亚姆·劳森",
    "LEC": "夏尔·勒克莱尔", "NOR": "兰多·诺里斯", "OCO": "埃斯特班·奥康",
    "PIA": "奥斯卡·皮亚斯特里", "RUS": "乔治·拉塞尔", "SAI": "卡洛斯·赛恩斯",
    "STR": "兰斯·斯特罗尔", "TSU": "角田裕毅", "VER": "马克斯·维斯塔潘",
    "DEV": "尼克·德弗里斯", "LAT": "尼古拉斯·拉提菲",
    "MSC": "米克·舒马赫", "VET": "塞巴斯蒂安·维特尔",
    "BOT": "瓦尔特利·博塔斯", "MAG": "凯文·马格努森", "PER": "塞尔吉奥·佩雷兹",
    "RIC": "丹尼尔·里卡多", "SAR": "洛根·萨金特", "ZHO": "周冠宇",
    "GIO": "安东尼奥·吉奥维纳兹", "KUB": "罗伯特·库比卡",
    "MAZ": "尼基塔·马泽平", "RAI": "基米·莱科宁",
    "GRO": "罗曼·格罗斯让", "KVY": "丹尼尔·科维亚特",
    "AIT": "杰克·艾特肯", "FIT": "皮埃特罗·菲蒂帕尔迪",
    "ERI": "马库斯·埃里克森", "HAR": "布兰登·哈特利",
    "SIR": "谢尔盖·斯洛特金", "VAN": "斯托菲尔·范多恩",
    "ARO": "保罗·阿龙", "BEG": "迪诺·贝加诺维奇", "BRO": "卢克·布朗宁",
    "CRA": "杰克·克劳福德", "DRU": "菲利佩·德鲁戈维奇", "DUN": "亚历山大·邓恩",
    "FUO": "安东尼奥·福科", "HIR": "平川亮", "IWA": "岩佐步梦",
    "LEL": "阿蒂尔·勒克莱尔", "LIN": "阿尔维德·林德布拉德", "MAR": "维克多·马丁斯",
    "OWA": "帕特里西奥·奥沃德", "SHI": "西恩·希尔兹", "VES": "弗雷德里克·维斯蒂",
    "SHW": "罗伯特·施瓦茨曼",
    "BAD": "巴德", "BIL": "比尔", "CAM": "卡姆",
    "CHO": "乔", "GIU": "朱", "HED": "赫德",
    "INT": "因特", "JOH": "约翰", "LAC": "拉克",
    "TRA": "特拉", "UGO": "乌戈", "VOI": "沃伊",
    "WHA": "沃",
}

TEAM_CN = {
    "McLaren": "McLaren 迈凯伦", "Ferrari": "Ferrari 法拉利",
    "Red Bull Racing": "Red Bull 红牛", "Mercedes": "Mercedes 梅赛德斯",
    "Aston Martin": "Aston Martin 阿斯顿马丁", "Alpine": "Alpine 阿尔派",
    "Haas F1 Team": "Haas 哈斯", "Racing Bulls": "Racing Bulls 小红牛",
    "Williams": "Williams 威廉姆斯", "Kick Sauber": "Kick Sauber 索伯",
    "Sauber": "Sauber 索伯",
    "Alfa Romeo": "Alfa Romeo 阿尔法罗密欧", "AlphaTauri": "AlphaTauri 小红牛",
    "Racing Point": "Racing Point 赛点", "Renault": "Renault 雷诺",
    "Toro Rosso": "Toro Rosso 小红牛",
    "Force India": "Force India 印度力量",
}

EVENT_CN = {
    "Australian Grand Prix": "澳大利亚站",
    "Chinese Grand Prix": "中国站",
    "Japanese Grand Prix": "日本站",
    "Bahrain Grand Prix": "巴林站",
    "Saudi Arabian Grand Prix": "沙特站",
    "Miami Grand Prix": "迈阿密站",
    "Emilia Romagna Grand Prix": "伊莫拉站",
    "Monaco Grand Prix": "摩纳哥站",
    "Spanish Grand Prix": "西班牙站",
    "Canadian Grand Prix": "加拿大站",
    "Austrian Grand Prix": "奥地利站",
    "British Grand Prix": "英国站",
    "Belgian Grand Prix": "比利时站",
    "Hungarian Grand Prix": "匈牙利站",
    "Dutch Grand Prix": "荷兰站",
    "Italian Grand Prix": "蒙扎站",
    "Azerbaijan Grand Prix": "阿塞拜疆站",
    "Singapore Grand Prix": "新加坡站",
    "United States Grand Prix": "奥斯汀站",
    "Mexico City Grand Prix": "墨西哥站",
    "São Paulo Grand Prix": "巴西站",
    "Las Vegas Grand Prix": "拉斯维加斯站",
    "Qatar Grand Prix": "卡塔尔站",
    "French Grand Prix": "法国站",
    "Portuguese Grand Prix": "葡萄牙站",
    "Russian Grand Prix": "俄罗斯站",
    "Styrian Grand Prix": "施蒂利亚站",
    "Turkish Grand Prix": "土耳其站",
    "70th Anniversary Grand Prix": "70周年大奖赛",
    "Eifel Grand Prix": "艾菲尔站",
    "Sakhir Grand Prix": "萨基尔站",
    "Tuscan Grand Prix": "托斯卡纳站",
    "Pre-Season Test": "季前测试", "Pre-Season Test 2": "季前测试2",
    "Abu Dhabi Grand Prix": "阿布扎比站",
    "German Grand Prix": "德国站",
    "Brazilian Grand Prix": "巴西站",
    "Mexican Grand Prix": "墨西哥站",
}

LOCATION_CN = {
    "Melbourne": "阿尔伯特公园赛道", "Shanghai": "上海国际赛车场",
    "Suzuka": "铃鹿国际赛车场", "Sakhir": "巴林国际赛车场",
    "Jeddah": "吉达滨海赛道", "Miami": "迈阿密国际赛车场", "Miami Gardens": "迈阿密国际赛车场",
    "Imola": "伊莫拉赛道", "Monaco": "蒙特卡洛赛道",
    "Barcelona": "巴塞罗那-加泰罗尼亚赛道", "Montréal": "吉尔斯·维伦纽夫赛道",
    "Spielberg": "红牛环赛道", "Silverstone": "银石赛道",
    "Spa-Francorchamps": "斯帕-弗朗科尔尚赛道", "Budapest": "亨格罗宁赛道",
    "Zandvoort": "赞德沃特赛道", "Monza": "蒙扎国家赛车场",
    "Baku": "巴库城市赛道", "Marina Bay": "滨海湾市街赛道",
    "Austin": "美洲赛道", "Mexico City": "罗德里格斯兄弟赛道",
    "São Paulo": "若泽·卡洛斯·帕塞赛道", "Las Vegas": "拉斯维加斯大道赛道",
    "Lusail": "卢赛尔国际赛车场", "Yas Island": "亚斯码头赛道",
    "Le Castellet": "保罗·里卡德赛道",
    "Bahrain": "巴林国际赛车场", "Istanbul": "伊斯坦布尔公园赛道",
    "Monte Carlo": "蒙特卡洛赛道", "Portimão": "阿尔加维国际赛车场",
    "Sochi": "索契赛道", "Mugello": "穆杰罗赛道",
    "Nürburgring": "纽博格林赛道",
    "Hockenheim": "霍根海姆赛道",
    "Singapore": "滨海湾市街赛道",
}

COUNTRY_CN = {
    "Australia": "澳大利亚", "China": "中国", "Japan": "日本",
    "Bahrain": "巴林", "Saudi Arabia": "沙特阿拉伯", "USA": "美国",
    "United States": "美国", "Italy": "意大利", "Monaco": "摩纳哥",
    "Spain": "西班牙", "Canada": "加拿大", "Austria": "奥地利",
    "United Kingdom": "英国", "Great Britain": "英国",
    "Belgium": "比利时", "Hungary": "匈牙利", "Netherlands": "荷兰",
    "Azerbaijan": "阿塞拜疆", "Singapore": "新加坡", "Mexico": "墨西哥",
    "Brazil": "巴西", "Qatar": "卡塔尔", "France": "法国",
    "Portugal": "葡萄牙", "Russia": "俄罗斯", "Turkey": "土耳其",
    "Germany": "德国",
    "UAE": "阿联酋", "United Arab Emirates": "阿联酋",
    "Abu Dhabi": "阿联酋",
}

TEAM_FULL_CN = {
    "McLaren": "迈凯伦", "Ferrari": "法拉利", "Red Bull Racing": "红牛",
    "Mercedes": "梅赛德斯", "Aston Martin": "阿斯顿马丁", "Alpine": "阿尔派",
    "Haas F1 Team": "哈斯", "Racing Bulls": "小红牛",
    "Williams": "威廉姆斯", "Kick Sauber": "索伯",
    "Sauber": "索伯",
    "Alfa Romeo": "阿尔法罗密欧", "AlphaTauri": "小红牛",
    "Racing Point": "赛点", "Renault": "雷诺",
    "Toro Rosso": "红牛二队",
    "Force India": "印度力量",
}

TEAM_COLORS = {
    "Ferrari": "#DC0000", "Red Bull Racing": "#1E41FF",
    "McLaren": "#FF8000", "Mercedes": "#00A19C",
    "Alpine": "#FF87BC", "Aston Martin": "#006F62",
    "Williams": "#41B6E6", "Haas F1 Team": "#B6BABD",
    "Racing Bulls": "#A8C0E0", "Kick Sauber": "#00E701",
    "Sauber": "#00E701",
    "Alfa Romeo": "#800020", "AlphaTauri": "#1E3A5F",
    "Racing Point": "#F596C8", "Renault": "#FFF500",
    "Toro Rosso": "#1E3A5F",
    "Force India": "#F596C8",
}

COMPOUND_CN = {
    "SOFT": "软胎", "MEDIUM": "中性胎", "HARD": "硬胎",
    "INTERMEDIATE": "半雨胎", "WET": "雨胎",
    "HYPERSOFT": "极软胎", "ULTRASOFT": "超软胎",
    "SUPERSOFT": "红软胎",
}

COMPOUND_COLORS = {
    "软胎": "#FF0000", "中性胎": "#FFD700", "硬胎": "#FFFFFF",
    "半雨胎": "#228B22", "雨胎": "#0055FF",
    "极软胎": "#E20074", "超软胎": "#83309C",
    "红软胎": "#DA291C",
    "无数据": "#CCCCCC",
}

PRACTICE_SESSIONS = [
    {"type": "FP1", "label": "一练 FP1", "color": "#2E8B57"},
    {"type": "FP2", "label": "二练 FP2", "color": "#1E90FF"},
    {"type": "FP3", "label": "三练 FP3", "color": "#FF8C00"},
]

QUALI_PHASES = [
    {"key": "Q1", "col": "q1_sec", "label": "Q1 第一节", "color": "#2E8B57"},
    {"key": "Q2", "col": "q2_sec", "label": "Q2 第二节", "color": "#1E90FF"},
    {"key": "Q3", "col": "q3_sec", "label": "Q3 第三节", "color": "#E10600"},
]


def _fmt_lap_time(sec):
    if pd.isna(sec) or sec is None or sec == 0:
        return None
    s = float(sec)
    return f"{int(s // 60)}:{s % 60:06.3f}"


def query(sql: str) -> pd.DataFrame:
    db = sqlite3.connect(str(DB_PATH))
    df = pd.read_sql_query(sql, db)
    db.close()
    return df


_DB_NAME_CACHE = None


def _load_db_names():
    global _DB_NAME_CACHE
    if _DB_NAME_CACHE is not None:
        return _DB_NAME_CACHE
    _DB_NAME_CACHE = {}
    try:
        db = sqlite3.connect(str(DB_PATH))
        for row in db.execute("SELECT driver, full_name FROM driver_names"):
            _DB_NAME_CACHE[row[0]] = row[1]
        db.close()
    except Exception:
        pass
    return _DB_NAME_CACHE


def _dname(drv):
    s = DRIVER_CN.get(drv)
    if s:
        return s
    names = _load_db_names()
    full = names.get(drv)
    if full:
        return auto_cn_short(drv, full)
    return drv


def _dfull(drv):
    s = DRIVER_FULL_CN.get(drv)
    if s:
        return s
    names = _load_db_names()
    full = names.get(drv)
    if full:
        return auto_cn_full(drv, full)
    return drv


def _tname(tm):
    return TEAM_CN.get(tm, tm)


def _ename(ev):
    return EVENT_CN.get(ev, ev)


def _lname(loc):
    return LOCATION_CN.get(loc, loc)


def _cname(cty):
    return COUNTRY_CN.get(cty, cty)


def _tfull(tm):
    return TEAM_FULL_CN.get(tm, tm)


def _comp(c):
    s = str(c)
    if s in ("", "nan", "None"):
        return "无数据"
    return COMPOUND_CN.get(s, s)


def _get_years():
    return sorted(query("SELECT DISTINCT year FROM events")["year"].tolist(), reverse=True)


F1_RED = "#E10600"

SCROLL_TOP_JS = """
<script>
(function(){
    var n=0;var t=setInterval(function(){
        window.scrollTo(0,0);
        var e=document.querySelector('[data-testid="stAppViewContainer"]');
        if(e)e.scrollTop=0;
        n+=30;if(n>600){clearInterval(t);}
    },30);
})();
</script>
"""


def _chart_style(fig, height=400, **kwargs):
    fig.update_layout(
        template="plotly_white",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#333333", family="Inter, sans-serif"),
        title=dict(font=dict(size=16, color="#1A1A1A")),
        margin=dict(l=20, r=20, t=50, b=20),
        height=height,
        legend=dict(font=dict(color="#555555")),
        **kwargs
    )
    fig.update_xaxes(gridcolor="rgba(0,0,0,0.06)", zeroline=False)
    fig.update_yaxes(gridcolor="rgba(0,0,0,0.06)", zeroline=False)
    return fig


# ============================================================
# Sidebar
# ============================================================
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

# ============================================================
# PAGE 1: Season Overview
# ============================================================
if st.session_state.page == "赛季总览":
    st.markdown(SCROLL_TOP_JS, unsafe_allow_html=True)
    st.title(f"📊 {year} 赛季总览")

    # Raw data
    raw_drv = query(f"""
        SELECT r.driver, r.team,
               COALESCE(SUM(r.points),0) +
               COALESCE((SELECT SUM(sp.points) FROM sprint_points sp
                         WHERE sp.driver COLLATE NOCASE = r.driver COLLATE NOCASE
                         AND sp.year={year}), 0) as pts,
               COUNT(*) as races,
               SUM(CASE WHEN r.position<=3 THEN 1 ELSE 0 END) as podiums,
               SUM(CASE WHEN r.position=1 THEN 1 ELSE 0 END) as wins,
               ROUND(AVG(r.grid), 1) as avg_grid,
               ROUND(AVG(r.position), 1) as avg_fin
        FROM results r WHERE r.year={year}
        GROUP BY r.driver ORDER BY pts DESC, podiums DESC, wins DESC
    """)
    raw_drv["pts"] = raw_drv["pts"].astype(float)
    raw_drv["车手"] = raw_drv["driver"].apply(_dname)
    raw_drv["车队"] = raw_drv["team"].apply(_tname)


    st.subheader("车手积分榜")
    drv_all = raw_drv
    badges = ["🥇 ", "🥈 ", "🥉 "]
    for i in range(min(3, len(drv_all))):
        drv_all.at[drv_all.index[i], "车手"] = badges[i] + drv_all.at[drv_all.index[i], "车手"]
    drv_order = drv_all.sort_values(["pts", "podiums", "wins"], ascending=True)["车手"].tolist()
    drv_colors = [TEAM_COLORS.get(drv_all.iloc[i]["team"], F1_RED) for i in range(len(drv_all))]
    fig = px.bar(drv_all, x="pts", y="车手", orientation="h",
                 title="🥇 车手积分榜", text="pts")
    fig = _chart_style(fig, height=max(300, len(drv_all) * 28 + 80))
    fig.update_layout(xaxis_title="积分", yaxis_title="",
                       showlegend=False)
    fig.update_traces(marker_color=drv_colors, width=0.7,
                      texttemplate="%{text:.0f}", textposition="outside",
                      textfont=dict(color="#555555", size=11))
    fig.update_yaxes(categoryarray=drv_order)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("车队积分榜")
    raw_team = query(f"""
        SELECT team, SUM(pts) as pts, SUM(wins) as wins FROM (
            SELECT r.team, r.driver,
                   SUM(r.points) + COALESCE(
                     (SELECT SUM(sp.points) FROM sprint_points sp
                      WHERE sp.driver COLLATE NOCASE = r.driver COLLATE NOCASE
                      AND sp.year={year}), 0) as pts,
                   SUM(CASE WHEN r.position=1 THEN 1 ELSE 0 END) as wins
            FROM results r WHERE r.year={year}
            GROUP BY r.team, r.driver
        ) GROUP BY team ORDER BY pts DESC, wins DESC
    """)
    raw_team["pts"] = raw_team["pts"].astype(float)
    raw_team["车队"] = raw_team["team"].apply(_tname)
    badges = ["🥇 ", "🥈 ", "🥉 "]
    for i in range(min(3, len(raw_team))):
        raw_team.at[raw_team.index[i], "车队"] = badges[i] + raw_team.at[raw_team.index[i], "车队"]
    team_order = raw_team.sort_values(["pts", "wins"], ascending=True)["车队"].tolist()
    team_colors = [TEAM_COLORS.get(raw_team.iloc[i]["team"], F1_RED) for i in range(len(raw_team))]
    fig = px.bar(raw_team, x="pts", y="车队", orientation="h",
                 title="🏆 车队积分榜", text="pts")
    fig = _chart_style(fig, height=max(300, len(raw_team) * 28 + 80))
    fig.update_layout(xaxis_title="积分", yaxis_title="",
                       showlegend=False)
    fig.update_traces(marker_color=team_colors, width=0.7,
                      texttemplate="%{text:.0f}", textposition="outside",
                      textfont=dict(color="#555555", size=11))
    fig.update_yaxes(categoryarray=team_order)
    st.plotly_chart(fig, use_container_width=True)

    st.subheader("车手数据明细")
    raw_drv["车手全名"] = raw_drv["driver"].apply(_dfull)
    trows = ""
    badges = ["🥇", "🥈", "🥉"]
    borders = ["#FFD700", "#C0C0C0", "#CD7F32"]
    for idx, (_, r) in enumerate(raw_drv.iterrows()):
        badge = badges[idx] if idx < 3 else ""
        bd = f"border-left:3px solid {borders[idx]};" if idx < 3 else ""
        bg = "#FFFEFA" if idx == 0 else "#fff"
        tc = TEAM_COLORS.get(r["team"], F1_RED)
        trows += f"""<tr style="background:{bg};{bd}">
            <td style="padding:6px 8px;"><span style="color:{tc};font-weight:600;">{r['车手全名']}</span></td>
            <td style="text-align:center;padding:6px 8px;font-weight:600;">{badge} {r['pts']:.0f}</td>
            <td style="text-align:center;padding:6px 8px;">{int(r['races'])}</td>
            <td style="text-align:center;padding:6px 8px;">{int(r['wins'])}</td>
            <td style="text-align:center;padding:6px 8px;">{int(r['podiums'])}</td>
            <td style="text-align:center;padding:6px 8px;">{r['avg_grid']}</td>
            <td style="text-align:center;padding:6px 8px;">{r['avg_fin']}</td></tr>"""
    st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
    <thead><tr style="background:#E10600;color:#fff;font-weight:600;">
    <th style="padding:8px;">车手</th><th style="padding:8px;">积分</th>
    <th style="padding:8px;">参赛</th><th style="padding:8px;">冠军</th>
    <th style="padding:8px;">领奖台</th><th style="padding:8px;">平均发车</th>
    <th style="padding:8px;">平均完赛</th></tr></thead>
    <tbody>{trows}</tbody></table>""", unsafe_allow_html=True)

    st.subheader("冠军积分争夺走势")
    top5 = raw_drv.sort_values(["pts", "podiums", "wins"], ascending=False).head(5)["driver"].tolist()
    ev = query(f"""
        SELECT r.round, r.driver, r.points, e.event_name,
               SUM(r.points) OVER (PARTITION BY r.driver ORDER BY r.round) +
               COALESCE((SELECT SUM(sp.points) FROM sprint_points sp
                         WHERE sp.driver COLLATE NOCASE = r.driver COLLATE NOCASE
                         AND sp.year={year} AND sp.round <= r.round), 0) as total
        FROM results r JOIN events e USING(year, round)
        WHERE r.year={year} AND r.driver IN ({','.join(repr(d) for d in top5)})
    """)
    ev["车手"] = ev["driver"].apply(_dname)
    ev["车手简"] = ev["driver"].apply(_dfull)
    ev["站名"] = ev["event_name"].apply(_ename)
    fig = px.line(ev, x="round", y="total", color="车手",
                  title="积分累计走势（TOP 5）", markers=True,
                  custom_data=["车手简", "站名"],
                  labels={"round": "第 X 站", "total": "累计积分"})
    fig.update_traces(
        hovertemplate="车手：%{customdata[0]}<br>第%{x}站：%{customdata[1]}<br>积分：%{y:.0f}<extra></extra>"
    )
    fig.data = sorted(fig.data, key=lambda t: t.y[-1], reverse=True)
    for trace in fig.data:
        x_last = trace.x[-1]
        y_last = trace.y[-1]
        fig.add_annotation(x=x_last, y=y_last,
                           text=f"  {trace.name} {y_last:.0f}  ",
                           showarrow=False, xanchor="left", xshift=6,
                           font=dict(color=trace.line.color, size=10),
                           bgcolor="rgba(255,255,255,0.85)",
                           borderpad=2)
    fig = _chart_style(fig, height=500)
    fig.update_layout(xaxis_title="第 X 站", yaxis_title="累计积分",
                      hovermode="x unified")
    fig.update_xaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                     spikethickness=1, spikecolor="rgba(128,128,128,0.4)")
    st.plotly_chart(fig, use_container_width=True)

# ============================================================
# PAGE 2: Race Browser
# ============================================================
elif st.session_state.page == "分站详情":
    st.markdown(SCROLL_TOP_JS, unsafe_allow_html=True)
    st.title(f"🔍 {year} 分站详情")

    races = query(f"""
        SELECT round, event_name, country, location FROM events
        WHERE year={year} AND round > 0 ORDER BY round
    """)
    race_label = {r["round"]: f"第{NUM_CN[r['round']]}站  {_ename(r['event_name'])}" for _, r in races.iterrows()}
    selected_round = st.selectbox("选择比赛", list(race_label.keys()),
                                   format_func=lambda x: race_label[x])

    race_info = races[races["round"] == selected_round].iloc[0]
    c1, c2 = st.columns(2)
    c1.metric("赛道", _lname(race_info["location"]))
    c2.metric("国家", _cname(race_info["country"]))

    w = query(f"SELECT * FROM weather WHERE year={year} AND round={selected_round}")
    if not w.empty:
        air = w["air_temp_avg"].iloc[0]
        trk = w["track_temp_avg"].iloc[0]
        hum = w["humidity_avg"].iloc[0]
        rain = w["had_rain"].iloc[0]
        w1, w2, w3, w4 = st.columns(4)
        with w1:
            st.markdown(f"""<div style="background:#fff;border-radius:10px;padding:14px;border-top:3px solid #E10600;border:1px solid #E8E8E8;">
            <div style="color:#888;font-size:0.75rem;">🌡️ 气温</div>
            <div style="font-size:1.4rem;font-weight:700;">{air:.1f}°C</div>
            <div style="background:#eee;height:4px;border-radius:2px;margin-top:8px;">
            <div style="background:#E10600;height:4px;border-radius:2px;width:{min(air/50*100,100)}%"></div></div></div>""", unsafe_allow_html=True)
        with w2:
            st.markdown(f"""<div style="background:#fff;border-radius:10px;padding:14px;border-top:3px solid #FF8C00;border:1px solid #E8E8E8;">
            <div style="color:#888;font-size:0.75rem;">🏁 赛道温度</div>
            <div style="font-size:1.4rem;font-weight:700;">{trk:.1f}°C</div>
            <div style="background:#eee;height:4px;border-radius:2px;margin-top:8px;">
            <div style="background:#FF8C00;height:4px;border-radius:2px;width:{min(trk/60*100,100)}%"></div></div></div>""", unsafe_allow_html=True)
        with w3:
            st.markdown(f"""<div style="background:#fff;border-radius:10px;padding:14px;border-top:3px solid #1E90FF;border:1px solid #E8E8E8;">
            <div style="color:#888;font-size:0.75rem;">💧 湿度</div>
            <div style="font-size:1.4rem;font-weight:700;">{hum:.0f}%</div>
            <div style="background:#eee;height:4px;border-radius:2px;margin-top:8px;">
            <div style="background:#1E90FF;height:4px;border-radius:2px;width:{min(hum,100)}%"></div></div></div>""", unsafe_allow_html=True)
        with w4:
            rain_icon = "🌧️" if rain else "☀️"
            rain_label = "有雨" if rain else "无雨"
            rain_color = "#1E90FF" if rain else "#FFB800"
            st.markdown(f"""<div style="background:#fff;border-radius:10px;padding:14px;border-top:3px solid {rain_color};border:1px solid #E8E8E8;">
            <div style="color:#888;font-size:0.75rem;">{rain_icon} 天气</div>
            <div style="font-size:1.4rem;font-weight:700;">{rain_label}</div>
            <div style="height:4px;margin-top:8px;"></div></div>""", unsafe_allow_html=True)

    fp_data = query(f"""
        SELECT s.driver, s.session_type, s.best_lap_sec, s.laps_count, s.position, r.team
        FROM sessions s LEFT JOIN results r ON s.year=r.year AND s.round=r.round
            AND s.driver COLLATE NOCASE = r.driver COLLATE NOCASE
        WHERE s.year={year} AND s.round={selected_round}
        ORDER BY s.session_type,
            CASE WHEN s.position IS NULL THEN 1 ELSE 0 END,
            s.position
    """)
    if not fp_data.empty:
        st.subheader("练习赛成绩")
        available_types = set(fp_data["session_type"].unique())
        available = [ps for ps in PRACTICE_SESSIONS if ps["type"] in available_types]
        if not available:
            available = [ps for ps in PRACTICE_SESSIONS if ps["type"] == "FP1"]
        cols = st.columns(len(available))
        for ci, ps in enumerate(available):
            subset = fp_data[fp_data["session_type"] == ps["type"]]
            with cols[ci]:
                if subset.empty:
                    st.caption(f"{ps['label']}: 暂无数据")
                    continue
                rows = ""
                for _, r in subset.iterrows():
                    t = r["best_lap_sec"]
                    if t and t > 0:
                        ft = _fmt_lap_time(t)
                        p_str = str(int(r["position"]))
                    else:
                        laps = int(r["laps_count"]) if r["laps_count"] else 0
                        ft = "无数据" if laps > 0 else "未出场"
                        p_str = "—"
                    rows += f"""<tr style="background:#fff;">
                        <td style="text-align:center;padding:4px 6px;">{p_str}</td>
                        <td style="padding:4px 6px;">
                            <span style="color:{TEAM_COLORS.get(r['team'],'#333')};font-size:0.8rem;">{_dname(r['driver'])}</span></td>
                        <td style="text-align:center;padding:4px 6px;">{ft}</td>
                        <td style="text-align:center;padding:4px 6px;">{int(r['laps_count'])}</td></tr>"""
                st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">
                <thead><tr style="background:{ps['color']};color:#fff;font-weight:600;">
                <th style="padding:5px 6px;">#</th><th style="padding:5px 6px;">{ps['label']}</th>
                <th style="padding:5px 6px;">圈速</th><th style="padding:5px 6px;">圈</th></tr></thead>
                <tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    is_2122_sprint = False
    if year in (2021, 2022):
        is_2122_sprint = not query(f"SELECT 1 FROM sprint_points WHERE year={year} AND round={selected_round} LIMIT 1").empty

    quali = query(f"""
        SELECT r.driver, r.q1_sec, r.q2_sec, r.q3_sec, r.quali_pos, r.team
        FROM results r WHERE r.year={year} AND r.round={selected_round}
    """)
    has_quali = not quali.empty and quali["q1_sec"].notna().any()
    if has_quali:
        st.subheader("排位赛成绩")
        if is_2122_sprint:
            st.caption("※ 本场排位赛决定冲刺赛发车顺序")
        for ph in QUALI_PHASES:
            quali[ph["key"] + "s"] = quali[ph["col"]].apply(_fmt_lap_time)

        q_order_maps = {}
        for ph in QUALI_PHASES:
            if ph["key"] == "Q1":
                q_order_maps[ph["key"]] = quali.sort_values(ph["col"], na_position="last")
            else:
                q_order_maps[ph["key"]] = quali[quali[ph["col"]].notna()].sort_values(ph["col"])

        cols = st.columns(len(QUALI_PHASES))
        for ci, ph in enumerate(QUALI_PHASES):
            subset = q_order_maps[ph["key"]]
            with cols[ci]:
                if subset.empty:
                    st.caption(f"{ph['label']}: 暂无数据")
                    continue
                rows = ""
                for seq, (_, r) in enumerate(subset.iterrows(), 1):
                    t = r[ph["key"] + "s"]
                    if t:
                        p_str = str(seq)
                    else:
                        p_str = "—"
                        t = "—"
                    rows += f"""<tr style="background:#fff;">
                        <td style="text-align:center;padding:4px 6px;">{p_str}</td>
                        <td style="padding:4px 6px;">
                            <span style="color:{TEAM_COLORS.get(r['team'],'#333')};font-size:0.8rem;">{_dname(r['driver'])}</span></td>
                        <td style="text-align:center;padding:4px 6px;">{t}</td></tr>"""
                st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">
                <thead><tr style="background:{ph['color']};color:#fff;font-weight:600;">
                <th style="padding:5px 6px;">#</th><th style="padding:5px 6px;">{ph['label']}</th>
                <th style="padding:5px 6px;">圈速</th></tr></thead>
                <tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    sprint_data = query(f"""
        SELECT sp.driver, sp.position, sp.points, sp.sq_pos, r.team
        FROM sprint_points sp JOIN results r ON sp.year=r.year AND sp.round=r.round
            AND sp.driver COLLATE NOCASE = r.driver COLLATE NOCASE
        WHERE sp.year={year} AND sp.round={selected_round}
        ORDER BY sp.position
    """)
    if not sprint_data.empty:
        st.subheader("冲刺赛")
        if is_2122_sprint:
            st.caption("※ 冲刺赛名次决定正赛发车顺序")
        sp_rows = ""
        for _, r in sprint_data.iterrows():
            pos = r["position"]
            pdm = int(pos) if pd.notna(pos) else 99
            if pdm == 1:
                bd = "#FFD700"
            elif pdm == 2:
                bd = "#C0C0C0"
            elif pdm == 3:
                bd = "#CD7F32"
            else:
                bd = "transparent"
            sq = int(r["sq_pos"]) if pd.notna(r["sq_pos"]) else "—"
            pts = int(r["points"]) if pd.notna(r["points"]) else 0
            sp_rows += f"""<tr style="background:#fff;border-left:3px solid {bd};">
                <td style="text-align:center;padding:6px 8px;">{pos}</td>
                <td style="padding:6px 8px;">{_dfull(r['driver'])}</td>
                <td style="padding:6px 8px;">{_tfull(r['team'])}</td>
                <td style="text-align:center;padding:6px 8px;">{sq}</td>
                <td style="text-align:center;padding:6px 8px;">{pts}</td></tr>"""
        st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
        <thead><tr style="background:#E10600;color:#fff;font-weight:600;">
        <th style="padding:8px;">名次</th><th style="padding:8px;">车手</th>
        <th style="padding:8px;">车队</th><th style="padding:8px;">发车</th>
        <th style="padding:8px;">积分</th>
        </tr></thead><tbody>{sp_rows}</tbody></table>""", unsafe_allow_html=True)

    st.subheader("正赛")
    res = query(f"""
        SELECT position, driver, team, grid, points, status
        FROM results WHERE year={year} AND round={selected_round}
        ORDER BY position
    """)
    res["车手"] = res["driver"].apply(_dfull)
    res["车队"] = res["team"].apply(_tfull)
    res["状态"] = res["status"].apply(lambda s: STATUS_CN.get(str(s), str(s)))
    rows = ""
    for _, r in res.iterrows():
        pos = r["position"]
        finished = str(r["status"]) == "Finished"
        pdm = int(pos) if pd.notna(pos) else 99
        if pdm == 1:
            bd = "#FFD700"
        elif pdm == 2:
            bd = "#C0C0C0"
        elif pdm == 3:
            bd = "#CD7F32"
        else:
            bd = "transparent"
        bg = "#fff" if finished else "#FFF0F0"
        rows += f"""<tr style="background:{bg};border-left:3px solid {bd};">
            <td style="text-align:center;padding:6px 8px;">{pos}</td>
            <td style="padding:6px 8px;">{r['车手']}</td>
            <td style="padding:6px 8px;">{r['车队']}</td>
            <td style="text-align:center;padding:6px 8px;">{r['grid']}</td>
            <td style="text-align:center;padding:6px 8px;">{r['points']}</td>
            <td style="text-align:center;padding:6px 8px;">{r['状态']}</td></tr>"""
    st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
    <thead><tr style="background:#E10600;color:#fff;font-weight:600;">
    <th style="padding:8px;">名次</th><th style="padding:8px;">车手</th>
    <th style="padding:8px;">车队</th><th style="padding:8px;">发车</th>
    <th style="padding:8px;">积分</th><th style="padding:8px;">状态</th>
    </tr></thead><tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    st.subheader("圈速对比")
    all_laps = query(f"""
        SELECT l.driver, l.lap_number, l.lap_time, r.team
        FROM laps l JOIN results r ON l.year=r.year AND l.round=r.round
          AND l.driver COLLATE NOCASE = r.driver COLLATE NOCASE
        WHERE l.year={year} AND l.round={selected_round} AND l.lap_time>0
          AND l.lap_number>0
        ORDER BY l.lap_number
    """)
    if not all_laps.empty:
        all_drivers = all_laps[["driver","team"]].drop_duplicates()
        all_drivers["label"] = all_drivers["driver"].apply(_dfull)
        all_drivers = all_drivers.sort_values("driver")

        st.caption("勾选车手对比圈速（最多 5 人）")
        checked = []
        cols = st.columns(4)
        for i, (_, dr) in enumerate(all_drivers.iterrows()):
            with cols[i % 4]:
                if st.checkbox(dr["label"], key=f"cb_{selected_round}_{dr['driver']}"):
                    checked.append((dr["driver"], dr["label"], dr["team"]))

        if len(checked) > 5:
            st.warning(f"最多选 5 人，当前已选 {len(checked)} 人")
        elif checked:
            df = all_laps[all_laps["driver"].isin([c[0] for c in checked])].copy()
            df["车手"] = df["driver"].apply(_dfull)
            df["圈速文本"] = df["lap_time"].apply(
                lambda s: f"{int(s//60)}分{s%60:06.3f}秒"
            )
            color_map = {c[1]: TEAM_COLORS.get(c[2], "#888888") for c in checked}

            fig = px.line(df, x="lap_number", y="lap_time", color="车手",
                          title=f"圈速对比 — {_ename(race_info['event_name'])}",
                          color_discrete_map=color_map,
                          labels={"lap_number": "圈数", "lap_time": "圈速"},
                          custom_data=["圈速文本"])
            fig.update_traces(
                hovertemplate="车手：%{fullData.name}<br>第%{x}圈<br>圈速：%{customdata[0]}<extra></extra>"
            )
            y_max = df["lap_time"].max() * 1.05
            tick_count = 8
            tick_step = max(0.5, np.ceil(y_max / tick_count))
            ticks = np.arange(0, y_max + tick_step, tick_step)
            tick_labels = []
            for v in ticks:
                mins = int(v // 60)
                secs = v % 60
                tick_labels.append(f"{mins}:{secs:04.1f}")
            fig = _chart_style(fig, height=480)
            fig.update_layout(
                yaxis=dict(tickmode="array", tickvals=ticks.tolist(),
                           ticktext=tick_labels, title="圈速"),
                xaxis=dict(title="圈数", dtick=5),
                hovermode="x unified")
            fig.update_xaxes(showspikes=True, spikemode="across",
                             spikesnap="cursor", spikethickness=1,
                             spikecolor="rgba(128,128,128,0.4)")
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("各车手轮胎使用量与类型")
    compounds = query(f"""
        SELECT driver, compound, COUNT(*) as laps
        FROM laps WHERE year={year} AND round={selected_round}
        GROUP BY driver, compound ORDER BY driver, compound
    """)
    if not compounds.empty:
        compounds["车手"] = compounds["driver"].apply(_dfull)
        compounds["配方"] = compounds["compound"].apply(_comp)
        fig = px.bar(compounds, x="车手", y="laps", color="配方",
                     title="各车手轮胎使用量与类型", barmode="stack",
                     color_discrete_map=COMPOUND_COLORS,
                     labels={"laps": "圈数"})
        fig = _chart_style(fig, height=350)
        fig.update_layout(xaxis_title="", yaxis_title="圈数")
        fig.update_traces(marker_line_color="rgba(0,0,0,0.25)", marker_line_width=1)
        st.plotly_chart(fig, use_container_width=True)

# ============================================================
# PAGE 3: Driver Profile
# ============================================================
elif st.session_state.page == "车手档案":
    st.markdown(SCROLL_TOP_JS, unsafe_allow_html=True)
    st.title("👤 车手档案")

    drivers = query(f"""
        SELECT DISTINCT driver, full_name FROM results WHERE year={year}
        ORDER BY driver
    """)
    selected_driver = st.selectbox("选择车手", drivers["driver"].tolist(),
                                    format_func=lambda d: _dname(d))

    stats = query(f"""
        SELECT COUNT(*) as races,
               SUM(r.points) + COALESCE(
                 (SELECT SUM(sp.points) FROM sprint_points sp
                  WHERE sp.driver='{selected_driver}' AND sp.year={year}), 0) as pts,
               SUM(CASE WHEN r.position=1 THEN 1 ELSE 0 END) as wins,
               SUM(CASE WHEN r.position<=3 THEN 1 ELSE 0 END) as podiums,
               ROUND(AVG(r.grid), 1) as avg_grid,
               ROUND(AVG(r.position), 1) as avg_fin
        FROM results r WHERE r.year={year} AND r.driver='{selected_driver}'
    """).iloc[0]

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    stats_items = [
        ("🏁", "参赛", int(stats["races"])),
        ("📊", "积分", int(stats["pts"])),
        ("🏆", "冠军", int(stats["wins"])),
        ("🏅", "领奖台", int(stats["podiums"])),
        ("📍", "平均发车", stats["avg_grid"]),
        ("🏎️", "平均完赛", stats["avg_fin"]),
    ]
    for (icon, label, val), col in zip(stats_items, [c1, c2, c3, c4, c5, c6]):
        with col:
            st.markdown(f"""<div style="background:#fff;border-radius:10px;padding:14px;
                border-top:3px solid #E10600;border:1px solid #E8E8E8;">
                <div style="color:#888;font-size:0.75rem;">{icon} {label}</div>
                <div style="font-size:1.3rem;font-weight:700;">{val}</div></div>""",
                unsafe_allow_html=True)

    st.subheader("各站成绩")
    dres = query(f"""
        SELECT r.round, e.event_name, r.position, r.grid, r.points, r.status
        FROM results r JOIN events e USING(year, round)
        WHERE r.year={year} AND r.driver='{selected_driver}'
        ORDER BY r.round
    """)
    dres["站"] = dres["round"].apply(lambda x: f"第{NUM_CN[x]}站")
    dres["比赛"] = dres["event_name"].apply(_ename)
    dres["状态"] = dres["status"].apply(lambda s: STATUS_CN.get(str(s), str(s)))
    rows = ""
    for _, r in dres.iterrows():
        pos = r["position"]
        pdm = int(pos) if pd.notna(pos) else 99
        sts_raw = str(r["status"])
        if pdm == 1:
            bg = "rgba(0,180,0,0.15)"
        elif 2 <= pdm <= 3:
            bg = "rgba(0,180,0,0.08)"
        elif 4 <= pdm <= 5:
            bg = "rgba(0,180,0,0.04)"
        elif 6 <= pdm <= 10:
            bg = "#fff"
        elif 11 <= pdm <= 15:
            bg = "rgba(200,150,0,0.08)"
        elif pdm >= 16:
            bg = "rgba(200,0,0,0.06)"
        else:
            bg = "#fff"
        if sts_raw != "Finished" and not sts_raw.startswith("+"):
            bg = "rgba(200,0,0,0.12)"
        rows += f"""<tr style="background:{bg};">
            <td style="text-align:center;padding:6px 8px;">{r['站']}</td>
            <td style="padding:6px 8px;">{r['比赛']}</td>
            <td style="text-align:center;padding:6px 8px;">{pos}</td>
            <td style="text-align:center;padding:6px 8px;">{r['grid']}</td>
            <td style="text-align:center;padding:6px 8px;">{r['points']}</td>
            <td style="text-align:center;padding:6px 8px;">{r['状态']}</td></tr>"""
    st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
    <thead><tr style="background:#E10600;color:#fff;font-weight:600;">
    <th style="padding:8px;">站</th><th style="padding:8px;">比赛</th>
    <th style="padding:8px;">名次</th><th style="padding:8px;">发车</th>
    <th style="padding:8px;">积分</th><th style="padding:8px;">状态</th>
    </tr></thead><tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("排名走势")
        if not dres.empty:
            dres["比赛名"] = dres["event_name"].apply(_ename)
            fig = px.line(dres, x="round", y="position",
                          title="各站排名变化", markers=True,
                          color_discrete_sequence=[F1_RED],
                          custom_data=["比赛名", "position"])
            fig.update_traces(
                hovertemplate="第%{x}站 %{customdata[0]}<br>名次：第%{y}名<extra></extra>"
            )
            fig = _chart_style(fig, height=350)
            fig.update_layout(yaxis=dict(autorange="reversed"),
                               xaxis_title="站", yaxis_title="名次",
                               hovermode="x unified")
            fig.update_xaxes(showspikes=True, spikemode="across",
                              spikesnap="cursor", spikethickness=1,
                              spikecolor="rgba(128,128,128,0.4)", dtick=1)
            fig.add_hline(y=3, line_dash="dash", line_color="rgba(0,0,0,0.3)",
                          annotation_text="领奖台", annotation_position="top right")
            st.plotly_chart(fig, use_container_width=True)

    with col_b:
        st.subheader("各站最快圈速")
        fl = query(f"""
            SELECT round, MIN(lap_time) as fastest
            FROM laps WHERE year={year} AND driver='{selected_driver}' AND lap_time>0
            GROUP BY round ORDER BY round
        """)
        if not fl.empty:
            fl["圈速文本"] = fl["fastest"].apply(
                lambda s: f"{int(s//60)}:{s%60:06.3f}"
            )
            y_max = fl["fastest"].max() * 1.05
            tick_count = 6
            tick_step = max(0.5, np.ceil(y_max / tick_count))
            ticks = np.arange(0, y_max + tick_step, tick_step)
            tick_labels = [f"{int(v//60)}:{v%60:04.1f}" for v in ticks]
            fig = px.bar(fl, x="round", y="fastest",
                         title="各站最快圈速",
                         color_discrete_sequence=[F1_RED],
                         custom_data=["圈速文本"])
            fig.update_traces(
                hovertemplate="第%{x}站<br>最快圈速：%{customdata[0]}<extra></extra>"
            )
            fig = _chart_style(fig, height=350)
            fig.update_layout(
                yaxis=dict(tickmode="array", tickvals=ticks.tolist(),
                            ticktext=tick_labels, title="圈速"),
                xaxis=dict(title="站", dtick=1))
            st.plotly_chart(fig, use_container_width=True)

# ============================================================
# PAGE 4: Track Analysis
# ============================================================
elif st.session_state.page == "赛道分析":
    st.markdown(SCROLL_TOP_JS, unsafe_allow_html=True)
    st.title("🏁 赛道分析")

    tracks = query(f"""
        SELECT DISTINCT location, country FROM events
        WHERE year={year} ORDER BY country
    """)
    track_names = tracks["location"].tolist()
    selected_track = st.selectbox("选择赛道", track_names, format_func=_lname)

    st.subheader(f"{_lname(selected_track)} 比赛结果")
    track_res = query(f"""
        SELECT r.position, r.driver, r.team, r.points, r.status
        FROM results r JOIN events e USING(year, round)
        WHERE r.year={year} AND e.location='{selected_track}'
        ORDER BY r.position
    """)
    if not track_res.empty:
        track_res["车手"] = track_res["driver"].apply(_dname)
        track_res["车队"] = track_res["team"].apply(_tname)
        track_res["状态"] = track_res["status"].apply(lambda s: STATUS_CN.get(str(s), str(s)))
        rows = ""
        for _, r in track_res.iterrows():
            pos = r["position"]
            finished = str(r["status"]) == "Finished"
            pdm = int(pos) if pd.notna(pos) else 99
            if pdm == 1:
                bd = "#FFD700"
            elif pdm == 2:
                bd = "#C0C0C0"
            elif pdm == 3:
                bd = "#CD7F32"
            else:
                bd = "transparent"
            bg = "#fff" if finished else "#FFF0F0"
            rows += f"""<tr style="background:{bg};border-left:3px solid {bd};">
                <td style="text-align:center;padding:6px 8px;">{pos}</td>
                <td style="padding:6px 8px;">{r['车手']}</td>
                <td style="padding:6px 8px;">{r['车队']}</td>
                <td style="text-align:center;padding:6px 8px;">{r['points']}</td>
                <td style="text-align:center;padding:6px 8px;">{r['状态']}</td></tr>"""
        st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
        <thead><tr style="background:#E10600;color:#fff;font-weight:600;">
        <th style="padding:8px;">名次</th><th style="padding:8px;">车手</th>
        <th style="padding:8px;">车队</th><th style="padding:8px;">积分</th><th style="padding:8px;">状态</th>
        </tr></thead><tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    st.subheader("赛道最快圈速排行")
    track_fl = query(f"""
        SELECT l.driver, MIN(l.lap_time) as fastest, r.team
        FROM laps l JOIN events e USING(year, round)
        JOIN results r ON l.year=r.year AND l.round=r.round
            AND l.driver COLLATE NOCASE = r.driver COLLATE NOCASE
        WHERE l.year={year} AND e.location='{selected_track}' AND l.lap_time>0
        GROUP BY l.driver ORDER BY fastest
    """)
    if not track_fl.empty:
        track_fl["车手"] = track_fl["driver"].apply(_dname)
        track_fl["圈速文本"] = track_fl["fastest"].apply(
            lambda s: f"{int(s//60)}:{s%60:06.3f}"
        )
        track_fl["车队色"] = track_fl["team"].apply(lambda t: TEAM_COLORS.get(t, "#888888"))
        top10 = track_fl.head(10)
        color_map = dict(zip(top10["车手"], top10["车队色"]))
        x_max = track_fl["fastest"].max() * 1.05
        tick_step = max(0.5, np.ceil(x_max / 6))
        ticks = np.arange(0, x_max + tick_step, tick_step)
        tick_labels = [f"{int(v//60)}:{v%60:04.1f}" for v in ticks]
        fig = px.bar(top10, x="fastest", y="车手", orientation="h",
                     title=f"{_lname(selected_track)} 最快圈速 TOP 10",
                     color="车手",
                     color_discrete_map=color_map,
                     custom_data=["圈速文本"])
        fig.update_traces(
            hovertemplate="%{customdata[0]}<extra>%{y}</extra>"
        )
        fig = _chart_style(fig, height=350)
        fig.update_layout(
            yaxis=dict(autorange="reversed"), showlegend=False,
            xaxis=dict(tickmode="array", tickvals=ticks.tolist(),
                        ticktext=tick_labels, title="圈速"))
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("赛季赛程表")
    cal = query(f"""
        SELECT e.round, e.event_name, e.location, e.event_date,
               r.team, r.driver, r.full_name
        FROM events e
        JOIN results r ON e.year=r.year AND e.round=r.round
        WHERE e.year={year} AND e.round>0 AND r.position=1
        ORDER BY e.round
    """)
    if not cal.empty:
        cal["事件名"] = cal["event_name"].apply(_ename)
        cal["赛道名"] = cal["location"].apply(_lname)
        cal["车队名"] = cal["team"].apply(_tname)
        cal["车手名"] = cal["driver"].apply(_dname)
        cal["日期"] = cal["event_date"].apply(lambda d: d[-5:] if len(str(d))>=10 else str(d))
        cal["色"] = cal["team"].apply(lambda t: TEAM_COLORS.get(t, "#888888"))

        cards = []
        for _, r in cal.iterrows():
            cards.append(f"""<div style="background:#fff;border-radius:8px;padding:10px 14px;
                border-left:4px solid {r['色']};margin-bottom:10px;
                box-shadow:0 1px 3px rgba(0,0,0,0.08);">
                <div style="font-size:0.72rem;color:#999;margin-bottom:2px;">
                    <span style="background:{r['色']};color:#fff;padding:1px 7px;
                        border-radius:4px;font-weight:600;font-size:0.68rem;">R{int(r['round'])}</span>
                    &nbsp;{r['事件名']}
                </div>
                <div style="font-size:0.75rem;color:#666;">{r['赛道名']}  ·  {r['日期']}</div>
                <div style="font-size:0.8rem;margin-top:3px;">
                    <span style="color:{r['色']};font-weight:600;">{r['车队名']}</span>
                    &nbsp;{r['车手名']}
                </div>
            </div>""")

        cols = st.columns(3)
        for col_idx in range(3):
            with cols[col_idx]:
                for i in range(col_idx, len(cards), 3):
                    st.markdown(cards[i], unsafe_allow_html=True)
