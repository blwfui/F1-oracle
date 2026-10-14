"""预测器：L0 零假设基线 + L1 Elo。

所有预测器都遵守同一协议（鸭子类型，无需继承）：
    predict(ctx: Round) -> list[str]   按预测的完赛顺序返回车手缩写
    observe(race: Race) -> None        赛后学习（框架在打分之后才调用）

⚠️ predict 里**只能**用 ctx 上的字段。想知道方向盘后面的真相，看 observe。
"""

from __future__ import annotations

import random

from .backtest import Entry, Race, Round


# ═══════════════════════════════════════════════════════════
# L0 —— 零假设基线。不打败它们就说明什么都没做出来。
# ═══════════════════════════════════════════════════════════
class RandomBaseline:
    """自检用：框架若正确，这个的 ρ 必须 ≈ 0，猜中冠军 ≈ 1/n。"""

    def __init__(self, seed: int = 20261013):
        self.rng = random.Random(seed)
        self.name = "L0 随机（自检用）"

    def predict(self, ctx: Round) -> list[str]:
        ds = list(ctx.drivers)
        self.rng.shuffle(ds)
        return ds

    def observe(self, race: Race) -> None:
        pass


def _grid_key(e: Entry) -> tuple:
    """发车格升序；grid=0（维修区起步）与缺失一律压到最后。"""
    if e.grid is None or e.grid <= 0:
        return (1, 999, e.driver)
    return (0, e.grid, e.driver)


class GridBaseline:
    """排位赛后的最强单变量。项目既有基准 ρ=0.622 就是它。"""

    name = "L0 发车格顺序"

    def predict(self, ctx: Round) -> list[str]:
        return [e.driver for e in sorted(ctx.entries, key=_grid_key)]

    def observe(self, race: Race) -> None:
        pass


class AdjustedGridBaseline:
    """发车格，但把「罚退幅度」按 alpha 收缩掉 —— 因为罚退不是速度。

    动机（全库实测）：
        被罚退的车手，实际发车位置远差于其真实速度，而**排位名次比发车格准得多**。

        | 罚退幅度 | n    | |完赛 − 发车格| | |完赛 − 排位名次| |
        | 未罚退   | 2120 |      2.61      |       2.61       |
        | 3–9 位   |  126 |      5.52      |       3.23       |
        | ≥10 位   |   19 |     10.42      |       2.16       |

        典型：VER 2022 斯帕 排位P1→发车P14→完赛P1；HAM 2022 蒙扎 P5→P19→P5。

    编码：effective = grid − alpha · max(0, grid − quali_pos)      [仅当 pen ≥ min_pen]
        alpha=0   → 纯发车格（现状，对罚退毫无补偿）
        alpha=1   → 完全按排位名次起算（认为罚退不影响完赛）

    min_pen 的作用：实测对 pen=1~2 的小罚退做修正**反而有害**（未受影响场次
    ρ 从 0.6576 掉到 0.6559）—— 小罚退没有实质影响，修正只是引入噪声。
    取 min_pen=3 后，pen<3 的车手 effective 与 grid 完全一致，零影响。

    grid=0（维修区起步）没有有效发车位，一律压到最后（与 _grid_key 一致）。

    ⚠️ 选择偏差警告：被重罚的多是强队车手（只有前排才值得换动力单元），
    所以「他们平均爬回多少」高估了罚退的可补偿性 —— alpha 不能从那张表直接推。
    实测（145 条罚退条目，逐条目配对检验）：
        α=0.5  Δ|误差| = −0.324 位  t = −3.88
        α=0.75 Δ|误差| = −0.552 位  t = −4.31   ← 选它
        α=1    Δ|误差| = −0.621 位  t = −4.15
    选 0.75 而非 1.0 是基于**无偏性**：α=1 时平均偏差转为 −1.00 位（高估被罚者），
    α=0.75 时 +0.97 位且重罚组（≥10位）表现最佳（−1.37 位）。
    """

    def __init__(self, alpha: float = 0.75, min_pen: int = 3) -> None:
        self.alpha = alpha
        self.min_pen = min_pen
        self.name = f"L0 发车格·罚退收缩(α={alpha:g},≥{min_pen})"

    def predict(self, ctx: Round) -> list[str]:
        def key(e: Entry) -> tuple:
            if e.grid is None or e.grid <= 0:
                return (1, 999.0, e.driver)
            qp = ctx.quali_pos.get(e.driver)
            eff = float(e.grid)
            if qp is not None and e.grid - qp >= self.min_pen:
                eff = e.grid - self.alpha * (e.grid - qp)
            return (0, eff, e.driver)

        return [e.driver for e in sorted(ctx.entries, key=key)]

    def observe(self, race: Race) -> None:
        pass


class PointsBaseline:
    """按赛季至今积分（正赛 + 冲刺）降序。排位赛前能拿到的最强信号。"""

    name = "L0 赛前积分榜"

    def __init__(self) -> None:
        self.pts: dict[tuple[int, str], float] = {}

    def predict(self, ctx: Round) -> list[str]:
        return sorted(ctx.drivers,
                      key=lambda d: (-self.pts.get((ctx.year, d), 0.0), d))

    def observe(self, race: Race) -> None:
        for e in race.entries:
            t = race.truth[e.driver]
            k = (race.year, e.driver)
            self.pts[k] = (self.pts.get(k, 0.0) + t.points
                           + race.sprint_points.get(e.driver, 0.0))


class PrevFinishBaseline:
    """按最近一次的名次（动量）。没出赛过的排最后。"""

    name = "L0 上一站名次"

    def __init__(self) -> None:
        self.last: dict[str, int] = {}

    def predict(self, ctx: Round) -> list[str]:
        return sorted(ctx.drivers, key=lambda d: (self.last.get(d, 999), d))

    def observe(self, race: Race) -> None:
        for e in race.entries:
            self.last[e.driver] = race.truth[e.driver].position


class AvgFinishBaseline:
    """按「平均完赛名次」升序 —— 最直觉的强度信号，也是 Elo 最该被对照的对象。

    window=0    本赛季至今平均（口径最接近积分榜，但赛季初几站没数据 → 靠后）
    window=N    最近 N 场滚动平均（跨赛季延续，年初不是空的）

    include_dnf
        True   把退赛者也算进平均（用 FastF1 给的分类名次 11–20）
        False  只算完赛者（退赛当没发生）

    ⚠️ 这个开关正是 Elo 那条 `finishers_only` 的账：
       退赛者的 position 是「分类名次」而非完赛名次，含进来等于把
       "运气差"当成"速度慢"。两种口径谁更好，要用回测说话，不能凭直觉。
    """

    def __init__(self, window: int = 0, include_dnf: bool = True) -> None:
        self.window = window
        self.include_dnf = include_dnf
        self.hist: dict[str, list[int]] = {}
        self._year: dict[str, int] = {}
        scope = f"近{window}场" if window else "本季"
        self.name = f"L0 平均名次({scope}{'·含退赛' if include_dnf else '·仅完赛'})"

    def predict(self, ctx: Round) -> list[str]:
        def key(d: str) -> tuple:
            h = self.hist.get(d)
            if not h:
                return (1, 999.0, d)
            return (0, sum(h) / len(h), d)

        return sorted(ctx.drivers, key=key)

    def observe(self, race: Race) -> None:
        for e in race.entries:
            t = race.truth[e.driver]
            if not self.include_dnf and not t.finished:
                continue
            if not self.window and self._year.get(e.driver) != race.year:
                self.hist[e.driver] = []          # 本季口径：跨年清空
            self._year[e.driver] = race.year
            h = self.hist.setdefault(e.driver, [])
            h.append(t.position)
            if self.window and len(h) > self.window:
                del h[0]


class CircuitHistoryBaseline:
    """按该赛道历史平均完赛名次（用 circuit_id，已做别名归一）；无历史则退到积分榜。"""

    name = "L0 该赛道历史名次"

    def __init__(self) -> None:
        self.hist: dict[tuple[str, str], list[int]] = {}
        self.pts: dict[tuple[int, str], float] = {}

    def predict(self, ctx: Round) -> list[str]:
        def key(d: str) -> tuple:
            h = self.hist.get((ctx.circuit_id, d))
            if h:
                return (0, sum(h) / len(h), d)
            return (1, -self.pts.get((ctx.year, d), 0.0), d)

        return sorted(ctx.drivers, key=key)

    def observe(self, race: Race) -> None:
        for e in race.entries:
            t = race.truth[e.driver]
            if t.finished:
                self.hist.setdefault((race.circuit_id, e.driver), []).append(t.position)
            k = (race.year, e.driver)
            self.pts[k] = (self.pts.get(k, 0.0) + t.points
                           + race.sprint_points.get(e.driver, 0.0))


# ═══════════════════════════════════════════════════════════
# L2 —— 赛周内的新信号
# ═══════════════════════════════════════════════════════════
# 这两个信号的数据一直都在库里（sessions 9410 条 / results 的 q1-q3 覆盖 98.1%），
# 只是模型从未用过。实测都能带来统计显著的增量，且与 Elo 互补。
class PracticePaceBaseline:
    """按练习赛最快圈排序。**pre_quali 合法** —— FP 排在排位赛之前。

    session 优先级从晚到早：越接近排位赛，条件越相似，信息量越大。
        实测单变量 ρ：FP3 0.5583 > FP2 0.5259 > FP1 0.4687
    冲刺周末没有 FP3（173 场里只有 145 场有），所以必须能逐级回退。

    ⚠️ 不要用 fp 里的数据去"补"排位赛成绩 —— 那是另一回事。
    """

    def __init__(self, order: tuple[str, ...] = ("FP3", "FP2", "FP1"),
                 label: str | None = None):
        self.order = tuple(order)
        self.name = label or f"L2 练习赛最快圈({'/'.join(self.order)})"

    def _laps(self, ctx: Round) -> dict[str, float]:
        for st in self.order:
            d = ctx.fp.get(st)
            if d:
                return d
        return {}

    def predict(self, ctx: Round) -> list[str]:
        best = self._laps(ctx)
        return sorted(ctx.drivers, key=lambda d: (best.get(d, 1e9), d))

    def observe(self, race: Race) -> None:
        pass


class QualiGapBaseline:
    """按排位赛最快圈相对杆位的秒差排序。**post_quali 合法**。

    与 GridBaseline 的区别：grid 是起跑位（含罚退），本基线是**纯速度差距**。
    同为第 5 位起步，可能只落后杆位 0.05s（几乎一样快），也可能落后 0.5s ——
    名次看不出这个差别，秒差可以。实测单变量 ρ=0.6366 > 纯发车格 0.6223。

    ⚠️ pre_quali 下 ctx.quali_gap 是空的（框架不暴露），本预测器会退化成
    全并列、ρ=nan。这是设计如此，不是 bug。
    """

    name = "L2 排位赛秒差"

    def predict(self, ctx: Round) -> list[str]:
        gap = ctx.quali_gap
        return sorted(ctx.drivers, key=lambda d: (gap.get(d, 1e9), d))

    def observe(self, race: Race) -> None:
        pass


# ═══════════════════════════════════════════════════════════
# L1 —— Elo
# ═══════════════════════════════════════════════════════════
class EloPredictor:
    """车手 Elo + 车队 Elo，逐站赛后自动更新。

    预测强度 = 车手评分 + (车队评分 − base)
        车队单独建模，所以车手换队时不会把旧赛车的能力带过去。
        use_team=False 时退化为单一车手评分（把赛车性能一并吸收）。

    更新：把一场比赛视为所有两两对决（C(n,2) 对），
        期望 E = 1 / (1 + 10^((s_j − s_i)/400))，实际 S = 1（i 排在 j 前）
        Δ_i = K/(n−1) · Σ(S − E)，再按 driver_share 拆给车手与车队。
        K/(n−1) 的缩放让每人每站的总变动量级与标准 Elo 可比。

    dnf_policy
        "as_position"    退赛者按分类名次参与（等价于"输给所有完赛者"）
        "finishers_only" 只用完赛者之间的对决；退赛者本场不动评分

    ⚠️ 用 finishers_only，不要用 as_position —— 实测：
        排位赛前 +0.0121 (t=3.56)、排位赛后 +0.0048 (t=2.03)。
    原因：退赛主要是随机事件，把它当"输"等于把可靠性噪声灌进本该是速度的评分。
    这比单独建一个 DNF 模型更有效（见 ReliabilityModel 的实测记录）。
    """

    def __init__(self, k: float = 24.0, base: float = 1500.0,
                 driver_share: float = 0.7, use_team: bool = True,
                 dnf_policy: str = "as_position", label: str | None = None):
        if dnf_policy not in ("as_position", "finishers_only"):
            raise ValueError(dnf_policy)
        self.k = k
        self.base = base
        self.driver_share = driver_share
        self.use_team = use_team
        self.dnf_policy = dnf_policy
        self.driver: dict[str, float] = {}
        self.team: dict[str, float] = {}
        self.name = label or (
            f"L1 Elo({'车手+车队' if use_team else '仅车手'}, k={k:g}, "
            f"{'含退赛' if dnf_policy == 'as_position' else '仅完赛者'})")

    def strength(self, driver: str, team: str) -> float:
        d = self.driver.get(driver, self.base)
        if not self.use_team:
            return d
        return d + (self.team.get(team, self.base) - self.base)

    def predict(self, ctx: Round) -> list[str]:
        team_of = ctx.team_of
        return sorted(ctx.drivers,
                      key=lambda d: (-self.strength(d, team_of[d]), d))

    def observe(self, race: Race) -> None:
        order = sorted(race.entries, key=lambda e: race.truth[e.driver].position)
        n = len(order)
        if n < 2:
            return

        s = {e.driver: self.strength(e.driver, e.team) for e in order}
        team_of = {e.driver: e.team for e in order}
        fin = {e.driver: race.truth[e.driver].finished for e in order}
        step = self.k / (n - 1)
        delta = {d: 0.0 for d in s}

        for a in range(n):
            da = order[a].driver
            for b in range(a + 1, n):
                db = order[b].driver
                if self.dnf_policy == "finishers_only" and not (fin[da] and fin[db]):
                    continue
                exp_a = 1.0 / (1.0 + 10.0 ** ((s[db] - s[da]) / 400.0))
                delta[da] += step * (1.0 - exp_a)
                delta[db] += step * (exp_a - 1.0)

        for d, dv in delta.items():
            if dv == 0.0:
                continue
            self.driver[d] = self.driver.get(d, self.base) + dv * self.driver_share
            if self.use_team:
                t = team_of[d]
                self.team[t] = (self.team.get(t, self.base)
                                + dv * (1.0 - self.driver_share))


# ═══════════════════════════════════════════════════════════
# 双模型 —— 已证伪的假设，保留作为记录（不要重试）
# ═══════════════════════════════════════════════════════════
# 假设：ρ(完赛) 比 ρ(全部) 高约 0.16，说明「谁会退赛」有可利用的信号，
#       应该把可靠性单独建模再加回去。
#
# 实测结论（173 场，见项目记忆 2026-10-13）：
#   · 可靠性模型 AUC = 0.5351（随机 = 0.500）；"风险最高 3 人"命中 15.8% vs 基准 14.9%
#   · 叠加到最佳组合后 Δρ = -0.0011 (t=-1.63) / -0.0001 (t=-0.21) —— 无增量，略负
#   → 那 0.16 的差距**不是「没建模」，而是不可约的噪声**：单场退赛基本是随机的
#     （碰撞、机械故障、被波及），历史退赛率只提供极弱的信息。
#
# 真正有效的做法简单得多：让速度模型更新时忽略退赛者（dnf_policy="finishers_only"），
# 实测 +0.0121 (t=3.56)，不需要第二个模型。
#
# 这两个类保留下来是为了避免以后重复探索同一条死路。
DNF_POS_RATIO = 0.92   # 退赛者的期望分类名次 ≈ 0.92 × 参赛人数（实测 18.4 / 20）


class ReliabilityModel:
    """累积「截止上一站」的退赛率，贝叶斯收缩到全局先验。

    分三个维度建模，因为退赛成因不同：
        车队 —— 机械故障（引擎 / 变速箱 / 液压），历史上是最强的单一预测因子
        车手 —— 个人失误（碰撞 / 打滑）
        赛道 —— 环境风险（Monaco 的墙、街道赛）

    每个维度的估计都收缩到全局退赛率先验：样本越少越靠近先验，所以首次参赛的
    新车手、新车队、新赛道不会给出 0% 或 100% 这种极端值。

    ⚠️ 实测 AUC 仅 0.5351，对排序无增量。保留仅为记录，勿用于生产路径。
    """

    def __init__(self, alpha: float = 12.0,
                 weights: tuple[float, float, float] = (0.4, 0.4, 0.2)):
        self.alpha = alpha
        self.w_driver, self.w_team, self.w_circuit = weights
        self.n_driver: dict[str, list[int]] = {}
        self.n_team: dict[str, list[int]] = {}
        self.n_circuit: dict[str, list[int]] = {}
        self.global_n = [0, 0]      # [dnf, total]

    def _prior(self) -> float:
        d, n = self.global_n
        return d / n if n else 0.15

    def _rate(self, cnt: list[int] | None, prior: float) -> float:
        if not cnt:
            return prior
        d, n = cnt
        return (d + self.alpha * prior) / (n + self.alpha)

    def prob(self, ctx: Round) -> dict[str, float]:
        """每个车手本场的退赛概率。只用截止上一站的数据。"""
        prior = self._prior()
        team_of = ctx.team_of
        out = {}
        for d in ctx.drivers:
            out[d] = (self.w_driver * self._rate(self.n_driver.get(d), prior)
                      + self.w_team * self._rate(self.n_team.get(team_of.get(d, "")), prior)
                      + self.w_circuit * self._rate(self.n_circuit.get(ctx.circuit_id), prior))
        return out

    def observe(self, race: Race) -> None:
        for e in race.entries:
            dnf = 0 if race.truth[e.driver].finished else 1
            for store, key in ((self.n_driver, e.driver),
                               (self.n_team, e.team),
                               (self.n_circuit, race.circuit_id)):
                c = store.setdefault(key, [0, 0])
                c[0] += dnf
                c[1] += 1
            self.global_n[0] += dnf
            self.global_n[1] += 1


class DnfAwarePredictor:
    """速度模型 + 退赛风险 → 期望完赛名次。

        E[名次] = (1 − p_dnf) · 速度名次 + p_dnf · 退赛名次

    这样「快但脆」与「慢但稳」会被分开排序，而不是揉成一个平均名次。
    纯速度模型若把可靠性也算进自己的评分，就会重复计算 —— 所以搭配时
    速度模型宜用 dnf_policy="finishers_only"（只学速度，不管退赛）。

    speed_factory 必须是工厂：框架要求每次回测都重建（预测器有状态）。

    ⚠️ 实测叠加后 Δρ = -0.0011 (t=-1.63)，无增量。保留仅为记录，勿用于生产路径。
    """

    def __init__(self, speed_factory, alpha: float = 12.0,
                 weights: tuple[float, float, float] = (0.4, 0.4, 0.2),
                 label: str | None = None):
        self.speed = speed_factory()
        self.rel = ReliabilityModel(alpha, weights)
        self.name = label or f"DNF感知({self.speed.name})"

    def predict(self, ctx: Round) -> list[str]:
        rank = {d: i + 1 for i, d in enumerate(self.speed.predict(ctx))}
        p = self.rel.prob(ctx)
        dnf_pos = DNF_POS_RATIO * len(ctx.drivers)
        exp_pos = {d: (1.0 - p[d]) * rank[d] + p[d] * dnf_pos for d in ctx.drivers}
        return sorted(ctx.drivers, key=lambda d: (exp_pos[d], d))

    def observe(self, race: Race) -> None:
        self.speed.observe(race)
        self.rel.observe(race)


class RankBlend:
    """把多个预测器的名次加权求和后重排。

    用来回答「发车格之外还有没有增量信息」：
        w=1.0 → 纯发车格；w=0.0 → 纯 Elo。
        若中间某个 w 的 ρ 明显更高，说明两者互补 —— Elo 带来了新信息。
    """

    def __init__(self, parts: list[tuple[object, float]], label: str):
        self.parts = parts
        self.name = label

    def predict(self, ctx: Round) -> list[str]:
        score = {d: 0.0 for d in ctx.drivers}
        for p, w in self.parts:
            for i, d in enumerate(p.predict(ctx)):
                if d in score:
                    score[d] += w * (i + 1)
        return sorted(ctx.drivers, key=lambda d: (score[d], d))

    def observe(self, race: Race) -> None:
        for p, _ in self.parts:
            p.observe(race)


# ═══════════════════════════════════════════════════════════
# 当前最佳组合 —— 唯一定义，回测与演示都用这一份
# ═══════════════════════════════════════════════════════════
def best_pre():
    """排位赛前的当前最佳组合：Elo + 赛前积分榜 + 练习赛。

    练习赛是唯一「时间上紧邻排位赛」的合法信号，且与 Elo 独立（实测 Δρ +0.0267, t=2.62）。
    Elo 用 finishers_only：退赛者不参与评分更新，把可靠性噪声挡在速度评分之外
    （实测比 as_position 高 +0.0121, t=3.56）。
    """
    return RankBlend([(EloPredictor(k=192, use_team=True, dnf_policy="finishers_only"), 0.4),
                      (PointsBaseline(), 0.3),
                      (PracticePaceBaseline(), 0.3)], "Elo+积分榜+练习赛")


def best_post():
    """排位赛后的当前最佳组合：发车格(罚退收缩) + 排位秒差 + Elo。

    秒差补上「起跑位看不出的速度差」；Elo 补上「排位赛看不出的赛季实力」。
    Elo 用 finishers_only（实测 0.6493 → 0.6542, t=2.03）。

    发车格用 AdjustedGridBaseline 而非纯 GridBaseline：被罚退的车手实际发车位置
    远差于其真实速度。实测（145 条罚退条目，逐条目配对检验）该修正让被罚退者
    本人的名次误差降低 0.55 位（t=−4.26），系统低估从 +2.23 位降到 +0.96 位；
    同时对未受影响的 81 场**逐行零影响**，全量 ρ 不变（0.6542→0.6543），
    冠军入前3 89.6%→90.8%。即：只修偏差，不换排序。
    """
    return RankBlend([(AdjustedGridBaseline(alpha=0.75, min_pen=3), 0.4),
                      (QualiGapBaseline(), 0.3),
                      (EloPredictor(k=192, use_team=True,
                                    dnf_policy="finishers_only"), 0.3)], "发车格(罚退收缩)+秒差+Elo")
