from __future__ import annotations
from datetime import datetime
from dateutil import parser as dtparser
from typing import Dict, Any, Optional
import pandas as pd
from .config import SETTINGS

STAGE_THRESHOLDS = {
    "Лид": 10,
    "Переговоры": 14,
    "Коммерческое": 10,
    "Предложение": 7,
    "Закрытие": 7,
}

NEGATIVE_KEYWORDS = [
    "дорого", "подождем", "выбрали другого", "неинтересно", "откажемся", "позже",
]


class RiskResult:
    def __init__(self, score: float, level: str, explanation: str):
        self.score = score
        self.level = level
        self.explanation = explanation

def days_since(date_str: str) -> int:
    dt = dtparser.parse(date_str)
    # naive -> treat as local
    now = datetime.now()
    return (now - dt).days

def stage_stall_days(stage: str, last_stage_change_date: Optional[str]) -> int:
    if not last_stage_change_date:
        return 0
    return days_since(last_stage_change_date)

def compute_risk_row(row: pd.Series, tone: str) -> RiskResult:
    # Weights (tuneable)
    W_STALE = 0.6
    W_STAGE = 0.5
    W_TONE_NEG = 0.8
    W_TONE_POS = -0.3

    d_stale = days_since(row["last_contact_date"])
    d_stage = stage_stall_days(row.get("last_stage_change_date", None), row.get("last_stage_change_date", None))

    score = 0.0
    reasons = []

    # Staleness
    if d_stale > 14:
        score += W_STALE * 2
        reasons.append(f"нет ответа {d_stale} дней")
    elif d_stale > 7:
        score += W_STALE * 1
        reasons.append(f"нет ответа {d_stale} дней")

    # Stage stall
    stage = row.get("stage", "Переговоры")
    thr = STAGE_THRESHOLDS.get(stage, 10)
    if d_stage and d_stage > thr:
        score += W_STAGE * 1.5
        reasons.append(f"застряла в стадии '{stage}' {d_stage} дней (порог {thr})")

    # Tone
    if tone == "negative":
        score += W_TONE_NEG
        reasons.append("негативный тон последнего сообщения")
    elif tone == "positive":
        score += W_TONE_POS
        reasons.append("позитивный тон последнего сообщения")

    # Keyword heuristics
    text = (row.get("last_message_text", "") or "").lower()
    if any(kw in text for kw in NEGATIVE_KEYWORDS):
        score += 0.4
        reasons.append("обнаружены триггерные фразы (напр. 'дорого', 'позже')")

    # Bucketize
    if score >= 1.5:
        level = "red"
    elif score >= 0.7:
        level = "yellow"
    else:
        level = "green"

    explanation = "; ".join(reasons) if reasons else "риски не выявлены"
    return RiskResult(score=round(score, 2), level=level, explanation=explanation)
