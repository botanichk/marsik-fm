# 📻 Marsik FM

Графическое интернет-радио для Linux (Void/Hyprland и другие) с визуализаторами
на реальном звуке и плеером локальной музыки. PySide6 + внешний mpv.

Репозиторий: <https://github.com/botanichk/marsik-fm>

## Установка на новом компьютере

Собирать нечего: нужен `python3` и пакеты. Пять шагов, порядок важен.

### 1. Пакеты

| Что | Зачем | Void | Arch | Debian/Ubuntu |
|-----|-------|------|------|---------------|
| PySide6 | интерфейс | `python3-pyside6` | `pyside6` | `python3-pyside6.qtgui python3-pyside6.qtwidgets` |
| mpv | звук (внешний плеер) | `mpv` | `mpv` | `mpv` |
| yt-dlp | кнопка «Сохранить» | `yt-dlp` | `yt-dlp` | `yt-dlp` |
| mutagen | длительности треков | `python3-mutagen` | `python-mutagen` | `python3-mutagen` |
| ffprobe | длительности, запасной путь | `ffmpeg6` | `ffmpeg` | `ffmpeg` |
| pactl | перехват звука для визуализаторов | `pulseaudio-utils` | `libpulse` | `pulseaudio-utils` |
| PyGObject + GStreamer | сами визуализаторы | `python3-gobject gst-plugins-good1` | `python-gobject gst-plugins-good` | `python3-gi gstreamer1.0-plugins-good` |

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

Без GStreamer/PyGObject программа работает, только визуализаторы стоят пустые.

### 2. Код

```bash
git clone git@github.com:botanichk/marsik-fm.git ~/radiofm
```

(если SSH-ключа на машине нет — `git clone https://github.com/botanichk/marsik-fm.git ~/radiofm`)

Папку держи именно в `~/radiofm`: на этот путь смотрит иконка из шага 4.

### 3. Запуск из терминала

```bash
python3 ~/radiofm/main.py
```

Если PySide6 в дистрибутиве нет или он старый, поднимаем venv:

```bash
cd ~/radiofm
python3 -m venv .venv && .venv/bin/pip install PySide6
.venv/bin/python main.py          # и в .desktop ниже замени python3 на .venv/bin/python
```

### 4. Иконка в меню приложений

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

Появится в меню/лаунчере как «Marsik FM» с иконкой из репо (иконку отдельно
никуда класть не надо). `$HOME` подставляется при создании файла, так что на
каждой машине команда одна и та же.

### 5. Что докладывается руками

В репозитории уже есть станции (17), 24 темы и иконка. Не в репо только тяжёлое
и личное:

- `backgrounds/` — фоны окна (png/jpg/webp, до 22 МБ) — скопировать с флешки,
  если нужны те же картинки;
- шрифт часов `Bitcount Single Cursive` — необязательный, без него время
  рисуется системным шрифтом;
- качанные треки лежат в XDG-папке «Музыка» (`~/Музыка` или `~/Music`), свои
  файлы туда можно просто класть;
- настройки (громкость, тема, фон, станция, размер окна) — свои на каждой
  машине, `~/.config/radiofm/radiofm.conf`.

### 6. Телефон (Android) — те же станции, без apk

<https://botanichk.github.io/marsik-fm/mobile/>

Открыть в Chrome → меню → **«Установить приложение»** (или «Добавить на главный
экран»): появится иконка, запускается без адресной строки. Список читается из
`stations.json` этого репозитория, поэтому станции, добавленные на компьютере,
появляются на телефоне после `git push`.

Чего в браузере нет: визуализаторов, скачивания и трёх станций с http-потоком
без TLS (Radio Caprice, XRDS.fm, Radio IDL) — они помечаются как неиграющие.

### Проверка после установки

```bash
python3 ~/radiofm/smoke_test.py
```

Гоняет окно и mpv, играет тестовый поток (`ao=null`, без звука) — для этого
нужна сеть, без неё часть проверок упадёт. Проверяет станции, сборку
интерфейса, часы и пилюли, перетаскивание станций, паузу/стоп, плейлист
«Скачанные», длительности, разбор процентов yt-dlp, визуализаторы, аудио-тап и
настройки. В конце печатает `ИТОГ: все проверки пройдены` или список падений.

## Как пользоваться

Шапка — пять пилюль-«островов», каждая раскрывает список:

- **пилюля станции** — список радиостанций, добавление и удаление;
  станции перетаскиваются мышью за строку, новый порядок сразу пишется
  в `stations.json`;
- **«Скачанные»** — плеер локальной музыки (см. ниже);
- **режим визуализатора** — Glowing Wave, Ring, Bars, Spectrum, Fireflies,
  Liquid, Galaxy, Warp, Oscilloscope;
- **фон** — картинки из папки `backgrounds/`;
- **тема** — встроенные и свои темы из `themes/`.

Справа в шапке — часы. Шрифт как у виджета часов Noctalia, но плотнее
(`Bitcount Single Cursive SemiBold`, константа `CLOCK_FONT` в `radio/ui.py`);
если шрифта нет — системный.

Панель плеера снизу: ←/→, пауза/продолжить (при подключении — отмена), стоп,
громкость и «Сохранить» (скачать текущий трек через yt-dlp).

Для локальных файлов над панелью появляется полоса с временем: слева сколько
прошло, справа длительность, полосу можно тянуть — перемотка. У радио полосы
нет: у живого потока не бывает длительности.

Скачивание показывает отдельная тонкая полоса (появляется над панелью и гаснет
после завершения): проценты приходят из вывода yt-dlp. Повторный клик по
«Сохранить» отменяет загрузку. Скачанное падает в XDG-папку «Музыка».

## Скачанные: папка «Музыка» как плейлист

Кликом по файлу в пилюле «Скачанные» запускается **вся папка** XDG «Музыка»
(`~/Музыка`), начиная с выбранного трека. Дальше mpv сам переходит к
следующему — ничего нажимать не нужно.

Порядок задаётся двумя пунктами в начале меню:

- **Играть все по порядку** — файлы в порядке списка (новые сверху), по кругу;
- **Играть вперемешку** — очередь перемешивается, выбранный трек играет первым.

Пока играет локальная музыка, в панели плеера появляется кнопка **Вперемешку**
— можно переключить порядок на ходу. Выбор запоминается между запусками.
Кнопки ←/→ в панели в это время листают треки очереди, а не станции (подсказки
на кнопках это подтверждают).

Свои файлы можно просто класть в `~/Музыка` — они появятся в списке сами
(поддерживаются mp3, ogg, flac, m4a). Рядом с именем каждого трека
показывается его длительность (считается в фоне через mutagen/ffprobe).

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
`assets/icon.png` (если его нет — `backgrounds/logo.png`); без картинки
интерфейс работает, просто без логотипа.

## Настройки

`~/.config/radiofm/radiofm.conf` — последняя станция, громкость, размер окна,
режим визуализатора, фон, тема, порядок очереди.

## Самопроверка

```bash
python3 smoke_test.py
```

Проверяет список станций, сборку окна, часы и пилюли (включая обрезку длинных
имён), перетаскивание станций, подъём mpv и воспроизведение потока без звука
(`ao=null`), паузу/стоп, отсутствие фоновых процессов mpv, плейлист «Скачанные»
(автопереход, ←/→, конец очереди, вперемешку), длительности треков, разбор
процентов yt-dlp, рендер визуализаторов, аудио-тап и запись настроек. Рисует
`preview.png`.

## Структура

```
main.py               точка входа
radio/engine.py       AudioEngine: mpv + JSON IPC (поток и файл)
radio/playlist.py     PlayQueue (порядок/вперемешку) и DurationProbe
radio/ui.py           окно Qt: пилюли, часы, визуализатор, панель плеера
radio/island.py       IslandMenu: выпадающий список-«остров», drag&drop строк
radio/theme.py        темы: роли цветов, встроенные и пользовательские
radio/stations.py     работа со станциями (stations.json)
radio/tap.py          AudioTap: пассивный перехват звука (monitor-порт sink'а)
radio/tracks.py       длительности локальных треков (mutagen, кэш)
radio/viz/            базовый класс + 9 режимов визуализации
stations.json         список станций (17)
themes/               темы (встроенные в коде + 24 JSON из Noctalia)
assets/               иконка окна, эмблема, вордмарк
backgrounds/          фоны окна и логотип (в репо нет — положить руками)
tools/                import_noctalia_themes.py — генератор themes/noctalia-*
mobile/               те же станции для телефона (PWA: index.html + manifest)
smoke_test.py         самопроверка
```

Визуализаторы реагируют на реальный звук: тап читает monitor-порт default sink
через GStreamer (256 полос FFT, наружу — 32 бина, ~17 раз в секунду) и срезы
PCM для осциллографа. Общая AGC-логика живёт в базовом классе, поэтому все
режимы дышат от одной энергии.

Ограничения: нет автопереподключения при обрыве радио (нужно нажать ▶);
«вперемешку» перемешивает порядок заново на каждом круге.

## Удаление

```bash
rm -rf ~/radiofm ~/.config/radiofm
rm -f ~/.local/share/applications/marsikfm.desktop
```

Система не изменяется: пакеты не ставились, конфиги рабочего стола не трогались
(кроме своего `.desktop` в `~/.local/share/applications`).
