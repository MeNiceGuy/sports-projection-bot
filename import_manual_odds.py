from __future__ import annotations

import argparse
import csv
from datetime import UTC, datetime
from pathlib import Path

from bot.odds_fetcher import FIELDNAMES, append_line_history, is_placeholder_market_row, write_current_lines, write_status

ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "data" / "manual_market_lines.csv"


def _parse_timestamp(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def validate_rows(rows: list[dict]):
    errors = []
    required = ["sport", "market", "matchup", "line_source", "side_a", "side_b", "odds_a", "odds_b", "timestamp"]
    for index, row in enumerate(rows, start=2):
        for field in required:
            if not str(row.get(field, "")).strip():
                errors.append(f"line {index}: missing {field}")
        if row.get("market") != "h2h":
            errors.append(f"line {index}: only h2h moneyline rows are supported for manual betting readiness")
        if row.get("sport") not in {"nba", "mlb", "wnba", "nfl", "ufc", "leagues_cup", "tennis_atp", "tennis_wta"}:
            errors.append(f"line {index}: sport must be nba, mlb, wnba, nfl, ufc, leagues_cup, tennis_atp, or tennis_wta")
        if is_placeholder_market_row(row):
            errors.append(f"line {index}: placeholder/example market rows are not allowed")
        if _parse_timestamp(row.get("timestamp", "")) is None:
            errors.append(f"line {index}: timestamp must be ISO format")
        for field in ["odds_a", "odds_b"]:
            try:
                int(float(str(row.get(field, "")).strip()))
            except ValueError:
                errors.append(f"line {index}: {field} must be American odds")
    return errors


def read_manual_rows(path: Path):
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        missing = [field for field in FIELDNAMES if field not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"manual odds file missing columns: {', '.join(missing)}")
        return [{field: row.get(field, "") for field in FIELDNAMES} for row in reader]


def import_manual_odds(path: Path = DEFAULT_INPUT):
    if not path.exists():
        raise FileNotFoundError(f"manual odds file not found: {path}")
    rows = read_manual_rows(path)
    errors = validate_rows(rows)
    if errors:
        raise ValueError("; ".join(errors[:10]))
    if not rows:
        raise ValueError("manual odds file has no rows")

    write_current_lines(rows)
    history_rows = append_line_history(rows)
    status = write_status(True, f"manual odds import succeeded from {path}", rows=len(rows), source="manual_import")
    return {
        "market_lines_written": len(rows),
        "line_history_appended": history_rows,
        "input": str(path),
        "status": status,
    }


def main():
    parser = argparse.ArgumentParser(description="Import fresh manually verified sportsbook moneylines.")
    parser.add_argument("--input", default=str(DEFAULT_INPUT), help="CSV path with market line columns")
    args = parser.parse_args()

    try:
        result = import_manual_odds(Path(args.input))
    except Exception as exc:
        write_current_lines([])
        status = write_status(False, f"manual odds import failed: {exc}", rows=0, source="manual_import")
        print(status)
        raise SystemExit(1)

    print(result)


if __name__ == "__main__":
    main()
