"""Read the raw FootyStats files and lineup files into clean tables.

Nothing here computes features. The loaders only rename columns, map team
names, build keys and check that each season is complete. Feature code in
later stages decides what is known before each match.

Run ``python -m src.load`` to print which seasons are available.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .names import canonical_teams, make_player_id, normalize_name

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = PROJECT_ROOT / "data" / "raw"

SEASONS = ("2020-2021", "2021-2022", "2022-2023", "2023-2024", "2024-2025")

_FILE_RE = re.compile(
    r"england-premier-league-(?P<kind>matches|players)-(?P<start>\d{4})-to-(?P<end>\d{4})-stats\.csv$"
)

#: Raw match columns kept, with their clean names.
MATCH_COLUMNS = {
    "timestamp": "timestamp",
    "status": "status",
    "Game Week": "matchweek",
    "home_team_name": "home_team",
    "away_team_name": "away_team",
    "home_team_goal_count": "home_goals",
    "away_team_goal_count": "away_goals",
    # Bookmaker odds, kept only as a reference point for evaluation.
    "odds_ft_home_team_win": "odds_home",
    "odds_ft_draw": "odds_draw",
    "odds_ft_away_team_win": "odds_away",
}

#: Raw player columns kept, with their clean names. Season totals only;
#: per-90 rates are computed later from these and ``minutes``.
PLAYER_COLUMNS = {
    "full_name": "full_name",
    "birthday": "birthday",
    "position": "position",
    "Current Club": "team",
    "minutes_played_overall": "minutes",
    "appearances_overall": "appearances",
    "games_started": "starts",
    "goals_overall": "goals",
    "assists_overall": "assists",
    "shots_total_overall": "shots",
    "xg_total_overall": "xg",
    "key_passes_total_overall": "key_passes",
    "tackles_total_overall": "tackles",
    "interceptions_total_overall": "interceptions",
    "clearances_total_overall": "clearances",
    "aerial_duels_won_total_overall": "aerials_won",
    "saves_total_overall": "saves",
    "clean_sheets_overall": "clean_sheets",
    "conceded_overall": "goals_conceded",
}

LINEUP_COLUMNS = ("date", "team", "player_name")

POSITIONS = ("Goalkeeper", "Defender", "Midfielder", "Forward")


def find_raw_files(raw_dir: Path = RAW_DIR) -> dict[str, dict[str, Path]]:
    """Map ``kind -> season -> path`` for FootyStats files in ``raw_dir``."""
    found: dict[str, dict[str, Path]] = {"matches": {}, "players": {}}
    for path in sorted(Path(raw_dir).glob("*.csv")):
        m = _FILE_RE.search(path.name)
        if m:
            season = f"{m['start']}-{m['end']}"
            found[m["kind"]][season] = path
    return found


def _select_seasons(files: dict[str, Path], seasons, kind: str) -> dict[str, Path]:
    if seasons is None:
        return files
    missing = [s for s in seasons if s not in files]
    if missing:
        raise FileNotFoundError(
            f"No {kind} file for seasons {missing}. See data/README.md."
        )
    return {s: files[s] for s in seasons}


def _slug(text: str) -> str:
    return normalize_name(text).replace(" ", "-")


# ---------------------------------------------------------------------------
# Matches
# ---------------------------------------------------------------------------


def load_matches(raw_dir: Path = RAW_DIR, seasons=None) -> pd.DataFrame:
    """One row per completed league match, sorted by kickoff.

    Columns: ``match_id, season, kickoff_utc, date, matchweek, home_team,
    away_team, home_goals, away_goals, result, odds_home, odds_draw,
    odds_away``. ``date`` is the local (London) calendar date, which is what
    lineup sources use. ``result`` is ``H``, ``D`` or ``A``.
    """
    files = _select_seasons(find_raw_files(raw_dir)["matches"], seasons, "match")
    if not files:
        raise FileNotFoundError(f"No match files in {raw_dir}. See data/README.md.")

    frames = []
    for season, path in files.items():
        raw = pd.read_csv(path)
        missing = set(MATCH_COLUMNS) - set(raw.columns)
        if missing:
            raise ValueError(f"{path.name} is missing columns {sorted(missing)}")
        df = raw[list(MATCH_COLUMNS)].rename(columns=MATCH_COLUMNS)
        df.insert(0, "season", season)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    df = df[df["status"] == "complete"].drop(columns="status")
    df["kickoff_utc"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    df["date"] = df["kickoff_utc"].dt.tz_convert("Europe/London").dt.date
    df["home_team"] = canonical_teams(df["home_team"])
    df["away_team"] = canonical_teams(df["away_team"])
    df["home_goals"] = df["home_goals"].astype(int)
    df["away_goals"] = df["away_goals"].astype(int)
    df["result"] = np.select(
        [df["home_goals"] > df["away_goals"], df["home_goals"] < df["away_goals"]],
        ["H", "A"],
        default="D",
    )
    # FootyStats uses 0 for missing odds.
    for col in ("odds_home", "odds_draw", "odds_away"):
        df[col] = df[col].where(df[col] > 0)

    df["match_id"] = [
        f"{d:%Y%m%d}_{_slug(h)}_{_slug(a)}"
        for d, h, a in zip(df["date"], df["home_team"], df["away_team"])
    ]
    cols = [
        "match_id", "season", "kickoff_utc", "date", "matchweek",
        "home_team", "away_team", "home_goals", "away_goals", "result",
        "odds_home", "odds_draw", "odds_away",
    ]
    df = df[cols].sort_values(["kickoff_utc", "match_id"]).reset_index(drop=True)
    if df["match_id"].duplicated().any():
        dups = df.loc[df["match_id"].duplicated(keep=False), "match_id"].tolist()
        raise ValueError(f"Duplicate match ids: {dups[:5]}")
    return df


def validate_matches(matches: pd.DataFrame) -> list[str]:
    """Return problems that would make a season incomplete or inconsistent."""
    issues = []
    for season, g in matches.groupby("season"):
        teams = pd.concat([g["home_team"], g["away_team"]])
        if len(g) != 380:
            issues.append(f"{season}: {len(g)} completed matches, expected 380")
        if teams.nunique() != 20:
            issues.append(f"{season}: {teams.nunique()} teams, expected 20")
        games = teams.value_counts()
        odd = games[games != 38]
        if len(odd):
            issues.append(f"{season}: teams without 38 matches: {odd.to_dict()}")
        pairs = g.groupby(["home_team", "away_team"]).size()
        if (pairs > 1).any():
            issues.append(f"{season}: repeated home/away pairings: {pairs[pairs > 1].index.tolist()}")
    return issues


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------


def load_players(raw_dir: Path = RAW_DIR, seasons=None, min_minutes: int = 1) -> pd.DataFrame:
    """One row per player and season, with season totals.

    Players below ``min_minutes`` are dropped. FootyStats lists the whole
    registered squad, so many rows have zero league minutes; keeping them
    would also create false name clashes during lineup matching.
    """
    files = _select_seasons(find_raw_files(raw_dir)["players"], seasons, "player")
    if not files:
        raise FileNotFoundError(f"No player files in {raw_dir}. See data/README.md.")

    frames = []
    for season, path in files.items():
        raw = pd.read_csv(path)
        missing = set(PLAYER_COLUMNS) - set(raw.columns)
        if missing:
            raise ValueError(f"{path.name} is missing columns {sorted(missing)}")
        df = raw[list(PLAYER_COLUMNS)].rename(columns=PLAYER_COLUMNS)
        df.insert(0, "season", season)
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)

    df = df[df["minutes"] >= min_minutes].copy()
    unknown_pos = set(df["position"]) - set(POSITIONS)
    if unknown_pos:
        raise ValueError(f"Unknown positions: {sorted(unknown_pos)}")
    df["team"] = canonical_teams(df["team"])
    df["player_id"] = [make_player_id(n, b) for n, b in zip(df["full_name"], df["birthday"])]
    df["name_norm"] = df["full_name"].map(normalize_name)
    df = df.drop(columns="birthday")

    if df.duplicated(["season", "player_id"]).any():
        dups = df.loc[df.duplicated(["season", "player_id"], keep=False), ["season", "full_name", "team"]]
        raise ValueError(f"Player listed twice in one season:\n{dups}")

    front = ["season", "player_id", "full_name", "name_norm", "team", "position"]
    return df[front + [c for c in df.columns if c not in front]].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Lineups
# ---------------------------------------------------------------------------


def load_lineups(lineup_dir: Path = RAW_DIR / "lineups") -> pd.DataFrame:
    """Read every CSV in ``lineup_dir``: one row per player in a match lineup.

    Required columns are ``date``, ``team`` and ``player_name``. An optional
    ``started`` column (1 for starters, 0 for substitutes) is kept. See
    data/README.md for the format.
    """
    paths = sorted(Path(lineup_dir).glob("*.csv"))
    if not paths:
        raise FileNotFoundError(f"No lineup files in {lineup_dir}. See data/README.md.")
    frames = []
    for path in paths:
        df = pd.read_csv(path)
        missing = set(LINEUP_COLUMNS) - set(df.columns)
        if missing:
            raise ValueError(f"{path.name} is missing columns {sorted(missing)}")
        keep = list(LINEUP_COLUMNS) + (["started"] if "started" in df.columns else [])
        frames.append(df[keep].assign(source_file=path.name))
    df = pd.concat(frames, ignore_index=True)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df["team"] = canonical_teams(df["team"])
    df["player_name"] = df["player_name"].astype(str).str.strip()
    if "started" not in df.columns:
        df["started"] = 1
    return df.drop_duplicates(["date", "team", "player_name"]).reset_index(drop=True)


def attach_matches(lineups: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    """Add ``match_id``, ``season`` and ``side`` (home/away) to lineup rows.

    A lineup row joins a match when its date and team equal the match date and
    either the home or away team. Rows that join no match keep ``match_id``
    as missing so they can be reported, not silently dropped.
    """
    keys = ["match_id", "season", "date"]
    home = matches[keys + ["home_team"]].rename(columns={"home_team": "team"}).assign(side="home")
    away = matches[keys + ["away_team"]].rename(columns={"away_team": "team"}).assign(side="away")
    sides = pd.concat([home, away], ignore_index=True)
    if sides.duplicated(["date", "team"]).any():
        raise ValueError("A team has two matches on the same date")
    return lineups.merge(sides, on=["date", "team"], how="left", validate="many_to_one")


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------


def coverage(raw_dir: Path = RAW_DIR) -> pd.DataFrame:
    """Rows available per season for each source."""
    files = find_raw_files(raw_dir)
    lineup_dir = Path(raw_dir) / "lineups"
    lineup_counts: dict[str, int] = {}
    if lineup_dir.is_dir() and any(lineup_dir.glob("*.csv")) and files["matches"]:
        joined = attach_matches(load_lineups(lineup_dir), load_matches(raw_dir))
        lineup_counts = joined.dropna(subset=["match_id"]).groupby("season")["match_id"].nunique().to_dict()

    rows = []
    for season in SEASONS:
        m = files["matches"].get(season)
        p = files["players"].get(season)
        rows.append(
            {
                "season": season,
                "matches": len(load_matches(raw_dir, [season])) if m else 0,
                "players": len(load_players(raw_dir, [season])) if p else 0,
                "matches_with_lineups": lineup_counts.get(season, 0),
            }
        )
    return pd.DataFrame(rows).set_index("season")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report which raw data is available.")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    args = parser.parse_args(argv)

    table = coverage(args.raw_dir)
    print(table.to_string())
    issues = []
    if (table["matches"] > 0).any():
        issues = validate_matches(load_matches(args.raw_dir))
    for issue in issues:
        print("WARNING:", issue)

    missing = table.index[(table[["matches", "players", "matches_with_lineups"]] == 0).any(axis=1)]
    if len(missing):
        print(f"\nIncomplete seasons: {', '.join(missing)}. See data/README.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
