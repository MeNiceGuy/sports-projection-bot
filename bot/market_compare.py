from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from sports.model_utils import probability_from_score_gap

ROOT = Path(__file__).resolve().parents[1]
REPORT_PATH = ROOT / "reports" / "daily_projection_report.json"
MARKET_LINES = ROOT / "logs" / "market_lines.csv"
OUT = ROOT / "reports" / "market_comparison_report.json"


EDGE_BAND_RANK = {"weak": 0, "moderate": 1, "strong": 2}
DEFAULT_MAX_LINE_AGE_HOURS = 12


def safe_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def american_to_implied_prob(odds):
    odds = safe_float(odds)
    if odds is None:
        return None
    if odds > 0:
        return round(100 / (odds + 100), 4)
    if odds < 0:
        return round(abs(odds) / (abs(odds) + 100), 4)
    return None


def american_to_decimal_odds(odds):
    odds = safe_float(odds)
    if odds is None or odds == 0:
        return None
    if odds > 0:
        return round(1 + (odds / 100), 4)
    return round(1 + (100 / abs(odds)), 4)


def no_vig_probabilities(implied_a, implied_b):
    if implied_a is None or implied_b is None:
        return None, None, None
    overround = implied_a + implied_b
    if overround <= 0:
        return None, None, None
    return round(implied_a / overround, 4), round(implied_b / overround, 4), round((overround - 1) * 100, 2)


def expected_value_per_unit(model_probability, odds):
    decimal_odds = american_to_decimal_odds(odds)
    model_probability = safe_float(model_probability)
    if decimal_odds is None or model_probability is None:
        return None
    return round((model_probability * decimal_odds) - 1, 4)


def kelly_fraction(model_probability, odds):
    decimal_odds = american_to_decimal_odds(odds)
    model_probability = safe_float(model_probability)
    if decimal_odds is None or model_probability is None:
        return None
    net_odds = decimal_odds - 1
    if net_odds <= 0:
        return None
    fraction = ((model_probability * decimal_odds) - 1) / net_odds
    return round(max(0.0, fraction), 4)


def fractional_kelly_pct(full_kelly_fraction, fraction=0.25):
    full_kelly_fraction = safe_float(full_kelly_fraction)
    if full_kelly_fraction is None:
        return None
    return round(full_kelly_fraction * fraction * 100, 2)


def normalize_team_name(text: str):
    return " ".join((text or "").lower().replace("los angeles clippers", "la clippers").replace("los angeles lakers", "la lakers").split())


def normalize_matchup(text: str):
    return normalize_team_name(text)


def read_lines():
    if not MARKET_LINES.exists():
        return []
    with MARKET_LINES.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def line_age_hours(row: dict, now: datetime | None = None):
    timestamp = row.get("timestamp", "")
    if not timestamp:
        return None
    try:
        line_time = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    now = now or datetime.now(UTC)
    if line_time.tzinfo is None:
        now = now.replace(tzinfo=None)
    return round(max(0.0, (now - line_time).total_seconds() / 3600), 2)


def is_line_fresh(row: dict, max_age_hours=DEFAULT_MAX_LINE_AGE_HOURS):
    age = line_age_hours(row)
    if age is None:
        return False
    return age <= max_age_hours


def side_value(
    side: str,
    side_norm: str,
    home_team_norm: str,
    away_team_norm: str,
    model_prob_home: float,
    model_prob_away: float,
    implied_prob,
    no_vig_probability,
    odds,
):
    if implied_prob is None or no_vig_probability is None:
        return None
    decimal_odds = american_to_decimal_odds(odds)
    if side_norm == home_team_norm:
        ev = expected_value_per_unit(model_prob_home, odds)
        full_kelly = kelly_fraction(model_prob_home, odds)
        return {
            "side": side,
            "side_role": "home",
            "model_probability": model_prob_home,
            "implied_probability": implied_prob,
            "no_vig_probability": no_vig_probability,
            "value_edge": round((model_prob_home - no_vig_probability) * 100, 2),
            "raw_value_edge": round((model_prob_home - implied_prob) * 100, 2),
            "expected_value_per_unit": ev,
            "decimal_odds": decimal_odds,
            "full_kelly_fraction": full_kelly,
            "quarter_kelly_bankroll_pct": fractional_kelly_pct(full_kelly),
            "odds": odds,
        }
    if side_norm == away_team_norm:
        ev = expected_value_per_unit(model_prob_away, odds)
        full_kelly = kelly_fraction(model_prob_away, odds)
        return {
            "side": side,
            "side_role": "away",
            "model_probability": model_prob_away,
            "implied_probability": implied_prob,
            "no_vig_probability": no_vig_probability,
            "value_edge": round((model_prob_away - no_vig_probability) * 100, 2),
            "raw_value_edge": round((model_prob_away - implied_prob) * 100, 2),
            "expected_value_per_unit": ev,
            "decimal_odds": decimal_odds,
            "full_kelly_fraction": full_kelly,
            "quarter_kelly_bankroll_pct": fractional_kelly_pct(full_kelly),
            "odds": odds,
        }
    return None


def rate_decision(game: dict, best_value: dict | None, teams_matched: bool, line_is_fresh: bool = True):
    reasons = []
    lean = normalize_team_name(game.get("simple_projection_lean", ""))
    edge_band = game.get("edge_band", "")
    confidence = game.get("confidence", "")
    value_edge = best_value.get("value_edge") if best_value else None
    ev = best_value.get("expected_value_per_unit") if best_value else None
    value_side = normalize_team_name(best_value.get("side", "")) if best_value else ""

    if not line_is_fresh:
        reasons.append("market_line_is_stale_or_missing_timestamp")
    if not teams_matched:
        reasons.append("team_names_did_not_match_market")
    if not best_value or value_edge is None:
        reasons.append("no_usable_market_value")
    elif value_edge <= 0:
        reasons.append("market_price_has_no_positive_value")
    if ev is None:
        reasons.append("no_expected_value_available")
    elif ev <= 0:
        reasons.append("expected_value_is_not_positive")
    if lean in {"", "no strong lean"}:
        reasons.append("model_has_no_strong_side")
    elif value_side and lean != value_side:
        reasons.append("best_price_is_not_on_model_lean")
    if confidence != "High":
        reasons.append("confidence_below_high")
    if EDGE_BAND_RANK.get(edge_band, 0) < EDGE_BAND_RANK["moderate"]:
        reasons.append("model_edge_band_below_moderate")

    if (
        line_is_fresh
        and teams_matched
        and best_value
        and value_edge is not None
        and ev is not None
        and value_edge >= 7.0
        and ev >= 0.05
        and confidence == "High"
        and EDGE_BAND_RANK.get(edge_band, 0) >= EDGE_BAND_RANK["strong"]
        and lean == value_side
    ):
        return "premium", ["high_confidence_strong_model_edge_and_market_value"]
    if (
        line_is_fresh
        and teams_matched
        and best_value
        and value_edge is not None
        and ev is not None
        and value_edge >= 5.0
        and ev > 0
        and EDGE_BAND_RANK.get(edge_band, 0) >= EDGE_BAND_RANK["moderate"]
        and lean == value_side
    ):
        return "watchlist", ["model_lean_and_market_value_are_aligned"]
    return "pass", reasons


def build_line_lookup(lines: list[dict]):
    lookup = {}
    for row in lines:
        if row.get("market", "") != "h2h":
            continue
        keys = [
            (row.get("sport", ""), "game_id", row.get("game_id", "")),
            (row.get("sport", ""), "matchup", normalize_matchup(row.get("matchup", ""))),
        ]
        for key in keys:
            if key[2]:
                lookup.setdefault(key, []).append(row)
    return lookup


def matching_market_rows(line_lookup: dict, sport: str, game: dict):
    game_id = game.get("game_id", "")
    matchup = normalize_matchup(game.get("matchup", ""))
    rows = []
    if game_id:
        rows.extend(line_lookup.get((sport, "game_id", game_id), []))
    if not rows and matchup:
        rows.extend(line_lookup.get((sport, "matchup", matchup), []))
    return rows


def main():
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}
    lines = read_lines()
    comparisons = []
    line_lookup = build_line_lookup(lines)

    for sport, block in report.get("reports", {}).items():
        for game in block.get("games", []):
            matchup = game.get("matchup", "")
            market_rows = matching_market_rows(line_lookup, sport, game)
            if not market_rows:
                continue
            model_edge = game.get("record_edge_pct", "")
            home_score = float(game.get("home_weighted_score", 50) or 50)
            away_score = float(game.get("away_weighted_score", 50) or 50)
            score_gap = home_score - away_score
            model_prob_home = probability_from_score_gap(score_gap)
            model_prob_away = round(1.0 - model_prob_home, 4)
            home_team = matchup.split(" at ")[-1] if " at " in matchup else ""
            away_team = matchup.split(" at ")[0] if " at " in matchup else ""
            home_team_norm = normalize_team_name(home_team)
            away_team_norm = normalize_team_name(away_team)

            book_comparisons = []
            value_options = []
            any_fresh_line = False
            teams_matched = False

            for market in market_rows:
                odds_a = market.get("odds_a", "")
                odds_b = market.get("odds_b", "")
                implied_a = american_to_implied_prob(odds_a)
                implied_b = american_to_implied_prob(odds_b)
                no_vig_a, no_vig_b, hold_pct = no_vig_probabilities(implied_a, implied_b)
                side_a = market.get("side_a", "")
                side_b = market.get("side_b", "")
                side_a_norm = normalize_team_name(side_a)
                side_b_norm = normalize_team_name(side_b)
                row_teams_matched = {home_team_norm, away_team_norm} == {side_a_norm, side_b_norm}
                line_is_fresh = is_line_fresh(market)
                teams_matched = teams_matched or row_teams_matched
                any_fresh_line = any_fresh_line or line_is_fresh
                side_a_value = side_value(side_a, side_a_norm, home_team_norm, away_team_norm, model_prob_home, model_prob_away, implied_a, no_vig_a, odds_a)
                side_b_value = side_value(side_b, side_b_norm, home_team_norm, away_team_norm, model_prob_home, model_prob_away, implied_b, no_vig_b, odds_b)
                for option in [side_a_value, side_b_value]:
                    if option is not None:
                        option["line_source"] = market.get("line_source", "")
                        option["line_age_hours"] = line_age_hours(market)
                        option["line_is_fresh"] = line_is_fresh
                        option["book_hold_pct"] = hold_pct
                        value_options.append(option)
                book_comparisons.append({
                    "line_source": market.get("line_source", ""),
                    "line_age_hours": line_age_hours(market),
                    "line_is_fresh": line_is_fresh,
                    "market_side_a": side_a,
                    "market_side_b": side_b,
                    "market_line_a": market.get("line_a", ""),
                    "market_line_b": market.get("line_b", ""),
                    "odds_a": odds_a,
                    "odds_b": odds_b,
                    "implied_prob_a": implied_a,
                    "implied_prob_b": implied_b,
                    "no_vig_prob_a": no_vig_a,
                    "no_vig_prob_b": no_vig_b,
                    "book_hold_pct": hold_pct,
                    "value_edge_a": side_a_value["value_edge"] if side_a_value else None,
                    "value_edge_b": side_b_value["value_edge"] if side_b_value else None,
                    "expected_value_a": side_a_value["expected_value_per_unit"] if side_a_value else None,
                    "expected_value_b": side_b_value["expected_value_per_unit"] if side_b_value else None,
                })

            fresh_options = [v for v in value_options if v.get("line_is_fresh")]
            best_value = max(fresh_options or value_options, key=lambda item: (item["value_edge"], item.get("expected_value_per_unit") or -999)) if value_options else None
            lean_norm = normalize_team_name(game.get("simple_projection_lean", ""))
            matched_sides = {normalize_team_name(row.get("side_a", "")) for row in market_rows} | {normalize_team_name(row.get("side_b", "")) for row in market_rows}
            if lean_norm in matched_sides:
                market_agreement = "leans_toward_model_side"
            elif teams_matched:
                market_agreement = "teams_matched_no_clear_model_lean"
            else:
                market_agreement = "name_mismatch"
            decision_tier, decision_reasons = rate_decision(game, best_value, teams_matched, any_fresh_line)
            first_book = book_comparisons[0] if book_comparisons else {}
            comparisons.append({
                "sport": sport,
                "game_id": game.get("game_id", ""),
                "matchup": matchup,
                "model_lean": game.get("simple_projection_lean", ""),
                "model_confidence": game.get("confidence", ""),
                "model_edge_band": game.get("edge_band", ""),
                "model_edge": model_edge,
                "model_prob_home": model_prob_home,
                "model_prob_away": model_prob_away,
                "probability_method": "score_gap_logistic_v1",
                "market_side_a": first_book.get("market_side_a", ""),
                "market_side_b": first_book.get("market_side_b", ""),
                "market_line_a": first_book.get("market_line_a", ""),
                "market_line_b": first_book.get("market_line_b", ""),
                "odds_a": first_book.get("odds_a", ""),
                "odds_b": first_book.get("odds_b", ""),
                "implied_prob_a": first_book.get("implied_prob_a"),
                "implied_prob_b": first_book.get("implied_prob_b"),
                "no_vig_prob_a": first_book.get("no_vig_prob_a"),
                "no_vig_prob_b": first_book.get("no_vig_prob_b"),
                "book_hold_pct": first_book.get("book_hold_pct"),
                "value_edge_a": first_book.get("value_edge_a"),
                "value_edge_b": first_book.get("value_edge_b"),
                "expected_value_a": first_book.get("expected_value_a"),
                "expected_value_b": first_book.get("expected_value_b"),
                "best_value_side": best_value.get("side", "") if best_value else "",
                "best_value_edge": best_value.get("value_edge") if best_value else None,
                "best_value_raw_edge": best_value.get("raw_value_edge") if best_value else None,
                "best_value_model_probability": best_value.get("model_probability") if best_value else None,
                "best_value_implied_probability": best_value.get("implied_probability") if best_value else None,
                "best_value_no_vig_probability": best_value.get("no_vig_probability") if best_value else None,
                "best_value_odds": best_value.get("odds") if best_value else "",
                "best_value_expected_value": best_value.get("expected_value_per_unit") if best_value else None,
                "best_value_decimal_odds": best_value.get("decimal_odds") if best_value else None,
                "full_kelly_fraction": best_value.get("full_kelly_fraction") if best_value else None,
                "quarter_kelly_bankroll_pct": best_value.get("quarter_kelly_bankroll_pct") if best_value else None,
                "decision_tier": decision_tier,
                "decision_reasons": decision_reasons,
                "line_source": best_value.get("line_source", "") if best_value else first_book.get("line_source", ""),
                "line_age_hours": best_value.get("line_age_hours") if best_value else first_book.get("line_age_hours"),
                "line_is_fresh": best_value.get("line_is_fresh") if best_value else first_book.get("line_is_fresh"),
                "available_books": len(book_comparisons),
                "book_comparisons": book_comparisons,
                "market_agreement": market_agreement,
                "note": "Market comparison layer uses no-vig fair probability, expected value, line freshness, and fractional Kelly sizing guidance. Research only."
            })

    out = {
        "generated_at": datetime.now(UTC).isoformat(),
        "comparisons": comparisons,
        "summary": {
            "premium": sum(1 for item in comparisons if item.get("decision_tier") == "premium"),
            "watchlist": sum(1 for item in comparisons if item.get("decision_tier") == "watchlist"),
            "pass": sum(1 for item in comparisons if item.get("decision_tier") == "pass"),
        },
        "note": "Decision tiers are research filters, not betting advice. Premium requires aligned model lean, fresh line, high confidence, strong model edge, positive expected value, and no-vig market value."
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
