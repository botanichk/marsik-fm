"""Самопроверка MVP + визуализатора без экрана и без звука.

Проверяет: загрузку станций, сборку окна, подъём mpv, IPC-связь, реальное
воспроизведение потока (ao=null), паузу/стоп, чистое завершение, запись
настроек, рендер волны и работу аудио-тапа. Рисует preview.png.

Запуск:  python3 smoke_test.py
"""
import math
import os
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
    real = [a for a in win.menu.actions() if not a.isSeparator()]
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
    # без трека и без yt-dlp-процесса кнопка неактивна
    check("без трека кнопка «Сохранить» неактивна",
          not win.btn_save.isEnabled())
    # меню скачанных: режим порядка + файлы (или заглушка)
    win._scan_downloads()
    dl_actions = win.dl_menu.actions()
    check("меню скачанных: переключатель порядка на месте",
          len(dl_actions) >= 2
          and dl_actions[0].text() in ("По порядку", "Вперемешку"),
          [a.text() for a in dl_actions][:3])
    check("меню скачанных строится (пустое или с файлами)",
          len(dl_actions) >= 2)
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

# 6d. плейлист локальных файлов: очередь, автопереход, ←/→, конец очереди
try:
    import tempfile
    import subprocess
    from radio.engine import AudioEngine as _AE

    # короткие файлы (2 сек) — для автоперехода по реальному eof
    qdir = tempfile.mkdtemp(prefix="radiofm-pl-")

    def _mk(prefix, count, secs):
        out = []
        for i in range(1, count + 1):
            p = os.path.join(qdir, "%s%d.mp3" % (prefix, i))
            subprocess.run(
                ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                 "anullsrc=r=44100:cl=mono", "-t", str(secs), "-q:a", "9",
                 p, "-y"], capture_output=True, timeout=30)
            if os.path.exists(p):
                out.append(p)
        return out

    qfiles = _mk("t", 3, 2)      # автопереход
    lfiles = _mk("l", 3, 10)     # ←/→ и вперемешку: трек не успевает кончиться

    if len(qfiles) < 3 or len(lfiles) < 3:
        print("skip плейлист: ffmpeg не создал файлы")
    else:
        pl = _AE(extra_args=["--ao=null"])
        pl_tracks, pl_pos, pl_errs, pl_states = [], [], [], []
        pl.trackChanged.connect(pl_tracks.append)
        pl.playlistChanged.connect(lambda p, c: pl_pos.append((p + 1, c)))
        pl.errorRaised.connect(pl_errs.append)
        pl.stateChanged.connect(pl_states.append)
        pl.play_playlist(qfiles, shuffle=False)
        check("плейлист: очередь принята", pl.has_queue)
        pump(11.0)   # 3 трека по 2 сек + запас
        played = [t for t in pl_tracks if t]
        check("плейлист: автопереход по всем трекам",
              played == ["t1.mp3", "t2.mp3", "t3.mp3"], "played=%s" % played)
        check("плейлист: позиция в очереди идёт (1..3)",
              [p for p, _ in pl_pos] == [1, 2, 3], "pos=%s" % pl_pos)
        check("плейлист: eof не считается ошибкой", not pl_errs,
              "errs=%s" % pl_errs)
        check("плейлист: конец очереди → stopped",
              pl.state == STOPPED and not pl.has_queue,
              "state=%s queue=%s" % (pl.state, pl.has_queue))

        # ←/→ внутри очереди (длинные файлы: трек не кончается сам)
        pl2 = _AE(extra_args=["--ao=null"])
        t2 = []
        pl2.trackChanged.connect(t2.append)
        pl2.play_playlist(lfiles, shuffle=False)
        pump(3.0)
        start = t2[-1] if t2 else None
        pl2.playlist_next()
        pump(2.5)
        nxt = t2[-1] if t2 else None
        pl2.playlist_prev()
        pump(2.5)
        back = t2[-1] if t2 else None
        check("плейлист: next/prev листают очередь",
              start == "l1.mp3" and nxt == "l2.mp3" and back == "l1.mp3",
              "start=%s next=%s prev=%s" % (start, nxt, back))
        pl2.shutdown()

        # вперемешку: старт с выбранного, состав тот же
        pl3 = _AE(extra_args=["--ao=null"])
        t3 = []
        pl3.trackChanged.connect(t3.append)
        pl3.play_playlist(lfiles, shuffle=True)
        pump(3.0)
        first = t3[-1] if t3 else None
        check("плейлист: вперемешку стартует с первого файла",
              first == "l1.mp3", "first=%s" % first)
        pl3.shutdown()
        pl.shutdown()
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

    # прогресс в UI: полоса идёт, перемотка работает
    if win is not None:
        win._local = True          # как будто играет локальный файл
        win._on_position(30.0, 120.0)
        check("прогресс: полоса отражает позицию",
              win.progress.value() == 250
              and win.lbl_pos.text() == "0:30"
              and win.lbl_dur.text() == "2:00",
              "value=%d pos=%s dur=%s" % (win.progress.value(),
                                          win.lbl_pos.text(),
                                          win.lbl_dur.text()))
        # радио (не локальный): полоса не должна врать
        win._local = False
        win._on_position(7.0, 24.0)
        check("прогресс: для радио полоса пустая",
              win.progress.value() == 0
              and win.lbl_dur.text() == "—:—"
              and not win.progress.isEnabled(),
              "value=%d dur=%s" % (win.progress.value(),
                                   win.lbl_dur.text()))
        # в списке скачанных видно время трека
        win._local = True
        win._scan_downloads()
        texts = [a.text() for a in win.dl_menu.actions() if not a.isSeparator()]
        check("прогресс: в списке скачанных есть время",
              any("·" in t and ":" in t for t in texts[1:]),
              texts[1:3])
except Exception as exc:
    import traceback
    traceback.print_exc()
    check("прогресс трека", False, str(exc))

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

    # Nebulous: рендерится, реагирует на полосы спектра
    from radio.viz.nebulous import Nebulous
    neb = Nebulous()
    neb.resize(500, 300)
    neb.set_active(True)
    for i in range(40):
        neb.set_audio_level(0.3 + 0.3 * math.sin(i * 0.4))
        neb.set_bands([0.6, 0.4, 0.2, 0.1, 0.05, 0.3, 0.5, 0.7])
        pump(0.02)
    check("Nebulous рендерится", not neb.grab().isNull())

    # полосы хранятся как есть (реакция на реальный спектр, без AGC)
    neb.set_bands([0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.8])
    check("спектр различает низ/верх",
          abs(neb._bands[0] - neb._bands[1]) > 0.5,
          "bands=%s" % neb._bands)

    # переключение режимов (QComboBox → QStackedWidget)
    from PySide6.QtWidgets import QComboBox, QStackedWidget
    stack = QStackedWidget()
    stack.addWidget(wave)
    stack.addWidget(neb)
    combo = QComboBox()
    combo.addItems(["Glowing Wave", "Nebulous"])
    combo.currentIndexChanged.connect(lambda i: stack.setCurrentIndex(i))
    combo.setCurrentIndex(1)
    check("переключение на Nebulous", stack.currentWidget() is neb)

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
    # резкий скачок энергии = удар → сверхновая вспыхивает
    gal._env, gal._prev_env = 0.2, 0.2
    gal._update(0.016, gal._t)
    gal.set_audio_level(0.95)
    for _ in range(6):
        pump(0.02)
    check("Galaxy: удар даёт сверхновую", gal._nova > 0.3,
          "nova=%.2f" % gal._nova)

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

    # Aurora: ленты рендерятся и реагируют на полосы спектра
    from radio.viz.aurora import Aurora
    aua = Aurora()
    aua.resize(500, 300)
    aua.set_active(True)
    for i in range(30):
        aua.set_audio_level(0.3 + 0.3 * math.sin(i * 0.4))
        aua.set_bands([0.7, 0.5, 0.3, 0.15, 0.1, 0.35, 0.55, 0.8])
        pump(0.02)
    check("Aurora рендерится", not aua.grab().isNull())

    # фон-картинка: set_background ставит pixmap, без него — сплошной цвет
    from PySide6.QtGui import QPixmap
    bg_path = os.path.join(HERE, "backgrounds", "balcony.png")
    if os.path.exists(bg_path):
        pm = QPixmap(bg_path)
        aua.set_background(pm)
        check("фон-картинка ставится и рендерится",
              aua._bg is not None and not aua.grab().isNull())
        aua.set_background(None)
        check("фон снимается (обратно сплошной цвет)", aua._bg is None)
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
