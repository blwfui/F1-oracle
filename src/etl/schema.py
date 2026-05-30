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
"""
