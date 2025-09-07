from __future__ import annotations
import os, time, requests
import pandas as pd
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv, find_dotenv


load_dotenv(find_dotenv(), override=True)

BASE = os.getenv("KOMMO_BASE_URL", "").rstrip("/")
TOKEN = os.getenv("KOMMO_ACCESS_TOKEN", "")
LIMIT = int(os.getenv("KOMMO_API_LIMIT", "100"))

def _headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

def _get(url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not BASE or not TOKEN:
        raise RuntimeError("Set KOMMO_BASE_URL and KOMMO_ACCESS_TOKEN in .env")
    for attempt in range(3):
        try:
            r = requests.get(
                url,
                headers={
                    "Authorization": f"Bearer {TOKEN}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": "kommo-client/1.0",
                },
                params=params,
                timeout=20,
            )
            # 204 = пустой ответ -> вернём пустую структуру
            if r.status_code == 204 or not (r.text or "").strip():
                return {}
            r.raise_for_status()
            ct = (r.headers.get("Content-Type") or "").lower()
            if "json" in ct:
                return r.json()
            raise RuntimeError(
                f"Unexpected response (status {r.status_code}, CT={ct}): {r.text[:300]}"
            )
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def fetch_leads(limit: int = 200) -> List[Dict[str, Any]]:
    """Берём лиды /api/v4/leads (первые N, пагинация)."""
    url = f"{BASE}/api/v4/leads"
    out: List[Dict[str, Any]] = []
    page, remain = 1, limit
    while remain > 0:
        per_page = min(LIMIT, remain)
        data = _get(url, params={"page": page, "limit": per_page, "with": "contacts"})
        chunk = data.get("_embedded", {}).get("leads", [])
        if not chunk:
            break
        out.extend(chunk)
        remain -= len(chunk)
        page += 1
    return out

def fetch_last_note(lead_id: int) -> str:
    """Последняя заметка лида как текст (если есть)."""
    url = f"{BASE}/api/v4/leads/{lead_id}/notes"
    data = _get(url, params={"limit": 1, "page": 1, "order[created_at]": "desc"})
    notes = data.get("_embedded", {}).get("notes", [])
    if not notes:
        return ""
    note = notes[0]
    return note.get("params", {}).get("text") or note.get("text") or ""

def normalize_to_df(leads: List[Dict[str, Any]], fetch_notes: bool = True) -> pd.DataFrame:
    """Приводим к формату нашего риск-движка."""
    rows = []
    for lead in leads:
        lead_id = lead.get("id")
        name = lead.get("name") or f"Lead {lead_id}"
        price = lead.get("price") or 0
        status_id = lead.get("status_id")
        ts = lead.get("updated_at") or lead.get("created_at")
        last_date = ""
        if ts:
            import datetime
            last_date = datetime.datetime.utcfromtimestamp(int(ts)).date().isoformat()

        last_msg = fetch_last_note(lead_id) if (fetch_notes and lead_id) else ""
        rows.append({
            "deal_id": str(lead_id),
            "client_name": name,
            "stage": str(status_id),              # пока ID стадии
            "last_contact_date": last_date,       # yyyy-mm-dd
            "last_message_text": last_msg,
            "owner": str(lead.get("responsible_user_id")),
            "deal_value": price,
            "last_stage_change_date": None,       # можно доработать позже
        })
    return pd.DataFrame(rows)

def create_task(lead_id: int, text: str, complete_till_ts: int, responsible_user_id: int | None = None) -> dict:
    """
    Создать задачу в Kommo, привязанную к сделке (entity_type=leads).
    complete_till_ts — unix timestamp дедлайна (например, сегодня 18:00).
    """
    url = f"{BASE}/api/v4/tasks"
    payload = [{
        "text": text,
        "complete_till": int(complete_till_ts),
        "entity_id": int(lead_id),
        "entity_type": "leads",
        **({"responsible_user_id": int(responsible_user_id)} if responsible_user_id else {})
    }]
    r = requests.post(url, headers=_headers(), json=payload, timeout=20)
    r.raise_for_status()
    ct = (r.headers.get("Content-Type") or "").lower()
    return r.json() if "json" in ct else {"status": r.status_code}

