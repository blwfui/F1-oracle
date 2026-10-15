"""逐圈回放动画：把一场比赛导出为可独立播放的 HTML。

核心换算
--------
赛道上的位置 = 落后时间 / 单圈圈速

某车手在第 L 圈结束时的累计时间比领跑者多 gap 秒，等价于他在赛道上
落后 gap / lap_time 圈的距离。因为位置 0 定义为终点线（领跑者刚通过），
所以他的绝对位置是 `(1 - gap/lap_time) mod 1`。

⚠️ 第 1 圈的 time_sec 包含赛前等待（约 1 小时），直接相减会得到 3831 秒
这种荒唐的"圈速"。因此基准圈速一律取**该圈全体车手圈速的中位数**，
且第 1 圈退化为使用第 2 圈的基准。

用法
----
    python -m scripts.export_replay 2026 1
    python -m scripts.export_replay 2026 1 -o outputs/monza.html
"""

import argparse
import html
import json
import math
import sqlite3
import sys
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.etl.aero_zones import NOTE as AERO_NOTE  # noqa: E402
from src.etl.aero_zones import overtake_for, zones_for  # noqa: E402
from src.model.lapdata import load_laptimelines  # noqa: E402
from src.dashboard.names_cn import auto_cn_short  # noqa: E402

DB_PATH = ROOT / "data" / "f1_oracle.db"

# 车队配色（与仪表板保持一致；此处独立定义以免引入 streamlit 依赖）
TEAM_COLORS = {
    "Mercedes": "#00D7B6", "Ferrari": "#E8002D", "Red Bull Racing": "#3671C6",
    "McLaren": "#FF8000", "Aston Martin": "#229971", "Alpine": "#0093CC",
    "Williams": "#64C4FF", "Racing Bulls": "#6692FF", "Haas F1 Team": "#B6BABD",
    "Kick Sauber": "#00E701", "Sauber": "#00E701", "Audi": "#00E701",
    "Cadillac": "#C8C8C8", "RB F1 Team": "#6692FF",
}
FALLBACK_COLOR = "#9aa4b2"


# ── 几何 ────────────────────────────────────────────────────────────

def _cumulative(points: list[list[float]]) -> list[float]:
    """返回每个顶点的累计弧长（米）。"""
    cum = [0.0]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        cum.append(cum[-1] + math.hypot(x1 - x0, y1 - y0))
    return cum


def _point_at(points, cum, t: float) -> tuple[float, float]:
    """沿赛道取进度 t∈[0,1) 处的坐标（按弧长，而非按点索引）。"""
    total = cum[-1]
    target = (t % 1.0) * total
    lo, hi = 0, len(cum) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if cum[mid] <= target:
            lo = mid
        else:
            hi = mid
    seg = cum[hi] - cum[lo]
    f = 0.0 if seg <= 1e-9 else (target - cum[lo]) / seg
    x0, y0 = points[lo]
    x1, y1 = points[hi] if hi < len(points) else points[lo]
    return x0 + (x1 - x0) * f, y0 + (y1 - y0) * f


# ── 数据 ────────────────────────────────────────────────────────────

STALL_SECONDS = 300.0


def js_json(obj) -> str:
    """序列化成**能安全嵌进 `<script>`** 的 JSON。

    审查报告 E3：原来这里直接 `json.dumps(...)` 后用 `str.replace` 塞进模板。
    `json.dumps` 会把 `</script>` 原样输出，浏览器在那里**就地结束脚本块** ——
    整页 JS 废掉，而且不报错、只是白屏。`U+2028` / `U+2029` 同理：
    在 JSON 里合法，在 JS 字符串字面量里却是换行。

    `<` / `>` / `&` 一律转成 `\\uXXXX`（同 Django 的 `json_script` 做法）。
    转义序列在 JSON 与 JS 里都合法，所以 `json.loads` 能原样还原。
    """
    return (json.dumps(obj, ensure_ascii=False)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("&", "\\u0026")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029"))


def html_esc(text) -> str:
    """把库内文本放进 HTML 前转义。

    ⚠️ 不要因为"数据是自己抓的"就省这一步：`event_name` / `location` / `country`
    来自 FastF1 上游，不是我们写的常量，本仓库也无权保证其内容。
    """
    return html.escape(str(text), quote=True)


def _lap_time_ref(tl, lap: int) -> float:
    """基准圈速 = 该圈全体车手圈速的中位数。第 1 圈用第 2 圈的值。

    ⚠️ 必须**剔除异常增量**（红旗暂停、长时间停车）再取中位：
    2023 澳大利亚第 8 圈红旗中断约 18 分钟，那一圈的中位增量是 1091.9 s，
    直接拿它当基准圈速，整个位置换算会失真 12 倍以上。
    """
    use = max(2, lap)
    t1, t0 = tl.times(use), tl.times(use - 1)
    diffs = [t1[d] - t0[d] for d in t1
             if d in t0 and 0 < t1[d] - t0[d] < STALL_SECONDS]
    return median(diffs) if diffs else 90.0


def _stalled(tl, code: str, lap: int) -> bool:
    """该车手在**这一圈**是否长时间没在正常行驶。

    判据：累计时间相对上一圈的增量远超正常圈速（阈值 ``STALL_SECONDS``）。
    例：2026 R1 的 ALO 第 13 圈 +1069 s（正常约 86 s；同圈其余 19 人都只在
    94–118 s 之间，只有他一人异常）。这一圈的位置变化无法由「与领跑者的秒差」
    反推，所以**这一圈**不画。

    ⚠️ 这里是逐圈判断，不是一票否决。ALO 第 14 圈就回到了 98.8 s 的正常节奏，
    所以第 14 圈起照常绘制 —— 他被判为「第 13 圈异常」而不是「从第 13 圈退赛」。
    早期版本把他永久拉黑，结果是观众会以为他退赛了，而其实他一直跑到结束
    （只是被套了 12 圈）。
    """
    if lap < 2:
        return False
    cur, prev = tl.times(lap).get(code), tl.times(lap - 1).get(code)
    if cur is None or prev is None:
        return False
    return (cur - prev) > STALL_SECONDS


def _wrap_delta(d: float) -> float:
    """把模 1 的位置差折回 ±半圈。

    跨起点线时直接相减会差一整圈（0.02 − 0.98 = −0.96 其实是 +0.04），
    不折回来「这一圈走了多少」就完全算错。
    """
    if d >= 0.5:
        d -= 1.0
    elif d < -0.5:
        d += 1.0
    return d


def build(year: int, rnd: int) -> dict:
    tls = load_laptimelines(year)
    match = [t for t in tls if t.round == rnd]
    if not match:
        raise SystemExit(f"库中找不到 {year} 年第 {rnd} 站")
    tl = match[0]

    db = sqlite3.connect(DB_PATH)
    info = db.execute(
        "SELECT event_name, location, country FROM events WHERE year=? AND round=?",
        (year, rnd),
    ).fetchone()
    event_name, location, country = info if info else (f"Round {rnd}", "", "")

    drivers: dict[str, dict] = {}
    laps_done: dict[str, int] = {}
    for code, team, full, done in db.execute(
        "SELECT driver, team, full_name, laps_completed FROM results WHERE year=? AND round=?",
        (year, rnd),
    ):
        laps_done[code] = int(done or 0)
        # auto_cn_short 返回的是 "LEC 勒克莱尔"（自带缩写前缀），
        # 这里剥掉前缀只留中文部分，避免页面上出现 "LEC LEC 勒克莱尔"。
        short = auto_cn_short(code, full)
        cn = short[len(code):].strip() if short.upper().startswith(code.upper()) else short
        drivers[code] = {
            "team": team,
            "color": TEAM_COLORS.get(team, FALLBACK_COLOR),
            "cn": cn,
        }

    # 并非所有赛季都填了 laps_completed —— 2026 赛季整列是 NULL，
    # int(None or 0) 全变 0。这种「数据缺失」不能拿它当判据，
    # 否则 lap > 0 恒真，会把全场车手每圈全部滤掉（画面一辆车都没有）。
    # 只有确实存在正数样本时，才启用「官方圈数」这道过滤。
    has_laps_data = any(v > 0 for v in laps_done.values())

    track = db.execute(
        "SELECT circuit_id, name, track_length_m, outline_json, pit_lane_json FROM circuits "
        "WHERE circuit_id IN (SELECT circuit_id FROM circuit_aliases WHERE location=?) "
        "   OR name = ?",
        (location, location),
    ).fetchone()
    if not track or not track[3]:
        raise SystemExit(f"找不到 {location} 的赛道几何（circuits 表）")

    circuit_id, circuit_name, track_len, outline_json, pit_lane_json = track
    points = json.loads(outline_json)
    cum = _cumulative(points)
    measured = cum[-1]

    # 真实维修区几何（scripts/fetch_pit_lane.py 从实跑遥测抽出）。
    # 车库格用「按车队等距铺开」的示意位 —— 2023 R3 三次红旗，正常进站样本太少，
    # 真实车库点不足以覆盖全车手。维修区**走线**是真实的，车库**编号**是示意。
    pitlane = None
    if pit_lane_json:
        pl = json.loads(pit_lane_json)
        ordered = sorted(drivers, key=lambda c: (drivers[c]["team"], c))
        n = max(1, len(ordered) - 1)
        pitlane = {
            "path": pl["path"],
            "entry": pl["entry"],
            "exit": pl["exit"],
            "boxes": {c: round(0.10 + 0.80 * i / n, 4) for i, c in enumerate(ordered)},
        }

    frames = []
    prev_l: dict[str, float] = {}   # 上一圈结束时各车的位置，用于圈内平滑插值
    prev_pit: dict[str, bool] = {}  # 上一圈该车是否在进站（用来区分 in-lap / out-lap）
    prev_gaps: dict[str, float] = {}  # 上一圈结束时各车的秒差，用于实时榜的进度起点
    ref_prev: float | None = None     # 上一圈（已处理的那圈）的参考圈速，同上
    for lap in range(1, tl.total_laps + 1):
        gaps = tl.gaps(lap)
        if not gaps:
            continue
        pos = tl.positions(lap)
        ahead = tl.gap_ahead(lap)
        ref = _lap_time_ref(tl, lap)
        # 红旗（TrackStatus '5'）：比赛中断，车手全部停在发车格或维修区，
        # 此时「按与领跑者的秒差反推位置」完全失效 —— 他们会散布在赛道上，
        # 而实际都挤在起点附近。所以这一圈不画车手，只显示红旗。
        red_flag = "5" in tl.track_status(lap)
        cars = []
        for code, gap in gaps.items():
            # 官方圈数才是「这一圈该车手在不在赛道上」的权威判据。
            # FastF1 会给 0 圈退赛者（2023 R3 的 LEC）填上与领跑者一字不差的 Time，
            # 与领跑的差值算出来恰好是 0 → 他会当「秒差 0 的幽灵车」杵在起跑线上。
            # 用 results.laps_completed 挡掉，别信 FastF1 那条脏 Time。
            # 但只在 laps_completed 确实有数据时才用（见上方 has_laps_data）。
            if has_laps_data and lap > laps_done.get(code, 0):
                continue
            bad = _stalled(tl, code, lap)   # 只看这一圈，不做永久封禁
            loc = (1.0 - gap / ref) % 1.0
            # l0 = 上一圈结束时的位置。一圈里他真正走过的是「1 + (loc - l0)」圈，
            # 其中 (loc - l0) 是这一圈相对领跑者又多落后的部分（通常是个小负数）。
            # 缺了 l0，每圈换帧时位置只能从上一个 loc 直接跳到新的 loc ——
            # 那个跳变就是「领跑者一过终点线、全场像卡一下」的来源。
            l0 = prev_l.get(code, loc)
            prev_l[code] = loc
            # 实时榜用的「进度起点偏移」：把上一圈结束时的秒差换算成圈数。
            # 于是 prog = (本圈序号 − 1) + u0 + frac × rate 在**每圈边界上
            # 恰好等于官方成绩** —— 帧末与官方表一致，帧内连续变化，
            # 不会像「直接用该圈结束的快照」那样提前半圈、把进站车提前拍到最后。
            #
            # ⚠️ 但相邻两圈的**秒差跨度**超过半圈，就说明上一圈的数据不可信：
            # 红旗/重启会把累计时间重算，2023 R3 第 8 圈全员秒差 ~910 s（正常的 11 倍），
            # 照抄进 u0 会让整个第 9 圈的榜乱掉（VER 显示落后 1000 多秒）。
            # 注意不能用 loc 的差值去判 —— loc 是模 1 的，折回后那 5 圈垃圾只剩 0.09，
            # 根本看不出来。这种帧改用一个本圈自洽的起点。
            g_prev = prev_gaps.get(code, gap)
            u0 = -g_prev / (ref_prev or ref)
            if abs(gap / ref - g_prev / (ref_prev or ref)) > 0.5:
                u0 = (1.0 - gap / ref) - (1.0 + _wrap_delta(loc - l0))
            is_pit_now = bool(tl.states.get(lap, {}).get(code, {}).get("is_pit"))
            was_pit = prev_pit.get(code, False)
            # in  = 进站圈（本圈进、上一圈不进）→ 车从赛道拐进维修区
            # out = 出站圈（连续两圈都标进站）→ 车从维修区出站汇回赛道
            phase = ("in" if (is_pit_now and not was_pit)
                     else "out" if (is_pit_now and was_pit) else "")
            cars.append({
                "c": code,
                "p": pos.get(code),
                "g": round(gap, 2),                       # 与领跑者差距
                "a": round(ahead.get(code, 0.0), 2),      # 与前车差距
                "l0": round(l0, 5),                       # 本圈起点位置（上一圈终点）
                "l": round(loc, 5),                       # 本圈终点位置
                "u0": round(u0, 5),                       # 本圈起点进度偏移（−上一圈秒差/圈速）
                "lap_dn": int(gap // ref),                # 被套圈数
                "pit": is_pit_now,                        # 本圈进站
                "phase": phase,                           # "" / "in" / "out"
                "box": (pitlane or {}).get("boxes", {}).get(code, 0.5),  # 车库格弧长比例
                "ok": not (bad or red_flag),              # False = 该圈位置不可信，不绘制
                "why": "red" if red_flag else ("stalled" if bad else ""),
            })
        # 全场基准速率 rp = 本圈「正常跑圈」车手 (1+dl) 的中位数。
        #
        # 为什么需要它：车的秒差 dl = l − l0 里**含了整次进站的损失**——SAR 第 36 圈
        # 从 −54.2s 掉到 −71.8s，也就是 −0.215 圈。若拿这个 dl 当赛道段的速度，
        # 这 0.215 圈会被**平摊到整圈**：他在还没开到进站口（拐点在 78% 处）之前，
        # 就已经比全场慢 20%，后车于是在赛道上把他白超了 —— 而真实情况是，
        # 这 17.2s 全花在维修区里（他的进站圈 99.3s vs 全场中位 82.1s）。
        # 所以赛道段一律用**全场同速**，进站损失完整留在维修区段。
        normal = [1.0 + _wrap_delta(c["l"] - c["l0"]) for c in cars
                  if c["ok"] and not c["pit"]]
        rp = sorted(normal)[len(normal) // 2] if normal else 1.0

        cars.sort(key=lambda x: (x["p"] is None, x["p"] or 99))
        for code in gaps:   # 更新「上一圈是否进站」，供下一圈判 in/out
            prev_pit[code] = bool(tl.states.get(lap, {}).get(code, {}).get("is_pit"))
        prev_gaps = gaps
        ref_prev = ref
        frames.append({
            "n": lap,
            "st": sorted(tl.track_status(lap)),
            "ms": round(ref * 1000),   # 该圈的现实时长(毫秒)，供按真实速度播放
            "rp": round(rp, 4),        # 该圈全场基准速率（进站车的赛道段照它走）
            "cars": cars,
        })

    db.close()
    ref_len = track_len or measured
    # 用几何长度做分母，与 pointAt 自洽；year 用来挡住规则生效年之前的场次
    zones = zones_for(circuit_id, measured, year)
    ot = overtake_for(circuit_id, measured, year)
    return {
        "year": year,
        "round": rnd,
        "event": event_name,
        "circuit": circuit_name or location,
        "country": country,
        "total_laps": tl.total_laps,
        "track_length_m": round(ref_len),
        "outline": [[round(x, 1), round(y, 1)] for x, y in points],
        "drivers": drivers,
        "frames": frames,
        "pitlane": pitlane,
        "aero": [{"s": round(s, 5), "e": round(e, 5)} for s, e in zones],
        "overtake": {k: round(v, 5) for k, v in ot.items()},
        "aero_note": AERO_NOTE if zones else "",
    }


# ── 渲染 ────────────────────────────────────────────────────────────

TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
  :root{
    --bg:#0d1117; --panel:#161b22; --line:#30363d;
    --fg:#e6edf3; --dim:#8b949e; --accent:#58a6ff;
  }
  *{box-sizing:border-box}
  body{margin:0;background:var(--bg);color:var(--fg);
       font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif}
  .app{max-width:1280px;margin:0 auto;padding:16px}
  header{display:flex;justify-content:space-between;align-items:baseline;
         flex-wrap:wrap;gap:8px;margin-bottom:12px}
  h1{font-size:19px;margin:0;font-weight:600}
  .meta{color:var(--dim);font-size:13px}
  .badge{display:inline-block;padding:1px 7px;border-radius:10px;
         font-size:11px;margin-left:6px;vertical-align:1px}
  .sc{background:#8b1a1a;color:#ffd7d7}
  .vsc{background:#8a6d1a;color:#fff3d0}
  .red{background:#c1121f;color:#fff;font-weight:600}
  .pit{background:#1f6feb;color:#dbeaff}
  main{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:16px}
  @media(max-width:900px){main{grid-template-columns:1fr}}
  .panel{background:var(--panel);border:1px solid var(--line);border-radius:10px}
  #trackwrap{padding:8px;position:relative;display:flex;align-items:center;
             justify-content:center}
  svg{display:block;width:100%;height:auto;max-height:68vh}
  aside{max-height:68vh;overflow-y:auto}
  table{width:100%;border-collapse:collapse;font-size:13px}
  th{position:sticky;top:0;background:var(--panel);color:var(--dim);
     font-weight:500;text-align:left;padding:8px 10px;font-size:11px;
     border-bottom:1px solid var(--line)}
  td{padding:5px 10px;border-bottom:1px solid rgba(48,54,61,.45)}
  tr.out td{opacity:.42}
  .pos{width:30px;color:var(--dim);font-variant-numeric:tabular-nums}
  .dot{display:inline-block;width:8px;height:8px;border-radius:50%;
       margin-right:7px;vertical-align:middle}
  .code{font-weight:600;letter-spacing:.3px}
  .cn{color:var(--dim);font-size:12px;margin-left:5px}
  .num{text-align:right;font-variant-numeric:tabular-nums;color:var(--dim)}
  .num.lead{color:var(--fg)}
  /* ── 控制条：放在赛道上方，最顺手的位置 ── */
  .controls{display:flex;align-items:center;gap:10px;flex-wrap:wrap;
            background:var(--panel);border:1px solid var(--line);
            border-radius:10px;padding:10px 14px;margin-bottom:14px}
  button{background:var(--panel);color:var(--fg);border:1px solid var(--line);
         border-radius:7px;padding:7px 15px;cursor:pointer;font-size:14px;
         font-family:inherit;white-space:nowrap}
  button:hover{border-color:var(--accent)}
  button.primary{background:#1f6feb;border-color:#1f6feb;color:#fff;
                 font-weight:600;min-width:104px}
  button.primary:hover{background:#388bfd;border-color:#388bfd}
  button.step{padding:7px 12px;font-size:13px;color:var(--dim)}
  button.step:hover{color:var(--fg)}
  button.step.on{color:var(--fg);border-color:#2fbf71;background:#102418}
  input[type=range]{flex:1;min-width:190px;height:24px;cursor:pointer;
                    accent-color:var(--accent)}
  .spdbox{display:flex;align-items:center;gap:1px;background:var(--bg);
          border:1px solid var(--line);border-radius:7px;padding:2px}
  .spdbtn{background:none;border:none;color:var(--dim);font-size:17px;
          width:27px;height:28px;padding:0;cursor:pointer;border-radius:5px;
          line-height:1;display:flex;align-items:center;justify-content:center}
  .spdbtn:hover{background:#21262d;color:var(--fg);border:none}
  .spdbtn:disabled{opacity:.5;cursor:default;background:none;color:#6e7681}
  .spdval{min-width:66px;text-align:center;font-size:12px;color:var(--fg);
          font-variant-numeric:tabular-nums}
  .dur{color:var(--dim);font-size:12px;white-space:nowrap;
       font-variant-numeric:tabular-nums}
  .hint{display:flex;justify-content:space-between;align-items:center;gap:14px;
        flex-wrap:wrap;color:var(--dim);font-size:13px;margin-top:11px;min-height:19px}
  .hint b{color:var(--fg);font-weight:600}
  .legend{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--dim)}
  .sw{display:inline-block;border-radius:2px;flex:0 0 auto}
  .sw.aero{width:18px;height:5px;background:#2fbf71}
  .sw.sf{width:5px;height:14px;background:#e6edf3;border-radius:1px}
  .sw.om{width:9px;height:9px;border-radius:50%;background:#f0883e}
  .laptag{color:var(--accent);font-variant-numeric:tabular-nums}

  /* ── 开场遮罩：手动开始比赛 ── */
  #overlay{position:fixed;inset:0;z-index:50;display:flex;align-items:center;
           justify-content:center;background:rgba(3,6,12,.84);
           -webkit-backdrop-filter:blur(3px);backdrop-filter:blur(3px);
           transition:opacity .35s ease,visibility .35s ease}
  #overlay.gone{opacity:0;visibility:hidden;pointer-events:none}
  .ovcard{text-align:center;max-width:580px;margin:20px;padding:34px 44px;
          background:var(--panel);border:1px solid var(--line);border-radius:16px;
          box-shadow:0 18px 60px rgba(0,0,0,.62)}
  .ovkicker{color:var(--accent);font-size:11px;letter-spacing:.24em;
            text-transform:uppercase;margin-bottom:13px}
  .ovtitle{font-size:21px;font-weight:600;line-height:1.4;margin-bottom:9px}
  .ovmeta{color:var(--dim);font-size:13px;margin-bottom:7px}
  .ovhint{color:var(--dim);font-size:12px;margin-bottom:24px;line-height:1.6}
  button.big{font-size:16px;padding:11px 38px}
</style>
</head>
<body>
<div class="app">
  <header>
    <div>
      <h1>__TITLE__<span id="flags"></span></h1>
      <div class="meta">__SUBTITLE__</div>
    </div>
    <div class="meta">第 <span id="lapno" class="laptag">1</span> / __TOTAL__ 圈</div>
  </header>

  <div class="controls">
    <button id="play" class="primary">开始比赛</button>
    <button id="prev" class="step" title="退后一圈（← 键）">上一圈</button>
    <button id="next" class="step" title="前进一圈（→ 键）">下一圈</button>
    <input type="range" id="scrub" min="1" max="__TOTAL__" value="1" step="1"
           title="拖动跳到任意一圈">
    <div class="spdbox" title="播放速度：×1 = 比赛中的真实速度">
      <button id="slower" class="spdbtn">−</button>
      <span id="spd" class="spdval"></span>
      <button id="faster" class="spdbtn">+</button>
    </div>
    <span id="dur" class="dur" title="当前速度下播完整场的时长"></span>
    <button id="aero" class="step on" title="显示 / 隐藏主动空气动力学区段（Straight Mode）">空力区段</button>
  </div>

  <main>
    <div class="panel" id="trackwrap"><svg id="track" viewBox="0 0 1000 1000"></svg></div>
    <aside class="panel"><table id="board"></table></aside>
  </main>

  <div class="hint">
    <span id="lab"></span>
    <span class="legend" id="legend"></span>
  </div>
</div>

<div id="overlay">
  <div class="ovcard">
    <div class="ovkicker">F1 Oracle</div>
    <div class="ovtitle">__EVENT__</div>
    <div class="ovmeta">__SUBTITLE__</div>
    <div class="ovhint">
      全场约 __DURATION__（×1 现实速度）· 每圈按该圈真实圈速播放<br>
      可拖进度条跳圈，空格键播放/暂停，← → 逐圈
    </div>
    <button id="startbtn" class="primary big">开始比赛</button>
  </div>
</div>

<script>
const DATA = __DATA__;

/* ── 赛道几何：等比缩放并留边距，y 轴翻转 ───────────────── */
const SVG_NS = "http://www.w3.org/2000/svg";
const W = 1000, H = 1000, PAD = 46;
const pts = DATA.outline;
const xs = pts.map(p => p[0]), ys = pts.map(p => p[1]);
const minx = Math.min(...xs), maxx = Math.max(...xs);
const miny = Math.min(...ys), maxy = Math.max(...ys);
const scale = Math.min((W - 2*PAD) / (maxx - minx), (H - 2*PAD) / (maxy - miny));
const offx = (W - (maxx - minx) * scale) / 2;
const offy = (H - (maxy - miny) * scale) / 2;
function project(x, y) {
  return [ offx + (x - minx) * scale,
           offy + (maxy - y) * scale ];   // 翻转 y
}
const path = pts.map((p, i) => {
  const [X, Y] = project(p[0], p[1]);
  return (i ? "L" : "M") + X.toFixed(1) + " " + Y.toFixed(1);
}).join(" ") + " Z";

/* 每圈把车手位置换算为坐标（按弧长行进，而非按点索引） */
const cum = [0];
for (let i = 1; i < pts.length; i++) {
  cum.push(cum[i-1] + Math.hypot(pts[i][0]-pts[i-1][0], pts[i][1]-pts[i-1][1]));
}
const TOTAL_LEN = cum[cum.length-1];
function pointAt(t) {
  const target = ((t % 1) + 1) % 1 * TOTAL_LEN;
  let lo = 0, hi = cum.length - 1;
  while (lo < hi - 1) { const m = (lo + hi) >> 1; (cum[m] <= target) ? lo = m : hi = m; }
  const seg = cum[hi] - cum[lo];
  const f = seg <= 1e-9 ? 0 : (target - cum[lo]) / seg;
  const x = pts[lo][0] + (pts[hi][0] - pts[lo][0]) * f;
  const y = pts[lo][1] + (pts[hi][1] - pts[lo][1]) * f;
  return project(x, y);
}

/* ── 静态图层 ──────────────────────────────────────────── */
const svg = document.getElementById("track");
function el(tag, attrs) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const k in attrs) e.setAttribute(k, attrs[k]);
  return e;
}
/* 赛道底色留出引用：红旗时整条变红，是最容易一眼看懂的信号 */
const trackOuter = el("path", { d: path, fill: "none", stroke: "#21262d",
                                "stroke-width": 34, "stroke-linejoin": "round" });
const trackInner = el("path", { d: path, fill: "none", stroke: "#30363d",
                                "stroke-width": 26, "stroke-linejoin": "round" });
svg.appendChild(trackOuter);
svg.appendChild(trackInner);
svg.appendChild(el("path", { d: path, fill: "none", stroke: "#484f58",
                             "stroke-width": 2, "stroke-dasharray": "7 9" }));

/* ── 主动空气动力学区段（Straight Mode）────────────────────
   位置来自 src/etl/aero_zones.py，依据公开报道按弯角推算，误差约 ±100 m。
   用「按弧长取样生成子路径」而不是 stroke-dasharray —— 区段可能跨过起点线，
   dasharray 处理这种首尾相接的区间很容易出错。 */
const aeroLayer = el("g", { opacity: 1 });
function subPath(f0, f1) {
  const spanM = (f1 - f0) * TOTAL_LEN;
  const steps = Math.max(10, Math.round(spanM / 6));   /* 每 ~6 m 取一点 */
  let d = "";
  for (let i = 0; i <= steps; i++) {
    const [x, y] = pointAt(f0 + (f1 - f0) * i / steps);
    d += (i ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1);
  }
  return d;
}
for (const z of DATA.aero) {
  aeroLayer.appendChild(el("path", {
    d: subPath(z.s, z.e), fill: "none", stroke: "#2fbf71",
    "stroke-width": 10, "stroke-linecap": "butt", opacity: 0.8,
  }));
}
/* Overtake Mode 的检测点 / 激活点（同为公开报道推算的位置） */
for (const key of ["detection", "activation"]) {
  const f = DATA.overtake[key];
  if (f == null) continue;
  const [x, y] = pointAt(f);
  aeroLayer.appendChild(el("circle", {
    cx: x, cy: y, r: 4, fill: "#f0883e", stroke: "#0d1117", "stroke-width": 1.6,
  }));
}
svg.appendChild(aeroLayer);

/* ── 起点/终点线 ──────────────────────────────────────────
   画在 loc=0 处。已验证几何起点就是官方 S/F 线：marshal sector #1 落在
   几何第 0 点（偏差 0.00），且 T1 里程 356.4 m 与几何弧长 350 m 吻合。 */
{
  const [sfx, sfy] = pointAt(0);
  const [sx2, sy2] = pointAt(0.004);
  const dl = Math.hypot(sx2 - sfx, sy2 - sfy) || 1;
  const nx = -(sy2 - sfy) / dl, ny = (sx2 - sfx) / dl;   /* 赛道法线 */
  const half = 28;
  svg.appendChild(el("line", {
    x1: sfx - nx * half, y1: sfy - ny * half,
    x2: sfx + nx * half, y2: sfy + ny * half,
    stroke: "#e6edf3", "stroke-width": 6, "stroke-linecap": "round",
  }));
  const sfLab = el("text", {
    x: sfx + nx * (half + 19), y: sfy + ny * (half + 19),
    "font-size": 14, "font-weight": 700, fill: "#e6edf3",
    "text-anchor": "middle", "dominant-baseline": "middle",
    stroke: "#0d1117", "stroke-width": 4, "paint-order": "stroke",
  });
  sfLab.textContent = "S/F";
  svg.appendChild(sfLab);
}

const carsLayer = el("g", {}); svg.appendChild(carsLayer);

/* ── 维修区（真实几何）────────────────────────────────────────
   几何来自实跑遥测（scripts/fetch_pit_lane.py：进站车的实际行驶轨迹），
   与 outline 同坐标系，直接 project()。
   车库格按车队等距铺开 —— 是示意编号，不是真实车队车库分配（真实点太少）。 */
const PIT = DATA.pitlane;
const PITFLASH = {};
const BOXEL = {};
let pitPointAt = null;
if (PIT && PIT.path && PIT.path.length > 1) {
  const pl = PIT.path, pcum = [0];
  for (let i = 1; i < pl.length; i++)
    pcum.push(pcum[i-1] + Math.hypot(pl[i][0]-pl[i-1][0], pl[i][1]-pl[i-1][1]));
  const PL_LEN = pcum[pcum.length-1];
  pitPointAt = function (s) {
    const target = Math.min(Math.max(s, 0), 1) * PL_LEN;
    let lo = 0, hi = pcum.length - 1;
    while (lo < hi - 1) { const m = (lo + hi) >> 1; (pcum[m] <= target) ? lo = m : hi = m; }
    const sg = pcum[hi] - pcum[lo];
    const f = sg <= 1e-9 ? 0 : (target - pcum[lo]) / sg;
    return project(pl[lo][0] + (pl[hi][0]-pl[lo][0]) * f,
                   pl[lo][1] + (pl[hi][1]-pl[lo][1]) * f);
  };
  const pitLayer = el("g", {});
  let pd = "";
  for (let i = 0; i < pl.length; i++) {
    const [X, Y] = project(pl[i][0], pl[i][1]);
    pd += (i ? "L" : "M") + X.toFixed(1) + " " + Y.toFixed(1);
  }
  pitLayer.appendChild(el("path", { d: pd, fill: "none", stroke: "#2b3138",
                                    "stroke-width": 22, "stroke-linecap": "round" }));
  pitLayer.appendChild(el("path", { d: pd, fill: "none", stroke: "#4a5260",
                                    "stroke-width": 2, "stroke-dasharray": "6 8" }));
  for (const code in PIT.boxes) {
    const [bx, by] = pitPointAt(PIT.boxes[code]);
    const col = (DATA.drivers[code] || {}).color || "#888";
    BOXEL[code] = el("rect", { x: bx-3.5, y: by-3.5, width: 7, height: 7,
      rx: 1.5, fill: col, stroke: "#0d1117", "stroke-width": 1.2, opacity: 0.85 });
    pitLayer.appendChild(BOXEL[code]);
    PITFLASH[code] = el("circle", { cx: bx, cy: by, r: 7, fill: "none",
      stroke: "#ffd33d", "stroke-width": 3, opacity: 0 });
    pitLayer.appendChild(PITFLASH[code]);
  }
  svg.appendChild(pitLayer);
}

/* 红旗时车手全部不绘制（位置不可信），画面会变空 —— 给一个居中提示 */
const redNotice = el("text", {
  x: 500, y: 500, "text-anchor": "middle", "dominant-baseline": "middle",
  "font-size": 42, "font-weight": 700, fill: "#ff6b6b", opacity: 0,
  stroke: "#0d1117", "stroke-width": 7, "paint-order": "stroke",
});
redNotice.textContent = "红旗 · 比赛中断";
svg.appendChild(redNotice);
const NODE = {}, LABEL = {}, RING = {};
for (const code in DATA.drivers) {
  const d = DATA.drivers[code];
  RING[code] = el("circle", { r: 13, fill: "none", stroke: d.color,
                              "stroke-width": 2, opacity: 0 });
  NODE[code] = el("circle", { r: 8.5, fill: d.color, stroke: "#0d1117",
                              "stroke-width": 2.5, opacity: 0 });
  LABEL[code] = el("text", { "font-size": 15, "font-weight": 700, fill: d.color,
                             "text-anchor": "start", "dominant-baseline": "middle",
                             stroke: "#0d1117", "stroke-width": 3.4,
                             "paint-order": "stroke", opacity: 0 });
  LABEL[code].textContent = code;
  carsLayer.appendChild(RING[code]);
  carsLayer.appendChild(NODE[code]);
  carsLayer.appendChild(LABEL[code]);
}

/* ── 播放状态 ──────────────────────────────────────────── */
/* 速度倍率以「现实速度」为基准：×1 = 按比赛中的真实用时逐圈播放。
   一圈约 85–90 秒（黄旗/安全车圈会自然变慢），整场要播一个多小时——
   这就是默认档，控制条上的 − / + 可逐级调速。 */
const frames = DATA.frames;
let cur = 0, t = 0, playing = false, last = 0, started = false;
const SPEEDS = [1, 2, 5, 10, 30, 60];
let si = 0;

const board = document.getElementById("board");
const scrub = document.getElementById("scrub");
const lab = document.getElementById("lab");
const spd = document.getElementById("spd");
const lapno = document.getElementById("lapno");
const flags = document.getElementById("flags");
const playBtn = document.getElementById("play");
const prevBtn = document.getElementById("prev");
const nextBtn = document.getElementById("next");
const slowerBtn = document.getElementById("slower");
const fasterBtn = document.getElementById("faster");
const dur = document.getElementById("dur");
const overlay = document.getElementById("overlay");
const startBtn = document.getElementById("startbtn");
const aeroBtn = document.getElementById("aero");
const legend = document.getElementById("legend");

/* 整场比赛的现实总时长（各圈真实圈速之和），用于显示「按当前速度要播多久」 */
const TOTAL_MS = frames.reduce((a, f) => a + (f.ms || 90000), 0);
const pad2 = n => String(n).padStart(2, "0");
function fmtDur(ms) {
  const s = Math.floor(ms / 1000);   /* 与 Python 侧一致用截断，两处显示的时长不该差 1 秒 */
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), ss = s % 60;
  return h ? h + ":" + pad2(m) + ":" + pad2(ss) : m + ":" + pad2(ss);
}
function updateSpeed() {
  const s = SPEEDS[si];
  spd.textContent = s === 1 ? "×1 实时" : "×" + s;
  dur.textContent = "全长 " + fmtDur(TOTAL_MS / s);
  slowerBtn.disabled = si === 0;
  fasterBtn.disabled = si === SPEEDS.length - 1;
}
/* 播放/暂停的唯一入口：按钮文案区分「还没开始 / 暂停中 / 播放中」 */
function setPlaying(v) {
  playing = v;
  if (v) started = true;
  playBtn.textContent = v ? "暂停" : (started ? "继续" : "开始比赛");
}
updateSpeed();
setPlaying(false);

/* 图例只列出这场实际画出来的图层 —— 免得出现「有图例但画面上找不到」 */
{
  const parts = [];
  if (DATA.aero.length) parts.push('<i class="sw aero"></i>主动空力区段 ×' + DATA.aero.length + '（推算）');
  parts.push('<i class="sw sf"></i>起终点线');
  if (Object.keys(DATA.overtake).length) parts.push('<i class="sw om"></i>超车模式检测点');
  legend.innerHTML = parts.join("　　");
  if (DATA.aero_note) legend.title = DATA.aero_note;
  if (!DATA.aero.length) {
    aeroBtn.disabled = true;
    aeroBtn.classList.remove("on");
    aeroBtn.textContent = "空力区段 —";
    aeroBtn.title = "本场没有主动空力区段数据（该规则 2026 年才启用，且目前只录入了墨尔本）";
  }
}
let aeroOn = true;

/* FastF1 的 TrackStatus 编码：1=绿旗 2=黄旗 4=安全车 5=红旗 6/7=虚拟安全车。
   一位字符串里可能同时含多个（例如 '45' = 先安全车、后红旗），按严重程度优先显示。
   ⚠️ 早期版本把 '5' 也当成安全车 —— 红旗和安全车是完全不同的事。 */
function flagOf(st) {
  if (!st.length) return "";
  if (st.includes("5")) return '<span class="badge red">红旗</span>';
  if (st.includes("4")) return '<span class="badge sc">安全车</span>';
  if (st.includes("6") || st.includes("7")) return '<span class="badge vsc">虚拟安全车</span>';
  if (st.includes("2") || st.includes("3")) return '<span class="badge vsc">黄旗</span>';
  return "";
}

function render(fi, frac) {
  const f = frames[fi];
  const isRed = f.st.includes("5");           /* 红旗中断 */
  lapno.textContent = f.n;
  flags.innerHTML = flagOf(f.st);
  trackOuter.setAttribute("stroke", isRed ? "#5c1414" : "#21262d");
  trackInner.setAttribute("stroke", isRed ? "#8f1d1d" : "#30363d");
  redNotice.setAttribute("opacity", isRed ? 1 : 0);

  const top = f.cars[0];
  const drawn = new Set();
  for (const car of f.cars) {
    const code = car.c;
    /* 本圈从 l0 平滑走到 l（途中跨过终点线）。
       ⚠️ l0 与 l 都是模 1 的位置，跨起点线时直接相减会差一整圈：
       2026 R1 第 2 圈的 RUS 真实走了 1.0088 圈，若不归一化就只剩 0.0088 圈 ——
       他会整整一圈几乎原地不动。所以先把差值折回 ±半圈，再加回那一整圈。
       位置与进度**共用这一个** dl，避免同一件事两种实现。 */
    let dl0 = car.l - car.l0;
    if (dl0 >= 0.5) dl0 -= 1; else if (dl0 < -0.5) dl0 += 1;
    const rateCar = 1 + dl0;
    /* 进站拐点：由几何解出「车何时真的开到进站口」，位置与进度共用。
       赛道段用**全场基准速率 rp**（理由见下面「进站圈」一段）。 */
    const isIn = !!(PIT && pitPointAt && car.phase === "in");
    const rateIn = f.rp > 1e-6 ? f.rp : 1;
    const Tin = isIn ? Math.min((((PIT.entry - car.l0) % 1) + 1) % 1 / rateIn, 0.98) : 1;

    /* ── 比赛进度 prog（实时榜的排序与秒差基准）────────────────────────
       prog = (本圈序号 − 1) + 进度起点 u0 + frac × 速率。
       u0 = −上一圈结束时的秒差 ÷ 圈速，所以它在**每圈边界上恰好等于官方成绩**：
       帧末与官方表分毫不差，帧内则连续变化 —— 不会像「直接用该圈结束的快照」
       那样提前半圈，把还在赛道上的进站车提前拍到最后一名的位置。

       进站车在维修区里位置不动，但**进度继续推进到本圈终点**：
       于是榜上不会被提前拍下去，后车得真的在赛道上开过进站口才会反超他。

       ⚠️ 进度必须对**每台车**都算，包括不绘制的那几台 —— 否则领跑者一旦被判
       「停摆」，会从榜首直接掉到表底，那比不显示还糟。 */
    car.prog = isIn
      ? (f.n - 1) + car.u0 + Math.min(frac, Tin) * rateIn
        + (frac > Tin ? (frac - Tin) / (1 - Tin) * (rateCar - Tin * rateIn) : 0)
      : (f.n - 1) + car.u0 + frac * rateCar;

    if (!car.ok) continue;       /* 位置不可信：不画在赛道上（榜上仍保留一行） */
    drawn.add(code);
    let x, y, atBox = false;
    /* 常规赛道位置：与不进站的车**完全同一套算法**（含跨起点线的归一化）。
       进站车只在最后一段从这里平滑并入维修区 —— 赛道段绝不复用别的公式，
       否则一旦把「还有大半圈才到进站口」折成负值，车就会倒着开。 */
    const norm = (f2) => pointAt(car.l0 + f2 * rateCar);
    if (isIn) {
      /* 进站圈：车沿赛道**正常前进**，恰好开到进站口那一刻才拐进维修区，
         再沿维修区滑到自己的车库格 —— 全程单向，不会「过终点线后倒退回维修区」。

         ⚠️ 赛道段的速度用**全场基准速率 rp**，不用车手自己那个 1+dl ——
         那个 dl 里含了整次进站的损失（SAR 第 36 圈 −54.2s → −71.8s，即 −0.215 圈），
         用它当速度，等于把 17.2s 的进站损失平摊到整圈：他还没开到进站口就先慢 20%，
         后车于是在赛道上白超了他。进站丢的时间，只该体现在维修区那一段。
         （更早的写法是「固定最后 20% 切进去」，那时车早已开过进站口，必然后退。） */
      if (frac <= Tin) {
        [x, y] = pointAt(car.l0 + frac * rateIn);
      } else {
        const u = (frac - Tin) / (1 - Tin);
        const s = car.box * Math.min(1, u / 0.55);  /* 55% 处抵达车位，剩下停着 */
        [x, y] = pitPointAt(s);
        atBox = u >= 0.55;
      }
    } else if (PIT && pitPointAt && car.phase === "out") {
      /* 出站圈：先从车位沿维修区**驶到出站口**，再从出站口沿赛道跑到本圈终点。
         两段都是直线、在出站口相接 —— 与进站圈严格对称。
         （早先的写法是「从车位直接插值到赛道上的常规位置」，而那个位置离车位
          小半圈远，几个采样点一插值车就斜着横切出去，看着像飞出赛道。）

         ⚠️ 出站段的时长不能再拍死 15%：这一段要从出站口走完 (出站口→本圈终点)
         的距离 dx（≈1.02 圈），按全场速度走需要 1 − dx/rp 的时间，剩下的才是
         「驶出维修区」。拍死 15% 会逼他在这 85% 里跑完 1.02 圈 → 快 20%。 */
      let dx = car.l - PIT.exit; if (dx < 0) dx += 1;
      if (dx < 0.5) dx += 1;   /* 被套圈车 pseudo 位置不可靠：补齐一圈，免得「爬行」 */
      const rate = f.rp > 1e-6 ? f.rp : 1;
      let T = 1 - dx / rate;
      if (T < 0.06) T = 0.06; else if (T > 0.28) T = 0.28;  /* 兜底：出站段过短/过长都不像样 */
      if (frac <= T) {
        const u = frac / T;
        [x, y] = pitPointAt(car.box + u * (1 - car.box));
        atBox = u < 0.10;
      } else {
        [x, y] = pointAt(PIT.exit + ((frac - T) / (1 - T)) * dx);
      }
    } else {
      [x, y] = norm(frac);
    }
    /* 换胎闪光：车停在车库格时黄环闪烁（每 170 ms 一亮一暗） */
    const fl = PITFLASH[code];
    if (fl) {
      const blink = (Math.floor(Date.now() / 170) % 2) === 0;
      fl.setAttribute("opacity", atBox ? (blink ? 1 : 0.2) : 0);
      fl.setAttribute("r", atBox && blink ? 11 : 7);
    }
    const be = BOXEL[code];   /* 车位格：车停上去时描金边高亮 */
    if (be) {
      be.setAttribute("stroke", atBox ? "#ffd33d" : "#0d1117");
      be.setAttribute("stroke-width", atBox ? 2.5 : 1.2);
    }
    NODE[code].setAttribute("cx", x); NODE[code].setAttribute("cy", y);
    LABEL[code].setAttribute("x", x + 13); LABEL[code].setAttribute("y", y + 0.5);
    const behind = car.lap_dn > 0;
    NODE[code].setAttribute("opacity", behind ? 0.45 : 1);
    LABEL[code].setAttribute("opacity", behind ? 0.5 : 1);
    const isLead = top && car.c === top.c;
    RING[code].setAttribute("cx", x); RING[code].setAttribute("cy", y);
    RING[code].setAttribute("opacity", isLead ? 0.9 : 0);
  }
  /* 退赛、未出赛与停摆的车手：从赛道画面上隐藏 */
  for (const code in NODE) {
    if (drawn.has(code)) continue;
    NODE[code].setAttribute("opacity", 0);
    LABEL[code].setAttribute("opacity", 0);
    RING[code].setAttribute("opacity", 0);
  }

  /* ── 实时榜 ────────────────────────────────────────────────────
     名次与两列秒差全部按当前帧的**实际进度**现算，不再用「该圈结束时」的官方快照。
     官方快照的毛病是提前半圈：第 36 圈刚跑三分之一，榜上就已经是这圈跑完的名次，
     还在赛道上领先的进站车被直接拍到最后一名。
     prog（见上）在每圈边界上恰好等于官方成绩，所以帧末与官方表一致，帧内平滑变化。 */
  const LT = Math.max(1, f.ms) / 1000;   /* 本圈参考圈速（秒），把进度差换算成秒 */
  const rank = f.cars.slice().sort((a, b) => b.prog - a.prog);
  const leadP = rank.length ? rank[0].prog : 0;
  let html = '<tr><th>#</th><th>车手</th><th class="num">与前车</th>' +
             '<th class="num">与领跑</th></tr>';
  rank.forEach((car, i) => {
    const d = DATA.drivers[car.c] || {};
    const cls = car.lap_dn > 0 ? "out" : "";
    const gapAhead = i === 0 ? "—" : "−" + ((rank[i-1].prog - car.prog) * LT).toFixed(1);
    const gapLead = i === 0 ? "领先" : "−" + ((leadP - car.prog) * LT).toFixed(1);
    let dn = car.lap_dn > 0 ? ' <span style="color:#f0883e">+' + car.lap_dn + '圈</span>' : "";
    /* 不绘制的车（红旗中断、或个别圈次位置异常）：位置不可信，逐行标一下。
       红旗时全员如此，逐行标「红旗」只会把整张表刷红，交给顶部徽标去说。 */
    if (!car.ok && car.why !== "red") dn = ' <span style="color:#f85149">停摆</span>';
    /* 本圈进站：蓝色徽标，跟在被套圈标记之后。
       仅在车手实际在赛道上时显示 —— 红旗圈全员 is_pit=1（都进了维修区），
       那时候刷满屏「进站」纯属噪声，交给顶部红旗徽标去说。 */
    const pit = (car.pit && car.ok) ? ' <span class="badge pit">进站</span>' : "";
    html += '<tr class="' + cls + '">' +
      '<td class="pos">' + (i + 1) + "</td>" +
      '<td><span class="dot" style="background:' + (d.color||"#888") + '"></span>' +
        '<span class="code">' + car.c + "</span>" +
        '<span class="cn">' + (d.cn || "") + "</span>" + dn + pit + "</td>" +
      '<td class="num">' + gapAhead + "</td>" +
      '<td class="num' + (i === 0 ? " lead" : "") + '">' + gapLead + "</td></tr>";
  });
  board.innerHTML = html;

  lab.innerHTML = "第 <b>" + f.n + "</b> 圈" +
                  (top && top.c ? "　领先 <b>" + top.c + "</b>" : "");
  scrub.value = f.n;
}

function loop(ts) {
  if (playing) {
    /* dt 封顶 100ms：切走标签页再回来时不至于一口气跳掉几十圈 */
    const dt = Math.min(last ? ts - last : 16, 100);
    t += dt * SPEEDS[si] / frames[cur].ms;   /* 每圈按它自己的真实圈速计时 */
    while (t >= 1) {
      t -= 1; cur = (cur + 1) % frames.length;
    }
    render(cur, t);
  }
  last = ts;
  requestAnimationFrame(loop);
}

/* ── 交互 ──────────────────────────────────────────────── */
/* 跳到指定圈：一律暂停 —— 复盘时「停在这一圈看清楚」比继续播更有用 */
function goto(i) {
  cur = Math.max(0, Math.min(frames.length - 1, i));
  t = 0;
  setPlaying(false);
  render(cur, 0);
}
playBtn.onclick = () => {
  overlay.classList.add("gone");               /* 兜底：没经遮罩也能直接开始 */
  setPlaying(!playing);
};
startBtn.onclick = (e) => {
  e.stopPropagation();
  overlay.classList.add("gone");
  setPlaying(true);
};
overlay.onclick = () => startBtn.click();      /* 点遮罩任意处都算「开始」 */
prevBtn.onclick = () => goto(cur - 1);
nextBtn.onclick = () => goto(cur + 1);
slowerBtn.onclick = () => { if (si > 0) { si--; updateSpeed(); } };
fasterBtn.onclick = () => { if (si < SPEEDS.length - 1) { si++; updateSpeed(); } };
aeroBtn.onclick = () => {
  aeroOn = !aeroOn;
  aeroLayer.setAttribute("opacity", aeroOn ? 1 : 0);
  aeroBtn.classList.toggle("on", aeroOn);
};
scrub.oninput = () => goto(scrub.value - 1);

/* 键盘：空格播放/暂停，← → 逐圈（焦点在滑动条上时交给它自己处理） */
window.addEventListener("keydown", e => {
  if (e.target && e.target.tagName === "INPUT") return;
  if (e.code === "Space") { e.preventDefault(); setPlaying(!playing); }
  else if (e.code === "ArrowRight") { e.preventDefault(); goto(cur + 1); }
  else if (e.code === "ArrowLeft") { e.preventDefault(); goto(cur - 1); }
});

/* ?lap=N 跳到某圈；?autostart=1 跳过开场遮罩；?paused=1 进入但不播（截图/嵌入用） */
const qs = new URLSearchParams(location.search);
let AUTOSTART = false;
if (qs.get("autostart") === "1" || qs.get("paused") === "1") AUTOSTART = true;
const startLap = parseInt(qs.get("lap") || "1", 10);
if (startLap > 1) cur = Math.max(0, Math.min(frames.length - 1, startLap - 1));

render(cur, 0);
if (AUTOSTART) {
  overlay.classList.add("gone");
  setPlaying(qs.get("paused") !== "1");
} else {
  setPlaying(false);          /* 停在开场遮罩上，等手动点「开始比赛」 */
}
requestAnimationFrame(loop);
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser(description="生成逐圈回放动画（独立 HTML）")
    ap.add_argument("year", type=int)
    ap.add_argument("round", type=int)
    ap.add_argument("-o", "--out", default=None)
    args = ap.parse_args()

    data = build(args.year, args.round)
    title = f"F1 Oracle · 逐圈回放 · {data['year']} {data['event']}"
    subtitle = (f"{data['circuit']}　{data['country']}　"
                f"赛道 {data['track_length_m']} m　"
                f"{len(data['drivers'])} 位车手")
    total_ms = sum(f["ms"] for f in data["frames"])
    hh, rem = divmod(total_ms, 3_600_000)
    mm, ss = divmod(rem, 60_000)
    duration = (f"{hh}:{mm:02d}:{ss // 1000:02d}" if hh
                else f"{mm}:{ss // 1000:02d}")
    html_out = (TEMPLATE
                .replace("__TITLE__", html_esc(title))
                .replace("__EVENT__", html_esc(f"{data['year']} {data['event']}"))
                .replace("__SUBTITLE__", html_esc(subtitle))
                .replace("__TOTAL__", str(int(data["total_laps"])))
                .replace("__DURATION__", html_esc(duration))
                .replace("__DATA__", js_json(data)))

    out = Path(args.out) if args.out else (
        ROOT / "outputs" / f"replay_{data['year']}_R{data['round']:02d}.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_out, encoding="utf-8")
    print(f"✓ {data['year']} R{data['round']} {data['event']}")
    print(f"  {data['circuit']} · {data['total_laps']} 圈 · "
          f"{len(data['drivers'])} 车手 · {len(data['frames'])} 帧")
    print(f"  输出: {out}  ({out.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
