# F1 Oracle

> **F1 比赛结果能预测到什么程度 —— 以及不能预测什么。**

用 2018–2026 九个赛季的真实赛事数据回答这个问题。核心不是又一个数据面板，而是一套**可复现的回测框架**：任何预测想法都放进同一把尺子里量，增益必须通过配对假设检验才算数，**被证伪的方法同样记录在案**。

**中文** ｜ [English](#english)

> **Language note** — The dashboard UI and most in-code text are in **Chinese**. If you'd
> like to use this project in another language, don't be put off: the translation surface is
> small and lives in four files — see [Localization](#localization).

> **语言说明** —— 界面与代码内的文案以中文为主。若要改成其他语言，改动面其实很小
> （集中在四个文件），见 [本地化](#本地化改成其他语言)。

---

## 中文

### 核心数字

| 预测时点 | 最笨基线 | 本项目 | 提升 |
|---|---:|---:|---:|
| 排位赛前（不知发车格） | 0.5501 〔赛前积分榜〕 | **0.6071** | +0.0570 |
| 排位赛后（已知发车格） | 0.6204 〔纯发车格顺序〕 | **0.6543** | +0.0339 |
| 真实前 10 名口径 | 0.7230 | **0.7680** | +0.0450 |

数字为 2018–2025 全部 190 站的 **Spearman ρ** 均值。配对 t 检验 **t = 4.88**，8 个赛季中 7 个为正 —— 增益不是某一年的运气。

**赛中逐圈预测**：用干净圈节奏外推剩余圈数（gain = 0.25），在比赛 10%–50% 进度区间
Δρ = **+0.0128**（t = **+7.71**，**8/8 年为正**）。

### ρ 是什么，为什么不用「准确率」

ρ（Spearman 秩相关系数）问的是：**按预测排一队、按真实排一队，两个队列有多像？**

不用"准确率"，因为它必须先定一个阈值（猜中冠军算对？±2 位算对？），换个阈值数字就换一副面孔；而 ρ 用满全部名次，且只看顺序、不看差值幅度。

诚实边界也在这里：ρ 从 0.6204 提到 0.6543 在统计上显著（t = 4.88），
但**平均名次误差只从 3.51 位降到 3.40 位**。所以对外只能说"大致顺序更准了"，不能说"排得准了"。

### 同样重要的是：被证伪的东西

| 尝试 | 结果 |
|---|---|
| 退赛预测（两个模型 + 特征工程） | AUC **0.5351**（随机 = 0.500）—— 退赛基本不可预测 |
| 「风险最高 3 人」命中率 | 15.8% vs 基准 14.9% |
| 圈速中位数作为特征 | 无增量（t = 0.38） |
| 进站补偿修正 | 概念错误：「已付过的成本」不等于「优势」 |
| 权重微调（Elo 0.3 → 0.4） | 无显著增益（t = 1.44） |

最有说服力的是一个反例：把退赛者排除出评分更新（`finishers_only`）**这一个开关**，
收益 **+0.0238（t = 4.05）**，大于整个 DNF 模型的全部努力。原因不难理解 ——
退赛多由爆胎、被撞、机械故障造成，把这种随机性灌进本该衡量速度的评分里只会让它变差。

### 2026 新规年：一个真实发现

同一套权重，两个时代结论相反：

| 排位赛前 ρ | 2018–2025 | 2026 |
|---|---:|---:|
| 含 Elo | **0.6071** ✅ | 0.6372 |
| 去 Elo（仅积分榜 + 练习赛） | 0.5768 | **0.6491** ✅ |

Elo 单独在 2026 猜中冠军只有 **11.8%**（历史 54.3%），冠军平均被排到 **4.47 位**（历史 2.37 位）。
原因：Elo 天然携带 2025 及以前的赛车能力，而 2026 换了动力单元与主动空力、车队顺序被打乱，
k = 192 的衰减速度需要好几站才能把旧信息冲掉 —— 17 站显然不够。

这不是坏消息。它把一个模糊的直觉（"新规让格局变了"）变成了一个**可测的数字**。

### 数据

| | |
|---|---|
| 赛季 | 2018–2026（9 季） |
| 分站 | 190 |
| 圈速记录 | 208,108 |
| 赛道（含几何与进站损失） | 31 |
| 车手 / 车队 | 44 / 19 |
| 存储 | 单个 SQLite 文件，28 MB |

数据来自 [FastF1](https://github.com/theOehrly/FastF1)。
赛道几何与进站损失取自 MultiViewer API —— 刻意绕开遥测：单站遥测约 112 MB，
而静态 JSON 只需一个小请求，成本从 3.4 GB 降到 31 次小请求。

### 快速开始

```bash
python -m venv .venv
.venv/Scripts/activate                # Windows；macOS/Linux 用 source .venv/bin/activate
pip install -r requirements.txt

# 建库并导入 2018–2025（首次耗时较长，之后走 FastF1 本地缓存会快得多）
python -m src.etl.ingest

# 增量导入后续赛季（可断点续跑：中断后重跑只补缺失轮次）
python -m scripts.import_season 2026

# 启动仪表板
./run.ps1                             # Windows PowerShell -> http://127.0.0.1:8517
```

> **数据库不在仓库里。** 28 MB 二进制文件每次改动都会往 git 历史里永久塞一份副本，
> 因此改由脚本重建。数据全部来自公开 API，不需要任何密钥。

AI 解说功能另需 `.streamlit/secrets.toml`（该文件**已被 `.gitignore` 排除**）：

```toml
[ai]
api_key = "sk-..."
model = "deepseek-chat"
```

### 逐圈回放动画

把**任意一场**导出成一个能独立播放的 HTML —— 赛道俯视图、每台车逐圈移动、
右侧实时排行榜、进站动画（拐进维修区 → 停在车位 → 换胎闪光）。约 200 KB，
数据全部内联，不联网、无依赖，双击就能放。

```bash
python -m scripts.export_replay 2023 3     # 2023 年第 3 站（轮次，不是赛道名）
```

`outputs/` 是生成物，不入库。**生成步骤、维修区几何怎么抽、「换成你自己的赛季 / 赛道 / 语言」
改哪里，见 [回放动画指南](docs/replay-guide.md)。**

### 项目结构

```
src/
  semantics.py      完赛/退赛语义的唯一定义 —— eval / etl / model 所有判定都走这里
  etl/              取数与建库（FastF1 -> SQLite），含赛道维表
  model/            预测层：回测框架 / 预测器库 / 逐圈分析 / 脏圈识别
  dashboard/        Streamlit 界面，六个页面
scripts/            回测、导入、评估、演示等命令行工具
docs/               评估报告、对标分析与回放动画指南
```

`src/model/` 的防泄漏是**结构性**的：`make_context()` 按预测时点（`pre_quali` / `post_quali`）
决定哪些字段可见，而不是靠调用方自觉。回测框架强制用工厂函数创建预测器，
避免有状态预测器在多次运行间残留。

### 本地化（改成其他语言）

所有**用户可见**的中文都集中在**四个文件**里。其余 `.py` 文件中的中文基本是**注释与命令行输出**，
不影响界面，可以完全不管。

| 改什么 | 文件 | 具体位置 |
|---|---|---|
| 侧边栏导航名 | `src/dashboard/app.py` | `nav_pages` 与 `_page_map` 两张表 |
| 各页面标题与文案 | `src/dashboard/views/*.py` | 六个页面各一个文件 |
| 车队显示名 | `src/dashboard/common.py` | `TEAM_CN` 字典（键是英文原名，值是显示名） |
| 车手姓名 | `src/dashboard/names_cn.py` | `LAST_NAME_CN` 字典 + `auto_cn_short()` / `auto_cn_full()` |
| AI 回答语言 | `src/dashboard/ai_chat.py` | `SCHEMA_PROMPT` 及其余提示词 |

**数据库里存的是英文原名**（`VER` / `Mercedes` / `Monza`），中文只存在于展示层。
也就是说：**只改上面这几处，不动数据库、不动模型**，界面就能换成任意语言。

如果要做成**多语言切换**（而不是直接替换）：在 `common.py` 里加一层按 locale 取名的函数，
让页面统一调用它 —— 这样就不必逐个去改六个页面文件。

### 已知局限

- **冠军几乎猜不准** —— 上限约 49–55%，被比赛内的随机事件封死。价值在排序，不在猜冠军
- **2026 新规年的结论还不够硬** —— 去 Elo 更好只领先 0.0119，17 场不足以定论
- **后段（真实第 16–20 名）误差约为前段的 3 倍** —— 这正是对外应看前 10 口径的原因
- **冲刺积分与正赛积分分表存储**，未合并（为保持与历史数据可比）

更详细的分析见 [`docs/`](docs/)：2026 新规年评估、与开源项目的同场同口径对标。

### 关于与反馈

这是一个**个人兴趣项目** —— 业余时间做的，没有团队，也不是产品。它起源于一个单纯的问题：
「F1 的比赛结果到底能预测到什么程度？」

正因为是业余项目，一定还有很多我没看到的问题。**如果发现 bug、数据口径错误，或者有更好的方法，
欢迎随时开 issue**，也欢迎直接指出我哪里想错了。以下几类我尤其想知道：

- **数据口径错误** —— 某个 `status` 被误判、某个字段的语义理解反了
- **方法论漏洞** —— 某个特征其实造成了数据泄漏、某个检验用得不合适
- **更好的预测信号** —— 有我没用上、但确实有效的数据

如果这些数字让你觉得「哦，原来还能这么看」，那这个项目的目的就达到了。

---

## English

### What this is

Nine seasons of real F1 data (2018–2026), used to answer one question:

> **How predictable are F1 race results — and what isn't predictable at all.**

This is not another data viewer. The core is a **reproducible backtesting framework**:
every prediction idea is measured with the same yardstick, gains must survive a paired
significance test — and **the approaches that were falsified are documented too**.

### Headline numbers

| Prediction point | Naive baseline | This project | Gain |
|---|---:|---:|---:|
| Pre-qualifying (grid unknown) | 0.5501 〔championship standings〕 | **0.6071** | +0.0570 |
| Post-qualifying (grid known) | 0.6204 〔grid order〕 | **0.6543** | +0.0339 |
| Actual top-10 only | 0.7230 | **0.7680** | +0.0450 |

Mean **Spearman ρ** over all 190 races of 2018–2025. Paired t-test **t = 4.88**,
positive in 7 of 8 seasons — not a one-year fluke.

**In-race lap-by-lap prediction**: projecting remaining laps from clean-pace
(gain = 0.25) yields Δρ = **+0.0128** in the 10%–50% race-progress band
(t = **+7.71**, **positive in 8/8 seasons**).

### Why ρ, not "accuracy"

ρ (Spearman rank correlation) asks a single question: **line up the predicted order and
the actual order — how similar are the two queues?**

Accuracy is avoided on purpose: it requires choosing a threshold first (is a correct
winner enough? within ±2 places?), and the number changes with the threshold. ρ uses
every position, and cares only about ordering, not magnitude.

The honest boundary sits here too: raising ρ from 0.6204 to 0.6543 is statistically
significant (t = 4.88), but it moves the **mean position error only from 3.51 to 3.40**.
So the correct claim is "the rough order is better" — not "the ordering is accurate".

### Equally important: what was falsified

| Attempt | Result |
|---|---|
| DNF prediction (two models + feature engineering) | AUC **0.5351** (chance = 0.500) — essentially unpredictable |
| "Top-3 highest risk" hit rate | 15.8% vs 14.9% baseline |
| Median lap time as a feature | No gain (t = 0.38) |
| Pit-stop compensation | Conceptually wrong: a cost already paid is not an advantage |
| Weight tuning (Elo 0.3 → 0.4) | No significant gain (t = 1.44) |

The most instructive result is a counter-example: simply excluding retired drivers from
rating updates (`finishers_only`) — **one switch** — gains **+0.0238 (t = 4.05)**,
more than the entire DNF model effort. Retirements are mostly punctures, collisions and
mechanical failures; feeding that randomness into a rating meant to measure pace only
makes it worse.

### 2026: a regulation-change finding

Same weights, opposite conclusions in two eras:

| Pre-qualifying ρ | 2018–2025 | 2026 |
|---|---:|---:|
| With Elo | **0.6071** ✅ | 0.6372 |
| Without Elo (standings + practice only) | 0.5768 | **0.6491** ✅ |

Elo alone picks the winner in only **11.8%** of 2026 races (54.3% historically), and places
the eventual winner at an average of **4.47** (2.37 historically). The reason: Elo carries
car performance from 2025 and earlier, while 2026 brought new power units and active
aerodynamics that reshuffled the running order — and at k = 192, Elo needs several races to
flush out stale information. Seventeen is not enough.

This is good news, not bad. It turns a vague intuition ("the new rules changed the order")
into a **measurable number**.

### Data

| | |
|---|---|
| Seasons | 2018–2026 (9) |
| Grands Prix | 190 |
| Lap records | 208,108 |
| Circuits (with geometry + pit loss) | 31 |
| Drivers / Teams | 44 / 19 |
| Storage | single SQLite file, 28 MB |

Data from [FastF1](https://github.com/theOehrly/FastF1).
Circuit geometry and pit-loss figures come from the MultiViewer API — telemetry is
deliberately avoided: one race of telemetry is ~112 MB, while the static JSON is a single
small request. Cost drops from 3.4 GB to 31 small requests.

### Quick start

```bash
python -m venv .venv
.venv/Scripts/activate                # Windows; use source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt

# Create the database and ingest 2018-2025 (slow on first run; much faster afterwards via FastF1's cache)
python -m src.etl.ingest

# Incrementally ingest a later season (resumable: re-running only fetches missing rounds)
python -m scripts.import_season 2026

# Launch the dashboard
./run.ps1                             # Windows PowerShell -> http://127.0.0.1:8517
```

> **The database is not committed.** A 28 MB binary would permanently bloat git history on
> every change, so it is rebuilt from scripts instead. All sources are public APIs and no
> credentials are required.

The AI commentary feature additionally needs `.streamlit/secrets.toml`
(**excluded by `.gitignore`**):

```toml
[ai]
api_key = "sk-..."
model = "deepseek-chat"
```

### Lap-by-lap replay

Export **any race** into a single self-contained, playable HTML file — a top-down circuit with
every car moving lap by lap, a live timing tower, and a pit-stop animation (peel into the pit
lane → stop at the box → tyre-change flash). ~200 KB, all data inlined; no network, no
dependencies, just open it.

```bash
python -m scripts.export_replay 2023 3     # 2023, round 3 (round number, not a circuit name)
```

`outputs/` holds generated artefacts and is git-ignored. **For the generation steps, how the
pit-lane geometry is extracted, and which knobs to turn to swap in your own season / circuit /
language, see the [replay guide](docs/replay-guide.md).**

### Layout

```
src/
  semantics.py      single source of truth for finished/DNF semantics — used by every layer
  etl/              ingestion (FastF1 -> SQLite), including the circuit dimension table
  model/            prediction layer: backtest framework / predictors / lap analysis / dirty-lap detection
  dashboard/        Streamlit UI, six pages
scripts/            backtest, ingest, evaluation and demo CLIs
docs/               evaluation reports, benchmark analyses and the replay guide
```

Leakage prevention in `src/model/` is **structural**: `make_context()` decides which fields
are visible at each prediction point (`pre_quali` / `post_quali`) rather than trusting the
caller. The backtest framework forces predictors to be created through a factory, so
stateful predictors cannot leak across runs.

### Localization

Every **user-facing** Chinese string lives in just **four files**. The rest of the Chinese text
in `.py` files is comments and CLI output — it never reaches the screen, and you can ignore it.

| What to change | File | Where |
|---|---|---|
| Sidebar navigation | `src/dashboard/app.py` | the `nav_pages` and `_page_map` tables |
| Page titles and copy | `src/dashboard/views/*.py` | one file per page (six pages) |
| Team display names | `src/dashboard/common.py` | the `TEAM_CN` dict (keys are the English originals) |
| Driver names | `src/dashboard/names_cn.py` | `LAST_NAME_CN` dict + `auto_cn_short()` / `auto_cn_full()` |
| AI reply language | `src/dashboard/ai_chat.py` | `SCHEMA_PROMPT` and the other prompts |

**The database stores English originals** (`VER` / `Mercedes` / `Monza`) — every Chinese string
lives in the presentation layer. So you can switch the UI to any language **without touching the
database or the model**.

For a real language **toggle** rather than a straight replacement, add a locale-aware lookup in
`common.py` and have the pages call that — you won't have to edit six page files.

### Known limitations

- **Winners are essentially unpredictable** — capped around 49–55% by in-race randomness.
  The value is in ordering, not in calling the winner
- **The 2026 finding is not yet conclusive** — dropping Elo wins by only 0.0119 over 17 races
- **The back of the field (actual P16–P20) has ~3× the error of the front** — the reason the
  top-10 view is the one worth quoting
- **Sprint and race points are stored separately**, not merged (kept comparable with history)

See [`docs/`](docs/) for the detailed analyses: the 2026 regulation-year evaluation and a
like-for-like benchmark against a comparable open-source project.

### About & feedback

This is a **personal hobby project** — built in spare time, with no team behind it and no
product ambitions. It started from one plain question: *how predictable are F1 race results,
really?*

Precisely because it is a hobby project, there is plenty I have not seen. **If you spot a bug,
a data-semantics mistake, or a better approach, please open an issue** — and feel free to tell
me where my reasoning is wrong. The three things I would most like to hear about:

- **Data semantics** — a `status` misclassified, or a field whose meaning I got backwards
- **Methodological flaws** — a feature that actually leaks future information, or a test used badly
- **Better predictive signals** — data that works but that I have not used

If these numbers made you think "huh, I hadn't looked at it that way", the project has done its job.
