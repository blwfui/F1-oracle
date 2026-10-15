"""Page: 赛道分析"""
import streamlit as st
import numpy as np
import plotly.express as px
from common import *


def render(year):
    st.markdown(SCROLL_TOP_JS, unsafe_allow_html=True)
    st.title("🏁 赛道分析")

    @st.fragment
    def _track_fragment():
        tracks = query("""
            SELECT DISTINCT location, country FROM events
            WHERE year = ? ORDER BY country
        """, (year,))
        track_names = tracks["location"].tolist()
        selected_track = st.selectbox("选择赛道", track_names, format_func=_lname)

        # ── AI 赛道攻略 ────────────────────────────────────────
        st.subheader("📖 AI 赛道攻略")
        if st.button("🤖 生成赛道攻略", key=f"guide_{selected_track}", width="stretch"):
            from ai_chat import generate_track_guide

            with st.spinner("AI 正在分析历史数据…"):
                # 只取完赛者：退赛者的 position 是按行驶距离分配的分类名次，
                # 拿它算「位置变化」会得出「退赛=掉 6.8 位」的假信号。
                # 注意不能用 `position IS NOT NULL` —— position 永不为 NULL，那样等于没过滤。
                # 带值的查询一律走 params（审查报告 E2）。
                # 唯一还能 f-string 插进 SQL 的是 `{FINISHED_SQL}` / `{DNF_SQL}` ——
                # 那是 `common.py` 里的**代码常量 SQL 片段**，不是值，本来就无法参数化。
                guide_overtaking = query(f"""
                    SELECT r.year, r.round, r.driver, r.full_name, r.team, r.grid, r.position
                    FROM results r JOIN events e USING(year, round)
                    WHERE e.location = ? AND {FINISHED_SQL}
                        AND r.grid > 0 AND e.round > 0
                    ORDER BY r.year, r.round
                """, (selected_track,))
                guide_tires = query(f"""
                    SELECT l.year, l.compound,
                           COUNT(*) as laps,
                           COUNT(DISTINCT l.driver) as driver_count
                    FROM laps l JOIN events e USING(year, round)
                    WHERE e.location = ? AND l.compound IS NOT NULL
                        AND l.compound != '' AND l.lap_time > 0 AND e.round > 0
                    GROUP BY l.year, l.compound
                    ORDER BY l.year, l.compound
                """, (selected_track,))
                guide_weather = query("""
                    SELECT w.year, w.round, w.air_temp_avg, w.track_temp_avg,
                           w.humidity_avg, w.had_rain
                    FROM weather w JOIN events e USING(year, round)
                    WHERE e.location = ? AND e.round > 0
                    ORDER BY w.year
                """, (selected_track,))
                guide_fastest = query("""
                    SELECT l.year, l.driver, MIN(l.lap_time) as fastest, r.team
                    FROM laps l JOIN events e USING(year, round)
                    JOIN results r ON l.year=r.year AND l.round=r.round
                        AND l.driver COLLATE NOCASE = r.driver COLLATE NOCASE
                    WHERE e.location = ? AND l.lap_time > 0 AND e.round > 0
                    GROUP BY l.year, l.driver
                    ORDER BY fastest
                """, (selected_track,))
                guide_dnf = query(f"""
                    SELECT r.year, r.status, COUNT(*) as count
                    FROM results r JOIN events e USING(year, round)
                    WHERE e.location = ? AND {DNF_SQL}
                        AND e.round > 0
                    GROUP BY r.year, r.status
                    ORDER BY count DESC
                """, (selected_track,))
                guide_data = {
                    "overtaking": guide_overtaking,
                    "tire_usage": guide_tires,
                    "weather": guide_weather,
                    "fastest": guide_fastest,
                    "dnf_stats": guide_dnf,
                }
                guide = generate_track_guide(selected_track, _lname(selected_track), guide_data)

            st.markdown(guide)

        st.divider()
        st.subheader(f"{_lname(selected_track)} 比赛结果")
        track_res = query(f"""
            SELECT r.position, r.driver, r.team, r.points, r.status
            FROM results r JOIN events e USING(year, round)
            WHERE r.year = ? AND e.location = ?
            ORDER BY r.position
        """, (year, selected_track))
        if not track_res.empty:
            track_res["车手"] = track_res["driver"].apply(_dname)
            track_res["车队"] = track_res["team"].apply(_tname)
            track_res["状态"] = track_res["status"].apply(lambda s: STATUS_CN.get(str(s), str(s)))
            rows = ""
            for _, r in track_res.iterrows():
                pos = r["position"]
                # 被套圈完赛（Lapped / +n Laps）同样算完赛
                finished = is_finished(r["status"])
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
            WHERE l.year = ? AND e.location = ? AND l.lap_time > 0
            GROUP BY l.driver ORDER BY fastest
        """, (year, selected_track))
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
            st.plotly_chart(fig, width="stretch")

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

    _track_fragment()
