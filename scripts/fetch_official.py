"""Fetch official F1 results from Jolpi Ergast mirror and update DB. Usage: python fetch_official.py [year]"""

import sys
import sqlite3
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "f1_oracle.db"

TEAM_MAP = {
    "Red Bull": "Red Bull Racing",
    "Alpine F1 Team": "Alpine",
    "RB F1 Team": "Racing Bulls",
    "Sauber": "Kick Sauber",
}

YEAR = int(sys.argv[1]) if len(sys.argv) > 1 else 2025


def fetch_race_results(round_num):
    url = f"https://api.jolpi.ca/ergast/f1/{YEAR}/{round_num}/results.json"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return []
    data = r.json()
    races = data["MRData"]["RaceTable"]["Races"]
    if not races:
        return []
    results = []
    for res in races[0]["Results"]:
        driver_code = res["Driver"]["code"]
        driver_name = f"{res['Driver']['givenName']} {res['Driver']['familyName']}"
        team_raw = res["Constructor"]["name"]
        team = TEAM_MAP.get(team_raw, team_raw)
        position = int(res["position"])
        grid = int(res["grid"]) if res["grid"].isdigit() else None
        points = float(res["points"])
        status = res["status"]
        laps = int(res["laps"])
        race_time = None
        if "Time" in res and res["Time"]:
            try:
                parts = res["Time"]["time"].split(":")
                if len(parts) == 3:
                    h, m, s = parts
                    race_time = int(h) * 3600 + int(m) * 60 + float(s)
                elif len(parts) == 2:
                    m, s = parts
                    race_time = int(m) * 60 + float(s)
            except Exception:
                pass
        results.append({
            "driver": driver_code, "full_name": driver_name, "team": team,
            "position": position, "grid": grid, "points": points,
            "status": status, "laps": laps, "race_time": race_time,
        })
    return results


def _qtime_to_sec(t):
    if not t:
        return None
    try:
        parts = str(t).split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
    except Exception:
        pass
    return None


def fetch_qualifying_results(round_num):
    url = f"https://api.jolpi.ca/ergast/f1/{YEAR}/{round_num}/qualifying.json"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return []
    data = r.json()
    races = data["MRData"]["RaceTable"]["Races"]
    if not races:
        return []
    results = []
    for res in races[0].get("QualifyingResults", []):
        results.append({
            "driver": res["Driver"]["code"],
            "position": int(res["position"]),
            "q1_sec": _qtime_to_sec(res.get("Q1")),
            "q2_sec": _qtime_to_sec(res.get("Q2")),
            "q3_sec": _qtime_to_sec(res.get("Q3")),
        })
    return results


def fetch_sprint_results(round_num):
    url = f"https://api.jolpi.ca/ergast/f1/{YEAR}/{round_num}/sprint.json"
    r = requests.get(url, timeout=15)
    if r.status_code != 200:
        return []
    data = r.json()
    races = data["MRData"]["RaceTable"]["Races"]
    if not races:
        return []
    sprint = races[0]["SprintResults"]
    results = []
    for res in sprint:
        results.append({
            "driver": res["Driver"]["code"],
            "position": int(res["position"]),
            "points": float(res["points"]),
        })
    return results


def update_db():
    db = sqlite3.connect(str(DB_PATH))
    max_round = db.execute(
        "SELECT MAX(round) FROM events WHERE year=?", (YEAR,)
    ).fetchone()[0]
    if not max_round:
        print(f"No events found for {YEAR}")
        db.close()
        return

    # --- Race results ---
    for rn in range(1, max_round + 1):
        results = fetch_race_results(rn)
        if not results:
            print(f"R{rn}: skip")
            continue
        for res in results:
            db.execute(
                """UPDATE results SET
                    full_name=?, team=?, position=?, grid=?,
                    points=?, laps_completed=?, race_time_sec=?,
                    status=CASE WHEN status IS NULL OR status='' THEN ? ELSE status END
                   WHERE year=? AND round=? AND driver COLLATE NOCASE=?""",
                (res["full_name"], res["team"], res["position"], res["grid"],
                 res["points"], res["laps"], res["race_time"],
                 res["status"], YEAR, rn, res["driver"]),
            )
        db.commit()
        top3 = db.execute(
            f"SELECT position, driver, points FROM results WHERE year={YEAR} AND round=? ORDER BY position LIMIT 3",
            (rn,),
        ).fetchall()
        top_str = ", ".join(f"P{r[0]} {r[1]} {r[2]}pts" for r in top3)
        print(f"R{rn}: {len(results)} drivers  {top_str}")
        time.sleep(0.25)

    # --- Qualifying results ---
    quali_found = False
    for rn in range(1, max_round + 1):
        results = fetch_qualifying_results(rn)
        if not results:
            continue
        if not quali_found:
            print()
            quali_found = True
        for res in results:
            db.execute(
                "UPDATE results SET q1_sec=?, q2_sec=?, q3_sec=?, quali_pos=?"
                " WHERE year=? AND round=? AND driver COLLATE NOCASE=?",
                (res["q1_sec"], res["q2_sec"], res["q3_sec"], res["position"],
                 YEAR, rn, res["driver"]),
            )
        db.commit()
        p1 = next((r for r in results if r["position"] == 1), None)
        p1_str = f"P1 {p1['driver']} {p1['q3_sec']:.3f}s" if p1 and p1["q3_sec"] else "P1 --"
        print(f"Q{rn}: {len(results)} drivers  {p1_str}")
        time.sleep(0.25)

    # --- Sprint results ---
    sprint_found = False
    for rn in range(1, max_round + 1):
        results = fetch_sprint_results(rn)
        if not results:
            continue
        if not sprint_found:
            print()
            sprint_found = True
        for res in results:
            db.execute(
                "INSERT INTO sprint_points (year, round, driver, position, points) VALUES (?,?,?,?,?)"
                " ON CONFLICT(year, round, driver) DO UPDATE SET position=excluded.position, points=excluded.points",
                (YEAR, rn, res["driver"], res["position"], res["points"]),
            )
        db.commit()
        top_str = ", ".join(
            f"P{r['position']} {r['driver']} {r['points']:.0f}pts"
            for r in sorted(results, key=lambda x: x["position"])[:3]
        )
        print(f"S{rn}: {len(results)} drivers  {top_str}")
        time.sleep(0.25)

    # --- Standings ---
    print()
    print(f"=== {YEAR} FINAL STANDINGS (race only) ===")
    for r in db.execute(
        f"""SELECT driver, SUM(points) as p,
                SUM(CASE WHEN position<=3 THEN 1 ELSE 0 END) as podiums,
                SUM(CASE WHEN position=1 THEN 1 ELSE 0 END) as wins
                FROM results WHERE year={YEAR}
                GROUP BY driver ORDER BY p DESC, podiums DESC, wins DESC LIMIT 6"""
    ).fetchall():
        print(f"  {r[0]}: {r[1]:.0f} pts")

    print()
    print(f"=== {YEAR} SPRINT STANDINGS ===")
    for r in db.execute(
        f"SELECT driver, SUM(points) as p FROM sprint_points WHERE year={YEAR} GROUP BY driver ORDER BY p DESC, COUNT(*) DESC LIMIT 6"
    ).fetchall():
        print(f"  {r[0]}: {r[1]:.0f} pts")

    print()
    print(f"=== {YEAR} COMBINED (race + sprint) ===")
    for r in db.execute(
        f"""SELECT r.driver,
        COALESCE(SUM(r.points),0) +
        COALESCE((SELECT SUM(sp.points) FROM sprint_points sp
                  WHERE sp.driver COLLATE NOCASE = r.driver COLLATE NOCASE
                  AND sp.year={YEAR}), 0) as total,
        SUM(CASE WHEN r.position<=3 THEN 1 ELSE 0 END) as podiums,
        SUM(CASE WHEN r.position=1 THEN 1 ELSE 0 END) as wins
        FROM results r WHERE r.year={YEAR}
        GROUP BY r.driver ORDER BY total DESC, podiums DESC, wins DESC LIMIT 6"""
    ).fetchall():
        print(f"  {r[0]}: {r[1]:.0f} pts")

    db.close()
    print("DONE")


if __name__ == "__main__":
    update_db()
