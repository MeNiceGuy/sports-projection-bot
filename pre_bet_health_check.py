from __future__ import annotations

import csv
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from bot.market_compare import DEFAULT_MAX_LINE_AGE_HOURS, line_age_hours
from bot.odds_fetcher import OUT_PATH, STATUS_PATH, load_api_key, load_config

ROOT = Path(__file__).resolve().parent
PROJECTION_REPORT_PATH = ROOT / "reports" / "daily_projection_report.json"
REPORT_PATH = ROOT / "reports" / "market_comparison_report.json"


def _load_rows(path: Path):
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _report_age_hours(report: dict):
    timestamp = report.get("generated_at", "")
    if not timestamp:
        return None
    try:
        generated_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    now = datetime.now(UTC)
    if generated_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return round(max(0.0, (now - generated_at).total_seconds() / 3600), 2)


def _projection_placeholder_games(report: dict):
    placeholders = []
    for sport, block in report.get("reports", {}).items():
        for game in block.get("games", []):
            matchup = game.get("matchup", "").lower()
            game_id = game.get("game_id", "").lower()
            if "away team at home team" in matchup or game_id.startswith("example"):
                placeholders.append({
                    "sport": sport,
                    "game_id": game.get("game_id", ""),
                    "matchup": game.get("matchup", ""),
                })
    return placeholders


def _projection_non_real_data_games(report: dict):
    flagged = []
    bad_tokens = {"fallback", "market_fallback", "cached_market_lines", "unknown"}
    fields_to_check = (
        "data_source",
        "home_starter_quality_source",
        "away_starter_quality_source",
        "home_bullpen_fatigue_status",
        "away_bullpen_fatigue_status",
        "split_data_source",
        "home_recent_form",
        "away_recent_form",
        "home_probable_pitcher",
        "away_probable_pitcher",
    )
    for sport, block in report.get("reports", {}).items():
        block_source = str(block.get("data_source", "")).lower()
        for game in block.get("games", []):
            reasons = []
            if block_source in bad_tokens:
                reasons.append(f"block_data_source:{block_source}")
            for field in fields_to_check:
                value = str(game.get(field, "")).lower()
                if value in bad_tokens or value.endswith("_fallback") or "fallback" in value:
                    reasons.append(f"{field}:{value}")
            if reasons:
                flagged.append({
                    "sport": sport,
                    "game_id": game.get("game_id", ""),
                    "matchup": game.get("matchup", ""),
                    "reasons": reasons,
                })
    return flagged


def run_check(max_line_age_hours=DEFAULT_MAX_LINE_AGE_HOURS):
    failures = []
    warnings = []

    config = load_config()
    status = _load_json(STATUS_PATH)
    status_source = status.get("source", "api") if status else "api"
    if status_source != "manual_import" and not load_api_key(config):
        failures.append("No odds API key configured in env or config.odds.json.")

    if not status:
        failures.append("No odds status file found. Run python run_odds_fetch.py or python import_manual_odds.py.")
    elif not status.get("ok"):
        label = "Latest manual odds import failed" if status_source == "manual_import" else "Latest odds fetch failed"
        failures.append(f"{label}: {status.get('reason', 'unknown reason')}")

    rows = _load_rows(OUT_PATH)
    if not rows:
        failures.append("No current market lines are available.")
    else:
        placeholder_rows = [
            row for row in rows
            if "away team at home team" in row.get("matchup", "").lower()
            or row.get("game_id", "").lower().startswith("example")
        ]
        if placeholder_rows:
            failures.append("Current market lines include placeholder/example odds rows.")
        ages = [line_age_hours(row) for row in rows]
        usable_ages = [age for age in ages if age is not None]
        if not usable_ages:
            failures.append("Market lines have no parseable timestamps.")
        else:
            newest_age = min(usable_ages)
            oldest_age = max(usable_ages)
            if newest_age > max_line_age_hours:
                failures.append(f"Newest market line is stale: {newest_age} hours old.")
            if oldest_age > max_line_age_hours:
                warnings.append(f"Some market lines are stale; oldest is {oldest_age} hours old.")

    projection_report = _load_json(PROJECTION_REPORT_PATH)
    projection_age = _report_age_hours(projection_report)
    if not projection_report:
        failures.append("No daily projection report found. Run python run_daily_projection.py.")
    elif projection_age is None:
        failures.append("Daily projection report has no parseable generated_at timestamp.")
    elif projection_age > max_line_age_hours:
        failures.append(f"Daily projection report is stale: {projection_age} hours old.")
    placeholder_projection_games = _projection_placeholder_games(projection_report)
    if placeholder_projection_games:
        failures.append("Daily projection report includes placeholder/example games.")
    non_real_projection_games = _projection_non_real_data_games(projection_report)
    if non_real_projection_games:
        failures.append("Daily projection report includes fallback/unknown data sources.")

    report = _load_json(REPORT_PATH)
    comparisons = report.get("comparisons", [])
    actionable = [item for item in comparisons if item.get("actionable_edge")]
    if not report:
        failures.append("No market comparison report found. Run python run_market_compare.py.")
    elif not comparisons:
        failures.append("Market comparison produced no matched games.")
    elif not actionable:
        failures.append("Market comparison has no actionable premium/watchlist edges.")

    return {
        "ok": not failures,
        "generated_at": datetime.now(UTC).isoformat(),
        "failures": failures,
        "warnings": warnings,
        "market_rows": len(rows),
        "comparisons": len(comparisons),
        "actionable_edges": len(actionable),
        "projection_age_hours": projection_age,
        "placeholder_projection_games": len(placeholder_projection_games),
        "non_real_projection_games": len(non_real_projection_games),
        "odds_source": status_source,
    }


def main():
    result = run_check()
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()
