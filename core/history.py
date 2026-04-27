"""
Gestion de l'historique des sessions.
"""
import json
import os
import time
import uuid

HISTORY_PATH = os.path.join(os.path.dirname(__file__), '..', 'history.json')


def load() -> list:
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def _save(sessions: list):
    with open(HISTORY_PATH, 'w', encoding='utf-8') as f:
        json.dump(sessions, f, indent=2, ensure_ascii=False)


def add(title: str, duration_s: float, total_fame: int, total_silver: int) -> dict:
    sessions = load()
    entry = {
        'id': uuid.uuid4().hex[:8],
        'title': title,
        'date': time.strftime('%d/%m/%Y'),
        'time': time.strftime('%H:%M'),
        'duration_seconds': int(duration_s),
        'total_fame': total_fame,
        'total_silver': total_silver,
        'fame_per_hour': int(total_fame / duration_s * 3600) if duration_s > 0 else 0,
        'silver_per_hour': int(total_silver / duration_s * 3600) if duration_s > 0 else 0,
    }
    sessions.insert(0, entry)
    _save(sessions)
    return entry


def delete(session_id: str):
    sessions = [s for s in load() if s.get('id') != session_id]
    _save(sessions)
