# 📻 Marsik FM

Графическое интернет-радио для Linux (Void/Hyprland и другие) с визуализаторами
на реальном звуке и плеером локальной музыки. PySide6 + внешний mpv.

## Запуск

```bash
cd ~/radiofm
python3 main.py
```

Сборка не требуется. Проверить: `python3 -c "import PySide6"`, `mpv --version`,
`which yt-dlp`.

### Иконка в меню приложений

```bash
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/marsikfm.desktop <<EOF
[Desktop Entry]
Type=Application
Name=Marsik FM
Comment=Интернет-радио с визуализаторами
Exec=python3 $HOME/radiofm/main.py
Path=$HOME/radiofm
Icon=$HOME/radiofm/assets/icon.png
Terminal=false
Categories=AudioVideo;Audio;Player;
Keywords=radio;радио;music;музыка;
StartupWMClass=radiofm
EOF
update-desktop-database ~/.local/share/applications 2>/dev/null || true
```

Появится в меню/лаунчере как «Marsik FM» (иконка — `assets/icon.png` из репо).
`$HOME` подставляет твой домашний каталог при создании файла, поэтому имя
пользователя нигде не хардкодится: на другом компьютере команду просто
повторяешь. Папку проекта держи в `~/radiofm` — иначе поправь пути в `Exec`,
`Path` и `Icon`.

## Установка на другом компьютере

Нужны python3 и пакеты (имена по дистрибутивам):

| Что | Зачем | Void | Arch | Debian/Ubuntu |
|-----|-------|------|------|---------------|
| PySide6 | интерфейс | `python3-pyside6` | `pyside6` | `python3-pyside6.qtgui python3-pyside6.qtwidgets` |
| mpv | звук (внешний плеер) | `mpv` | `mpv` | `mpv` |
| yt-dlp | «Сохранить» | `yt-dlp` | `yt-dlp` | `yt-dlp` |
| mutagen | длительности быстрее | `python3-mutagen` | `python-mutagen` | `python3-mutagen` |
| ffprobe | длительности (запасной путь) | `ffmpeg6` | `ffmpeg` | `ffmpeg` |
| pactl | перехват звука | `pulseaudio-utils` | `libpulse` | `pulseaudio-utils` |
| PyGObject + GStreamer | визуализаторы | `python3-gobject gst-plugins-good1` | `python-gobject gst-plugins-good` | `python3-gi gstreamer1.0-plugins-good` |

```bash
# Void
sudo xbps-install -S python3-pyside6 mpv yt-dlp python3-mutagen ffmpeg6 \
                     pulseaudio-utils python3-gobject gst-plugins-good1
# Arch
sudo pacman -S --needed pyside6 mpv yt-dlp python-mutagen ffmpeg libpulse \
                        python-gobject gst-plugins-good
# Debian/Ubuntu
sudo apt install python3-pyside6.qtgui python3-pyside6.qtwidgets mpv yt-dlp \
                 python3-mutagen ffmpeg pulseaudio-utils python3-gi \
                 gstreamer1.0-plugins-good
```

Дальше — `python3 main.py` в папке проекта. Если PySide6 в дистрибутиве нет
или он старый:

```bash
python3 -m venv .venv && .venv/bin/pip install PySide6
.venv/bin/python main.py
```

С собой (или в репозиторий) нужно взять данные, которые не в коде:
`stations.json` — станции; `themes/*.json` — свои темы; `backgrounds/` — фоны;
`assets/icon.png` — иконка окна. Без них программа запустится, но со встроенными
темами, пустым списком фонов и иконкой по умолчанию. Настройки (громкость,
тема, фон, станция) — в `~/.config/radiofm/radiofm.conf`, качанные треки — в
XDG-папке «Музыка» (`~/Музыка` или `~/Music`).

Шрифт часов `Bitcount Single Cursive` — необязательный: без него время
рисуется системным шрифтом.

Визуализаторы без GStreamer/PyGObject просто не получают данных (тишина в
волне), остальное работает.

## Как пользоваться

Шапка — пять пилюль-«островов», каждая раскрывает список:

- **пилюля станции** — список радиостанций, добавление и удаление;
  станции перетаскиваются мышью за строку, новый порядок сразу пишется
  в `stations.json`;
- **«Скачанные»** — плеер локальной музыки (см. ниже);
- **режим визуализатора** — Glowing Wave, Nebulous, Galaxy, Oscilloscope, Aurora;
- **фон** — картинки из папки `backgrounds/`;
- **тема** — встроенные и свои темы из `themes/`.

Справа в шапке — часы. Шрифт тот же, что у виджета часов в Noctalia
(`Bitcount Single Cursive ExtraLight`, задаётся константой `CLOCK_FONT`
в `radio/ui.py`).

Панель плеера снизу: ←/→, пауза/продолжить (при подключении — отмена), стоп,
громкость и «Сохранить» (скачать текущий трек через yt-dlp).

Над панелью — полоса прогресса трека со временем: слева сколько прошло,
справа длительность. Полосу можно тянуть — перемотка внутри трека. Для радио
полоса пустая: у живого потока нет длительности, и mpv отдаёт только размер
буфера, а не длину эфира.

Пока идёт скачивание, эта же полоса показывает загрузку: слева «Скачивание»
и оставшееся время, справа проценты. После 100% — «Обработка…» (yt-dlp ещё
конвертирует в mp3), затем полоса возвращается к воспроизведению. Повторный
клик по «Сохранить» отменяет загрузку.

## Скачанные: папка «Музыка» как плейлист

Кликом по файлу в пилюле «Скачанные» запускается **вся папка** XDG «Музыка»
(`~/Музыка`), начиная с выбранного трека. Дальше mpv сам переходит к
следующему — ничего нажимать не нужно.

Первый пункт меню переключает порядок:

- **По порядку** — файлы по алфавиту, очередь стартует с выбранного и идёт по
  кругу;
- **Вперемешку** — выбранный трек играет первым, остальные перемешиваются.

Выбор запоминается между запусками. Кнопки ←/→ в панели листают треки очереди,
а не станции, пока играет локальная музыка. Под панелью показывается позиция:
`Играет · 3 / 6 · вперемешку`.

Свои файлы можно просто класть в `~/Музыка` — они появятся в списке сами
(поддерживаются mp3, ogg, flac, m4a). Рядом с именем каждого трека
показывается его длительность.

## Станции

Список — `stations.json` в каталоге проекта. Формат:

```json
{ "id": "groovesalad", "name": "Groove Salad",
  "description": "...", "url": "https://ice1.somafm.com/groovesalad-128-mp3" }
```

Станции добавляются и удаляются прямо из меню пилюли; файл сохраняется
автоматически.

## Темы и фоны

Тема — набор ролей (акценты, поверхность, фон окна, градиент визуализатора).
Свои темы — JSON-файлы в `themes/`, пропущенные поля берутся из темы Marsik:

```json
{ "name": "Закат", "primary": "#e8743b", "secondary": "#5a2d4a",
  "tertiary": "#c8502c", "surface": "#fff4ea", "on_surface": "#3d2a26",
  "canvas": "#f6e3d3",
  "ramp": ["#ffb347", "#ff7e5f", "#c94b8a", "#6a4c93"], "viz_bg": "#1a1020" }
```

Фоны — png/jpg/webp/bmp в `backgrounds/` (кроме `logo*`). Логотип в шапке —
`backgrounds/logo.png`; без него интерфейс работает, просто без картинки.

## Настройки

`~/.config/radiofm/radiofm.conf` — последняя станция, громкость, размер окна,
режим визуализатора, фон, тема, порядок очереди.

## Самопроверка

```bash
python3 smoke_test.py
```

Проверяет список станций, сборку окна, воспроизведение потока без звука
(`ao=null`), паузу/стоп, отсутствие фоновых процессов mpv, плейлист локальных
файлов (автопереход, ←/→, конец очереди, вперемешку), полосу прогресса и
длительности треков, индикатор скачивания (проценты и ETA из вывода yt-dlp),
рендер всех пяти визуализаторов, аудио-тап и запись настроек. Рисует
`preview.png`.

## Структура

```
main.py            точка входа
radio/engine.py    AudioEngine: mpv + JSON IPC, поток и очередь файлов
radio/ui.py        окно Qt: пилюли, визуализатор, панель плеера
radio/island.py    IslandMenu: выпадающий список-«остров» из шапки
radio/theme.py     темы: роли цветов, встроенные и пользовательские
radio/stations.py  работа со станциями
radio/tap.py       AudioTap: пассивный перехват звука (monitor-порт sink'а)
radio/tracks.py    длительности локальных треков (mutagen, кэш) и формат времени
radio/viz/         базовый класс + 5 режимов визуализации
stations.json      список станций
themes/            пользовательские темы (JSON)
backgrounds/       фоны окна и логотип
smoke_test.py      самопроверка
```

Визуализаторы реагируют на реальный звук: тап читает monitor-порт default sink
через GStreamer, отдаёт 8 лог-полос спектра (~17 Гц) и срезы PCM. Общая
AGC-логика живёт в базовом классе, поэтому все режимы дышат от одной энергии.

Ограничения: нет автопереподключения при обрыве радио (нужно нажать ▶);
порядок «вперемешку» перемешивает очередь один раз при запуске, а не после
каждого круга.

## Удаление

```bash
rm -rf ~/radiofm ~/.config/radiofm
```

Система не изменяется: пакеты не ставились, конфиги рабочего стола не трогались.
