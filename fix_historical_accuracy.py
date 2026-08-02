import json

ROLLING_PATH = "data/rolling_retraining.json"
REPORT_PATH = "outputs/latest_report_with_odds.json"

with open(ROLLING_PATH, "r", encoding="utf-8") as f:
    retraining = json.load(f)

new_accuracy = retraining.get("recommended_historical_accuracy", 0.61)

with open(REPORT_PATH, "r", encoding="utf-8") as f:
    report = json.load(f)

def replace_accuracy(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "historical_accuracy":
                obj[k] = round(float(new_accuracy), 4)
            else:
                replace_accuracy(v)

    elif isinstance(obj, list):
        for item in obj:
            replace_accuracy(item)

replace_accuracy(report)

with open(REPORT_PATH, "w", encoding="utf-8") as f:
    json.dump(report, f, indent=2)

print(f"Updated historical_accuracy -> {new_accuracy}")
