from __future__ import annotations
import time, json, re, hashlib
import requests
from typing import Dict, Any
from .config import SETTINGS

POSTPONE_PATTERNS = [
    r"\bчерез\s+недел", r"\bна\s+следующ(ей|ую)\s+недел",
    r"\bпозже\b", r"\bдавайте\s+позже\b", r"\bперенес(ём|ем)\b",
    r"\bсвяжем(ся)?\s+позже\b", r"\bверн(ёмся|емся)\s+позже\b",
]
PRICE_PATTERNS = [r"\bдорого\b", r"\bбюджет(а|у)?\s*нет\b"]
CHOOSE_OTHER_PATTERNS = [r"\bвыбрали\s+другого\b", r"\bостановилис[ья]\s+на\b"]
REFUSAL_PATTERNS = [r"\bоткаж\w*\b", r"\bнеинтересно\b"]

def semantic_triggers(text:str) -> list[str]:
    t = (text or "").lower()

    def any_match(pats):
        return any(re.search(p, t, re.I) for p in pats)

    triggers = []
    if any_match(POSTPONE_PATTERNS): triggers.append("postpone")
    if any_match(PRICE_PATTERNS): triggers.append("price_objection")
    if any_match(CHOOSE_OTHER_PATTERNS): triggers.append("chose_other")
    if any_match(REFUSAL_PATTERNS): triggers.append("refusal")
    return triggers


_CACHE: dict[str, dict] = {}

def _hash_features(feats: Dict[str, Any]) -> str:
    s = json.dumps(feats, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def _extract_json_block(text: str) -> dict:
    """
    Пытаемся вытащить первый JSON-объект из ответа модели, даже если она добавила текст вокруг.
    """
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON object found in LLM response")
    return json.loads(m.group(0))

class LLMClient:
    def __init__(self,
                 api_url: str = SETTINGS.llm_api_url,
                 api_key: str = SETTINGS.llm_api_key,
                 model: str = SETTINGS.llm_model):
        self.api_url = api_url
        self.api_key = api_key
        self.model = model
        self.timeout = SETTINGS.request_timeout_seconds
        self.max_retries = SETTINGS.request_max_retries

    def _post(self, payload: dict) -> dict:
        headers = {
            "accept": "application/json",
            "x-litellm-api-key": self.api_key,
            "Content-Type": "application/json"
        }
        last_err = None
        for attempt in range(1, self.max_retries + 1):
            try:
                r = requests.post(self.api_url, headers=headers, json=payload, timeout=self.timeout)
                r.raise_for_status()
                return r.json()
            except Exception as e:
                last_err = e
                if attempt == self.max_retries:
                    raise
                time.sleep(min(2 ** attempt, 4))
        raise last_err  # на всякий случай

    def classify_tone(self, text: str) -> str:
        """
        Если вдруг понадобится отдельно получить тон. (Можно не использовать.)
        """
        prompt = f"""Классифицируй ТОН сообщения клиента как одно слово:
positive | neutral | negative

Сообщение: "{text}"
Ответь строго одним словом (без комментариев).
"""
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        data = self._post(payload)
        content = data["choices"][0]["message"]["content"].strip().lower()
        if "positive" in content: return "positive"
        if "negative" in content: return "negative"
        return "neutral"

    def assess_risk_llm(self, features: Dict[str, Any]) -> dict:
        """
        LLM-only оценка риска.
        модель НЕ может ссылаться на "задержку" или "старение",
        если соответствующие триггеры не активны. - чтоб галлюнов не было
        Вход features:
          {
            "deal_id": str,
            "client_name": str,
            "stage": str,
            "last_contact_days": int,
            "stage_age_days": int,
            "deal_value": float,
            "last_message_text": str
          }
        Возвращает dict:
          {
            "score": float [0..2],
            "level": "green"|"yellow"|"red",
            "reason": str (ru),
            "action": str (ru)
          }
        """
        lcd = int(features.get("last_contact_days", 0) or 0)
        sad = int(features.get("stage_age_days", 0) or 0)

        active_triggers = []
        if lcd > 14:
            active_triggers.append("no_reply_high")
        elif lcd > 7:
            active_triggers.append("no_reply_medium")

        if sad > 14:
            active_triggers.append("stage_age_high")
        elif sad > 7:
            active_triggers.append("stage_age_medium")

        guarded_feats = dict(features)
        guarded_feats["active_triggers"] = active_triggers

        sem_triggers = semantic_triggers(features.get("last_message_text", ""))
        guarded_feats = dict(features)
        guarded_feats["active_triggers"] = active_triggers
        guarded_feats["semantic_triggers"] = sem_triggers

        key = _hash_features(guarded_feats)
        if key in _CACHE:
            return _CACHE[key]

        # строгая инструкция для минимизации галлюцинаций
        prompt = f"""
Ты ассистент руководителя продаж. Оцени РИСК по сделке и предложи короткое действие менеджеру.
ОПИРАЙСЯ ТОЛЬКО на переданные признаки и список active_triggers. НЕ придумывай факторы.

Правила оценки (для консистентности):
- last_contact_days > 14 → высокий риск; 7–14 → средний.
- stage_age_days значительно выше типичных (если >14 — высокий, 7–14 — средний) → повышай риск.
- Негатив/отказ/«дорого», «выбрали другого», «откажемся», «неинтересно», «приостановим», «позже» → повышай риск.
- Позитивные сигналы («жду предложение», «финализировать») → слегка снижают.
- Большая сумма усиливает уже обнаруженный риск (но сама по себе не делает red).
- semantic_triggers может содержать: "postpone", "price_objection", "chose_other", "refusal".
  * "postpone" (перенос/«через неделю», «позже») => уровень НЕ может быть green (минимум yellow).
  * "price_objection" или "chose_other" или "refusal" => повышай риск.
- Итоговый score верни от 0 до 2 с шагом 0.1 примерно: 0..0.89=green, 0.9..1.99=yellow, >=2.0=red.

Верни СТРОГО JSON без лишнего текста:
{{
  "score": <float 0..2>,
  "level": "green"|"yellow"|"red",
  "reason": "<кратко по-русски, 1–2 причины>",
  "action": "<следующий шаг менеджера, 1 короткое предложение>"
}}

Признаки:
{json.dumps(guarded_feats, ensure_ascii=False)}
"""
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        data = self._post(payload)
        raw = data["choices"][0]["message"]["content"]

        try:
            obj = _extract_json_block(raw)
            level = str(obj.get("level", "yellow")).lower()
            if level not in {"green","yellow","red"}:
                level = "yellow"
            score = float(obj.get("score", 1.0))
            if score < 0: score = 0.0
            if score > 2: score = 2.0
            reason = str(obj.get("reason", "")).strip() or "причина не указана"
            action = str(obj.get("action", "")).strip() or "Связаться с клиентом сегодня"
            # если клиент перенёс ("postpone"), green недопустим
            if "postpone" in sem_triggers and level == "green":
                level = "yellow"
                # можно слегка подвинуть score если он слишком низкий
                if score < 0.9: score = 0.9
                if "перенос" not in reason and "позже" not in reason:
                    reason = (reason + "; перенос обсуждения").strip("; ").strip()
                if not action or action.lower().startswith("свяж"):
                    action = "Запланируйте слот на следующей неделе и закрепите повестку письмом."
            out = {"score": round(score,2), "level": level, "reason": reason, "action": action}
        except Exception:
            # безопасный фоллбэк
            out = {"score": 1.0, "level": "yellow", "reason": "fallback: не удалось распарсить ответ", "action": "Связаться с клиентом"}

        _CACHE[key] = out
        return out

    def draft_followup(self, client_name: str, reason: str, last_message_text: str) -> str:
        """
        Короткий follow-up (4–6 предложений) под причину риска. На русском, деловой тон.
        """
        prompt = f"""
    Сгенерируй краткий follow-up менеджера продаж (4–6 предложений) на русском.
    Контекст:
    - Клиент: "{client_name}"
    - Причина риска: "{reason}"
    - Последнее сообщение клиента: "{last_message_text}"

    Требования: вежливо и по делу, без воды; 2–3 слота на звонок; призыв к действию. Верни только текст письма.
    """
        payload = {"model": self.model, "messages": [{"role": "user", "content": prompt}]}
        data = self._post(payload)
        return data["choices"][0]["message"]["content"].strip()
