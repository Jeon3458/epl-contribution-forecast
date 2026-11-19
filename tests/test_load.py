from datetime import date

import pandas as pd
import pytest

from src import load
from src.load import (
    MATCH_COLUMNS,
    PLAYER_COLUMNS,
    attach_matches,
    find_raw_files,
    load_lineups,
    load_matches,
    load_players,
    validate_matches,
)


def _write_matches(raw_dir, season_start, rows):
    df = pd.DataFrame(rows)
    for col in MATCH_COLUMNS:
        if col not in df:
            df[col] = 0
    path = raw_dir / f"england-premier-league-matches-{season_start}-to-{season_start + 1}-stats.csv"
    df.to_csv(path, index=False)


def _write_players(raw_dir, season_start, rows):
    df = pd.DataFrame(rows)
    for col in PLAYER_COLUMNS:
        if col not in df:
            df[col] = 0
    path = raw_dir / f"england-premier-league-players-{season_start}-to-{season_start + 1}-stats.csv"
    df.to_csv(path, index=False)


def _match(ts, home, away, hg, ag, status="complete"):
    return {
        "timestamp": ts, "status": status, "Game Week": 1,
        "home_team_name": home, "away_team_name": away,
        "home_team_goal_count": hg, "away_team_goal_count": ag,
        "odds_ft_home_team_win": 2.0, "odds_ft_draw": 3.0, "odds_ft_away_team_win": 0,
    }


@pytest.fixture
def raw_dir(tmp_path):
    _write_matches(
        tmp_path,
        2023,
        [
            _match(1691780400, "Burnley", "Manchester City", 0, 3),         # 2023-08-11 19:00 UTC
            _match(1691841600, "Arsenal", "Nottingham Forest", 2, 1),       # 2023-08-12
            _match(1691848800, "AFC Bournemouth", "West Ham United", 1, 1),  # 2023-08-12
            _match(1691935200, "Chelsea", "Liverpool", 0, 0, status="suspended"),
        ],
    )
    _write_players(
        tmp_path,
        2023,
        [
            {"full_name": "Declan Rice", "birthday": 948931200, "position": "Midfielder",
             "Current Club": "Arsenal", "minutes_played_overall": 3000},
            {"full_name": "Unused Squad Player", "birthday": 1000000000, "position": "Defender",
             "Current Club": "Arsenal", "minutes_played_overall": 0},
        ],
    )
    (tmp_path / "notes.csv").write_text("ignored\n")
    return tmp_path


def test_find_raw_files(raw_dir):
    files = find_raw_files(raw_dir)
    assert list(files["matches"]) == ["2023-2024"]
    assert list(files["players"]) == ["2023-2024"]


def test_load_matches(raw_dir):
    m = load_matches(raw_dir)
    assert len(m) == 3  # suspended match dropped
    assert m["result"].tolist() == ["A", "H", "D"]
    assert m["date"].tolist() == [date(2023, 8, 11), date(2023, 8, 12), date(2023, 8, 12)]
    assert m.loc[0, "match_id"] == "20230811_burnley_manchester-city"
    assert m["season"].unique().tolist() == ["2023-2024"]
    assert m["odds_away"].isna().all()  # 0 means missing


def test_load_matches_missing_season(raw_dir):
    with pytest.raises(FileNotFoundError, match="2020-2021"):
        load_matches(raw_dir, seasons=["2020-2021"])


def test_load_players(raw_dir):
    p = load_players(raw_dir)
    assert p["full_name"].tolist() == ["Declan Rice"]  # zero-minute player dropped
    assert p.loc[0, "player_id"] == "declan-rice_20000127"
    assert {"minutes", "tackles", "key_passes", "goals_conceded"} <= set(p.columns)


def test_validate_matches_flags_short_season(raw_dir):
    issues = validate_matches(load_matches(raw_dir))
    assert any("expected 380" in i for i in issues)


def test_lineups_join_matches(raw_dir):
    lineup_dir = raw_dir / "lineups"
    lineup_dir.mkdir()
    pd.DataFrame(
        {
            "date": ["2023-08-12", "2023-08-12", "2023-08-12", "2023-08-20"],
            "team": ["Arsenal", "Nott'm Forest", "Bournemouth", "Arsenal"],
            "player_name": ["D. Rice", "M. Gibbs-White", "D. Solanke", "D. Rice"],
        }
    ).to_csv(lineup_dir / "epl23.csv", index=False)

    lineups = load_lineups(lineup_dir)
    assert lineups["started"].eq(1).all()
    joined = attach_matches(lineups, load_matches(raw_dir))
    assert joined["side"].tolist()[:3] == ["home", "away", "home"]
    assert joined.loc[0, "match_id"] == "20230812_arsenal_nottingham-forest"
    assert pd.isna(joined.loc[3, "match_id"])  # no match on that date


def test_coverage_report(raw_dir, capsys):
    assert load.main(["--raw-dir", str(raw_dir)]) == 0
    out = capsys.readouterr().out
    assert "2023-2024" in out
    assert "expected 380" in out
