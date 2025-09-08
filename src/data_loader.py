from __future__ import annotations
import os, time, requests
import pandas as pd
from typing import Dict, Any, List, Optional, Callable
from dotenv import load_dotenv, find_dotenv


load_dotenv(find_dotenv(), override=True)

BASE = os.getenv("KOMMO_BASE_URL", "").rstrip("/")
TOKEN = os.getenv("KOMMO_ACCESS_TOKEN", "")
LIMIT = int(os.getenv("KOMMO_API_LIMIT", "100"))

def _headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

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


def fetch_leads(base_url: str, token: str, limit: int = 200):
    url = f"{base_url.rstrip('/')}/api/v4/leads?limit={limit}"
    r = requests.get(url, headers=_headers(token), timeout=20)
    r.raise_for_status()
    return r.json()

def fetch_last_note(lead_id: int, *, base_url: str, token: str, timeout: int = 10) -> str:
    """
    Возвращает текст последней заметки/сообщения по сделке.
    Работает в контексте конкретного аккаунта (base_url + token).
    """
    url = f"{base_url}/api/v4/leads/{lead_id}/notes"
    params = {"limit": 1, "page": 1, "order": "desc"}  # последняя
    headers = {"Authorization": f"Bearer {token}"}

    r = requests.get(url, headers=headers, params=params, timeout=timeout)
    r.raise_for_status()
    notes = r.json().get("_embedded", {}).get("notes", [])
    if not notes:
        return ""

    n = notes[0]
    # разные типы заметок в Kommo могут хранить текст в разных местах
    text = (
        n.get("text")
        or (n.get("params") or {}).get("text")
        or (n.get("params") or {}).get("message")
        or ""
    )
    return (text or "").strip()


def normalize_to_df(
    leads: List[Dict[str, Any]],
    fetch_notes: bool = True,
    base_url: Optional[str] = None,
    token: Optional[str] = None,
    note_fetcher: Optional[Callable[[int], str]] = None,
) -> pd.DataFrame:
    """
    Приводим к формату риск-движка. ВАЖНО: заметки тянем теми же base_url/token,
    что и сами лиды. Либо передайте готовый note_fetcher, уже "забинденный" на креды.
    """
    base_url = (base_url or os.getenv("KOMMO_BASE_URL", "")).rstrip("/")
    token = token or os.getenv("KOMMO_ACCESS_TOKEN", "")

    if fetch_notes and note_fetcher is None and (not base_url or not token):
        fetch_notes = False  # безопасный даунгрейд

    rows: List[Dict[str, Any]] = []
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

        # берём заметку строго из ТЕКУЩЕГО аккаунта
        last_msg = ""
        if fetch_notes and lead_id:
            try:
                if note_fetcher is not None:
                    last_msg = note_fetcher(int(lead_id)) or ""
                else:
                    last_msg = fetch_last_note(int(lead_id), base_url=base_url, token=token) or ""
            except Exception:
                # не даём упасть пайплайну из-за одной кривой заметки
                last_msg = ""

        rows.append({
            "deal_id": str(lead_id),
            "client_name": name,
            "stage": str(status_id),              # ID стадии
            "last_contact_date": last_date,       # yyyy-mm-dd
            "last_message_text": last_msg,
            "owner": str(lead.get("responsible_user_id")),
            "deal_value": float(price or 0),
            "last_stage_change_date": None,       # можно доработать позже
        })

    return pd.DataFrame(rows)


def create_task(base_url: str, token: str, lead_id: int, text: str, complete_till: int, responsible_user_id: int | None = None):
    url = f"{base_url.rstrip('/')}/api/v4/tasks"
    payload = [{"text": text, "complete_till": complete_till, "entity_id": lead_id, "entity_type": "leads",
                **({"responsible_user_id": responsible_user_id} if responsible_user_id else {})}]
    r = requests.post(url, headers=_headers(token), json=payload, timeout=20)
    r.raise_for_status()
    return r.json()

