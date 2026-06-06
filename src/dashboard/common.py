"""F1 Oracle — shared constants, helpers, and database access."""

import sqlite3
import time
from pathlib import Path

import pandas as pd
import plotly.express as px
import numpy as np
import streamlit as st

from names_cn import auto_cn_short, auto_cn_full

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "f1_oracle.db"

__all__ = [
    # Database
    "query", "_query_stats",

    # Modules
    "pd", "np",

    # Chinese maps
    "NUM_CN", "STATUS_CN",
    "DRIVER_CN", "DRIVER_FULL_CN",
    "TEAM_CN", "TEAM_FULL_CN", "TEAM_COLORS",
    "EVENT_CN", "LOCATION_CN", "COUNTRY_CN",
    "COMPOUND_CN", "COMPOUND_COLORS",

    # Session constants
    "PRACTICE_SESSIONS", "QUALI_PHASES",

    # Styling
    "F1_RED", "SCROLL_TOP_JS",

    # Helper functions
    "_fmt_lap_time",
    "_dname", "_dfull",
    "_tname", "_ename", "_lname", "_cname", "_tfull", "_comp",
    "_chart_style", "_get_years",
]


# ═══════════════════════════════════════════════════════════
# Cached database layer
# ═══════════════════════════════════════════════════════════

@st.cache_resource
def _get_connection():
    """Single SQLite connection reused for the entire user session.

    check_same_thread=False is needed because Streamlit's multi-page mode
    may run different pages on different threads.
    """
    db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")
    return db


_query_misses = 0
_query_total_ms = 0.0


def _query_stats():
    """Return (miss_count, total_ms) for the current session."""
    return _query_misses, _query_total_ms


@st.cache_data
def query(sql: str) -> pd.DataFrame:
    """Run a read-only SQL query against the F1 data warehouse.

    Results are cached for the entire session (data is read-only, no TTL needed).
    Same SQL returns instantly on reruns.
    """
    global _query_misses, _query_total_ms
    _query_misses += 1
    t0 = time.perf_counter()
    db = _get_connection()
    result = pd.read_sql_query(sql, db)
    elapsed = (time.perf_counter() - t0) * 1000
    _query_total_ms += elapsed
    return result


# ═══════════════════════════════════════════════════════════
# Chinese name maps
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# Helper functions
# ═══════════════════════════════════════════════════════════

def _fmt_lap_time(sec):
    if pd.isna(sec) or sec is None or sec == 0:
        return None
    s = float(sec)
    return f"{int(s // 60)}:{s % 60:06.3f}"


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
