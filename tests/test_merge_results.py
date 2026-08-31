import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import bot.merge_results as merge_results_module


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


class MergeResultsPreservesHistoryTests(unittest.TestCase):
    def test_existing_graded_rows_survive_when_source_logs_no_longer_have_them(self):
        # prediction_log.csv and results_ingest_template.csv get rotated over
        # time, so a game graded weeks ago may not appear in either input on
        # a later run. That must not delete it from graded_results.csv.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [{
                "generated_at": "2026-06-02T00:00:00+00:00",
                "sport": "mlb",
                "game_id": "824027",
                "matchup": "Colorado Rockies at Los Angeles Angels",
                "lean": "Los Angeles Angels",
                "confidence": "High",
                "actual_winner": "Colorado Rockies",
                "was_correct": "false",
                "grading_note": "old loss",
                "model_era": "pre_moneyline_guard",
            }])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value={}),
            ):
                added = merge_results_module.merge_results()

            self.assertEqual(added, 0)
            rows = merge_results_module.read_csv(graded)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["game_id"], "824027")
            self.assertEqual(rows[0]["model_era"], "pre_moneyline_guard")

    def test_new_completed_result_is_appended_and_stamped_with_current_era(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [{
                "generated_at": "2026-06-02T00:00:00+00:00", "sport": "mlb", "game_id": "824027",
                "matchup": "Colorado Rockies at Los Angeles Angels", "lean": "Los Angeles Angels",
                "confidence": "High", "actual_winner": "Colorado Rockies", "was_correct": "false",
                "grading_note": "old loss", "model_era": "pre_moneyline_guard",
            }])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [{
                "generated_at": "2026-08-05T12:00:00+00:00", "sport": "mlb", "game_id": "999999",
                "matchup": "Team A at Team B", "lean": "Team B", "confidence": "High",
            }])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [{
                "sport": "mlb", "game_id": "999999", "matchup": "Team A at Team B",
                "actual_winner": "Team B", "game_completed": "true", "notes": "won",
            }])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value={}),
            ):
                added = merge_results_module.merge_results()

            self.assertEqual(added, 1)
            rows = {r["game_id"]: r for r in merge_results_module.read_csv(graded)}
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows["824027"]["model_era"], "pre_moneyline_guard")
            self.assertEqual(rows["999999"]["model_era"], merge_results_module.CURRENT_MODEL_ERA)
            self.assertEqual(rows["999999"]["was_correct"], "True")

    def test_known_odds_computes_flat_unit_profit_for_a_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [{
                "generated_at": "2026-08-05T12:00:00+00:00", "sport": "mlb", "game_id": "999999",
                "matchup": "Team A at Team B", "lean": "Team B", "confidence": "High",
            }])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [{
                "sport": "mlb", "game_id": "999999", "matchup": "Team A at Team B",
                "actual_winner": "Team B", "game_completed": "true", "notes": "won",
            }])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value={}),
                patch.object(merge_results_module, "lookup_pick", return_value={"odds": "-150"}),
            ):
                merge_results_module.merge_results()

            rows = {r["game_id"]: r for r in merge_results_module.read_csv(graded)}
            self.assertEqual(rows["999999"]["odds"], "-150")
            self.assertAlmostEqual(float(rows["999999"]["profit_units"]), 0.666667, places=5)

    def test_missing_odds_leaves_a_win_profit_blank_but_a_loss_is_still_minus_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [
                {"generated_at": "2026-08-05T12:00:00+00:00", "sport": "mlb", "game_id": "999999",
                 "matchup": "Team A at Team B", "lean": "Team B", "confidence": "High"},
                {"generated_at": "2026-08-05T12:00:00+00:00", "sport": "mlb", "game_id": "888888",
                 "matchup": "Team C at Team D", "lean": "Team D", "confidence": "High"},
            ])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [
                {"sport": "mlb", "game_id": "999999", "matchup": "Team A at Team B",
                 "actual_winner": "Team B", "game_completed": "true", "notes": "won, odds never recorded"},
                {"sport": "mlb", "game_id": "888888", "matchup": "Team C at Team D",
                 "actual_winner": "Team C", "game_completed": "true", "notes": "lost, odds never recorded"},
            ])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value={}),
                patch.object(merge_results_module, "lookup_pick", return_value=None),
            ):
                merge_results_module.merge_results()

            rows = {r["game_id"]: r for r in merge_results_module.read_csv(graded)}
            self.assertEqual(rows["999999"]["odds"], "")
            self.assertEqual(rows["999999"]["profit_units"], "")
            self.assertEqual(rows["888888"]["odds"], "")
            self.assertEqual(rows["888888"]["profit_units"], "-1.0")

    def test_predicted_probability_from_prediction_log_carries_through_to_grading(self):
        # prediction_log.csv already logs a real predicted_probability for
        # the leaned side (model_probability_for_game() in
        # run_daily_projection.py) -- this must survive into
        # graded_results.csv, not be dropped, or no calibration check has
        # a real probability to compare against the real outcome.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence", "predicted_probability"], [{
                "generated_at": "2026-08-05T12:00:00+00:00", "sport": "mlb", "game_id": "999999",
                "matchup": "Team A at Team B", "lean": "Team B", "confidence": "High",
                "predicted_probability": "0.6161",
            }])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [{
                "sport": "mlb", "game_id": "999999", "matchup": "Team A at Team B",
                "actual_winner": "Team B", "game_completed": "true", "notes": "won",
            }])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value={}),
            ):
                merge_results_module.merge_results()

            rows = {r["game_id"]: r for r in merge_results_module.read_csv(graded)}
            self.assertEqual(rows["999999"]["predicted_probability"], "0.6161")

    def test_no_new_completed_results_leaves_file_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value={}),
            ):
                added = merge_results_module.merge_results()

            self.assertEqual(added, 0)


class MergeResultsWarehouseFallbackTests(unittest.TestCase):
    def _make_warehouse(self, db_path: Path, rows: list[dict]):
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE projection_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_at TEXT, sport TEXT, game_id TEXT, matchup TEXT,
                lean TEXT, confidence TEXT
            )
        """)
        for r in rows:
            conn.execute(
                "INSERT INTO projection_history (generated_at, sport, game_id, matchup, lean, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                (r["generated_at"], r["sport"], r["game_id"], r["matchup"], r["lean"], r["confidence"]),
            )
        conn.commit()
        conn.close()

    def test_grades_a_pick_whose_game_already_aged_out_of_prediction_log(self):
        # Regression: caught live -- two real tennis wins (Jakub Mensik,
        # Belinda Bencic) from the prior day's run could not be graded
        # because run_daily_projection.py had already overwritten
        # prediction_log.csv by the time their results were being entered.
        # The warehouse's append-only projection_history table is the
        # fallback source for exactly this case.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [])
            preds = tmp_path / "prediction_log.csv"
            # Today's prediction_log.csv no longer has this game -- it
            # already finished and isn't "upcoming" anymore.
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [{
                "sport": "tennis_atp", "game_id": "181777", "matchup": "Terence Atmane at Jakub Mensik",
                "actual_winner": "Jakub Mensik", "game_completed": "true",
                "notes": "Mensik ML premium pick won 7-5, 6-4 (verified via ESPN)",
            }])
            db_path = tmp_path / "bets.db"
            self._make_warehouse(db_path, [{
                "generated_at": "2026-08-07T17:11:23+00:00", "sport": "tennis_atp", "game_id": "181777",
                "matchup": "Terence Atmane at Jakub Mensik", "lean": "Jakub Mensik", "confidence": "High",
            }])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value={}),
                patch.object(merge_results_module, "WAREHOUSE_DB", db_path),
                patch.object(merge_results_module, "lookup_pick", return_value={"odds": "-220"}),
            ):
                added = merge_results_module.merge_results()

            self.assertEqual(added, 1)
            rows = {r["game_id"]: r for r in merge_results_module.read_csv(graded)}
            self.assertEqual(rows["181777"]["lean"], "Jakub Mensik")
            self.assertEqual(rows["181777"]["was_correct"], "True")
            self.assertEqual(rows["181777"]["odds"], "-220")

    def _make_warehouse_with_probabilities(self, db_path: Path, rows: list[dict]):
        conn = sqlite3.connect(db_path)
        conn.execute("""
            CREATE TABLE projection_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                generated_at TEXT, sport TEXT, game_id TEXT, matchup TEXT,
                lean TEXT, confidence TEXT, home_probability REAL, away_probability REAL
            )
        """)
        for r in rows:
            conn.execute(
                "INSERT INTO projection_history (generated_at, sport, game_id, matchup, lean, confidence, "
                "home_probability, away_probability) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (r["generated_at"], r["sport"], r["game_id"], r["matchup"], r["lean"], r["confidence"],
                 r["home_probability"], r["away_probability"]),
            )
        conn.commit()
        conn.close()

    def test_predicted_probability_derived_from_warehouse_home_away_split(self):
        # projection_history stores home_probability/away_probability, not
        # "the leaned side's probability" directly -- this must pick out
        # the right one using the same "Away at Home" matchup convention
        # every sport module writes.
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [{
                "sport": "tennis_atp", "game_id": "181777", "matchup": "Terence Atmane at Jakub Mensik",
                "actual_winner": "Jakub Mensik", "game_completed": "true", "notes": "won",
            }])
            db_path = tmp_path / "bets.db"
            # matchup is "Away at Home" -> Jakub Mensik is the home player;
            # lean picked the home side, so predicted_probability should be
            # home_probability (0.71), not away_probability (0.29).
            self._make_warehouse_with_probabilities(db_path, [{
                "generated_at": "2026-08-07T17:11:23+00:00", "sport": "tennis_atp", "game_id": "181777",
                "matchup": "Terence Atmane at Jakub Mensik", "lean": "Jakub Mensik", "confidence": "High",
                "home_probability": 0.71, "away_probability": 0.29,
            }])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value={}),
                patch.object(merge_results_module, "WAREHOUSE_DB", db_path),
                patch.object(merge_results_module, "lookup_pick", return_value={"odds": "-220"}),
            ):
                merge_results_module.merge_results()

            rows = {r["game_id"]: r for r in merge_results_module.read_csv(graded)}
            self.assertEqual(rows["181777"]["predicted_probability"], "0.71")

    def test_already_graded_key_is_not_re_pulled_from_warehouse(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [{
                "generated_at": "2026-08-07T00:00:00+00:00", "sport": "tennis_atp", "game_id": "181777",
                "matchup": "Terence Atmane at Jakub Mensik", "lean": "Jakub Mensik", "confidence": "High",
                "actual_winner": "Jakub Mensik", "was_correct": "True", "odds": "-220",
                "profit_units": "0.4545", "grading_note": "already graded", "model_era": "post_moneyline_guard",
            }])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [{
                "sport": "tennis_atp", "game_id": "181777", "matchup": "Terence Atmane at Jakub Mensik",
                "actual_winner": "Jakub Mensik", "game_completed": "true", "notes": "won",
            }])
            db_path = tmp_path / "bets.db"
            self._make_warehouse(db_path, [{
                "generated_at": "2026-08-07T17:11:23+00:00", "sport": "tennis_atp", "game_id": "181777",
                "matchup": "Terence Atmane at Jakub Mensik", "lean": "Jakub Mensik", "confidence": "High",
            }])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value={}),
                patch.object(merge_results_module, "WAREHOUSE_DB", db_path),
            ):
                added = merge_results_module.merge_results()

            self.assertEqual(added, 0)
            rows = merge_results_module.read_csv(graded)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["grading_note"], "already graded")

    def test_missing_warehouse_db_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, [])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [{
                "sport": "tennis_atp", "game_id": "181777", "matchup": "Terence Atmane at Jakub Mensik",
                "actual_winner": "Jakub Mensik", "game_completed": "true", "notes": "won",
            }])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value={}),
                patch.object(merge_results_module, "WAREHOUSE_DB", tmp_path / "does_not_exist.db"),
            ):
                added = merge_results_module.merge_results()

            self.assertEqual(added, 0)


class AutoGradeFromPickLedgerTests(unittest.TestCase):
    """The new self-updating grading path: every actionable pick in
    bot/pick_ledger.py's append-only log gets checked against a real live
    result (bot/result_fetcher.py) with no manual results_ingest_template
    .csv entry required at all."""

    def _run(self, pick_ledger_rows, fetch_real_result_return, graded_rows=None):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            graded = tmp_path / "graded_results.csv"
            write_csv(graded, merge_results_module.FIELDNAMES, graded_rows or [])
            preds = tmp_path / "prediction_log.csv"
            write_csv(preds, ["generated_at", "sport", "game_id", "matchup", "lean", "confidence"], [])
            results = tmp_path / "results_ingest_template.csv"
            write_csv(results, ["sport", "game_id", "matchup", "actual_winner", "game_completed", "notes"], [])

            with (
                patch.object(merge_results_module, "GRADED_RESULTS", graded),
                patch.object(merge_results_module, "PREDICTION_LOG", preds),
                patch.object(merge_results_module, "RESULTS_TEMPLATE", results),
                patch.object(merge_results_module, "read_pick_ledger", return_value=pick_ledger_rows),
                patch.object(merge_results_module, "fetch_real_result", side_effect=fetch_real_result_return),
            ):
                added = merge_results_module.merge_results()

            return added, {r["game_id"]: r for r in merge_results_module.read_csv(graded)}

    def test_grades_a_finished_pick_with_no_manual_entry_at_all(self):
        pick_ledger_rows = {
            ("ufc", "401886039"): {
                "sport": "ufc", "game_id": "401886039", "matchup": "Quillan Salkilld at Mateusz Gamrot",
                "side": "Quillan Salkilld", "odds": "-148", "decision_tier": "premium",
                "recorded_at": "2026-08-07T15:19:04+00:00",
            },
        }
        added, rows = self._run(pick_ledger_rows, lambda sport, gid: (True, "Quillan Salkilld"))

        self.assertEqual(added, 1)
        self.assertEqual(rows["401886039"]["was_correct"], "True")
        self.assertEqual(rows["401886039"]["actual_winner"], "Quillan Salkilld")
        self.assertEqual(rows["401886039"]["odds"], "-148")
        self.assertIn("auto-graded", rows["401886039"]["grading_note"])

    def test_a_losing_pick_grades_as_a_loss(self):
        pick_ledger_rows = {
            ("tennis_wta", "182186"): {
                "sport": "tennis_wta", "game_id": "182186", "matchup": "Marta Kostyuk at Iga Swiatek",
                "side": "Marta Kostyuk", "odds": "130", "decision_tier": "premium",
                "recorded_at": "2026-08-07T17:16:44+00:00",
            },
        }
        added, rows = self._run(pick_ledger_rows, lambda sport, gid: (True, "Iga Swiatek"))

        self.assertEqual(added, 1)
        self.assertEqual(rows["182186"]["was_correct"], "False")
        self.assertEqual(rows["182186"]["profit_units"], "-1.0")

    def test_a_real_draw_grades_as_a_loss_for_whichever_side_was_picked(self):
        pick_ledger_rows = {
            ("leagues_cup", "555"): {
                "sport": "leagues_cup", "game_id": "555", "matchup": "Team A at Team B",
                "side": "Team B", "odds": "-120", "decision_tier": "watchlist",
                "recorded_at": "2026-08-07T00:00:00+00:00",
            },
        }
        added, rows = self._run(pick_ledger_rows, lambda sport, gid: (True, None))

        self.assertEqual(added, 1)
        self.assertEqual(rows["555"]["was_correct"], "False")
        self.assertEqual(rows["555"]["actual_winner"], "")

    def test_unfinished_game_is_left_ungraded_not_guessed(self):
        pick_ledger_rows = {
            ("tennis_atp", "999"): {
                "sport": "tennis_atp", "game_id": "999", "matchup": "A at B",
                "side": "B", "odds": "-110", "decision_tier": "premium",
                "recorded_at": "2026-08-09T00:00:00+00:00",
            },
        }
        added, rows = self._run(pick_ledger_rows, lambda sport, gid: (False, None))

        self.assertEqual(added, 0)
        self.assertEqual(rows, {})

    def test_predicted_probability_carries_through_from_pick_ledger(self):
        pick_ledger_rows = {
            ("ufc", "401886039"): {
                "sport": "ufc", "game_id": "401886039", "matchup": "Quillan Salkilld at Mateusz Gamrot",
                "side": "Quillan Salkilld", "odds": "-148", "decision_tier": "premium",
                "model_probability": "0.5977", "recorded_at": "2026-08-07T15:19:04+00:00",
            },
        }
        added, rows = self._run(pick_ledger_rows, lambda sport, gid: (True, "Quillan Salkilld"))

        self.assertEqual(added, 1)
        self.assertEqual(rows["401886039"]["predicted_probability"], "0.5977")

    def test_already_graded_pick_is_not_re_fetched(self):
        already_graded = [{
            "generated_at": "2026-08-07T00:00:00+00:00", "sport": "ufc", "game_id": "401886039",
            "matchup": "Quillan Salkilld at Mateusz Gamrot", "lean": "Quillan Salkilld", "confidence": "",
            "actual_winner": "Quillan Salkilld", "was_correct": "True", "odds": "-148",
            "profit_units": "0.6757", "grading_note": "already graded", "model_era": "post_moneyline_guard",
        }]
        pick_ledger_rows = {
            ("ufc", "401886039"): {
                "sport": "ufc", "game_id": "401886039", "matchup": "Quillan Salkilld at Mateusz Gamrot",
                "side": "Quillan Salkilld", "odds": "-148", "decision_tier": "premium",
                "recorded_at": "2026-08-07T15:19:04+00:00",
            },
        }
        fetch_calls = []
        def fake_fetch(sport, game_id):
            fetch_calls.append((sport, game_id))
            return True, "Quillan Salkilld"

        added, rows = self._run(pick_ledger_rows, fake_fetch, graded_rows=already_graded)

        self.assertEqual(added, 0)
        self.assertEqual(fetch_calls, [])  # never even attempted -- already graded
        self.assertEqual(rows["401886039"]["grading_note"], "already graded")


if __name__ == "__main__":
    unittest.main()
