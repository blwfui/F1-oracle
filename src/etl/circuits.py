"""赛道维表：规范身份 + 静态几何 + 历史统计。

构建 `circuits` 与 `circuit_aliases` 两张表。

## 为什么需要
`events.location` 存在"同一物理赛道多种写法"：
    Monaco / Monte Carlo · Yas Island / Yas Marina
    Miami / Miami Gardens · Marina Bay / Singapore
直接按 location 分组会把样本劈开（35 个名字 → 实为 31 条赛道）。

## 几何数据从哪来
`fastf1.mvapi.get_circuit_info()` —— 走 MultiViewer 公开 API 取一个小 JSON。
**不需要下载遥测**（position/car data 每个赛站约 110 MB）。
31 条赛道 = 31 个小请求，之后由 FastF1 缓存。

## 泄漏纪律（重要）
本表写入的 races / pole_win_* / move_n / dnf_* / rain_* 是
2018-2025 **全历史**汇总，只用于展示，**禁止直接当模型特征**。
预测第 n 站只能看到 round < n 的数据。
请调用 `circuit_stats_asof()` 按轮次过滤重算。

用法：
    python -m src.etl.circuits            # 全部 31 条
    python -m src.etl.circuits --no-geo   # 跳过网络，只建身份+统计
"""

from __future__ import annotations

import json
import logging
import math
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.etl.schema import SCHEMA_SQL  # noqa: E402
from src.semantics import is_dnf  # noqa: E402

DB_PATH = ROOT / "data" / "f1_oracle.db"
CACHE_DIR = ROOT / "data" / "cache"

logging.basicConfig(level=logging.WARNING, format="%(message)s")
log = logging.getLogger("circuits")

# ═══════════════════════════════════════════════════════════
# 规范映射
# ═══════════════════════════════════════════════════════════

# events.location 里的别名 → 规范 location
LOCATION_ALIASES = {
    "Monte Carlo": "Monaco",
    "Yas Island": "Yas Marina",
    "Miami Gardens": "Miami",
    "Singapore": "Marina Bay",
}

# 国家标签归一（events.country 同样存在多写法）
COUNTRY_ALIASES = {
    "Great Britain": "United Kingdom",
    "Abu Dhabi": "United Arab Emirates",
}

# 规范 location → (官方赛道名, 中文名, 国家, 国家中文)
CIRCUIT_META = {
    "Austin":            ("Circuit of the Americas",                  "美洲赛道",              "United States",  "美国"),
    "Baku":              ("Baku City Circuit",                        "巴库城市赛道",          "Azerbaijan",     "阿塞拜疆"),
    "Barcelona":         ("Circuit de Barcelona-Catalunya",           "巴塞罗那-加泰罗尼亚赛道", "Spain",         "西班牙"),
    "Budapest":          ("Hungaroring",                              "亨格罗宁赛道",          "Hungary",        "匈牙利"),
    "Hockenheim":        ("Hockenheimring",                           "霍根海姆赛道",          "Germany",        "德国"),
    "Imola":             ("Autodromo Enzo e Dino Ferrari",            "伊莫拉赛道",            "Italy",          "意大利"),
    "Istanbul":          ("Istanbul Park",                            "伊斯坦布尔公园赛道",    "Turkey",         "土耳其"),
    "Jeddah":            ("Jeddah Corniche Circuit",                  "吉达滨海赛道",          "Saudi Arabia",   "沙特阿拉伯"),
    "Las Vegas":         ("Las Vegas Strip Circuit",                  "拉斯维加斯大道赛道",    "United States",  "美国"),
    "Le Castellet":      ("Circuit Paul Ricard",                      "保罗·里卡德赛道",       "France",         "法国"),
    "Lusail":            ("Lusail International Circuit",             "卢赛尔国际赛车场",      "Qatar",          "卡塔尔"),
    "Marina Bay":        ("Marina Bay Street Circuit",                "滨海湾市街赛道",        "Singapore",      "新加坡"),
    "Melbourne":         ("Albert Park Circuit",                      "阿尔伯特公园赛道",      "Australia",      "澳大利亚"),
    "Mexico City":       ("Autódromo Hermanos Rodríguez",             "罗德里格斯兄弟赛道",    "Mexico",         "墨西哥"),
    "Miami":             ("Miami International Autodrome",            "迈阿密国际赛车场",      "United States",  "美国"),
    "Monaco":            ("Circuit de Monaco",                        "蒙特卡洛赛道",          "Monaco",         "摩纳哥"),
    "Montréal":          ("Circuit Gilles Villeneuve",                "吉尔斯·维伦纽夫赛道",   "Canada",         "加拿大"),
    "Monza":             ("Autodromo Nazionale Monza",                "蒙扎国家赛车场",        "Italy",          "意大利"),
    "Mugello":           ("Mugello Circuit",                          "穆杰罗赛道",            "Italy",          "意大利"),
    "Nürburgring":       ("Nürburgring GP-Strecke",                   "纽博格林赛道",          "Germany",        "德国"),
    "Portimão":          ("Autódromo Internacional do Algarve",       "阿尔加维国际赛车场",    "Portugal",       "葡萄牙"),
    "Sakhir":            ("Bahrain International Circuit",            "巴林国际赛车场",        "Bahrain",        "巴林"),
    "Shanghai":          ("Shanghai International Circuit",           "上海国际赛车场",        "China",          "中国"),
    "Silverstone":       ("Silverstone Circuit",                      "银石赛道",              "United Kingdom", "英国"),
    "Sochi":             ("Sochi Autodrom",                           "索契赛道",              "Russia",         "俄罗斯"),
    "Spa-Francorchamps": ("Circuit de Spa-Francorchamps",             "斯帕-弗朗科尔尚赛道",   "Belgium",        "比利时"),
    "Spielberg":         ("Red Bull Ring",                            "红牛环赛道",            "Austria",        "奥地利"),
    "Suzuka":            ("Suzuka International Racing Course",       "铃鹿国际赛车场",        "Japan",          "日本"),
    "São Paulo":         ("Autódromo José Carlos Pace",               "若泽·卡洛斯·帕塞赛道",  "Brazil",         "巴西"),
    "Yas Marina":        ("Yas Marina Circuit",                       "亚斯码头赛道",          "United Arab Emirates", "阿联酋"),
    "Zandvoort":         ("Circuit Zandvoort",                        "赞德沃特赛道",          "Netherlands",    "荷兰"),
}

# 弯道角度阈值（Angle 为绝对值）
HAIRPIN_ANGLE = 150.0
FAST_ANGLE = 45.0

# MultiViewer 坐标单位：1 单位 = 0.1 m（分米）。
# 实测 16 条已知赛道 official/perimeter 比值 = 0.10085 ± 0.0005，
# 由全轮廓推算的单圈长度与官方值差 0.1%–2.0%。
COORD_UNIT_M = 0.1

# 上游 MultiViewer 数据集缺失的赛道（geometry 保持 NULL，避免写入错误数据）。
# Mugello：其 session_info 上报的 circuit Key=149 与 Jeddah 冲突，
# 而 FastF1 内置的"149→146"修正实际指向的是【国家】key（146=葡萄牙），
# 因此取不到。扫描 key 100-200 未找到 Mugello。
NO_GEOMETRY = {
    "mugello": "MultiViewer 数据集缺此赛道（上游 key 与 Jeddah 冲突）",
}

def canonical(location: str) -> str:
    """把 events.location 的原始写法映射到规范赛道名。"""
    return LOCATION_ALIASES.get(location, location)


def slug(name: str) -> str:
    """规范赛道名 → circuit_id。"""
    out = []
    for ch in name.lower():
        if ch.isascii() and (ch.isalnum() or ch == "-"):
            out.append(ch)
        elif ch in " -_":
            out.append("_")
    return "".join(out).strip("_")


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(str(DB_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    return db


# ═══════════════════════════════════════════════════════════
# 几何：MultiViewer API（小 JSON，无需遥测）
# ═══════════════════════════════════════════════════════════

def fetch_circuit_keys(db: sqlite3.Connection) -> dict[str, tuple[int, int, int]]:
    """为每条规范赛道取一个 (circuit_key, year, round)。

    优先取该赛道在库中【最新】的年份 —— 赛道布局会改
    （如 Barcelona 2023 拆掉末段减速弯），要的是当前布局。
    """
    import fastf1

    fastf1.Cache.enable_cache(str(CACHE_DIR))

    # 规范赛道 -> 最新的 (year, round)
    latest: dict[str, tuple[int, int]] = {}
    for loc, year, rnd in db.execute(
        "SELECT location, year, round FROM events WHERE round > 0"
    ):
        cid = canonical(loc)
        if cid not in latest or (year, rnd) > latest[cid]:
            latest[cid] = (year, rnd)

    keys: dict[str, tuple[int, int, int]] = {}
    for cid, (year, rnd) in sorted(latest.items()):
        if slug(cid) in NO_GEOMETRY:
            log.warning("  key  %-18s 跳过（%s）", cid, NO_GEOMETRY[slug(cid)])
            continue
        try:
            s = fastf1.get_session(year, rnd, "R")
            s.load(laps=False, telemetry=False, weather=False, messages=False)
            circ = s.session_info["Meeting"]["Circuit"]
            key = int(circ["Key"])
            # 注意：不要套用 FastF1 内置的 "Mugello 149→146" 修正 ——
            # 146 是【国家】key（葡萄牙），套用后会取到空数据。
            # 上游 key 与 Jeddah(149) 冲突的问题已在 NO_GEOMETRY 中显式处理。
            keys[cid] = (key, year, rnd)
            log.warning("  key %-4s %-18s (%d R%d)", key, cid, year, rnd)
        except Exception as exc:  # noqa: BLE001
            log.warning("  key 取失败 %-18s %s: %s", cid, year, exc)
    return keys


def fetch_geometry(circuit_key: int, year: int) -> dict | None:
    """从 MultiViewer API 取赛道几何。取不到返回 None。

    用返回的【完整赛道轮廓】（约 700 点，单位 0.1 m）计算单圈长度，
    而不是只用弯心的 15-27 点连线 —— 后者要割掉大量弯内弧长，
    误差 5%-9%；全轮廓把误差压到 0.1%-2.0%（实测 16 条已知赛道）。
    """
    from fastf1.mvapi.api import get_circuit

    try:
        d = get_circuit(year=year, circuit_key=circuit_key)
    except Exception as exc:  # noqa: BLE001
        log.warning("  几何取数失败 key=%s: %s", circuit_key, exc)
        return None
    if not d:
        return None

    xs = d.get("x") or []
    ys = d.get("y") or []
    corners = d.get("corners") or []
    if not xs or len(xs) != len(ys) or not corners:
        return None

    perim_units = 0.0
    for i in range(len(xs)):
        j = (i + 1) % len(xs)
        perim_units += math.hypot(xs[j] - xs[i], ys[j] - ys[i])
    length_m = perim_units * COORD_UNIT_M

    angles = [abs(float(c.get("angle", 0.0))) for c in corners]
    n_corners = len(corners)
    outline = [[round(x * COORD_UNIT_M, 1), round(y * COORD_UNIT_M, 1)]
               for x, y in zip(xs, ys)]

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    pit = d.get("pitLoss") or {}
    if not isinstance(pit, dict):
        pit = {}

    return {
        "corners": n_corners,
        "hairpins": sum(1 for a in angles if a >= HAIRPIN_ANGLE),
        "fast_corners": sum(1 for a in angles if a <= FAST_ANGLE),
        "rotation": float(d["rotation"]) if d.get("rotation") is not None else None,
        "marshal_lights": len(d.get("marshalLights") or []),
        "track_length_m": round(length_m, 1),
        "corner_density": round(n_corners / (length_m / 1000), 2) if length_m else None,
        "pit_loss_normal_s": _num(pit.get("normal")),
        "pit_loss_sc_s": _num(pit.get("sc")),
        "pit_loss_vsc_s": _num(pit.get("vsc")),
        "outline_json": json.dumps(outline, separators=(",", ":")),
    }


# ═══════════════════════════════════════════════════════════
# 历史统计（全历史，仅供展示）
# ═══════════════════════════════════════════════════════════

def history_stats(db: sqlite3.Connection, up_to=None) -> dict[str, dict]:
    """按规范赛道聚合历史统计。

    Args:
        up_to: (year, round) 元组；只统计严格早于该轮次的比赛。
               None 表示全历史（仅用于展示）。
    """
    where = "WHERE e.round > 0"
    params: list = []
    if up_to is not None:
        where += " AND (e.year < ? OR (e.year = ? AND e.round < ?))"
        params = [up_to[0], up_to[0], up_to[1]]

    rows = db.execute(
        f"""SELECT e.location, e.year, e.round, r.grid, r.position, r.status
            FROM results r JOIN events e USING(year, round) {where}""",
        params,
    ).fetchall()

    weather = {}
    for yr, rnd, rain in db.execute("SELECT year, round, had_rain FROM weather"):
        weather[(yr, rnd)] = rain

    agg: dict[str, dict] = {}

    def slot(cid):
        return agg.setdefault(cid, {
            "race_keys": set(), "pole_n": 0, "pole_d": 0,
            "move_sum": 0.0, "move_cnt": 0,
            "dnf_n": 0, "dnf_d": 0, "rain_n": 0, "rain_d": 0,
            "rain_seen": set(),
        })

    for loc, yr, rnd, grid, pos, status in rows:
        a = slot(canonical(loc))
        rk = (yr, rnd)
        a["race_keys"].add(rk)
        a["dnf_d"] += 1
        if is_dnf(status):
            a["dnf_n"] += 1
        else:
            if grid and pos:
                a["move_sum"] += abs(int(grid) - int(pos))
                a["move_cnt"] += 1
        if pos == 1:
            a["pole_d"] += 1
            if grid == 1:
                a["pole_n"] += 1

    for cid, a in agg.items():
        for rk in a["race_keys"]:
            rain = weather.get(rk)
            if rain is not None:
                a["rain_d"] += 1
                if rain:
                    a["rain_n"] += 1

    return agg


def circuit_stats_asof(db: sqlite3.Connection, circuit_id: str,
                       year: int, round_exclusive: int) -> dict:
    """⚠️ 防泄漏接口：返回预测 (year, round_exclusive) 时可用的赛道历史特征。

    只使用 round < round_exclusive 的比赛。预测第 n 站时用这个，
    不要用 circuits 表里的全历史列。
    """
    hist = history_stats(db, up_to=(year, round_exclusive))
    a = hist.get(circuit_id)
    if not a:
        return {"races": 0, "pole_win_rate": None, "avg_move": None,
                "dnf_rate": None, "rain_rate": None}
    return {
        "races": len(a["race_keys"]),
        "pole_win_n": a["pole_n"], "pole_win_d": a["pole_d"],
        "pole_win_rate": (a["pole_n"] / a["pole_d"]) if a["pole_d"] else None,
        "avg_move": (a["move_sum"] / a["move_cnt"]) if a["move_cnt"] else None,
        "dnf_n": a["dnf_n"], "dnf_d": a["dnf_d"],
        "dnf_rate": (a["dnf_n"] / a["dnf_d"]) if a["dnf_d"] else None,
        "rain_n": a["rain_n"], "rain_d": a["rain_d"],
        "rain_rate": (a["rain_n"] / a["rain_d"]) if a["rain_d"] else None,
    }


# ═══════════════════════════════════════════════════════════
# 建表主流程
# ═══════════════════════════════════════════════════════════

def build(with_geometry: bool = True) -> None:
    db = connect()
    db.executescript(SCHEMA_SQL)

    # 别名表：把 events 里出现过的每个原始 location 都登记
    locs = [r[0] for r in db.execute(
        "SELECT DISTINCT location FROM events WHERE round > 0")]
    db.executemany(
        "INSERT OR REPLACE INTO circuit_aliases VALUES (?,?)",
        [(loc, canonical(loc)) for loc in locs],
    )

    cids = sorted({canonical(loc) for loc in locs})
    unknown = [c for c in cids if c not in CIRCUIT_META]
    if unknown:
        log.warning("⚠️ CIRCUIT_META 缺少 %d 条赛道: %s", len(unknown), unknown)

    stats = history_stats(db)
    keys = fetch_circuit_keys(db) if with_geometry else {}

    n_geo = 0
    for cid in cids:
        name, name_cn, country, country_cn = CIRCUIT_META.get(
            cid, (cid, cid, COUNTRY_ALIASES.get(cid, cid), None))
        country = COUNTRY_ALIASES.get(country, country)
        a = stats.get(cid, {})

        geo = None
        key = year = None
        if cid in keys:
            key, gyear, _ = keys[cid]
            geo = fetch_geometry(key, gyear)
            if geo:
                year = gyear
                n_geo += 1

        g = geo or {}
        db.execute(
            """INSERT OR REPLACE INTO circuits (
                   circuit_id, name, name_cn, country, country_cn,
                   circuit_key, geo_year,
                   corners, hairpins, fast_corners, rotation, marshal_lights,
                   track_length_m, corner_density,
                   pit_loss_normal_s, pit_loss_sc_s, pit_loss_vsc_s,
                   outline_json,
                   races, pole_win_n, pole_win_d, move_n, dnf_n, dnf_d,
                   rain_n, rain_d
               ) VALUES (?,?,?,?,?,
                         ?,?,
                         ?,?,?,?,?,
                         ?,?,
                         ?,?,?,
                         ?,
                         ?,?,?,?,?,?,
                         ?,?)""",
            (
                cid, name, name_cn, country, country_cn,
                key, year,
                g.get("corners"), g.get("hairpins"), g.get("fast_corners"),
                g.get("rotation"), g.get("marshal_lights"),
                g.get("track_length_m"), g.get("corner_density"),
                g.get("pit_loss_normal_s"), g.get("pit_loss_sc_s"),
                g.get("pit_loss_vsc_s"),
                g.get("outline_json"),
                len(a.get("race_keys", ())),
                a.get("pole_n"), a.get("pole_d"),
                (a.get("move_sum", 0.0) / a["move_cnt"]) if a.get("move_cnt") else None,
                a.get("dnf_n"), a.get("dnf_d"),
                a.get("rain_n"), a.get("rain_d"),
            ),
        )

    db.commit()
    log.warning("✅ circuits: %d 条赛道（几何 %d 条）· 别名 %d 条 → %s",
                len(cids), n_geo, len(locs), DB_PATH)
    db.close()


def _selfcheck() -> None:
    """建表后自检：场次守恒 + 几何合理性。"""
    db = connect()
    print("=" * 74)
    print("自检")
    print("=" * 74)

    total_alias = db.execute("SELECT COUNT(*) FROM circuit_aliases").fetchone()[0]
    total_circ = db.execute("SELECT COUNT(*) FROM circuits").fetchone()[0]
    races_events = db.execute(
        "SELECT COUNT(*) FROM events WHERE round>0").fetchone()[0]
    races_circ = db.execute("SELECT COALESCE(SUM(races),0) FROM circuits").fetchone()[0]
    print(f"  别名 {total_alias} 条 → 规范赛道 {total_circ} 条")
    print(f"  场次守恒: events={races_events}  circuits.races 合计={races_circ}"
          f"  {'✅' if races_events == races_circ else '❌ 不一致'}")

    print()
    n_geo = db.execute(
        "SELECT COUNT(*) FROM circuits WHERE track_length_m IS NOT NULL").fetchone()[0]
    bad = db.execute(
        "SELECT circuit_id, track_length_m FROM circuits WHERE track_length_m IS NOT NULL"
        " AND (track_length_m < 2000 OR track_length_m > 8000)").fetchall()
    print(f"  几何覆盖 {n_geo}/{total_circ} 条"
          f"   {'✅ 长度均在合理区间 (2-8 km)' if not bad else '❌ 越界: ' + str(bad)}")
    print()
    print(f"  {'circuit':<18}{'k':>4}{'弯':>4}{'发夹':>5}{'快弯':>5}{'长度m':>8}"
          f"{'弯/km':>7}{'进站s':>13}{'轮廓点':>7}{'场次':>5}{'杆位胜率':>12}"
          f"{'名次波动':>9}{'退赛率':>8}")
    for row in db.execute(
        """SELECT circuit_id,circuit_key,corners,hairpins,fast_corners,track_length_m,
                  corner_density,pit_loss_normal_s,pit_loss_sc_s,outline_json,
                  races,pole_win_n,pole_win_d,move_n,dnf_n,dnf_d
           FROM circuits ORDER BY races DESC, circuit_id"""
    ):
        (cid, key, cn, hp, fc, ln, cd, pnorm, psc, oj, rc, pn, pd, mv, dn, dd) = row
        pts = len(json.loads(oj)) if oj else 0
        pole = f"{pn}/{pd} ({pn/pd*100:.0f}%)" if pd else "—"
        pit = f"{pnorm:.1f}/{psc:.1f}" if pnorm and psc else "—"
        print(f"  {cid:<18}{str(key):>4}{str(cn):>4}{str(hp):>5}{str(fc):>5}"
              f"{(f'{ln:.0f}' if ln else '—'):>8}"
              f"{(f'{cd:.2f}' if cd else '—'):>7}"
              f"{pit:>13}"
              f"{pts:>7}{rc:>5}{pole:>12}"
              f"{(f'{mv:.2f}' if mv else '—'):>9}"
              f"{(f'{dn/dd*100:.1f}%' if dd else '—'):>8}")
    print()
    print("  进站s 列为 绿旗/安全车 两档；差值即安全车期间进站白赚的时间")
    db.close()


if __name__ == "__main__":
    build(with_geometry="--no-geo" not in sys.argv)
    _selfcheck()
