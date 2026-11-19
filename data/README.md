# Data

Raw data is not included in this repository. The FootyStats files were provided for academic research, so each user downloads them separately. Everything under `data/raw/` is ignored by git.

Check what you have at any time:

```bash
python -m src.load
```

This prints how many matches, players, and matches with lineups were found for each season, and warns if a season is incomplete.

## 1. FootyStats season files

Download the CSV exports from [FootyStats](https://footystats.org) for the English Premier League, seasons 2020/21 to 2024/25. Keep the original file names and place them directly in `data/raw/`:

```
data/raw/
├── england-premier-league-matches-2020-to-2021-stats.csv
├── ...
├── england-premier-league-matches-2024-to-2025-stats.csv
├── england-premier-league-players-2020-to-2021-stats.csv
├── ...
└── england-premier-league-players-2024-to-2025-stats.csv
```

The loader finds files by this name pattern, so other files in the folder are ignored.

| File | Used for | Key columns |
|---|---|---|
| `matches-*` | Results, dates, baselines | `timestamp`, `home_team_name`, `away_team_name`, `home_team_goal_count`, `away_team_goal_count`, `status` |
| `players-*` | AC and DC metrics | `full_name`, `birthday`, `position`, `Current Club`, `minutes_played_overall`, season totals |

Notes on the player files:

- `Current Club` is the club the player ended the season with. A player who moved in January is listed under the new club for the whole season.
- Players with zero league minutes are dropped when loading.
- Two different players can share a name in one season. Players are keyed by `player_id`, which is the normalised name plus date of birth, for example `ben-davies_19930424`.

## 2. Lineup files

Contribution features need to know which players started each match. FootyStats season exports do not include lineups, so they come from a separate source. Place one or more CSV files in `data/raw/lineups/`, one row per player per match:

| Column | Required | Example | Notes |
|---|---|---|---|
| `date` | yes | `2023-08-12` | Local match date |
| `team` | yes | `Man City` | Short names are mapped automatically (see `TEAM_ALIASES` in `src/names.py`) |
| `player_name` | yes | `D. Rice` | Full or abbreviated names both work |
| `started` | no | `1` | 1 for starters, 0 for substitutes. Assumed 1 if missing |

Lineup rows are joined to matches by date and team, then player names are matched to FootyStats players of the same season and team. Each match records which rule matched it (`exact_team`, `initial_surname`, `fuzzy`, and so on), so the share of uncertain matches can be reported.

If a name cannot be matched automatically, add it to `data/name_aliases.csv`:

```csv
source_name,full_name,team
Bernard,Bernard Anício Caldeira Duarte,Everton
```

`team` is optional. Leave it empty to apply the alias for every team.
