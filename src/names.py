"""Name normalisation and matching for teams and players.

Team names are mapped to the names FootyStats uses in its match and player
files. Unknown team names raise an error instead of being dropped silently.

Player names from lineup sources rarely match the FootyStats ``full_name``
exactly ("D. Rice", "Bernard" for "Bernard Anício Caldeira Duarte"). The
matcher tries a fixed sequence of rules and records which rule produced each
match, so the share of uncertain matches can be reported.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

import pandas as pd

# Letters that NFKD does not decompose into an ASCII base letter.
_SPECIAL_LETTERS = str.maketrans(
    {
        "ø": "o", "Ø": "O", "đ": "d", "Đ": "D", "ł": "l", "Ł": "L",
        "ß": "ss", "æ": "ae", "Æ": "AE", "œ": "oe", "Œ": "OE", "ı": "i",
    }
)


def normalize_name(name: object) -> str:
    """Lowercase ASCII form of a name with punctuation turned into spaces.

    >>> normalize_name("Martin Ødegaard")
    'martin odegaard'
    >>> normalize_name("Aaron Wan-Bissaka")
    'aaron wan bissaka'
    """
    if not isinstance(name, str):
        return ""
    s = unicodedata.normalize("NFKD", name.translate(_SPECIAL_LETTERS))
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return " ".join(s.split())


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------

#: Team names as they appear in the FootyStats files (2020/21 to 2024/25).
CANONICAL_TEAMS = (
    "AFC Bournemouth", "Arsenal", "Aston Villa", "Brentford",
    "Brighton & Hove Albion", "Burnley", "Chelsea", "Crystal Palace",
    "Everton", "Fulham", "Ipswich Town", "Leeds United", "Leicester City",
    "Liverpool", "Luton Town", "Manchester City", "Manchester United",
    "Newcastle United", "Norwich City", "Nottingham Forest",
    "Sheffield United", "Southampton", "Tottenham Hotspur", "Watford",
    "West Bromwich Albion", "West Ham United", "Wolverhampton Wanderers",
)

#: Short or alternative names seen in lineup sources, including the forms
#: used in the Version 1 notebook.
TEAM_ALIASES = {
    "Bournemouth": "AFC Bournemouth",
    "Brighton": "Brighton & Hove Albion",
    "Brighton and Hove Albion": "Brighton & Hove Albion",
    "Ipswich": "Ipswich Town",
    "Leeds": "Leeds United",
    "Leicester": "Leicester City",
    "Luton": "Luton Town",
    "Man City": "Manchester City",
    "Man Utd": "Manchester United",
    "Man United": "Manchester United",
    "Manchester Utd": "Manchester United",
    "Newcastle": "Newcastle United",
    "Newcastle Utd": "Newcastle United",
    "Norwich": "Norwich City",
    "Nott'm Forest": "Nottingham Forest",
    "Nottm Forest": "Nottingham Forest",
    "Sheffield Utd": "Sheffield United",
    "Spurs": "Tottenham Hotspur",
    "Tottenham": "Tottenham Hotspur",
    "West Brom": "West Bromwich Albion",
    "West Ham": "West Ham United",
    "Wolves": "Wolverhampton Wanderers",
    "Wolverhampton": "Wolverhampton Wanderers",
}

_TEAM_LOOKUP = {normalize_name(t): t for t in CANONICAL_TEAMS}
_TEAM_LOOKUP.update({normalize_name(k): v for k, v in TEAM_ALIASES.items()})


class UnknownTeamError(ValueError):
    """Raised when a team name has no canonical mapping."""


def canonical_team(name: str) -> str:
    """Map any known spelling of a team to its FootyStats name."""
    try:
        return _TEAM_LOOKUP[normalize_name(name)]
    except KeyError:
        raise UnknownTeamError(
            f"Unknown team name {name!r}. Add it to TEAM_ALIASES in src/names.py."
        ) from None


def canonical_teams(names: pd.Series) -> pd.Series:
    """Vectorised :func:`canonical_team` that reports every unknown name at once."""
    unique = pd.unique(names.dropna())
    mapping, unknown = {}, []
    for n in unique:
        try:
            mapping[n] = canonical_team(n)
        except UnknownTeamError:
            unknown.append(n)
    if unknown:
        raise UnknownTeamError(
            f"Unknown team names {sorted(unknown)}. Add them to TEAM_ALIASES in src/names.py."
        )
    return names.map(mapping)


# ---------------------------------------------------------------------------
# Players
# ---------------------------------------------------------------------------


def make_player_id(full_name: str, birthday_ts: float) -> str:
    """Stable player key across seasons: normalised name plus date of birth.

    Two different players can share a name in the same season (for example
    two "Ben Davies" in 2020/21), so the name alone is not a key.
    """
    born = pd.Timestamp(int(birthday_ts), unit="s", tz="UTC").strftime("%Y%m%d")
    return f"{normalize_name(full_name).replace(' ', '-')}_{born}"


@dataclass(frozen=True)
class PlayerMatch:
    player_id: str | None
    method: str
    score: float


#: Methods in the order they are tried. ``ambiguous`` and ``unmatched`` mean no id.
MATCH_METHODS = (
    "alias", "exact_team", "exact_season", "initial_surname",
    "token_subset", "fuzzy", "ambiguous", "unmatched",
)


@dataclass(frozen=True)
class _Candidate:
    player_id: str
    norm: str
    tokens: tuple[str, ...]


class PlayerMatcher:
    """Match lineup names to FootyStats players of the same season.

    Rules, tried in order (each must give exactly one candidate):

    1. ``alias``: a manual override from the alias table.
    2. ``exact_team``: same normalised name, same team and season.
    3. ``exact_season``: same normalised name, any team that season. FootyStats
       lists a player under the club he ended the season with, so a January
       transfer appears under the new club for the whole season.
    4. ``initial_surname``: "D. Rice" style, same team.
    5. ``token_subset``: every token of one name appears in the other, same
       team ("Bernard" and "Bernard Anício Caldeira Duarte").
    6. ``fuzzy``: string similarity above ``fuzzy_threshold``, same team, and
       clearly better than the runner-up.

    Rules 4 to 6 stay inside the team to avoid matching a different player
    with a similar name at another club.
    """

    def __init__(
        self,
        players: pd.DataFrame,
        aliases: pd.DataFrame | None = None,
        fuzzy_threshold: float = 0.85,
        fuzzy_margin: float = 0.05,
    ) -> None:
        required = {"season", "team", "player_id", "full_name"}
        missing = required - set(players.columns)
        if missing:
            raise ValueError(f"players is missing columns {sorted(missing)}")

        self.fuzzy_threshold = fuzzy_threshold
        self.fuzzy_margin = fuzzy_margin
        self._by_team: dict[tuple[str, str], list[_Candidate]] = {}
        self._by_season: dict[str, list[_Candidate]] = {}
        for row in players[list(required)].drop_duplicates().itertuples(index=False):
            norm = normalize_name(row.full_name)
            cand = _Candidate(row.player_id, norm, tuple(norm.split()))
            self._by_team.setdefault((row.season, row.team), []).append(cand)
            self._by_season.setdefault(row.season, []).append(cand)

        self._aliases: dict[tuple[str, str | None], str] = {}
        if aliases is not None:
            for row in aliases.itertuples(index=False):
                team = getattr(row, "team", None)
                team = canonical_team(team) if isinstance(team, str) and team else None
                self._aliases[(normalize_name(row.source_name), team)] = normalize_name(row.full_name)

        self._cache: dict[tuple[str, str, str], PlayerMatch] = {}

    def match(self, name: str, team: str, season: str) -> PlayerMatch:
        key = (name, team, season)
        if key not in self._cache:
            self._cache[key] = self._match(name, team, season)
        return self._cache[key]

    def _match(self, name: str, team: str, season: str) -> PlayerMatch:
        query = normalize_name(name)
        if not query:
            return PlayerMatch(None, "unmatched", 0.0)
        team_cands = self._by_team.get((season, team), [])

        alias = self._aliases.get((query, team)) or self._aliases.get((query, None))
        if alias is not None:
            hits = [c for c in team_cands if c.norm == alias] or [
                c for c in self._by_season.get(season, []) if c.norm == alias
            ]
            if len(hits) == 1:
                return PlayerMatch(hits[0].player_id, "alias", 1.0)
            query = alias

        hits = [c for c in team_cands if c.norm == query]
        if hits:
            return self._unique(hits, "exact_team", 1.0)

        hits = [c for c in self._by_season.get(season, []) if c.norm == query]
        if hits:
            return self._unique(hits, "exact_season", 1.0)

        q_tokens = tuple(query.split())

        if len(q_tokens) >= 2 and len(q_tokens[0]) == 1:
            initial, rest = q_tokens[0], q_tokens[1:]
            hits = [
                c for c in team_cands
                if len(c.tokens) > len(rest)
                and c.tokens[0].startswith(initial)
                and c.tokens[-len(rest):] == rest
            ]
            if hits:
                return self._unique(hits, "initial_surname", 0.9)

        q_set = set(q_tokens)
        hits = [
            c for c in team_cands
            if q_set <= set(c.tokens) or set(c.tokens) <= q_set
        ]
        if hits:
            return self._unique(hits, "token_subset", 0.8)

        scored = sorted(
            ((SequenceMatcher(None, query, c.norm).ratio(), c) for c in team_cands),
            key=lambda t: t[0],
            reverse=True,
        )
        if scored and scored[0][0] >= self.fuzzy_threshold:
            runner_up = scored[1][0] if len(scored) > 1 else 0.0
            if scored[0][0] - runner_up >= self.fuzzy_margin:
                return PlayerMatch(scored[0][1].player_id, "fuzzy", round(scored[0][0], 3))
            return PlayerMatch(None, "ambiguous", round(scored[0][0], 3))

        return PlayerMatch(None, "unmatched", 0.0)

    @staticmethod
    def _unique(hits: list[_Candidate], method: str, score: float) -> PlayerMatch:
        ids = {c.player_id for c in hits}
        if len(ids) == 1:
            return PlayerMatch(ids.pop(), method, score)
        return PlayerMatch(None, "ambiguous", score)

    def match_frame(
        self,
        df: pd.DataFrame,
        name_col: str = "player_name",
        team_col: str = "team",
        season_col: str = "season",
    ) -> pd.DataFrame:
        """Return ``df`` with ``player_id``, ``match_method`` and ``match_score`` added."""
        results = [
            self.match(n, t, s)
            for n, t, s in zip(df[name_col], df[team_col], df[season_col])
        ]
        out = df.copy()
        out["player_id"] = [r.player_id for r in results]
        out["match_method"] = pd.Categorical(
            [r.method for r in results], categories=MATCH_METHODS
        )
        out["match_score"] = [r.score for r in results]
        return out


def match_summary(matched: pd.DataFrame) -> pd.DataFrame:
    """Count and share of rows per match method."""
    counts = matched["match_method"].value_counts(sort=False)
    return pd.DataFrame({"rows": counts, "share": (counts / counts.sum()).round(4)})
