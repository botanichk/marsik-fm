#!/usr/bin/env python3
"""Проверка потоков из stations.json и поиск https-адресов для телефона.

Запуск (из папки проекта):
    python3 tools/check_streams.py            # только проверить и показать
    python3 tools/check_streams.py --apply    # добавить найденные https-адреса

Что делает:
1. Для каждой станции проверяет адрес (читаются только заголовки, звук не
   качается). Для http-адресов отдельно проверяет https-версию — именно она
   нужна мобильной версии, потому что с https-страницы браузер не играет http.
2. Если у станции нет рабочего https, ищет такую же станцию в каталоге
   radio-browser.info и проверяет найденные https-адреса.
3. С --apply записывает найденное в stations.json в поле "urls" (только для
   телефона; поле "url" для компьютера не трогается). Перед этим делается
   копия stations.json.bak. Результат стоит просмотреть глазами: поиск идёт
   по названию и может найти не ту станцию.

Поиск новых станций с рабочим https (для телефона):
    python3 tools/check_streams.py --find blues bluegrass country --country US
    python3 tools/check_streams.py --name "radio caprice"
    ... добавьте --add, чтобы дописать найденное в stations.json
"""
import argparse
import http.client
import json
import re
import shutil
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATIONS = ROOT / "stations.json"
RB_SERVERS = ("https://de1.api.radio-browser.info",
              "https://nl1.api.radio-browser.info",
              "https://at1.api.radio-browser.info")
UA = "Mozilla/5.0 (Marsik FM stream check)"
GOOD_TYPES = ("audio/", "application/ogg", "application/octet-stream",
              "application/vnd.apple.mpegurl", "application/x-mpegurl")


def probe(url, timeout=8):
    """(ok, подробности, итоговый адрес, имя потока). Читает только заголовки.

    Если https-адрес по цепочке редиректов уходит на http, браузер на телефоне
    такой поток заблокирует (mixed content) — считаем это неудачей.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Icy-MetaData": "0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            ctype = (r.headers.get("Content-Type") or "").lower()
            final = r.geturl()
            name = r.headers.get("icy-name") or ""
            if r.status != 200:
                return False, "HTTP %s" % r.status, final, name
            if ctype.startswith("text/html"):
                return False, "это веб-страница, а не поток", final, name
            if url.startswith("https://") and final.startswith("http://"):
                return False, "перенаправляет на http — телефон заблокирует: " \
                    + final, final, name
            if not ctype or ctype.startswith(GOOD_TYPES):
                return True, "%s%s" % (
                    ctype or "поток", "" if final == url else " → " + final), \
                    final, name
            return False, "неожиданный тип: " + ctype, final, name
    except http.client.BadStatusLine as exc:
        # старый SHOUTcast отвечает не по HTTP: «ICY 200 OK» — это нормальный поток
        if "ICY" in str(exc):
            return True, "ICY (SHOUTcast)", url, ""
        return False, "странный ответ сервера", url, ""
    except Exception as exc:
        reason = getattr(exc, "reason", exc)
        return False, "%s" % str(reason)[:70], url, ""


def https_variant(url):
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(("https",) + tuple(p[1:])) \
        if p.scheme == "http" else url


def words(name):
    return [w for w in re.split(r"[^\w]+", name.lower()) if len(w) > 2]


def name_queries(name):
    """Варианты названия для поиска: целиком, затем после тире."""
    full = re.sub(r"[—–\-]+", " ", name).strip()
    out = [full]
    parts = [p.strip() for p in re.split(r"\s[—–-]\s", name) if p.strip()]
    if len(parts) > 1:
        out.append(parts[-1])
    return list(dict.fromkeys(out))


def pick_candidates(station_name, results, limit=4):
    """Из ответа каталога — https-адреса станций с похожим названием."""
    need = words(station_name)
    out, seen = [], set()
    for r in results:
        got = words(r.get("name", ""))
        if need and not all(w in got for w in need[-2:]):
            continue
        url = r.get("url_resolved") or r.get("url") or ""
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        out.append((r.get("name", ""), url))
        if len(out) >= limit:
            break
    return out


def rb_search(name):
    q = urllib.parse.urlencode({"name": name, "limit": 20, "hidebroken": "true",
                                "order": "votes", "reverse": "true"})
    for server in RB_SERVERS:
        try:
            req = urllib.request.Request(
                "%s/json/stations/search?%s" % (server, q),
                headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.load(r)
        except Exception:
            continue
    return []


def check_station(st):
    urls = st.get("urls") or [st["url"]]
    res = {"station": st, "checks": [], "https_ok": None, "found": [],
           "stream_name": "", "catalog": None}
    for url in urls:
        ok, why, final, sname = probe(url)
        res["checks"].append(("оригинал", url, ok, why))
        res["stream_name"] = res["stream_name"] or sname
        if url.startswith("https://"):
            if ok:
                res["https_ok"] = url
            elif final.startswith("http://") and final != url:
                # https-адрес ведёт на http-сервер: пробуем https-версию конца цепочки
                hv = https_variant(final)
                ok2, why2, _f, _n = probe(hv)
                res["checks"].append(("https по цепочке", hv, ok2, why2))
                if ok2:
                    res["https_ok"] = hv
        if url.startswith("http://"):
            hv = https_variant(url)
            ok2, why2, _f, _n = probe(hv)
            res["checks"].append(("https-версия", hv, ok2, why2))
            if ok2:
                res["https_ok"] = hv
    if not res["https_ok"]:
        seen = set()
        stat = {"найдено": 0, "по названию": 0, "https рабочих": 0}
        for q in name_queries(st["name"]):
            raw = rb_search(q)
            stat["найдено"] += len(raw)
            cands = pick_candidates(st["name"], raw)
            stat["по названию"] += len(cands)
            for name, url in cands:
                for cand in dict.fromkeys((https_variant(url), url)):
                    if not cand.startswith("https://") or cand in seen:
                        continue
                    seen.add(cand)
                    ok, why, _f, _n = probe(cand)
                    if ok:
                        res["found"].append((name, cand, why))
                        stat["https рабочих"] += 1
            if res["found"]:
                break
        res["catalog"] = stat
    return res


# ---------- поиск новых станций ----------

def rb_query(params):
    q = urllib.parse.urlencode(dict(params, hidebroken="true",
                                    order="clickcount", reverse="true"))
    for server in RB_SERVERS:
        try:
            req = urllib.request.Request(
                "%s/json/stations/search?%s" % (server, q),
                headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=12) as r:
                return json.load(r)
        except Exception:
            continue
    return None


def slug(name):
    return re.sub(r"[^\w]+", "_", name.lower()).strip("_")[:40] or "station"


def discover(results, limit, have_urls):
    """Из ответа каталога — станции с проверенным рабочим https-потоком."""
    cands, seen_names = [], set()
    for r in results:
        url = r.get("url_resolved") or r.get("url") or ""
        name = (r.get("name") or "").strip()
        if not name or name.lower() in seen_names or url in have_urls:
            continue
        if not url.startswith(("https://", "http://")):
            continue
        seen_names.add(name.lower())
        cands.append((name, https_variant(url), r))
    out = []

    def check(item):
        name, url, r = item
        ok, why, final, sname = probe(url)
        return item, ok, why

    with ThreadPoolExecutor(max_workers=8) as pool:
        for item, ok, why in pool.map(check, cands[:limit * 4]):
            if ok:
                out.append(item)
            if len(out) >= limit:
                break
    return out


def find_mode(args):
    stations = json.loads(STATIONS.read_text(encoding="utf-8"))
    have = {s.get("url") for s in stations} | {
        u for s in stations for u in s.get("urls", [])}
    found, seen = [], set()
    queries = []
    if args.name:
        queries.append(("название «%s»" % args.name, {"name": args.name}))
    for tag in args.find or []:
        p = {"tag": tag, "tagExact": "false"}
        queries.append(("жанр «%s»" % tag, p))
    for label, params in queries:
        params = dict(params, limit=60)
        if args.country:
            params["countrycode"] = args.country.upper()
        print("Ищу: %s%s…" % (label, " (%s)" % args.country.upper()
                              if args.country else ""))
        res = rb_query(params)
        if res is None:
            print("  каталог radio-browser.info не отвечает — проверь интернет/VPN")
            continue
        picked = discover(res, args.limit, have | seen)
        print("  в каталоге %d, с рабочим https-потоком: %d" % (len(res), len(picked)))
        for item in picked:
            name, url, r = item
            seen.add(url)
            found.append(item)
            print("    • %s  [%s, %s %s kbps]\n        %s" % (
                name, r.get("tags", "")[:40], r.get("codec", "?"),
                r.get("bitrate", "?"), url))
        print()
    if not found:
        print("Ничего нового не нашлось.")
        return 0
    if args.add:
        existing = {s["id"] for s in stations}
        added = 0
        for name, url, r in found:
            sid = slug(name)
            while sid in existing:
                sid += "_2"
            existing.add(sid)
            stations.append({"id": sid, "name": name,
                             "description": (r.get("tags") or "").replace(",", ", ")[:80],
                             "url": url})
            added += 1
        shutil.copy(STATIONS, str(STATIONS) + ".bak")
        STATIONS.write_text(json.dumps(stations, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        print("Добавлено станций: %d (копия: stations.json.bak)" % added)
    else:
        print("Найдено %d. Чтобы дописать их в stations.json, повтори с --add." % len(found))
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true",
                    help="записать найденные https-адреса в stations.json")
    ap.add_argument("--find", nargs="+", metavar="ЖАНР",
                    help="найти новые станции по жанрам, например: blues country")
    ap.add_argument("--name", help="найти станции по части названия")
    ap.add_argument("--country", help="код страны, например US")
    ap.add_argument("--limit", type=int, default=8,
                    help="сколько станций на запрос (по умолчанию 8)")
    ap.add_argument("--add", action="store_true",
                    help="с --find/--name: дописать найденное в stations.json")
    args = ap.parse_args()
    if args.find or args.name:
        return find_mode(args)

    stations = json.loads(STATIONS.read_text(encoding="utf-8"))
    print("Проверяю %d станций (это займёт полминуты)…\n" % len(stations))
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(check_station, stations))

    changed = 0
    for res in results:
        st = res["station"]
        good = res["https_ok"]
        mark = "✓" if good else "✗"
        print("%s %s" % (mark, st["name"]))
        if res["stream_name"]:
            print("    поток называется: %s" % res["stream_name"])
        for kind, url, ok, why in res["checks"]:
            print("    %-13s %s  %s" % (kind, "ок " if ok else "нет", why))
        if good:
            print("    → для телефона подходит: %s" % good)
            # https-оригинал, который сам не годится (уходит на http), а конец
            # цепочки по https играет — это нужно записать для телефона
            orig_failed = st["url"].startswith("https://") and not any(
                ok for kind, u, ok, _w in res["checks"]
                if kind == "оригинал" and u == st["url"])
            if args.apply and orig_failed and good != st["url"]:
                for s in stations:
                    if s["id"] == st["id"]:
                        s["urls"] = [good]
                        changed += 1
        elif res["found"]:
            print("    → найдено в каталоге (проверь, та ли это станция):")
            for name, url, why in res["found"][:3]:
                print("        %s\n          %s" % (name, url))
            if args.apply:
                for s in stations:
                    if s["id"] == st["id"]:
                        s["urls"] = [res["found"][0][1]]
                        changed += 1
        else:
            print("    → https-адрес не найден: на телефоне не заиграет")
            c = res.get("catalog")
            if c is not None:
                print("    каталог: ответил %d, подошло по названию %d, "
                      "рабочих https %d" % (c["найдено"], c["по названию"],
                                            c["https рабочих"]))
                if not c["найдено"]:
                    print("    (каталог не ответил — проверь интернет/VPN)")
        print()

    ok_n = sum(1 for r in results if r["https_ok"])
    print("Итог: для телефона годятся %d из %d." % (ok_n, len(results)))
    if args.apply and changed:
        shutil.copy(STATIONS, str(STATIONS) + ".bak")
        STATIONS.write_text(
            json.dumps(stations, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print("Записано %d станций (поле urls). Копия: stations.json.bak" % changed)
    elif args.apply:
        print("Применять нечего.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
