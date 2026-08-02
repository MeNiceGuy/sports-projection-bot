import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import run_player_props


class PlayerPropsCacheTests(unittest.TestCase):
    def test_cached_props_are_fresh_inside_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "player_props.csv"
            out_path.write_text("matchup,book,market,player,side,line,odds,last_update\n", encoding="utf-8")

            with patch.object(run_player_props, "OUT", out_path):
                fresh, age = run_player_props.cached_props_are_fresh(30)

            self.assertTrue(fresh)
            self.assertLessEqual(age, 30)

    def test_cached_props_are_stale_outside_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "player_props.csv"
            out_path.write_text("matchup,book,market,player,side,line,odds,last_update\n", encoding="utf-8")
            old = time.time() - 3600
            Path(out_path).touch()
            import os
            os.utime(out_path, (old, old))

            with patch.object(run_player_props, "OUT", out_path):
                fresh, age = run_player_props.cached_props_are_fresh(30)

            self.assertFalse(fresh)
            self.assertGreater(age, 30)


if __name__ == "__main__":
    unittest.main()
