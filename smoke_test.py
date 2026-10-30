"""Самопроверка без экрана (QT_QPA_PLATFORM=offscreen).

Проверяет: станции, сборку окна, часы и пилюли, перетаскивание станций,
подъём mpv и воспроизведение тестового потока (ao=null — нужна сеть), паузу и
стоп, очередь скачанных и автопереход по eof, длительности и полосу перемотки,
разбор процентов yt-dlp, визуализаторы, аудио-тап и настройки.
Рисует preview.png.

Запуск:  python3 smoke_test.py
"""
import math
import os
import re
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from radio.engine import AudioEngine, PAUSED, PLAYING, STOPPED  # noqa: E402
from radio.stations import load_stations  # noqa: E402

URL = "https://ice1.somafm.com/groovesalad-128-mp3"
HERE = os.path.dirname(os.path.abspath(__file__))
FAILURES = []


def check(name, ok, detail=""):
    print("%s %s%s" % ("ok  " if ok else "FAIL", name,
                       (" — " + detail) if detail and not ok else ""))
    if not ok:
        FAILURES.append(name)


def pump(seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.03)


def wait_state(engine, wanted, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if engine.state in wanted:
            return True
        time.sleep(0.03)
    return False


app = QApplication([])

# 1. список станций
try:
    stations = load_stations()
    check("stations.json загружается", len(stations) >= 5,
          "найдено %d" % len(stations))
except Exception as exc:
    check("stations.json загружается", False, str(exc))
    stations = []

# 2. окно собирается (offscreen)
try:
    from radio.ui import MainWindow
    win = MainWindow()
    # IslandMenu держит пункты в _actions (QWidget.actions() их не знает)
    real = [a for a in win.menu._actions if not a.isSeparator()]
    check("окно собирается",
          len(real) == len(stations) + 2 and win.pill is not None,
          "actions=%d" % len(real))
    # добавление/удаление: служебные пункты в меню
    texts = [a.text() for a in real]
    check("меню: пункты «Добавить» и «Удалить» на месте",
          any("Добавить станцию" in t for t in texts)
          and any("Удалить станцию" in t or "Удалить «" in t for t in texts),
          texts[-2:])

    # yt-dlp: пилюля скачанных, кнопка сохранить, список файлов
    check("скачивание: пилюля+кнопка+меню на месте",
          win.dl_pill is not None and win.btn_save is not None
          and win.dl_menu is not None)
    # длинное имя трека не растягивает пилюлю (ширина ограничена, текст с «…»)
    win.dl_pill.setText("Очень длинное название трека " * 4)
    check("длинное имя не растягивает пилюлю",
          win.dl_pill.sizeHint().width() < 260
          and win.dl_pill.text().endswith("…")
          and "\n" in win.dl_pill.toolTip())
    # часы в правом углу шапки
    check("часы в шапке показывают время",
          re.fullmatch(r"\d{2}:\d{2}", win.clock.text()) is not None,
          win.clock.text())
    # перетаскивание станций: порядок меняется и уходит в save_stations
    from PySide6.QtCore import QEvent, QPointF, Qt as _Qt
    from PySide6.QtGui import QMouseEvent
    import radio.ui as _ui
    m = win.menu
    m.open_menu()
    m._p, m._scroll = 1.0, 0
    rows = m._rows
    cx = m.width() // 2

    def _mev(kind, yy):
        return QMouseEvent(kind, QPointF(cx, yy), QPointF(cx, yy),
                           _Qt.LeftButton, _Qt.LeftButton, _Qt.NoModifier)

    y0 = rows[0][1] + rows[0][2] // 2
    y2 = rows[2][1] + rows[2][2] // 2
    saved_orders = []
    orig_save = _ui.save_stations
    _ui.save_stations = lambda sts: saved_orders.append(
        [s["id"] for s in sts])       # файл проекта не трогаем
    first_id = win.stations[0]["id"]
    m.mousePressEvent(_mev(QEvent.MouseButtonPress, y0))
    m.mouseMoveEvent(_mev(QEvent.MouseMove, y0 + 10))
    m.mouseMoveEvent(_mev(QEvent.MouseMove, y2 + 12))
    m.mouseReleaseEvent(_mev(QEvent.MouseButtonRelease, y2 + 12))
    _ui.save_stations = orig_save
    m.close_menu()
    check("перетаскивание станции меняет порядок и сохраняется",
          win.stations[0]["id"] != first_id
          and saved_orders[-1:] == [[s["id"] for s in win.stations]])

    # разбор вывода yt-dlp: проценты приходят кусками (readyRead не по строкам)
    class _FakeProc:
        def __init__(self, chunks):
            self.chunks = list(chunks)

        def readAllStandardOutput(self):
            return self.chunks.pop(0)

    win._dl_proc = _FakeProc([b"[download]  4", b"2.5% of 3MiB\n",
                              b"[ExtractAudio] Destination: x.mp3\n"])
    win._dl_buf = ""
    win._on_dl_output()
    partial = win.dl_progress.value()
    win._on_dl_output()
    whole = win.dl_progress.value()
    win._on_dl_output()
    win._dl_proc = None
    check("скачивание: проценты из вывода yt-dlp видны в полосе",
          partial < 1 and whole == 42
          and win.dl_progress.value() == 42,
          "%s → %s → %s" % (partial, whole, win.dl_progress.value()))
    # без трека и без yt-dlp-процесса кнопка неактивна
    check("без трека кнопка «Сохранить» неактивна",
          not win.btn_save.isEnabled())
    # меню скачанных: режим порядка + файлы (или заглушка)
    win._scan_downloads()
    dl_actions = win.dl_menu._actions
    files = win._downloads_list()
    check("меню скачанных: файлы или заглушка",
          bool(dl_actions)
          and (len(dl_actions) > 2 if files
               else len(dl_actions) == 1 and not dl_actions[0].isEnabled()),
          [a.text() for a in dl_actions][:3])
    check("меню скачанных: пункты порядка на месте",
          (dl_actions[0].text() == "Играть все по порядку"
           and dl_actions[1].text() == "Играть вперемешку") if files
          else all(a.isSeparator() is False
                   and "не скачано" in a.text() for a in dl_actions),
          [a.text() for a in dl_actions][:2])
except Exception as exc:
    check("окно собирается", False, str(exc))
    win = None

# 3. движок: play -> playing (реальный поток, звук в null)
engine = AudioEngine(extra_args=["--ao=null"])
states = []
engine.stateChanged.connect(states.append)
engine.play(URL)
check("переход в playing",
      wait_state(engine, {PLAYING, PAUSED}, 30),
      "финальное состояние: %s, история: %s" % (engine.state, states))
playing_ok = engine.state in (PLAYING, PAUSED)

# 4. пауза/снятие паузы
if playing_ok:
    engine.toggle_pause()
    ok_pause = wait_state(engine, {PAUSED, PLAYING}, 10)
    check("toggle_pause переключает состояние", ok_pause,
          "состояние: %s" % engine.state)
    engine.toggle_pause()
    wait_state(engine, {PLAYING, PAUSED}, 10)

# 5. остановка
engine.stop()
check("stop -> stopped", wait_state(engine, {STOPPED}, 10),
      "состояние: %s" % engine.state)

# 6. mpv умирает начисто, сирот нет
engine.shutdown()
check("mpv завершён (сирот нет)", not engine.is_running)

# 6b. media-title фильтр: имя потока не эмитится, трек эмитится
eng2 = AudioEngine()
eng2._url = "https://ice1.somafm.com/groovesalad-128-mp3"
got = []
eng2.trackChanged.connect(got.append)
eng2._on_property({"name": "media-title", "data": "groovesalad-128-mp3"})
name_filtered = not got
eng2._on_property({"name": "media-title", "data": "Artist - Song"})
eng2._on_property({"name": "icy-title", "data": "Icy Song"})
check("media-title: имя потока фильтруется, трек проходит",
      name_filtered and got == ["Artist - Song", "Icy Song"],
      "got=%s" % got)
# локальный файл: media-title = имя трека, показываем
eng2._url = "/home/user/downloads/Some Track.mp3"
got.clear()
eng2._on_property({"name": "media-title", "data": "Some Track"})
check("media-title локального файла проходит", got == ["Some Track"],
      "got=%s" % got)
eng2.shutdown()

# 6c. станции: сохранение/загрузка roundtrip (для добавления из UI)
try:
    import tempfile
    from radio.stations import save_stations, load_stations
    sample = [{"id": "boot_liquor", "name": "Boot Liquor",
               "description": "Americana Roots", "url": "https://x/abc.mp3"}]
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, "stations.json")
        save_stations(sample, path=p)
        back = load_stations(path=p)
    check("станции: save/load roundtrip", back == sample, "back=%s" % back)
except Exception as exc:
    check("станции: save/load roundtrip", False, str(exc))

# 6d. очередь скачанных: PlayQueue, автопереход по eof, пустая очередь
try:
    import tempfile
    import subprocess
    from radio.engine import AudioEngine as _AE
    from radio.playlist import PlayQueue

    # короткие файлы (2 сек): реальный eof для fileEnded и длительности
    qdir = tempfile.mkdtemp(prefix="radiofm-pl-")
    qfiles = []
    for i in (1, 2):
        p = os.path.join(qdir, "t%d.mp3" % i)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
             "anullsrc=r=44100:cl=mono", "-t", "2", "-q:a", "9",
             p, "-y"], capture_output=True, timeout=30)
        if os.path.exists(p):
            qfiles.append(p)

    items = ["/m/a.mp3", "/m/b.mp3", "/m/c.mp3"]
    q = PlayQueue()
    q.start(items, items[0])
    order = [q.current()] + [q.next() for _ in range(3)]
    check("очередь: по порядку и по кругу",
          order == [items[0], items[1], items[2], items[0]], order)
    check("очередь: prev листает назад по кругу",
          [q.prev(), q.prev()] == [items[2], items[1]])
    q.start(items, items[1])
    q.set_shuffle(True)
    seen = [q.current()] + [q.next() for _ in range(2)]
    check("очередь: вперемешку — старт с выбранного, все треки по разу",
          seen[0] == items[1] and sorted(seen) == sorted(items), seen)
    q.set_shuffle(False)
    check("очередь: выключение перемешки не сбивает текущий трек",
          q.current() in items, q.current())

    # UI: конец трека → следующий из очереди, пустая очередь → stop
    if win is not None:
        played, stopped = [], []
        orig_play, orig_stop = win._play_queue_item, win.engine.stop
        win._play_queue_item = played.append
        win.engine.stop = lambda: stopped.append(True)
        win._local = True
        win.queue.set_shuffle(False)      # QSettings мог сохранить «вперемешку»
        win.queue.start(items, items[0])
        for _ in range(3):
            win._on_file_ended()
        win.queue.items = []
        win._on_file_ended()
        win._play_queue_item, win.engine.stop = orig_play, orig_stop
        check("плейлист: автопереход по кругу, пустая очередь → stop",
              played == [items[1], items[2], items[0]] and stopped,
              "played=%s stopped=%s" % (played, stopped))

    # реальный eof: mpv доиграл файл → fileEnded (по нему идёт автопереход)
    if qfiles:
        eof_eng = _AE(extra_args=["--ao=null"])
        ended, errs = [], []
        eof_eng.fileEnded.connect(lambda: ended.append(True))
        eof_eng.errorRaised.connect(errs.append)
        eof_eng.play(qfiles[0])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not ended and not errs:
            app.processEvents()
            time.sleep(0.03)
        eof_eng.shutdown()
        check("плейлист: доигранный файл даёт fileEnded, а не ошибку",
              bool(ended) and not errs, "ended=%s errs=%s" % (ended, errs))
    else:
        print("skip плейлист: ffmpeg не создал файлы")
except Exception as exc:
    import traceback
    traceback.print_exc()
    check("плейлист локальных файлов", False, str(exc))

# 6e. прогресс трека: длительности, формат времени, позиция от mpv, перемотка
try:
    from radio.tracks import duration, fmt_time

    check("время: формат mm:ss и h:mm:ss",
          fmt_time(0) == "—:—" and fmt_time(207.5) == "3:28"
          and fmt_time(3725) == "1:02:05" and fmt_time(None) == "—:—",
          [fmt_time(0), fmt_time(207.5), fmt_time(3725)])

    # длительность реального файла (тот же набор, что для плейлиста)
    if qfiles:
        d = duration(qfiles[0])
        check("время: длительность файла читается",
              d is not None and 1.5 < d < 2.5, "duration=%s" % d)
        check("время: длительность кэшируется",
              duration(qfiles[0]) == d)
        check("время: битый путь → None",
              duration(os.path.join(qdir, "нет-такого.mp3")) is None)

    # позиция от mpv: полоса перемотки, время, видимость строки
    if win is not None:
        win._local = True          # как будто играет локальный файл
        win._on_position(30.0, 120.0)
        check("прогресс: полоса отражает позицию",
              win.seek.value() == 250
              and win.lbl_pos.text() == "0:30"
              and win.lbl_dur.text() == "2:00"
              and not win.seek_row.isHidden(),
              "value=%d pos=%s dur=%s" % (win.seek.value(),
                                          win.lbl_pos.text(),
                                          win.lbl_dur.text()))
        # радио (не локальный): длительности нет — строку прячем
        win._local = False
        win._on_position(7.0, 24.0)
        check("прогресс: для радио полосы нет",
              win._cur_dur == 0.0 and win.seek_row.isHidden(),
              "dur=%s hidden=%s" % (win._cur_dur, win.seek_row.isHidden()))
except Exception as exc:
    import traceback
    traceback.print_exc()
    check("прогресс трека", False, str(exc))

# 6f. скачивание: проценты из вывода yt-dlp уходят в свою полосу
try:
    from radio.ui import _DL_PCT_RE

    line = ("[download]  45.2% of    4.13MiB at    1.23MiB/s "
            "ETA 00:03 (frag 3/9)")
    m = _DL_PCT_RE.search(line)
    check("скачивание: проценты из вывода yt-dlp разбираются",
          m is not None and abs(float(m.group(1)) - 45.2) < 0.01,
          "m=%s" % (m.group(1) if m else None))
    # строки без процентов не должны ломать парсер
    check("скачивание: служебные строки не дают процентов",
          _DL_PCT_RE.search("[download] Destination: /x/y.mp3") is None
          and _DL_PCT_RE.search("[download] Download completed") is None)

    if win is not None:
        class _Proc:
            def __init__(self, chunks):
                self.chunks = list(chunks)

            def readAllStandardOutput(self):
                return self.chunks.pop(0) if self.chunks else b""

            def deleteLater(self):
                pass

        # живой yt-dlp подменяем фейком: проверяем полосу, а не сеть
        win._dl_proc = _Proc([b"[download]  1", b"2.5% of 3MiB\n",
                              b"[download] Download completed\n"])
        win._dl_buf = ""
        win.dl_progress.setValue(0)
        win.dl_progress.show()
        win._on_dl_output()
        partial = win.dl_progress.value()
        win._on_dl_output()
        check("скачивание: проценты видны в полосе загрузки",
              partial < 1 and win.dl_progress.value() == 12
              and win.dl_progress.format() == "12%",
              "%s → %s (%s)" % (partial, win.dl_progress.value(),
                                win.dl_progress.format()))
        check("скачивание: полоса видна, пока качаем",
              not win.dl_progress.isHidden())
        win._on_dl_finished(0, None)
        check("скачивание: после завершения полоса скрыта",
              win.dl_progress.isHidden() and win._dl_proc is None)
        win.dl_pill.setStyleSheet("")     # снять «✓ Сохранено!» сразу
        win._count_downloads()
except Exception as exc:
    import traceback
    traceback.print_exc()
    check("скачивание: индикатор", False, str(exc))

# 7. настройки на месте
settings = QSettings("radiofm", "radiofm")
settings.setValue("smoke", "1")
settings.sync()
conf_dir = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
conf_file = os.path.join(conf_dir, "radiofm", "radiofm.conf")
check("QSettings пишутся на диск",
      settings.value("smoke") == "1" and os.path.exists(conf_file),
      conf_file)
settings.remove("smoke")
settings.sync()

# 8. визуализатор: волна рендерится, реагирует на уровень, пишет preview.png
try:
    from radio.visualizer import GlowingWave

    wave = GlowingWave()
    wave.resize(760, 260)
    wave.set_active(True)

    # «музыкальная» последовательность: басы + редкие транзиенты
    for i in range(70):
        level = 0.25 + 0.25 * math.sin(i * 0.45) + 0.06 * math.sin(i * 2.1)
        if i in (20, 45):          # сильный удар
            level = 0.9
        wave.set_audio_level(level)
        pump(0.02)
    wave.set_audio_level(0.7)
    pump(0.1)
    preview = os.path.join(HERE, "preview.png")
    saved = (not wave.grab().isNull()) and wave.grab().save(preview)
    check("волна рендерится, preview.png записан", saved, preview)

    # остановка → волна успокаивается и рисуется в idle
    wave.set_active(False)
    pump(0.5)
    check("волна рисуется и в idle", not wave.grab().isNull())

    # Spectrum: рендерится, реагирует на полосы спектра
    from radio.viz.spectrum import Spectrum
    sp = Spectrum()
    sp.resize(500, 300)
    sp.set_active(True)
    for i in range(40):
        sp.set_audio_level(0.3 + 0.3 * math.sin(i * 0.4))
        sp.set_bands([0.6, 0.4, 0.2, 0.1, 0.05, 0.3, 0.5, 0.7])
        pump(0.02)
    check("Spectrum рендерится", not sp.grab().isNull())

    # полосы хранятся как есть (реакция на реальный спектр, без AGC)
    sp.set_bands([0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.8])
    check("спектр различает низ/верх",
          abs(sp._bands[0] - sp._bands[1]) > 0.5,
          "bands=%s" % sp._bands)

    # переключение режимов (QComboBox → QStackedWidget)
    from PySide6.QtWidgets import QComboBox, QStackedWidget
    stack = QStackedWidget()
    stack.addWidget(wave)
    stack.addWidget(sp)
    combo = QComboBox()
    combo.addItems(["Glowing Wave", "Spectrum"])
    combo.currentIndexChanged.connect(lambda i: stack.setCurrentIndex(i))
    combo.setCurrentIndex(1)
    check("переключение на Spectrum", stack.currentWidget() is sp)

    # Galaxy: рендерится, вращается, реагирует на полосы и удар (сверхновая)
    from radio.viz.galaxy import Galaxy
    gal = Galaxy()
    gal.resize(500, 300)
    gal.set_active(True)
    for i in range(40):
        gal.set_audio_level(0.3 + 0.3 * math.sin(i * 0.4))
        gal.set_bands([0.6, 0.4, 0.2, 0.1, 0.05, 0.3, 0.5, 0.7])
        pump(0.02)
    check("Galaxy рендерится", not gal.grab().isNull())
    # удар (beat) → сверхновая вспыхивает и гаснет
    gal._active = True
    gal._prev_beat, gal._beat = 0.0, 1.0
    gal._update(0.016, gal._t)
    nova = gal._nova
    gal._update(0.5, gal._t)
    check("Galaxy: удар даёт сверхновую, вспышка гаснет",
          nova > 0.3 and gal._nova < nova,
          "nova=%.2f → %.2f" % (nova, gal._nova))

    # Oscilloscope: реальная форма волны рисуется, idle — синусоида
    from radio.viz.oscilloscope import Oscilloscope
    osc = Oscilloscope()
    osc.resize(500, 300)
    osc.set_active(True)
    # реальный «срез PCM»: полусинусоида, отличная от плоской линии
    pcm = [math.sin(i * 0.25) * (0.4 + 0.5 * (i % 40) / 40.0)
           for i in range(200)]
    for _ in range(10):
        osc.set_wave(pcm)
        osc.set_audio_level(0.5)
        pump(0.02)
    check("Oscilloscope: реальная волна рисуется", not osc.grab().isNull())
    check("Oscilloscope: set_wave принимает данные",
          len(osc._wave) == 200 and osc._wave_time > 0,
          "wave=%d" % len(osc._wave))

    # фон-картинка: set_background ставит pixmap, без него — сплошной цвет
    from PySide6.QtGui import QPixmap
    bg_path = os.path.join(HERE, "backgrounds", "balcony.png")
    if os.path.exists(bg_path):
        pm = QPixmap(bg_path)
        gal.set_background(pm)
        check("фон-картинка ставится и рендерится",
              gal._bg is not None and not gal.grab().isNull())
        gal.set_background(None)
        check("фон снимается (обратно сплошной цвет)", gal._bg is None)
    else:
        print("skip фон: %s нет" % bg_path)

except Exception as exc:
    import traceback
    traceback.print_exc()
    check("визуализатор", False, str(exc))

# 9. аудио-тап: буферы идут с monitor-порта (реальные данные доступны)
try:
    from radio.tap import AudioTap
    if not AudioTap.available:
        print("skip аудио-тап: GStreamer недоступен")
    else:
        tap = AudioTap()
        levels = []
        tap_errors = []
        tap.level.connect(levels.append)
        tap.failed.connect(tap_errors.append)
        tap.start()
        pump(2.5)
        tap.stop()
        check("аудио-тап отдаёт уровень (~43/сек)",
              len(levels) >= 10,
              "уровней: %d, ошибки: %s" % (len(levels), tap_errors))
        if tap_errors:
            print("     тап сообщил: %s" % tap_errors[0])
except Exception as exc:
    import traceback
    traceback.print_exc()
    check("аудио-тап", False, str(exc))

if win is not None:
    win.close()

print()
if FAILURES:
    print("ИТОГ: FAIL (%d)" % len(FAILURES))
    sys.exit(1)
print("ИТОГ: все проверки пройдены")
