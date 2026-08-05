import pandas as pd
from pathlib import Path

from bot.market_compare import normalize_matchup, normalize_team_name
from sports.dates import current_slate_date_str
from sports.mlb_pitching import get_pitcher_handedness
from sports.mlb_schedule import build_probable_pitcher_map
from sports.prop_probability import evaluate_prop_side, is_suspiciously_large_edge, shrunk_rate_per_game

ROOT = Path(__file__).resolve().parent

STATS = ROOT / "logs" / "mlb_player_stats.csv"
PROPS = ROOT / "logs" / "mlb_player_props.csv"
OUT = ROOT / "logs" / "mlb_enhanced_props.csv"

# Market -> (required stat role, display rate column, probability rate column).
# Batter and pitcher rate stats live on separate rows for the same player
# name, so lookups are keyed by (player, role) instead of a blind merge --
# a two-way player like Ohtani has both a batter row and a pitcher row.
#
# total_bases is a compound stat (a double is worth 2 "bases", a HR worth 4,
# all from a single event), so it isn't shaped like a Poisson count the way
# hits/home runs/strikeouts are. hits_per_game is only a valid probability
# proxy for the *0.5* line specifically, where clearing it is exactly
# "getting at least one hit" -- for any higher line (1.5+), a single extra-
# base hit alone can clear it, so modeling that as "needs N separate hits"
# systematically *understates* power hitters' true probability (see
# stat_rates_for_market). There's no trustworthy per-game rate for those
# higher lines with the data currently collected, so they get no probability
# estimate at all rather than a wrong one.
MARKET_STAT_MAP = {
    "batter_hits": ("batter", "hits_per_game", "hits_per_game"),
    "batter_home_runs": ("batter", "home_runs_per_game", "home_runs_per_game"),
    "batter_rbis": ("batter", "rbi_per_game", "rbi_per_game"),
    "batter_runs_scored": ("batter", "runs_per_game", "runs_per_game"),
    "batter_total_bases": ("batter", "total_bases_per_game", "hits_per_game"),
    "batter_walks": ("batter", "walks_per_game", "walks_per_game"),
    "batter_strikeouts": ("batter", "strikeouts_per_game", "strikeouts_per_game"),
    "pitcher_strikeouts": ("pitcher", "strikeouts_per_start", "strikeouts_per_start"),
    "pitcher_hits_allowed": ("pitcher", "hits_allowed_per_start", "hits_allowed_per_start"),
    "pitcher_walks": ("pitcher", "walks_per_start", "walks_per_start"),
    "pitcher_earned_runs": ("pitcher", "earned_runs_per_start", "earned_runs_per_start"),
}

# total_bases probability is only valid at this exact threshold -- see the
# MARKET_STAT_MAP comment above.
TOTAL_BASES_HITS_PROXY_MAX_LINE = 0.5

# batter market -> the vs_lhp_*/vs_rhp_* split-stat suffix in mlb_player_stats.csv
# used for opponent-handedness-adjusted probability. Pitcher markets aren't
# covered (no batter-side handedness split data is fetched), and this is only
# used for the probability rate, never the displayed season projection.
MARKET_SPLIT_STAT_KEY = {
    "batter_hits": "hits",
    "batter_home_runs": "hr",
    "batter_rbis": "rbi",
    "batter_runs_scored": "runs",
    "batter_total_bases": "hits",  # same hits-proxy reasoning as MARKET_STAT_MAP
    "batter_walks": "bb",
    "batter_strikeouts": "so",
}


def build_stat_lookup(stats: pd.DataFrame) -> dict:
    lookup = {}
    for _, row in stats.iterrows():
        lookup[(row.get("player_key", ""), row.get("role", ""))] = row
    return lookup


def build_opponent_hand_lookup(props: pd.DataFrame, stats: pd.DataFrame, pitcher_map: dict, handedness_by_pitcher_id: dict) -> dict:
    """Map each batter's player_key to the throwing hand of tonight's
    opposing probable starter, or None if it can't be determined.

    `pitcher_map` and `handedness_by_pitcher_id` are pre-fetched plain dicts
    so this stays a pure function -- network calls happen in main()/the
    fetch helpers below, not here, so this is directly unit-testable.
    """
    # Derive player_key from "player" directly rather than trusting the
    # caller to have already added it -- stats and props are often read
    # fresh from CSV right before this is called, with no player_key column
    # yet, and a silent empty-string key here would make every lookup miss.
    team_by_player_key = {
        str(row.get("player", "")).lower().strip(): row.get("team", "")
        for _, row in stats.iterrows()
        if row.get("role") == "batter"
    }

    # Index the pitcher map by normalized matchup so it can be matched
    # against props' matchup strings, which come from a different source
    # (the odds API) than the pitcher map (MLB's own schedule) and may not
    # be byte-identical even for the same real game.
    normalized_pitcher_map = {}
    for matchup, entry in pitcher_map.items():
        if not matchup:
            continue
        away_name, _, home_name = matchup.partition(" at ")
        normalized_pitcher_map[normalize_matchup(matchup)] = {
            "home_team": normalize_team_name(home_name),
            "away_team": normalize_team_name(away_name),
            "home_pitcher_id": entry.get("home_pitcher_id"),
            "away_pitcher_id": entry.get("away_pitcher_id"),
        }

    result = {}
    seen_players = set()
    for _, row in props.iterrows():
        player_key = str(row.get("player", "")).lower().strip()
        if not player_key or player_key in seen_players:
            continue
        seen_players.add(player_key)
        team = team_by_player_key.get(player_key, "")
        if not team:
            continue
        entry = normalized_pitcher_map.get(normalize_matchup(row.get("matchup", "")))
        if not entry:
            continue
        team_norm = normalize_team_name(team)
        if team_norm == entry["home_team"]:
            opposing_pitcher_id = entry["away_pitcher_id"]
        elif team_norm == entry["away_team"]:
            opposing_pitcher_id = entry["home_pitcher_id"]
        else:
            continue
        result[player_key] = handedness_by_pitcher_id.get(opposing_pitcher_id)
    return result


def fetch_opponent_hand_lookup(props: pd.DataFrame, stats: pd.DataFrame) -> dict:
    """I/O wrapper: fetch today's probable-pitcher map and look up each
    unique starter's throwing hand, then build the batter -> opposing-hand
    lookup. Failures degrade to an empty lookup (no adjustment applied,
    falls back to season rates) rather than raising."""
    try:
        pitcher_map = build_probable_pitcher_map(current_slate_date_str())
    except Exception:
        return {}

    pitcher_ids = set()
    for entry in pitcher_map.values():
        pitcher_ids.add(entry.get("home_pitcher_id"))
        pitcher_ids.add(entry.get("away_pitcher_id"))
    pitcher_ids.discard(None)

    handedness_by_pitcher_id = {pid: get_pitcher_handedness(pid) for pid in pitcher_ids}
    return build_opponent_hand_lookup(props, stats, pitcher_map, handedness_by_pitcher_id)


def stat_rates_for_market(stat_lookup: dict, player_key: str, market: str, line=None, opponent_hand: str | None = None):
    """Return (display_rate, probability_rate, games, role) for a market."""
    market = str(market)
    mapping = MARKET_STAT_MAP.get(market)
    if mapping is None:
        return None, None, None, None
    role, display_col, probability_col = mapping
    row = stat_lookup.get((player_key, role))
    if row is None:
        return None, None, None, role

    display_rate = row.get(display_col)
    display_rate = None if pd.isna(display_rate) else float(display_rate)

    if market == "batter_total_bases":
        try:
            line_value = float(line)
        except (TypeError, ValueError):
            line_value = None
        if line_value is None or line_value > TOTAL_BASES_HITS_PROXY_MAX_LINE:
            return display_rate, None, row.get("games"), role

    split_key = MARKET_SPLIT_STAT_KEY.get(market)
    if role == "batter" and split_key and opponent_hand in ("L", "R"):
        split_prefix = "vs_lhp" if opponent_hand == "L" else "vs_rhp"
        blended = shrunk_rate_per_game(
            row.get(f"season_{split_key}"), row.get("season_ab"),
            row.get(f"{split_prefix}_{split_key}"), row.get(f"{split_prefix}_ab"),
            row.get("games"),
        )
        if blended is not None:
            return display_rate, blended, row.get("games"), role

    probability_rate = row.get(probability_col)
    probability_rate = None if pd.isna(probability_rate) else float(probability_rate)
    return display_rate, probability_rate, row.get("games"), role


def confidence_from_edge(value_edge, expected_value):
    if value_edge is None or expected_value is None:
        return "LOW"
    if is_suspiciously_large_edge(value_edge):
        return "LOW"
    if value_edge >= 15 and expected_value >= 0.15:
        return "HIGH"
    if value_edge >= 7 and expected_value > 0:
        return "MEDIUM"
    return "LOW"


def build_enhanced_props(props: pd.DataFrame, stats: pd.DataFrame, opponent_hand_by_player: dict | None = None) -> pd.DataFrame:
    stats = stats.copy()
    props = props.copy()
    stats["player_key"] = stats["player"].astype(str).str.lower().str.strip()
    props["player_key"] = props["player"].astype(str).str.lower().str.strip()
    stat_lookup = build_stat_lookup(stats)
    opponent_hand_by_player = opponent_hand_by_player or {}

    # Look up the opposite side's odds within the same book/line so the
    # no-vig market probability reflects that specific book's own pricing.
    opposite_odds_lookup = {}
    for _, row in props.iterrows():
        key = (row.get("book"), row.get("market"), row.get("player_key"), row.get("line"), row.get("side"))
        opposite_odds_lookup[key] = row.get("odds")

    def opposite_side(side):
        side_norm = (side or "").strip().lower()
        if side_norm == "over":
            return "Under"
        if side_norm == "under":
            return "Over"
        return None

    display_rates, prob_rates, games_values, roles = [], [], [], []
    model_probs, market_probs, decimal_odds_values, value_edges, expected_values, confidences = [], [], [], [], [], []
    opponent_hands = []

    for _, row in props.iterrows():
        opponent_hand = opponent_hand_by_player.get(row.get("player_key", ""))
        display_rate, probability_rate, games, role = stat_rates_for_market(
            stat_lookup, row.get("player_key", ""), row.get("market", ""), row.get("line"), opponent_hand
        )
        opp_key = (row.get("book"), row.get("market"), row.get("player_key"), row.get("line"), opposite_side(row.get("side")))
        opposite_odds = opposite_odds_lookup.get(opp_key)

        evaluation = evaluate_prop_side(probability_rate, row.get("line"), row.get("side", ""), row.get("odds"), opposite_odds) \
            if probability_rate is not None else {
                "model_probability": None, "market_probability": None,
                "decimal_odds": None, "value_edge": None, "expected_value_per_unit": None,
            }

        display_rates.append(display_rate)
        prob_rates.append(probability_rate)
        games_values.append(games)
        roles.append(role)
        opponent_hands.append(opponent_hand)
        model_probs.append(evaluation["model_probability"])
        market_probs.append(evaluation["market_probability"])
        decimal_odds_values.append(evaluation["decimal_odds"])
        value_edges.append(evaluation["value_edge"])
        expected_values.append(evaluation["expected_value_per_unit"])
        confidences.append(confidence_from_edge(evaluation["value_edge"], evaluation["expected_value_per_unit"]))

    props["role"] = roles
    props["games"] = games_values
    props["projected_stat"] = display_rates
    props["probability_rate"] = prob_rates
    props["opponent_pitcher_hand"] = opponent_hands
    props["model_probability"] = model_probs
    props["market_probability"] = market_probs
    props["decimal_odds"] = decimal_odds_values
    props["value_edge"] = value_edges
    props["expected_value_per_unit"] = expected_values
    props["confidence"] = confidences
    props["sport"] = "mlb"
    return props


def main():
    stats = pd.read_csv(STATS)
    props = pd.read_csv(PROPS)
    props["player_key"] = props["player"].astype(str).str.lower().str.strip()
    opponent_hand_by_player = fetch_opponent_hand_lookup(props, stats)
    merged = build_enhanced_props(props, stats, opponent_hand_by_player)
    merged.to_csv(OUT, index=False)
    matched = sum(1 for v in opponent_hand_by_player.values() if v)
    print(f"mlb enhanced props written: {len(merged)} (opponent hand resolved for {matched} batters)")
    print(OUT)


if __name__ == "__main__":
    main()
