from __future__ import annotations

from datetime import UTC, datetime


def _current_nba_season_label() -> str:
    """NBA/WNBA seasons: WNBA is a single calendar year; NBA spans two."""
    now = datetime.now(UTC)
    year = now.year
    return f"{year}-{str(year + 1)[2:]}"


def get_league_advanced_team_stats(league_id: str, season: str | None = None) -> dict:
    """Return {team_name: {off_rating, def_rating, net_rating, pace}} for a league/season.

    Uses nba_api's league-wide advanced team stats (real per-team offensive/
    defensive rating and pace) instead of ESPN's per-team statistics endpoint,
    which does not expose points-allowed or pace fields for either NBA or
    WNBA -- those factors would otherwise silently fall back to identical
    placeholder values for both teams in every game, contributing no real
    signal to the weighted score. One bulk call covers the whole league, so
    callers should fetch it once per report build, not once per team.
    """
    from nba_api.stats.endpoints import leaguedashteamstats

    if season is None:
        season = _current_nba_season_label() if league_id == "00" else str(datetime.now(UTC).year)

    try:
        stats = leaguedashteamstats.LeagueDashTeamStats(
            season=season,
            league_id_nullable=league_id,
            season_type_all_star="Regular Season",
            measure_type_detailed_defense="Advanced",
        )
        df = stats.get_data_frames()[0]
    except Exception:
        return {}

    result = {}
    for _, row in df.iterrows():
        try:
            result[str(row["TEAM_NAME"])] = {
                "off_rating": float(row["OFF_RATING"]),
                "def_rating": float(row["DEF_RATING"]),
                "net_rating": float(row["NET_RATING"]),
                "pace": float(row["PACE"]),
            }
        except (KeyError, TypeError, ValueError):
            continue
    return result


def league_average_pace(team_stats: dict, default: float = 99.0) -> float:
    paces = [v["pace"] for v in team_stats.values() if v.get("pace")]
    return round(sum(paces) / len(paces), 2) if paces else default
