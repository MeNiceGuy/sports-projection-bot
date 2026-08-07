from __future__ import annotations
from sports.adaptive_accuracy import get_dynamic_historical_accuracy

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from sports.mlb import build_mlb_report
from sports.nba import build_nba_report
from sports.wnba import build_wnba_report
from sports.nfl import build_nfl_report
from sports.ufc import build_ufc_report
from sports.model_utils import probability_from_score_gap
from sports.advanced_analytics import enrich_game
from bot.data_warehouse import store_projection_report
from bot.dynamic_learning import apply_dynamic_learning_to_game, load_learning_state

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
REPORT_OUT = ROOT / "reports" / "daily_projection_report.json"
PRED_LOG = ROOT / "logs" / "prediction_log.csv"
GRADED_RESULTS = ROOT / "logs" / "graded_results.csv"

BUILDERS = {
    "nba": build_nba_report,
    "mlb": build_mlb_report,
    "wnba": build_wnba_report,
    "nfl": build_nfl_report,
    "ufc": build_ufc_report,
}


def load_config():
    if not CONFIG_PATH.exists():
        return {"active_sports": ["nba", "mlb", "wnba", "nfl", "ufc"], "output_report": str(REPORT_OUT)}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def load_historical_accuracy():
    if not GRADED_RESULTS.exists():
        return {}
    totals = {}
    with GRADED_RESULTS.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            sport = row.get("sport", "")
            if not sport:
                continue
            totals.setdefault(sport, {"total": 0, "correct": 0})
            totals[sport]["total"] += 1
            if str(row.get("was_correct", "")).strip().lower() in {"true", "1", "yes", "win"}:
                totals[sport]["correct"] += 1
    return {
        sport: round(data["correct"] / data["total"], 4)
        for sport, data in totals.items()
        if data["total"] >= 5
    }


def model_probability_for_game(game: dict):
    if game.get("simple_projection_lean") == (game.get("matchup", "").split(" at ")[0] if " at " in game.get("matchup", "") else ""):
        return round(float(game.get("win_probability_away", 0) or 0), 4) or _score_gap_probability(game, away=True)
    if game.get("simple_projection_lean") == (game.get("matchup", "").split(" at ")[-1] if " at " in game.get("matchup", "") else ""):
        return round(float(game.get("win_probability_home", 0) or 0), 4) or _score_gap_probability(game)
    if game.get("win_probability_home") is not None and game.get("win_probability_away") is not None:
        return round(max(float(game.get("win_probability_home") or 0.5), float(game.get("win_probability_away") or 0.5)), 4)
    return _score_gap_probability(game)


def _score_gap_probability(game: dict, away: bool = False):
    home_score = float(game.get("home_weighted_score", 50) or 50)
    away_score = float(game.get("away_weighted_score", 50) or 50)
    home_probability = probability_from_score_gap(home_score - away_score)
    if away:
        return round(1.0 - home_probability, 4)
    return round(max(home_probability, 1.0 - home_probability), 4)


def write_prediction_log(report: dict):
    PRED_LOG.parent.mkdir(parents=True, exist_ok=True)
    with PRED_LOG.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "generated_at",
            "sport",
            "game_id",
            "matchup",
            "lean",
            "confidence",
            "edge",
            "edge_band",
            "predicted_probability",
            "win_probability_home",
            "win_probability_away",
            "confidence_band_lower",
            "confidence_band_upper",
            "factor_agreement",
            "historical_accuracy",
            "calibration_method",
            "notes",
        ])
        writer.writeheader()
        for sport, block in report.get("reports", {}).items():
            for game in block.get("games", []):
                writer.writerow({
                    "generated_at": report.get("generated_at", ""),
                    "sport": sport,
                    "game_id": game.get("game_id", ""),
                    "matchup": game.get("matchup", ""),
                    "lean": game.get("simple_projection_lean", ""),
                    "confidence": game.get("confidence", ""),
                    "edge": game.get("record_edge_pct", ""),
                    "edge_band": game.get("edge_band", ""),
                    "predicted_probability": model_probability_for_game(game),
                    "win_probability_home": game.get("win_probability_home", ""),
                    "win_probability_away": game.get("win_probability_away", ""),
                    "confidence_band_lower": (game.get("confidence_band_home") or {}).get("lower", ""),
                    "confidence_band_upper": (game.get("confidence_band_home") or {}).get("upper", ""),
                    "factor_agreement": game.get("factor_agreement", ""),
                    "historical_accuracy": game.get("historical_accuracy", ""),
                    "calibration_method": (game.get("calibration") or {}).get("method", ""),
                    "notes": game.get("note", ""),
                })


def enrich_report(report: dict):
    historical_accuracy = load_historical_accuracy()
    learning_state = load_learning_state()
    for sport, block in report.get("reports", {}).items():
        for game in block.get("games", []):
            game["historical_accuracy"] = historical_accuracy.get(sport, get_dynamic_historical_accuracy(sport))
        block["games"] = [
            apply_dynamic_learning_to_game(enrich_game(sport, game), learning_state)
            for game in block.get("games", [])
        ]
    return report


def main():
    config = load_config()
    active_sports = [sport for sport in config.get("active_sports", []) if sport in BUILDERS]
    now = datetime.now(UTC).isoformat()
    report = {
        "generated_at": now,
        "active_sports": active_sports,
        "reports": {},
        "model_stack": "weighted_team_models_v2_plus_market_governance",
        "note": "Daily projection now runs the sport-specific weighted models. Market comparison, EV filtering, staking research, CLV, and governance run in later pipeline steps.",
    }

    for sport in active_sports:
        report["reports"][sport] = BUILDERS[sport]()

    enrich_report(report)
    output_path = ROOT / config.get("output_report", "reports/daily_projection_report.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    write_prediction_log(report)
    store_projection_report(report)

    print({
        "sports": active_sports,
        "games": sum(len(block.get("games", [])) for block in report["reports"].values()),
        "output": str(output_path),
        "prediction_log": str(PRED_LOG),
        "warehouse": str(ROOT / "logs" / "bets.db"),
    })


if __name__ == "__main__":
    main()

