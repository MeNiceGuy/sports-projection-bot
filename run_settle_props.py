from __future__ import annotations

"""Settle PENDING props in logs/bets.db against real box scores.

Replaces legacy/settle_bets.py, which picked WIN/LOSS with random.choice()
and never checked reality. Every row this touches gets a real outcome
looked up from bot/prop_settlement.py, or is left PENDING if the game
hasn't finished yet, can't be found, or predates matchup/side being
captured at all (nothing to look up).
"""

import sqlite3
from pathlib import Path

from bot.betting_metrics import closing_line_value
from bot.prop_history import lookup_prop_closing_odds, read_prop_history_rows
from bot.prop_settlement import settle_prop

ROOT = Path(__file__).resolve().parent
DB = ROOT / "logs" / "bets.db"


def settle_pending_props():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        pending = conn.execute("SELECT * FROM bets WHERE result = 'PENDING'").fetchall()
        settled = 0
        skipped_no_data = 0
        by_result = {}
        # Read once, not once per prop -- same reasoning as
        # bot/merge_results.py reading market_line_history.csv once per run.
        prop_history_rows = read_prop_history_rows()

        for row in pending:
            row_dict = dict(row)
            if not row_dict.get("matchup") or not row_dict.get("side"):
                skipped_no_data += 1
                continue

            outcome = settle_prop(row_dict)
            if outcome is None:
                continue  # game not final yet / not found -- stays PENDING

            # Real closing price, not the opening_odds==closing_odds
            # placeholder save_best_bets.py seeds every prop with -- only
            # available for props saved since bot/prop_history.py started
            # capturing real prop-line history (no historical backlog to
            # draw from the way moneylines had). A miss leaves closing_odds
            # at whatever it already was rather than guessing.
            closing = lookup_prop_closing_odds(
                row_dict.get("sport", ""), row_dict.get("player", ""), row_dict.get("market", ""),
                row_dict.get("side", ""), row_dict.get("line"), rows=prop_history_rows,
            )
            if closing is not None:
                clv = closing_line_value(row_dict.get("odds"), closing)
                conn.execute(
                    "UPDATE bets SET closing_odds = ?, clv = ? WHERE id = ?",
                    (closing, clv.get("clv_probability_points"), row_dict["id"]),
                )

            conn.execute(
                "UPDATE bets SET result = ?, profit = ?, settlement_note = ? WHERE id = ?",
                (outcome["result"], outcome["profit"], outcome["settlement_note"], row_dict["id"]),
            )
            settled += 1
            by_result[outcome["result"]] = by_result.get(outcome["result"], 0) + 1

        conn.commit()
    finally:
        conn.close()

    return {
        "pending_checked": len(pending),
        "settled": settled,
        "by_result": by_result,
        "skipped_no_matchup_or_side": skipped_no_data,
        "still_pending": len(pending) - settled,
    }


def main():
    print(settle_pending_props())


if __name__ == "__main__":
    main()
