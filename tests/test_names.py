import pandas as pd
import pytest

from src.names import (
    PlayerMatcher,
    UnknownTeamError,
    canonical_team,
    canonical_teams,
    make_player_id,
    match_summary,
    normalize_name,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Martin Ødegaard", "martin odegaard"),
        ("Aleksandar Mitrović", "aleksandar mitrovic"),
        ("Aaron Wan-Bissaka", "aaron wan bissaka"),
        ("D. Rice", "d rice"),
        ("  Dara  O'Shea ", "dara o shea"),
        ("Jakub Kiwior", "jakub kiwior"),
        ("Łukasz Fabiański", "lukasz fabianski"),
        (None, ""),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Man City", "Manchester City"),
        ("Spurs", "Tottenham Hotspur"),
        ("Brighton", "Brighton & Hove Albion"),
        ("Brighton and Hove Albion", "Brighton & Hove Albion"),
        ("Bournemouth", "AFC Bournemouth"),
        ("Nott'm Forest", "Nottingham Forest"),
        ("wolverhampton wanderers", "Wolverhampton Wanderers"),
        ("Arsenal", "Arsenal"),
    ],
)
def test_canonical_team(raw, expected):
    assert canonical_team(raw) == expected


def test_unknown_team_raises_with_all_names():
    with pytest.raises(UnknownTeamError) as err:
        canonical_teams(pd.Series(["Arsenal", "Real Madrid", "Barcelona"]))
    assert "Barcelona" in str(err.value) and "Real Madrid" in str(err.value)


def test_player_id_separates_namesakes():
    a = make_player_id("Ben Davies", 735609600)  # 1993-04-24
    b = make_player_id("Ben Davies", 783648000)  # 1994-11-01
    assert a == "ben-davies_19930424"
    assert a != b


@pytest.fixture
def players():
    rows = [
        ("2023-2024", "Arsenal", "declan-rice", "Declan Rice"),
        ("2023-2024", "Arsenal", "martin-odegaard", "Martin Ødegaard"),
        ("2023-2024", "Arsenal", "gabriel-jesus", "Gabriel Fernando de Jesus"),
        ("2023-2024", "Arsenal", "gabriel-martinelli", "Gabriel Martinelli Silva"),
        ("2023-2024", "Chelsea", "reece-james", "Reece James"),
        ("2023-2024", "Chelsea", "daniel-james", "Daniel James"),
        ("2023-2024", "Everton", "bernard", "Bernard Anício Caldeira Duarte"),
        ("2023-2024", "Everton", "dominic-calvert-lewin", "Dominic Calvert-Lewin"),
        ("2023-2024", "Fulham", "aleksandar-mitrovic", "Aleksandar Mitrović"),
        ("2020-2021", "Liverpool", "ben-davies-lfc", "Ben Davies"),
        ("2020-2021", "Tottenham Hotspur", "ben-davies-spurs", "Ben Davies"),
    ]
    return pd.DataFrame(rows, columns=["season", "team", "player_id", "full_name"])


@pytest.mark.parametrize(
    "name, team, season, pid, method",
    [
        ("Declan Rice", "Arsenal", "2023-2024", "declan-rice", "exact_team"),
        ("Martin Odegaard", "Arsenal", "2023-2024", "martin-odegaard", "exact_team"),
        ("Declan Rice", "Chelsea", "2023-2024", "declan-rice", "exact_season"),
        ("D. Rice", "Arsenal", "2023-2024", "declan-rice", "initial_surname"),
        ("D. Calvert-Lewin", "Everton", "2023-2024", "dominic-calvert-lewin", "initial_surname"),
        ("Bernard", "Everton", "2023-2024", "bernard", "token_subset"),
        ("Aleksandar Mitrovich", "Fulham", "2023-2024", "aleksandar-mitrovic", "fuzzy"),
        ("Ben Davies", "Tottenham Hotspur", "2020-2021", "ben-davies-spurs", "exact_team"),
    ],
)
def test_matcher_rules(players, name, team, season, pid, method):
    result = PlayerMatcher(players).match(name, team, season)
    assert (result.player_id, result.method) == (pid, method)


def test_matcher_refuses_ambiguous_names(players):
    m = PlayerMatcher(players)
    assert m.match("James", "Chelsea", "2023-2024").method == "ambiguous"
    assert m.match("Gabriel", "Arsenal", "2023-2024").method == "ambiguous"
    # Same name at two clubs, and the lineup team is neither of them.
    assert m.match("Ben Davies", "Arsenal", "2020-2021").method == "ambiguous"


def test_matcher_does_not_guess_across_teams(players):
    # Abbreviated and fuzzy rules stay inside the team.
    result = PlayerMatcher(players).match("D. Rice", "Chelsea", "2023-2024")
    assert result.method == "unmatched"
    assert result.player_id is None


def test_alias_override(players):
    aliases = pd.DataFrame(
        {"source_name": ["Gabriel Jesus"], "full_name": ["Gabriel Fernando de Jesus"], "team": ["Arsenal"]}
    )
    result = PlayerMatcher(players, aliases=aliases).match("Gabriel Jesus", "Arsenal", "2023-2024")
    assert (result.player_id, result.method) == ("gabriel-jesus", "alias")


def test_match_frame_and_summary(players):
    lineup = pd.DataFrame(
        {
            "player_name": ["D. Rice", "James", "Nobody Here"],
            "team": ["Arsenal", "Chelsea", "Arsenal"],
            "season": ["2023-2024"] * 3,
        }
    )
    out = PlayerMatcher(players).match_frame(lineup)
    assert out.loc[0, "player_id"] == "declan-rice"
    assert out.loc[1:, "player_id"].isna().all()
    summary = match_summary(out)
    assert summary.loc["initial_surname", "rows"] == 1
    assert summary.loc["ambiguous", "rows"] == 1
    assert summary.loc["unmatched", "rows"] == 1
    assert summary["share"].sum() == pytest.approx(1.0, abs=1e-3)  # shares are rounded
