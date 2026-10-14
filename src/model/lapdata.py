"""逐圈数据层 —— 把 laps 表重建成「每场比赛的逐圈时间线」。

    tls = load_laptimelines(2024)
    for tl in tls:
        for lap in range(1, tl.total_laps + 1):
            running = tl.running(lap)              # 该圈仍在跑的车手
            pos     = tl.positions(lap)            # 该圈结束时的名次
            pace    = tl.recent_pace(lap, window=5)  # 最近 5 圈的干净圈速中位数
            gaps    = tl.gaps(lap)                 # 相对领跑者的秒差（需已回填 time_sec）

三个必须在这里解决的坑：
    1. 第 1 圈 lap_time 恒为 NULL —— recent_pace 自动跳过，无需特判
    2. 退赛后该车手再没有 laps 记录 —— running(lap) 就是「该圈有记录的车手」，
       天然排除了已退赛者，不需要额外判断
    3. 进站圈圈速含 20+ 秒停顿，不可比 —— is_pit=1 的圈不计入 recent_pace
    4. 安全车/虚拟安全车圈整场被压缩，圈速同样不可比 —— is_neutralized(k) 的圈
       也不计入 recent_pace（早期版本漏了这条，导致速度差算错，见 recent_pace 注释）

⚠️ 注意：states[lap] 的键是「该圈有 laps 记录的车手」，这既排除了已退赛者，
   也可能漏掉「仍在跑但该圈数据缺失」的极少数情况。做逐圈分析时把 running()
   当作「截至该圈仍在跑」的定义即可。
"""

from __future__ import annotations

import sqlite3
import statistics
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from src.semantics import is_finished
from src.model import cleanlap

ROOT = Path(__file__).resolve().parent.parent.parent
DB_PATH = ROOT / "data" / "f1_oracle.db"


@dataclass(frozen=True)
class Final:
    """最终结果（逐圈预测的评分目标）。"""
    position: int
    finished: bool
    status: str


class LapTimeline:
    """一场比赛的逐圈时间线。"""

    def __init__(self, year: int, round_no: int, total_laps: int,
                 states: dict[int, dict[str, dict]], final: dict[str, Final]):
        self.year = year
        self.round = round_no
        self.total_laps = total_laps
        self.states = states
        self.final = final
        self._stint_stats_cache: dict | None = None

    def stint_stats(self) -> dict:
        """(车手, stint) 的稳健统计（中位数/MAD），用于交通离群判定。首次调用时计算。"""
        if self._stint_stats_cache is None:
            self._stint_stats_cache = cleanlap.stint_stats(self)
        return self._stint_stats_cache

    @property
    def key(self) -> str:
        return f"{self.year}-R{self.round:02d}"

    def __repr__(self) -> str:
        return (f"<LapTimeline {self.key} {self.total_laps} 圈 "
                f"{len(self.final)} 车手>")

    def running(self, lap: int) -> list[str]:
        """截止该圈仍在跑的车手（该圈有记录的人）。"""
        return list(self.states.get(lap, {}))

    def positions(self, lap: int) -> dict[str, int]:
        """该圈结束时的赛道名次。position 可能为 NaN（少数圈），一律跳过。"""
        out: dict[str, int] = {}
        for d, s in self.states.get(lap, {}).items():
            p = s["position"]
            if p is None or p != p:      # p != p 用于识别 NaN
                continue
            out[d] = int(p)
        return out

    # ── 时间轴 / 秒差 ────────────────────────────────────────
    # 名次告诉你「谁在前面」，gap 才告诉你「他稳不稳」。
    # 数据来自 laps.time_sec（会话累计时间），由 scripts/backfill_lap_times.py 回填。

    def times(self, lap: int) -> dict[str, float]:
        """该圈完成时刻的会话累计时间（秒）。仅返回有值的车手。"""
        return {d: s["time_sec"] for d, s in self.states.get(lap, {}).items()
                if s.get("time_sec") is not None}

    def gaps(self, lap: int) -> dict[str, float]:
        """相对领跑者的秒差。领跑者 = 该圈仍在跑且累计时间最小者。

        用累计时间差而非名次差：名次是离散的，秒差能反映「追得上还是追不上」。
        """
        t = self.times(lap)
        if not t:
            return {}
        ref = min(t.values())
        return {d: v - ref for d, v in t.items()}

    def gap_ahead(self, lap: int) -> dict[str, float]:
        """相对「正前方那位车手」的秒差（按赛道名次相邻计算）。P1 记为 0。"""
        g = self.gaps(lap)
        pos = self.positions(lap)
        order = sorted((d for d in pos if d in g), key=lambda d: pos[d])
        out: dict[str, float] = {}
        for i, d in enumerate(order):
            out[d] = 0.0 if i == 0 else g[d] - g[order[i - 1]]
        return out

    def track_status(self, lap: int) -> set[str]:
        """该圈的赛道状态标志集合（'4'=安全车, '6'=虚拟安全车, '2'=黄旗, '5'=红旗…）。"""
        out: set[str] = set()
        for s in self.states.get(lap, {}).values():
            ts = s.get("track_status") or ""
            out.update(ch for ch in str(ts) if ch.isdigit())
        return out

    def is_neutralized(self, lap: int) -> bool:
        """该圈是否处于安全车 / 虚拟安全车（赛场被压缩，gap 失去可比性）。"""
        return bool(self.track_status(lap) & {"4", "6"})

    def recent_pace(self, lap: int, window: int = 5, clean: bool = True
                    ) -> dict[str, float]:
        """最近 window 圈的**干净**圈速中位数（秒）。

        完整清洗见 `src/model/cleanlap.py`，共排除五类不可比的圈：
        无圈速 / 进站圈 / 冷胎（含起跑前两圈）/ 安全车圈 / 交通受损圈。

        clean=False 退回旧口径（只排进站圈）—— **仅供对照，勿用于分析**：
        实测 2021 R22 第 40 圈，旧口径把 SAI 的近 6 圈混进 3 个安全车圈，
        中位数从 88.3s 被拉到 91.1s，凭空造出 3 秒/圈的假差距。
        """
        if clean:
            return cleanlap.clean_pace(self, lap, window, self.stint_stats())
        return self._raw_pace(lap, window)

    def _raw_pace(self, lap: int, window: int = 5) -> dict[str, float]:
        """旧口径：只排除进站圈。保留是为了能对照出清洗带来了多少变化。"""
        out: dict[str, float] = {}
        lo = max(1, lap - window + 1)
        for d in self.states.get(lap, {}):
            vals = []
            for k in range(lo, lap + 1):
                st = self.states.get(k, {}).get(d)
                if st and st["lap_time"] and not st["is_pit"]:
                    vals.append(st["lap_time"])
            if vals:
                out[d] = statistics.median(vals)
        return out

    def final_position(self, driver: str) -> int | None:
        f = self.final.get(driver)
        return f.position if f else None

    def finished(self, driver: str) -> bool:
        f = self.final.get(driver)
        return bool(f and f.finished)

    # ── 收敛曲线 / 转折点 ────────────────────────────────────

    def convergence(self, predictor=None) -> list[dict]:
        """逐圈收敛曲线：每圈预测一次，算 ρ，看比赛跑到第几圈基本定型。

        默认用**最保守的基线**（当前名次 = 最终名次）—— 它不知道速度、轮胎、
        策略，只知道现在谁在前面，所以给出的是**下界**。

        传入 `predictor` 可换成更聪明的预测器（签名 `(tl, lap) -> list[str]`），
        用来量化「比赛中的信息值多少钱」。实测 `lappredict.PaceProjection`
        在 gain=0.25 时中段 ρ 0.8017 vs 基线 0.7890（Δ+0.0128, t=+7.71）。

        ⚠️ 分母口径：只在该圈**仍在跑**的车手之间算 ρ。已退赛者的最终名次其实
        已经确定（排最后），算进去等于白送分，曲线会虚高。

        返回 [{'lap','progress','rho_all','rho_fin','n','n_fin','neutralized'}, ...]
        progress = lap / total_laps，因为不同比赛 44–78 圈不等，绝对圈数无法对齐。
        """
        from src.model.backtest import spearman  # 延迟导入，避免模型层内部相互依赖

        out: list[dict] = []
        for lap in sorted(self.states):
            pos = self.positions(lap)
            ds = [d for d in pos if d in self.final]
            if len(ds) < 3:
                continue
            if predictor is None:
                order = sorted(ds, key=lambda d: pos[d])
            else:
                dset = set(ds)
                order = [d for d in predictor(self, lap) if d in dset]
            pred_rank = {d: i + 1 for i, d in enumerate(order)}
            for j, d in enumerate(d for d in ds if d not in pred_rank):
                pred_rank[d] = len(order) + j + 1
            fin = [d for d in ds if self.final[d].finished]
            rho_fin = float("nan")
            if len(fin) >= 3:
                rho_fin = spearman([pred_rank[d] for d in fin],
                                   [self.final[d].position for d in fin])
            out.append({
                "lap": lap,
                "progress": lap / self.total_laps,
                "rho_all": spearman([pred_rank[d] for d in ds],
                                    [self.final[d].position for d in ds]),
                "rho_fin": rho_fin,
                "n": len(ds),
                "n_fin": len(fin),
                "neutralized": self.is_neutralized(lap),
            })
        return out

    def lead_changes(self) -> list[dict]:
        """领先权易手记录。返回 [{'lap','leader','prev','neutralized'}, ...]。

        第 1 圈不算「易手」（那是起跑），但会作为 prev 的起点。
        """
        out: list[dict] = []
        prev: str | None = None
        for lap in sorted(self.states):
            pos = self.positions(lap)
            if not pos:
                continue
            lead = min(pos, key=lambda d: pos[d])
            if prev is None:
                prev = lead
                continue
            if lead != prev:
                out.append({"lap": lap, "leader": lead, "prev": prev,
                            "neutralized": self.is_neutralized(lap)})
                prev = lead
        return out

    def swing_laps(self, top: int = 5) -> list[dict]:
        """单圈位置变动人数最多的圈 —— 安全车、大规模进站、事故的指纹。"""
        laps = sorted(self.states)
        rows: list[dict] = []
        for a, b in zip(laps, laps[1:]):
            p0, p1 = self.positions(a), self.positions(b)
            common = set(p0) & set(p1)
            moved = [d for d in common if p0[d] != p1[d]]
            rows.append({"lap": b, "moved": len(moved), "drivers": moved,
                         "neutralized": self.is_neutralized(b)})
        rows.sort(key=lambda r: -r["moved"])
        return rows[:top]


def load_laptimelines(year: int | None = None, db_path: Path | str = DB_PATH
                      ) -> list[LapTimeline]:
    """载入逐圈时间线。year=None 表示全部赛季（188K 行，较慢）。"""
    db = sqlite3.connect(str(db_path))
    yw = f" WHERE year={int(year)}" if year else ""
    yw_r = f" AND r.year={int(year)}" if year else ""

    # 时间轴字段由 scripts/backfill_lap_times.py 回填；若尚未回填则列不存在，
    # 用 NULL 占位以免整个数据层不可用。
    have = {r[1] for r in db.execute("PRAGMA table_info(laps)")}
    extra = {
        "time_sec": "time_sec" if "time_sec" in have else "NULL AS time_sec",
        "lap_start_sec": "lap_start_sec" if "lap_start_sec" in have else "NULL AS lap_start_sec",
        "track_status": "track_status" if "track_status" in have else "NULL AS track_status",
    }
    if not {"time_sec", "lap_start_sec", "track_status"} <= have:
        import warnings
        warnings.warn("laps 缺少时间轴字段，gap 相关功能不可用；"
                      "请先运行 python -m scripts.backfill_lap_times", stacklevel=2)

    laps = pd.read_sql_query(
        "SELECT year, round, driver, lap_number, position, lap_time, is_pit, "
        "compound, tyre_life, stint, "
        f"{extra['time_sec']}, {extra['lap_start_sec']}, {extra['track_status']} "
        "FROM laps" + yw, db)
    res = pd.read_sql_query(
        "SELECT r.year, r.round, r.driver, r.position, r.status FROM results r "
        "JOIN events e USING(year, round) WHERE e.round > 0" + yw_r, db)
    db.close()

    final_by_race: dict[tuple[int, int], dict[str, Final]] = {}
    for t in res.itertuples(index=False):
        final_by_race.setdefault((t.year, t.round), {})[t.driver] = Final(
            int(t.position), is_finished(t.status), t.status)

    out: list[LapTimeline] = []
    for (y, r), g in laps.groupby(["year", "round"]):
        states: dict[int, dict[str, dict]] = {}
        for lap, gg in g.groupby("lap_number"):
            states[int(lap)] = {
                t.driver: dict(position=t.position, lap_time=t.lap_time,
                               is_pit=bool(t.is_pit), compound=t.compound,
                               tyre_life=t.tyre_life,
                               stint=(None if pd.isna(t.stint) else int(t.stint)),
                               time_sec=(None if pd.isna(t.time_sec) else float(t.time_sec)),
                               lap_start_sec=(None if pd.isna(t.lap_start_sec)
                                              else float(t.lap_start_sec)),
                               track_status=(None if pd.isna(t.track_status)
                                             else str(t.track_status)))
                for t in gg.itertuples(index=False)}
        if not states:
            continue
        out.append(LapTimeline(int(y), int(r), max(states), states,
                               final_by_race.get((int(y), int(r)), {})))
    out.sort(key=lambda t: (t.year, t.round))
    return out
