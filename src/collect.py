# Download EPL data from the FootyStats API
#
# How to run (in the project folder):
#   python3 -m src.collect --test       quick test of the new parts (about 20 requests)
#   python3 -m src.collect              download everything
#   python3 -m src.collect 2026-2027    download one season only
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
    "2017-2018": 161,
    "2018-2019": 1625,
    "2019-2020": 2012,
    "2020-2021": 4759,
    "2021-2022": 6135,
    "2022-2023": 7704,
    "2023-2024": 9660,
    "2024-2025": 12325,
    "2025-2026": 15050,
    "2026-2027": 17146,
}

# this season is still being played, so its lists change -> download them again every run
CURRENT_SEASON = "2026-2027"

# the API has detailed player stats (tackles, ...) only from 2020/21
DETAIL_SEASONS = ["2020-2021", "2021-2022", "2022-2023", "2023-2024", "2024-2025", "2025-2026", "2026-2027"]

# other competitions: match lists only (rest days, busy weeks, promoted teams)
# season ids in the same order as SEASONS (None = the competition did not exist yet)
OTHER_COMPS = {
    "championship":      [165, 1624, 2187, 4912, 6089, 7593, 9663, 12451, 14930, 17184],
    "fa_cup":            [1033, 1674, 2414, 4803, 6068, 7836, 9759, 13698, 15238, 17234],
    "league_cup":        [1047, 1675, 2215, 4780, 7470, 7579, 9574, 12473, 15137, 17111],
    "champions_league":  [247, 1534, 2202, 4655, 5977, 7455, 9543, 12321, 14924, 17128],
    "europa_league":     [964, 1535, 2203, 4693, 6218, 7985, 10210, 12327, 15002, 17127],
    "conference_league": [None, None, None, None, 7322, 7480, 9600, 12278, 14904, 17130],
    "community_shield":  [3870, 1626, 2196, 4657, 5962, 7348, 9541, 12036, 15119, 17086],
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


def get_pages(endpoint, params, folder, name, key, max_pages=None, refresh=False):
    # some endpoints split the result into pages -> save each page as a file
    # pages we already have are not downloaded again (unless refresh=True)
    page = 1
    last_page = 1
    while page <= last_page:
        path = f"{folder}/{name}_page{page}.json"
        if os.path.exists(path) and not refresh:
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


def get_once(endpoint, params, path, key, refresh=False):
    # for endpoints that answer in one response (table, league stats, ...)
    if os.path.exists(path) and not refresh:
        return True
    data = call_api(endpoint, params, key)
    if data is None:
        return False
    save_json(path, data)
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
    refresh = season == CURRENT_SEASON
    print(f"\n===== {season} (season_id {season_id}) =====")

    # step 1: all matches of the season
    ok = get_pages("league-matches", {"season_id": season_id, "max_per_page": 500}, folder, "matches", key, refresh=refresh)
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
    get_pages("league-players", {"season_id": season_id, "include": "stats"}, folder, "players", key, max_pages, refresh)
    print(f"players: {len(read_pages(folder, 'players'))}")

    # step 3: match details (lineups, subs, goals) = one request per finished match
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


def collect_player_stats(seasons, key):
    # step 4: detailed stats (tackles, interceptions...) = one request per player
    # one request gives every season and competition of that player
    print("\n===== player details =====")
    ids = []
    for season in seasons:
        if season not in DETAIL_SEASONS:
            continue  # no detailed stats in the API before 2020/21
        for p in read_pages(f"{SAVE_DIR}/{season}", "players"):
            if (p["minutes_played_overall"] or 0) > 0 and p["id"] not in ids:
                ids.append(p["id"])
    print(f"players: {len(ids)}")

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


def collect_extras(seasons, key):
    # step 5: season summaries = 4 requests per season
    print("\n===== season summaries =====")
    for season in seasons:
        season_id = SEASONS[season]
        folder = f"{SAVE_DIR}/{season}"
        refresh = season == CURRENT_SEASON
        ok = 0
        ok += get_once("league-teams", {"season_id": season_id, "include": "stats"}, f"{folder}/teams.json", key, refresh)
        ok += get_once("league-tables", {"season_id": season_id}, f"{folder}/table.json", key, refresh)
        ok += get_once("league-referees", {"season_id": season_id}, f"{folder}/referees.json", key, refresh)
        ok += get_once("league-season", {"season_id": season_id}, f"{folder}/league_stats.json", key, refresh)
        print(f"{season}: {ok}/4 saved")


def collect_other_comps(seasons, key):
    # step 6: match lists of other competitions (1-2 requests each)
    print("\n===== other competitions =====")
    season_names = list(SEASONS)
    for comp, comp_ids in OTHER_COMPS.items():
        saved = []
        for season, comp_id in zip(season_names, comp_ids):
            if comp_id is None or season not in seasons:
                continue
            folder = f"{SAVE_DIR}/other_comps/{comp}/{season}"
            refresh = season == CURRENT_SEASON
            if get_pages("league-matches", {"season_id": comp_id, "max_per_page": 500}, folder, "matches", key, refresh=refresh):
                saved.append(f"{season[2:4]}/{season[7:]}({len(read_pages(folder, 'matches'))})")
        if saved:
            print(f"{comp}: " + ", ".join(saved))
        else:
            print(f"{comp}: nothing saved")


def run_test(key):
    # test only the new parts, about 20 requests
    collect_season("2026-2027", key, test=True)  # current season
    collect_season("2017-2018", key, test=True)  # old season
    collect_extras(["2025-2026"], key)
    collect_other_comps(["2025-2026"], key)

    print("\n----- check -----")
    for season in ["2026-2027", "2017-2018"]:
        matches = read_pages(f"{SAVE_DIR}/{season}", "matches")
        finished = [m for m in matches if m["status"] == "complete"]
        print(f"{season}: {len(matches)} matches in the list, {len(finished)} finished")
        for path in sorted(glob.glob(f"{SAVE_DIR}/{season}/match_details/*.json"))[:1]:
            m = load_json(path)["data"]
            print(f"  {m['home_name']} {m['homeGoalCount']}-{m['awayGoalCount']} {m['away_name']}"
                  f" | starters {len(m['lineups']['team_a'])}+{len(m['lineups']['team_b'])}")
    for name in ["teams", "table", "referees", "league_stats"]:
        ok = os.path.exists(f"{SAVE_DIR}/2025-2026/{name}.json")
        print(f"2025-2026 {name}.json: {'ok' if ok else 'MISSING'}")


if __name__ == "__main__":
    key = read_api_key()

    if "--test" in sys.argv:
        run_test(key)
    else:
        seasons = [a for a in sys.argv[1:] if a in SEASONS]
        if len(seasons) == 0:
            seasons = list(SEASONS)
        for s in seasons:
            collect_season(s, key)
        collect_player_stats(seasons, key)
        collect_extras(seasons, key)
        collect_other_comps(seasons, key)
        print("\ndone!")