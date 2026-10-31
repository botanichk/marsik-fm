"""Добавляет режим «Fireflies Dots» в radio/ui.py (точечная правка, без перезаписи файла)."""
import sys
p = sys.argv[1] if len(sys.argv) > 1 else "radio/ui.py"
s = open(p, encoding="utf-8").read()
if "from .viz.dots import Dots" in s:
    print("уже добавлено"); sys.exit(0)
steps = [
    ("from .viz.fireflies import Fireflies\n",
     "from .viz.fireflies import Fireflies\nfrom .viz.dots import Dots\n"),
    ('"Fireflies",\n              "Liquid"',
     '"Fireflies",\n              "Fireflies Dots", "Liquid"'),
    ("Spectrum(),\n                          Fireflies(), Liquid(),",
     "Spectrum(),\n                          Fireflies(), Dots(), Liquid(),"),
]
for old, new in steps:
    if s.count(old) != 1:
        print("ui.py отличается от ожидаемого (не нашёл: %r) — файл не тронут, пришли его" % old[:40])
        sys.exit(1)
    s = s.replace(old, new)
open(p, "w", encoding="utf-8").write(s)
print("готово")
