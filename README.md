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

数字为 **2018–2025 的 173 场**（不是 190 —— 190 是再加上 2026 那 17 场；两者混用会差约 0.003）
的 **Spearman ρ** 均值，全部由 `python -m scripts.readme_numbers` 产出。

**"提升"取决于拿什么当分母**，所以两张表都给：

| 预测时点 | 最笨基线 | 本项目 | 提升 |
|---|---:|---:|---:|
| 排位赛前（不知发车格） | 0.5501 〔赛前积分榜〕 | **0.6082** | +0.0582 |
| 排位赛后（已知发车格） | 0.6204 〔纯发车格顺序〕 | **0.6543** | +0.0339 |

但这两个都不是现有信号能做出的最强零拟合基线 —— 只拿最笨的当分母，会把提升放大成两倍。
**对外我主张用同复杂度口径**：

| 预测时点 | 同复杂度基线（同样零拟合） | 本项目 | **相对提升** |
|---|---:|---:|---:|
| 排位赛前 | 0.5768 〔积分榜 + 练习赛〕 | **0.6082** | **+0.0314**（t = 4.94） |
| 排位赛后 | 0.6355 〔发车格 + 排位秒差〕 | **0.6543** | **+0.0188**（t = 4.16） |
| 对照库里最强的零拟合基线（平均完赛名次·仅完赛，0.5849） | | | **+0.0234** |

配对 t 检验（最笨基线口径）：赛前 **t = 5.34**、赛后 **t = 4.93**，**8/8** 个赛季为正 —— 增益不是某一年的运气。
真实前 10 名口径：**0.7230 → 0.7690**。

**赛中逐圈预测**：用干净圈节奏外推剩余圈数（gain = 0.25）。两个进度窗口方向一致都为正 ——
10%–50% 区间 Δρ = **+0.0179**（t = **+6.45**）；25%–75% 区间 Δρ = **+0.0125**（t = **+7.57**），均 8/8 年为正。
⚠️ 检验单位是 **172 场**，不是 6 万个圈：每场的逐圈 Δ 先平均成一个点，且相邻圈的窗口重叠 4/5，
有效样本量是**场**。

> **结论强度：留出验证已做**（`python -m scripts.holdout_eval --loso`，落档 `docs/留出集验证.md`）。
> 超参只在**看不见的年份**上重选（每折 75 组：Elo `k`×`dnf_policy` 18、罚退收缩 `α`×`min_pen` 15、
> 赛前/赛后融合权重各 21），再在被锁起来的年份上评估：
>
> | 协议 | 赛前 Δρ（t） | 赛后 Δρ（t） |
> |---|---:|---:|
> | 前向滚动 OOF（n = 114，**唯一无泄漏**） | **+0.0354**（3.71） | **+0.0248**（3.73） |
> | 主切分：2018–2022 选 → 2023–2025 评（n = 70） | **+0.0314**（2.66） | +0.0169（**1.998**，未过 \|t\|>2） |
>
> **结论成立但有条件**：留出增益全为正，跨 5 个赛季 **5/5** 为正 —— 不是灾难性过拟合。
> **两个严格前瞻协议共 4 个预注册门槛，过 3 个**（留一赛季那两条已标注非前瞻，不计入）。
> 没过的是主切分赛后那条：t = **1.998**，门槛是严格 `|t| > 2`，**差 0.002 也是没过**；
> 最硬的前向滚动两个口径都过（3.71 / 3.73）。
> 但要扣掉乐观量：**同一批 test 场上「样本内」口径是 +0.0400 / +0.0202，比留出高
> 0.0086 / 0.0033（21% / 16%）**。所以正文那两行 **t = 4.94 / 4.16 是样本内口径**、
> 应读作偏乐观；上表才是已经扣掉"从 75 组里挑最好"这件事的留出结果。
> 另有两条不能外推的选点：罚退收缩 `α` 与 Elo `k` 在各折间不稳定（`α` 取遍 0.5/0.75/1），
> 所以 `α = 0.75` 只能说"一组效果相近的取值之一"，不是"调出来的最优值"。
> 唯一被 8/8 折一致选中的是 `dnf_policy = finishers_only`。
>
> ⚠️ **逐圈那组也已单独做过同样的留出验证**（`scripts/holdout_eval.py` 的思路套到
> `gain` 上，两个进度窗口 × 主切分 + 前向滚动，四个口径全过门槛）：
> 10–50% 窗口 主切分 **+0.0152**（t=3.03）/ 前向滚动 **+0.0168**（t=4.05）；
> 25–75% 窗口 主切分 **+0.0112**（t=3.85）/ 前向滚动 **+0.0114**（t=4.64）。
> 乐观量比横截面更小（15% / 10%），`gain=0.25` 也确认是**内点解**而非网格边界。
> **仍未覆盖的是 `window`（固定为 5，没扫过）** —— 那一维没有留出证据。
> 产出这组数字的脚本现在是 `python -m scripts.verify_claims --lap`。

### ρ 是什么，为什么不用「准确率」

ρ（Spearman 秩相关系数）问的是：**按预测排一队、按真实排一队，两个队列有多像？**

不用"准确率"，因为它必须先定一个阈值（猜中冠军算对？±2 位算对？），换个阈值数字就换一副面孔；而 ρ 用满全部名次，且只看顺序、不看差值幅度。

诚实边界也在这里：ρ 从 0.6204 提到 0.6543 在统计上显著（t = 4.93），
但**平均名次误差只从 3.51 位降到 3.36 位**。所以对外只能说"大致顺序更准了"，不能说"排得准了"。

**两个 ρ 口径，以及为什么主指标选的是更严的那个。** 模型层有一条明确主张：
退赛者的 `position` 是按行驶距离分配的**分类名次**，把它算进相关性里等于"把运气差当速度慢"。
如果照这条主张走，主指标该用 `rho_fin`（只比完赛者）。我们却用 `rho_all`（全部人）。
这不是在挑好看的指标 —— **恰恰相反，`rho_all` 是更严的那个**：

| 对照 | Δρ_all（t） | Δρ_fin（t） |
|---|---:|---:|
| 赛前 best_pre vs 同复杂度 | +0.0314（4.94） | **+0.0372**（6.11） |
| 赛后 best_post vs 同复杂度 | +0.0188（4.16） | **+0.0307**（5.20） |
| 赛后 best_post vs 纯发车格 | +0.0339（4.93） | **+0.0512**（7.32） |

原因是退赛会让**基线**掉得比模型更多。所以用 `rho_all` 报出来的增益是**悲观**的那一版；
两个口径都列在 `scripts/verify_claims.py` 里，谁都能自己验。（审查报告 L3。）

### 同样重要的是：被证伪的东西

| 尝试 | 结果 |
|---|---|
| 退赛预测（两个模型 + 特征工程） | AUC **0.5351**（随机 = 0.500）—— 退赛基本不可预测 |
| 「风险最高 3 人」命中率 | 15.8% vs 基准 14.9% |
| 圈速中位数作为特征 | 无增量（t = 0.38） |
| 进站补偿修正 | 概念错误：「已付过的成本」不等于「优势」 |

**⚠️ 这条不在上表里，因为它不是「被证伪」，是「测不出来」：**

| 尝试 | 结果 | 为什么不算证伪 |
|---|---|---|
| 融合权重微调（Elo 0.3 → 0.4） | t = 1.44 | 方向**是正的**（+0.0034），而 n=173 下这个检验的最小可检测效应约 **0.008** —— **大于它想检测的效应**。功效不足的检验什么都没证明，不该进上面那张表 |

（审查报告 L1。原表把这行列进"被证伪清单"，是把"证据不足"当成了"被证伪"。
顺带记录另一处内部不一致：`best_post` 用的是 Elo 权重 0.3，而权重扫描显示 0.4 更好 ——
但 +0.0028 的差距配上 t=1.30，同样够不着门槛，所以**没有**改生产权重。）

最有说服力的是一个反例：把退赛者排除出评分更新（`finishers_only`）**这一个开关**，
收益 **+0.0245（t = 3.99）**，大于整个 DNF 模型的全部努力。原因不难理解 ——
退赛多由爆胎、被撞、机械故障造成，把这种随机性灌进本该衡量速度的评分里只会让它变差。

### 2026 新规年：一个真实发现

同一套权重，两个时代结论相反：

| 排位赛前 ρ | 2018–2025 | 2026 |
|---|---:|---:|
| 含 Elo | **0.6082** ✅ | 0.6318 |
| 去 Elo（仅积分榜 + 练习赛） | 0.5768 | **0.6495** ✅ |

Elo 单独在 2026 猜中冠军只有 **11.8%**（历史 54.3%），冠军平均被排到 **4.53 位**（历史 2.37 位）。
口径是"**全历史累积后切 2026**"；只喂 2026 那 17 场则是 35.3% / 3.59 —— 两个口径差很远，引用时必须说明。

⚠️ **这一条是探索性发现，不是结论**：Δρ = +0.0177 的配对检验 **t = +1.10（n = 17）**，
按本项目自己对内使用的 |t| > 2 门槛**不成立**。要等 2027 赛季才能验证。

原因：Elo 天然携带 2025 及以前的赛车能力，而 2026 换了动力单元与主动空力、车队顺序被打乱，
k = 192 的衰减速度需要好几站才能把旧信息冲掉 —— 17 站显然不够。

**另外，"2026 的 ρ 更高"也不是混杂造成的。** 2026 退赛率 20.9%，落在历史最差那一档，
而主指标 `rho_all` 与退赛率**负相关**（−0.565，退赛越多 ρ 越低）。按退赛率匹配后 2026 仍更高：
同档历史场次（n=59）rho_all 0.4929 / rho_fin 0.6996；2026 则是 0.6468 / 0.8146。
所以数字站得住 —— 但也**不能**由此推出"2026 超车更难、比赛更巡航化"，那仍然只是一个未证实的假说。

这不是坏消息。它把一个模糊的直觉（"新规让格局变了"）变成了一个**可测的数字**。

### 数据

| | |
|---|---|
| 赛季 | 2018–2026（9 季） |
| 分站 | 190 = **173**（2018–2025）+ **17**（2026） |
| 圈速记录 | 208,108 = 188,487 + 19,621 |
| 赛道（含几何与进站损失） | 31 |
| 车手 / 车队 | 44 / 19 个队名（= **11 支物理车队**，改名已归并） |
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

### 测试

```bash
pip install -r requirements-dev.txt
pytest                     # 129 项，约 5 秒
```

测试**不需要数据库、也不联网**（内存 SQLite 夹具），跑的全是已经踩过的坑：
完赛/退赛语义的两套实现必须逐字一致、最快圈积分规则按年份、车队血缘分并、
回测框架的防泄漏结构、AI 查询守卫的真值表（含 CTE 与 `load_extension`）、
入库完整性判据、**留出验证的预注册判据本身**（`tests/test_holdout.py`
把 `Δρ>0 / t>2 / 正向年份≥半数` 钉死 —— 事后放松判据会直接测试失败）、
**仪表板的 SQL 卫生**（`tests/test_dashboard_sql.py` 静态扫描：任何把变量拼进
SQL 值的写法都会红，除非显式加进白名单并写明理由）、导出层的
`<script>` 转义与 `times()` 缓存语义，以及**核验入口自身的机制**
（`tests/test_verify_claims.py`：把 README 改一个数字，核验必须跟着变红 ——
防的是"尺子把文档值抄成常量、于是永远报全绿"这种假绿）。
CI 在 `.github/workflows/ci.yml`。

**另有一条"自己验"的入口**，与测试互补 —— 测试管"别退回去"，这条管"数字是真的"：

```bash
python -m scripts.verify_claims          # 文档值现场解析 README，逐条判 ✅/❌，约 5 秒
python -m scripts.verify_claims --lap    # 含逐圈 Δρ（多约 80 秒）
```

它**不保存任何文档值**：54 条断言里的每一条，文档值都由 55 条锚点正则**现场从
`README.md` 解析**。锚点找不到或命中多处都判失败；容差自动取"文档写出的那一位的一半"，
所以没有能人为放宽的旋钮 —— README 漂了它就会红。

### 项目结构

```
src/
  semantics.py      完赛/退赛语义的唯一定义 —— eval / etl / model 所有判定都走这里
  etl/              取数与建库（FastF1 -> SQLite），含赛道维表与积分规则
  model/            预测层：回测框架 / 预测器库 / 逐圈分析 / 脏圈识别 / 车队身份
  dashboard/        Streamlit 界面，六个页面
scripts/            回测、导入、评估、演示等命令行工具
                    verify_claims.py  —— 核验入口：文档值现场解析 README，逐条判 ✅/❌（自己验）
                    holdout_eval.py   —— 留出验证：选参与评估分离
tests/              回归测试（不需要数据库）
docs/               评估报告、对标分析、审查报告、留出验证记录与回放动画指南
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
- **2026 新规年的结论还不够硬** —— 去 Elo 更好只领先 0.0177，配对检验 t = 1.10（17 场），
  按本项目自己的 |t|>2 门槛不成立；要等 2027 赛季验证
- **后段（真实第 16–20 名）误差约为前段的 3 倍** —— 这正是对外应看前 10 口径的原因
- **「车手分 + 车队分」不能当解释用** —— 一队两台车，车手与赛车的贡献**无法分离**。
  分成比例 `driver_share` 对预测几乎无影响（实测 0.5→0.9，ρ 跨度仅 0.0035），
  它决定的是**哪张表更忠实**（零和的）。车队分是**相对车手的残差**：车手分越高，
  同样的成绩越会被算作「车不行」。2026 的 Williams 就是这个形状 —— 两台车都被评成
  好车手，车队分被压到垫底，尽管它的平均完赛名次好于 Aston Martin 和 Cadillac
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

Mean **Spearman ρ** over the **173 races of 2018–2025** (not 190 — 190 is those plus the 17 of
2026; mixing the two shifts ρ by ~0.003). Every number below is produced by
`python -m scripts.readme_numbers`.

**The gain depends on the denominator**, so here are both tables:

| Prediction point | Naive baseline | This project | Gain |
|---|---:|---:|---:|
| Pre-qualifying (grid unknown) | 0.5501 〔championship standings〕 | **0.6082** | +0.0582 |
| Post-qualifying (grid known) | 0.6204 〔grid order〕 | **0.6543** | +0.0339 |

But neither of those is the strongest zero-fit baseline available from the same signals —
using only the dumbest one roughly doubles the apparent gain. **The comparison I stand
behind is against same-complexity baselines:**

| Prediction point | Same-complexity baseline (zero-fit) | This project | **Gain** |
|---|---:|---:|---:|
| Pre-qualifying | 0.5768 〔standings + practice〕 | **0.6082** | **+0.0314** (t = 4.94) |
| Post-qualifying | 0.6355 〔grid + quali gap〕 | **0.6543** | **+0.0188** (t = 4.16) |
| Against the strongest zero-fit baseline in the repo (avg finish, finishers only, 0.5849) | | | **+0.0234** |

Paired t-test (naive-baseline framing): **t = 5.34** pre-qualifying, **t = 4.93** post-qualifying,
positive in **8/8** seasons — not a one-year fluke. Actual top-10 subset: **0.7230 → 0.7690**.

**In-race lap-by-lap prediction**: projecting remaining laps from clean pace (gain = 0.25).
Both progress windows agree and are positive — Δρ = **+0.0179** over 10%–50%
(t = **+6.45**), and **+0.0125** over 25%–75% (t = **+7.57**), both 8/8 seasons.
⚠️ The unit of the test is **172 races**, not 60,000 laps: each race's lap deltas are averaged
into a single point, and adjacent windows overlap 4/5 — the effective sample size is races.

> **How strong is this claim? Holdout validation has been done**
> (`python -m scripts.holdout_eval --loso`, recorded in `docs/留出集验证.md`).
> Hyperparameters are re-selected on **years the tuner never sees** (75 configs per fold:
> Elo `k`×`dnf_policy` 18, grid-penalty `α`×`min_pen` 15, pre/post blend weights 21 each),
> then evaluated on the locked-away years:
>
> | Protocol | Pre-quali Δρ (t) | Post-quali Δρ (t) |
> |---|---:|---:|
> | Walk-forward OOF (n = 114, **the only leak-free one**) | **+0.0354** (3.71) | **+0.0248** (3.73) |
> | Main split: tune 2018–2022 → test 2023–2025 (n = 70) | **+0.0314** (2.66) | +0.0169 (**1.998**, fails \|t\|>2) |
>
> **The claim holds, with a caveat**: every holdout gain is positive, **5/5** seasons positive —
> not catastrophic overfitting. **Across the two strictly prequential protocols, 3 of the 4
> pre-registered thresholds pass** (the leave-one-season pair is flagged non-prequential and
> not counted). The one that fails is the main-split post-quali cell: t = **1.998** against a
> strict `|t| > 2` — **missing by 0.002 still counts as missing**. Walk-forward, the strongest
> protocol, passes both cells (3.71 / 3.73). But discount the optimism: **on that same test set the in-sample
> number is +0.0400 / +0.0202, i.e. 0.0086 / 0.0033 (21% / 16%) higher.** So the
> **t = 4.94 / 4.16 is the in-sample figure** and should be read as optimistic;
> the table above is what remains after paying for "best of 75 configurations".
> Two knobs cannot be extrapolated: the penalty shrink `α` and Elo `k` are unstable across
> folds (`α` lands on 0.5, 0.75 and 1 in different folds), so `α = 0.75` is "one of a set of
> near-equivalent choices", not "the tuned optimum". The only knob picked unanimously by
> 8/8 folds is `dnf_policy = finishers_only`.
>
> ⚠️ **The lap-by-lap numbers got the same holdout treatment separately** (the
> `scripts/holdout_eval.py` approach applied to `gain`: two progress windows × main split +
> walk-forward — all four pass the bar): 10–50% main split **+0.0152** (t=3.03) /
> walk-forward **+0.0168** (t=4.05); 25–75% main split **+0.0112** (t=3.85) /
> walk-forward **+0.0114** (t=4.64). The optimism is smaller than the cross-sectional
> case (15% / 10%), and `gain=0.25` is confirmed to be an **interior** optimum, not a grid
> boundary. **`window` (fixed at 5) is still unvalidated** — that dimension has no holdout
> evidence. The script producing these numbers is now `python -m scripts.verify_claims --lap`.

### Why ρ, not "accuracy"

ρ (Spearman rank correlation) asks a single question: **line up the predicted order and
the actual order — how similar are the two queues?**

Accuracy is avoided on purpose: it requires choosing a threshold first (is a correct
winner enough? within ±2 places?), and the number changes with the threshold. ρ uses
every position, and cares only about ordering, not magnitude.

The honest boundary sits here too: raising ρ from 0.6204 to 0.6543 is statistically
significant (t = 4.93), but it moves the **mean position error only from 3.51 to 3.36**.
So the correct claim is "the rough order is better" — not "the ordering is accurate".

**Two ρ variants, and why the headline one is the stricter of the two.** The model layer
argues explicitly that a retired driver's `position` is a *classification* placing, and
counting it = "treating bad luck as slow pace". Following that argument literally would mean
using `rho_fin` (finishers only) as the primary metric. We use `rho_all` (everyone) instead.
That is not metric-shopping — **`rho_all` is the stricter one**:

| Comparison | Δρ_all (t) | Δρ_fin (t) |
|---|---:|---:|
| Pre-quali best_pre vs same-complexity | +0.0314 (4.94) | **+0.0372** (6.11) |
| Post-quali best_post vs same-complexity | +0.0188 (4.16) | **+0.0307** (5.20) |
| Post-quali best_post vs plain grid | +0.0339 (4.93) | **+0.0512** (7.32) |

Retirements cost the **baseline** more than the model, so the `rho_all` figure is the
pessimistic version. Both are printed by `scripts/verify_claims.py` — check it yourself.
(Audit item L3.)

### Equally important: what was falsified

| Attempt | Result |
|---|---|
| DNF prediction (two models + feature engineering) | AUC **0.5351** (chance = 0.500) — essentially unpredictable |
| "Top-3 highest risk" hit rate | 15.8% vs 14.9% baseline |
| Median lap time as a feature | No gain (t = 0.38) |
| Pit-stop compensation | Conceptually wrong: a cost already paid is not an advantage |

**⚠️ The next one is deliberately NOT in that table — it was not falsified, it was unmeasurable:**

| Attempt | Result | Why it does not count as falsification |
|---|---|---|
| Blend-weight tuning (Elo 0.3 → 0.4) | t = 1.44 | The direction was **positive** (+0.0034), while at n=173 this test's minimum detectable effect is about **0.008** — **larger than the effect it was trying to detect**. An underpowered test proves nothing and does not belong in the table above |

(Audit item L1. The original table called this "falsified"; that conflates "insufficient
evidence" with "disproved". Related inconsistency, recorded for the record: `best_post`
uses an Elo weight of 0.3 while the weight sweep prefers 0.4 — but that +0.0028 gap comes
with t=1.30, equally below the bar, so the production weight was **not** changed.)

The most instructive result is a counter-example: simply excluding retired drivers from
rating updates (`finishers_only`) — **one switch** — gains **+0.0245 (t = 3.99)**,
more than the entire DNF model effort. Retirements are mostly punctures, collisions and
mechanical failures; feeding that randomness into a rating meant to measure pace only
makes it worse.

### 2026: a regulation-change finding

Same weights, opposite conclusions in two eras:

| Pre-qualifying ρ | 2018–2025 | 2026 |
|---|---:|---:|
| With Elo | **0.6082** ✅ | 0.6318 |
| Without Elo (standings + practice only) | 0.5768 | **0.6495** ✅ |

Elo alone picks the winner in only **11.8%** of 2026 races (54.3% historically), and places
the eventual winner at an average of **4.53** (2.37 historically). That figure uses the
"accumulate all history, then slice 2026" convention; feeding it only the 17 races of 2026
gives 35.3% / 3.59 — the two conventions differ a lot and must be labelled.

⚠️ **This is an exploratory finding, not a conclusion**: the paired test on Δρ = +0.0177 gives
**t = +1.10 (n = 17)**, which fails the project's own |t| > 2 bar. It needs the 2027 season.

Reason: Elo carries car performance from 2025 and earlier, while 2026 brought new power units and
active aerodynamics that reshuffled the running order — and at k = 192, Elo needs several races to
flush out stale information. Seventeen is not enough.

**Nor is "2026 has a higher ρ" an artefact of its DNF rate.** 2026 retired 20.9% of entries — the
worst historical band — and the headline metric `rho_all` is *negatively* correlated with the
retirement rate (−0.565: more retirements, lower ρ). Matched on that rate, 2026 is still higher:
historical races in the same band (n=59) average rho_all 0.4929 / rho_fin 0.6996, versus
2026's 0.6468 / 0.8146. The number holds up — but that still does **not** license the claim that
"overtaking got harder"; that remains an untested hypothesis.

This is good news, not bad. It turns a vague intuition ("the new rules changed the order")
into a **measurable number**.

### Data

| | |
|---|---|
| Seasons | 2018–2026 (9) |
| Grands Prix | 190 = **173** (2018–2025) + **17** (2026) |
| Lap records | 208,108 = 188,487 + 19,621 |
| Circuits (with geometry + pit loss) | 31 |
| Drivers / Teams | 44 / 19 team names (= **11 physical teams**; renames merged) |
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

### Tests

```bash
pip install -r requirements-dev.txt
pytest                     # 129 tests, ~5 seconds
```

The tests need **no database and no network** (in-memory SQLite fixtures). They cover the
mistakes that have already bitten this project: the two implementations of finish/DNF semantics
must agree exactly, the fastest-lap points rule by season, team-lineage collapsing, the
backtest framework's structural leakage guards, the AI SQL guard's truth table (including CTEs
and `load_extension`), the ingestion completeness criteria, **the holdout validation's
pre-registered criteria themselves** (`tests/test_holdout.py` pins `Δρ>0 / t>2 / majority of
positive years` — loosening them after the fact fails the build), **dashboard SQL hygiene**
(`tests/test_dashboard_sql.py` statically scans for any variable interpolated into SQL; it fails
unless the name is explicitly whitelisted with a reason), the export layer's `<script>`
escaping and `times()` cache semantics, and **the verifier's own mechanism**
(`tests/test_verify_claims.py`: change one number in the README and the verification must go
red — the failure mode being guarded against is a ruler that copies the documented values into
constants and therefore reports all-green forever).
CI lives in `.github/workflows/ci.yml`.

**There is also a "verify it yourself" entry point**, complementary to the tests — the tests
guard against regressions, this one checks that the numbers are real:

```bash
python -m scripts.verify_claims          # doc values parsed live from README, ✅/❌, ~5s
python -m scripts.verify_claims --lap    # includes lap-by-lap Δρ (+80s)
```

It **stores no documented value of its own**: for each of the 54 assertions the expected number
is parsed **live out of `README.md`** via 55 anchor regexes. A missing or ambiguous anchor is a
failure; the tolerance is derived from the precision the README itself writes (half of the last
digit), so there is no knob to widen it — if the README drifts, this goes red.

### Layout

```
src/
  semantics.py      single source of truth for finished/DNF semantics — used by every layer
  etl/              ingestion (FastF1 -> SQLite), incl. circuit dimension table & points rules
  model/            prediction layer: backtest framework / predictors / lap analysis / dirty-lap detection / team identity
  dashboard/        Streamlit UI, six pages
scripts/            backtest, ingest, evaluation and demo CLIs
                    verify_claims.py  — verification entry: doc values parsed live from README
                    holdout_eval.py   — holdout validation: tuning split from evaluation
tests/              regression tests (no database needed)
docs/               evaluation reports, benchmarks, audit report, holdout record and replay guide
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
- **The 2026 finding is not yet conclusive** — dropping Elo wins by only 0.0177, paired test
  t = 1.10 over 17 races, which fails the project's own |t| > 2 bar; it needs the 2027 season
- **The back of the field (actual P16–P20) has ~3× the error of the front** — the reason the
  top-10 view is the one worth quoting
- **"Driver rating + team rating" is not an explanation** — with two cars per team, driver and
  car contributions are **not separately identifiable**. The split (`driver_share`) barely moves
  prediction (0.5→0.9 spans just 0.0035 of ρ) — what it decides is **which table stays faithful**,
  and that trade is zero-sum. The team rating is a **residual against its drivers**: the higher a
  driver is rated, the more the same result gets blamed on the car. Williams in 2026 is exactly
  this shape — both its drivers rate well, so the team rating sinks to last even though its
  average finish beats Aston Martin's and Cadillac's
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
