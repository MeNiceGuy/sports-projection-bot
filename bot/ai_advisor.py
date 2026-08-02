from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
DAILY_REPORT = ROOT / "reports" / "daily_projection_report.json"
MARKET_REPORT = ROOT / "reports" / "market_comparison_report.json"
GOVERNANCE_REPORT = ROOT / "reports" / "model_governance_report.json"
BACKTESTING_REPORT = ROOT / "reports" / "backtesting_engine_report.json"
OUT = ROOT / "reports" / "ai_advisor_report.json"

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
DEFAULT_MODEL = "gpt-4.1-mini"


def load_json(path: Path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def summarize_daily_report(report: dict):
    sports = report.get("reports", {})
    games = []
    for sport, block in sports.items():
        for game in block.get("games", [])[:8]:
            games.append({
                "sport": sport,
                "matchup": game.get("matchup", ""),
                "lean": game.get("simple_projection_lean", ""),
                "confidence": game.get("confidence", ""),
                "edge_band": game.get("edge_band", ""),
                "win_probability_home": game.get("win_probability_home"),
                "win_probability_away": game.get("win_probability_away"),
                "factor_agreement": game.get("factor_agreement"),
                "regime_flags": (game.get("regime") or {}).get("flags", []),
            })
    return {
        "generated_at": report.get("generated_at"),
        "active_sports": report.get("active_sports", []),
        "game_count": sum(len(block.get("games", [])) for block in sports.values()),
        "sample_games": games,
    }


def summarize_market_report(report: dict):
    comparisons = report.get("comparisons", [])
    by_tier = {}
    for item in comparisons:
        tier = item.get("decision_tier", "unknown")
        by_tier[tier] = by_tier.get(tier, 0) + 1
    return {
        "generated_at": report.get("generated_at"),
        "comparison_count": len(comparisons),
        "decision_tiers": by_tier,
        "top_candidates": [
            {
                "sport": item.get("sport", ""),
                "matchup": item.get("matchup", ""),
                "tier": item.get("decision_tier", ""),
                "model_lean": item.get("model_lean", ""),
                "best_value_side": item.get("best_value_side", ""),
                "best_value_edge": item.get("best_value_edge"),
                "expected_value": item.get("best_value_expected_value"),
                "risk_flags": item.get("risk_flags", []),
            }
            for item in comparisons[:8]
        ],
    }


def compact_context():
    governance = load_json(GOVERNANCE_REPORT)
    backtesting = load_json(BACKTESTING_REPORT)
    return {
        "daily_projection": summarize_daily_report(load_json(DAILY_REPORT)),
        "market_comparison": summarize_market_report(load_json(MARKET_REPORT)),
        "model_governance": {
            "generated_at": governance.get("generated_at"),
            "release_gate": (governance.get("model_governance") or {}).get("release_gate"),
            "capability_strength": governance.get("capability_strength"),
            "predictive_accuracy": governance.get("predictive_accuracy"),
            "calibration": governance.get("calibration"),
            "risk_management": governance.get("risk_management"),
            "adaptive_learning": governance.get("adaptive_learning"),
        },
        "backtesting": {
            "generated_at": backtesting.get("generated_at"),
            "summary": backtesting.get("summary"),
            "edge_persistence": backtesting.get("edge_persistence"),
            "rolling_performance": backtesting.get("rolling_performance"),
        },
    }


def local_recommendations(context: dict):
    daily = context.get("daily_projection", {})
    market = context.get("market_comparison", {})
    governance = context.get("model_governance", {})
    release_gate = governance.get("release_gate") or {}
    predictive = governance.get("predictive_accuracy") or {}
    release_status = release_gate.get("status") if isinstance(release_gate, dict) else str(release_gate)

    recommendations = []
    if release_status not in {"passed", "open"}:
        recommendations.append({
            "priority": "high",
            "area": "validation",
            "action": "Keep grading completed projections before raising trust in confidence labels.",
            "why": "The governance gate is still blocking or missing because sample size is not strong enough.",
        })
    if predictive.get("sample_size", 0) < 100:
        recommendations.append({
            "priority": "high",
            "area": "data",
            "action": "Increase graded result volume and preserve prediction snapshots for every run.",
            "why": "Calibration, Brier score, and bucket accuracy are weak signals until enough outcomes exist.",
        })
    if not market.get("comparison_count"):
        recommendations.append({
            "priority": "medium",
            "area": "market",
            "action": "Run odds fetching before market comparison so edges include no-vig pricing and EV.",
            "why": "The advisor did not see priced market comparisons in the current report context.",
        })
    if daily.get("game_count", 0) > 0:
        recommendations.append({
            "priority": "medium",
            "area": "explainability",
            "action": "Review high-confidence plays with regime flags before alerting.",
            "why": "Projection quality improves when confidence, factor agreement, injuries, rest, and line movement agree.",
        })

    return recommendations or [{
        "priority": "low",
        "area": "operations",
        "action": "No urgent local upgrade was detected from the available reports.",
        "why": "The current report context did not expose a missing critical pipeline artifact.",
    }]


def advisor_prompt(context: dict):
    return (
        "You are an AI advisor inside a sports projection research bot. "
        "Use the JSON context to identify concrete engineering and model-quality upgrades. "
        "Do not give betting advice or claim profitability. Return strict JSON with keys: "
        "summary, recommendations, risks, next_pipeline_actions. Each recommendation must include "
        "priority, area, action, and why.\n\n"
        f"Context:\n{json.dumps(context, indent=2)[:18000]}"
    )


def extract_response_text(payload: dict):
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    parts = []
    for item in payload.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                parts.append(text)
    return "\n".join(parts).strip()


def parse_json_response(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def call_openai_advisor(context: dict, api_key: str, model: str):
    response = requests.post(
        OPENAI_RESPONSES_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "input": advisor_prompt(context),
            "temperature": 0.2,
            "max_output_tokens": 1400,
        },
        timeout=45,
    )
    response.raise_for_status()
    text = extract_response_text(response.json())
    return parse_json_response(text)


def build_ai_advisor_report(api_key: str | None = None, model: str | None = None):
    context = compact_context()
    api_key = api_key or os.getenv("OPENAI_API_KEY", "").strip()
    model = model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL

    source = "local_rules"
    advisor = {
        "summary": "Local rules generated this report because no AI API response was available.",
        "recommendations": local_recommendations(context),
        "risks": ["This is research support only and not betting advice."],
        "next_pipeline_actions": ["Run the full pipeline, grade completed results, then rerun the advisor."],
    }
    error = None

    if api_key:
        try:
            advisor = call_openai_advisor(context, api_key, model)
            source = "openai_responses_api"
        except Exception as exc:
            error = str(exc)

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": source,
        "model": model if source == "openai_responses_api" else "",
        "advisor": advisor,
        "context_snapshot": context,
        "api_error": error,
        "note": "AI advisor output is for model development and operations review only. It is not betting advice and does not apply code changes automatically.",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main():
    report = build_ai_advisor_report()
    print(json.dumps({
        "source": report["source"],
        "model": report["model"],
        "recommendations": len((report.get("advisor") or {}).get("recommendations", [])),
        "output": str(OUT),
        "api_error": report.get("api_error"),
    }, indent=2))


if __name__ == "__main__":
    main()
