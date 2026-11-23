# Data

Raw and processed data are not included in this repository. Both come from FootyStats, which does not allow redistribution. Everything under `data/raw/` and `data/processed/` is ignored by git.

## 1. Get an API key

1. Subscribe to the [FootyStats API](https://footystats.org/api). The Hobby plan is enough. Select **England Premier League** as one of your leagues.
2. Create a file named `.env` in the project folder with one line:

```
FOOTYSTATS_API_KEY=your_key_here
```

`.env` is ignored by git, so the key is never uploaded.

## 2. Download the raw data

```bash
python3 -m src.collect --test   # quick check with a few requests
python3 -m src.collect          # download everything
```

- Seasons 2020/21 to 2025/26.
- About 3,700 requests in total. The Hobby plan allows 1,800 requests per hour, so the script waits about 2 seconds between requests. A full run takes about 2.5 hours.
- Files that are already downloaded are skipped. If the run stops, run the same command again to continue.

| API endpoint | Saved to | Contents |
|---|---|---|
| `league-matches` | `data/raw/api/<season>/matches_page*.json` | Results, dates, odds |
| `league-players` | `data/raw/api/<season>/players_page*.json` | Players and basic season stats |
| `match` | `data/raw/api/<season>/match_details/<match_id>.json` | Starting XI, substitutions with times, goals, cards |
| `player-stats` | `data/raw/api/player_stats/<player_id>.json` | Detailed stats for every season and competition of one player |

**Optional:** the FootyStats CSV player exports used in Version 1 (`england-premier-league-players-YYYY-to-YYYY-stats.csv`, 2020/21 to 2024/25) can be placed in `data/raw/`. They are used only to fill gaps in the API data (see below).

## 3. Build the clean tables

```bash
python3 -m src.load
```

| File | One row per | Main columns |
|---|---|---|
| `data/processed/matches.csv` | Match (2,280) | `match_id`, `season`, `date`, home/away team, goals, `result` (H/D/A), odds |
| `data/processed/appearances.csv` | Player in a match (66,624) | `match_id`, `team_id`, `side`, `player_id`, `started`, `minute_in`, `minute_out` |
| `data/processed/player_seasons.csv` | Player in a season (3,281) | `player_id`, `position`, `minutes`, goals, assists, shots, xG, key passes, tackles, interceptions, clearances, aerial duels won, saves, clean sheets, conceded, `stats_source` |

The script ends by printing checks: matches per season, teams without 11 starters, and how many starts have detailed stats.

## Known data issues

**Missing detailed stats.** For some player-seasons the API has no detailed stats (tackles, interceptions, key passes, and so on), even for regular starters. Missing values are filled from the Version 1 CSV exports when the same player (name and date of birth) is found there. The source is recorded in `stats_source`. Share of starts by source:

| Season | API | CSV | Missing |
|---|---|---|---|
| 2020/21 | 97.7% | 0.6% | 1.7% |
| 2021/22 | 98.6% | 0.5% | 0.9% |
| 2022/23 | 97.6% | 0.7% | 1.7% |
| 2023/24 | 93.1% | 3.2% | 3.6% |
| 2024/25 | 91.9% | 3.7% | 4.4% |
| 2025/26 | 99.5% | 0.0% | 0.5% |

How missing values are handled in the features is decided in the contribution stage.

**Wrong positions.** FootyStats lists 9 players who later became coaches with the position "Coach", even in seasons where they played. Their real positions are set in `POSITION_FIX` in `src/load.py`.

**Approximate minutes.** Minutes in `appearances.csv` assume a 90-minute match. Stoppage time and red cards are ignored. MI only uses whether a player started, so this does not affect it.

**Odds.** Bookmaker odds are kept for reference only and are not used as features.