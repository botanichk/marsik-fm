"""Длительности локальных треков для списка «Скачанные».

Читаются через mutagen (быстро, без запуска процессов): на шести файлах
~55 мс. Если mutagen недоступен или файл битый — падаем на ffprobe, а если
и его нет, возвращаем None (в списке просто не будет времени).

Результат кэшируется по (путь, mtime, размер): повторное открытие меню не
перечитывает теги.
"""
import os
import subprocess

try:
    from mutagen import File as _MFile
except Exception:      # mutagen не установлен — останется ffprobe
    _MFile = None

_CACHE = {}


def _key(path):
    st = os.stat(path)
    return (path, int(st.st_mtime), st.st_size)


def _from_mutagen(path):
    if _MFile is None:
        return None
    try:
        f = _MFile(path)
        length = getattr(getattr(f, "info", None), "length", None)
        if length:
            return float(length)
    except Exception:
        return None
    return None


def _from_ffprobe(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", path],
            capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return float(out.stdout.strip().splitlines()[0])
    except Exception:
        return None
    return None


def duration(path):
    """Длительность файла в секундах или None."""
    try:
        key = _key(path)
    except OSError:
        return None
    if key in _CACHE:
        return _CACHE[key]
    value = _from_mutagen(path)
    if value is None:
        value = _from_ffprobe(path)
    _CACHE[key] = value
    return value


def fmt_time(seconds):
    """Секунды → «3:27» или «1:02:05» (None/0 → «—:—»)."""
    if not seconds or seconds < 0:
        return "—:—"
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return "%d:%02d:%02d" % (h, m, s)
    return "%d:%02d" % (m, s)
