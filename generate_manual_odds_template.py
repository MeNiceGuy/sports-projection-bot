from __future__ import annotations

import csv
import json
from datetime import UTC, datetime
from pathlib import Path

from bot.odds_fetcher import FIELDNAMES

ROOT = Path(__file__).resolve().parent
REPORT_PATH = ROOT / "reports" / "daily_projection_report.json"
OUT_PATH = ROOT / "data" / "manual_market_lines.csv"


def _load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _split_matchup(matchup: str) -> tuple[str, str]:
    if " at " not in matchup:
        return "", ""
    away, home = matchup.split(" at ", 1)
    return away.strip(), home.strip()


def _is_placeholder(game: dict) -> bool:
    matchup = game.get("matchup", "").lower()
    game_id = game.get("game_id", "").lower()
    return "away team at home team" in matchup or game_id.startswith("example")


def build_rows(report: dict, line_source: str = "ManualBook", now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(UTC)
    timestamp = now.isoformat()
    rows = []

    for sport, block in report.get("reports", {}).items():
        if sport not in {"nba", "mlb", "wnba", "nfl", "ufc", "leagues_cup", "tennis_atp", "tennis_wta"}:
            continue
        for game in block.get("games", []):
            if _is_placeholder(game):
                continue
            matchup = game.get("matchup", "")
            away, home = _split_matchup(matchup)
            if not away or not home:
                continue
            rows.append({
                "sport": sport,
                "market": "h2h",
                "game_id": game.get("game_id", ""),
                "matchup": matchup,
                "line_source": line_source,
                "side_a": away,
                "side_b": home,
                "line_a": "",
                "line_b": "",
                "odds_a": "",
                "odds_b": "",
                "timestamp": timestamp,
            })
    return rows


def write_template(rows: list[dict], out_path: Path = OUT_PATH) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)


def generate_template(report_path: Path = REPORT_PATH, out_path: Path = OUT_PATH) -> list[dict]:
    rows = build_rows(_load_json(report_path))
    if not rows:
        raise RuntimeError(
            "No real NBA/MLB projection games found. Run python run_daily_projection.py with live data before generating manual odds."
        )
    write_template(rows, out_path)
    return rows


def main() -> None:
    try:
        rows = generate_template()
    except RuntimeError as exc:
        print({"ok": False, "error": str(exc), "output": str(OUT_PATH)})
        raise SystemExit(1)

    print({
        "ok": True,
        "rows_written": len(rows),
        "output": str(OUT_PATH),
        "next_step": "Fill odds_a and odds_b with verified sportsbook moneylines, then run python import_manual_odds.py.",
    })


if __name__ == "__main__":
    main()
