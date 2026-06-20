"""
AI 모델 티어링 (definition 08-core 비용 가드)
"""

MODEL_TIER_LIGHT = "claude-sonnet-4-20250514"
MODEL_TIER_HEAVY = "claude-opus-4-8"

TASK_MODEL = {
    "review_summarize": MODEL_TIER_LIGHT,
    "sentiment": MODEL_TIER_LIGHT,
    "parse_image": MODEL_TIER_LIGHT,
    "race_plan": MODEL_TIER_HEAVY,
    "race_summarize": MODEL_TIER_LIGHT,
}


def model_for(task: str, default: str = MODEL_TIER_LIGHT) -> str:
    return TASK_MODEL.get(task, default)
