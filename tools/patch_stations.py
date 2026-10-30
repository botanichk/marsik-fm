"""Учит radio/stations.py сохранять поле urls (запасные https-адреса для телефона)."""
import sys
p = sys.argv[1] if len(sys.argv) > 1 else "radio/stations.py"
s = open(p, encoding="utf-8").read()
if '"urls"' in s:
    print("уже исправлено"); sys.exit(0)
old = '''            stations.append({
                "id": str(entry.get("id") or entry["name"]),
                "name": str(entry["name"]),
                "description": str(entry.get("description") or ""),
                "url": str(entry["url"]),
            })'''
new = '''            station = {
                "id": str(entry.get("id") or entry["name"]),
                "name": str(entry["name"]),
                "description": str(entry.get("description") or ""),
                "url": str(entry["url"]),
            }
            # запасные https-адреса для мобильной версии — не терять при сохранении
            if isinstance(entry.get("urls"), list) and entry["urls"]:
                station["urls"] = [str(u) for u in entry["urls"] if u]
            stations.append(station)'''
if old not in s:
    print("stations.py отличается от ожидаемого — не трогаю, пришли файл"); sys.exit(1)
open(p, "w", encoding="utf-8").write(s.replace(old, new))
print("готово")
