"""
Generate F1 Oracle project summary .docx on Desktop.
"""
from docx import Document
from docx.shared import Inches, Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
import os

doc = Document()

# === Styles ===
style = doc.styles['Normal']
font = style.font
font.name = 'Microsoft YaHei'
font.size = Pt(11)
style.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

for level in range(1, 4):
    h_style = doc.styles[f'Heading {level}']
    h_font = h_style.font
    h_font.color.rgb = RGBColor(0xE1, 0x06, 0x00)
    h_font.name = 'Microsoft YaHei'
    h_style.element.rPr.rFonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

# === Title ===
title = doc.add_paragraph()
title.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = title.add_run('F1 Oracle — 项目总结文档')
run.font.size = Pt(26)
run.font.bold = True
run.font.color.rgb = RGBColor(0xE1, 0x06, 0x00)

subtitle = doc.add_paragraph()
subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
run = subtitle.add_run('F1 一级方程式赛车数据可视化与分析平台')
run.font.size = Pt(14)
run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

doc.add_paragraph()

# ============================================================
# Chapter 1
# ============================================================
doc.add_heading('一、项目概述', level=1)

doc.add_paragraph(
    'F1 Oracle 是一个 F1 一级方程式赛车数据可视化与分析平台，基于 Python Streamlit 构建的 Web 仪表板。'
    '它从 FastF1 API（提供圈速、天气、轮胎等详细遥测数据）和 Jolpi Ergast API（提供官方积分和排位赛数据）'
    '拉取数据，汇总到一个本地 SQLite 数据仓库中，然后通过交互式 Web 界面展示。'
)

doc.add_paragraph('平台支持 2018-2025 共 8 个赛季的数据，页面全部使用中文（车手名、车队名、赛道名、国家名等均已翻译）。')

doc.add_heading('数据来源', level=2)
sources = [
    ('FastF1 API', '提供每圈详细数据（圈速/分段计时/轮胎/进站）、练习赛及排位赛成绩、天气数据、赛道信息等'),
    ('Jolpi Ergast API', 'F1 官方数据库的第三方封装，用于获取准确的积分、正赛名次、发车位、退赛原因等官方数据'),
]
for name, desc in sources:
    p = doc.add_paragraph()
    run = p.add_run(f'{name}：')
    run.bold = True
    p.add_run(desc)

doc.add_heading('数据库覆盖', level=2)
doc.add_paragraph('使用 SQLite 数据库（f1_oracle.db）存储以下信息：')
db_tables = [
    ('events', '赛季赛程信息（年份、轮次、赛道、国家、日期）'),
    ('results', '正赛结果（名次、积分、发车位、排位时间、退赛状态）'),
    ('laps', '每圈详细数据（圈速、分段计时、轮胎配方、进站次数）'),
    ('weather', '天气数据（气温、赛道温度、湿度、降雨、风速）'),
    ('sessions', '练习赛/排位赛成绩（圈速、名次）'),
    ('sprint_points', '冲刺赛积分及 SQ 排位名次'),
    ('driver_names', '车手缩写与全名映射'),
]
table = doc.add_table(rows=1, cols=2)
table.style = 'Light Grid Accent 1'
table.alignment = WD_TABLE_ALIGNMENT.CENTER
hdr = table.rows[0].cells
hdr[0].text = '数据表'
hdr[1].text = '说明'
for name, desc in db_tables:
    row = table.add_row().cells
    row[0].text = name
    row[1].text = desc

doc.add_paragraph()

# ============================================================
# Chapter 2
# ============================================================
doc.add_heading('二、技术栈', level=1)

tech_table = doc.add_table(rows=1, cols=3)
tech_table.style = 'Light Grid Accent 1'
tech_table.alignment = WD_TABLE_ALIGNMENT.CENTER
hdr = tech_table.rows[0].cells
hdr[0].text = '分类'
hdr[1].text = '技术'
hdr[2].text = '用途'

techs = [
    ('编程语言', 'Python 3.11', '整个项目的核心语言'),
    ('Web 框架', 'Streamlit ≥1.35', '构建交互式数据仪表板'),
    ('可视化', 'Plotly ≥5.20', '交互式图表（柱状图、折线图、热力图）'),
    ('数据获取', 'FastF1 ≥3.3.0', '从 F1 官方遥测 API 获取圈速/天气/轮胎数据'),
    ('HTTP 请求', 'Requests ≥2.32', '调用 Jolpi Ergast API 获取官方积分/排位'),
    ('数据处理', 'Pandas ≥2.0 / NumPy ≥1.24', '数据清洗、转换、分析'),
    ('数据存储', 'SQLite (WAL 模式)', '本地数据仓库，支持并发读取'),
    ('序列化', 'PyArrow ≥15.0', 'Streamlit DataFrame 高效序列化'),
    ('文档生成', 'python-docx', '生成项目总结 Word 文档'),
]
for cat, tech, use in techs:
    row = tech_table.add_row().cells
    row[0].text = cat
    row[1].text = tech
    row[2].text = use

doc.add_paragraph()

# ============================================================
# Chapter 3
# ============================================================
doc.add_heading('三、运行流程', level=1)

doc.add_heading('3.1 系统架构', level=2)

arch_text = (
    'FastF1 API ──→ ingest.py (ETL) ──→ f1_oracle.db (SQLite)\n'
    '                                      │\n'
    'Jolpi API ──→ fetch_official.py ──→ ─┘ (修正积分/排位)\n'
    '                                      │\n'
    '                          build_sprint.py (冲刺赛)\n'
    '                                      │\n'
    '                                      ▼\n'
    '                             app.py (Streamlit)\n'
    '                                      │\n'
    '               ┌────┬────────┼────────┬────┐\n'
    '          赛季总览  分站详情  车手档案  赛道分析'
)
p = doc.add_paragraph()
run = p.add_run(arch_text)
run.font.name = 'Consolas'
run.font.size = Pt(10)

doc.add_heading('3.2 ETL 数据导入管道', level=2)
doc.add_paragraph('核心文件：src/etl/schema.py（表结构定义）+ src/etl/ingest.py（导入逻辑）')

steps = [
    'init_db() — 初始化数据库，创建 events / results / laps / weather / sessions / driver_names 表',
    'ingest_events() — 从 FastF1 get_event_schedule() 导入赛季赛程，排除 round=0（Pre-Season Testing）',
    'ingest_session() — 导入练习赛 FP1/FP2/FP3 成绩到 sessions 表（需从 session.laps 计算圈速，因 Position/Time 为 NaN）',
    'ingest_qualifying() — 导入排位赛 Q1/Q2/Q3 分段计时',
    'ingest_race() — 导入正赛结果（名次/积分/状态）、圈速数据（每圈圈速/分段/轮胎/进站）、天气数据',
    'run(years=[...]) — 主入口函数，按年份序列执行完整 ETL 管道',
]
for i, step in enumerate(steps, 1):
    doc.add_paragraph(f'{i}. {step}')

doc.add_heading('3.3 数据修正与补充', level=2)

doc.add_paragraph('由于 FastF1 数据与官方 F1 积分存在偏差，需要额外步骤修正：')

fix_steps = [
    ('build_sprint.py', '动态检测赛季冲刺赛轮次，从 FastF1 Sprint session 提取最终名次并计算积分（P1=8, P2=7, ..., P8=1），写入 sprint_points 表。同时导入 SQ 冲刺排位赛发车位（sq_pos）。'),
    ('fetch_official.py', '从 Jolpi Ergast API 获取官方正赛结果（修正 position/grid/points/status/race_time）、排位赛 Q1/Q2/Q3 时间、冲刺赛官方积分。使用 CASE WHEN 逻辑保护 FastF1 的详细退赛原因不被覆盖。'),
]
for name, desc in fix_steps:
    p = doc.add_paragraph()
    run = p.add_run(f'{name}：')
    run.bold = True
    p.add_run(desc)

doc.add_heading('3.4 导入新赛季完整流程', level=2)
flow = [
    'Step 1 — ETL：python -c "from src.etl.ingest import run; run(years=[年份])"',
    'Step 2 — 冲刺赛：python scripts/build_sprint.py [年份]',
    'Step 3 — 官方修正：python scripts/fetch_official.py [年份]（顺序执行，勿并行！Jolpi API 限流）',
    'Step 4 — 翻译验证：查 DB DISTINCT 对照 DRIVER_CN / TEAM_CN / LOCATION_CN / EVENT_CN / STATUS_CN / COMPOUND_CN 补全缺失翻译',
    'Step 5 — 积分核对：对比仪表板积分榜与 F1 官方网站赛季排名',
]
for f in flow:
    p = doc.add_paragraph()
    run = p.add_run('> ')
    run.font.color.rgb = RGBColor(0xE1, 0x06, 0x00)
    p.add_run(f)

doc.add_heading('3.5 Streamlit 仪表板', level=2)

pages = [
    ('赛季总览', '车手/车队积分榜（柱状图）、积分走势图（折线图）、车手数据明细表。前三名标注金/银/铜牌，走势末端自动标注车手名+积分。'),
    ('分站详情', '天气卡片（温度/湿度/降雨四列结构）、练习赛成绩（FP1/FP2/FP3 自适应列数，冲刺赛周末仅 FP1）、排位赛 Q1/Q2/Q3 分段计时表、正赛结果表（领奖台金/银/铜左边框 + DNF 红色淡底）、圈速对比图（Plotly 交互）、轮胎使用量堆叠图。'),
    ('车手档案', '统计卡片（参赛场次/总积分/冠军数/领奖台/平均发车位/平均完赛位）、各站成绩热力图（1=深绿 → 16+=淡红）、排名走势图（标注 P3 领奖台虚线）、最快圈速柱状图。'),
    ('赛道分析', '赛道历史比赛结果表、赛道最快圈速 TOP 10 排名、赛季赛程 CSS 卡片日历（车队色左边框 + 圆角徽章 + 赛道/日期/冠军信息）。'),
]
for name, desc in pages:
    p = doc.add_paragraph()
    run = p.add_run(f'{name}：')
    run.bold = True
    p.add_run(desc)

doc.add_paragraph()

# ============================================================
# Chapter 4
# ============================================================
doc.add_heading('四、遇到的困难与解决方案', level=1)

difficulties = [
    {
        'title': '1. FastF1 正赛积分不准确',
        'problem': 'FastF1 基于圈速推算名次，其计算的积分常与 F1 官方积分有偏差（例如冲刺赛积分、部分退赛车手仍被计分等）。',
        'solution': '引入 Jolpi Ergast API 作为官方修正源。编写 fetch_official.py，对每条记录使用 CASE WHEN 逻辑：若 status 已有详细退赛原因则保留，否则用官方数据覆盖积分和 position。',
    },
    {
        'title': '2. 练习赛 Position 和 Time 字段全为 NaN',
        'problem': 'FastF1 练习赛 session.results 中的 Position/Time 列全为 NaN，不能像正赛那样直接取值。',
        'solution': '改用 session.laps 自行计算：遍历每圈数据，对每位车手取最快圈速（best_lap_sec）和总圈数（laps）。有计时圈按圈速升序排名，无计时圈置 NULL。同时用 session.results["Abbreviation"] 获取全量车手列表（避免遗漏未出场车手）。',
    },
    {
        'title': '3. 冲刺排位赛 SQ 数据获取复杂',
        'problem': 'FastF1 SQ（Sprint Qualifying）session 加载时必须同时传入 messages=True + laps=True，否则 Position 全为 NaN。赛事控制消息（race_control_messages）包含因赛道边界违规被删除的圈速，缺少则无法正确计算排位名次。',
        'solution': '加载 session 时强制开启 messages=True + laps=True。通过 race_control_messages 过滤被删除的圈速后计算最终排位。sq_pos 存入 sprint_points 表，build_sprint.py 和 fetch_official.py 均使用 ON CONFLICT DO UPDATE 保护该字段。',
    },
    {
        'title': '4. 2018 赛季特殊处理',
        'problem': (
            '2018 赛季存在多项异常：\n'
            '  • 轮胎体系为 HYPERSOFT/ULTRASOFT/SUPERSOFT（2019 后改为 SOFT/MEDIUM/HARD），需新增颜色和翻译\n'
            '  • R14（意大利站）FastF1 v3.8.3 __fix_tyre_info 函数 IndexError bug，导致 session.laps 加载崩溃\n'
            '  • Force India 车队 2019 更名 Racing Point、Toro Rosso 2020 更名 AlphaTauri\n'
            '  • Hockenheim 赛道仅 2018 出现、赛事名 Brazilian GP ≠ São Paulo GP\n'
            '  • 圈速 compound 字段含 "nan"/"None"（缺失轮胎数据）'
        ),
        'solution': (
            '① COMPOUND_CN 补全 5 种 2018 专用轮胎翻译 + Pirelli 官方色\n'
            '② ingest_race 中添加 try/except DataNotLoadedError，崩溃时结果表正常写入、圈速表跳过\n'
            '③ TEAM_CN / TEAM_FULL_CN / TEAM_COLORS 覆盖 2018 及更名后的全部车队\n'
            '④ LOCATION_CN / EVENT_CN 手动补全 Hockenheim 和 German GP\n'
            '⑤ _comp() 函数拦截空值映射为"无数据"，COMPOUND_COLORS 补灰色 #CCCCCC'
        ),
    },
    {
        'title': '5. 车队更名追踪',
        'problem': 'F1 车队生态每年变化：2023 AlphaTauri → 2024 Racing Bulls；2019-23 Alfa Romeo → 2024 Kick Sauber；2018 Force India → 2019 Racing Point → 2021 Aston Martin。改名后 TEAM_CN / TEAM_COLORS 需同步更新。',
        'solution': '建立 TEAM_CN / TEAM_FULL_CN / TEAM_COLORS 三合一字典，按年份映射。导入新赛季时执行 SELECT DISTINCT team FROM results WHERE year=X 对照补全。',
    },
    {
        'title': '6. Jolpi API 请求限流',
        'problem': 'Jolpi Ergast API 对并发请求有限流，并行跑多个年份会导致部分站数据被跳过（HTTP 429 Too Many Requests），且 fetch_official.py 需遍历所有轮次逐一请求。',
        'solution': '导入流程明确要求 build_sprint.py → fetch_official.py 顺序执行，勿并行多个年份。fetch_official.py 内逐个轮次串行请求，利用 requests 的重试机制自动等待。',
    },
    {
        'title': '7. 2018 R14 圈速数据无法加载',
        'problem': '意大利站 (Monza) 因 FastF1 内部 __fix_tyre_info 函数的 IndexError bug 导致 session.laps 加载失败。该 bug 等待 FastF1 库修复。',
        'solution': '在 ingest_race() 中用 try/except DataNotLoadedError 包裹 session.laps，拦截异常后跳过该站圈速导入，但正赛结果表正常写入。roadmap 中标记此 Issue 待修复后回填。',
    },
    {
        'title': '8. 2025 赛季自检循环与网络卡死',
        'problem': '2025 赛季实际有 24 站（R1-R24），R25 不存在。如果硬编码 TOTAL_ROUNDS=25，自检循环会无限重试。FastF1 API 加载大数据 session 时可能网络卡死（无响应超时）。',
        'solution': (
            'import_2025.py 改为从 events 表动态取 MAX(round) WHERE round>0 作为总站数。'
            '每次会话加载用 threading + 120 秒超时包装，超时自动跳过。'
            '30 分钟自检间隔，全部练习赛/排位赛就绪后自动退出。'
        ),
    },
    {
        'title': '9. 全量中文翻译维护',
        'problem': '每个赛季新增车手、赛道、车队、退赛状态码、轮胎配方，维护 8 个赛季的 DRIVER_CN / TEAM_CN / LOCATION_CN / EVENT_CN / STATUS_CN / COMPOUND_CN / COUNTRY_CN 字典极其繁琐。车手姓名翻译还需处理组合逻辑。',
        'solution': (
            '建立标准化翻译检查流程（见 notes.txt 第 18 条），导入新赛季后执行 7 条 SQL DISTINCT 查询对照补全。'
            'names_cn.py 提供自动回退机制：车手英文全名拆分为名+姓，通过 FIRST_NAME_CN / LAST_NAME_CN 字典组合翻译。'
            '未收录的罕见名/姓将在界面显示英文原文，不会崩溃。'
        ),
    },
]

for d in difficulties:
    doc.add_heading(d['title'], level=2)
    p = doc.add_paragraph()
    run = p.add_run('问题：')
    run.bold = True
    p.add_run(d['problem'])
    p2 = doc.add_paragraph()
    run2 = p2.add_run('解决方案：')
    run2.bold = True
    p2.add_run(d['solution'])

# ============================================================
# Chapter 5
# ============================================================
doc.add_heading('五、项目成果', level=1)

doc.add_heading('5.1 已完成功能', level=2)
results_list = [
    '覆盖 2018-2025 共 8 个完整赛季的 F1 数据（超 160 场大奖赛）',
    '4 个交互式仪表板页面：赛季总览 / 分站详情 / 车手档案 / 赛道分析',
    '全中文界面：车手名、车队名、赛道名、国家名、赛事名、轮胎配方、退赛状态全覆盖',
    'F1 红色主题 UI（#E10600）：领奖台金/银/铜边框、位置热力图、车队色卡片日历',
    'Plotly 交互图表：走势图末端车手标注、积分数值显示、领奖台虚线参考线',
    '数据完整性保障：FastF1 + Jolpi API 双源交叉验证，积分/排位/冲刺赛官方修正',
    '自动化导入管道：ETL → 冲刺赛 → 官方修正，三步完成新赛季数据导入',
    '2025 赛季自检循环脚本：每 30 分钟检查缺失数据，自动补全练习赛/排位赛',
]
for r in results_list:
    doc.add_paragraph(r, style='List Bullet')

doc.add_heading('5.2 数据统计', level=2)
stats = [
    ('已导入赛季', '2018 - 2025（8 个赛季）'),
    ('数据表', '7 张（events / results / laps / weather / sessions / sprint_points / driver_names）'),
    ('总代码行数', '约 2,000+ 行 Python'),
    ('仪表板页面', '4 个交互页面'),
    ('历年平均赛事', '21-24 站/赛季'),
]
for k, v in stats:
    p = doc.add_paragraph()
    run = p.add_run(f'{k}：')
    run.bold = True
    p.add_run(v)

doc.add_heading('5.3 未来计划', level=2)
roadmap = [
    '数据补全：2018-2024 练习赛/排位赛 Q1-Q3/冲刺赛 SQ 回填、进站数据分析、2018 R14 圈速修复',
    '新车手对比页：任选两位车手，同坐标对比圈速分布/排位/积分走势',
    '队友内斗页：同队两人积分差、排位 PK、名次对比',
    '名人堂页面：跨赛季总冠军数/胜场/领奖台/杆位总排行',
    '排位分析页：排位 vs 正赛名次变化、Q1/Q2/Q3 晋级率',
    '功能增强：车手档案统计卡升级、赛道 SVG 地图、天气可视化、跨赛季总数据',
]
for r in roadmap:
    doc.add_paragraph(r, style='List Bullet')

# === Save ===
desktop = os.path.join(os.path.expanduser('~'), 'Desktop')
path = os.path.join(desktop, 'F1_Oracle_项目总结.docx')
doc.save(path)
print(f'Document saved to: {path}')
