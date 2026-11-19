"""Checks on the real FootyStats files. Skipped when data/raw is empty."""

import pytest

from src.load import find_raw_files, load_matches, load_players, validate_matches

FILES = find_raw_files()
needs_matches = pytest.mark.skipif(not FILES["matches"], reason="no match files in data/raw")
needs_players = pytest.mark.skipif(not FILES["players"], reason="no player files in data/raw")


@needs_matches
def test_every_available_season_is_complete():
    assert validate_matches(load_matches()) == []


@needs_players
def test_players_load_for_every_available_season():
    players = load_players()
    assert set(players["season"]) == set(FILES["players"])
    assert players["player_id"].notna().all()
    # Each season should have 20 clubs.
    assert players.groupby("season")["team"].nunique().eq(20).all()
