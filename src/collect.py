# Download EPL data from the FootyStats API
#
# How to run (in the project folder):
#   python3 -m src.collect --test       quick test with a few requests
#   python3 -m src.collect              download everything
#   python3 -m src.collect 2025-2026    download one season only
#
# Raw json files are saved in data/raw/api/ (git ignores this folder).
# The API key comes from the .env file. Never print the key!

import os
import sys
import json
import time
import glob
import requests

BASE_URL = "https://api.football-data-api.com"
SAVE_DIR = "data/raw/api"

# EPL season ids (found with the league-list endpoint)
SEASONS = {
    "2020-2021": 4759,
    "2021-2022": 6135,
    "2022-2023": 7704,
    "2023-2024": 9660,
    "2024-2025": 12325,
    "2025-2026": 15050,
}

# Hobby plan = 1800 requests per hour, so wait about 2 sec after each request
WAIT = 2.1


def read_api_key():
    # read FOOTYSTATS_API_KEY from the .env file
    key = ""
    if os.path.exists(".env"):
        for line in open(".env"):
            line = line.strip()
            if line.startswith("FOOTYSTATS_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if key == "":
        print("No API key found. Add FOOTYSTATS_API_KEY=... to .env")
        sys.exit()
    return key


def call_api(endpoint, params, key):
    # send one request and return the json (None if it fails)
    # never print the full url or the error text, they contain the key
    full_params = dict(params)
    full_params["key"] = key

    for attempt in range(1, 6):
        try:
            res = requests.get(BASE_URL + "/" + endpoint, params=full_params, timeout=60)
        except Exception:
            print(f"  connection error {endpoint} {params}, retry in 10s ({attempt}/5)")
            time.sleep(10)
            continue

        if res.status_code == 429:
            print("  hit the request limit, waiting 10 min")
            time.sleep(600)
            continue

        try:
            data = res.json()
        except Exception:
            print(f"  bad response {endpoint} {params}, retry in 10s ({attempt}/5)")
            time.sleep(10)
            continue

        if "limit" in str(data.get("message")).lower():
            print("  hit the request limit, waiting 10 min")
            time.sleep(600)
            continue

        if not data.get("success"):
            print(f"  failed {endpoint} {params}: {data.get('message')}")
            return None

        # close to the hourly limit -> take a break
        left = data.get("metadata", {}).get("request_remaining")
        if left is not None and int(left) < 20:
            print(f"  only {left} requests left this hour, waiting 10 min")
            time.sleep(600)

        time.sleep(WAIT)
        return data

    print(f"  gave up on {endpoint} {params}")
    return None


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_pages(endpoint, params, folder, name, key, max_pages=None):
    # some endpoints split the result into pages -> save each page as a file
    # pages we already have are not downloaded again
    page = 1
    last_page = 1
    while page <= last_page:
        path = f"{folder}/{name}_page{page}.json"
        if os.path.exists(path):
            data = load_json(path)
        else:
            p = dict(params)
            p["page"] = page
            data = call_api(endpoint, p, key)
            if data is None:
                return False
            save_json(path, data)

        last_page = data["pager"]["max_page"]
        if max_pages is not None:
            last_page = min(last_page, max_pages)
        page += 1
    return True


def read_pages(folder, name):
    # join all saved pages into one list
    rows = []
    page = 1
    while os.path.exists(f"{folder}/{name}_page{page}.json"):
        rows += load_json(f"{folder}/{name}_page{page}.json")["data"]
        page += 1
    return rows


def collect_season(season, key, test=False):
    season_id = SEASONS[season]
    folder = f"{SAVE_DIR}/{season}"
    print(f"\n===== {season} (season_id {season_id}) =====")

    # step 1: all matches of the season
    ok = get_pages("league-matches", {"season_id": season_id, "max_per_page": 500}, folder, "matches", key)
    if not ok:
        print("could not get the match list, skip this season")
        return
    matches = read_pages(folder, "matches")
    finished = [m for m in matches if m["status"] == "complete"]
    print(f"matches: {len(matches)} ({len(finished)} finished)")

    # step 2: all players of the season (test mode = first page only)
    max_pages = None
    if test:
        max_pages = 1
    get_pages("league-players", {"season_id": season_id, "include": "stats"}, folder, "players", key, max_pages)
    print(f"players: {len(read_pages(folder, 'players'))}")

    # step 3: match details (lineups, subs, goals) = one request per match
    if test:
        finished = finished[:2]
    new = 0
    failed = 0
    start = time.time()
    for i, m in enumerate(finished):
        path = f"{folder}/match_details/{m['id']}.json"
        if os.path.exists(path):
            continue  # already have it
        data = call_api("match", {"match_id": m["id"]}, key)
        if data is None:
            failed += 1
            continue
        save_json(path, data)
        new += 1
        if new % 20 == 0:
            print(f"  match details {i + 1}/{len(finished)} ({(time.time() - start) / 60:.1f} min)")
    print(f"match details: {new} new, {failed} failed")


def collect_player_stats(seasons, key, test=False):
    # step 4: detailed stats (tackles, interceptions...) = one request per player
    # one request gives every season and competition of that player
    print("\n===== player details =====")
    ids = []
    for season in seasons:
        players = read_pages(f"{SAVE_DIR}/{season}", "players")
        if test:
            # test: only the outfield player with the most minutes
            outfield = [p for p in players if p["position"] != "Goalkeeper"]
            best = max(outfield, key=lambda p: p["minutes_played_overall"] or 0)
            ids.append(best["id"])
            continue
        for p in players:
            if (p["minutes_played_overall"] or 0) > 0 and p["id"] not in ids:
                ids.append(p["id"])
    print(f"players to download: {len(ids)}")

    new = 0
    failed = 0
    start = time.time()
    for i, pid in enumerate(ids):
        path = f"{SAVE_DIR}/player_stats/{pid}.json"
        if os.path.exists(path):
            continue  # already have it
        data = call_api("player-stats", {"player_id": pid}, key)
        if data is None:
            failed += 1
            continue
        save_json(path, data)
        new += 1
        if new % 50 == 0:
            print(f"  players {i + 1}/{len(ids)} ({(time.time() - start) / 60:.1f} min)")
    print(f"player details: {new} new, {failed} failed")


def print_test_report(season):
    # check that the test data has everything we need
    folder = f"{SAVE_DIR}/{season}"
    print(f"\n----- check {season} -----")

    # lineups of 2 matches
    for path in sorted(glob.glob(f"{folder}/match_details/*.json"))[:2]:
        m = load_json(path)["data"]
        goals = len(m["team_a_goal_details"]) + len(m["team_b_goal_details"])
        print(f"{m['home_name']} {m['homeGoalCount']}-{m['awayGoalCount']} {m['away_name']}"
              f" | starters {len(m['lineups']['team_a'])}+{len(m['lineups']['team_b'])}"
              f" | bench {len(m['bench']['team_a'])}+{len(m['bench']['team_b'])}"
              f" | goals {goals}")

    # detailed stats of one player in this season (competition_id = season id)
    row = None
    for path in glob.glob(f"{SAVE_DIR}/player_stats/*.json"):
        for r in load_json(path)["data"]:
            if r["competition_id"] == SEASONS[season]:
                row = r
    if row is None:
        print("no player details for this season")
        return
    stats = dict(row)
    stats.update(row.get("detailed") or {})
    print(f"player: {row['known_as']} ({row['position']})")
    for col in ["minutes_played_overall", "goals_overall", "assists_overall",
                "shots_total_overall", "xg_total_overall", "key_passes_total_overall",
                "tackles_total_overall", "interceptions_total_overall",
                "clearances_total_overall", "aerial_duels_won_total_overall",
                "saves_total_overall", "clean_sheets_overall", "conceded_overall"]:
        print(f"  {col:32s} {stats.get(col, 'MISSING')}")


if __name__ == "__main__":
    key = read_api_key()

    if "--test" in sys.argv:
        test_seasons = ["2020-2021", "2025-2026"]
        for s in test_seasons:
            collect_season(s, key, test=True)
        collect_player_stats(test_seasons, key, test=True)
        for s in test_seasons:
            print_test_report(s)
    else:
        seasons = [a for a in sys.argv[1:] if a in SEASONS]
        if len(seasons) == 0:
            seasons = list(SEASONS)
        for s in seasons:
            collect_season(s, key)
        collect_player_stats(seasons, key)
        print("\ndone!")