#!/usr/bin/env python3
"""Импорт встроенных палитр Noctalia в темы radiofm.

Читает Assets/ColorScheme/*/*.json из репозитория noctalia-shell и пишет
JSON-темы в themes/ (формат radio/theme.py). Для каждой палитры — тёмная
и светлая версия.

Запуск: python3 tools/import_noctalia_themes.py [путь-к-noctalia-shell]
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
THEMES_DIR = HERE / "themes"
DEFAULT_SRC = Path.home() / ".config" / "noctalia-shell.backup" / "Assets" / "ColorScheme"

# порядок как в палитрах Noctalia
ORDER = ["Noctalia-default", "Ayu", "Catppuccin", "Dracula", "Eldritch",
         "Gruvbox", "Kanagawa", "Nord", "Rosepine", "Tokyo-Night"]

# подписи для меню (Rosepine в Noctalia зовётся «Rosé Pine»)
LABEL = {"Rosepine": "Rosé Pine", "Noctalia-default": "Noctalia"}


def _rgb(h):
    s = h.strip().lstrip("#")
    if len(s) == 3:
        s = "".join(c * 2 for c in s)
    return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))


def _hex(c):
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(v)))) for v in c)


def _mix(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _lum(c):
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255.0


def build(pal, dark):
    """Палитра Noctalia (dict с mPrimary/...) → тема radiofm."""
    t = pal["terminal"]
    norm = t.get("normal", {})
    bright = t.get("bright", {})

    primary = _rgb(pal["mPrimary"])
    secondary = _rgb(pal["mSecondary"])
    tertiary = _rgb(pal["mTertiary"])
    surface = _rgb(pal["mSurface"])
    on_surface = _rgb(pal["mOnSurface"])
    variant = _rgb(pal.get("mSurfaceVariant", pal["mSurface"]))

    # canvas — фон окна: чуть отличается от поверхности панелей
    canvas = variant if _lum(variant) != _lum(surface) else _mix(surface, (0, 0, 0) if dark else (255, 255, 255), 0.12)

    # градиент визуализатора: 4 цвета из терминальной палитры
    pick = bright if dark else norm
    ramp_src = [pick.get("green"), pick.get("blue"), pick.get("magenta"),
                pick.get("cyan")]
    ramp = [_hex(_rgb(c)) for c in ramp_src if c]
    while len(ramp) < 4:  # страховка, если в палитре нет терминала
        ramp.append(_hex(primary))
    ramp = ramp[:4]

    # фон визуализатора всегда тёмный, чтобы волна читалась
    viz_bg = _mix(surface, (0, 0, 0), 0.35) if dark else _mix(surface, (0, 0, 0), 0.82)

    return {
        "name": None,  # подставляется вызывающим
        "dark": dark,
        "primary": _hex(primary),
        "secondary": _hex(secondary),
        "tertiary": _hex(tertiary),
        "surface": _hex(surface),
        "on_surface": _hex(on_surface),
        "canvas": _hex(canvas),
        "ramp": ramp,
        "viz_bg": _hex(viz_bg),
    }


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_SRC
    if not src.is_dir():
        sys.exit("нет папки с палитрами: %s" % src)

    THEMES_DIR.mkdir(exist_ok=True)
    written = []
    for stem in ORDER:
        path = src / stem / ("%s.json" % stem)
        if not path.is_file():
            print("пропуск (нет файла): %s" % path)
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        label = LABEL.get(stem, stem)
        for dark, suffix in ((True, ""), (False, " Light")):
            key = "dark" if dark else "light"
            pal = data.get(key)
            if not pal:
                continue
            theme = build(pal, dark)
            theme["name"] = label + suffix
            out = THEMES_DIR / ("noctalia-%s%s.json" % (
                stem.lower().replace("-", "_"),
                "" if dark else "-light"))
            out.write_text(json.dumps(theme, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
            written.append(theme["name"])
    print("записано тем: %d" % len(written))
    for n in written:
        print("  ", n)


if __name__ == "__main__":
    main()
