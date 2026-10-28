"""Темы Marsik FM: цвета интерфейса и визуализаторов в одном месте.

Тема — набор ролей (как в Material You / Noctalia): акценты primary,
secondary, tertiary, поверхность, цвет текста на поверхности, фон окна и
градиент из 4 цветов для визуализаций. Всё остальное (наведение, рамки,
приглушённый текст) выводится из этих ролей, поэтому тему можно описать
десятком цветов.

Свои темы — JSON-файлы в папке themes/ рядом с проектом (имя файла, не
начинающееся с «_»). Пропущенные поля берутся из темы Marsik:

    {
      "name": "Закат",
      "dark": false,
      "primary": "#e8743b",   "secondary": "#4a2f50",  "tertiary": "#c46a2c",
      "surface": "#fff6ee",   "on_surface": "#40312a", "canvas": "#f8f0e4",
      "ramp": ["#ffb347", "#ff7e5f", "#c94b8a", "#6a4c93"],
      "viz_bg": "#150f1e"
    }

Менеджер ThemeManager (синглтон `manager`) шлёт сигнал changed при смене
темы; визуализаторы просто читают manager.current при каждой отрисовке.
"""
import json
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor

THEMES_DIR = Path(__file__).resolve().parent.parent / "themes"
DEFAULT_THEME = "Marsik"
_POS = (0.00, 0.30, 0.65, 1.00)


# ---------- цветовые утилиты ----------

def parse_color(v):
    """'#rrggbb' / '#rgb' / [r, g, b] → (r, g, b). ValueError при мусоре."""
    if isinstance(v, str):
        s = v.strip().lstrip("#")
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        if len(s) != 6:
            raise ValueError("цвет должен быть #rrggbb: %r" % v)
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    r, g, b = v[:3]
    return (int(r), int(g), int(b))


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def lighten(c, k):
    return mix(c, (255, 255, 255), k)


def darken(c, k):
    return mix(c, (0, 0, 0), k)


def luminance(c):
    return (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255.0


def hexs(c):
    return "#%02x%02x%02x" % tuple(c)


def rgba(c, a):
    return "rgba(%d, %d, %d, %d)" % (c[0], c[1], c[2], a)


# ---------- тема ----------

class Theme:
    def __init__(self, name, primary, secondary, tertiary, surface,
                 on_surface, canvas, ramp, viz_bg, dark=None):
        self.name = name
        self.primary = parse_color(primary)
        self.secondary = parse_color(secondary)
        self.tertiary = parse_color(tertiary)
        self.surface = parse_color(surface)
        self.on_surface = parse_color(on_surface)
        self.canvas = parse_color(canvas)
        ramp = [parse_color(c) for c in ramp]
        if len(ramp) != 4:
            raise ValueError("ramp: нужно ровно 4 цвета")
        self.ramp_colors = ramp
        self.stops = list(zip(_POS, ramp))
        self.viz_bg = parse_color(viz_bg)
        self.dark = (luminance(self.surface) < 0.5) if dark is None \
            else bool(dark)

        # производные роли
        self.viz_bg_dark = darken(self.viz_bg, 0.45)
        self.muted = mix(self.on_surface, self.surface, 0.45)
        self.disabled = mix(self.on_surface, self.surface, 0.68)
        self.field = (lighten(self.surface, 0.07) if self.dark
                      else lighten(self.surface, 0.5))
        self.on_primary = ((255, 255, 255) if luminance(self.primary) < 0.62
                           else (36, 28, 26))
        if self.dark:
            self.veil = (darken(self.canvas, 0.5), 70)
        else:
            self.veil = (lighten(self.canvas, 0.6), 46)
        # статусы: чуть разные для светлых/тёмных тем
        self.ok = (110, 214, 160) if self.dark else (42, 157, 106)
        self.warn = (240, 190, 90) if self.dark else (196, 138, 26)
        self.err = (255, 120, 100) if self.dark else (210, 74, 42)

    # --- помощники для рисования ---

    def q(self, rgb, alpha=255):
        return QColor(rgb[0], rgb[1], rgb[2], alpha)

    def ramp(self, h):
        """Градиент темы 0..1 → (r, g, b)."""
        h = max(0.0, min(1.0, h))
        for i in range(len(self.stops) - 1):
            p0, c0 = self.stops[i]
            p1, c1 = self.stops[i + 1]
            if h <= p1:
                t = (h - p0) / (p1 - p0) if p1 > p0 else 0.0
                return mix(c0, c1, max(0.0, min(1.0, t)))
        return self.stops[-1][1]

    # --- переменные для таблицы стилей ---

    def css(self):
        p, s, o = self.primary, self.surface, self.on_surface
        soft = mix(s, p, 0.30)
        return {
            "text": hexs(o), "muted": hexs(self.muted),
            "disabled": hexs(self.disabled),
            "title": hexs(self.secondary), "accent": hexs(self.tertiary),
            "surface": hexs(s), "field": hexs(self.field),
            "primary": hexs(p), "on_primary": hexs(self.on_primary),
            "panel_bg": rgba(s, 222), "bar_bg": rgba(s, 232),
            "line": rgba(o, 34), "line2": rgba(o, 46), "line3": rgba(o, 60),
            "pill_bg": rgba(s, 235), "pill_border": rgba(p, 120),
            "pill_border_h": rgba(p, 220), "pill_hover": rgba(soft, 220),
            "primary_a": rgba(p, 235),
            "primary_h": rgba(lighten(p, 0.1), 245),
            "primary_p": rgba(darken(p, 0.1), 245),
            "primary_border": rgba(darken(p, 0.2), 160),
            "btn_bg": rgba(self.field, 220), "btn_hover": rgba(soft, 200),
            "btn_press": rgba(mix(s, p, 0.5), 220),
            "play_hover": rgba(mix(s, p, 0.4), 220),
            "prog_bg": rgba(o, 40),
            "prog_a": hexs(lighten(p, 0.15)), "prog_b": hexs(darken(p, 0.05)),
        }


def _t(name, primary, secondary, tertiary, surface, on_surface, canvas,
       ramp, viz_bg):
    return Theme(name, primary, secondary, tertiary, surface, on_surface,
                 canvas, ramp, viz_bg)


def _builtin():
    themes = [
        _t("Marsik", "#e08a3c", "#4a2f50", "#c46a2c", "#fffaf3", "#40312a",
           "#f8f0e4",
           ["#3dd8ff", "#4b82ff", "#965fff", "#e256ff"], "#0b0e1a"),
        _t("Ночь", "#5ac8ff", "#c0aaff", "#78e6ff", "#1e2234", "#e2e8f5",
           "#0e101c",
           ["#3dd8ff", "#4b82ff", "#965fff", "#e256ff"], "#0b0e1a"),
        _t("Роза", "#e86c96", "#78405f", "#c84678", "#fff5f8", "#4a2c3a",
           "#fae8ee",
           ["#ff96be", "#f078aa", "#be6ee6", "#8282ff"], "#1c1020"),
        _t("Nord", "#88c0d0", "#b48ead", "#a3be8c", "#2e3440", "#d8dee9",
           "#242933",
           ["#88c0d0", "#81a1c1", "#5e81ac", "#b48ead"], "#1b2029"),
        _t("Mocha", "#cba6f7", "#f5c2e7", "#94e2d5", "#1e1e2e", "#cdd6f4",
           "#181825",
           ["#94e2d5", "#89b4fa", "#cba6f7", "#f5c2e7"], "#11111b"),
        _t("Gruvbox", "#fabd2f", "#fe8019", "#b8bb26", "#32302f", "#ebdbb2",
           "#282828",
           ["#b8bb26", "#fabd2f", "#fe8019", "#fb4934"], "#1d2021"),
    ]
    return {t.name: t for t in themes}


def _load_user_themes(base):
    """JSON-файлы из themes/ → {имя: Theme}. Битые файлы пропускаются."""
    found = {}
    if not THEMES_DIR.is_dir():
        return found
    for path in sorted(THEMES_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
            name = str(d.get("name") or path.stem)
            found[name] = Theme(
                name,
                d.get("primary", base.primary),
                d.get("secondary", base.secondary),
                d.get("tertiary", base.tertiary),
                d.get("surface", base.surface),
                d.get("on_surface", base.on_surface),
                d.get("canvas", base.canvas),
                d.get("ramp", base.ramp_colors),
                d.get("viz_bg", base.viz_bg),
                dark=d.get("dark"),
            )
        except Exception:
            continue
    return found


class ThemeManager(QObject):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.themes = {}
        self.current = None
        self.reload()
        self.current = self.themes[DEFAULT_THEME]

    def reload(self):
        """Перечитывает встроенные и пользовательские темы."""
        builtin = _builtin()
        themes = dict(builtin)
        themes.update(_load_user_themes(builtin[DEFAULT_THEME]))
        self.themes = themes
        if self.current is not None:
            self.current = themes.get(self.current.name, themes[DEFAULT_THEME])

    def names(self):
        return list(self.themes)

    def set(self, name):
        th = self.themes.get(name)
        if th is None or th is self.current:
            return
        self.current = th
        self.changed.emit()


manager = ThemeManager()
