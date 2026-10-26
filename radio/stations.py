"""Загрузка и сохранение списка станций (stations.json — редактируется руками)."""
import json
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_PATH = PROJECT_DIR / "stations.json"


def load_stations(path=DEFAULT_PATH):
    """Читает stations.json. Бросает исключение при ошибке — вызывающий покажет."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("ожидался JSON-список станций")
    stations = []
    for entry in data:
        if isinstance(entry, dict) and entry.get("name") and entry.get("url"):
            stations.append({
                "id": str(entry.get("id") or entry["name"]),
                "name": str(entry["name"]),
                "description": str(entry.get("description") or ""),
                "url": str(entry["url"]),
            })
    return stations


def save_stations(stations, path=DEFAULT_PATH):
    Path(path).write_text(
        json.dumps(stations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
