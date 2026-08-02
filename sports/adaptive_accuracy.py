import json
from pathlib import Path

def get_dynamic_historical_accuracy(sport=None, default=0.61):
    path = Path("data/rolling_retraining.json")

    if not path.exists():
        return default

    try:
        data = json.loads(path.read_text(encoding="utf-8"))

        if sport:
            sport_values = data.get("by_sport", {})
            if sport in sport_values:
                return float(sport_values[sport])

        return float(
            data.get("recommended_historical_accuracy")
            or data.get("rolling_100_accuracy")
            or data.get("overall_accuracy")
            or default
        )
    except Exception:
        return default
