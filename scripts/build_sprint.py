"""Build sprint race points for a given F1 season. Usage: python build_sprint.py [year]"""

import sys
import sqlite3
from pathlib import Path

import fastf1

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "f1_oracle.db"
CACHE_DIR = ROOT / "data" / "cache"

fastf1.Cache.enable_cache(str(CACHE_DIR))

SPRINT_PTS = {1: 8, 2: 7, 3: 6, 4: 5, 5: 4, 6: 3, 7: 2, 8: 1}

YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2025

schedule = fastf1.get_event_schedule(YEAR)
sprint_rounds = []
for _, ev in schedule.iterrows():
    rn = int(ev["RoundNumber"])
    if rn <= 0 or ev.get("EventFormat") == "conference":
        continue
    session_names = [str(ev.get(f"Session{i}", "")) for i in range(1, 6)]
    if any(s.strip() == "Sprint" for s in session_names):
        sprint_rounds.append(rn)

if not sprint_rounds:
    print(f"No sprint rounds found for {YEAR}")
    sys.exit(0)

db = sqlite3.connect(str(DB_PATH))
db.execute("DELETE FROM sprint_points WHERE year=?", (YEAR,))

for rn in sprint_rounds:
    try:
        s = fastf1.get_session(YEAR, rn, "S")
        s.load(telemetry=False, laps=True, weather=False, messages=True)
        lp = s.laps
        drivers_with_time = []
        for drv in lp["Driver"].unique():
            dl = lp.pick_driver(drv).dropna(subset=["Position"]).sort_values(
                "LapNumber", ascending=False
            )
            if dl.empty:
                continue
            pos = int(dl.iloc[0]["Position"])
            best = lp.pick_driver(drv).dropna(subset=["LapTime"]).sort_values("LapTime")
            best_time = (
                best.iloc[0]["LapTime"].total_seconds() if not best.empty else 9999
            )
            drivers_with_time.append((drv, pos, best_time))
        drivers_with_time.sort(key=lambda x: (x[1], x[2]))

        rows = []
        for seq, (drv, orig_pos, best_time) in enumerate(drivers_with_time, 1):
            pts = SPRINT_PTS.get(seq, 0)
            rows.append((YEAR, rn, str(drv), seq, pts))
        db.executemany(
            "INSERT INTO sprint_points (year, round, driver, position, points) VALUES (?,?,?,?,?)"
            " ON CONFLICT(year, round, driver) DO UPDATE SET position=excluded.position, points=excluded.points",
            rows,
        )
        db.commit()
        total_pts = sum(r[4] for r in rows)
        print(f"R{rn}: {len(rows)} drivers, {total_pts} pts")
    except Exception as e:
        print(f"R{rn} FAIL: {e}")

print()
print(f"=== {YEAR} Sprint standings ===")
for r in db.execute(
    f"SELECT driver, SUM(points) FROM sprint_points WHERE year={YEAR} GROUP BY driver ORDER BY SUM(points) DESC, COUNT(*) DESC LIMIT 6"
).fetchall():
    print(f"  {r[0]}: {r[1]} sprint pts")

print()
print(f"=== {YEAR} Combined race + sprint ===")
for r in db.execute(
    f"""SELECT r.driver,
    COALESCE(SUM(r.points),0) +
    COALESCE((SELECT SUM(sp.points) FROM sprint_points sp
              WHERE sp.driver COLLATE NOCASE = r.driver COLLATE NOCASE
              AND sp.year={YEAR}), 0) as total,
    SUM(CASE WHEN r.position<=3 THEN 1 ELSE 0 END) as podiums,
    SUM(CASE WHEN r.position=1 THEN 1 ELSE 0 END) as wins
    FROM results r WHERE r.year={YEAR} GROUP BY r.driver ORDER BY total DESC, podiums DESC, wins DESC LIMIT 6"""
).fetchall():
    print(f"  {r[0]}: {r[1]} pts")

db.close()
print("DONE")
