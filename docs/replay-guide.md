# 逐圈回放动画 · 生成与本地化指南

**中文** ｜ [English](#english)

> 想让人自己生成、或者把它换成自己的赛季／赛道／语言，看这一篇就够。
> 代码里的推导与踩过的坑写在 `scripts/export_replay.py` 的注释里。

---

## 中文

### 它是什么

`scripts/export_replay.py` 把**任意一场比赛**导出成**一个自包含的 HTML 文件**：

- 赛道俯视图 + 每台车逐圈移动（位置由秒差反推）
- 右侧**实时排行榜**（名次、与前车、与领跑，随播放平滑变化）
- **进站动画**：拐进维修区 → 滑到自己的车位 → 换胎闪光（黄环 + 车位格描金）
- 红旗 / 安全车 / 虚拟安全车徽标，主动空力区段、超车模式检测点

约 200 KB，数据全部内联，**不需要服务器、不需要联网、没有任何依赖** —— 双击就能放。

> **仓库里不含生成物。** `outputs/` 已被 `.gitignore` 排除。想看得自己跑一遍，五分钟。

### 一、生成

#### 0) 前置：先把数据库建起来

回放**只读 SQLite**，运行时**不联网**。

```bash
python -m venv .venv
.venv/Scripts/activate                 # Windows；macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python -m src.etl.ingest               # 建库 + 导入 2018–2025（首次较慢，之后走缓存）
python -m scripts.import_season 2026   # 可选：增量补后续赛季（可断点续跑）
```

数据库不入库，必须自己建一次。

#### 1) 一场比赛 = 一条命令

```bash
python -m scripts.export_replay 2023 3              # 2023 年第 3 站（澳大利亚）
python -m scripts.export_replay 2024 16 -o monza.html
```

| 参数 | 含义 |
|---|---|
| `year` | 赛季年份 |
| `round` | **轮次**（不是赛道名）。库里的 `events.round` |
| `-o / --out` | 输出路径；默认 `outputs/replay_<year>_R<round>.html` |

跑完直接双击那个 HTML。播放控制条上的 `−` / `+` 是速度倍率（`×1` = 按比赛真实用时）。

#### 2) 想要进站动画？先抽维修区几何

维修区**不在**默认数据里 —— FastF1 不提供。它得从**实跑遥测**里抽，需要联网下**一次**该站遥测
（下完进 `data/cache`，同一站只会下一次，约几十秒）：

```bash
python -m scripts.fetch_pit_lane 2023 3            # 先干跑：只诊断 + 出校验图，不写库
python -m scripts.fetch_pit_lane 2023 3 --commit   # 确认无误后写入 circuits.pit_lane_json
```

**怎么判断抽对了**（校验图会画出来）：

- 进站口与出站口分别落在起终点线**两侧**（墨尔本：0.9523 / 0.0045）
- 维修区折线**平行主直道**，离赛道十几米（墨尔本：14.6 m）
- 形状是一条干净的横向折线，没有跨赛道的乱线

**不抽会怎样？** 回放照常生成，只是没有维修区图层 —— 进站车直接按赛道位置走，没有拐进维修区的动画。
（`pit_lane_json` 为空时 `build()` 会返回 `pitlane: None`，前端全部按「没有维修区」降级。）

### 二、替换它（本地化 / 换成你自己的东西）

#### 换场次、换赛季

回放与赛季无关，给它任意 `year round` 即可，前提是那一站已经入库：

```bash
python -m scripts.import_season 2019
python -m scripts.export_replay 2019 5
```

#### 换赛道几何

几何存在 `circuits.outline_json`，来源是 `fastf1.mvapi.get_circuit_info()`
（MultiViewer 公开 API，一个小 JSON，**不需要下遥测**）：

```bash
python -m src.etl.circuits             # 建 / 补全部赛道
python -m src.etl.circuits --no-geo    # 只建身份映射，跳过网络
```

同一物理赛道有多种写法（`Monaco` / `Monte Carlo`、`Miami` / `Miami Gardens`），
由 `circuit_aliases` 表收敛。**如果回放报「找不到 xxx 的赛道几何」**，
去 `circuit_aliases` 加一条 `location → circuit_id` 就行，不用改代码。

#### 换配色、车手名、界面文案

| 想改什么 | 改哪里 |
|---|---|
| 车队配色 | `scripts/export_replay.py` 顶部 `TEAM_COLORS`（键是车队英文名，值 `#RRGGBB`；找不到的走 `FALLBACK_COLOR`） |
| 车手名字 | `src/dashboard/names_cn.py` —— `LAST_NAME_CN` 字典 + `auto_cn_short()` |
| **界面全部文案** | `scripts/export_replay.py` 里的 `TEMPLATE`（HTML + CSS + JS 都在这一块），如 `进站` / `红旗` / `领先` / `与前车` |
| 页面标题格式 | `scripts/export_replay.py` 的 `main()` —— `title` / `subtitle` 两行 |

**换成别的语言**：只改后两行就行。**数据层完全不用动** —— 数据库里存的是
`VER` / `Mercedes` / `Monza` 这类英文原名，中文只活在展示层。

#### 想让维修区更真

车库格目前是**按车队等距铺开**的示意位（2023 R3 三面红旗，正常进站样本太少，真实停车点不够铺满）。
要更真：在**没有红旗**的站多抽几位车手，把真实停车点合并进 `fetch_pit_lane.py`。
**维修区走线本身是真实的**，只有车库格编号是排出来的。

### 三、改代码之前，先读这三条铁律

回放的位置**不是真实轨迹**，是用秒差反推的：`位置 = (1 − 落后秒数 ÷ 本圈基准圈速) mod 1`。
所以：

1. **位置、名次、秒差必须同一套口径。** 谁在哪、排第几、差几秒，全部由同一个进度量 `prog` 导出。
   一旦出现「榜上说 P17、画面上还在前面」，就是两套口径打架 —— 而不是某一处「算错了」。
2. **进站／出站丢的时间，只能体现在维修区那一段。** 赛道段一律用**全场基准速率**
   （该圈非进站车速率的**中位数**）。拿车手自己含进站损失的秒差当速度，等于把那十几秒
   平摊到整圈 —— 他还没开到进站口就先慢 20%，被后车在赛道上白超。**这个坑踩过。**
3. **拐点、段长要用几何解出来，不能拍固定比例。** 进站拐点 = 车**真的开到进站口**的时刻；
   出站段长 = 走完「出站口→本圈终点」所需的时间。拍 `0.8` / 拍 `0.15` 都翻过车
   （车会倒着开、或者斜着横切出赛道）。

另有一条数据侧的：**任何字段当权威判据之前，先确认它在目标数据里非空**。
（2026 赛季的 `results.laps_completed` 整列是 NULL，拿它当过滤条件会把全场滤光。）

### 四、改完怎么验（两分钟，不用装任何东西）

**数值验证**：复刻 `prog` 公式，检查两件事 ——

- 每一圈**帧末的实时顺序 == 该圈官方名次**（2023 R3 应是 58/58，2026 R1 56/58，
  差的那两处是 FastF1 名次与累计时间口径的相邻互换）
- 进站车在赛道段**单调前进**，且**抵达进站口之前不被反超**（反超必须发生在维修区里）

**画面验证**：用无头浏览器截图，HTML 自带 URL 参数，不用改代码：

```bash
# ?lap=36 跳到第 36 圈；?paused=1 跳过开场遮罩、不自动播
msedge --headless=new --disable-gpu --window-size=1500,1150 --virtual-time-budget=6000 \
  --screenshot=shot.png "file:///F:/F1_Commentary/outputs/replay_2023_R03.html?lap=36&paused=1"
```

（Windows 上 `msedge` 完整路径通常是
`/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`。
想定格在**圈中**某一刻，把 `render(cur, 0)` 的第二个参数改成 `0.5` 即可。）

---

## English

### What it is

`scripts/export_replay.py` turns **any race** into **a single self-contained HTML file**:

- top-down circuit view with every car moving lap by lap (positions are *derived* from gaps)
- a **live timing tower** on the right (position / gap to car ahead / gap to leader, updating
  smoothly as it plays)
- a **pit-stop animation**: peel into the pit lane → roll to your own box → tyre-change flash
- red-flag / safety-car / VSC badges, active-aero zones and overtake-mode detection points

Roughly 200 KB, all data inlined — **no server, no network, no dependencies**. Double-click it.

> **Generated files are not in the repo.** `outputs/` is git-ignored. Build your own in five minutes.

### 1. Generating

#### 0) Prerequisite: build the database

The replay only **reads** SQLite; it never touches the network at runtime.

```bash
python -m venv .venv
.venv/Scripts/activate                 # Windows; macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python -m src.etl.ingest               # create DB + ingest 2018–2025 (slow first time)
python -m scripts.import_season 2026   # optional: add a later season (resumable)
```

The database is not committed — you must build it once.

#### 1) One race = one command

```bash
python -m scripts.export_replay 2023 3              # 2023, round 3 (Australia)
python -m scripts.export_replay 2024 16 -o monza.html
```

| Argument | Meaning |
|---|---|
| `year` | season |
| `round` | **round number** (not a circuit name) — `events.round` in the DB |
| `-o / --out` | output path; defaults to `outputs/replay_<year>_R<round>.html` |

Open the HTML directly. The `−` / `+` buttons on the control bar step the speed multiplier
(`×1` = the race's real elapsed time).

#### 2) Want the pit animation? Extract the pit lane first

The pit lane is **not** in the default data — FastF1 does not provide it. It is extracted from
**real telemetry**, which means downloading that race's telemetry **once**
(it lands in `data/cache`; one download per race, tens of seconds):

```bash
python -m scripts.fetch_pit_lane 2023 3            # dry run: diagnostics + a check image only
python -m scripts.fetch_pit_lane 2023 3 --commit   # write circuits.pit_lane_json
```

**How to tell it worked** (the script draws a check image):

- pit entry and pit exit land on **opposite sides of the start/finish line**
  (Melbourne: 0.9523 / 0.0045)
- the pit-lane polyline runs **parallel to the main straight**, a dozen metres off it
  (Melbourne: 14.6 m)
- it is a clean lateral polyline — no lines cutting across the circuit

**If you skip it:** the replay still generates, just without the pit-lane layer — cars simply
keep running on track. (`pit_lane_json` empty → `build()` returns `pitlane: None` and the whole
front end degrades to "no pit lane".)

### 2. Swapping things out (localization / making it yours)

#### Another race, another season

The exporter is season-agnostic — hand it any `year round`, as long as that race is ingested:

```bash
python -m scripts.import_season 2019
python -m scripts.export_replay 2019 5
```

#### Another circuit's geometry

Geometry lives in `circuits.outline_json`, sourced from `fastf1.mvapi.get_circuit_info()`
(MultiViewer's public API — one small JSON, **no telemetry download**):

```bash
python -m src.etl.circuits             # build / top up every circuit
python -m src.etl.circuits --no-geo    # identity + stats only, skip the network
```

One physical circuit has many spellings (`Monaco` / `Monte Carlo`, `Miami` / `Miami Gardens`);
the `circuit_aliases` table collapses them. **If the exporter says
"找不到 xxx 的赛道几何" (no geometry found for xxx)**, add one `location → circuit_id` row to
`circuit_aliases` — no code change needed.

#### Colours, driver names, UI copy

| What | Where |
|---|---|
| Team colours | `TEAM_COLORS` at the top of `scripts/export_replay.py` (English team name → `#RRGGBB`; unknown teams fall back to `FALLBACK_COLOR`) |
| Driver names | `src/dashboard/names_cn.py` — the `LAST_NAME_CN` dict + `auto_cn_short()` |
| **All UI copy** | the `TEMPLATE` block in `scripts/export_replay.py` (HTML + CSS + JS all live there) — e.g. `进站` / `红旗` / `领先` / `与前车` |
| Page title format | `main()` in `scripts/export_replay.py` — the `title` / `subtitle` lines |

**To use another language**, only the last two rows need touching. **The data layer never
changes** — the database stores English originals (`VER` / `Mercedes` / `Monza`) and every
translated string lives in the presentation layer.

#### Making the pit lane more faithful

The garage boxes are currently **evenly spaced placeholders per team** (at 2023 R3 there were
three red flags, so normal pit-stop samples were too few to fill the row). For more fidelity,
extract several drivers at a red-flag-free race and merge their real stopping points into
`fetch_pit_lane.py`. **The pit-lane path itself is real** — only the box numbering is laid out.

### 3. Before you change the code: three ground rules

Replay positions are **not** a real trajectory — they are back-derived from time gaps:
`position = (1 − gap ÷ lap reference time) mod 1`. Hence:

1. **Position, rank and gap must share one source of truth.** Where a car is, which place it
   holds and how far behind it is all come from one progress scalar, `prog`. The moment you see
   "the tower says P17 but it's clearly ahead on the map", that is two competing definitions —
   not one place being "computed wrong".
2. **Time lost in the pits may only show up in the pit-lane segment.** On-track segments always
   use the **field reference rate** (the median rate of the cars *not* pitting that lap). Feed a
   driver's own gap — which already contains the pit loss — into its on-track speed and you
   smear those ~17 seconds across the whole lap: it decelerates 20% before it ever reaches pit
   entry and gets passed on track for free. **We've been bitten by this one.**
3. **Solve the corner and segment lengths geometrically; never hard-code a fraction.** Pit entry
   is *the moment the car actually reaches pit entry*; the out-lap segment is *the time needed to
   cover "pit exit → end of lap"*. Hard-coding `0.8` or `0.15` has burned us twice — cars drive
   backwards, or cut diagonally off the circuit.

And one from the data side: **before treating a field as authoritative, confirm it is non-null
in the target data.** (In the 2026 season `results.laps_completed` is entirely NULL — filtering
on it wipes out the whole field.)

### 4. Verifying a change (two minutes, zero installs)

**Numerically**, reproduce the `prog` formula and check two things:

- the **live order at each lap boundary equals that lap's official classification**
  (2023 R3 should be 58/58; 2026 R1 56/58 — the two misses are adjacent swaps between FastF1's
  timing-loop position and the cumulative-time convention)
- a pitting car moves **monotonically** along the track and is **not passed before it reaches
  pit entry** (the pass must happen inside the pit lane)

**Visually**, screenshot with a headless browser — the HTML ships the URL parameters, so no code
edits are needed:

```bash
# ?lap=36 jumps to lap 36; ?paused=1 skips the intro overlay and does not auto-play
msedge --headless=new --disable-gpu --window-size=1500,1150 --virtual-time-budget=6000 \
  --screenshot=shot.png "file:///F:/F1_Commentary/outputs/replay_2023_R03.html?lap=36&paused=1"
```

(On Windows the full path is usually
`/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe`.
To freeze *mid*-lap, change the second argument of `render(cur, 0)` to `0.5`.)
