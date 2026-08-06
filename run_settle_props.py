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

        for row in pending:
            row_dict = dict(row)
            if not row_dict.get("matchup") or not row_dict.get("side"):
                skipped_no_data += 1
                continue

            outcome = settle_prop(row_dict)
            if outcome is None:
                continue  # game not final yet / not found -- stays PENDING

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
