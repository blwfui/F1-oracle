"""Page: AI 问答"""
import re

import plotly.express as px
import streamlit as st
from common import SCROLL_TOP_JS, F1_RED, _chart_style, query  # noqa: F401

PRESETS = [
    ("🏆", "2024 年维斯塔潘赢了几场比赛？"),
    ("🥇", "2023 年谁上了最多次领奖台？"),
    ("👑", "汉密尔顿在哪条赛道夺冠次数最多？"),
    ("🌧️", "2024 年哪场比赛下雨了？"),
    ("⚔️", "勒克莱尔和赛恩斯在 2024 年谁积分更高？"),
    ("🇨🇳", "周冠宇生涯最佳完赛名次是多少？"),
    ("🛑", "2023 年退赛次数最多的车手是谁？"),
    ("⏱️", "2024 年摩纳哥站最快圈速是谁跑的？"),
]

CHART_PRESETS = [
    ("📊", "画一个 2024 车手积分柱状图"),
    ("📈", "画一个维斯塔潘 2024 每站积分走势"),
    ("🏁", "画一个 2024 各车队总积分对比图"),
    ("⏱️", "画一个 2024 中国站各车手最快圈速对比"),
]

CHART_KEYWORDS = re.compile(
    r"(画|图表|柱状图|折线图|散点图|走势图|对比图|可视化|plot|chart|graph)",
    re.IGNORECASE,
)


def _is_chart_request(text: str) -> bool:
    return bool(CHART_KEYWORDS.search(text))


# ── Chart color palette ─────────────────────────────────────
CHART_PALETTE = [
    "#E10600",  # F1 red
    "#1E3A5F",  # dark blue
    "#FF8C00",  # orange
    "#2E8B57",  # sea green
    "#8B5CF6",  # purple
    "#DC143C",  # crimson
    "#008B8B",  # teal
    "#DAA520",  # goldenrod
]


def _render_chart(spec: dict):
    """Execute SQL and render a Plotly chart styled like 车手档案 ranking trend."""
    sql = spec["sql"]
    try:
        df = query(sql)
    except Exception as e:
        st.error(f"SQL 执行错误：{e}")
        st.code(sql, language="sql")
        return

    if df.empty:
        st.info("查询结果为空")
        st.code(sql, language="sql")
        return

    chart_type = spec.get("chart_type", "bar")
    x = spec.get("x") or df.columns[0]
    y = spec.get("y")
    if not y or y not in df.columns:
        y = df.columns[1] if len(df.columns) > 1 else df.columns[0]
    color = spec.get("color")
    title = spec.get("title", "")
    x_label = spec.get("x_label", x)
    y_label = spec.get("y_label", y)
    sort = spec.get("sort")

    if sort == "desc":
        df = df.sort_values(y, ascending=False)
    elif sort == "asc":
        df = df.sort_values(y, ascending=True)

    has_color = color and color != "null" and color in df.columns
    custom_cols = [c for c in df.columns if c not in (x, y, color)]

    # ── Build figure with px (same pattern as 车手档案) ──
    if chart_type == "line":
        if has_color:
            fig = px.line(df, x=x, y=y, color=color, title=title,
                          markers=True, color_discrete_sequence=CHART_PALETTE,
                          custom_data=custom_cols)
        else:
            fig = px.line(df, x=x, y=y, title=title, markers=True,
                          color_discrete_sequence=[F1_RED], custom_data=custom_cols)
        fig.update_traces(
            line_width=2.5, marker_size=7,
            hovertemplate=f"{x_label}: %{{x}}<br>{y_label}: %{{y:.1f}}<extra></extra>"
        )

    elif chart_type == "scatter":
        if has_color:
            fig = px.scatter(df, x=x, y=y, color=color, title=title,
                             color_discrete_sequence=CHART_PALETTE,
                             custom_data=custom_cols)
        else:
            fig = px.scatter(df, x=x, y=y, title=title,
                             color_discrete_sequence=[F1_RED],
                             custom_data=custom_cols)
        fig.update_traces(
            marker_size=10,
            hovertemplate=f"{x_label}: %{{x}}<br>{y_label}: %{{y:.1f}}<extra></extra>"
        )

    else:  # bar
        if has_color:
            fig = px.bar(df, x=x, y=y, color=color, title=title,
                         color_discrete_sequence=CHART_PALETTE,
                         text=y, custom_data=custom_cols)
        else:
            fig = px.bar(df, x=x, y=y, title=title,
                         color_discrete_sequence=[F1_RED],
                         text=y, custom_data=custom_cols)
        fig.update_traces(
            textposition="outside", textfont_size=11,
            marker_line_width=0.5, marker_line_color="rgba(255,255,255,0.6)",
            hovertemplate=f"{x_label}: %{{x}}<br>{y_label}: %{{y:.1f}}<extra></extra>"
        )

    # ── Layout: match 车手档案 ranking chart style ──
    fig = _chart_style(fig, height=400)
    fig.update_layout(
        title=title,
        xaxis_title=x_label,
        yaxis_title=y_label,
        hovermode="x unified",
    )
    # Spike crosshair on hover
    fig.update_xaxes(
        showspikes=True, spikemode="across", spikesnap="cursor",
        spikethickness=1, spikecolor="rgba(128,128,128,0.4)",
    )
    fig.update_yaxes(showspikes=True, spikemode="across", spikesnap="cursor",
                     spikethickness=1, spikecolor="rgba(128,128,128,0.4)")

    st.plotly_chart(fig, use_container_width=True)


def _process(prompt: str):
    """Run a question through the AI and append to history."""
    from ai_chat import ask as ai_ask, ask_chart, suggest_followups

    st.session_state.chat_history_ai.append({"role": "user", "content": prompt})

    is_chart = _is_chart_request(prompt)
    chart_spec = None

    if is_chart:
        with st.spinner("生成图表…"):
            chart_spec = ask_chart(prompt)
        if chart_spec:
            answer = f"已生成图表：{chart_spec.get('title', '')}"
        else:
            answer = "抱歉，无法生成该图表。请尝试更具体的描述，例如'画一个 2024 车手积分柱状图'。"
    else:
        with st.spinner("思考中…"):
            prev = st.session_state.chat_history_ai[:-1]
            answer = ai_ask(prompt, history=prev)

    # Store answer + optional chart spec
    entry = {"role": "assistant", "content": answer}
    if chart_spec:
        entry["chart_spec"] = chart_spec
    st.session_state.chat_history_ai.append(entry)

    # Generate follow-up suggestions (skip for chart requests)
    if not is_chart:
        with st.spinner(""):
            prev = st.session_state.chat_history_ai[:-1]
            followups = suggest_followups(prompt, answer, history=prev)
        st.session_state.followups = followups
    else:
        st.session_state.followups = []


def _render_followups():
    """Render follow-up question buttons if available."""
    followups = st.session_state.get("followups", [])
    if not followups:
        return
    st.markdown("**💡 你可以继续问：**")
    cols = st.columns(3)
    for i, q in enumerate(followups):
        with cols[i]:
            if st.button(q, key=f"followup_{i}", use_container_width=True):
                st.session_state.followups = []
                _process(q)
                st.rerun()


def render(year):
    st.markdown(SCROLL_TOP_JS, unsafe_allow_html=True)
    st.title("💬 AI 问答")
    st.caption(f"用中文提问 F1 数据问题，AI 自动查库回答。也可以说'画一个…'生成图表。当前数据：{year} 赛季")

    st.session_state.setdefault("chat_history_ai", [])
    st.session_state.setdefault("followups", [])

    # Clear chat button
    if st.session_state.chat_history_ai:
        if st.button("🗑️ 清空对话", key="clear_chat"):
            st.session_state.chat_history_ai = []
            st.session_state.followups = []
            st.rerun()

    # Preset questions — only show before first conversation
    if not st.session_state.chat_history_ai:
        st.subheader("💡 试试点击以下问题：")
        cols = st.columns(2)
        for i, (icon, q) in enumerate(PRESETS):
            with cols[i % 2]:
                if st.button(f"{icon}  {q}", key=f"preset_{i}", use_container_width=True):
                    _process(q)
                    st.rerun()

        st.subheader("📊 或者试试生成图表：")
        cols = st.columns(2)
        for i, (icon, q) in enumerate(CHART_PRESETS):
            with cols[i % 2]:
                if st.button(f"{icon}  {q}", key=f"chart_preset_{i}", use_container_width=True):
                    _process(q)
                    st.rerun()

    # Display chat history
    for msg in st.session_state.chat_history_ai:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            # Re-render chart from stored spec
            if "chart_spec" in msg:
                _render_chart(msg["chart_spec"])
                with st.expander("查看 SQL"):
                    st.code(msg["chart_spec"]["sql"], language="sql")

    # Show follow-up suggestions after the last answer
    if st.session_state.chat_history_ai and st.session_state.followups:
        _render_followups()

    # Chat input
    if prompt := st.chat_input("输入你的 F1 问题，或说'画一个…'生成图表…"):
        st.session_state.followups = []
        _process(prompt)
        st.rerun()

    st.divider()
    st.caption("⚠️ AI 生成内容仅供参考，可能存在错误。数据来源于 FastF1，以 F1 官方发布为准。")
