"""SQLite schema for F1 data warehouse — Route A."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS events (
    year       INTEGER NOT NULL,
    round      INTEGER NOT NULL,
    event_name TEXT,
    country    TEXT,
    location   TEXT,
    event_date TEXT,
    PRIMARY KEY (year, round)
);

CREATE TABLE IF NOT EXISTS results (
    year           INTEGER NOT NULL,
    round          INTEGER NOT NULL,
    driver         TEXT    NOT NULL,
    full_name      TEXT,
    team           TEXT,
    position       INTEGER,
    grid           INTEGER,
    points         REAL,
    status         TEXT,
    laps_completed INTEGER,
    race_time_sec  REAL,
    q1_sec         REAL,
    q2_sec         REAL,
    q3_sec         REAL,
    quali_pos      INTEGER,
    PRIMARY KEY (year, round, driver)
);

CREATE TABLE IF NOT EXISTS laps (
    year        INTEGER NOT NULL,
    round       INTEGER NOT NULL,
    driver      TEXT    NOT NULL,
    lap_number  INTEGER NOT NULL,
    position    INTEGER,
    lap_time    REAL,
    sector1     REAL,
    sector2     REAL,
    sector3     REAL,
    compound    TEXT,
    tyre_life   INTEGER,
    stint       INTEGER,
    is_pit      INTEGER,
    is_best     INTEGER,
    speed_fl    REAL,
    -- 时间轴：来自 FastF1 laps（非遥测，抓取成本低）
    -- time_sec      该圈完成时刻的【会话累计时间】（秒）。含义：从 session 开始算起，
    --               含赛前等待（约 1 小时），故绝对值无意义；但同场所有车手共享同一
    --               起点，所以 gap = 同圈两人 time_sec 之差 即为真实秒差。
    -- lap_start_sec 该圈开始时刻（秒，同为会话累计）。与 LapTime 相加应等于 time_sec。
    time_sec       REAL,
    lap_start_sec  REAL,
    -- 赛道状态标志位组合串（FastF1 TrackStatus）：
    --   1=绿旗 2=黄旗 3=黄旗(双黄?) 4=安全车 5=红旗 6=虚拟安全车 7=VSC结束
    --   多标志会连写，如 "12" = 绿旗+黄旗。用于识别安全车/黄旗窗口。
    track_status   TEXT,
    PRIMARY KEY (year, round, driver, lap_number)
);

CREATE TABLE IF NOT EXISTS weather (
    year           INTEGER NOT NULL,
    round          INTEGER NOT NULL,
    air_temp_avg   REAL,
    track_temp_avg REAL,
    humidity_avg   REAL,
    pressure_avg   REAL,
    had_rain       INTEGER,
    wind_speed_max REAL,
    PRIMARY KEY (year, round)
);

CREATE INDEX IF NOT EXISTS idx_results_driver ON results(driver);
CREATE INDEX IF NOT EXISTS idx_results_team   ON results(team);
CREATE INDEX IF NOT EXISTS idx_laps_driver    ON laps(driver);
CREATE INDEX IF NOT EXISTS idx_events_country ON events(country);

CREATE TABLE IF NOT EXISTS driver_names (
    driver         TEXT PRIMARY KEY,
    full_name      TEXT,
    first_seen_year INTEGER
);

CREATE TABLE IF NOT EXISTS sessions (
    year         INTEGER NOT NULL,
    round        INTEGER NOT NULL,
    driver       TEXT    NOT NULL,
    session_type TEXT    NOT NULL,
    best_lap_sec REAL,
    laps_count   INTEGER,
    position     INTEGER,
    PRIMARY KEY (year, round, driver, session_type)
);

CREATE TABLE IF NOT EXISTS sprint_points (
    year     INTEGER NOT NULL,
    round    INTEGER NOT NULL,
    driver   TEXT    NOT NULL,
    position INTEGER,
    points   REAL,
    sq_pos   INTEGER,
    PRIMARY KEY (year, round, driver)
);

CREATE INDEX IF NOT EXISTS idx_sprint_points_driver ON sprint_points(year, driver);

-- ═══════════════════════════════════════════════════════════
-- circuits — 赛道维表（规范身份 + 静态几何）
-- ═══════════════════════════════════════════════════════════
-- circuit_id 是规范标识，解决 events.location 的"同赛道多名"问题
-- （Monaco/Monte Carlo、Yas Island/Yas Marina、Miami/Miami Gardens、
--   Marina Bay/Singapore 各是同一物理赛道的两种写法）。
--
-- ⚠️ 本表的 races / pole_win_* / move_n / dnf_* / rain_* 是
--    2018-2025 全历史汇总，仅供展示与人工参考。
--    建模时【禁止】直接当作特征使用：预测第 n 站只能看到 round < n 的数据，
--    用全季/全历史聚合会造成数据泄漏（回测虚高、实盘无法复现）。
--    模型特征请用 src/etl/circuits.py 的 circuit_stats_asof() 按轮次过滤重算。
CREATE TABLE IF NOT EXISTS circuits (
    circuit_id     TEXT PRIMARY KEY,
    name           TEXT NOT NULL,
    name_cn        TEXT,
    country        TEXT,
    country_cn     TEXT,
    -- 几何：来自 MultiViewer API（静态事实，无泄漏风险）
    -- 坐标单位 = 0.1 m（分米）。实测 16 条赛道比值 0.10085 ± 0.0005；
    -- 由全轮廓（约 700 点）推算的单圈长度与官方值差 0.1%–2.0%。
    -- outline_json = 完整赛道轮廓，已换算为米，可直接用于绘制赛道图。
    circuit_key    INTEGER,
    geo_year       INTEGER,
    corners        INTEGER,
    hairpins       INTEGER,
    fast_corners   INTEGER,
    rotation       REAL,
    marshal_lights INTEGER,
    track_length_m REAL,
    corner_density REAL,
    -- 进站损失时间（秒），来自 MultiViewer。normal=绿旗 / sc=安全车 / vsc=虚拟安全车。
    -- normal 与 sc 的差值直接量化"安全车期间进站能白赚多少"。
    pit_loss_normal_s REAL,
    pit_loss_sc_s     REAL,
    pit_loss_vsc_s    REAL,
    outline_json   TEXT,
    -- 全历史经验统计（⚠️ 仅供展示，勿作特征）
    races          INTEGER,
    pole_win_n     INTEGER,
    pole_win_d     INTEGER,
    move_n         REAL,
    dnf_n          INTEGER,
    dnf_d          INTEGER,
    rain_n         INTEGER,
    rain_d         INTEGER
);

CREATE TABLE IF NOT EXISTS circuit_aliases (
    location   TEXT PRIMARY KEY,
    circuit_id TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_circuit_aliases_cid ON circuit_aliases(circuit_id);
"""
