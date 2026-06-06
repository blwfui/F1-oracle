"""Page: 分站详情"""
import streamlit as st
import numpy as np
import plotly.express as px
from common import *


def render(year):
    st.markdown(SCROLL_TOP_JS, unsafe_allow_html=True)
    st.title(f"🔍 {year} 分站详情")

    races = query(f"""
        SELECT round, event_name, country, location FROM events
        WHERE year={year} AND round > 0 ORDER BY round
    """)
    race_label = {r["round"]: f"第{NUM_CN[r['round']]}站  {_ename(r['event_name'])}" for _, r in races.iterrows()}
    selected_round = st.selectbox("选择比赛", list(race_label.keys()),
                                   format_func=lambda x: race_label[x])

    race_info = races[races["round"] == selected_round].iloc[0]
    c1, c2 = st.columns(2)
    c1.metric("赛道", _lname(race_info["location"]))
    c2.metric("国家", _cname(race_info["country"]))

    # ── AI 分析 ──────────────────────────────────────────────
    st.subheader("📝 AI 赛事战报")
    if st.button("🤖 生成 AI 战报", key=f"report_{selected_round}", use_container_width=True):
        from ai_chat import generate_race_report

        with st.spinner("AI 正在分析比赛数据…"):
            report_results = query(f"""
                SELECT position, driver, full_name, team, grid, points, status
                FROM results WHERE year={year} AND round={selected_round}
                ORDER BY position
            """)
            report_weather = query(f"SELECT * FROM weather WHERE year={year} AND round={selected_round}")
            report_laps = query(f"""
                SELECT driver, MIN(lap_time) as best_lap
                FROM laps WHERE year={year} AND round={selected_round} AND lap_time > 0
                GROUP BY driver ORDER BY best_lap
            """)
            report_sprint = query(f"""
                SELECT sp.driver, sp.position, sp.points, r.full_name, r.team
                FROM sprint_points sp JOIN results r ON sp.year=r.year AND sp.round=r.round
                    AND sp.driver COLLATE NOCASE = r.driver COLLATE NOCASE
                WHERE sp.year={year} AND sp.round={selected_round}
                ORDER BY sp.position
            """)
            report_data = {
                "results": report_results,
                "weather": report_weather,
                "laps_summary": report_laps,
                "sprint": report_sprint if not report_sprint.empty else None,
            }
            report = generate_race_report(year, selected_round, race_info["event_name"], report_data)

        st.markdown(report)

    st.subheader("🔧 AI 策略分析")
    if st.button("🤖 生成策略分析", key=f"strategy_{selected_round}", use_container_width=True):
        from ai_chat import generate_strategy_analysis

        with st.spinner("AI 正在分析进站策略…"):
            strat_pitstops = query(f"""
                SELECT l.driver, l.lap_number, l.compound, l.stint
                FROM laps l
                WHERE l.year={year} AND l.round={selected_round} AND l.is_pit=1
                ORDER BY l.driver, l.lap_number
            """)
            strat_stints = query(f"""
                SELECT driver, stint, compound, COUNT(*) as stint_laps
                FROM laps
                WHERE year={year} AND round={selected_round} AND lap_time > 0
                GROUP BY driver, stint, compound
                ORDER BY driver, stint
            """)
            strat_results = query(f"""
                SELECT position, driver, full_name, team, grid, points, status
                FROM results WHERE year={year} AND round={selected_round}
                ORDER BY position
            """)
            strat_weather = query(f"SELECT * FROM weather WHERE year={year} AND round={selected_round}")
            strat_data = {
                "pitstops": strat_pitstops,
                "stint_summary": strat_stints,
                "results": strat_results,
                "weather": strat_weather,
            }
            analysis = generate_strategy_analysis(year, selected_round, race_info["event_name"], strat_data)

        st.markdown(analysis)

    st.divider()
    w = query(f"SELECT * FROM weather WHERE year={year} AND round={selected_round}")
    if not w.empty:
        air = w["air_temp_avg"].iloc[0]
        trk = w["track_temp_avg"].iloc[0]
        hum = w["humidity_avg"].iloc[0]
        rain = w["had_rain"].iloc[0]
        w1, w2, w3, w4 = st.columns(4)
        with w1:
            st.markdown(f"""<div style="background:#fff;border-radius:10px;padding:14px;border-top:3px solid #E10600;border:1px solid #E8E8E8;">
            <div style="color:#888;font-size:0.75rem;">🌡️ 气温</div>
            <div style="font-size:1.4rem;font-weight:700;">{air:.1f}°C</div>
            <div style="background:#eee;height:4px;border-radius:2px;margin-top:8px;">
            <div style="background:#E10600;height:4px;border-radius:2px;width:{min(air/50*100,100)}%"></div></div></div>""", unsafe_allow_html=True)
        with w2:
            st.markdown(f"""<div style="background:#fff;border-radius:10px;padding:14px;border-top:3px solid #FF8C00;border:1px solid #E8E8E8;">
            <div style="color:#888;font-size:0.75rem;">🏁 赛道温度</div>
            <div style="font-size:1.4rem;font-weight:700;">{trk:.1f}°C</div>
            <div style="background:#eee;height:4px;border-radius:2px;margin-top:8px;">
            <div style="background:#FF8C00;height:4px;border-radius:2px;width:{min(trk/60*100,100)}%"></div></div></div>""", unsafe_allow_html=True)
        with w3:
            st.markdown(f"""<div style="background:#fff;border-radius:10px;padding:14px;border-top:3px solid #1E90FF;border:1px solid #E8E8E8;">
            <div style="color:#888;font-size:0.75rem;">💧 湿度</div>
            <div style="font-size:1.4rem;font-weight:700;">{hum:.0f}%</div>
            <div style="background:#eee;height:4px;border-radius:2px;margin-top:8px;">
            <div style="background:#1E90FF;height:4px;border-radius:2px;width:{min(hum,100)}%"></div></div></div>""", unsafe_allow_html=True)
        with w4:
            rain_icon = "🌧️" if rain else "☀️"
            rain_label = "有雨" if rain else "无雨"
            rain_color = "#1E90FF" if rain else "#FFB800"
            st.markdown(f"""<div style="background:#fff;border-radius:10px;padding:14px;border-top:3px solid {rain_color};border:1px solid #E8E8E8;">
            <div style="color:#888;font-size:0.75rem;">{rain_icon} 天气</div>
            <div style="font-size:1.4rem;font-weight:700;">{rain_label}</div>
            <div style="height:4px;margin-top:8px;"></div></div>""", unsafe_allow_html=True)

    fp_data = query(f"""
        SELECT s.driver, s.session_type, s.best_lap_sec, s.laps_count, s.position, r.team
        FROM sessions s LEFT JOIN results r ON s.year=r.year AND s.round=r.round
            AND s.driver COLLATE NOCASE = r.driver COLLATE NOCASE
        WHERE s.year={year} AND s.round={selected_round}
        ORDER BY s.session_type,
            CASE WHEN s.position IS NULL THEN 1 ELSE 0 END,
            s.position
    """)
    if not fp_data.empty:
        st.subheader("练习赛成绩")
        available_types = set(fp_data["session_type"].unique())
        available = [ps for ps in PRACTICE_SESSIONS if ps["type"] in available_types]
        if not available:
            available = [ps for ps in PRACTICE_SESSIONS if ps["type"] == "FP1"]
        cols = st.columns(len(available))
        for ci, ps in enumerate(available):
            subset = fp_data[fp_data["session_type"] == ps["type"]]
            with cols[ci]:
                if subset.empty:
                    st.caption(f"{ps['label']}: 暂无数据")
                    continue
                rows = ""
                for _, r in subset.iterrows():
                    t = r["best_lap_sec"]
                    if t and t > 0:
                        ft = _fmt_lap_time(t)
                        p_str = str(int(r["position"]))
                    else:
                        laps = int(r["laps_count"]) if r["laps_count"] else 0
                        ft = "无数据" if laps > 0 else "未出场"
                        p_str = "—"
                    rows += f"""<tr style="background:#fff;">
                        <td style="text-align:center;padding:4px 6px;">{p_str}</td>
                        <td style="padding:4px 6px;">
                            <span style="color:{TEAM_COLORS.get(r['team'],'#333')};font-size:0.8rem;">{_dname(r['driver'])}</span></td>
                        <td style="text-align:center;padding:4px 6px;">{ft}</td>
                        <td style="text-align:center;padding:4px 6px;">{int(r['laps_count'])}</td></tr>"""
                st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">
                <thead><tr style="background:{ps['color']};color:#fff;font-weight:600;">
                <th style="padding:5px 6px;">#</th><th style="padding:5px 6px;">{ps['label']}</th>
                <th style="padding:5px 6px;">圈速</th><th style="padding:5px 6px;">圈</th></tr></thead>
                <tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    is_2122_sprint = False
    if year in (2021, 2022):
        is_2122_sprint = not query(f"SELECT 1 FROM sprint_points WHERE year={year} AND round={selected_round} LIMIT 1").empty

    quali = query(f"""
        SELECT r.driver, r.q1_sec, r.q2_sec, r.q3_sec, r.quali_pos, r.team
        FROM results r WHERE r.year={year} AND r.round={selected_round}
    """)
    has_quali = not quali.empty and quali["q1_sec"].notna().any()
    if has_quali:
        st.subheader("排位赛成绩")
        if is_2122_sprint:
            st.caption("※ 本场排位赛决定冲刺赛发车顺序")
        for ph in QUALI_PHASES:
            quali[ph["key"] + "s"] = quali[ph["col"]].apply(_fmt_lap_time)

        q_order_maps = {}
        for ph in QUALI_PHASES:
            if ph["key"] == "Q1":
                q_order_maps[ph["key"]] = quali.sort_values(ph["col"], na_position="last")
            else:
                q_order_maps[ph["key"]] = quali[quali[ph["col"]].notna()].sort_values(ph["col"])

        cols = st.columns(len(QUALI_PHASES))
        for ci, ph in enumerate(QUALI_PHASES):
            subset = q_order_maps[ph["key"]]
            with cols[ci]:
                if subset.empty:
                    st.caption(f"{ph['label']}: 暂无数据")
                    continue
                rows = ""
                for seq, (_, r) in enumerate(subset.iterrows(), 1):
                    t = r[ph["key"] + "s"]
                    if t:
                        p_str = str(seq)
                    else:
                        p_str = "—"
                        t = "—"
                    rows += f"""<tr style="background:#fff;">
                        <td style="text-align:center;padding:4px 6px;">{p_str}</td>
                        <td style="padding:4px 6px;">
                            <span style="color:{TEAM_COLORS.get(r['team'],'#333')};font-size:0.8rem;">{_dname(r['driver'])}</span></td>
                        <td style="text-align:center;padding:4px 6px;">{t}</td></tr>"""
                st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.78rem;">
                <thead><tr style="background:{ph['color']};color:#fff;font-weight:600;">
                <th style="padding:5px 6px;">#</th><th style="padding:5px 6px;">{ph['label']}</th>
                <th style="padding:5px 6px;">圈速</th></tr></thead>
                <tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    sprint_data = query(f"""
        SELECT sp.driver, sp.position, sp.points, sp.sq_pos, r.team
        FROM sprint_points sp JOIN results r ON sp.year=r.year AND sp.round=r.round
            AND sp.driver COLLATE NOCASE = r.driver COLLATE NOCASE
        WHERE sp.year={year} AND sp.round={selected_round}
        ORDER BY sp.position
    """)
    if not sprint_data.empty:
        st.subheader("冲刺赛")
        if is_2122_sprint:
            st.caption("※ 冲刺赛名次决定正赛发车顺序")
        sp_rows = ""
        for _, r in sprint_data.iterrows():
            pos = r["position"]
            pdm = int(pos) if pd.notna(pos) else 99
            if pdm == 1:
                bd = "#FFD700"
            elif pdm == 2:
                bd = "#C0C0C0"
            elif pdm == 3:
                bd = "#CD7F32"
            else:
                bd = "transparent"
            sq = int(r["sq_pos"]) if pd.notna(r["sq_pos"]) else "—"
            pts = int(r["points"]) if pd.notna(r["points"]) else 0
            sp_rows += f"""<tr style="background:#fff;border-left:3px solid {bd};">
                <td style="text-align:center;padding:6px 8px;">{pos}</td>
                <td style="padding:6px 8px;">{_dfull(r['driver'])}</td>
                <td style="padding:6px 8px;">{_tfull(r['team'])}</td>
                <td style="text-align:center;padding:6px 8px;">{sq}</td>
                <td style="text-align:center;padding:6px 8px;">{pts}</td></tr>"""
        st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
        <thead><tr style="background:#E10600;color:#fff;font-weight:600;">
        <th style="padding:8px;">名次</th><th style="padding:8px;">车手</th>
        <th style="padding:8px;">车队</th><th style="padding:8px;">发车</th>
        <th style="padding:8px;">积分</th>
        </tr></thead><tbody>{sp_rows}</tbody></table>""", unsafe_allow_html=True)

    st.subheader("正赛")
    res = query(f"""
        SELECT position, driver, team, grid, points, status
        FROM results WHERE year={year} AND round={selected_round}
        ORDER BY position
    """)
    res["车手"] = res["driver"].apply(_dfull)
    res["车队"] = res["team"].apply(_tfull)
    res["状态"] = res["status"].apply(lambda s: STATUS_CN.get(str(s), str(s)))
    rows = ""
    for _, r in res.iterrows():
        pos = r["position"]
        finished = str(r["status"]) == "Finished"
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
            <td style="text-align:center;padding:6px 8px;">{r['grid']}</td>
            <td style="text-align:center;padding:6px 8px;">{r['points']}</td>
            <td style="text-align:center;padding:6px 8px;">{r['状态']}</td></tr>"""
    st.markdown(f"""<table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
    <thead><tr style="background:#E10600;color:#fff;font-weight:600;">
    <th style="padding:8px;">名次</th><th style="padding:8px;">车手</th>
    <th style="padding:8px;">车队</th><th style="padding:8px;">发车</th>
    <th style="padding:8px;">积分</th><th style="padding:8px;">状态</th>
    </tr></thead><tbody>{rows}</tbody></table>""", unsafe_allow_html=True)

    st.subheader("圈速对比")
    all_laps = query(f"""
        SELECT l.driver, l.lap_number, l.lap_time, r.team
        FROM laps l JOIN results r ON l.year=r.year AND l.round=r.round
          AND l.driver COLLATE NOCASE = r.driver COLLATE NOCASE
        WHERE l.year={year} AND l.round={selected_round} AND l.lap_time>0
          AND l.lap_number>0
        ORDER BY l.lap_number
    """)
    if not all_laps.empty:
        all_drivers = all_laps[["driver", "team"]].drop_duplicates()
        all_drivers["label"] = all_drivers["driver"].apply(_dfull)
        all_drivers = all_drivers.sort_values("driver")

        @st.fragment
        def _lap_chart_fragment():
            st.caption("勾选车手对比圈速（最多 5 人）")
            checked = []
            cols = st.columns(4)
            for i, (_, dr) in enumerate(all_drivers.iterrows()):
                with cols[i % 4]:
                    if st.checkbox(dr["label"], key=f"cb_{selected_round}_{dr['driver']}"):
                        checked.append((dr["driver"], dr["label"], dr["team"]))

            if len(checked) > 5:
                st.warning(f"最多选 5 人，当前已选 {len(checked)} 人")
            elif checked:
                df = all_laps[all_laps["driver"].isin([c[0] for c in checked])].copy()
                df["车手"] = df["driver"].apply(_dfull)
                df["圈速文本"] = df["lap_time"].apply(
                    lambda s: f"{int(s//60)}分{s%60:06.3f}秒"
                )
                color_map = {c[1]: TEAM_COLORS.get(c[2], "#888888") for c in checked}

                fig = px.line(df, x="lap_number", y="lap_time", color="车手",
                              title=f"圈速对比 — {_ename(race_info['event_name'])}",
                              color_discrete_map=color_map,
                              labels={"lap_number": "圈数", "lap_time": "圈速"},
                              custom_data=["圈速文本"])
                fig.update_traces(
                    hovertemplate="车手：%{fullData.name}<br>第%{x}圈<br>圈速：%{customdata[0]}<extra></extra>"
                )
                y_max = df["lap_time"].max() * 1.05
                tick_count = 8
                tick_step = max(0.5, np.ceil(y_max / tick_count))
                ticks = np.arange(0, y_max + tick_step, tick_step)
                tick_labels = []
                for v in ticks:
                    mins = int(v // 60)
                    secs = v % 60
                    tick_labels.append(f"{mins}:{secs:04.1f}")
                fig = _chart_style(fig, height=480)
                fig.update_layout(
                    yaxis=dict(tickmode="array", tickvals=ticks.tolist(),
                               ticktext=tick_labels, title="圈速"),
                    xaxis=dict(title="圈数", dtick=5),
                    hovermode="x unified")
                fig.update_xaxes(showspikes=True, spikemode="across",
                                 spikesnap="cursor", spikethickness=1,
                                 spikecolor="rgba(128,128,128,0.4)")
                st.plotly_chart(fig, use_container_width=True)

        _lap_chart_fragment()

    st.subheader("各车手轮胎使用量与类型")
    compounds = query(f"""
        SELECT driver, compound, COUNT(*) as laps
        FROM laps WHERE year={year} AND round={selected_round}
        GROUP BY driver, compound ORDER BY driver, compound
    """)
    if not compounds.empty:
        compounds["车手"] = compounds["driver"].apply(_dfull)
        compounds["配方"] = compounds["compound"].apply(_comp)
        fig = px.bar(compounds, x="车手", y="laps", color="配方",
                     title="各车手轮胎使用量与类型", barmode="stack",
                     color_discrete_map=COMPOUND_COLORS,
                     labels={"laps": "圈数"})
        fig = _chart_style(fig, height=350)
        fig.update_layout(xaxis_title="", yaxis_title="圈数")
        fig.update_traces(marker_line_color="rgba(0,0,0,0.25)", marker_line_width=1)
        st.plotly_chart(fig, use_container_width=True)
