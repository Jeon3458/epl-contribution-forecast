# Turn the raw API json files into 3 clean tables (csv)
#
# How to run (in the project folder):
#   python3 -m src.load
#
# Output (git ignores this folder):
#   data/processed/matches.csv          one row per match
#   data/processed/appearances.csv      one row per player per match
#   data/processed/player_seasons.csv   one row per player per season

import os
import re
import json
import glob
import unicodedata
import pandas as pd

API_DIR = "data/raw/api"
CSV_DIR = "data/raw"  # old FootyStats csv files from V1, only used to fill gaps
OUT_DIR = "data/processed"

SEASONS = {
    "2020-2021": 4759,
    "2021-2022": 6135,
    "2022-2023": 7704,
    "2023-2024": 9660,
    "2024-2025": 12325,
    "2025-2026": 15050,
}

# detailed stats we need (same names in the API and in the old csv files)
DETAILED = {
    "shots_total_overall": "shots",
    "xg_total_overall": "xg",
    "key_passes_total_overall": "key_passes",
    "tackles_total_overall": "tackles",
    "interceptions_total_overall": "interceptions",
    "clearances_total_overall": "clearances",
    "aerial_duels_won_total_overall": "aerials_won",
    "saves_total_overall": "saves",
}

# FootyStats marks some players as "Coach" (they became coaches later)
# real positions checked with the old V1 csv files
POSITION_FIX = {
    17552: "Defender",    # Maxime Le Marchand
    4068: "Forward",      # Shane Long
    1728: "Defender",     # Christian Fuchs
    8329: "Forward",      # Billy Sharp
    7332: "Midfielder",   # Conor Hourihane
    2965: "Defender",     # Shkodran Mustafi
    4022: "Midfielder",   # Tom Cleverley
    2901: "Defender",     # Felipe Augusto
    7270: "Defender",     # Lewis Dunk
}


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_pages(folder, name):
    # join all saved pages (matches_page1.json, matches_page2.json ...) into one list
    rows = []
    for path in sorted(glob.glob(f"{folder}/{name}_page*.json")):
        rows += load_json(path)["data"]
    return rows


def clean_name(name):
    # "Martin Ødegaard" -> "martin odegaard" (to match names in the old csv)
    name = str(name)
    for a, b in [("ø", "o"), ("Ø", "O"), ("ł", "l"), ("Ł", "L"), ("đ", "d"), ("Đ", "D"), ("ß", "ss")]:
        name = name.replace(a, b)
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"[^a-z0-9]+", " ", name.lower())
    return name.strip()


def to_minute(text):
    # "46'" -> 46, "90+3'" -> 90, "-1" -> None
    text = str(text).strip().replace("'", "")
    if text == "" or text.startswith("-"):
        return None
    return int(text.split("+")[0])


def build_matches():
    rows = []
    for season in SEASONS:
        for m in read_pages(f"{API_DIR}/{season}", "matches"):
            if m["status"] != "complete":
                continue

            if m["homeGoalCount"] > m["awayGoalCount"]:
                result = "H"
            elif m["homeGoalCount"] < m["awayGoalCount"]:
                result = "A"
            else:
                result = "D"

            rows.append({
                "match_id": m["id"],
                "season": season,
                "date_unix": m["date_unix"],
                "game_week": m["game_week"],
                "home_team_id": m["homeID"],
                "home_team": m["home_name"],
                "away_team_id": m["awayID"],
                "away_team": m["away_name"],
                "home_goals": m["homeGoalCount"],
                "away_goals": m["awayGoalCount"],
                "result": result,
                # odds are only for reference, not used as features
                "odds_home": m["odds_ft_1"],
                "odds_draw": m["odds_ft_x"],
                "odds_away": m["odds_ft_2"],
            })

    df = pd.DataFrame(rows)
    # unix time -> date in UK time
    df["date"] = pd.to_datetime(df["date_unix"], unit="s", utc=True).dt.tz_convert("Europe/London").dt.date
    # 0 odds means no data
    for col in ["odds_home", "odds_draw", "odds_away"]:
        df.loc[df[col] <= 0, col] = None
    df = df.sort_values(["date_unix", "match_id"]).reset_index(drop=True)

    first = ["match_id", "season", "date"]
    return df[first + [c for c in df.columns if c not in first]]


def build_appearances(matches):
    rows = []
    for m in matches.itertuples():
        d = load_json(f"{API_DIR}/{m.season}/match_details/{m.match_id}.json")["data"]

        # in the API, team_a = home team and team_b = away team
        for side, key, team_id in [("home", "team_a", m.home_team_id), ("away", "team_b", m.away_team_id)]:

            # read the subs: who came off and who came on, and when
            minute_out = {}
            subs_in = []
            for b in d["bench"][key]:
                if b["player_out_id"] == -1:
                    continue  # stayed on the bench
                t = to_minute(b["player_out_time"])
                minute_out[b["player_out_id"]] = t
                subs_in.append((b["player_in_id"], t))

            base = {"match_id": m.match_id, "season": m.season, "date": m.date, "team_id": team_id, "side": side}

            # starters play from minute 0 until they are subbed off (or 90)
            for p in d["lineups"][key]:
                row = dict(base)
                row["player_id"] = p["player_id"]
                row["started"] = 1
                row["minute_in"] = 0
                row["minute_out"] = minute_out.get(p["player_id"], 90)
                rows.append(row)

            # subs play from when they came on until the end (or until subbed off)
            for pid, t in subs_in:
                row = dict(base)
                row["player_id"] = pid
                row["started"] = 0
                row["minute_in"] = t
                row["minute_out"] = minute_out.get(pid, 90)
                rows.append(row)

    return pd.DataFrame(rows)


def build_player_seasons():
    # detailed stats from the old csv files, key = (season, name, birthday)
    csv_stats = {}
    for season in SEASONS:
        path = f"{CSV_DIR}/england-premier-league-players-{season[:4]}-to-{season[5:]}-stats.csv"
        if not os.path.exists(path):
            continue
        old = pd.read_csv(path)
        for r in old.to_dict("records"):
            if r["minutes_played_overall"] > 0 and not pd.isna(r["tackles_total_overall"]):
                csv_stats[(season, clean_name(r["full_name"]), int(r["birthday"]))] = r

    rows = []
    for season, season_id in SEASONS.items():
        for p in read_pages(f"{API_DIR}/{season}", "players"):
            if not p["minutes_played_overall"]:
                continue  # never played

            position = POSITION_FIX.get(p["id"], p["position"])
            if position == "Coach":
                print(f"  skipped, position is 'Coach': {season} {p['known_as']}")
                continue

            row = {
                "season": season,
                "player_id": p["id"],
                "name": p["known_as"],
                "full_name": p["full_name"],
                "birthday": p["birthday"],
                "position": position,
                "team_id": p["club_team_id"],
                "minutes": p["minutes_played_overall"],
                "appearances": p["appearances_overall"],
                "goals": p["goals_overall"],
                "assists": p["assists_overall"],
                "clean_sheets": p["clean_sheets_overall"],
                "conceded": p["conceded_overall"],
            }

            # 1st choice: detailed stats from the API (row of this EPL season)
            detailed = None
            path = f"{API_DIR}/player_stats/{p['id']}.json"
            if os.path.exists(path):
                for r in load_json(path)["data"]:
                    if r["competition_id"] == season_id and isinstance(r.get("detailed"), dict):
                        detailed = r["detailed"]
            source = "api"

            # sometimes the API has no detailed stats -> 2nd choice: old csv
            # (goalkeepers have no tackles, so check saves for them)
            check = "saves_total_overall" if position == "Goalkeeper" else "tackles_total_overall"
            if detailed is None or detailed.get(check) is None:
                detailed = csv_stats.get((season, clean_name(p["full_name"]), int(p["birthday"] or 0)))
                source = "csv"
            if detailed is None:
                detailed = {}
                source = "missing"

            for long_name, short_name in DETAILED.items():
                row[short_name] = detailed.get(long_name)
            row["stats_source"] = source
            rows.append(row)

    return pd.DataFrame(rows)


def print_checks(matches, apps, players):
    print("\n----- checks -----")
    print("matches per season:")
    print(matches.groupby("season").size().to_string())

    starters = apps[apps["started"] == 1]
    per_team = starters.groupby(["match_id", "side"]).size()
    print(f"\nteams without 11 starters: {(per_team != 11).sum()}")
    print(f"subs with unknown minute: {apps['minute_in'].isna().sum()}")

    # how many starts have detailed stats for that season?
    s = starters.merge(players[["season", "player_id", "stats_source"]], on=["season", "player_id"], how="left")
    s["stats_source"] = s["stats_source"].fillna("no player row")
    print("\nstarts by stats source (% of starts in each season):")
    print((pd.crosstab(s["season"], s["stats_source"], normalize="index") * 100).round(1).to_string())


def main():
    os.makedirs(OUT_DIR, exist_ok=True)

    print("building matches...")
    matches = build_matches()
    print("building appearances... (reads 2280 files, takes a bit)")
    apps = build_appearances(matches)
    print("building player seasons...")
    players = build_player_seasons()

    matches.to_csv(f"{OUT_DIR}/matches.csv", index=False)
    apps.to_csv(f"{OUT_DIR}/appearances.csv", index=False)
    players.to_csv(f"{OUT_DIR}/player_seasons.csv", index=False)
    print(f"\nsaved to {OUT_DIR}: matches {len(matches)}, appearances {len(apps)}, player_seasons {len(players)}")

    print_checks(matches, apps, players)


if __name__ == "__main__":
    main()