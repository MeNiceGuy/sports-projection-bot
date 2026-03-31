from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sports.nba import build_nba_report
from sports.mlb import build_mlb_report
from sports.nfl import build_nfl_report
from sports.nhl import build_nhl_report
from sports.ncaab import build_ncaab_report
from sports.ncaaf import build_ncaaf_report

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"


def main():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    active = config.get("active_sports", [])
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "active_sports": active,
        "reports": {}
    }

    if "nba" in active:
        report["reports"]["nba"] = build_nba_report()
    if "mlb" in active:
        report["reports"]["mlb"] = build_mlb_report()
    if "nfl" in active:
        report["reports"]["nfl"] = build_nfl_report()
    if "nhl" in active:
        report["reports"]["nhl"] = build_nhl_report()
    if "ncaab" in active:
        report["reports"]["ncaab"] = build_ncaab_report()
    if "ncaaf" in active:
        report["reports"]["ncaaf"] = build_ncaaf_report()

    out_path = ROOT / config.get("output_report", "reports/daily_projection_report.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
