from __future__ import annotations

import csv
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "logs" / "bets.db"
MARKET_LINES = ROOT / "logs" / "market_lines.csv"


def connect(db_path: Path = DB):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(db_path)


def initialize_warehouse(conn: sqlite3.Connection):
    conn.execute("""
    CREATE TABLE IF NOT EXISTS projection_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        generated_at TEXT,
        sport TEXT,
        game_id TEXT,
        matchup TEXT,
        lean TEXT,
        confidence TEXT,
        edge_band TEXT,
        home_probability REAL,
        away_probability REAL,
        ensemble_json TEXT,
        monte_carlo_json TEXT,
        regime_json TEXT,
        feature_importance_json TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS odds_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        captured_at TEXT,
        sport TEXT,
        market TEXT,
        game_id TEXT,
        matchup TEXT,
        line_source TEXT,
        side_a TEXT,
        side_b TEXT,
        line_a REAL,
        line_b REAL,
        odds_a REAL,
        odds_b REAL
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS result_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        graded_at TEXT,
        sport TEXT,
        game_id TEXT,
        matchup TEXT,
        lean TEXT,
        confidence TEXT,
        actual_winner TEXT,
        was_correct TEXT,
        closing_line REAL,
        notes TEXT
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS line_movement_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evaluated_at TEXT,
        sport TEXT,
        game_id TEXT,
        matchup TEXT,
        line_source TEXT,
        market TEXT,
        open_line_a REAL,
        open_line_b REAL,
        close_line_a REAL,
        close_line_b REAL,
        open_odds_a REAL,
        open_odds_b REAL,
        close_odds_a REAL,
        close_odds_b REAL,
        movement_direction TEXT
    )
    """)
    conn.commit()


def store_projection_report(report: dict, conn: sqlite3.Connection | None = None):
    owns_conn = conn is None
    conn = conn or connect()
    initialize_warehouse(conn)
    generated_at = report.get("generated_at", datetime.now(UTC).isoformat())
    for sport, block in report.get("reports", {}).items():
        for game in block.get("games", []):
            conn.execute(
                """
                INSERT INTO projection_history (
                    generated_at, sport, game_id, matchup, lean, confidence, edge_band,
                    home_probability, away_probability, ensemble_json, monte_carlo_json,
                    regime_json, feature_importance_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    generated_at,
                    sport,
                    game.get("game_id", ""),
                    game.get("matchup", ""),
                    game.get("simple_projection_lean", ""),
                    game.get("confidence", ""),
                    game.get("edge_band", ""),
                    game.get("win_probability_home"),
                    game.get("win_probability_away"),
                    json.dumps(game.get("ensemble", {})),
                    json.dumps(game.get("monte_carlo", {})),
                    json.dumps(game.get("regime", {})),
                    json.dumps(game.get("feature_importance", [])),
                ),
            )
    conn.commit()
    if owns_conn:
        conn.close()


def store_market_lines(path: Path = MARKET_LINES, conn: sqlite3.Connection | None = None):
    if not path.exists():
        return 0
    owns_conn = conn is None
    conn = conn or connect()
    initialize_warehouse(conn)
    count = 0
    with path.open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            conn.execute(
                """
                INSERT INTO odds_history (
                    captured_at, sport, market, game_id, matchup, line_source, side_a, side_b,
                    line_a, line_b, odds_a, odds_b
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("timestamp", ""),
                    row.get("sport", ""),
                    row.get("market", ""),
                    row.get("game_id", ""),
                    row.get("matchup", ""),
                    row.get("line_source", ""),
                    row.get("side_a", ""),
                    row.get("side_b", ""),
                    _to_float(row.get("line_a")),
                    _to_float(row.get("line_b")),
                    _to_float(row.get("odds_a")),
                    _to_float(row.get("odds_b")),
                ),
            )
            count += 1
    conn.commit()
    if owns_conn:
        conn.close()
    return count


def store_line_movements(comparisons: list[dict], conn: sqlite3.Connection | None = None):
    owns_conn = conn is None
    conn = conn or connect()
    initialize_warehouse(conn)
    count = 0
    evaluated_at = datetime.now(UTC).isoformat()
    for item in comparisons:
        movement = item.get("line_movement") or {}
        if not movement:
            continue
        open_line = movement.get("open_line") or {}
        close_line = movement.get("closing_line") or {}
        conn.execute(
            """
            INSERT INTO line_movement_history (
                evaluated_at, sport, game_id, matchup, line_source, market,
                open_line_a, open_line_b, close_line_a, close_line_b,
                open_odds_a, open_odds_b, close_odds_a, close_odds_b,
                movement_direction
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evaluated_at,
                item.get("sport", ""),
                item.get("game_id", ""),
                item.get("matchup", ""),
                item.get("line_source", ""),
                "h2h",
                _to_float(open_line.get("line_a")),
                _to_float(open_line.get("line_b")),
                _to_float(close_line.get("line_a")),
                _to_float(close_line.get("line_b")),
                _to_float(open_line.get("odds_a")),
                _to_float(open_line.get("odds_b")),
                _to_float(close_line.get("odds_a")),
                _to_float(close_line.get("odds_b")),
                movement.get("movement_direction", ""),
            ),
        )
        count += 1
    conn.commit()
    if owns_conn:
        conn.close()
    return count


def _to_float(value):
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
