"""Page: 车手档案"""
import streamlit as st
import numpy as np
import plotly.express as px
from common import *


def render(year):
    st.markdown(SCROLL_TOP_JS, unsafe_allow_html=True)
    st.title("👤 车手档案")

    @st.fragment
    def _driver_fragment():
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

    _driver_fragment()
