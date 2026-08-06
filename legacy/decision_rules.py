def decision_grade(model_prob, edge, confidence, factor_agreement):
    model_prob = model_prob or 0
    edge = edge or 0
    factor_agreement = factor_agreement or 0

    if edge < 0:
        return "AVOID"

    if model_prob >= 0.58 and edge >= 0.08 and confidence == "High" and factor_agreement >= 0.80:
        return "BET"

    if model_prob >= 0.55 and edge >= 0.06 and confidence in ["Medium", "High"] and factor_agreement >= 0.75:
        return "LEAN"

    return "PASS"
