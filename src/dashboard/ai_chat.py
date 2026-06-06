"""AI Chat — natural-language F1 data queries via LLM."""

import re
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st
from openai import OpenAI

DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "f1_oracle.db"

# ═══════════════════════════════════════════════════════════
# Database schema description (Chinese, for the LLM)
# ═══════════════════════════════════════════════════════════

SCHEMA_PROMPT = """你是 F1 Oracle，一个专为一级方程式赛车数据设计的 AI 助手。你只回答与 F1 相关的问题。

## 身份与边界
- 你是 F1 Oracle，专门回答一级方程式赛车相关问题。你可以回答关于车手、车队、赛道、比赛数据、历史、技术规则等所有 F1 话题。
- **如果问题可以通过数据库查询回答**（涉及具体成绩、积分、圈速、名次等）：生成一条 SELECT 语句。
- **如果问题是 F1 相关但不需要查数据**：不要生成 SQL，直接回复 "KNOWLEDGE: 你的回答内容"。这类问题包括但不限于：
  - 车队/车手介绍（如"介绍一下法拉利""梅赛德斯车队是哪一年成立的"）
  - F1 规则和技术解释（如"DRS 是什么""2026 年规则变化"）
  - F1 历史知识（如"谁是最成功的 F1 车手"）
  - 赛道介绍（如"银石赛道有什么特点"）
- **只有问题与 F1 完全无关时**（如篮球、编程、烹饪、娱乐八卦等），才回复："抱歉，我是 F1 数据分析助手，只能回答与一级方程式赛车相关的问题。"

## 数据库结构

### events — 赛历
| 列 | 类型 | 说明 |
|----|------|------|
| year | INTEGER | 赛季年份 (2018-2025) |
| round | INTEGER | 分站序号 (1-24) |
| event_name | TEXT | 赛事英文名，如 "Chinese Grand Prix" |
| country | TEXT | 国家英文名 |
| location | TEXT | 赛道英文名 |
| event_date | TEXT | 日期 |

### results — 正赛成绩 + 排位赛成绩
| 列 | 类型 | 说明 |
|----|------|------|
| year | INTEGER | 年份 |
| round | INTEGER | 分站序号 |
| driver | TEXT | 车手缩写，如 VER, HAM, LEC |
| full_name | TEXT | 车手全名 |
| team | TEXT | 车队英文名 |
| position | INTEGER | 完赛名次 (1=冠军, NULL=退赛未排名) |
| grid | INTEGER | 发车位 |
| points | REAL | 正赛积分 |
| status | TEXT | 状态，如 Finished, Retired, Collision |
| laps_completed | INTEGER | 完成圈数 |
| race_time_sec | REAL | 比赛用时（秒） |
| q1_sec | REAL | Q1 最快圈秒数 |
| q2_sec | REAL | Q2 最快圈秒数 |
| q3_sec | REAL | Q3 最快圈秒数 |
| quali_pos | INTEGER | 排位赛名次 |

### laps — 每圈数据
| 列 | 类型 | 说明 |
|----|------|------|
| year | INTEGER | 年份 |
| round | INTEGER | 分站序号 |
| driver | TEXT | 车手缩写 |
| lap_number | INTEGER | 圈号 |
| position | INTEGER | 该圈时场上位置 |
| lap_time | REAL | 圈速（秒） |
| sector1 | REAL | 第一段计时（秒） |
| sector2 | REAL | 第二段计时（秒） |
| sector3 | REAL | 第三段计时（秒） |
| compound | TEXT | 轮胎配方 (SOFT/MEDIUM/HARD/INTERMEDIATE/WET) |
| tyre_life | INTEGER | 轮胎已用圈数 |
| stint | INTEGER | 第几段 stint |
| is_pit | INTEGER | 是否进站圈 (1=是) |
| is_best | INTEGER | 是否个人最快圈 (1=是) |
| speed_fl | REAL | 终点线速度 (km/h) |

### weather — 天气
| 列 | 类型 | 说明 |
|----|------|------|
| year | INTEGER | 年份 |
| round | INTEGER | 分站序号 |
| air_temp_avg | REAL | 平均气温 (°C) |
| track_temp_avg | REAL | 平均赛道温度 (°C) |
| humidity_avg | REAL | 平均湿度 (%) |
| pressure_avg | REAL | 平均气压 |
| had_rain | INTEGER | 是否下雨 (1=是, 0=否) |
| wind_speed_max | REAL | 最大风速 |

### sprint_points — 冲刺赛
| 列 | 类型 | 说明 |
|----|------|------|
| year | INTEGER | 年份 |
| round | INTEGER | 分站序号 |
| driver | TEXT | 车手缩写 |
| position | INTEGER | 冲刺赛名次 |
| points | REAL | 冲刺赛积分 |
| sq_pos | INTEGER | 冲刺排位赛发车位 |

### sessions — 练习赛 / 排位赛
| 列 | 类型 | 说明 |
|----|------|------|
| year | INTEGER | 年份 |
| round | INTEGER | 分站序号 |
| driver | TEXT | 车手缩写 |
| session_type | TEXT | 类型: FP1/FP2/FP3/Q |
| best_lap_sec | REAL | 最快圈速（秒） |
| laps_count | INTEGER | 完成圈数 |
| position | INTEGER | 名次 |

### driver_names — 车手姓名映射
| 列 | 类型 | 说明 |
|----|------|------|
| driver | TEXT | 缩写 |
| full_name | TEXT | 全名 |

## 常用车手中文名 → 缩写速查

用户常说中文名，你需要匹配到 driver 缩写：
- 维斯塔潘/潘子 → VER, 汉密尔顿/老汉 → HAM, 勒克莱尔/乐扣 → LEC, 诺里斯 → NOR
- 赛恩斯 → SAI, 拉塞尔 → RUS, 皮亚斯特里 → PIA, 阿隆索 → ALO
- 佩雷兹/佩大师 → PER, 角田裕毅 → TSU, 博塔斯 → BOT, 里卡多 → RIC
- 周冠宇 → ZHO, 马格努森 → MAG, 霍肯伯格 → HUL, 斯特罗尔 → STR
- 加斯利 → GAS, 奥康 → OCO, 阿尔本 → ALB, 维特尔 → VET
- 莱科宁 → RAI, 格罗斯让 → GRO, 米克·舒马赫 → MSC, 吉奥维纳兹 → GIO
- 库比卡 → KUB, 马泽平 → MAZ, 萨金特 → SAR, 德弗里斯 → DEV, 劳森 → LAW
- 比尔曼 → BEA, 安东内利 → ANT, 哈贾尔 → HAD, 杜汉 → DOO, 博托莱托 → BOR

## 常用车队中文名 → 英文名速查

- 红牛/大红牛 → "Red Bull Racing", 法拉利 → "Ferrari", 梅赛德斯/奔驰 → "Mercedes"
- 迈凯伦 → "McLaren", 阿斯顿马丁 → "Aston Martin", 阿尔派/雷诺 → "Alpine"
- 威廉姆斯 → "Williams", 哈斯 → "Haas F1 Team", 索伯/奥迪 → "Kick Sauber"
- 小红牛 → "Racing Bulls"（2024+）/ "AlphaTauri"（2020-2023）/ "Toro Rosso"（2019 前）
- 赛点/印度力量 → "Racing Point"（2019-2020）/ "Force India"（2018）

## 重要规则

1. **只生成 SELECT 语句**，不要 INSERT/UPDATE/DELETE/DROP。
2. **车手名匹配**：用户可能说中文名，用上面的速查表匹配 driver 缩写。如找不到，查 driver_names 表的 full_name 列模糊匹配。
3. **车队名** 在 results.team 列，是英文（如 "Red Bull Racing", "Ferrari"）。用上面的速查表匹配。
4. **赛道/分站** 通过 events 表的 event_name, location, country 匹配。
5. **积分计算**：总积分 = results.points + sprint_points.points（需要 LEFT JOIN 或子查询）。如果用户问"总积分"或"积分榜"，必须包含冲刺赛积分。
6. **领奖台** = position <= 3（正赛名次 ≤ 3）。
7. **完赛率** = status='Finished' 的场次 / 总参赛场次。
8. **进站次数** 通过 laps 表 is_pit=1 统计。
9. **SQLite 语法**：不支持 TOP，用 LIMIT；字符串用单引号；日期函数用 strftime。
10. 只返回一条可执行的 SQL 语句，不要多余的解释。
"""

# ═══════════════════════════════════════════════════════════
# Safety check
# ═══════════════════════════════════════════════════════════

def _is_safe_sql(sql: str) -> bool:
    """Reject any SQL that isn't a read-only SELECT."""
    cleaned = sql.strip().upper()
    # Remove leading comments
    cleaned = re.sub(r'--.*?\n', '', cleaned)
    cleaned = re.sub(r'/\*.*?\*/', '', cleaned, flags=re.DOTALL)
    cleaned = cleaned.strip()

    if not cleaned.startswith("SELECT"):
        return False

    # Block dangerous keywords even inside SELECT
    dangerous = ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
                 "CREATE", "ATTACH", "DETACH", "PRAGMA"]
    for word in dangerous:
        if re.search(rf'\b{word}\b', cleaned):
            return False

    return True


# ═══════════════════════════════════════════════════════════
# LLM client
# ═══════════════════════════════════════════════════════════

def _get_client() -> OpenAI:
    cfg = st.secrets.get("ai", {})
    return OpenAI(
        api_key=cfg.get("api_key", "sk-unknown"),
        base_url=cfg.get("base_url", "https://api.deepseek.com"),
    )


def _get_model() -> str:
    return st.secrets.get("ai", {}).get("model", "deepseek-chat")


# ═══════════════════════════════════════════════════════════
# Core: Text → SQL → Data → Answer
# ═══════════════════════════════════════════════════════════

def ask(question: str, history: list | None = None) -> str:
    """Answer a natural-language F1 question by generating and executing SQL.

    Args:
        question: The user's question in Chinese.
        history: List of {"role": "user"/"assistant", "content": "..."} — last N exchanges.
    """
    client = _get_client()
    model = _get_model()
    context = (history or [])[-10:]  # Last 10 messages for context

    # ── Step 1: question → SQL (with conversation context) ──
    messages = [{"role": "system", "content": SCHEMA_PROMPT}]
    # Include recent context so model understands pronouns / references
    for m in context:
        role = m["role"]
        if role == "user":
            messages.append({"role": "user", "content": f"[历史提问] {m['content']}"})
        # Skip assistant answers in SQL step — only questions matter for SQL generation
    messages.append({"role": "user", "content": f"请根据以下问题生成一条 SQLite 查询：\n\n{question}"})

    sql_response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=1000,
    )
    raw = sql_response.choices[0].message.content.strip()

    # If the model returned a knowledge answer (F1 but no SQL needed)
    if raw.upper().startswith("KNOWLEDGE:"):
        return raw.split("KNOWLEDGE:", 1)[1].strip()

    # If the model refused (non-F1 question), return the refusal directly
    if not _looks_like_sql(raw):
        return raw

    # Extract SQL from possible markdown code block
    sql = _extract_sql(raw)

    if not sql:
        return f"❌ 未能生成有效 SQL。模型返回：\n```\n{raw[:300]}\n```"

    if not _is_safe_sql(sql):
        return f"❌ 安全限制：只允许 SELECT 查询。生成的语句被拒绝。"

    # ── Step 2: execute SQL ──
    try:
        db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        df = pd.read_sql_query(sql, db)
        db.close()
    except Exception as e:
        return f"❌ SQL 执行错误：{e}\n\n生成的 SQL：\n```sql\n{sql}\n```"

    if df.empty:
        return f"📭 查询结果为空。SQL：\n```sql\n{sql}\n```"

    # ── Step 3: results → natural language (with full conversation context) ──
    result_text = df.to_markdown(index=False)
    answer_messages = [
        {"role": "system", "content": "你是 F1 Oracle，专为一级方程式赛车数据设计的 AI 助手。根据查询结果用简洁的中文回答用户问题。可以补充分析见解，但不要编造数据。回答控制在 1-4 句话，自然流畅。"},
    ]
    # Include full conversation context
    for m in context:
        answer_messages.append(m)
    answer_messages.append({"role": "user", "content": f"用户问题：{question}\n\n查询结果：\n```\n{result_text}\n```\n\n请用中文回答。"})

    answer_response = client.chat.completions.create(
        model=model,
        messages=answer_messages,
        temperature=0.3,
        max_tokens=800,
    )
    return answer_response.choices[0].message.content.strip()


def suggest_followups(question: str, answer: str, history: list | None = None) -> list[str]:
    """Generate 3 follow-up question suggestions based on the conversation."""
    client = _get_client()
    model = _get_model()
    context = (history or [])[-6:]

    messages = [
        {"role": "system", "content": (
            "你是 F1 数据分析助手。根据用户刚刚的提问和 AI 的回答，生成 3 个自然的追问。"
            "要求：\n"
            "1. 每个追问应该能通过查数据库回答（涉及车手、车队、赛道、积分、圈速等具体数据）\n"
            "2. 追问应与当前话题相关，引导用户从不同角度深入了解\n"
            "3. 每个追问不超过 20 个中文字\n"
            "4. 只返回 3 行纯文本，每行一个问题，不要编号、不要引号、不要其他内容"
        )},
    ]
    for m in context:
        messages.append(m)
    messages.append({"role": "user", "content": f"用户问：{question}\n\nAI 答：{answer}\n\n请生成 3 个追问："})

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,
            max_tokens=200,
        )
        raw = resp.choices[0].message.content.strip()
        questions = [line.strip().lstrip("0123456789.、-）) ") for line in raw.split("\n") if line.strip()]
        return questions[:3]
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════
# Feature: Natural Language → Chart
# ═══════════════════════════════════════════════════════════

CHART_SYSTEM_PROMPT = """你是 F1 数据可视化助手。用户用中文描述想要的图表，你生成 SQL 查询和图表配置。

## 输出格式
严格返回以下 JSON，不要有其他内容：
```json
{
  "sql": "SELECT ...",
  "chart_type": "bar",
  "x": "列名",
  "y": "列名",
  "color": "列名或null",
  "title": "图表标题",
  "x_label": "X轴标签",
  "y_label": "Y轴标签",
  "sort": "asc或desc或null"
}
```

## chart_type 可选值
- bar: 柱状图（适合积分、排名、计数对比）
- line: 折线图（适合走势、圈速变化）
- scatter: 散点图（适合相关性分析）

## 数据库结构（SQLite）

### results — 正赛成绩
| 列 | 说明 |
|----|------|
| year | 年份 (INTEGER) |
| round | 分站序号 (INTEGER) |
| driver | 车手缩写 TEXT，如 'VER', 'HAM' |
| full_name | 车手全名 TEXT |
| team | 车队英文名 TEXT |
| position | 完赛名次 (INTEGER, NULL=退赛) |
| grid | 发车位 (INTEGER) |
| points | 正赛积分 (REAL) |
| status | 状态 TEXT |
| q1_sec/q2_sec/q3_sec | 排位赛秒数 (REAL) |
| quali_pos | 排位名次 (INTEGER) |

### events — 赛历
| 列 | 说明 |
|----|------|
| year | 年份 |
| round | 分站序号 |
| event_name | 赛事名 TEXT |
| country | 国家 TEXT |
| location | 赛道 TEXT |

### laps — 每圈数据
| 列 | 说明 |
|----|------|
| year, round, driver | 同上 |
| lap_number | 圈号 |
| lap_time | 圈速秒数 (REAL) |
| compound | 轮胎配方 TEXT |
| tyre_life | 轮胎已用圈数 |
| stint | 第几段 stint |
| is_pit | 是否进站圈 (1=是) |

### sprint_points — 冲刺赛
| 列 | 说明 |
|----|------|
| year, round, driver | 同上 |
| position | 冲刺赛名次 |
| points | 冲刺赛积分 |
| sq_pos | SQ 排位发车位 |

### sessions — 练习赛
| 列 | 说明 |
|----|------|
| year, round, driver | 同上 |
| session_type | FP1/FP2/FP3 |
| best_lap_sec | 最快圈速秒数 |
| laps_count | 完成圈数 |

### weather — 天气
| 列 | 说明 |
|----|------|
| year, round | 同上 |
| air_temp_avg | 气温 (REAL) |
| track_temp_avg | 赛道温度 (REAL) |
| humidity_avg | 湿度 (REAL) |
| had_rain | 是否下雨 (1=是) |

## 关联方式
- results 和 events 通过 year + round 关联（不是 event_id！）
- results 和 laps 通过 year + round + driver 关联
- results 和 sprint_points 通过 year + round + driver 关联

## 规则
1. 只生成 SELECT 语句，不要 INSERT/UPDATE/DELETE
2. **车手名匹配**：用 driver 列（缩写），不是 driver_id。维斯塔潘→'VER', 汉密尔顿→'HAM', 勒克莱尔→'LEC', 诺里斯→'NOR', 赛恩斯→'SAI', 拉塞尔→'RUS', 皮亚斯特里→'PIA', 阿隆索→'ALO', 佩雷兹→'PER', 周冠宇→'ZHO', 博塔斯→'BOT', 角田裕毅→'TSU', 里卡多→'RIC', 马格努森→'MAG', 霍肯伯格→'HUL', 加斯利→'GAS', 奥康→'OCO', 阿尔本→'ALB', 斯特罗尔→'STR'
3. **车队名匹配**：用 team 列。红牛→'Red Bull Racing', 法拉利→'Ferrari', 梅赛德斯→'Mercedes', 迈凯伦→'McLaren'
4. **表关联用 year + round**，不要用不存在的 id 列
5. SQLite 语法：不支持 TOP，用 LIMIT；字符串用单引号
6. SELECT 中可以用中文别名（AS '积分'），但 GROUP BY/ORDER BY 用原始列名
7. 如果用户没指定年份，默认查 2024
8. x 是横轴（分类/时间），y 是纵轴（数值）
9. **默认用 bar（柱状图）**，除非用户明确说"折线图"或数据是连续数值（如圈速随圈号变化、温度随时间变化）。"每站积分""各站排名""各车手对比"这类按分站/车手分类的数据，一律用 bar
10. x 轴用可读文本：按分站查时用 event_name（赛事名），按车手查时用 driver。不要用 round 数字做 x 轴
"""


_CHART_CACHE: dict[str, dict] = {}


def ask_chart(description: str) -> dict | None:
    """Generate a chart spec from natural language description.

    Returns dict with keys: sql, chart_type, x, y, color, title, x_label, y_label, sort
    Returns None on failure. Results are cached for 1 hour.
    """
    if description in _CHART_CACHE:
        return _CHART_CACHE[description]
    client = _get_client()
    model = _get_model()

    messages = [
        {"role": "system", "content": CHART_SYSTEM_PROMPT},
        {"role": "user", "content": description},
    ]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            max_tokens=800,
        )
        raw = resp.choices[0].message.content.strip()

        # Extract JSON from possible markdown code block
        import json
        m = re.search(r'```(?:json)?\s*\n?(.*?)```', raw, re.DOTALL | re.IGNORECASE)
        if m:
            raw = m.group(1).strip()

        spec = json.loads(raw)

        # Validate required keys
        if not spec.get("sql") or not spec.get("chart_type"):
            return None
        if not _is_safe_sql(spec["sql"]):
            return None

        _CHART_CACHE[description] = spec
        return spec
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# Feature: AI Race Report
# ═══════════════════════════════════════════════════════════

def generate_race_report(year: int, round_num: int, event_name: str, race_data: dict) -> str:
    """Generate a Chinese race analysis report.

    Args:
        year: Season year
        round_num: Round number
        event_name: Event name (e.g. "Chinese Grand Prix")
        race_data: dict with keys: results (df), weather (df), laps_summary (df), sprint (df or None)
    """
    client = _get_client()
    model = _get_model()

    # Build data summary for the LLM
    parts = [f"赛事：{year} {event_name}（第{round_num}站）\n"]

    # Weather
    w = race_data.get("weather")
    if w is not None and not w.empty:
        row = w.iloc[0]
        rain = "有雨" if row.get("had_rain") else "无雨"
        parts.append(f"天气：气温 {row.get('air_temp_avg', 0):.1f}°C，"
                     f"赛道温度 {row.get('track_temp_avg', 0):.1f}°C，"
                     f"湿度 {row.get('humidity_avg', 0):.0f}%，{rain}")

    # Race results
    res = race_data.get("results")
    if res is not None and not res.empty:
        parts.append("\n正赛成绩（前10名）：")
        for _, r in res.head(10).iterrows():
            pos = int(r["position"]) if pd.notna(r["position"]) else "DNF"
            pts = r.get("points", 0)
            grid = int(r["grid"]) if pd.notna(r.get("grid")) else "?"
            status = r.get("status", "")
            parts.append(f"  P{pos} {r['full_name']} ({r['team']}) — "
                         f"发车P{grid}, 积分{pts}, {status}")

        # DNF summary
        dnfs = res[res["status"] != "Finished"]
        if not dnfs.empty:
            parts.append(f"\n退赛 {len(dnfs)} 人：")
            for _, r in dnfs.iterrows():
                parts.append(f"  {r['full_name']} — {r['status']}")

    # Sprint
    sp = race_data.get("sprint")
    if sp is not None and not sp.empty:
        parts.append("\n冲刺赛前5：")
        for _, r in sp.head(5).iterrows():
            parts.append(f"  P{int(r['position'])} {r['full_name']} — 积分{r.get('points', 0)}")

    # Lap time summary
    laps = race_data.get("laps_summary")
    if laps is not None and not laps.empty:
        parts.append("\n各车手最快圈速：")
        for _, r in laps.iterrows():
            t = r.get("best_lap", 0)
            if t and t > 0:
                mins = int(t // 60)
                secs = t % 60
                parts.append(f"  {r['driver']}: {mins}:{secs:06.3f}")

    data_text = "\n".join(parts)

    messages = [
        {"role": "system", "content": (
            "你是一位专业的 F1 赛事分析师。根据提供的比赛数据，撰写一篇简洁的中文赛事战报。\n"
            "要求：\n"
            "1. 200-400 字，像体育记者写的赛事回顾\n"
            "2. 重点分析：冠军表现、关键超越、退赛事件、策略亮点\n"
            "3. 如果有天气变化，分析天气对比赛的影响\n"
            "4. 语言生动专业，使用 F1 术语（undercut、overcut、DRS 等）\n"
            "5. 不要编造数据中没有的信息\n"
            "6. 使用中文，车手名用中文（维斯塔潘、汉密尔顿等）"
        )},
        {"role": "user", "content": data_text},
    ]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5,
            max_tokens=1500,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"生成失败：{e}"


# ═══════════════════════════════════════════════════════════
# Feature: AI Season Review
# ═══════════════════════════════════════════════════════════

def generate_season_review(year: int, season_data: dict) -> str:
    """Generate a Chinese season review report.

    Args:
        year: Season year
        season_data: dict with keys:
            standings (df): driver standings with columns driver, team, pts, wins, podiums
            team_standings (df): team standings with columns team, pts, wins
            winners (df): race winners per round with columns round, event_name, driver, team
            stats (df): extra stats with columns driver, team, dnf_count, avg_grid, avg_fin
    """
    client = _get_client()
    model = _get_model()

    parts = [f"赛季：{year}\n"]

    # Driver standings
    standings = season_data.get("standings")
    if standings is not None and not standings.empty:
        parts.append("车手积分榜（前10）：")
        for i, (_, r) in enumerate(standings.head(10).iterrows()):
            pts = r.get("pts", 0)
            wins = r.get("wins", 0)
            podiums = r.get("podiums", 0)
            parts.append(f"  P{i+1} {r['driver']} ({r['team']}) — "
                         f"积分{pts:.0f}, 冠军{wins}, 领奖台{podiums}")

    # Team standings
    team_st = season_data.get("team_standings")
    if team_st is not None and not team_st.empty:
        parts.append("\n车队积分榜：")
        for i, (_, r) in enumerate(team_st.iterrows()):
            parts.append(f"  P{i+1} {r['team']} — 积分{r['pts']:.0f}, 冠军{r['wins']}")

    # Race winners
    winners = season_data.get("winners")
    if winners is not None and not winners.empty:
        parts.append(f"\n全年{len(winners)}站冠军：")
        for _, r in winners.iterrows():
            parts.append(f"  R{int(r['round'])} {r['event_name']}: {r['driver']}")

    # Extra stats
    stats = season_data.get("stats")
    if stats is not None and not stats.empty:
        # Most DNFs
        top_dnf = stats.nlargest(3, "dnf_count")
        if not top_dnf.empty and top_dnf.iloc[0]["dnf_count"] > 0:
            parts.append("\n退赛最多的车手：")
            for _, r in top_dnf.iterrows():
                if r["dnf_count"] > 0:
                    parts.append(f"  {r['driver']} — {int(r['dnf_count'])} 次退赛")

    data_text = "\n".join(parts)

    messages = [
        {"role": "system", "content": (
            "你是一位专业的 F1 赛季分析师。根据提供的赛季数据，撰写一篇中文赛季回顾报告。\n"
            "要求：\n"
            "1. 300-500 字，像体育记者写的赛季总结\n"
            "2. 重点分析：总冠军争夺、车队竞争格局、关键转折站、惊喜与失望\n"
            "3. 提及具体数据（积分、冠军次数、领奖台）增强说服力\n"
            "4. 语言生动专业，使用 F1 术语\n"
            "5. 不要编造数据中没有的信息\n"
            "6. 使用中文，车手名用中文（维斯塔潘、汉密尔顿等）\n"
            "7. 按「总冠军→车队格局→关键转折→赛季亮点」的结构组织"
        )},
        {"role": "user", "content": data_text},
    ]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5,
            max_tokens=2000,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"生成失败：{e}"


# ═══════════════════════════════════════════════════════════
# Feature: AI Strategy Analysis
# ═══════════════════════════════════════════════════════════

def generate_strategy_analysis(year: int, round_num: int, event_name: str,
                                strategy_data: dict) -> str:
    """Generate a Chinese race strategy analysis.

    Args:
        year: Season year
        round_num: Round number
        event_name: Event name
        strategy_data: dict with keys:
            pitstops (df): pit stop data — driver, lap_number, compound, stint
            stint_summary (df): stint breakdown — driver, stint, compound, stint_laps
            results (df): race results — driver, full_name, team, position, grid, points
            weather (df): weather data
    """
    client = _get_client()
    model = _get_model()

    parts = [f"赛事：{year} {event_name}（第{round_num}站）\n"]

    # Weather
    w = strategy_data.get("weather")
    if w is not None and not w.empty:
        row = w.iloc[0]
        rain = "有雨" if row.get("had_rain") else "无雨"
        parts.append(f"天气：气温 {row.get('air_temp_avg', 0):.1f}°C，"
                     f"赛道温度 {row.get('track_temp_avg', 0):.1f}°C，{rain}")

    # Race results (top 10)
    res = strategy_data.get("results")
    if res is not None and not res.empty:
        parts.append("\n正赛成绩（前10）：")
        for _, r in res.head(10).iterrows():
            pos = int(r["position"]) if pd.notna(r["position"]) else "DNF"
            grid = int(r["grid"]) if pd.notna(r.get("grid")) else "?"
            gain = int(grid) - int(pos) if pd.notna(r.get("grid")) and pd.notna(r["position"]) else 0
            gain_str = f"↑{gain}" if gain > 0 else (f"↓{abs(gain)}" if gain < 0 else "→")
            parts.append(f"  P{pos} {r['full_name']} ({r['team']}) — "
                         f"发车P{grid} {gain_str}, 积分{r.get('points', 0)}")

    # Stint summary (tire strategy per driver)
    stints = strategy_data.get("stint_summary")
    if stints is not None and not stints.empty:
        parts.append("\n轮胎策略（各车手停站方案）：")
        # Group by driver
        for driver in stints["driver"].unique():
            driver_stints = stints[stints["driver"] == driver]
            strategy_parts = []
            for _, s in driver_stints.iterrows():
                compound = s.get("compound", "?")
                laps = int(s.get("stint_laps", 0))
                strategy_parts.append(f"{compound}×{laps}")
            parts.append(f"  {driver}: {' → '.join(strategy_parts)}")

    # Pit stop count per driver
    pitstops = strategy_data.get("pitstops")
    if pitstops is not None and not pitstops.empty:
        pit_counts = pitstops.groupby("driver").size().sort_values(ascending=False)
        if not pit_counts.empty:
            parts.append(f"\n停站次数统计：")
            for driver, count in pit_counts.head(10).items():
                parts.append(f"  {driver}: {count} 次")

    data_text = "\n".join(parts)

    messages = [
        {"role": "system", "content": (
            "你是一位专业的 F1 策略分析师。根据提供的比赛数据，撰写一篇中文策略分析报告。\n"
            "要求：\n"
            "200-400 字，重点分析：\n"
            "1. 主流策略：大多数车手采用的停站方案和轮胎选择\n"
            "2. 策略亮点：哪些车手通过策略获得了位置提升（发车 vs 完赛名次）\n"
            "3. undercut/overcut 效果：早停站 vs 晚停站的优劣\n"
            "4. 轮胎管理：哪些车手在硬胎/软胎上的表现更出色\n"
            "5. 如果有天气变化，分析天气对策略的影响\n"
            "6. 不要编造数据中没有的信息\n"
            "7. 使用中文，车手名用中文，使用 F1 策略术语"
        )},
        {"role": "user", "content": data_text},
    ]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5,
            max_tokens=1500,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"生成失败：{e}"


# ═══════════════════════════════════════════════════════════
# Feature: AI Track Guide
# ═══════════════════════════════════════════════════════════

def generate_track_guide(location: str, track_name_cn: str, track_data: dict) -> str:
    """Generate a Chinese track guide with historical analysis.

    Args:
        location: Track location name in DB (e.g. "Shanghai")
        track_name_cn: Chinese track name (e.g. "上海国际赛车场")
        track_data: dict with keys:
            overtaking (df): grid vs finish per driver per year — year, round, driver, full_name, team, grid, position
            tire_usage (df): compound usage across years — year, compound, laps, driver_count
            weather (df): weather across years — year, round, air_temp_avg, track_temp_avg, humidity_avg, had_rain
            fastest (df): fastest laps — year, driver, fastest, team
            dnf_stats (df): DNF causes — year, status, count
    """
    client = _get_client()
    model = _get_model()

    parts = [f"赛道：{track_name_cn}（{location}）\n"]

    # Overtaking analysis: grid vs finish
    ot = track_data.get("overtaking")
    if ot is not None and not ot.empty:
        ot = ot.copy()
        ot["gain"] = ot["grid"] - ot["position"]
        avg_gain = ot["gain"].mean()
        max_gain = ot.loc[ot["gain"].idxmax()]
        max_loss = ot.loc[ot["gain"].idxmin()]
        gained = (ot["gain"] > 0).sum()
        lost = (ot["gain"] < 0).sum()
        same = (ot["gain"] == 0).sum()
        total = len(ot)
        parts.append(f"历史超车数据（{ot['year'].nunique()} 年 {total} 条记录）：")
        parts.append(f"  平均位置变化：{avg_gain:+.2f} 位")
        parts.append(f"  位置提升：{gained}次 ({gained/total*100:.0f}%)，位置下降：{lost}次 ({lost/total*100:.0f}%)，不变：{same}次 ({same/total*100:.0f}%)")
        parts.append(f"  最大超车：{max_gain['full_name']} ({int(max_gain['year'])}) "
                     f"从 P{int(max_gain['grid'])} 到 P{int(max_gain['position'])}（+{int(max_gain['gain'])}位）")
        parts.append(f"  最大丢位：{max_loss['full_name']} ({int(max_loss['year'])}) "
                     f"从 P{int(max_loss['grid'])} 到 P{int(max_loss['position'])}（{int(max_loss['gain'])}位）")
        # Overtaking frequency by position range
        top6 = ot[ot["grid"] <= 6]
        mid = ot[(ot["grid"] > 6) & (ot["grid"] <= 12)]
        back = ot[ot["grid"] > 12]
        if not top6.empty:
            parts.append(f"  前6起步({len(top6)}次)平均变化：{top6['gain'].mean():+.2f} 位，提升率{( top6['gain']>0).sum()/len(top6)*100:.0f}%")
        if not mid.empty:
            parts.append(f"  中游7-12({len(mid)}次)平均变化：{mid['gain'].mean():+.2f} 位，提升率{(mid['gain']>0).sum()/len(mid)*100:.0f}%")
        if not back.empty:
            parts.append(f"  后排13+({len(back)}次)平均变化：{back['gain'].mean():+.2f} 位，提升率{(back['gain']>0).sum()/len(back)*100:.0f}%")

    # Tire strategy patterns
    tires = track_data.get("tire_usage")
    if tires is not None and not tires.empty:
        parts.append("\n轮胎使用偏好：")
        compound_stats = tires.groupby("compound").agg(
            total_laps=("laps", "sum"),
            appearances=("driver_count", "sum")
        ).sort_values("total_laps", ascending=False)
        for comp, row in compound_stats.iterrows():
            parts.append(f"  {comp}: 总使用 {int(row['total_laps'])} 圈, "
                         f"共 {int(row['appearances'])} 车次选用")

    # Weather patterns
    weather = track_data.get("weather")
    if weather is not None and not weather.empty:
        rain_count = weather["had_rain"].sum()
        total_races = len(weather)
        avg_air = weather["air_temp_avg"].mean()
        avg_track = weather["track_temp_avg"].mean()
        parts.append(f"\n天气特征（{total_races} 年数据）：")
        parts.append(f"  下雨概率：{rain_count}/{total_races} ({rain_count/total_races*100:.0f}%)")
        parts.append(f"  平均气温：{avg_air:.1f}°C，平均赛道温度：{avg_track:.1f}°C")
        if rain_count > 0:
            rain_years = weather[weather["had_rain"] == 1]["year"].tolist()
            parts.append(f"  下雨年份：{', '.join(str(int(y)) for y in rain_years)}")

    # Fastest lap records
    fastest = track_data.get("fastest")
    if fastest is not None and not fastest.empty:
        best = fastest.loc[fastest["fastest"].idxmin()]
        mins = int(best["fastest"] // 60)
        secs = best["fastest"] % 60
        parts.append(f"\n最快圈速纪录：{mins}:{secs:06.3f} — "
                     f"{best['driver']} ({int(best['year'])})")

    # DNF statistics
    dnf = track_data.get("dnf_stats")
    if dnf is not None and not dnf.empty:
        total_dnf = dnf["count"].sum()
        parts.append(f"\n退赛统计：共 {int(total_dnf)} 次退赛")
        top_causes = dnf.groupby("status")["count"].sum().nlargest(3)
        for cause, cnt in top_causes.items():
            parts.append(f"  {cause}: {int(cnt)} 次")

    data_text = "\n".join(parts)

    messages = [
        {"role": "system", "content": (
            "你是一位专业的 F1 赛道分析师。根据提供的历史数据，撰写一篇中文赛道攻略。\n"
            "要求：\n"
            "300-500 字，重点分析：\n"
            "1. 赛道特征：基于超车数据判断这是一条「超车容易/困难」的赛道，分析发车位的重要性\n"
            "   — 必须引用数据中的具体数字（平均位置变化、提升率百分比），不要四舍五入到整数\n"
            "   — 如果平均变化接近0但不为0，用「几乎不变」「微幅变化」等表述，不要说「为0」\n"
            "   — 描述提升率和下降率时，用客观中性的语气。提升率高于下降率时，不要用「仅为」形容提升率，也不要用「高达」形容下降率\n"
            "2. 轮胎策略：哪种轮胎最受欢迎，可能的最优停站策略（一停/两停）\n"
            "3. 天气影响：下雨概率、雨战历史表现\n"
            "4. 观赛建议：哪些位置的争夺最值得关注\n"
            "5. 不要编造数据中没有的信息\n"
            "6. 使用中文，使用 F1 术语（DRS区、制动区、undercut 等）"
        )},
        {"role": "user", "content": data_text},
    ]

    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.5,
            max_tokens=2000,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"生成失败：{e}"


def _looks_like_sql(raw: str) -> bool:
    """Check if the response contains a SQL query (not a refusal)."""
    return bool(re.search(r'\bSELECT\b', raw, re.IGNORECASE))


def _extract_sql(raw: str) -> str | None:
    """Extract SQL from LLM response, handling markdown code blocks."""
    # Try ```sql ... ``` first
    m = re.search(r'```(?:sql)?\s*\n?(.*?)```', raw, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    # Try to find a SELECT statement
    m = re.search(r'(SELECT\b.*?)(?:;|\n\n|$)', raw, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip(";")
    # Fallback: just return the raw text if it starts with SELECT
    if raw.upper().strip().startswith("SELECT"):
        return raw.strip().rstrip(";")
    return None
