"""Page: 赛前预测 · 逐圈复盘

把 `src/model/` 的预测能力搬进仪表板，严格按时间顺序 **一段一段** 展示：

    ① 赛前分析    只用赛季数据 + 练习赛（不知道发车格）
    ② 排位赛后    加上发车格 / 罚退 / 排位秒差
    ③ 逐圈复盘    每圈「当前名次 = 最终名次」的收敛曲线 + 转折点
    ④ 赛后实测    预测 vs 实际，逐项打分

防泄漏由模型层结构保证（`make_context` 决定哪些信号可见），这里只负责展示，
不在 UI 层做任何「选择性隐藏」—— 否则就变成事后诸葛了。
"""

import sys
from pathlib import Path

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from common import *  # noqa: F403

# ── 模型层导入 ────────────────────────────────────────────────
# src/ 是命名空间包，需要项目根目录在 sys.path 上
_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.model.backtest import load_races, make_context, score_round  # noqa: E402
from src.model.lapdata import load_laptimelines  # noqa: E402
from src.model.predictors import best_post, best_pre  # noqa: E402


# ═══════════════════════════════════════════════════════════
# 缓存：模型层很重，整个会话只做一次
# ═══════════════════════════════════════════════════════════

@st.cache_resource(show_spinner=False)
def _races():
    """全部 173 场（含 Elo 需要的完整时间序）。"""
    return load_races()


@st.cache_resource(show_spinner=False)
def _timelines(year: int):
    return {t.round: t for t in load_laptimelines(year)}


@st.cache_data(show_spinner=False)
def _predict(year: int, rnd: int, ctx_name: str) -> list[str]:
    """防泄漏预测：只 observe 本场之前的比赛。

    不能用 run_backtest 整季跑（那会看到未来）。这里显式截断到 races[:idx]。
    """
    races = _races()
    idx = next((i for i, r in enumerate(races)
                if r.year == year and r.round == rnd), None)
    if idx is None:
        return []
    factory = best_pre if ctx_name == "pre_quali" else best_post
    p = factory()
    for r in races[:idx]:
        p.observe(r)
    return p.predict(make_context(races[idx], ctx_name))


@st.cache_data(show_spinner=False)
def _asof_points(year: int, rnd: int) -> dict:
    """本场之前的车手积分（正赛 + 冲刺）。"""
    df = query(f"""
        SELECT driver, SUM(points) AS pts FROM (
            SELECT driver, points FROM results WHERE year={year} AND round < {rnd}
            UNION ALL
            SELECT driver, points FROM sprint_points WHERE year={year} AND round < {rnd}
        ) GROUP BY driver
    """)
    return dict(zip(df["driver"], df["pts"].astype(float)))


@st.cache_data(show_spinner=False)
def _convergence(year: int, rnd: int):
    """返回 (基线曲线, 模型曲线)。

    基线 = 「当前名次 = 最终名次」，是下界；模型 = 节奏外推（gain=0.25）。
    两条线画在一起，差值就是「比赛中的信息值多少钱」。
    """
    tl = _timelines(year).get(rnd)
    if tl is None:
        return [], []
    from src.model.lappredict import (
        DEFAULT_GAIN, DEFAULT_WINDOW, PaceProjectionCached, cached_pace,
    )
    table = cached_pace(tl, DEFAULT_WINDOW)
    model = PaceProjectionCached(table, DEFAULT_WINDOW, DEFAULT_GAIN)
    return tl.convergence(), tl.convergence(model.predict)


def _team_of(year: int, rnd: int) -> dict:
    df = query(f"SELECT driver, team FROM results WHERE year={year} AND round={rnd}")
    return dict(zip(df["driver"], df["team"]))


def _col(team: str) -> str:
    return TEAM_COLORS.get(team, F1_RED)  # noqa: F405


# ═══════════════════════════════════════════════════════════
# 渲染
# ═══════════════════════════════════════════════════════════

def render(year):
    st.markdown(SCROLL_TOP_JS, unsafe_allow_html=True)  # noqa: F405
    st.title("🎯 赛前预测 · 逐圈复盘")

    ev = query(f"""
        SELECT round, event_name, location FROM events
        WHERE year={year} AND round > 0 ORDER BY round
    """)
    if ev.empty:
        st.info(f"{year} 赛季暂无数据")
        return

    labels = [f"R{int(r)} · {_ename(e)}" for r, e in zip(ev["round"], ev["event_name"])]
    rounds = [int(r) for r in ev["round"]]
    pick = st.selectbox("选择分站", labels, index=len(labels) - 1)
    rnd = rounds[labels.index(pick)]
    teams = _team_of(year, rnd)

    t1, t2, t3, t4 = st.tabs(["① 赛前分析", "② 排位赛后", "③ 逐圈复盘", "④ 赛后实测"])
    with t1:
        _tab_pre(year, rnd, teams)
    with t2:
        _tab_quali(year, rnd, teams)
    with t3:
        _tab_laps(year, rnd, teams)
    with t4:
        _tab_result(year, rnd, teams)


# ── ① 赛前 ───────────────────────────────────────────────────

def _tab_pre(year, rnd, teams):
    st.caption("模型此时**只看得到赛季数据 + 练习赛**，不知道排位赛成绩，也不知道发车格。")

    pts = _asof_points(year, rnd)
    if pts:
        df = (pd.DataFrame({"driver": list(pts), "pts": list(pts.values())})  # noqa: F405
              .sort_values("pts", ascending=False).head(10).reset_index(drop=True))
        df["name"] = df["driver"].apply(_dname)  # noqa: F405
        df["team"] = df["driver"].map(teams)
        order = df["name"].tolist()[::-1]
        fig = px.bar(df, x="pts", y="name", orientation="h", text="pts")  # noqa: F405
        fig = _chart_style(fig, height=340)  # noqa: F405
        fig.update_traces(marker_color=[_col(t) for t in df["team"]][::-1],
                          texttemplate="%{text:.0f}", textposition="outside",
                          textfont=dict(color="#555555", size=11))
        fig.update_layout(xaxis_title="赛前积分", yaxis_title="", showlegend=False,
                          title="赛前车手积分榜（本场之前的累计）")
        fig.update_yaxes(categoryarray=order)
        st.plotly_chart(fig, use_container_width=True)

    order = _predict(year, rnd, "pre_quali")
    if not order:
        st.warning("该场无历史数据，无法预测")
        return
    st.subheader("模型预测（赛前口径）")
    _order_table(order, teams, "冠军热门")
    st.caption("赛前口径用的是 Elo（车手+车队）+ 赛前积分榜 + 练习赛最快圈。"
               "实测该口径整榜 ρ ≈ 0.607（纯抄积分榜是 0.550）。")


# ── ② 排位赛后 ───────────────────────────────────────────────

def _tab_quali(year, rnd, teams):
    st.caption("排位赛跑完：拿到了**发车格**、**排位秒差**，也知道了谁被罚退。")

    q = query(f"""
        SELECT driver, quali_pos, q1_sec, q2_sec, q3_sec, grid
        FROM results WHERE year={year} AND round={rnd} AND quali_pos IS NOT NULL
        ORDER BY quali_pos
    """)
    if q.empty:
        st.info("该场无排位数据（上游缺失）")
        return
    q["time"] = q[["q3_sec", "q2_sec", "q1_sec"]].bfill(axis=1).iloc[:, 0]
    pole = q["time"].dropna().min()

    with st.expander("排位赛完整成绩", expanded=False):
        if pd.notna(pole):  # noqa: F405
            st.caption(f"杆位成绩 {_fmt_lap_time(pole)}　（括号内为落后杆位秒数）")  # noqa: F405
        rows = []
        for _, r in q.iterrows():
            gap = (f"({r['time'] - pole:+.3f})"
                   if pd.notna(r["time"]) and pd.notna(pole) else "—")  # noqa: F405
            rows.append({"排位": f"Q{int(r['quali_pos'])}",
                         "车手": _dname(r["driver"]),  # noqa: F405
                         "最快圈": _fmt_lap_time(r["time"]) or "—",  # noqa: F405
                         "差距": gap,
                         "发车": f"P{int(r['grid'])}" if r["grid"] else "维修区"})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)  # noqa: F405
        st.caption("注意：**排位名次 ≠ 发车位置**。排位成绩取自 `results` 表"
                   "（`quali_pos` + q1/q2/q3），覆盖率 100%；`sessions` 表只存练习赛。")

    # 排位 → 发车 位次变化
    moved = q[(q["grid"] > 0) & (q["grid"] != q["quali_pos"])].copy()
    if not moved.empty:
        fig = go.Figure()
        for _, r in moved.iterrows():
            back = r["grid"] > r["quali_pos"]
            c = "#C62828" if back else "#2E7D32"
            fig.add_trace(go.Scatter(
                x=[0, 1], y=[r["quali_pos"], r["grid"]], mode="lines+markers",
                line=dict(color=c, width=1.6), marker=dict(size=5),
                name=_dname(r["driver"]),  # noqa: F405
                hovertemplate=(f"{_dname(r['driver'])}<br>"  # noqa: F405
                               "排位 Q%{y}<extra></extra>"),
                showlegend=False))
            fig.add_annotation(x=1, y=r["grid"], text=_dname(r["driver"]),  # noqa: F405
                               xanchor="left", xshift=6, font=dict(size=10, color=c))
        fig.update_xaxes(tickvals=[0, 1], ticktext=["排位赛", "实际发车"], range=[-0.15, 1.5])
        fig.update_yaxes(autorange="reversed", title="位次")
        fig = _chart_style(fig, height=max(260, len(moved) * 26 + 120))  # noqa: F405
        fig.update_layout(title="排位成绩 → 实际发车格（红=被罚退 绿=因他人受罚受益）")
        st.plotly_chart(fig, use_container_width=True)

    pen = q[(q["grid"] > 0) & (q["grid"] - q["quali_pos"] >= 3)]
    if not pen.empty:
        st.subheader(f"发车罚退（{len(pen)} 台车）")
        rows = [{"车手": _dname(r["driver"]), "排位": f"Q{int(r['quali_pos'])}",  # noqa: F405
                 "发车": f"P{int(r['grid'])}", "退后": f"{int(r['grid'] - r['quali_pos'])} 位"}
                for _, r in pen.sort_values("quali_pos").iterrows()]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)  # noqa: F405
        st.caption("模型不会按发车格估值这些车手 —— 实测被罚退 ≥10 位者，"
                   "完赛名次与**排位**的差仅 2.16 位，与**发车格**的差达 10.42 位。")

    order = _predict(year, rnd, "post_quali")
    order_pre = _predict(year, rnd, "pre_quali")
    if not order:
        return
    st.subheader("模型预测（排位赛后口径）")
    _order_table(order, teams, "冠军热门")

    if order_pre:
        st.subheader("相对赛前口径的调整")
        shift = []
        for d in order[:10]:
            if d in order_pre:
                s = order_pre.index(d) + 1 - (order.index(d) + 1)
                shift.append({"车手": _dname(d),  # noqa: F405
                              "赛前": f"P{order_pre.index(d) + 1}",
                              "现在": f"P{order.index(d) + 1}",
                              "调整": f"{'↑' if s > 0 else '↓' if s < 0 else '—'}"
                                      f"{abs(s) if s else ''}"})
        st.dataframe(pd.DataFrame(shift), use_container_width=True, hide_index=True)  # noqa: F405


# ── ③ 逐圈复盘 ───────────────────────────────────────────────

def _tab_laps(year, rnd, teams):
    tl = _timelines(year).get(rnd)
    if tl is None:
        st.info("该场无逐圈数据")
        return

    cv, cvm = _convergence(year, rnd)
    if cv:
        b = pd.DataFrame(cv)  # noqa: F405
        m = pd.DataFrame(cvm) if cvm else pd.DataFrame()
        b["pct"] = b["progress"] * 100
        if not m.empty:
            m["pct"] = m["progress"] * 100

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=b["pct"], y=b["rho_all"], mode="lines",
            name="基线（当前名次 = 最终名次）",
            line=dict(color="#9AA5B1", width=2, dash="dot")))
        if not m.empty:
            fig.add_trace(go.Scatter(
                x=m["pct"], y=m["rho_all"], mode="lines",
                name="模型（节奏外推 gain=0.25）",
                line=dict(color=F1_RED, width=2.8)))  # noqa: F405
            fig.add_trace(go.Scatter(
                x=m["pct"], y=m["rho_fin"], mode="lines",
                name="模型 · 仅完赛者",
                line=dict(color="#1E88E5", width=1.8, dash="dot")))
        sc = b[b["neutralized"]]
        if not sc.empty:
            fig.add_trace(go.Scatter(
                x=sc["pct"], y=sc["rho_all"], mode="markers", name="安全车/VSC 圈",
                marker=dict(color="#FFB300", size=7, symbol="diamond")))
        for y0 in (0.8, 0.9):
            fig.add_hline(y=y0, line=dict(color="#CCCCCC", width=1, dash="dash"))
        fig.update_layout(xaxis_title="比赛进度 %", yaxis_title="排序相关 ρ",
                          yaxis_range=[0, 1.02],
                          title="逐圈收敛曲线 · 比赛跑到第几圈基本定型")
        fig = _chart_style(fig, height=400)  # noqa: F405
        st.plotly_chart(fig, use_container_width=True)

        mid_b = b[(b["pct"] >= 25) & (b["pct"] < 75)]["rho_all"].mean()
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("第 1 圈结束 ρ", f"{b.iloc[0]['rho_all']:.3f}")
        if not m.empty:
            mid_m = m[(m["pct"] >= 25) & (m["pct"] < 75)]["rho_all"].mean()
            r90 = m[m["rho_all"] >= 0.90]
            c2.metric("中段 ρ（模型）", f"{mid_m:.4f}", f"{mid_m - mid_b:+.4f}")
            c3.metric("中段 ρ（基线）", f"{mid_b:.4f}")
            c4.metric("达到 0.90 的进度",
                      f"{r90.iloc[0]['pct']:.0f}%" if not r90.empty else "未达到")
            st.caption(
                "**模型在比赛前段和早中期明显更高** —— 那是唯一还有信息可利用的窗口。"
                "第 1 圈结束两边几乎相同（起步阶段几乎不提供新信息），"
                "最后 25% 也基本相同（剩余距离太短，节奏来不及改变顺序）。")
        st.caption("ρ 达到 0.90 之后剩余的不确定性，就是策略 / 轮胎 / 安全车还能改写结果的空间。")

    # 领先权易手
    lc = tl.lead_changes()
    if lc:
        st.subheader(f"领先权易手（{len(lc)} 次）")
        rows = [{"圈": f"第 {x['lap']} 圈",
                 "从": _dname(x["prev"]), "到": _dname(x["leader"]),  # noqa: F405
                 "状态": "安全车/VSC" if x["neutralized"] else "绿旗"}
                for x in lc]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)  # noqa: F405

    # 最混乱的圈
    sw = tl.swing_laps(5)
    if sw:
        st.subheader("位置变动最剧烈的圈")
        rows = [{"圈": f"第 {x['lap']} 圈", "变动人数": x["moved"],
                 "状态": "安全车/VSC" if x["neutralized"] else "绿旗",
                 "涉及": "、".join(_dname(d) for d in x["drivers"][:6])  # noqa: F405
                        + ("…" if len(x["drivers"]) > 6 else "")}
                for x in sw]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)  # noqa: F405

    # 追赶可行性
    st.subheader("追赶可行性")
    lap = st.slider("查看第几圈", 2, tl.total_laps, max(2, tl.total_laps // 2),
                    key=f"lap_{year}_{rnd}")
    pos, ga, pace = tl.positions(lap), tl.gap_ahead(lap), tl.recent_pace(lap, 6)
    order = sorted(pos, key=lambda d: pos[d])
    remain = tl.total_laps - lap
    rows = []
    for i, d in enumerate(order[:10]):
        if i == 0:
            rows.append({"名次": "P1", "车手": _dname(d),  # noqa: F405
                         "与前车": "—", "速度差": "—", "需圈数": "—", "判定": "领跑"})
            continue
        ahead = order[i - 1]
        if d not in ga or d not in pace or ahead not in pace:
            continue
        dp = pace[ahead] - pace[d]
        if dp <= 0.001:
            need, verdict = "—", "追不上"
        else:
            need = f"{ga[d] / dp:.0f}"
            verdict = "能追上" if ga[d] / dp <= remain else "来不及"
        rows.append({"名次": f"P{pos[d]}", "车手": _dname(d),  # noqa: F405
                     "与前车": f"{ga[d]:.1f}s", "速度差": f"{dp:+.3f}s/圈",
                     "需圈数": need, "判定": verdict})
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)  # noqa: F405
    st.caption(f"剩余 {remain} 圈。速度差用干净圈速中位数（已排除安全车 / 进站 / 冷胎 / 交通圈）。"
               + ("　⚠️ 本圈处于安全车下，秒差失去可比性。" if tl.is_neutralized(lap) else ""))


# ── ④ 赛后实测 ───────────────────────────────────────────────

def _order_table(order, teams, tag):
    rows = [{"预测名次": f"P{i}", "车手": _dname(d),  # noqa: F405
             "车队": _tname(teams.get(d, "")),  # noqa: F405
             "": tag if i == 1 else ""}
            for i, d in enumerate(order[:10], 1)]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)  # noqa: F405


def _tab_result(year, rnd, teams):
    races = _races()
    idx = next((i for i, r in enumerate(races)
                if r.year == year and r.round == rnd), None)
    if idx is None:
        st.info("该场不在回测序列中")
        return
    target = races[idx]
    order = _predict(year, rnd, "post_quali")
    if not order:
        st.info("无预测")
        return

    truth = sorted(target.truth.items(), key=lambda x: x[1].position)
    actual = [d for d, _ in truth]
    sc = score_round(order, target)
    grids = {e.driver: e.grid for e in target.entries}

    # 预测 vs 实际
    fig = go.Figure()
    for i, (d, t) in enumerate(truth[:12], 1):
        pr = order.index(d) + 1 if d in order else None
        if pr is None:
            continue
        err = i - pr
        c = "#2E7D32" if abs(err) <= 2 else ("#F9A825" if abs(err) <= 5 else "#C62828")
        fig.add_trace(go.Scatter(
            x=[pr, i], y=[d, d], mode="lines+markers",
            line=dict(color=c, width=2), marker=dict(size=7, color=c),
            name=_dname(d), showlegend=False,  # noqa: F405
            hovertemplate=(f"{_dname(d)}<br>预测 P{pr} → 实际 P{i}"  # noqa: F405
                           "<extra></extra>")))
    names = [_dname(d) for d, _ in truth[:12]]  # noqa: F405
    fig.update_yaxes(tickmode="array", tickvals=names, ticktext=names, autorange="reversed")
    fig.update_xaxes(title="名次", dtick=1)
    fig = _chart_style(fig, height=max(320, len(names) * 26 + 120))  # noqa: F405
    fig.update_layout(title="预测名次 → 实际名次（连线越短越准）")
    st.plotly_chart(fig, use_container_width=True)

    c1, c2, c3, c4 = st.columns(4)
    winner = actual[0]
    c1.metric("猜中冠军", "✅" if order[0] == winner else "❌",
              f"押 {_dname(order[0])}")  # noqa: F405
    c2.metric("冠军入前3", "✅" if winner in order[:3] else "❌")
    c3.metric("整榜 ρ", f"{sc['rho_all']:.4f}")
    c4.metric("ρ（仅完赛者）", f"{sc['rho_fin']:.4f}")
    st.caption(f"实际冠军：{_dname(winner)}（发车 P{grids.get(winner) or '—'}）；"  # noqa: F405
               f"模型把他排在第 {order.index(winner) + 1} 位。"
               f"全榜 20 人平均误差 "
               f"{sum(abs(i - (order.index(d) + 1)) for i, (d, _) in enumerate(truth, 1)) / len(truth):.2f} 位。")

    st.subheader("逐项对照")
    rows = []
    for i, (d, t) in enumerate(truth, 1):
        pr = order.index(d) + 1 if d in order else None
        err = i - pr if pr else None
        rows.append({
            "实际": f"P{i}", "车手": _dname(d),  # noqa: F405
            "车队": _tname(teams.get(d, "")),  # noqa: F405
            "发车": f"P{grids.get(d) or '—'}",
            "预测": f"P{pr}" if pr else "—",
            "误差": f"{err:+d}" if err is not None else "—",
            "状态": STATUS_CN.get(t.status, t.status),  # noqa: F405
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)  # noqa: F405
    st.caption("提示：「误差」为正表示模型高估了（预测名次比实际靠前）；"
               "为负表示低估。系统性偏向某一侧就是可以修的信号。")
