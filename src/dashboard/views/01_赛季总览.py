"""Page: 赛季总览"""
import streamlit as st
import numpy as np
import plotly.express as px
from common import *


def render(year):
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

    # ── AI 赛季回顾 ──────────────────────────────────────────
    st.subheader("📝 AI 赛季回顾")
    if st.button("🤖 生成赛季回顾", key=f"season_review_{year}", use_container_width=True):
        from ai_chat import generate_season_review

        with st.spinner("AI 正在回顾整个赛季…"):
            review_standings = raw_drv[["driver", "team", "pts", "wins", "podiums"]].copy()
            review_teams = raw_team[["team", "pts", "wins"]].copy()
            review_winners = query(f"""
                SELECT r.round, e.event_name, r.driver, r.team
                FROM results r JOIN events e USING(year, round)
                WHERE r.year={year} AND r.position=1 AND e.round>0
                ORDER BY r.round
            """)
            review_stats = query(f"""
                SELECT r.driver, r.team,
                       SUM(CASE WHEN r.status != 'Finished' THEN 1 ELSE 0 END) as dnf_count,
                       ROUND(AVG(r.grid), 1) as avg_grid,
                       ROUND(AVG(r.position), 1) as avg_fin
                FROM results r WHERE r.year={year}
                GROUP BY r.driver
            """)
            review_data = {
                "standings": review_standings,
                "team_standings": review_teams,
                "winners": review_winners,
                "stats": review_stats,
            }
            report = generate_season_review(year, review_data)

        st.markdown(report)

    st.divider()
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
