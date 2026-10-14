"""F1 预测回测框架 —— 逐场推进，严格只用「该场之前」的信息。

## 为什么先建这个而不是先建模型
预测项目最大的陷阱不是模型不够好，而是**数据泄漏**：用全季聚合的积分榜去
"预测"第 5 站，回测分数会虚高，实盘根本复现不了，而且你永远不会发现。

所以把纪律写进结构里，不靠自觉：

    for race in races:                  # 按 (year, round) 严格递增
        pred = predictor.predict(ctx)   # ctx 只含「预测时点可得」的字段
        score_round(pred, race)         # 真值由框架持有，不交给预测器
        predictor.observe(race)         # 赛后才能学习

## 两种预测时点
    context="pre_quali"    排位赛前：只有历史数据，**不含发车格**
    context="post_quali"   排位赛后：额外知道发车格
`pre_quali` 模式下框架会把 grid 置为 None 再交给预测器 —— 结构性防止泄漏，
而不是靠预测器自己"记得别用"。

## 打分口径
    rho_all  预测名次 vs 真实 position（含退赛者）—— 与项目既有基准 0.622 同口径
    rho_fin  仅在所有完赛者之间比 —— 「纯速度」的排序质量
    另外三个是针对「谁夺冠」的：猜中率、冠军是否入预测前3、冠军的平均预测名次
"""

from __future__ import annotations

import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.semantics import is_finished  # noqa: E402

DB_PATH = ROOT / "data" / "f1_oracle.db"

WINNER_POINTS = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Entry:
    """预测时点可见的参赛信息。"""
    driver: str
    full_name: str
    team: str
    grid: int | None = None


@dataclass(frozen=True)
class Truth:
    """目标真值。框架持有，绝不交给预测器。"""
    position: int
    status: str
    points: float
    finished: bool


@dataclass
class Race:
    """一场比赛：可见信息 + 真值。"""
    year: int
    round: int
    event_name: str
    location: str
    circuit_id: str
    entries: list[Entry]
    truth: dict[str, Truth]
    sprint_points: dict[str, float]
    # 赛周内信息（是否可见由 make_context 决定，不在这里判断）
    fp: dict[str, dict[str, float]] = field(default_factory=dict)   # session -> driver -> 秒
    quali_gap: dict[str, float] = field(default_factory=dict)       # driver -> 落后杆位秒数
    quali_pos: dict[str, int] = field(default_factory=dict)         # driver -> 排位赛原始名次

    @property
    def key(self) -> str:
        return f"{self.year}-R{self.round:02d}"

    @property
    def winner(self) -> str:
        for d, t in self.truth.items():
            if t.position == 1:
                return d
        return ""

    @property
    def size(self) -> int:
        return len(self.entries)


@dataclass
class Round:
    """交给预测器的一场比赛 —— 不含任何结果信息。

    fp / quali_gap / quali_pos 只在预测时点合法时才由 make_context 填充：
        pre_quali   fp=有（FP 早于排位赛），quali_gap/quali_pos=空（排位赛还没跑）
        post_quali  fp=有，quali_gap/quali_pos=有
    想用 quali_* 的预测器在 pre_quali 下会拿到空 dict —— 结构性拿不到，不是靠自觉。

    ⚠️ quali_pos 与 grid 语义不同：quali_pos 是排位赛原始成绩名次，grid 是实际发车位置。
    两者之差 = 发车罚退（grid > quali_pos 表示自己被罚退；grid == 0 表示维修区起步）。
    实测罚退 >=10 位的车手，完赛名次与 quali_pos 的绝对差仅 2.16 位，
    而与 grid 的绝对差达 10.42 位 —— 见 predictors.AdjustedGridBaseline。
    """
    year: int
    round: int
    event_name: str
    location: str
    circuit_id: str
    entries: list[Entry]
    fp: dict[str, dict[str, float]] = field(default_factory=dict)
    quali_gap: dict[str, float] = field(default_factory=dict)
    quali_pos: dict[str, int] = field(default_factory=dict)

    @property
    def drivers(self) -> list[str]:
        return [e.driver for e in self.entries]

    @property
    def team_of(self) -> dict[str, str]:
        return {e.driver: e.team for e in self.entries}


# ═══════════════════════════════════════════════════════════
# 载入
# ═══════════════════════════════════════════════════════════
def load_races(db_path: Path | str = DB_PATH) -> list[Race]:
    """按 (year, round) 升序载入全部正赛。"""
    db = sqlite3.connect(str(db_path))

    alias: dict[str, str] = {}
    try:
        alias = dict(db.execute("SELECT location, circuit_id FROM circuit_aliases"))
    except sqlite3.OperationalError:
        pass  # circuits 表还没建，退回用原始 location

    meta = {
        (y, r): (name, loc)
        for y, r, name, loc in db.execute(
            "SELECT year, round, event_name, location FROM events WHERE round > 0")
    }

    rows: dict[tuple[int, int], list] = {}
    for rec in db.execute(
            """SELECT r.year, r.round, r.driver, r.full_name, r.team,
                      r.grid, r.position, r.points, r.status,
                      r.q1_sec, r.q2_sec, r.q3_sec, r.quali_pos
               FROM results r JOIN events e USING(year, round)
               WHERE e.round > 0"""):
        rows.setdefault(rec[0:2], []).append(rec[2:])

    sprint: dict[tuple[int, int], dict[str, float]] = {}
    for y, r, drv, pts in db.execute(
            "SELECT year, round, driver, points FROM sprint_points"):
        sprint.setdefault((y, r), {})[drv] = float(pts or 0.0)

    # 练习赛最快圈：按 session 分开存，让预测器自己选优先级
    # （实测 FP3 ρ=0.558 > FP2 0.526 > FP1 0.469；冲刺周末没有 FP3，须回退）
    fp: dict[tuple[int, int], dict[str, dict[str, float]]] = {}
    for y, r, drv, st, sec in db.execute(
            "SELECT year, round, driver, session_type, best_lap_sec FROM sessions "
            "WHERE best_lap_sec IS NOT NULL"):
        fp.setdefault((y, r), {}).setdefault(st, {})[drv] = float(sec)

    # 排位赛秒差：q1/q2/q3 取最快，再减去该场杆位成绩
    # 注意：q_best 跨赛段比较有轻微偏差（Q3 通常快于 Q1），但实测有效且简单
    qbest: dict[tuple[int, int], dict[str, float]] = {}
    for k, recs in rows.items():
        for rec in recs:
            drv, vals = rec[0], [x for x in (rec[7], rec[8], rec[9]) if x is not None]
            if vals:
                qbest.setdefault(k, {})[drv] = min(vals)
    quali_gap: dict[tuple[int, int], dict[str, float]] = {}
    for k, m in qbest.items():
        if m:
            ref = min(m.values())
            quali_gap[k] = {d: v - ref for d, v in m.items()}

    db.close()

    races: list[Race] = []
    for (y, r) in sorted(meta):
        recs = rows.get((y, r))
        if not recs:
            continue
        name, loc = meta[(y, r)]
        entries, truth = [], {}
        qpos: dict[str, int] = {}
        for rec in recs:
            drv, full, team, grid = rec[0], rec[1], rec[2], rec[3]
            pos, pts, st = rec[4], rec[5], rec[6]
            qp = rec[10]
            entries.append(Entry(drv, full, team, grid))
            truth[drv] = Truth(int(pos), st, float(pts or 0.0), is_finished(st))
            if qp is not None:
                qpos[drv] = int(qp)
        races.append(Race(
            year=y, round=r, event_name=name, location=loc,
            circuit_id=alias.get(loc, loc),
            entries=entries, truth=truth, sprint_points=sprint.get((y, r), {}),
            fp=fp.get((y, r), {}), quali_gap=quali_gap.get((y, r), {}),
            quali_pos=qpos,
        ))
    return races


def make_context(race: Race, context: str) -> Round:
    """构造交给预测器的比赛视图 —— 按预测时点剥离尚未发生的信号。

    pre_quali   排位赛前：剥掉发车格、清空排位秒差；练习赛（早于排位赛）保留
    post_quali  排位赛后：全部保留
    """
    if context == "post_quali":
        return Round(race.year, race.round, race.event_name, race.location,
                     race.circuit_id, list(race.entries),
                     fp=race.fp, quali_gap=race.quali_gap, quali_pos=race.quali_pos)
    if context == "pre_quali":
        # 练习赛在排位赛之前，所以 FP 可见；发车格与排位成绩都还没发生
        return Round(race.year, race.round, race.event_name, race.location,
                     race.circuit_id,
                     [Entry(e.driver, e.full_name, e.team, None) for e in race.entries],
                     fp=race.fp, quali_gap={}, quali_pos={})
    raise ValueError(f"未知预测时点: {context!r}（只能 pre_quali / post_quali）")


# ═══════════════════════════════════════════════════════════
# 打分
# ═══════════════════════════════════════════════════════════
def spearman(a, b) -> float:
    """Spearman 秩相关。用 pandas 的平均秩处理并列名次。"""
    if len(a) < 3:
        return float("nan")
    s = pd.Series(list(a)).rank()
    t = pd.Series(list(b)).rank()
    if s.nunique() < 2 or t.nunique() < 2:
        return float("nan")
    return float(s.corr(t))


def _ranks(order: list[str], race: Race) -> dict[str, int]:
    """预测顺序 → 车手到预测名次的映射。漏掉的车手一律排在最后。"""
    rank: dict[str, int] = {}
    for i, d in enumerate(order):
        if d in race.truth:
            rank.setdefault(d, i + 1)
    base = len(rank) + 1
    for j, d in enumerate(sorted(d for d in race.truth if d not in rank)):
        rank[d] = base + j
    return rank


def score_round(order: list[str], race: Race) -> dict | None:
    """给一次预测打分。order = 预测的完赛顺序（从第 1 到最末）。"""
    pred_rank = _ranks(order, race)
    if not pred_rank:
        return None

    drivers = list(pred_rank)
    rho_all = spearman([pred_rank[d] for d in drivers],
                       [race.truth[d].position for d in drivers])

    fin = [d for d in drivers if race.truth[d].finished]
    rho_fin = spearman([pred_rank[d] for d in fin],
                       [race.truth[d].position for d in fin])

    winner = race.winner
    return {
        "rho_all": rho_all,
        "rho_fin": rho_fin,
        "top1": float(order[0] == winner) if order else float("nan"),
        "top3": float(winner in order[:3]),
        "winner_rank": float(pred_rank.get(winner, float("nan"))),
        "n": len(drivers),
        "n_fin": len(fin),
    }


def practical_accuracy(races: list[Race], make_predictor, *,
                       context: str = "post_quali") -> dict:
    """把抽象的 ρ 翻译成人能感受的数字。

    ρ = 0.65 到底算好还是不好？这个函数回答：
        · 平均差几个名次
        · 有多少比例差在 ±1 / ±2 / ±3 位以内
        · 预测的前 3 / 前 5 / 前 10 里，真正的前 N 有几个人进去了（不看顺序）
        · 前段（好名次）和后段的准确度差多少
    """
    predictor = make_predictor()
    recs = []
    hit = {3: [0, 0], 5: [0, 0], 10: [0, 0]}

    for race in races:
        ctx = make_context(race, context)
        rank = _ranks(predictor.predict(ctx), race)
        for d, t in race.truth.items():
            recs.append((rank[d], t.position, t.finished))
        for n in hit:
            true_set = {d for d, t in race.truth.items() if t.position <= n}
            pred_set = {d for d in race.truth if rank[d] <= n}
            hit[n][0] += len(true_set & pred_set)
            hit[n][1] += len(true_set)
        predictor.observe(race)

    df = pd.DataFrame(recs, columns=["pred", "actual", "finished"])
    err = (df["pred"] - df["actual"]).abs()

    def bucket(lo: int, hi: int) -> float:
        sub = err[(df["actual"] >= lo) & (df["actual"] <= hi)]
        return float(sub.mean()) if len(sub) else float("nan")

    return {
        "n": len(df),
        "mae": float(err.mean()),
        "within1": float((err <= 1).mean()),
        "within2": float((err <= 2).mean()),
        "within3": float((err <= 3).mean()),
        "within5": float((err <= 5).mean()),
        "r1_5": bucket(1, 5),
        "r6_10": bucket(6, 10),
        "r11_15": bucket(11, 15),
        "r16_20": bucket(16, 20),
        "top": {n: (v[0] / v[1] if v[1] else float("nan")) for n, v in hit.items()},
    }


def format_accuracy(acc: dict, label: str) -> str:
    return (
        f"  {label}\n"
        f"    平均差 {acc['mae']:.2f} 个名次 ｜ "
        f"误差 ≤1 位 {acc['within1'] * 100:.0f}%、≤2 位 {acc['within2'] * 100:.0f}%、"
        f"≤3 位 {acc['within3'] * 100:.0f}%、≤5 位 {acc['within5'] * 100:.0f}%\n"
        f"    前 N 名命中率（不看顺序）：前3 {acc['top'][3] * 100:.0f}% ｜ "
        f"前5 {acc['top'][5] * 100:.0f}% ｜ 前10 {acc['top'][10] * 100:.0f}%\n"
        f"    分段平均误差：1-5名 {acc['r1_5']:.2f} ｜ 6-10名 {acc['r6_10']:.2f} ｜ "
        f"11-15名 {acc['r11_15']:.2f} ｜ 16-20名 {acc['r16_20']:.2f}")


# ═══════════════════════════════════════════════════════════
# 回测
# ═══════════════════════════════════════════════════════════
def run_backtest(races: list[Race], make_predictor, *, context: str = "pre_quali",
                 verbose: bool = False) -> pd.DataFrame:
    """逐场推进地回测。

    参数 make_predictor 必须是**无参可调用对象**（工厂），每次调用返回一个全新的
    预测器。预测器是有状态的 —— Elo 会累积评分、积分基线会累积积分 —— 复用同一个
    实例跑第二遍时，它在第 1 场就已经知道整季结果，属于静默泄漏。
    （本框架第一版就踩了这个坑：同一个 Elo 实例跑两遍，第二遍的逐年数字全错。）
    用工厂从结构上杜绝，而不是靠调用方记得重建。

    预测器需实现 predict(round) -> list[str] 与 observe(race)。
    """
    predictor = make_predictor()
    records = []
    for i, race in enumerate(races):
        ctx = make_context(race, context)
        order = predictor.predict(ctx)
        sc = score_round(order, race)
        if sc is not None:
            sc.update(key=race.key, year=race.year, round=race.round)
            records.append(sc)
        predictor.observe(race)
        if verbose and (i + 1) % 40 == 0:
            print(f"    ... 已回测 {i + 1}/{len(races)} 场")
    return pd.DataFrame(records)


def summarize(df: pd.DataFrame, *, label: str, drop_years: set[int] | None = None) -> dict:
    d = df if not drop_years else df[~df["year"].isin(drop_years)]
    if d.empty:
        return {"label": label, "races": 0}
    return {
        "label": label,
        "races": len(d),
        "rho_all": float(d["rho_all"].mean()),
        "rho_fin": float(d["rho_fin"].mean()),
        "top1": float(d["top1"].mean()),
        "top3": float(d["top3"].mean()),
        "winner_rank": float(d["winner_rank"].mean()),
    }


def format_table(rows: list[dict]) -> str:
    """把 summarize 的结果排成对齐的记分板。"""
    head = (f"  {'预测器':<26}{'场次':>5}{'ρ(全部)':>9}{'ρ(完赛)':>9}"
            f"{'猜中冠军':>9}{'冠军入前3':>10}{'冠军均名次':>11}")
    lines = [head, "  " + "─" * (len(head) - 2)]
    for r in rows:
        if not r.get("races"):
            continue
        lines.append(
            f"  {r['label']:<26}{r['races']:>5}{r['rho_all']:>9.4f}{r['rho_fin']:>9.4f}"
            f"{r['top1'] * 100:>8.1f}%{r['top3'] * 100:>9.1f}%{r['winner_rank']:>11.2f}")
    return "\n".join(lines)
