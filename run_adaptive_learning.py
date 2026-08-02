from __future__ import annotations

import json

from bot.dynamic_learning import write_outcome_learning_state


def main():
    state = write_outcome_learning_state()
    print(json.dumps({
        "output": "reports/adaptive_learning_recommendations.json",
        "rolling_retraining": "data/rolling_retraining.json",
        "sample_size": state["sample_size"],
        "mode": state["mode"],
        "global_probability_multiplier": state["global_probability_multiplier"],
        "bucket_recommendations": len(state["bucket_recommendations"]),
    }, indent=2))


if __name__ == "__main__":
    main()
