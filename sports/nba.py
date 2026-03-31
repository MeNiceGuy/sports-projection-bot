from __future__ import annotations

from datetime import datetime


def build_nba_report():
    return {
        "status": "scaffold",
        "model": "nba_scaffold_v1",
        "generated_at": datetime.utcnow().isoformat(),
        "games": [],
        "note": "NBA module scaffold is active, but the live public feed needs a working source upgrade before real game projections can populate automatically."
    }
