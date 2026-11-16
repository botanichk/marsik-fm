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
            station = {
                "id": str(entry.get("id") or entry["name"]),
                "name": str(entry["name"]),
                "description": str(entry.get("description") or ""),
                "url": str(entry["url"]),
            }
            # запасные https-адреса для мобильной версии — не терять при сохранении
            if isinstance(entry.get("urls"), list) and entry["urls"]:
                station["urls"] = [str(u) for u in entry["urls"] if u]
            # обложка станции: без неё мобильная версия рисует буквы вместо логотипа
            if entry.get("logo"):
                station["logo"] = str(entry["logo"])
            stations.append(station)
    return stations


def save_stations(stations, path=DEFAULT_PATH):
    Path(path).write_text(
        json.dumps(stations, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")


def resolve_logo(logo):
    """Логотип станции из stations.json → абсолютный путь.

    В stations.json путь относительный («../assets/logo/x.webp»); берём только
    имя файла и ищем в `<проект>/assets/logo` (штатное), затем в корне
    `<проект>/assets`, затем сам путь как есть. Первое найденное — побеждает.
    (Кастомные обложки станций лежат в assets — не в backgrounds.)
    """
    if not logo:
        return None
    logo = str(logo)
    name = Path(logo).name
    candidates = [
        PROJECT_DIR / "assets" / "logo" / name,
        PROJECT_DIR / "assets" / name,
        Path(logo).expanduser(),
    ]
    for cand in candidates:
        try:
            if cand.is_file():
                return str(cand)
        except OSError:
            continue
    return None
