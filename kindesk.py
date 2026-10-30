#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KinDesk - области («заборы») для значков рабочего стола Windows 10/11.

Без сторонних библиотек: нужен только 64-битный Python 3.8+ с Tkinter.

Запуск:          pythonw kindesk.py        (без консоли)
Диагностика:     python kindesk.py --dump
Вернуть файлы:   python kindesk.py --restore   (вернуть всё из областей на рабочий стол)
Горячие клавиши: Ctrl+Alt+F - панель управления, Ctrl+Alt+G - свернуть / развернуть все.

Как это работает
  * Каждая область - настоящая папка (%APPDATA%\\KinDesk\\Области\\<имя>).
    Бросьте ярлык или папку с рабочего стола на область - файл переезжает в папку области
    и ИСЧЕЗАЕТ с рабочего стола; область сама рисует содержимое своей папки.
  * Двойной клик по значку - открыть, правый клик - меню. Перетащите значок за пределы
    области - он вернётся на рабочий стол в то место, куда вы его бросили; на другую
    область - переедет в неё. Файлы, которые вы сами положите в папку области, тоже видны.
  * Области - полупрозрачные окна над обоями, но под окнами программ (только на рабочем столе).
  * Управление через заголовок: ▾ свернуть / развернуть,  ◐ цветовая схема,  ≡ меню (или
    правый клик), перетаскивание за заголовок - двигать (в том числе на другой монитор),
    уголок справа внизу - размер.
  * --restore возвращает ВСЕ файлы из областей на рабочий стол.
Настройки: %APPDATA%\\KinDesk\\config.json, лог: log.txt рядом.
"""
import calendar as _calendar
import collections
import datetime
import fnmatch
import json
import math
import os
import shutil
import sys
import threading
import time
import traceback
import uuid

IS_WIN = sys.platform == "win32"

# Размеры интерфейса заданы для масштаба 100% и умножаются на масштаб экрана (apply_scale).
BASE_SIZES = {"TITLE_H": 30, "PAD": 10, "MIN_W": 190, "MIN_H": 90, "GRIP": 18}
SCALE = [1.0]
TITLE_H = 30
PAD = 10
MIN_W, MIN_H = 190, 90
GRIP = 18                     # размер уголка для изменения размера


def sc(v):
    """Логические пиксели -> физические (с учётом масштаба экрана)."""
    return int(round(v * SCALE[0]))


def apply_scale(s):
    SCALE[0] = float(s)
    g = globals()
    for k, v in BASE_SIZES.items():
        g[k] = int(round(v * SCALE[0]))

BAR_ALPHA = 0.93              # заголовок почти непрозрачный, чтобы текст читался
HOTKEY_VK = ord("F")          # Ctrl+Alt+F - панель управления
HOTKEY_KBD_VK = ord("K")      # Ctrl+Alt+K - управление областями с клавиатуры
HOTKEY_ALL_VK = ord("G")      # Ctrl+Alt+G - свернуть / развернуть все области
ICON_SIZES = [("Маленькие (24)", 24), ("Средние (32)", 32), ("Крупные (48)", 48), ("Огромные (64)", 64)]
HIDDEN_FILES = ("desktop.ini", "thumbs.db")

# Цветовые схемы из популярных палитр: (название, фон, заголовок, текст заголовка)
SCHEMES_MODERN = [
    ("Графит",   "#1E2025", "#4C8DFF", "#FFFFFF"),
    ("Полночь",  "#14172B", "#7C6CF2", "#FFFFFF"),
    ("Океан",    "#0F2530", "#1FA2C4", "#FFFFFF"),
    ("Хвоя",     "#14261F", "#2FB67C", "#FFFFFF"),
    ("Закат",    "#2B1A1F", "#F2665C", "#FFFFFF"),
    ("Янтарь",   "#2A2113", "#F0A030", "#1A1204"),
    ("Орхидея",  "#2A1730", "#C65BCF", "#FFFFFF"),
    ("Сланец",   "#26303A", "#8FA6BF", "#101820"),
    ("Лёд",      "#EAF1FA", "#5B9BEA", "#FFFFFF"),
    ("Мята",     "#E6F4EE", "#3DB88A", "#FFFFFF"),
    ("Сакура",   "#F9E9EF", "#E56B97", "#FFFFFF"),
    ("Песок",    "#F3EBDD", "#C28B3C", "#FFFFFF"),
    ("Лаванда",  "#EDE8F8", "#8A6FE0", "#FFFFFF"),
    ("Туман",    "#E9ECEF", "#667085", "#FFFFFF"),
]
SCHEMES_CLASSIC = [
    ("Nord",                "#2E3440", "#5E81AC", "#ECEFF4"),
    ("Dracula",             "#282A36", "#6272A4", "#F8F8F2"),
    ("Solarized Dark",      "#002B36", "#268BD2", "#FDF6E3"),
    ("Solarized Light",     "#FDF6E3", "#268BD2", "#FDF6E3"),
    ("Gruvbox Dark",        "#282828", "#D79921", "#282828"),
    ("Catppuccin Mocha",    "#1E1E2E", "#CBA6F7", "#1E1E2E"),
    ("Catppuccin Latte",    "#EFF1F5", "#8839EF", "#EFF1F5"),
    ("Tokyo Night",         "#1A1B26", "#7AA2F7", "#1A1B26"),
    ("One Dark",            "#282C34", "#61AFEF", "#282C34"),
    ("Monokai",             "#272822", "#A6E22E", "#272822"),
    ("Rosé Pine",           "#191724", "#EBBCBA", "#191724"),
    ("Material Teal",       "#263238", "#009688", "#FFFFFF"),
]
SCHEMES = SCHEMES_MODERN + SCHEMES_CLASSIC


def scheme_items(pick):
    """Пункты меню схем: современные, разделитель, классические."""
    mk = lambda s: (s[0], lambda s=s: pick(s), s)           # noqa: E731
    return [mk(s) for s in SCHEMES_MODERN] + [None] + [mk(s) for s in SCHEMES_CLASSIC]


ALPHAS = [(p, p / 100.0) for p in range(10, 101, 10)]     # непрозрачность области, %

APP_NAME = "KinDesk"
LEGACY_NAME = "DesktopFences"                     # прежнее имя программы (для переноса настроек)
APP_VERSION = "11.0"
APP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
CFG_PATH = os.path.join(APP_DIR, "config.json")
LOG_PATH = os.path.join(APP_DIR, "log.txt")
FENCE_ROOT = os.path.join(APP_DIR, "Области")      # здесь лежат папки областей

# Координаты областей - в системе рабочего стола (как у значков): начало в левом верхнем
# углу ВИРТУАЛЬНОГО экрана. ORIGIN - его положение на экране (отрицательное, если
# монитор расположен левее / выше основного). Задаётся в App при старте.
ORIGIN = [0, 0]


def log(msg):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except Exception:
        pass


# ----------------------------------------------------------------------------
# Конфигурация
# ----------------------------------------------------------------------------
def default_fence(name="Новая область", x=200, y=200, w=None, h=None):
    w = sc(380) if w is None else w
    h = sc(240) if h is None else h
    s = SCHEMES[0]
    return {"id": uuid.uuid4().hex[:8], "kind": "files", "folder": None, "name": name, "x": x, "y": y, "w": w, "h": h,
            "scheme": s[0], "color": s[1], "bar": s[2], "text": s[3],
            "alpha": 0.8, "icon": 32, "labels": False, "collapsed": False, "rules": [], "members": []}


MONTHS_RU = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август",
             "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
# ----------------------------------------------------------------------------
# Виджеты: чистая логика (без Windows) - заметки, события, таймер, система, буфер, поиск
# ----------------------------------------------------------------------------
WIDGETS = [("calendar", "Календарь"), ("todo", "Список дел"), ("note", "Заметки"),
           ("timer", "Таймер (помидоро / секундомер)"), ("sysmon", "Система (процессор, память, сеть)"),
           ("clipboard", "История буфера обмена"), ("search", "Поиск"), ("dock", "Панель быстрого доступа")]
WIDGET_TITLES = {"calendar": "Календарь", "todo": "Список дел", "note": "Заметка", "timer": "Таймер",
                 "sysmon": "Система", "clipboard": "Буфер обмена", "search": "Поиск"}
NOTE_SCHEME = ("Стикер", "#FFF3B0", "#F2C94C", "#3A2E00")
SYSMON_METRICS = [("cpu", "Процессор"), ("ram", "Память"), ("disk", "Диски"), ("net", "Сеть")]
SEARCH_HOTKEYS = [("Ctrl+Alt+Space", 0x20), ("Ctrl+Alt+S", ord("S")), ("Ctrl+Alt+Z", ord("Z"))]


ICON_OVR = {}                                   # путь значка (в нижнем регистре) -> файл со своим значком


def icon_key(path):
    return os.path.normcase(os.path.normpath(path))


def ensure_task_ids(cfg):
    for t in cfg.get("todo", []):
        t.setdefault("id", uuid.uuid4().hex[:8])
        t.setdefault("pomos", 0)


def parse_hotkey(name):
    """'Ctrl+Alt+Space' -> (модификаторы RegisterHotKey, код клавиши) или None."""
    for n, vk in SEARCH_HOTKEYS:
        if n == name:
            return 0x0001 | 0x0002 | 0x4000, vk
    return None


def default_timer():
    return {"mode": "pomodoro", "work": 25, "short": 5, "long": 15, "cycles": 4, "auto": False,
            "sound": True, "phase": "work", "running": False, "end": 0.0, "left": 25 * 60.0,
            "done": 0, "task": None, "sw_start": 0.0, "sw_elapsed": 0.0}


def default_dock():
    s = SCHEMES[0]
    return {"id": "dock", "kind": "dock", "name": "Панель", "folder": "_Панель", "on": False,
            "icon": 40, "topmost": False, "x": 0, "y": 0, "w": 0, "h": 0, "collapsed": False,
            "scheme": s[0], "color": s[1], "bar": s[2], "text": s[3], "alpha": 0.85}


def make_widget(kind, x=300, y=200):
    """Виджет - такая же область (заголовок, цвета, прозрачность, сворачивание), другое содержимое."""
    f = default_fence(WIDGET_TITLES.get(kind, "Виджет"), x, y)
    f["kind"] = kind
    f["alpha"] = 0.85
    f.update(cal_y=datetime.date.today().year, cal_m=datetime.date.today().month, first_weekday=0)
    f["w"] = {"calendar": sc(300), "todo": sc(320), "note": sc(240), "timer": sc(260),
              "sysmon": sc(270), "clipboard": sc(330), "search": sc(340)}.get(kind, sc(300))
    if kind == "note":
        apply_scheme(f, NOTE_SCHEME)
        f.update(note="", font=14, alpha=0.95, h=sc(200))
        return f
    if kind == "sysmon":
        f.update(metrics=[k for k, _ in SYSMON_METRICS], interval=2)
    if kind == "clipboard":
        f.update(rows=8)
    f["h"] = widget_height(f, int(f.get("rows", 8)) if kind == "clipboard" else 0)
    return f


def month_grid(year, month, first=0):
    """6 недель по 7 дней (datetime.date) для показа месяца."""
    weeks = _calendar.Calendar(first).monthdatescalendar(year, month)
    while len(weeks) < 6:
        weeks.append([weeks[-1][-1] + datetime.timedelta(days=1 + i) for i in range(7)])
    return weeks


def cal_layout(f):
    w, pad, top = f["w"], sc(12), TITLE_H + sc(10)
    nav = sc(34)
    return {"prev": (pad, top, pad + sc(34), top + nav), "next": (w - pad - sc(34), top, w - pad, top + nav),
            "label": (pad + sc(34), top, w - pad - sc(34), top + nav), "wd_y": top + nav,
            "gx": pad, "gy": top + nav + sc(24), "cw": (w - 2 * pad) / 7.0, "ch": sc(34)}


def todo_layout(f, n):
    """Строки списка дел: [(индекс, строка, галочка, крестик)], прямоугольник «добавить», высота."""
    w, pad, top = f["w"], sc(12), TITLE_H + sc(8)
    add = (pad, top, w - pad, top + sc(34))
    y, rh, rows = add[3] + sc(6), sc(32), []
    shown = min(n, 12)
    for i in range(shown):
        rows.append((i, (pad, y, w - pad, y + rh), (pad + sc(4), y + sc(6), pad + sc(24), y + sc(26)),
                     (w - pad - sc(28), y + sc(4), w - pad - sc(4), y + rh - sc(4))))
        y += rh
    more = None
    if n > shown:
        more = y
        y += sc(22)
    if n == 0:
        y += sc(40)
    return {"add": add, "rows": rows, "more": more, "h": y + sc(12)}


def timer_layout(f):
    w, pad = f["w"], sc(14)
    y = TITLE_H + sc(8)
    half = (w - 2 * pad) // 2
    tabs = {"pomodoro": (pad, y, pad + half, y + sc(28)), "stopwatch": (pad + half, y, w - pad, y + sc(28))}
    y += sc(34)
    task = (pad, y, w - pad, y + sc(24))
    y += sc(30)
    ring = sc(104)
    ring_r = ((w - ring) // 2, y, (w + ring) // 2, y + ring)
    y += ring + sc(10)
    b = sc(38)
    cx = w // 2
    btn = {"reset": (cx - sc(70) - b // 2, y, cx - sc(70) + b // 2, y + b),
           "toggle": (cx - sc(24), y - sc(4), cx + sc(24), y + b + sc(4)),
           "skip": (cx + sc(70) - b // 2, y, cx + sc(70) + b // 2, y + b)}
    return {"tabs": tabs, "task": task, "ring": ring_r, "btn": btn, "h": y + b + sc(16)}


def search_layout(f):
    return (sc(12), TITLE_H + sc(10), f["w"] - sc(12), TITLE_H + sc(44))


def sysmon_row(f, i):
    y = TITLE_H + sc(10) + i * sc(40)
    return (sc(14), y, f["w"] - sc(14), y + sc(36))


def sysmon_rows(f):
    return max(1, len(f.get("metrics", [])))


def clip_layout(f, n):
    w, pad, rh = f["w"], sc(12), sc(30)
    top = TITLE_H + sc(8)
    head = (pad, top, w - pad, top + sc(26))
    y, rows = head[3] + sc(4), []
    for i in range(min(n, int(f.get("rows", 8)))):
        rows.append((i, (pad, y, w - pad, y + rh), (w - pad - sc(52), y + sc(3), w - pad - sc(28), y + rh - sc(3)),
                     (w - pad - sc(26), y + sc(3), w - pad - sc(2), y + rh - sc(3))))
        y += rh
    if n == 0:
        y += sc(46)
    return {"head": head, "rows": rows, "h": y + sc(12)}


def widget_height(f, n_items):
    kind = f["kind"]
    if kind == "calendar":
        lay = cal_layout(f)
        return int(lay["gy"] + 6 * lay["ch"] + sc(14))
    if kind == "todo":
        return todo_layout(f, n_items)["h"]
    if kind == "timer":
        return timer_layout(f)["h"]
    if kind == "sysmon":
        return TITLE_H + sc(14) + sysmon_rows(f) * sc(40) + sc(8)
    if kind == "clipboard":
        return clip_layout(f, min(n_items, int(f.get("rows", 8))))["h"]
    if kind == "search":
        return TITLE_H + sc(56)
    return f["h"]


def dock_geom(d, n, primary):
    """Размер и положение панели: по центру сверху основного монитора. primary = (x, y, ширина)."""
    isz = sc(int(d.get("icon", 40)))
    cell, pad = isz + sc(18), sc(12)
    w = max(2 * pad + n * cell + sc(26), sc(300) if n == 0 else 0)
    d["w"], d["h"] = w, isz + sc(22)
    d["x"] = primary[0] + (primary[2] - w) // 2
    d["y"] = primary[1] + sc(8)
    return cell, pad, isz


def dock_rects(d, n):
    """Ячейки значков и маленькая кнопка «+» относительно левого верхнего угла панели."""
    isz = sc(int(d.get("icon", 40)))
    cell, pad = isz + sc(18), sc(12)
    top = (d["h"] - (isz + sc(12))) // 2
    items = [(pad + i * cell, top, pad + (i + 1) * cell, top + isz + sc(12)) for i in range(n)]
    ax = pad + n * cell
    add = (ax, d["h"] // 2 - sc(11), ax + sc(22), d["h"] // 2 + sc(11))
    return items, add


# ---- календарь: события -------------------------------------------------------
def parse_ics(text):
    """Разобрать iCalendar (.ics): [{'date': 'ГГГГ-ММ-ДД', 't': название, 'rep': none/yearly/...}]."""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    out, ev = [], None
    for ln in lines:
        if ln.startswith("BEGIN:VEVENT"):
            ev = {}
        elif ln.startswith("END:VEVENT") and ev is not None:
            if ev.get("date") and ev.get("t"):
                out.append(ev)
            ev = None
        elif ev is not None and ":" in ln:
            key, _, val = ln.partition(":")
            name = key.split(";")[0].upper()
            if name == "DTSTART" and len(val) >= 8 and val[:8].isdigit():
                ev["date"] = "%s-%s-%s" % (val[0:4], val[4:6], val[6:8])
            elif name == "SUMMARY":
                ev["t"] = val.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()
            elif name == "RRULE":
                freq = {p.split("=")[0]: p.split("=")[-1] for p in val.split(";") if "=" in p}.get("FREQ", "")
                ev["rep"] = {"YEARLY": "yearly", "MONTHLY": "monthly", "WEEKLY": "weekly",
                             "DAILY": "daily"}.get(freq, "none")
    for e in out:
        e.setdefault("rep", "none")
    return out


def events_on(events, day):
    """Тексты событий на дату day (datetime.date) из списка событий с повторами."""
    res = []
    for e in events:
        try:
            d0 = datetime.date.fromisoformat(e["date"])
        except (ValueError, KeyError):
            continue
        rep = e.get("rep", "none")
        if rep == "none":
            ok = d0 == day
        elif day < d0:
            ok = False
        elif rep == "yearly":
            ok = (d0.month, d0.day) == (day.month, day.day)
        elif rep == "monthly":
            ok = d0.day == day.day
        elif rep == "weekly":
            ok = d0.weekday() == day.weekday()
        elif rep == "daily":
            ok = True
        else:
            ok = False
        if ok:
            res.append(e["t"])
    return res


# ---- таймер ----------------------------------------------------------------------
class TimerState(object):
    """Помидоро (работа / короткий / длинный перерыв) и секундомер. now - время в секундах."""

    def __init__(self, t):
        self.t = t

    def phase_seconds(self):
        t = self.t
        return float({"work": t["work"], "short": t["short"], "long": t["long"]}[t["phase"]] * 60)

    def remaining(self, now):
        t = self.t
        return max(0.0, t["end"] - now) if t["running"] else t["left"]

    def elapsed(self, now):
        t = self.t
        return t["sw_elapsed"] + (now - t["sw_start"] if t["running"] else 0.0)

    def start(self, now):
        t = self.t
        if t["running"]:
            return
        t["running"] = True
        if t["mode"] == "pomodoro":
            t["end"] = now + t["left"]
        else:
            t["sw_start"] = now

    def pause(self, now):
        t = self.t
        if not t["running"]:
            return
        if t["mode"] == "pomodoro":
            t["left"] = max(0.0, t["end"] - now)
        else:
            t["sw_elapsed"] += now - t["sw_start"]
        t["running"] = False

    def toggle(self, now):
        (self.pause if self.t["running"] else self.start)(now)

    def reset(self):
        t = self.t
        t.update(running=False, left=self.phase_seconds(), sw_elapsed=0.0, sw_start=0.0)

    def set_mode(self, mode):
        self.t["mode"] = mode
        self.t["running"] = False
        self.reset()

    def _next_phase(self, finished):
        t = self.t
        if finished == "work":
            return "long" if t["done"] % max(1, int(t["cycles"])) == 0 else "short"
        return "work"

    def skip(self, now):
        """Перейти к следующей фазе без зачёта помидора."""
        t = self.t
        nxt = "work" if t["phase"] != "work" else "short"
        t["phase"] = nxt
        t["running"] = False
        t["left"] = self.phase_seconds()
        return nxt

    def tick(self, now):
        """-> None или ('done', завершённая фаза, следующая фаза)."""
        t = self.t
        if t["mode"] != "pomodoro" or not t["running"] or now < t["end"]:
            return None
        finished = t["phase"]
        if finished == "work":
            t["done"] += 1
        t["phase"] = self._next_phase(finished)
        t["left"] = self.phase_seconds()
        t["running"] = bool(t["auto"])
        if t["running"]:
            t["end"] = now + t["left"]
        return ("done", finished, t["phase"])


def fmt_clock(sec):
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return "%d:%02d:%02d" % (h, m, s) if h else "%02d:%02d" % (m, s)


# ---- система ---------------------------------------------------------------------
class SysMon(object):
    """Считает загрузку процессора и скорость сети по двум замерам. readers - словарь функций:
    cpu() -> (idle, total), mem() -> процент, disks() -> [(метка, процент занято, свободно ГБ)],
    net() -> (принято байт, отправлено байт)."""

    def __init__(self, readers):
        self.r = readers
        self.prev_cpu = self.prev_net = None
        self.last = {"cpu": 0.0, "ram": 0.0, "disks": [], "down": 0.0, "up": 0.0}

    def sample(self, now):
        r, out = self.r, self.last
        try:
            idle, total = r["cpu"]()
            if self.prev_cpu:
                di, dt = idle - self.prev_cpu[0], total - self.prev_cpu[1]
                if dt > 0:
                    out["cpu"] = max(0.0, min(100.0, 100.0 * (1.0 - di / float(dt))))
            self.prev_cpu = (idle, total)
            out["ram"] = float(r["mem"]())
            out["disks"] = r["disks"]()
            rx, tx = r["net"]()
            if self.prev_net:
                dts = max(0.001, now - self.prev_net[2])
                out["down"] = max(0.0, ((rx - self.prev_net[0]) % 2 ** 32) / dts)
                out["up"] = max(0.0, ((tx - self.prev_net[1]) % 2 ** 32) / dts)
            self.prev_net = (rx, tx, now)
        except Exception:
            log("sysmon sample failed:\n" + traceback.format_exc())
        return out


def fmt_speed(bps):
    for unit, div in (("ГБ/с", 1 << 30), ("МБ/с", 1 << 20), ("КБ/с", 1 << 10)):
        if bps >= div:
            return "%.1f %s" % (bps / div, unit)
    return "%d Б/с" % bps


# ---- буфер обмена ------------------------------------------------------------------
class ClipHistory(object):
    """История текстов из буфера обмена: закреплённые сверху, остальные ограничены лимитом."""

    def __init__(self, data):
        self.d = data                                    # {"items": [...], "pins": [...], "max": 30}

    def add(self, text):
        text = text.strip("\r\n")
        if not text.strip():
            return False
        d = self.d
        if text in d["pins"]:
            return False
        if text in d["items"]:
            d["items"].remove(text)
        d["items"].insert(0, text)
        del d["items"][int(d.get("max", 30)):]
        return True

    def all(self):
        return list(self.d["pins"]) + list(self.d["items"])

    def is_pinned(self, i):
        return i < len(self.d["pins"])

    def toggle_pin(self, i):
        d, allv = self.d, self.all()
        if not 0 <= i < len(allv):
            return
        text = allv[i]
        if i < len(d["pins"]):
            d["pins"].remove(text)
            d["items"].insert(0, text)
        else:
            d["items"].remove(text)
            d["pins"].append(text)

    def delete(self, i):
        d, allv = self.d, self.all()
        if 0 <= i < len(allv):
            (d["pins"] if i < len(d["pins"]) else d["items"]).remove(allv[i])

    def clear(self):
        self.d["items"] = []


# ---- поиск -----------------------------------------------------------------------------
def safe_calc(expr):
    """Вычислить простое арифметическое выражение без eval. -> число или None."""
    import ast
    import operator
    ops = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
           ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv}

    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.BinOp) and type(n.op) in ops:
            a, b = ev(n.left), ev(n.right)
            if isinstance(n.op, ast.Pow) and abs(b) > 100:
                raise ValueError("слишком большая степень")
            return ops[type(n.op)](a, b)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.UAdd, ast.USub)):
            return ev(n.operand) * (1 if isinstance(n.op, ast.UAdd) else -1)
        raise ValueError("недопустимо")
    try:
        text = expr.replace(",", ".").replace("×", "*").replace("÷", "/").replace("^", "**")
        if not any(c in text for c in "+-*/%") or not all(c in "0123456789.+-*/%() " for c in text):
            return None
        return ev(ast.parse(text.strip(), mode="eval"))
    except Exception:
        return None


def fmt_number(v):
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        v = int(v)
    return ("%.10g" % v) if isinstance(v, float) else str(v)


def search_index(roots, limit=30000):
    """Собрать список (название, путь) из папок roots: [(путь, макс. глубина)]."""
    out, seen = [], set()
    for root, depth in roots:
        if not os.path.isdir(root):
            continue
        base = root.rstrip("\\/").count(os.sep)
        for dirpath, dirs, files in os.walk(root):
            if dirpath.count(os.sep) - base >= depth:
                dirs[:] = []
            for n in files + dirs:
                if n.lower() in HIDDEN_FILES:
                    continue
                p = os.path.join(dirpath, n)
                if p in seen:
                    continue
                seen.add(p)
                out.append((item_label(n), p))
                if len(out) >= limit:
                    return out
    return out


def search_rank(index, query, limit=8):
    """Лучшие совпадения по названию: сначала начало слова, потом подстрока."""
    q = query.strip().lower()
    if not q:
        return []
    scored = []
    for label, path in index:
        low = label.lower()
        if low == q:
            sc_ = 0
        elif low.startswith(q):
            sc_ = 1
        elif (" " + q) in (" " + low.replace("-", " ").replace("_", " ")):
            sc_ = 2
        elif q in low:
            sc_ = 3
        else:
            continue
        ext = os.path.splitext(path)[1].lower()
        scored.append((sc_, 0 if ext in (".lnk", ".exe", ".url") else 1, len(label), label, path))
    scored.sort()
    out, seen = [], set()
    for _, _, _, label, path in scored:
        if (label.lower(), os.path.splitext(path)[1].lower()) in seen:
            continue
        seen.add((label.lower(), os.path.splitext(path)[1].lower()))
        out.append((label, path))
        if len(out) >= limit:
            break
    return out


def eff_h(f):
    """Видимая высота области: у свёрнутой - только заголовок."""
    return TITLE_H if f.get("collapsed") else f["h"]


def group_members(cfg, gid):
    """Области одной группы сверху вниз (по порядку gi)."""
    if not gid:
        return []
    return sorted((f for f in cfg["fences"] if f.get("group") == gid), key=lambda f: f.get("gi", 0))


GROUP_COLORS = ["#4C8DFF", "#2FB67C", "#F2665C", "#F0A030", "#C65BCF", "#1FA2C4", "#E56B97", "#8A6FE0"]


def group_color(gid):
    try:
        return GROUP_COLORS[int(gid, 16) % len(GROUP_COLORS)]
    except (TypeError, ValueError):
        return GROUP_COLORS[0]


def layout_groups(cfg, hfn=eff_h, gap=None):
    """Сложить сгруппированные области: в столбец (по умолчанию) или в ряд (gdir = "h").
    Первая область - якорь, остальные идут за ней без перекрытий (высоту даёт hfn).
    -> список областей, сдвинутых с места."""
    gap = sc(10) if gap is None else gap
    moved = []
    for gid in {f.get("group") for f in cfg["fences"] if f.get("group")}:
        ms = group_members(cfg, gid)
        if len(ms) < 2:
            continue
        lead = ms[0]
        row = lead.get("gdir") == "h"
        x, y = (lead["x"] + lead["w"] + gap, lead["y"]) if row else (lead["x"], lead["y"] + hfn(lead) + gap)
        for f in ms[1:]:
            if (f["x"], f["y"]) != (x, y):
                f["x"], f["y"] = x, y
                moved.append(f)
            if row:
                x += f["w"] + gap
            else:
                y += hfn(f) + gap
    return moved


def apply_scheme(f, scheme):
    f["scheme"], f["color"], f["bar"], f["text"] = scheme


def new_config():
    return {"fences": [], "sync_ms": 800, "parent_mode": None, "translucent": True, "coord_space": "desk",
            "todo": [], "stash": {}, "dock": default_dock(), "events": [], "ics_urls": [], "ics_cache": [],
            "timer": default_timer(),
            "clip": {"items": [], "pins": [], "max": 30, "persist": False, "skip_private": True},
            "search": {"folders": [], "web": "https://www.google.com/search?q={q}", "hotkey": "Ctrl+Alt+Space"},
            "dblclick": "off", "icons": {}, "look": "modern",
            "backup_auto": True, "app_version": ""}


SCHEMA = 2                                       # версия формата config.json
LOAD_INFO = {"recovered": None}                  # откуда пришлось восстанавливать повреждённые настройки


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and isinstance(data.get("fences", []), list) else None
    except (OSError, ValueError):
        return None


def normalize_config(cfg):
    """Достроить настройки значениями по умолчанию и перенести старые форматы."""
    cfg.setdefault("fences", [])
    cfg.setdefault("sync_ms", 2000)
    cfg.setdefault("parent_mode", None)
    cfg.setdefault("translucent", True)
    cfg["sync_ms"] = min(int(cfg.get("sync_ms", 800)), 800)
    for k, v in new_config().items():
        cfg.setdefault(k, v)
        if isinstance(v, dict) and k != "stash" and isinstance(cfg[k], dict):
            for kk, vv in v.items():
                cfg[k].setdefault(kk, vv)
    ensure_task_ids(cfg)
    fix_legacy_paths(cfg)
    notes = list(cfg["fences"]) + [n for v in cfg.get("stash", {}).values() for n in (v if isinstance(v, list) else [v])]
    for f in notes:                                  # заметки v9: текст был в ключе «text» (цвет)
        if isinstance(f, dict) and f.get("kind") == "note":
            if not str(f.get("text", "")).startswith("#"):
                f["note"] = f.get("note") or f.get("text", "")
                f["text"] = NOTE_SCHEME[3]
    dock = cfg.setdefault("dock", default_dock())
    for k, v in default_dock().items():
        dock.setdefault(k, v)
    cfg.setdefault("coord_space", None)      # None = старый конфиг с экранными координатами
    for f in cfg["fences"]:
        base = default_fence()
        old_color = "color" in f and "bar" not in f
        for k, v in base.items():
            f.setdefault(k, v)
        if not f.get("id"):
            f["id"] = base["id"]
        if old_color:                      # конфиг из первой версии
            f["bar"], f["text"] = darken(f["color"]), "#FFFFFF"
    cfg["schema"] = SCHEMA
    return cfg


def load_config():
    """Прочитать настройки. Если файл повреждён - не терять всё молча: взять предыдущую
    копию (.bak), затем последнюю резервную копию; повреждённый файл сохраняется рядом."""
    LOAD_INFO["recovered"] = None
    try:
        if not os.path.exists(CFG_PATH):
            return new_config()
        cfg = _read_json(CFG_PATH)
        if cfg is None:
            log("config.json повреждён, пробую восстановить")
            try:
                shutil.copy2(CFG_PATH, CFG_PATH + ".corrupt-" + time.strftime("%Y%m%d-%H%M%S"))
            except OSError:
                pass
            cfg = _read_json(CFG_PATH + ".bak")
            if cfg is not None:
                LOAD_INFO["recovered"] = "предыдущей версии файла настроек"
            else:
                for path, _when, _tag, _size in list_backups():
                    cfg = read_backup_config(path)
                    if cfg is not None:
                        LOAD_INFO["recovered"] = "резервной копии " + os.path.basename(path)
                        break
            if cfg is None:
                return new_config()
        return normalize_config(cfg)
    except Exception:
        log("config load failed:\n" + traceback.format_exc())
        return new_config()


def save_config(cfg):
    """Записать настройки целиком и атомарно; прошлая версия остаётся в config.json.bak."""
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        tmp = CFG_PATH + ".tmp"
        out = cfg
        clip = cfg.get("clip")
        if clip and not clip.get("persist"):             # история буфера - только в памяти
            out = dict(cfg)
            out["clip"] = dict(clip, items=[])
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        if os.path.exists(CFG_PATH):
            try:
                shutil.copyfile(CFG_PATH, CFG_PATH + ".bak")
            except OSError:
                pass
        os.replace(tmp, CFG_PATH)
    except Exception:
        log("config save failed:\n" + traceback.format_exc())


# ---- резервные копии -------------------------------------------------------------------
def backup_dir():
    return os.path.join(APP_DIR, "backups")


def icons_dir():
    return os.path.join(APP_DIR, "icons")


def make_backup(tag="auto", dst=None, keep=20):
    """Zip с настройками и своими значками (файлы пользователя в областях не копируются).
    tag: auto - ежедневные / перед обновлением / перед опасными действиями (хранится последние keep),
    manual - по кнопке (не удаляется сам). -> путь или None."""
    try:
        if dst is None:
            os.makedirs(backup_dir(), exist_ok=True)
            dst = os.path.join(backup_dir(), "kindesk-%s-%s.zip" % (time.strftime("%Y%m%d-%H%M%S"), tag))
            n = 1
            while os.path.exists(dst):
                n += 1
                dst = dst[:-4].rsplit("#", 1)[0] + "#%d.zip" % n
        import zipfile
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
            if os.path.exists(CFG_PATH):
                z.write(CFG_PATH, "config.json")
            idir = icons_dir()
            if os.path.isdir(idir):
                for n_ in os.listdir(idir):
                    z.write(os.path.join(idir, n_), "icons/" + n_)
            z.writestr("meta.json", json.dumps({"app": APP_NAME, "version": APP_VERSION, "tag": tag,
                                                 "time": time.strftime("%Y-%m-%d %H:%M:%S")}))
        if tag != "manual" and os.path.dirname(dst) == backup_dir():
            auto = [b for b in list_backups() if b[2] != "manual"]
            for path, _w, _t, _s in auto[keep:]:
                try:
                    os.remove(path)
                except OSError:
                    pass
        return dst
    except Exception:
        log("make_backup failed:\n" + traceback.format_exc())
        return None


def list_backups():
    """[(путь, время, метка, размер)] от новых к старым."""
    out = []
    try:
        for n in os.listdir(backup_dir()):
            if n.startswith("kindesk-") and n.endswith(".zip"):
                p_ = os.path.join(backup_dir(), n)
                parts = n[:-4].split("-")
                tag = "-".join(parts[3:]).split("#")[0] if len(parts) > 3 else "auto"
                out.append((p_, os.path.getmtime(p_), tag, os.path.getsize(p_)))
    except OSError:
        pass
    return sorted(out, key=lambda b: (b[1], b[0]), reverse=True)


def read_backup_config(path):
    try:
        import zipfile
        with zipfile.ZipFile(path) as z:
            data = json.loads(z.read("config.json").decode("utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def restore_backup(path):
    """Вернуть настройки и значки из zip (из резервной копии или экспорта). Перед этим
    текущие настройки сохраняются отдельной копией. -> True / False."""
    import zipfile
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "config.json" not in names or read_backup_config(path) is None:
                return False
            make_backup("before-restore")
            data = z.read("config.json")
            os.makedirs(APP_DIR, exist_ok=True)
            with open(CFG_PATH + ".tmp", "wb") as fh:
                fh.write(data)
            os.replace(CFG_PATH + ".tmp", CFG_PATH)
            for n in names:
                if n.startswith("icons/") and os.path.basename(n) == n[6:] and n[6:]:
                    os.makedirs(icons_dir(), exist_ok=True)       # только плоские файлы: защита от ../
                    with open(os.path.join(icons_dir(), n[6:]), "wb") as fh:
                        fh.write(z.read(n))
        return True
    except Exception:
        log("restore_backup failed:\n" + traceback.format_exc())
        return False


def ui_palette(accent="#4C8DFF"):
    """Единые цвета меню и окон программы."""
    return {"bg": "#202227", "panel": "#2A2D34", "btn": "#343841", "btn_hi": "#40454F", "fg": "#F2F3F5",
            "mute": "#98A0AD", "line": "#3B3F48", "acc": accent, "acc_hi": blend(accent, "#FFFFFF", 0.18),
            "hi": blend(accent, "#000000", 0.15)}


# ----------------------------------------------------------------------------
# Движок: значки, брошенные в область, переезжают в папку области (без Windows)
# ----------------------------------------------------------------------------
def make_shortcut(target, dst):
    """Создать ярлык .lnk на target (через Windows Script Host; окно консоли не показывается)."""
    import subprocess
    q = lambda p: "'" + p.replace("'", "''") + "'"
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut(%s);$s.TargetPath=%s;"
          "$s.WorkingDirectory=(Split-Path -Parent %s);$s.Save()" % (q(dst), q(target), q(target)))
    flags = 0x08000000 if IS_WIN else 0                    # CREATE_NO_WINDOW
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                   check=True, creationflags=flags, timeout=20)


def desktop_dirs():
    """Папки рабочего стола: личная и общая (OneDrive-перенаправление учитывается)."""
    out = []
    if IS_WIN:
        import ctypes
        buf = ctypes.create_unicode_buffer(520)
        for csidl in (0x10, 0x19):               # DESKTOPDIRECTORY, COMMON_DESKTOPDIRECTORY
            try:
                if ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf) == 0 and buf.value:
                    out.append(buf.value)
            except Exception:
                pass
    if not out:
        out.append(os.path.join(os.path.expanduser("~"), "Desktop"))
    return out


def migrate_legacy_name(base=None):
    """Программа раньше называлась DesktopFences: перенести папку настроек под новое имя.
    Вызывается до того, как что-то запишет в новую папку. -> True, если перенесли."""
    base = base or os.environ.get("APPDATA", os.path.expanduser("~"))
    old, new = os.path.join(base, LEGACY_NAME), os.path.join(base, APP_NAME)
    try:
        if os.path.isdir(old) and not os.path.exists(new):
            os.rename(old, new)
            return True
    except OSError:
        pass
    return False


def fix_legacy_paths(cfg):
    """Пути к своим значкам в настройках вели в папку со старым именем."""
    mark = os.sep + LEGACY_NAME + os.sep
    for k, v in list(cfg.get("icons", {}).items()):
        if isinstance(v, str) and mark in v:
            cfg["icons"][k] = v.replace(mark, os.sep + APP_NAME + os.sep)


def choose_fence_root():
    """Папки областей должны лежать на том же диске, что и рабочий стол: тогда перенос -
    мгновенное переименование, а не копирование (на другом диске shutil.move копирует)."""
    global FENCE_ROOT
    try:
        d = desktop_dirs()[0]
        drive = os.path.splitdrive(d)[0]
        if drive and drive.upper() != os.path.splitdrive(FENCE_ROOT)[0].upper():
            new = drive + os.sep + APP_NAME
            legacy = drive + os.sep + LEGACY_NAME
            if os.path.isdir(legacy) and not os.path.exists(new):
                os.rename(legacy, new)                      # прежнее имя программы
                log("fence root renamed %s -> %s" % (legacy, new))
            os.makedirs(new, exist_ok=True)
            old, FENCE_ROOT = FENCE_ROOT, new
            log("fence root moved to %s (desktop is on %s)" % (new, drive))
            if os.path.isdir(old):
                for n in os.listdir(old):
                    dst = os.path.join(new, n)
                    if not os.path.exists(dst):
                        shutil.move(os.path.join(old, n), dst)
    except Exception:
        log("choose_fence_root failed:\n" + traceback.format_exc())


def item_label(name):
    """Как подписан файл на рабочем столе: у ярлыков нет .lnk / .url."""
    base, ext = os.path.splitext(name)
    return base if ext.lower() in (".lnk", ".url") else name


def safe_name(name):
    s = "".join("_" if c in '<>:"/\\|?*' or ord(c) < 32 else c for c in name).strip(" .")
    return s or "Область"


def unique_path(folder, name):
    dst = os.path.join(folder, name)
    if not os.path.exists(dst):
        return dst
    base, ext = os.path.splitext(name)
    k = 2
    while os.path.exists(os.path.join(folder, "%s (%d)%s" % (base, k, ext))):
        k += 1
    return os.path.join(folder, "%s (%d)%s" % (base, k, ext))


def contrast(hexc):
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return "#FFFFFF" if 0.299 * r + 0.587 * g + 0.114 * b < 140 else "#1B1B1B"


def blend(a, b, t):
    ha, hb = a.lstrip("#"), b.lstrip("#")
    ca = [int(ha[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(hb[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ca, cb))


class FenceEngine:
    """Каждая область - настоящая папка в FENCE_ROOT. Значок, брошенный на область,
    переносится в эту папку (с рабочего стола он исчезает), а область рисует содержимое
    папки сама. Работает с рабочим столом через объект: snapshot() -> [{'idx','name',
    'x','y'}], spacing() -> (cw, ch), set_pos(idx, x, y)."""

    def __init__(self, cfg, desktop):
        self.cfg = cfg
        self.dt = desktop
        self._items = {}                       # id(f) -> список файлов папки
        self.pending = []                      # значки, вернувшиеся на стол: поставить на место
        self.cwd = {}                          # id области -> открытая вложенная папка (относительно корня)
        self._warned = set()

    @property
    def fences(self):
        return self.cfg["fences"]

    def areas(self):
        """Всё, что хранит файлы в папке: области с файлами и (если включена) панель быстрого доступа."""
        out = [f for f in self.fences if f.get("kind", "files") == "files"]
        dock = self.cfg.get("dock")
        if dock and dock.get("on"):
            out.append(dock)
        return out

    @staticmethod
    def has_files(f):
        return f.get("kind", "files") in ("files", "dock")

    # --- папки -------------------------------------------------------------------
    def folder(self, f):
        name = f.get("folder")
        if not name:
            used = set(g.get("folder", "").lower() for g in self.fences if g is not f and g.get("folder"))
            base = safe_name(f["name"])
            name, k = base, 2
            while name.lower() in used:
                name = "%s (%d)" % (base, k)
                k += 1
            f["folder"] = name
        path = os.path.join(FENCE_ROOT, name)
        os.makedirs(path, exist_ok=True)
        return path

    def cur(self, f):
        """Папка, которая сейчас открыта в области (корень или вложенная)."""
        root = self.folder(f)
        rel = self.cwd.get(f["id"], "")
        path = os.path.join(root, rel) if rel else root
        if rel and not os.path.isdir(path):      # вложенную папку удалили снаружи
            self.cwd[f["id"]] = ""
            return root
        return path

    def title(self, f):
        if f.get("kind") == "todo":
            left = sum(1 for t in self.cfg.get("todo", []) if not t.get("d"))
            return f["name"] + ("  ·  %d" % left if left else "")
        rel = self.cwd.get(f["id"], "")
        return f["name"] + ("  ›  " + "  ›  ".join(rel.split(os.sep)) if rel else "")

    def navigate(self, f, name):
        path = os.path.join(self.cur(f), name)
        if os.path.isdir(path):
            rel = self.cwd.get(f["id"], "")
            self.cwd[f["id"]] = os.path.join(rel, name) if rel else name
            self.rescan(f)
            return True
        return False

    def go_up(self, f):
        rel = self.cwd.get(f["id"], "")
        if rel:
            self.cwd[f["id"]] = os.path.dirname(rel)
            self.rescan(f)

    def rename_folder(self, f, new_name):
        old = self.folder(f)
        used = set(g.get("folder", "").lower() for g in self.fences if g is not f and g.get("folder"))
        base = safe_name(new_name)
        name, k = base, 2
        while name.lower() in used:
            name = "%s (%d)" % (base, k)
            k += 1
        if name == f["folder"]:
            return
        try:
            os.rename(old, os.path.join(FENCE_ROOT, name))
            f["folder"] = name
        except OSError:
            log("rename folder failed:\n" + traceback.format_exc())

    def scan(self, f):
        if not self.has_files(f):
            return []
        path = self.cur(f)
        try:
            names = os.listdir(path)
        except OSError:
            names = []
        out = [{"name": n, "label": item_label(n), "path": os.path.join(path, n),
                "isdir": os.path.isdir(os.path.join(path, n))}
               for n in names if n.lower() not in HIDDEN_FILES]
        out.sort(key=lambda d: (not d["isdir"], d["label"].lower()))     # папки первыми, как в Проводнике
        if self.cwd.get(f["id"]):
            out.insert(0, {"name": "..", "label": "..", "path": os.path.dirname(path),
                           "isdir": True, "up": True})
        return out

    def rescan(self, f):
        """-> True, если состав папки изменился."""
        new = self.scan(f)
        old = self._items.get(id(f))
        self._items[id(f)] = new
        if self.grow(f):
            return True
        return old is None or [d["name"] for d in old] != [d["name"] for d in new]

    def rescan_all(self):
        changed = False
        for f in self.areas():
            if self.rescan(f):
                changed = True
        return changed

    def items(self, f):
        if id(f) not in self._items:
            self.rescan(f)
        return self._items[id(f)]

    # --- геометрия сетки -----------------------------------------------------------
    @staticmethod
    def cell(f):
        """Размер ячейки значка: зависит от размера иконок и от того, показаны ли подписи."""
        isz = sc(int(f.get("icon", 32)))
        if f.get("labels"):
            return max(sc(88), isz + sc(24)), isz + sc(16) + sc(32)
        return isz + sc(24), isz + sc(16)

    def cols(self, f):
        return max(1, int((f["w"] - 2 * PAD) // self.cell(f)[0]))

    def need_h(self, f, n=None):
        if n is None:
            n = len(self.items(f))
        rows = max(1, int(math.ceil(n / float(self.cols(f)))))
        return max(MIN_H, TITLE_H + 2 * PAD + rows * self.cell(f)[1])

    def grow(self, f):
        if f.get("kind", "files") != "files":
            return False
        need = self.need_h(f, len(self._items.get(id(f), ())))
        if f["h"] < need:
            f["h"] = need
            return True
        return False

    def slot(self, f, k):
        """Ячейка k внутри тела области: (x, y) относительно левого верхнего угла области."""
        cols = self.cols(f)
        r, c = divmod(k, cols)
        cw, ch = self.cell(f)
        return PAD + c * cw, TITLE_H + PAD + r * ch

    # --- перенос файлов --------------------------------------------------------------
    @staticmethod
    def _inside(f, ic, cw, ch):
        cx = ic["x"] + cw / 2.0
        cy = ic["y"] + ch / 2.0
        return f["x"] <= cx < f["x"] + f["w"] and f["y"] <= cy < f["y"] + f["h"]

    def find_on_desktop(self, label):
        stem = None
        for d in desktop_dirs():
            try:
                names = os.listdir(d)
            except OSError:
                continue
            for n in names:
                if n.lower() in HIDDEN_FILES:
                    continue
                if n == label or item_label(n) == label:
                    return os.path.join(d, n)
                if stem is None and os.path.splitext(n)[0] == label:
                    stem = os.path.join(d, n)
        return stem

    def claim(self, f, label):
        """Перенести значок рабочего стола в папку области. -> True, если перенесён."""
        src = self.find_on_desktop(label)
        if src is None:
            if label not in self._warned:      # корзина, «Этот компьютер» и т.п. - не файлы
                self._warned.add(label)
                log("claim: файл «%s» не найден на рабочем столе (системный значок?)" % label)
            return False
        try:
            shutil.move(src, unique_path(self.cur(f), os.path.basename(src)))
        except (OSError, shutil.Error):
            if label not in self._warned:
                self._warned.add(label)
                log("claim failed for %r:\n%s" % (src, traceback.format_exc()))
            return False
        self.rescan(f)
        return True

    def sync(self):
        """Значки, лежащие внутри развёрнутой области, переезжают в её папку.
        -> True, если что-то изменилось (нужно перерисовать)."""
        changed = False
        icons = self.dt.snapshot()
        cw, ch = self.dt.spacing()
        waiting = set(p["label"] for p in self.pending)
        for ic in icons:
            if ic["name"] in waiting:
                continue
            for f in reversed(self.areas()):   # верхняя область главнее
                if f.get("collapsed"):
                    continue
                if self._inside(f, ic, cw, ch):
                    if self.claim(f, ic["name"]):
                        changed = True
                    break
        if self.rescan_all():
            changed = True
        return changed

    def move_item(self, src, name, dst):
        """Из одной области в другую."""
        shutil.move(os.path.join(self.cur(src), name), unique_path(self.cur(dst), name))
        self.rescan(src)
        self.rescan(dst)

    def release_item(self, f, name, pos=None):
        """Вернуть файл на рабочий стол; pos - где поставить значок (координаты стола)."""
        dst = unique_path(desktop_dirs()[0], name)
        shutil.move(os.path.join(self.cur(f), name), dst)
        if pos is not None:
            self.pending.append({"label": item_label(os.path.basename(dst)),
                                 "x": pos[0], "y": pos[1], "t": time.time()})
        self.rescan(f)
        return dst

    def move_into(self, f, name, sub):
        """Переложить элемент в папку sub той же области."""
        base = self.cur(f)
        shutil.move(os.path.join(base, name), unique_path(os.path.join(base, sub), name))
        self.rescan(f)

    def move_up(self, f, name):
        base = self.cur(f)
        shutil.move(os.path.join(base, name), unique_path(os.path.dirname(base), name))
        self.rescan(f)

    def rename_item(self, f, old, new):
        """Переименовать; у ярлыков расширение .lnk / .url сохраняется. -> новое имя файла."""
        new = new.strip()
        if not new or any(c in new for c in '<>:"/\\|?*') or new in (".", ".."):
            raise ValueError("недопустимое имя")
        ext = os.path.splitext(old)[1]
        if item_label(old) != old and not new.lower().endswith(ext.lower()):
            new += ext
        base = self.cur(f)
        if new != old and os.path.exists(os.path.join(base, new)):
            raise ValueError("такое имя уже есть")
        os.rename(os.path.join(base, old), os.path.join(base, new))
        self.rescan(f)
        return new

    def new_folder(self, f):
        path = unique_path(self.cur(f), "Новая папка")
        os.makedirs(path)
        self.rescan(f)
        return os.path.basename(path)

    def paste(self, f, paths, cut):
        """Вставить файлы (из буфера обмена) в открытую папку области. -> сколько вставлено."""
        n = 0
        for p in paths:
            if not os.path.exists(p):
                continue
            dst = unique_path(self.cur(f), os.path.basename(p)) if not cut else \
                unique_path(self.cur(f), os.path.basename(p))
            try:
                if cut:
                    shutil.move(p, dst)
                elif os.path.isdir(p):
                    shutil.copytree(p, dst)
                else:
                    shutil.copy2(p, dst)
                n += 1
            except (OSError, shutil.Error):
                log("paste failed %r:\n%s" % (p, traceback.format_exc()))
        self.rescan(f)
        return n

    def release_all(self, f):
        self.cwd[f["id"]] = ""
        n = 0
        for it in list(self.items(f)):
            if it.get("up"):
                continue
            try:
                self.release_item(f, it["name"])
                n += 1
            except (OSError, shutil.Error):
                log("release failed:\n" + traceback.format_exc())
        return n

    def place_pending(self):
        """Поставить вернувшиеся значки туда, куда их бросили (Explorer добавляет их с задержкой)."""
        if not self.pending:
            return
        by = {i["name"]: i for i in self.dt.snapshot()}
        cw, ch = self.dt.spacing()
        keep = []
        for p in self.pending:
            ic = by.get(p["label"])
            if ic is not None:
                self.dt.set_pos(ic["idx"], max(0, p["x"] - cw // 2), max(0, p["y"] - ch // 2))
            elif time.time() - p["t"] < 15:
                keep.append(p)
        self.pending = keep

    def collapse(self, f):
        f["collapsed"] = True

    def expand(self, f):
        f["collapsed"] = False

    # --- панель быстрого доступа -------------------------------------------------
    def add_to_dock(self, path):
        """Добавить программу / файл / папку на панель (ярлыком). -> имя ярлыка."""
        dock = self.cfg["dock"]
        dst_dir = self.folder(dock)
        base = os.path.basename(path.rstrip("\\/")) or "Ярлык"
        if base.lower().endswith((".lnk", ".url")):
            dst = unique_path(dst_dir, base)
            shutil.copy2(path, dst)
        else:
            dst = unique_path(dst_dir, os.path.splitext(base)[0] + ".lnk")
            make_shortcut(path, dst)
        self.rescan(dock)
        return os.path.basename(dst)

    # --- список дел ------------------------------------------------------------------
    def add_task(self, text):
        text = text.strip()
        if text:
            self.cfg["todo"].append({"t": text, "d": False, "id": uuid.uuid4().hex[:8], "pomos": 0})
        return bool(text)

    def toggle_task(self, i):
        t = self.cfg["todo"]
        if 0 <= i < len(t):
            t[i]["d"] = not t[i].get("d")

    def delete_task(self, i):
        t = self.cfg["todo"]
        if 0 <= i < len(t):
            del t[i]

    def edit_task(self, i, text):
        t = self.cfg["todo"]
        if 0 <= i < len(t) and text.strip():
            t[i]["t"] = text.strip()

    def move_task(self, i, delta):
        t = self.cfg["todo"]
        j = i + delta
        if 0 <= i < len(t) and 0 <= j < len(t):
            t[i], t[j] = t[j], t[i]

    def clear_done(self):
        self.cfg["todo"] = [t for t in self.cfg["todo"] if not t.get("d")]

    def migrate_legacy(self):
        """Старые версии хранили имена значков в members: перенести эти файлы в папки."""
        n = 0
        for f in self.fences:
            for label in f.get("members") or []:
                if self.claim(f, label):
                    n += 1
            f["members"] = []
        return n

    @staticmethod
    def _match(name, patterns):
        low = name.lower()
        for p in patterns:
            p = p.strip().lower()
            if not p:
                continue
            if not any(ch in p for ch in "*?["):
                p = "*" + p + "*"
            if fnmatch.fnmatch(low, p):
                return True
        return False

    def tidy_by_rules(self):
        """Переложить значки рабочего стола в области по правилам (маскам имён)."""
        count = 0
        for ic in self.dt.snapshot():
            for f in self.areas():
                if self._match(ic["name"], f.get("rules", [])):
                    if self.claim(f, ic["name"]):
                        count += 1
                    break
        return count
# ----------------------------------------------------------------------------
# Жесты мыши над областями (без Tk и Windows - поэтому проверяется тестами)
# ----------------------------------------------------------------------------
def find_zone(zones, x, y):
    for z in zones:
        if z[2] <= x < z[4] and z[3] <= y < z[5]:
            return z
    return None


class Interaction(object):
    """Состояние перетаскивания области / значка, растягивания, нажатия на кнопки."""

    def __init__(self, cfg, engine, desktop):
        self.cfg, self.eng, self.dt = cfg, engine, desktop
        self.drag = None
        self.bounds = None                     # (ширина, высота) виртуального экрана
        self.last_click = None                 # для двойного клика по значку

    def zones(self):
        """Горячие зоны: (вид, область, x1, y1, x2, y2[, имя / действие]); верхние - первыми."""
        zs = []
        for f in reversed(self.cfg["fences"]):
            kind = f.get("kind", "files")
            x, y, w = f["x"], f["y"], f["w"]
            zs.append(("menu", f, x + w - TITLE_H, y, x + w, y + TITLE_H))
            zs.append(("palette", f, x + w - 2 * TITLE_H, y, x + w - TITLE_H, y + TITLE_H))
            zs.append(("collapse", f, x, y, x + TITLE_H, y + TITLE_H))
            zs.append(("title", f, x, y, x + w, y + TITLE_H))
            if f.get("collapsed"):
                continue
            if kind in ("files", "note"):
                zs.append(("grip", f, x + w - GRIP, y + f["h"] - GRIP, x + w, y + f["h"]))
            if kind == "files":
                for k, it in enumerate(self.eng.items(f)):
                    ix, iy = self.eng.slot(f, k)
                    cw, ch = self.eng.cell(f)
                    zs.append(("item", f, x + ix, y + iy, x + ix + cw, y + iy + ch, it["name"]))
            elif kind == "calendar":
                lay = cal_layout(f)
                for nm, act in (("prev", "prev"), ("next", "next"), ("label", "today")):
                    r = lay[nm]
                    zs.append(("wact", f, x + r[0], y + r[1], x + r[2], y + r[3], ("cal", act)))
                for ri, week in enumerate(month_grid(f["cal_y"], f["cal_m"], int(f.get("first_weekday", 0)))):
                    for ci, day in enumerate(week):
                        cx1, cy1 = x + lay["gx"] + ci * lay["cw"], y + lay["gy"] + ri * lay["ch"]
                        zs.append(("wact", f, cx1, cy1, cx1 + lay["cw"], cy1 + lay["ch"], ("cal", "day", day.isoformat())))
            elif kind == "note":
                zs.append(("wact", f, x, y + TITLE_H, x + w, y + f["h"] - GRIP, ("note", "edit")))
            elif kind == "timer":
                lay = timer_layout(f)
                for key, r in lay["tabs"].items():
                    zs.append(("wact", f, x + r[0], y + r[1], x + r[2], y + r[3], ("timer", "mode", key)))
                r = lay["task"]
                zs.append(("wact", f, x + r[0], y + r[1], x + r[2], y + r[3], ("timer", "task")))
                for key, r in lay["btn"].items():
                    zs.append(("wact", f, x + r[0], y + r[1], x + r[2], y + r[3], ("timer", key)))
                r = lay["ring"]
                zs.append(("wact", f, x + r[0], y + r[1], x + r[2], y + r[3], ("timer", "toggle")))
            elif kind == "clipboard":
                lay = clip_layout(f, min(len(self.cfg["clip"]["pins"]) + len(self.cfg["clip"]["items"]),
                                         int(f.get("rows", 8))))
                r = lay["head"]
                zs.append(("wact", f, x + r[0], y + r[1], x + r[2], y + r[3], ("clip", "clear")))
                for i, row, pin, dele in lay["rows"]:
                    zs.append(("wact", f, x + dele[0], y + dele[1], x + dele[2], y + dele[3], ("clip", "del", i)))
                    zs.append(("wact", f, x + pin[0], y + pin[1], x + pin[2], y + pin[3], ("clip", "pin", i)))
                    zs.append(("wact", f, x + row[0], y + row[1], x + row[2], y + row[3], ("clip", "copy", i)))
            elif kind == "search":
                r = search_layout(f)
                zs.append(("wact", f, x + r[0], y + r[1], x + r[2], y + r[3], ("search", "open")))
            elif kind == "todo":
                lay = todo_layout(f, len(self.cfg.get("todo", [])))
                r = lay["add"]
                zs.append(("wact", f, x + r[0], y + r[1], x + r[2], y + r[3], ("todo", "add")))
                for i, row, chk, dele in lay["rows"]:
                    zs.append(("wact", f, x + dele[0], y + dele[1], x + dele[2], y + dele[3], ("todo", "del", i)))
                    zs.append(("wact", f, x + row[0], y + row[1], x + row[2], y + row[3], ("todo", "toggle", i)))
            zs.append(("body", f, x, y + TITLE_H, x + w, y + f["h"]))
        d = self.cfg.get("dock")
        if d and d.get("on") and d.get("w"):
            names = [it["name"] for it in self.eng.items(d)]
            rects, add = dock_rects(d, len(names))
            for nm, r in zip(names, rects):
                zs.append(("dockitem", d, d["x"] + r[0], d["y"] + r[1], d["x"] + r[2], d["y"] + r[3], nm))
            zs.append(("dockadd", d, d["x"] + add[0], d["y"] + add[1], d["x"] + add[2], d["y"] + add[3]))
            zs.append(("dockbody", d, d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"]))
        return zs

    def fence_at(self, x, y):
        """Развёрнутая область (или панель) под точкой (координаты стола) или None."""
        for f in reversed(self.eng.areas()):
            if f.get("collapsed"):
                continue
            if f["x"] <= x < f["x"] + f["w"] and f["y"] <= y < f["y"] + f["h"]:
                return f
        return None

    def press(self, kind, f, x, y, name=None):
        try:
            self.eng.sync()                    # зафиксировать состав области до жеста
        except Exception:
            log("press sync failed:\n" + traceback.format_exc())
        gm = group_members(self.cfg, f.get("group"))
        off = (f["x"] - gm[0]["x"], f["y"] - gm[0]["y"]) if len(gm) > 1 else None
        self.drag = {"kind": kind, "f": f, "sx": x, "sy": y, "fx": f["x"], "fy": f["y"],
                     "fw": f["w"], "fh": f["h"], "moved": False, "name": name, "off": off}

    def move(self, x, y):
        """-> True, если изменилась геометрия области; "item" - тянут значок."""
        d = self.drag
        if not d:
            return False
        dx, dy = x - d["sx"], y - d["sy"]
        if not d["moved"] and abs(dx) <= 4 and abs(dy) <= 4:
            return False
        d["moved"] = True
        f = d["f"]
        if d["kind"] == "title":
            nx, ny = max(0, d["fx"] + dx), max(0, d["fy"] + dy)
            if self.bounds:                    # не дальше края виртуального экрана
                nx = min(nx, max(0, self.bounds[0] - MIN_W))
                ny = min(ny, max(0, self.bounds[1] - TITLE_H))
            if d.get("off"):                   # группа ездит целиком: якорь = первая область
                lead = group_members(self.cfg, f.get("group"))[0]
                lead["x"], lead["y"] = max(0, nx - d["off"][0]), max(0, ny - d["off"][1])
                layout_groups(self.cfg)
                if lead is not f:
                    return True
                return True
            f["x"], f["y"] = nx, ny
            return True
        if d["kind"] == "grip":
            f["w"] = max(MIN_W, d["fw"] + dx)
            f["h"] = max(MIN_H, d["fh"] + dy, self.eng.need_h(f) if f.get("kind", "files") == "files" else 0)
            return True
        if d["kind"] == "item":
            return "item" if d["name"] != ".." else False
        return False

    def release(self, x, y, now=None):
        """-> действие для интерфейса или None."""
        d, self.drag = self.drag, None
        if not d:
            return None
        f, kind, moved = d["f"], d["kind"], d["moved"]
        if kind == "collapse" and not moved:
            return ("toggle", f)
        if kind == "palette" and not moved:
            return ("palette", f, x, y)
        if kind == "menu" and not moved:
            return ("menu", f, x, y)
        if kind in ("wact", "dockitem") and not moved:
            return (kind, f, d["name"])
        if kind == "dockadd" and not moved:
            return ("dockadd", f)
        if kind == "item":
            if moved:
                self.last_click = None
                return ("drop", f, d["name"], x, y)
            now = time.time() if now is None else now
            lc = self.last_click
            if lc and lc[0] is f and lc[1] == d["name"] and now - lc[2] < 0.5:
                self.last_click = None
                return ("open", f, d["name"])
            self.last_click = (f, d["name"], now)
            return ("select", f, d["name"])
        if kind in ("title", "grip") and moved:
            return ("moved" if kind == "title" else "resized", f, x, y)
        return None


# ----------------------------------------------------------------------------
# Windows: доступ к значкам рабочего стола, «приклеивание» окон к обоям, мышь
# ----------------------------------------------------------------------------
if IS_WIN:
    import ctypes
    from ctypes import wintypes as wt

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    LRESULT = ctypes.c_ssize_t

    user32.SendMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.SendMessageW.restype = LRESULT
    user32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT,
                                           wt.UINT, ctypes.POINTER(ctypes.c_ssize_t)]
    user32.SendMessageTimeoutW.restype = LRESULT
    user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
    user32.FindWindowW.restype = wt.HWND
    user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
    user32.FindWindowExW.restype = wt.HWND
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
    user32.GetAncestor.restype = wt.HWND
    user32.GetParent.argtypes = [wt.HWND]
    user32.GetParent.restype = wt.HWND
    user32.SetParent.argtypes = [wt.HWND, wt.HWND]
    user32.SetParent.restype = wt.HWND
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.SetWindowPos.restype = wt.BOOL
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.RegisterHotKey.argtypes = [wt.HWND, ctypes.c_int, wt.UINT, wt.UINT]
    user32.RegisterHotKey.restype = wt.BOOL
    user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    user32.GetMessageW.restype = ctypes.c_int
    user32.WindowFromPoint.argtypes = [wt.POINT]
    user32.WindowFromPoint.restype = wt.HWND
    user32.ScreenToClient.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
    user32.ScreenToClient.restype = wt.BOOL
    WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
    user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
    user32.SetWindowsHookExW.restype = ctypes.c_void_p
    user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
    user32.CallNextHookEx.restype = LRESULT

    _get_long = getattr(user32, "GetWindowLongPtrW", None) or user32.GetWindowLongW
    _set_long = getattr(user32, "SetWindowLongPtrW", None) or user32.SetWindowLongW
    _get_long.argtypes = [wt.HWND, ctypes.c_int]
    _get_long.restype = ctypes.c_ssize_t
    _set_long.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _set_long.restype = ctypes.c_ssize_t

    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                        wt.DWORD, wt.DWORD]
    kernel32.VirtualAllocEx.restype = ctypes.c_void_p
    kernel32.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
    kernel32.VirtualFreeEx.restype = wt.BOOL
    kernel32.WriteProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.c_size_t, ctypes.c_void_p]
    kernel32.WriteProcessMemory.restype = wt.BOOL
    kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
                                           ctypes.c_size_t, ctypes.c_void_p]
    kernel32.ReadProcessMemory.restype = wt.BOOL
    kernel32.CloseHandle.argtypes = [wt.HANDLE]

    GWL_STYLE, GWL_EXSTYLE = -16, -20
    WS_POPUP, WS_CHILD, WS_VISIBLE = 0x80000000, 0x40000000, 0x10000000
    WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE, WS_EX_APPWINDOW = 0x80, 0x08000000, 0x40000
    SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x04, 0x10, 0x20, 0x40
    HWND_TOP, HWND_BOTTOM, HWND_TOPMOST = 0, 1, -1
    LVS_AUTOARRANGE = 0x0100
    LVS_EX_SNAPTOGRID = 0x00080000
    LVM_GETITEMCOUNT, LVM_GETITEMSPACING = 0x1004, 0x1033
    LVM_SETITEMPOSITION, LVM_GETITEMPOSITION = 0x100F, 0x1010
    LVM_GETITEMTEXTW, LVM_SETEXTENDEDLISTVIEWSTYLE = 0x1073, 0x1036
    LVM_HITTEST = 0x1012
    WM_MOUSEMOVE, WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0200, 0x0201, 0x0202
    WM_RBUTTONDOWN, WM_RBUTTONUP = 0x0204, 0x0205

    class LVITEMW(ctypes.Structure):
        _fields_ = [("mask", wt.UINT), ("iItem", ctypes.c_int), ("iSubItem", ctypes.c_int),
                    ("state", wt.UINT), ("stateMask", wt.UINT),
                    ("pszText", ctypes.c_void_p), ("cchTextMax", ctypes.c_int),
                    ("iImage", ctypes.c_int), ("lParam", wt.LPARAM),
                    ("iIndent", ctypes.c_int), ("iGroupId", ctypes.c_int),
                    ("cColumns", wt.UINT), ("puColumns", ctypes.c_void_p),
                    ("piColFmt", ctypes.c_void_p), ("iGroup", ctypes.c_int)]

    class MSLLHOOKSTRUCT(ctypes.Structure):
        _fields_ = [("pt", wt.POINT), ("mouseData", wt.DWORD), ("flags", wt.DWORD),
                    ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]

    def virtual_metrics():
        """(x, y, ширина, высота) виртуального экрана: все мониторы вместе."""
        return (user32.GetSystemMetrics(76), user32.GetSystemMetrics(77),
                user32.GetSystemMetrics(78), user32.GetSystemMetrics(79))

    def class_name(hwnd):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def _enum_top_windows():
        found = []

        def cb(h, _l):
            found.append(h)
            return True
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return found

    def find_defview():
        """-> (defview_hwnd, host_hwnd, in_progman)"""
        progman = user32.FindWindowW("Progman", None)
        dv = user32.FindWindowExW(progman, None, "SHELLDLL_DefView", None) if progman else None
        if dv:
            return dv, progman, True
        for h in _enum_top_windows():
            if class_name(h) == "WorkerW":
                dv = user32.FindWindowExW(h, None, "SHELLDLL_DefView", None)
                if dv:
                    return dv, h, False
        return None, None, False

    def parent_strategies():
        """Способы показать области. Каждый возвращает (вид, родитель, после_кого) или None.
        вид "child" - дочернее окно рабочего стола ЗА значками;
        вид "overlay" - запасной: прозрачное для мыши окно чуть выше рабочего стола."""
        def progman():
            return user32.FindWindowW("Progman", None)

        def wall_child():                      # Windows 11 24H2: слой обоев - WorkerW внутри Progman
            p = progman()
            w = user32.FindWindowExW(p, None, "WorkerW", None) if p else None
            return ("child", w, HWND_TOP) if w else None

        def above_wallpaper():
            dv, host, in_prog = find_defview()
            if not in_prog:
                return None
            wall = user32.FindWindowExW(host, None, "WorkerW", None)
            return ("child", host, wall) if wall else None

        def progman_bottom():
            p = progman()
            return ("child", p, HWND_BOTTOM) if p else None

        def behind_workerw():                  # классика: WorkerW за слоем значков
            dv, host, in_prog = find_defview()
            if in_prog or not host:
                return None
            b = user32.FindWindowExW(None, host, "WorkerW", None)
            return ("child", b, HWND_TOP) if b else None

        def after_052c():                      # как делают программы живых обоев
            p = progman()
            if not p:
                return None
            res = ctypes.c_ssize_t(0)
            user32.SendMessageTimeoutW(p, 0x052C, 0xD, 0x1, 0, 1000, ctypes.byref(res))
            user32.SendMessageTimeoutW(p, 0x052C, 0xD, 0x0, 0, 1000, ctypes.byref(res))
            return behind_workerw()

        def overlay():
            dv, host, _in = find_defview()
            return ("overlay", None, host) if host else None

        return [("Дочерний слой обоев (WorkerW в Progman)", wall_child),
                ("Progman, над обоями", above_wallpaper),
                ("Progman, внизу", progman_bottom),
                ("WorkerW за значками", behind_workerw),
                ("WorkerW после служебного сообщения", after_052c),
                ("Запасной: поверх рабочего стола, мышь проходит насквозь", overlay)]

    class DesktopListView(object):
        """Чтение имён и позиций значков рабочего стола (через память Explorer)."""

        def __init__(self):
            dv, _host, _p = find_defview()
            if not dv:
                raise RuntimeError("Не найден рабочий стол. Включите: ПКМ по рабочему столу "
                                   "→ Вид → Отображать значки рабочего стола.")
            self.hwnd = user32.FindWindowExW(dv, None, "SysListView32", None)
            if not self.hwnd:
                raise RuntimeError("Не найден список значков (SysListView32)")
            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(self.hwnd, ctypes.byref(pid))
            self.proc = kernel32.OpenProcess(0x0008 | 0x0010 | 0x0020 | 0x0400, False, pid.value)
            if not self.proc:
                raise RuntimeError("Нет доступа к процессу Explorer (WinError %d). "
                                   "Запускайте от того же пользователя, без прав админа."
                                   % ctypes.get_last_error())
            self.remote = kernel32.VirtualAllocEx(self.proc, None, 4096, 0x3000, 0x04)
            if not self.remote:
                raise RuntimeError("Не удалось выделить память в Explorer. Нужен 64-битный Python.")
            self._item = LVITEMW()

        def show_icons(self, on):
            try:
                user32.ShowWindow(self.hwnd, 5 if on else 0)       # SW_SHOW / SW_HIDE
            except Exception:
                log("show_icons failed:\n" + traceback.format_exc())

        def close(self):
            try:
                kernel32.VirtualFreeEx(self.proc, self.remote, 0, 0x8000)
                kernel32.CloseHandle(self.proc)
            except Exception:
                pass

        def prepare(self):
            """Выключить авто-расположение и привязку к сетке, чтобы позиции слушались."""
            style = _get_long(self.hwnd, GWL_STYLE)
            if style & LVS_AUTOARRANGE:
                _set_long(self.hwnd, GWL_STYLE, style & ~LVS_AUTOARRANGE)
            user32.SendMessageW(self.hwnd, LVM_SETEXTENDEDLISTVIEWSTYLE, LVS_EX_SNAPTOGRID, 0)
            return not (_get_long(self.hwnd, GWL_STYLE) & LVS_AUTOARRANGE)

        def spacing(self):
            v = user32.SendMessageW(self.hwnd, LVM_GETITEMSPACING, 0, 0)
            cw, ch = v & 0xFFFF, (v >> 16) & 0xFFFF
            return (cw, ch) if cw > 20 and ch > 20 else (80, 100)

        def _name(self, i):
            item = self._item
            item.mask, item.iItem, item.iSubItem = 1, i, 0
            item.pszText = self.remote + 256
            item.cchTextMax = 255
            kernel32.WriteProcessMemory(self.proc, self.remote, ctypes.byref(item),
                                        ctypes.sizeof(item), None)
            user32.SendMessageW(self.hwnd, LVM_GETITEMTEXTW, i, self.remote)
            buf = ctypes.create_unicode_buffer(256)
            kernel32.ReadProcessMemory(self.proc, self.remote + 256, buf, 510, None)
            return buf.value

        def _pos(self, i):
            user32.SendMessageW(self.hwnd, LVM_GETITEMPOSITION, i, self.remote + 1024)
            pt = wt.POINT()
            kernel32.ReadProcessMemory(self.proc, self.remote + 1024, ctypes.byref(pt),
                                       ctypes.sizeof(pt), None)
            return pt.x, pt.y

        def snapshot(self):
            n = user32.SendMessageW(self.hwnd, LVM_GETITEMCOUNT, 0, 0)
            out = []
            for i in range(n):
                x, y = self._pos(i)
                out.append({"idx": i, "name": self._name(i), "x": x, "y": y})
            return out

        def set_pos(self, idx, x, y):
            x = max(-32768, min(32767, int(x)))
            y = max(-32768, min(32767, int(y)))
            user32.SendMessageW(self.hwnd, LVM_SETITEMPOSITION, idx,
                                (y & 0xFFFF) << 16 | (x & 0xFFFF))

        def origin(self):
            """Экранные координаты точки (0,0) списка значков - начало системы значков."""
            pt = wt.POINT(0, 0)
            user32.ClientToScreen(self.hwnd, ctypes.byref(pt))
            return pt.x, pt.y

        def is_desktop_point(self, x, y):
            """Под курсором именно рабочий стол (а не окно программы)?"""
            h = user32.WindowFromPoint(wt.POINT(int(x), int(y)))
            if not h:
                return False
            return class_name(user32.GetAncestor(h, 2)) in ("Progman", "WorkerW")

        def window_at(self, x, y):
            """(класс, заголовок) окна верхнего уровня под точкой - для диагностики."""
            h = user32.WindowFromPoint(wt.POINT(int(x), int(y)))
            if not h:
                return ("-", "")
            root = user32.GetAncestor(h, 2)
            buf = ctypes.create_unicode_buffer(128)
            user32.GetWindowTextW(root, buf, 128)
            return (class_name(root), buf.value)

        def hit_icon(self, x, y):
            """Попадает ли точка (экранные координаты) в какой-либо значок?"""
            pt = wt.POINT(int(x), int(y))
            user32.ScreenToClient(self.hwnd, ctypes.byref(pt))
            info = (ctypes.c_int * 6)(pt.x, pt.y, 0, -1, 0, -1)    # POINT, flags, item, sub, group
            kernel32.WriteProcessMemory(self.proc, self.remote + 2048, info,
                                        ctypes.sizeof(info), None)
            res = ctypes.c_ssize_t(-1)
            ok = user32.SendMessageTimeoutW(self.hwnd, LVM_HITTEST, 0, self.remote + 2048,
                                            2, 150, ctypes.byref(res))      # 2 = ABORTIFHUNG
            return True if not ok else res.value >= 0

    class InputEvents(object):
        """Передаёт события из потока перехвата мыши в основной поток (Tk)."""

        def __init__(self):
            self.edit = threading.Event()       # Ctrl+Alt+F - панель
            self.all = threading.Event()        # Ctrl+Alt+G - свернуть / развернуть все
            self.search = threading.Event()     # горячая клавиша поиска
            self.kbd = threading.Event()        # Ctrl+Alt+K - клавиатурный режим вкл / выкл
            self.kbd_on = False                 # режим включён: хук забирает стрелки, Enter, Esc...
            self.hotkey = None                  # (модификаторы, код клавиши) поиска или None
            self.dbl_on = False                 # следить за двойным кликом по пустому столу
            self.q = collections.deque()
            self.zones = ()                     # горячие зоны (обновляет основной поток)
            self.popup = None                   # прямоугольник открытого меню
            self.rects = ()                     # окна областей (экранные координаты) - для подсветки
            self.validate = lambda x, y: False  # «это пустое место рабочего стола?»

    def start_input_thread(ev):
        """Один поток: горячие клавиши + низкоуровневый хук мыши. Хук не блокирует
        мышь, кроме нажатий на заголовки/кнопки областей на рабочем столе."""
        def run():
            mods = 0x0001 | 0x0002 | 0x4000      # Alt + Ctrl + NOREPEAT
            if not user32.RegisterHotKey(None, 1, mods, HOTKEY_VK):
                log("RegisterHotKey F failed: %d" % ctypes.get_last_error())
            if not user32.RegisterHotKey(None, 2, mods, HOTKEY_ALL_VK):
                log("RegisterHotKey G failed: %d" % ctypes.get_last_error())
            if not user32.RegisterHotKey(None, 4, mods, HOTKEY_KBD_VK):
                log("RegisterHotKey K failed: %d" % ctypes.get_last_error())
            if ev.hotkey and not user32.RegisterHotKey(None, 3, ev.hotkey[0], ev.hotkey[1]):
                log("RegisterHotKey search failed: %d" % ctypes.get_last_error())
            st = {"press": False, "t": 0.0, "rsw": False, "hov": False, "lc": (0.0, 0, 0)}
            try:
                create_tray(ev)
            except Exception:
                log("create_tray failed:\n" + traceback.format_exc())

            def proc(n_code, w_param, l_param):
                try:
                    if n_code >= 0:
                        ms = ctypes.cast(l_param, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                        x, y = ms.pt.x, ms.pt.y
                        if w_param == WM_MOUSEMOVE:
                            if st["press"]:
                                if ev.q and ev.q[-1][0] == "move":
                                    ev.q[-1] = ("move", x, y)
                                else:
                                    ev.q.append(("move", x, y))
                            else:                                  # наведение: только над окнами областей
                                inside = False
                                for r in ev.rects:
                                    if r[0] <= x < r[2] and r[1] <= y < r[3]:
                                        inside = True
                                        break
                                if inside or st["hov"]:
                                    if ev.q and ev.q[-1][0] == "hover":
                                        ev.q[-1] = ("hover", x, y)
                                    else:
                                        ev.q.append(("hover", x, y))
                                    st["hov"] = inside
                        elif w_param == WM_LBUTTONDOWN:
                            if st["press"] and time.time() - st["t"] > 20:
                                st["press"] = False                # потеряли отпускание
                            p = ev.popup
                            if p and not (p[0] <= x < p[2] and p[1] <= y < p[3]):
                                ev.q.append(("dismiss",))
                            z = find_zone(ev.zones, x, y)
                            if z and not st["press"] and ev.validate(x, y):
                                st["press"], st["t"] = True, time.time()
                                ev.q.append(("press", z, x, y))
                                return 1                           # не отдавать клик рабочему столу
                            if not z and ev.dbl_on:                # двойной клик по пустому месту
                                now = time.time()
                                t0, x0, y0 = st["lc"]
                                if now - t0 <= user32.GetDoubleClickTime() / 1000.0 and \
                                        abs(x - x0) <= 6 and abs(y - y0) <= 6:
                                    st["lc"] = (0.0, 0, 0)
                                    ev.q.append(("dblclick", x, y))
                                else:
                                    st["lc"] = (now, x, y)
                        elif w_param == WM_LBUTTONUP and st["press"]:
                            st["press"] = False
                            ev.q.append(("release", x, y))
                            return 1
                        elif w_param == WM_RBUTTONDOWN:
                            z = find_zone(ev.zones, x, y)
                            if z and z[0] != "grip" and ev.validate(x, y):
                                st["rsw"] = True
                                ev.q.append(("rclick", z, x, y))
                                return 1
                        elif w_param == WM_RBUTTONUP and st["rsw"]:
                            st["rsw"] = False
                            return 1
                except Exception:
                    pass
                return user32.CallNextHookEx(None, n_code, w_param, l_param)

            KEYS = {0x25, 0x26, 0x27, 0x28, 0x09, 0x0D, 0x1B, 0x20, 0x2E, 0x71, 0x08, 0x43, 0x58, 0x56, 0x41}

            def kproc(n_code, w_param, l_param):
                try:
                    if n_code == 0 and ev.kbd_on and w_param in (0x0100, 0x0104):    # WM_KEYDOWN
                        vk = ctypes.cast(l_param, ctypes.POINTER(ctypes.c_uint32))[0]
                        ctrl = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
                        if vk in KEYS and (not ctrl or vk in (0x43, 0x58, 0x56, 0x41)):
                            if vk in (0x43, 0x58, 0x56, 0x41) and not ctrl:
                                return user32.CallNextHookEx(None, n_code, w_param, l_param)
                            ev.q.append(("key", vk, ctrl, bool(user32.GetAsyncKeyState(0x10) & 0x8000)))
                            return 1
                except Exception:
                    pass
                return user32.CallNextHookEx(None, n_code, w_param, l_param)

            kcb = HOOKPROC(kproc)
            khook = user32.SetWindowsHookExW(13, kcb, kernel32.GetModuleHandleW(None), 0)   # WH_KEYBOARD_LL
            if not khook:
                log("Keyboard hook failed: %d" % ctypes.get_last_error())
            cb = HOOKPROC(proc)                  # держим ссылку, иначе хук умрёт
            hook = user32.SetWindowsHookExW(14, cb, kernel32.GetModuleHandleW(None), 0)   # WH_MOUSE_LL
            if not hook:
                log("SetWindowsHookEx failed: %d" % ctypes.get_last_error())
            msg = wt.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message == 0x0312:        # WM_HOTKEY
                    (ev.edit if msg.wParam == 1 else (ev.all if msg.wParam == 2 else
                                                      (ev.kbd if msg.wParam == 4 else ev.search))).set()
                else:
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))     # сообщения значка в трее
        threading.Thread(target=run, daemon=True).start()

    # ---- свои окна (Win32 + GDI), без Tk ------------------------------------------
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    HGDI = ctypes.c_void_p
    user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD,
                                       ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                       wt.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    user32.CreateWindowExW.restype = wt.HWND
    user32.DestroyWindow.argtypes = [wt.HWND]
    user32.DestroyWindow.restype = wt.BOOL
    user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.BeginPaint.argtypes = [wt.HWND, ctypes.c_void_p]
    user32.BeginPaint.restype = HGDI
    user32.EndPaint.argtypes = [wt.HWND, ctypes.c_void_p]
    user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.InvalidateRect.argtypes = [wt.HWND, ctypes.c_void_p, wt.BOOL]
    user32.FillRect.argtypes = [HGDI, ctypes.POINTER(wt.RECT), HGDI]
    user32.DrawTextW.argtypes = [HGDI, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.RECT), wt.UINT]
    user32.SetLayeredWindowAttributes.argtypes = [wt.HWND, wt.DWORD, ctypes.c_ubyte, wt.DWORD]
    user32.SetLayeredWindowAttributes.restype = wt.BOOL
    user32.GetDC.argtypes = [wt.HWND]
    user32.GetDC.restype = HGDI
    user32.ReleaseDC.argtypes = [wt.HWND, HGDI]
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetDoubleClickTime.restype = wt.UINT
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.LoadCursorW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.LoadCursorW.restype = ctypes.c_void_p
    user32.RegisterClassW.restype = wt.ATOM
    kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    kernel32.GetModuleHandleW.restype = ctypes.c_void_p
    gdi32.CreateSolidBrush.argtypes = [wt.DWORD]
    gdi32.CreateSolidBrush.restype = HGDI
    gdi32.DeleteObject.argtypes = [HGDI]
    gdi32.SelectObject.argtypes = [HGDI, HGDI]
    gdi32.SelectObject.restype = HGDI
    gdi32.SetBkMode.argtypes = [HGDI, ctypes.c_int]
    gdi32.SetTextColor.argtypes = [HGDI, wt.DWORD]
    gdi32.GetPixel.argtypes = [HGDI, ctypes.c_int, ctypes.c_int]
    gdi32.GetPixel.restype = wt.DWORD
    gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wt.DWORD] * 8 + [wt.LPCWSTR]
    gdi32.CreateFontW.restype = HGDI

    WS_CLIPSIBLINGS, WS_EX_LAYERED, WS_EX_TRANSPARENT = 0x04000000, 0x00080000, 0x00000020
    SWP_NOMOVE, SWP_NOSIZE = 0x02, 0x01
    DT_CENTER, DT_VCENTER, DT_SINGLELINE, DT_NOPREFIX, DT_END_ELLIPSIS = 0x1, 0x4, 0x20, 0x800, 0x8000
    DT_WORDBREAK = 0x10

    class SHFILEINFOW(ctypes.Structure):
        _fields_ = [("hIcon", ctypes.c_void_p), ("iIcon", ctypes.c_int), ("dwAttributes", wt.DWORD),
                    ("szDisplayName", wt.WCHAR * 260), ("szTypeName", wt.WCHAR * 80)]

    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.SHGetFileInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.POINTER(SHFILEINFOW),
                                       wt.UINT, wt.UINT]
    shell32.SHGetFileInfoW.restype = ctypes.c_size_t
    shell32.SHGetImageList.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
    shell32.SHGetImageList.restype = ctypes.c_long
    user32.DrawIconEx.argtypes = [HGDI, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                  ctypes.c_int, ctypes.c_int, wt.UINT, ctypes.c_void_p, wt.UINT]
    user32.DrawIconEx.restype = wt.BOOL
    _icons = {}

    def _jumbo_icon(path, shil):
        """Значок большого размера из системного списка (48 / 256 px); 0 при неудаче."""
        try:
            info = SHFILEINFOW()
            shell32.SHGetFileInfoW(path, 0, ctypes.byref(info), ctypes.sizeof(info),
                                   0x4000 | 0x20)               # SYSICONINDEX | ADDOVERLAYS
            idx = info.iIcon
            iid = (ctypes.c_ubyte * 16)(*uuid.UUID("46EB5926-582E-4017-9FDF-E8998DAA0950").bytes_le)
            ppv = ctypes.c_void_p()
            if shell32.SHGetImageList(shil, ctypes.byref(iid), ctypes.byref(ppv)) != 0 or not ppv:
                return 0
            vtbl = ctypes.cast(ppv, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
            get_icon = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.c_int, wt.UINT,
                                          ctypes.POINTER(ctypes.c_void_p))(vtbl[10])
            hicon = ctypes.c_void_p()
            ov = (idx >> 24) & 0xF
            if get_icon(ppv, idx & 0xFFFFFF, 1 | (ov << 8), ctypes.byref(hicon)) == 0 and hicon:
                return hicon.value
        except Exception:
            log("jumbo icon failed:\n" + traceback.format_exc())
        return 0

    def get_icon(path, size=32):
        """Системный значок файла (со стрелкой у ярлыков); кэшируется."""
        key = (path, 0 if size <= 32 else (2 if size <= 48 else 4))
        h = _icons.get(key)
        if h is None:
            h = _jumbo_icon(path, key[1]) if key[1] else 0
            if not h:
                info = SHFILEINFOW()
                shell32.SHGetFileInfoW(path, 0, ctypes.byref(info), ctypes.sizeof(info),
                                       0x100 | 0x20)            # ICON | ADDOVERLAYS
                h = info.hIcon or 0
            _icons[key] = h
        return h

    def draw_icon(hdc, path, x, y, size=32):
        h = get_icon(path, size)
        if h:
            user32.DrawIconEx(hdc, int(x), int(y), h, size, size, 0, None, 3)    # DI_NORMAL
    WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int), ("hInstance", ctypes.c_void_p),
                    ("hIcon", ctypes.c_void_p), ("hCursor", ctypes.c_void_p),
                    ("hbrBackground", ctypes.c_void_p), ("lpszMenuName", wt.LPCWSTR),
                    ("lpszClassName", wt.LPCWSTR)]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [("hdc", ctypes.c_void_p), ("fErase", wt.BOOL), ("rcPaint", wt.RECT),
                    ("fRestore", wt.BOOL), ("fIncUpdate", wt.BOOL), ("rgb", ctypes.c_byte * 32)]

    def rgb(hexc):
        h = hexc.lstrip("#")
        return int(h[0:2], 16) | int(h[2:4], 16) << 8 | int(h[4:6], 16) << 16

    def g_fill(hdc, x1, y1, x2, y2, hexc):
        br = gdi32.CreateSolidBrush(rgb(hexc))
        rc = wt.RECT(int(x1), int(y1), int(x2), int(y2))
        user32.FillRect(hdc, ctypes.byref(rc), br)
        gdi32.DeleteObject(br)

    _fonts = {}

    def get_font(name, height, bold):
        key = (name, height, bold)
        if key not in _fonts:
            _fonts[key] = gdi32.CreateFontW(height, 0, 0, 0, 700 if bold else 400, 0, 0, 0,
                                            1, 0, 0, 5, 0, name)
        return _fonts[key]

    def g_text(hdc, text, x1, y1, x2, y2, hexc, font, flags):
        gdi32.SetBkMode(hdc, 1)
        gdi32.SetTextColor(hdc, rgb(hexc))
        old = gdi32.SelectObject(hdc, font)
        rc = wt.RECT(int(x1), int(y1), int(x2), int(y2))
        user32.DrawTextW(hdc, text, -1, ctypes.byref(rc), flags)
        gdi32.SelectObject(hdc, old)

    def _wndproc(hwnd, msg, wp, lp):
        try:
            if msg == 0x000F:                                  # WM_PAINT
                ps = PAINTSTRUCT()
                hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                inst = NativeWin.registry.get(hwnd)
                if inst is not None:
                    inst.paints += 1
                if inst is not None and inst.painter is not None:
                    rc = wt.RECT()
                    user32.GetClientRect(hwnd, ctypes.byref(rc))
                    inst.painter(hdc, rc.right, rc.bottom)
                user32.EndPaint(hwnd, ctypes.byref(ps))
                return 0
            if msg == 0x0014:                                  # WM_ERASEBKGND
                return 1
        except Exception:
            log("wndproc failed:\n" + traceback.format_exc())
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    _WNDPROC_REF = WNDPROC(_wndproc)                           # ссылка, чтобы не собрал GC

    # ---- приём файлов, перетащенных из других программ (OLE drag & drop) -------------
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    ole32.OleInitialize.argtypes = [ctypes.c_void_p]
    ole32.RegisterDragDrop.argtypes = [wt.HWND, ctypes.c_void_p]
    ole32.RevokeDragDrop.argtypes = [wt.HWND]
    ole32.ReleaseStgMedium.argtypes = [ctypes.c_void_p]
    shell32.DragQueryFileW.argtypes = [ctypes.c_void_p, wt.UINT, wt.LPWSTR, wt.UINT]
    shell32.DragQueryFileW.restype = wt.UINT
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short

    class _FORMATETC(ctypes.Structure):
        _fields_ = [("cf", ctypes.c_ushort), ("ptd", ctypes.c_void_p), ("aspect", wt.DWORD),
                    ("lindex", ctypes.c_long), ("tymed", wt.DWORD)]

    class _STGMEDIUM(ctypes.Structure):
        _fields_ = [("tymed", wt.DWORD), ("h", ctypes.c_void_p), ("unk", ctypes.c_void_p)]

    class _GUID(ctypes.Structure):
        _fields_ = [("d1", ctypes.c_ulong), ("d2", ctypes.c_ushort), ("d3", ctypes.c_ushort),
                    ("d4", ctypes.c_ubyte * 8)]

    def _guid_bytes(g):
        return bytes(ctypes.string_at(ctypes.addressof(g), 16))

    def _mk_guid(s):
        import uuid as _u
        return _u.UUID(s).bytes_le

    _OK_IIDS = (_mk_guid("00000000-0000-0000-C000-000000000046"),      # IUnknown
                _mk_guid("00000122-0000-0000-C000-000000000046"))      # IDropTarget

    def data_object_files(pdata):
        """Пути файлов из IDataObject (формат CF_HDROP). -> список строк."""
        vt = ctypes.cast(ctypes.cast(pdata, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        get_data = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(_FORMATETC),
                                      ctypes.POINTER(_STGMEDIUM))(vt[3])
        fmt = _FORMATETC(15, None, 1, -1, 1)           # CF_HDROP, DVASPECT_CONTENT, TYMED_HGLOBAL
        med = _STGMEDIUM()
        if get_data(pdata, ctypes.byref(fmt), ctypes.byref(med)) != 0:
            return []
        out = []
        try:
            n = shell32.DragQueryFileW(med.h, 0xFFFFFFFF, None, 0)
            for i in range(n):
                buf = ctypes.create_unicode_buffer(1024)
                shell32.DragQueryFileW(med.h, i, buf, 1024)
                out.append(buf.value)
        finally:
            ole32.ReleaseStgMedium(ctypes.byref(med))
        return out

    class DropHub(object):
        """Прозрачные «ловцы» над областями. Показываются только пока пользователь тянет
        что-то из окна ДРУГОЙ программы (кнопка мыши зажата, началось не на рабочем столе).
        Сброшенные файлы попадают в очередь events: ("over", fence_id) / ("leave",) /
        ("drop", fence_id, [пути], перемещать?)."""
        CLASS = "KinDeskDrop"

        def __init__(self):
            from collections import deque
            self.events = deque()
            self.catchers = {}                 # id области -> hwnd
            self.rects = {}
            self.shown = None
            self.cur = None
            self.armed = False
            self.t_off = 0.0
            self._refs = []
            self.ok = False
            try:
                ole32.OleInitialize(None)
                wc = WNDCLASSW()
                self._defproc = WNDPROC(("DefWindowProcW", user32))
                wc.lpfnWndProc = self._defproc
                wc.hInstance = kernel32.GetModuleHandleW(None)
                wc.lpszClassName = self.CLASS
                if not user32.RegisterClassW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:
                    raise OSError("RegisterClassW drop: %d" % ctypes.get_last_error())
                self._build_target()
                self.ok = True
            except Exception:
                log("DropHub init failed:\n" + traceback.format_exc())

        # -- COM-объект IDropTarget
        def _build_target(self):
            P = ctypes.c_void_p
            H = ctypes.c_long
            if ctypes.sizeof(P) == 8:
                pt_t = [ctypes.c_longlong]
            else:
                pt_t = [ctypes.c_long, ctypes.c_long]
            PD = ctypes.POINTER(wt.DWORD)
            hub = self

            def qi(this, riid, ppv):
                if bytes(ctypes.string_at(riid, 16)) in _OK_IIDS:
                    ctypes.cast(ppv, ctypes.POINTER(P))[0] = this
                    return 0
                ctypes.cast(ppv, ctypes.POINTER(P))[0] = None
                return -2147467262                     # E_NOINTERFACE

            def addref(this):
                return 2

            def release(this):
                return 1

            def effect(keys, peff):
                peff[0] = 2 if keys & 4 else 1          # Shift - переместить, иначе копировать
                return 0

            def enter(this, pdata, keys, *rest):
                try:
                    hub.cur_data = pdata
                    hub.events.append(("over", hub.cur))
                    return effect(keys, rest[-1])
                except Exception:
                    return -2147467259

            def over(this, keys, *rest):
                try:
                    return effect(keys, rest[-1])
                except Exception:
                    return -2147467259

            def leave(this):
                hub.events.append(("leave",))
                return 0

            def drop(this, pdata, keys, *rest):
                try:
                    paths = data_object_files(pdata)
                    move = bool(keys & 4)
                    if paths and hub.cur:
                        hub.events.append(("drop", hub.cur, paths, move))
                    rest[-1][0] = 2 if move else 1
                    return 0
                except Exception:
                    log("drop failed:\n" + traceback.format_exc())
                    return -2147467259

            T = ctypes.WINFUNCTYPE
            protos = [T(H, P, P, P)(qi), T(wt.ULONG, P)(addref), T(wt.ULONG, P)(release),
                      T(H, *([P, P, wt.DWORD] + pt_t + [PD]))(enter),
                      T(H, *([P, wt.DWORD] + pt_t + [PD]))(over),
                      T(H, P)(leave),
                      T(H, *([P, P, wt.DWORD] + pt_t + [PD]))(drop)]
            self._vtbl = (P * 7)(*[ctypes.cast(fn, P) for fn in protos])
            self._obj = P(ctypes.addressof(self._vtbl))
            self._refs += [protos, self._vtbl, self._obj]
            self.ptr = ctypes.addressof(self._obj)
            self.cur_data = None

        def _catcher(self, fid):
            h = self.catchers.get(fid)
            if h:
                return h
            h = user32.CreateWindowExW(0x08000000 | 0x00000080 | 0x00080000 | 0x00000008, self.CLASS, "", 0x80000000,
                                       0, 0, 10, 10, None, None, kernel32.GetModuleHandleW(None), None)
            # NOACTIVATE | TOOLWINDOW | LAYERED | TOPMOST
            if not h:
                return None
            user32.SetLayeredWindowAttributes(h, 0, 3, 2)           # почти невидим, но ловит мышь
            if ole32.RegisterDragDrop(h, self.ptr) != 0:
                log("RegisterDragDrop failed")
            self.catchers[fid] = h
            return h

        def update(self, targets):
            """targets: {id области: (l, t, r, b) экранные}. Вызывать из poll (~20 мс)."""
            if not self.ok:
                return
            down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
            return down

        def show(self, fid, rect):
            h = self._catcher(fid)
            if not h:
                return
            l, t, r, b = rect
            user32.SetWindowPos(h, -1, int(l), int(t), int(r - l), int(b - t), 0x0010 | 0x0040)   # TOPMOST NOACTIVATE SHOWWINDOW
            self.cur = fid
            self.shown = fid

        def hide(self):
            for h in self.catchers.values():
                user32.ShowWindow(h, 0)
            self.shown = None

        def close(self):
            for h in list(self.catchers.values()):
                try:
                    ole32.RevokeDragDrop(h)
                    user32.DestroyWindow(h)
                except Exception:
                    pass
            self.catchers.clear()


    class NativeWin(object):
        """Окно области: дочернее окно рабочего стола ("child") либо
        прозрачный для мыши верхнеуровневый слой над рабочим столом ("overlay")."""
        registry = {}
        CLASS = "KinDeskWnd"
        _registered = False

        @classmethod
        def _ensure_class(cls):
            if cls._registered:
                return
            wc = WNDCLASSW()
            wc.style = 0x0003                                  # CS_HREDRAW | CS_VREDRAW
            wc.lpfnWndProc = _WNDPROC_REF
            wc.hInstance = kernel32.GetModuleHandleW(None)
            wc.hCursor = user32.LoadCursorW(None, 32512)       # IDC_ARROW
            wc.lpszClassName = cls.CLASS
            if not user32.RegisterClassW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:
                raise OSError("RegisterClassW: %d" % ctypes.get_last_error())
            cls._registered = True

        def __init__(self, spec, x, y, w, h, painter, alpha=None, key=None):
            self._ensure_class()
            self.kind, parent, self.after = spec
            self.painter = painter
            self.paints = 0
            if self.kind == "overlay":         # верхнеуровневому окну нужны экранные координаты
                x, y = x + ORIGIN[0], y + ORIGIN[1]
            ex = WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW
            if self.kind == "overlay":
                style, par = WS_POPUP, None
                ex |= WS_EX_LAYERED | WS_EX_TRANSPARENT
                if alpha is None:
                    alpha = 1.0
            else:
                style, par = WS_CHILD | WS_CLIPSIBLINGS, parent
                if alpha is not None or key is not None:
                    ex |= WS_EX_LAYERED
            self.hwnd = user32.CreateWindowExW(ex, self.CLASS, "KinDesk", style,
                                               int(x), int(y), int(w), int(h), par, None,
                                               kernel32.GetModuleHandleW(None), None)
            if not self.hwnd:
                raise OSError("CreateWindowExW: %d" % ctypes.get_last_error())
            NativeWin.registry[self.hwnd] = self
            if key is not None:                # цвет фона области = «прозрачный»
                if not user32.SetLayeredWindowAttributes(self.hwnd, rgb(key), 255, 3):
                    log("SetLayeredWindowAttributes(key) failed: %d" % ctypes.get_last_error())
            elif alpha is not None:
                if not user32.SetLayeredWindowAttributes(self.hwnd, 0, int(255 * alpha), 2):
                    log("SetLayeredWindowAttributes failed: %d" % ctypes.get_last_error())
            insert = self.after if self.after is not None else HWND_TOP
            user32.SetWindowPos(self.hwnd, insert, int(x), int(y), int(w), int(h),
                                SWP_NOACTIVATE | SWP_SHOWWINDOW)
            user32.InvalidateRect(self.hwnd, None, True)

        def info(self):
            rc = wt.RECT()
            user32.GetWindowRect(self.hwnd, ctypes.byref(rc))
            return {"hwnd": self.hwnd, "visible": bool(user32.IsWindowVisible(self.hwnd)),
                    "rect": (rc.left, rc.top, rc.right, rc.bottom),
                    "parent": user32.GetParent(self.hwnd), "paints": self.paints}

        def place(self, x, y, w, h):
            if self.kind == "overlay":
                x, y = x + ORIGIN[0], y + ORIGIN[1]
            user32.SetWindowPos(self.hwnd, None, int(x), int(y), int(w), int(h),
                                SWP_NOZORDER | SWP_NOACTIVATE)
            user32.InvalidateRect(self.hwnd, None, True)

        def above(self, other):
            """Поставить прямо над окном other."""
            user32.SetWindowPos(self.hwnd, other.hwnd, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        def invalidate(self):
            user32.InvalidateRect(self.hwnd, None, True)

        def keep_above_desktop(self):
            """Для режима overlay: Explorer может поднять рабочий стол выше нас."""
            if self.kind == "overlay" and self.after:
                user32.SetWindowPos(self.hwnd, self.after, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        def destroy(self):
            NativeWin.registry.pop(self.hwnd, None)
            try:
                user32.DestroyWindow(self.hwnd)
            except Exception:
                pass

    gdi32.CreateCompatibleDC.argtypes = [HGDI]
    gdi32.CreateCompatibleDC.restype = HGDI
    gdi32.CreateCompatibleBitmap.argtypes = [HGDI, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = HGDI
    gdi32.BitBlt.argtypes = [HGDI, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                             HGDI, ctypes.c_int, ctypes.c_int, wt.DWORD]
    gdi32.BitBlt.restype = wt.BOOL
    gdi32.DeleteDC.argtypes = [HGDI]

    class Grab(object):
        """Снимок основного монитора вместе с полупрозрачными окнами (CAPTUREBLT)."""

        def __init__(self, sw, sh):
            self.w, self.h = sw, sh
            scr = user32.GetDC(None)
            self.mem = gdi32.CreateCompatibleDC(scr)
            self.bmp = gdi32.CreateCompatibleBitmap(scr, sw, sh)
            self.old = gdi32.SelectObject(self.mem, self.bmp)
            self.ok = bool(gdi32.BitBlt(self.mem, 0, 0, sw, sh, scr, 0, 0, 0x40CC0020))
            user32.ReleaseDC(None, scr)

        def px(self, x, y):
            if not (0 <= x < self.w and 0 <= y < self.h):
                return (-999, -999, -999)
            v = gdi32.GetPixel(self.mem, int(x), int(y))
            if v == 0xFFFFFFFF:
                return (-999, -999, -999)
            return (v & 255, (v >> 8) & 255, (v >> 16) & 255)

        def close(self):
            try:
                gdi32.SelectObject(self.mem, self.old)
                gdi32.DeleteObject(self.bmp)
                gdi32.DeleteDC(self.mem)
            except Exception:
                pass

    def _dist(a, b):
        return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))

    def probe_spec(spec, red_rect, cell, blue_rect, pump, size, origin=(0, 0)):
        """Показать тестовые окна выбранным способом и по пикселям экрана понять:
        видны ли они, лежат ли значки поверх них, работает ли прозрачность."""
        RED, BLUE = (217, 48, 44), (40, 90, 230)
        res = {"visible": False, "icons_above": False, "translucent": False, "err": ""}
        wins, before, after = [], None, None
        try:
            bx, by, bw, bh = blue_rect
            before = Grab(*size)
            base = before.px(bx + bw // 2, by + bh // 2)
            rx, ry, rw, rh = red_rect
            ox, oy = origin                    # окна принимают координаты рабочего стола
            wins.append(NativeWin(spec, rx - ox, ry - oy, rw, rh,
                                  lambda h, w, hh: g_fill(h, 0, 0, w, hh, "#d9302c")))
            wins.append(NativeWin(spec, bx - ox, by - oy, bw, bh,
                                  lambda h, w, hh: g_fill(h, 0, 0, w, hh, "#285ae6"), alpha=0.5))
            pump()
            after = Grab(*size)
            res["grab_ok"] = after.ok
            res["px_red"] = after.px(rx + rw - 10, ry + rh - 10)
            res["px_base"] = base
            res["px_blue"] = after.px(bx + bw // 2, by + bh // 2)
            res["wins"] = [w.info() for w in wins]
            res["visible"] = _dist(res["px_red"], RED) <= 12
            if res["visible"]:
                cx0, cy0, cw, ch = cell
                diff = 0
                for yy in range(cy0 + 4, cy0 + ch - 8, 3):
                    for xx in range(cx0 + 8, cx0 + cw - 8, 3):
                        if _dist(after.px(xx, yy), RED) > 12:
                            diff += 1
                res["icons_above"] = diff > 25
                q = after.px(bx + bw // 2, by + bh // 2)
                res["translucent"] = _dist(q, base) > 14 and _dist(q, BLUE) > 40
        except Exception:
            res["err"] = traceback.format_exc()
        finally:
            for w in wins:
                w.destroy()
            for g_ in (before, after):
                if g_ is not None:
                    g_.close()
        return res


# ----------------------------------------------------------------------------
# Интерфейс (Tkinter)
# ----------------------------------------------------------------------------
# ----------------------------------------------------------------------------
# Windows: буфер обмена файлов, корзина, свойства, клавиши-модификаторы
# ----------------------------------------------------------------------------
if IS_WIN:
    user32.GetKeyState.argtypes = [ctypes.c_int]
    user32.GetKeyState.restype = ctypes.c_short
    user32.OpenClipboard.argtypes = [wt.HWND]
    user32.OpenClipboard.restype = wt.BOOL
    user32.CloseClipboard.restype = wt.BOOL
    user32.EmptyClipboard.restype = wt.BOOL
    user32.SetClipboardData.argtypes = [wt.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.GetClipboardData.argtypes = [wt.UINT]
    user32.GetClipboardData.restype = ctypes.c_void_p
    user32.IsClipboardFormatAvailable.argtypes = [wt.UINT]
    user32.IsClipboardFormatAvailable.restype = wt.BOOL
    user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wt.UINT
    kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    _shell = ctypes.WinDLL("shell32", use_last_error=True)
    _shell.DragQueryFileW.argtypes = [ctypes.c_void_p, wt.UINT, wt.LPWSTR, wt.UINT]
    _shell.DragQueryFileW.restype = wt.UINT

    CF_HDROP = 15

    class DROPFILES(ctypes.Structure):
        _fields_ = [("pFiles", wt.DWORD), ("pt", wt.POINT), ("fNC", wt.BOOL), ("fWide", wt.BOOL)]

    def mods():
        """(Ctrl нажат, Shift нажат)."""
        return bool(user32.GetKeyState(0x11) & 0x8000), bool(user32.GetKeyState(0x10) & 0x8000)

    def clip_set_files(paths, cut=False):
        """Положить файлы в буфер обмена как Проводник (копировать / вырезать)."""
        data = ("\0".join(paths) + "\0\0").encode("utf-16-le")
        hdr = DROPFILES(ctypes.sizeof(DROPFILES), wt.POINT(0, 0), 0, 1)
        h = kernel32.GlobalAlloc(0x42, ctypes.sizeof(DROPFILES) + len(data))   # MOVEABLE | ZEROINIT
        p = kernel32.GlobalLock(h)
        ctypes.memmove(p, ctypes.byref(hdr), ctypes.sizeof(DROPFILES))
        ctypes.memmove(p + ctypes.sizeof(DROPFILES), data, len(data))
        kernel32.GlobalUnlock(h)
        he = kernel32.GlobalAlloc(0x42, 4)
        pe = kernel32.GlobalLock(he)
        ctypes.c_uint32.from_address(pe).value = 2 if cut else 1
        kernel32.GlobalUnlock(he)
        if not user32.OpenClipboard(None):
            raise OSError("OpenClipboard: %d" % ctypes.get_last_error())
        try:
            user32.EmptyClipboard()
            user32.SetClipboardData(CF_HDROP, h)
            user32.SetClipboardData(user32.RegisterClipboardFormatW("Preferred DropEffect"), he)
        finally:
            user32.CloseClipboard()

    def clip_get_files():
        """-> (список путей, это «вырезать»?) из буфера обмена."""
        if not user32.OpenClipboard(None):
            return [], False
        try:
            if not user32.IsClipboardFormatAvailable(CF_HDROP):
                return [], False
            h = user32.GetClipboardData(CF_HDROP)
            n = _shell.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
            out = []
            for i in range(n):
                buf = ctypes.create_unicode_buffer(1040)
                _shell.DragQueryFileW(h, i, buf, 1040)
                out.append(buf.value)
            cut = False
            fmt = user32.RegisterClipboardFormatW("Preferred DropEffect")
            if user32.IsClipboardFormatAvailable(fmt):
                hh = user32.GetClipboardData(fmt)
                p = kernel32.GlobalLock(hh)
                if p:
                    cut = bool(ctypes.c_uint32.from_address(p).value & 2)
                    kernel32.GlobalUnlock(hh)
            return out, cut
        finally:
            user32.CloseClipboard()

    CF_UNICODETEXT = 13
    user32.GetClipboardSequenceNumber.restype = wt.DWORD

    def clip_seq():
        return user32.GetClipboardSequenceNumber()

    def clip_get_text():
        """Текст из буфера обмена или None (если там не текст / это скрытая от истории запись)."""
        if not user32.OpenClipboard(None):
            return None
        try:
            for nm in ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory"):
                fmt = user32.RegisterClipboardFormatW(nm)
                if fmt and user32.IsClipboardFormatAvailable(fmt) and nm.startswith("Exclude"):
                    return "\0private"
            if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
                return None
            h = user32.GetClipboardData(CF_UNICODETEXT)
            p_ = kernel32.GlobalLock(h) if h else None
            if not p_:
                return None
            try:
                return ctypes.wstring_at(p_)
            finally:
                kernel32.GlobalUnlock(h)
        finally:
            user32.CloseClipboard()

    def clip_set_text(text):
        data = (text + "\0").encode("utf-16-le")
        h = kernel32.GlobalAlloc(0x42, len(data))
        p_ = kernel32.GlobalLock(h)
        ctypes.memmove(p_, data, len(data))
        kernel32.GlobalUnlock(h)
        if not user32.OpenClipboard(None):
            raise OSError("OpenClipboard: %d" % ctypes.get_last_error())
        try:
            user32.EmptyClipboard()
            user32.SetClipboardData(CF_UNICODETEXT, h)
        finally:
            user32.CloseClipboard()

    class FILETIME2(ctypes.Structure):
        _fields_ = [("lo", wt.DWORD), ("hi", wt.DWORD)]

    class MEMSTATUSEX(ctypes.Structure):
        _fields_ = [("dwLength", wt.DWORD), ("dwMemoryLoad", wt.DWORD), ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong), ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong), ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong), ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    def _ft(f):
        return (f.hi << 32) | f.lo

    def read_cpu():
        idle, kern, user = FILETIME2(), FILETIME2(), FILETIME2()
        kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user))
        return _ft(idle), _ft(kern) + _ft(user)               # ядро уже включает простой

    def read_mem():
        ms = MEMSTATUSEX()
        ms.dwLength = ctypes.sizeof(MEMSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(ms))
        return ms.dwMemoryLoad

    def read_disks():
        out = []
        mask = kernel32.GetLogicalDrives()
        for i in range(26):
            if mask >> i & 1:
                root = "%s:\\" % chr(65 + i)
                if kernel32.GetDriveTypeW(root) == 3:           # DRIVE_FIXED
                    try:
                        u = shutil.disk_usage(root)
                        out.append(("%s:" % chr(65 + i), 100.0 * u.used / max(1, u.total), u.free / float(1 << 30)))
                    except OSError:
                        pass
        return out

    _iph = ctypes.WinDLL("iphlpapi", use_last_error=True)
    _iph.GetIfTable.argtypes = [ctypes.c_void_p, ctypes.POINTER(wt.ULONG), wt.BOOL]
    _iph.GetIfTable.restype = wt.DWORD

    def read_net():
        """Суммарно принято / отправлено байт по рабочим сетевым интерфейсам (счётчики 32-битные)."""
        size = wt.ULONG(0)
        _iph.GetIfTable(None, ctypes.byref(size), False)
        buf = (ctypes.c_ubyte * max(size.value, 4))()
        if _iph.GetIfTable(buf, ctypes.byref(size), False) != 0:
            return 0, 0
        n = ctypes.c_uint32.from_buffer(buf, 0).value
        rx = tx = 0
        for i in range(n):
            o = 4 + i * 860
            typ = ctypes.c_uint32.from_buffer(buf, o + 516).value
            st = ctypes.c_uint32.from_buffer(buf, o + 544).value
            if typ == 24 or st < 4:                              # петля / не подключён
                continue
            rx += ctypes.c_uint32.from_buffer(buf, o + 552).value
            tx += ctypes.c_uint32.from_buffer(buf, o + 576).value
        return rx, tx

    def sys_readers():
        return {"cpu": read_cpu, "mem": read_mem, "disks": read_disks, "net": read_net}

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]

    user32.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
    user32.MonitorFromPoint.restype = ctypes.c_void_p
    user32.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(MONITORINFO)]
    user32.GetMonitorInfoW.restype = wt.BOOL

    def monitor_work(x, y):
        """Рабочая область (без панели задач) монитора, на котором точка (x, y); None при неудаче."""
        hm = user32.MonitorFromPoint(wt.POINT(int(x), int(y)), 2)         # ближайший монитор
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if hm and user32.GetMonitorInfoW(hm, ctypes.byref(mi)):
            r = mi.rcWork
            return r.left, r.top, r.right, r.bottom
        return None

    def beep():
        try:
            import winsound
            winsound.MessageBeep(0x40)
        except Exception:
            pass

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", ctypes.c_void_p), ("wFunc", wt.UINT), ("pFrom", ctypes.c_void_p),
                    ("pTo", ctypes.c_void_p), ("fFlags", ctypes.c_ushort),
                    ("fAnyOperationsAborted", wt.BOOL), ("hNameMappings", ctypes.c_void_p),
                    ("lpszProgressTitle", ctypes.c_void_p)]

    _shell.SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
    _shell.SHFileOperationW.restype = ctypes.c_int

    def recycle(paths):
        """Переместить в корзину (можно восстановить). -> True при успехе."""
        s = "\0".join(paths) + "\0\0"
        buf = ctypes.create_unicode_buffer(s, len(s) + 1)
        op = SHFILEOPSTRUCTW(None, 3, ctypes.cast(buf, ctypes.c_void_p), None,
                             0x40 | 0x10 | 0x4, 0, None, None)     # ALLOWUNDO | NOCONFIRMATION | SILENT
        return _shell.SHFileOperationW(ctypes.byref(op)) == 0 and not op.fAnyOperationsAborted

    class SHELLEXECUTEINFOW(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("fMask", ctypes.c_ulong), ("hwnd", ctypes.c_void_p),
                    ("lpVerb", wt.LPCWSTR), ("lpFile", wt.LPCWSTR), ("lpParameters", wt.LPCWSTR),
                    ("lpDirectory", wt.LPCWSTR), ("nShow", ctypes.c_int), ("hInstApp", ctypes.c_void_p),
                    ("lpIDList", ctypes.c_void_p), ("lpClass", wt.LPCWSTR), ("hkeyClass", ctypes.c_void_p),
                    ("dwHotKey", wt.DWORD), ("hIcon", ctypes.c_void_p), ("hProcess", ctypes.c_void_p)]

    _shell.ShellExecuteExW.argtypes = [ctypes.POINTER(SHELLEXECUTEINFOW)]
    _shell.ShellExecuteExW.restype = wt.BOOL

    def shell_properties(path):
        """Стандартное окно «Свойства» Проводника."""
        info = SHELLEXECUTEINFOW()
        info.cbSize = ctypes.sizeof(info)
        info.fMask = 0x0000000C                  # SEE_MASK_INVOKEIDLIST
        info.lpVerb, info.lpFile, info.nShow = "properties", path, 1
        return bool(_shell.ShellExecuteExW(ctypes.byref(info)))


# ----------------------------------------------------------------------------
# Приложение: автозапуск, значок в трее, один экземпляр
# ----------------------------------------------------------------------------
def app_dir():
    """Папка, где лежит программа (для .exe - рядом с ним)."""
    base = sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    return os.path.dirname(base)


if IS_WIN:
    RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"

    def launch_command():
        if getattr(sys, "frozen", False):
            return '"%s"' % sys.executable
        pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        exe = pyw if os.path.exists(pyw) else sys.executable
        return '"%s" "%s"' % (exe, os.path.abspath(__file__))

    def autostart_enabled():
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, APP_NAME)
            return True
        except OSError:
            return False

    def set_autostart(on):
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if on:
                winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, launch_command())
            else:
                try:
                    winreg.DeleteValue(k, APP_NAME)
                except OSError:
                    pass

    class NOTIFYICONDATAW(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("hWnd", ctypes.c_void_p), ("uID", wt.UINT),
                    ("uFlags", wt.UINT), ("uCallbackMessage", wt.UINT), ("hIcon", ctypes.c_void_p),
                    ("szTip", wt.WCHAR * 128), ("dwState", wt.DWORD), ("dwStateMask", wt.DWORD),
                    ("szInfo", wt.WCHAR * 256), ("uVersion", wt.UINT), ("szInfoTitle", wt.WCHAR * 64),
                    ("dwInfoFlags", wt.DWORD), ("guidItem", ctypes.c_ubyte * 16),
                    ("hBalloonIcon", ctypes.c_void_p)]

    _shell.Shell_NotifyIconW.argtypes = [wt.DWORD, ctypes.POINTER(NOTIFYICONDATAW)]
    _shell.Shell_NotifyIconW.restype = wt.BOOL
    _shell.ExtractIconW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.UINT]
    _shell.ExtractIconW.restype = ctypes.c_void_p
    user32.LoadImageW.argtypes = [ctypes.c_void_p, wt.LPCWSTR, wt.UINT, ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.LoadImageW.restype = ctypes.c_void_p
    user32.LoadIconW.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.LoadIconW.restype = ctypes.c_void_p
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.RegisterWindowMessageW.argtypes = [wt.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wt.UINT
    TRAY_MSG = 0x8001                                    # WM_APP + 1
    _tray = {"nid": None, "ev": None, "taskbar": 0}

    def _tray_icon():
        for name in (APP_NAME + ".ico",):
            p = os.path.join(app_dir(), name)
            if os.path.exists(p):
                h = user32.LoadImageW(None, p, 1, 16, 16, 0x10)      # IMAGE_ICON, LR_LOADFROMFILE
                if h:
                    return h
        if getattr(sys, "frozen", False):
            h = _shell.ExtractIconW(kernel32.GetModuleHandleW(None), sys.executable, 0)
            if h and h != 1:
                return h
        return user32.LoadIconW(None, 32512)                  # стандартный значок

    def _tray_proc(hwnd, msg, wp, lp):
        try:
            if msg == TRAY_MSG:
                m = lp & 0xFFFF
                if m in (0x202, 0x203):                       # левый клик / двойной клик
                    _tray["ev"].edit.set()
                elif m == 0x205:                              # правая кнопка - меню
                    pt = wt.POINT()
                    user32.GetCursorPos(ctypes.byref(pt))
                    _tray["ev"].q.append(("tray", pt.x, pt.y))
                return 0
            if _tray["taskbar"] and msg == _tray["taskbar"] and _tray["nid"] is not None:
                _shell.Shell_NotifyIconW(0, ctypes.byref(_tray["nid"]))      # Проводник перезапустился
                return 0
        except Exception:
            log("tray proc failed:\n" + traceback.format_exc())
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    _TRAY_PROC_REF = WNDPROC(_tray_proc)

    def create_tray(ev):
        """Значок в области уведомлений (вызывается из потока ввода: ему нужен цикл сообщений)."""
        wc = WNDCLASSW()
        wc.lpfnWndProc = _TRAY_PROC_REF
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "KinDeskTray"
        if not user32.RegisterClassW(ctypes.byref(wc)) and ctypes.get_last_error() != 1410:
            log("tray RegisterClassW failed: %d" % ctypes.get_last_error())
            return
        hwnd = user32.CreateWindowExW(0, "KinDeskTray", APP_NAME, 0, 0, 0, 0, 0,
                                      -3, None, wc.hInstance, None)               # HWND_MESSAGE
        if not hwnd:
            log("tray CreateWindowExW failed: %d" % ctypes.get_last_error())
            return
        nid = NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(nid)
        nid.hWnd, nid.uID, nid.uFlags = hwnd, 1, 0x1 | 0x2 | 0x4       # MESSAGE | ICON | TIP
        nid.uCallbackMessage = TRAY_MSG
        nid.hIcon = _tray_icon()
        nid.szTip = APP_NAME
        _tray.update(nid=nid, ev=ev, taskbar=user32.RegisterWindowMessageW("TaskbarCreated"))
        if not _shell.Shell_NotifyIconW(0, ctypes.byref(nid)):     # NIM_ADD
            log("Shell_NotifyIcon failed: %d" % ctypes.get_last_error())

    def remove_tray():
        if _tray["nid"] is not None:
            _shell.Shell_NotifyIconW(2, ctypes.byref(_tray["nid"]))   # NIM_DELETE
            _tray["nid"] = None

    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
    user32.MessageBoxW.restype = ctypes.c_int
    _mutex = []

    def already_running():
        """True, если копия программы уже запущена."""
        h = kernel32.CreateMutexW(None, False, "Local\\KinDesk_SingleInstance")
        _mutex.append(h)
        return ctypes.get_last_error() == 183           # ERROR_ALREADY_EXISTS

    def detect_scale():
        """Масштаб интерфейса Windows (100% = 1.0) по основному монитору."""
        try:
            user32.GetDpiForSystem.restype = wt.UINT
            dpi = user32.GetDpiForSystem()
        except Exception:
            try:
                dc = user32.GetDC(None)
                dpi = gdi32.GetDeviceCaps(dc, 88)           # LOGPIXELSX
                user32.ReleaseDC(None, dc)
            except Exception:
                dpi = 96
        return max(1.0, min(3.0, (dpi or 96) / 96.0))

    def message_box(text, title=APP_NAME):
        user32.MessageBoxW(None, text, title, 0x40)


# ----------------------------------------------------------------------------
# Плавная отрисовка: GDI+ (сглаживание) + окно с попиксельной прозрачностью
# ----------------------------------------------------------------------------
if IS_WIN:
    gp = ctypes.WinDLL("gdiplus", use_last_error=True)
    _P, _I, _F, _U = ctypes.c_void_p, ctypes.c_int, ctypes.c_float, ctypes.c_uint32

    class GdiplusStartupInput(ctypes.Structure):
        _fields_ = [("GdiplusVersion", ctypes.c_uint32), ("DebugEventCallback", ctypes.c_void_p),
                    ("SuppressBackgroundThread", wt.BOOL), ("SuppressExternalCodecs", wt.BOOL)]

    class RectI(ctypes.Structure):
        _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("w", ctypes.c_int), ("h", ctypes.c_int)]

    class RectF(ctypes.Structure):
        _fields_ = [("x", ctypes.c_float), ("y", ctypes.c_float),
                    ("w", ctypes.c_float), ("h", ctypes.c_float)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                    ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]

    def _gp(name, *argtypes):
        fn = getattr(gp, name)
        fn.argtypes = list(argtypes)
        fn.restype = _I
        return fn

    _pp = ctypes.POINTER(_P)
    GdiplusStartup = _gp("GdiplusStartup", ctypes.POINTER(ctypes.c_size_t),
                         ctypes.POINTER(GdiplusStartupInput), _P)
    GdipCreateBitmapFromScan0 = _gp("GdipCreateBitmapFromScan0", _I, _I, _I, _I, _P, _pp)
    GdipGetImageGraphicsContext = _gp("GdipGetImageGraphicsContext", _P, _pp)
    GdipDeleteGraphics = _gp("GdipDeleteGraphics", _P)
    GdipDisposeImage = _gp("GdipDisposeImage", _P)
    GdipSetSmoothingMode = _gp("GdipSetSmoothingMode", _P, _I)
    GdipSetTextRenderingHint = _gp("GdipSetTextRenderingHint", _P, _I)
    GdipSetInterpolationMode = _gp("GdipSetInterpolationMode", _P, _I)
    GdipSetPixelOffsetMode = _gp("GdipSetPixelOffsetMode", _P, _I)
    GdipSetCompositingMode = _gp("GdipSetCompositingMode", _P, _I)
    GdipCreatePath = _gp("GdipCreatePath", _I, _pp)
    GdipDeletePath = _gp("GdipDeletePath", _P)
    GdipAddPathArcI = _gp("GdipAddPathArcI", _P, _I, _I, _I, _I, _F, _F)
    GdipAddPathLineI = _gp("GdipAddPathLineI", _P, _I, _I, _I, _I)
    GdipClosePathFigure = _gp("GdipClosePathFigure", _P)
    GdipCreateSolidFill = _gp("GdipCreateSolidFill", _U, _pp)
    GdipDeleteBrush = _gp("GdipDeleteBrush", _P)
    GdipFillPath = _gp("GdipFillPath", _P, _P, _P)
    GdipCreatePen1 = _gp("GdipCreatePen1", _U, _F, _I, _pp)
    GdipDeletePen = _gp("GdipDeletePen", _P)
    GdipDrawPath = _gp("GdipDrawPath", _P, _P, _P)
    GdipDrawLineI = _gp("GdipDrawLineI", _P, _P, _I, _I, _I, _I)
    GdipFillEllipseI = _gp("GdipFillEllipseI", _P, _P, _I, _I, _I, _I)
    GdipDrawEllipseI = _gp("GdipDrawEllipseI", _P, _P, _I, _I, _I, _I)
    GdipFillPieI = _gp("GdipFillPieI", _P, _P, _I, _I, _I, _I, _F, _F)
    GdipSetPenStartCap = _gp("GdipSetPenStartCap", _P, _I)
    GdipSetPenEndCap = _gp("GdipSetPenEndCap", _P, _I)
    GdipCreateFontFamilyFromName = _gp("GdipCreateFontFamilyFromName", wt.LPCWSTR, _P, _pp)
    GdipCreateFont = _gp("GdipCreateFont", _P, _F, _I, _I, _pp)
    GdipCreateStringFormat = _gp("GdipCreateStringFormat", _I, _I, _pp)
    GdipDeleteStringFormat = _gp("GdipDeleteStringFormat", _P)
    GdipSetStringFormatAlign = _gp("GdipSetStringFormatAlign", _P, _I)
    GdipSetStringFormatLineAlign = _gp("GdipSetStringFormatLineAlign", _P, _I)
    GdipSetStringFormatTrimming = _gp("GdipSetStringFormatTrimming", _P, _I)
    GdipDrawString = _gp("GdipDrawString", _P, wt.LPCWSTR, _I, _P, ctypes.POINTER(RectF), _P, _P)
    GdipCreateBitmapFromHICON = _gp("GdipCreateBitmapFromHICON", _P, _pp)
    GdipCreateLineBrushFromRectI = _gp("GdipCreateLineBrushFromRectI", ctypes.POINTER(RectI), _U, _U, _I, _I, _pp)
    GdipCreateBitmapFromFile = _gp("GdipCreateBitmapFromFile", wt.LPCWSTR, _pp)
    GdipDrawArcI = _gp("GdipDrawArcI", _P, _P, _I, _I, _I, _I, _F, _F)
    GdipDrawImageRectI = _gp("GdipDrawImageRectI", _P, _P, _I, _I, _I, _I)
    GdipCreateHBITMAPFromBitmap = _gp("GdipCreateHBITMAPFromBitmap", _P, _pp, _U)

    user32.UpdateLayeredWindow.argtypes = [wt.HWND, HGDI, ctypes.POINTER(wt.POINT),
                                           ctypes.POINTER(wt.SIZE), HGDI, ctypes.POINTER(wt.POINT),
                                           wt.DWORD, ctypes.POINTER(BLENDFUNCTION), wt.DWORD]
    user32.UpdateLayeredWindow.restype = wt.BOOL

    _gp_state = {"token": None, "ok": False}
    _gp_fonts = {}
    _gp_icons = {}

    def gp_start():
        """Запустить GDI+; False - рисовать по-старому."""
        if _gp_state["token"] is None:
            tok = ctypes.c_size_t(0)
            inp = GdiplusStartupInput(1, None, False, False)
            st = GdiplusStartup(ctypes.byref(tok), ctypes.byref(inp), None)
            _gp_state["token"], _gp_state["ok"] = tok.value, st == 0
            if st != 0:
                log("GdiplusStartup failed: %d" % st)
        return _gp_state["ok"]

    def argb(hexc, alpha=1.0):
        h = hexc.lstrip("#")
        a = max(0, min(255, int(round(255 * alpha))))
        return (a << 24) | (int(h[0:2], 16) << 16) | (int(h[2:4], 16) << 8) | int(h[4:6], 16)

    def _font(name, px, style):
        key = (name, px, style)
        if key not in _gp_fonts:
            fam, font = _P(), _P()
            GdipCreateFontFamilyFromName(name, None, ctypes.byref(fam))
            GdipCreateFont(fam, float(px), style, 2, ctypes.byref(font))     # 2 = пиксели
            _gp_fonts[key] = font
        return _gp_fonts[key]

    _custom_bmps = {}

    def custom_bitmap(file):
        """GDI+ картинка из файла .ico / .png / .jpg / .bmp или значок из .exe / .dll; кэш по времени файла."""
        try:
            mt = os.path.getmtime(file)
        except OSError:
            return None
        cur = _custom_bmps.get(file)
        if cur and cur[0] == mt:
            return cur[1]
        bmp = _P()
        if os.path.splitext(file)[1].lower() in (".exe", ".dll", ".icl", ".scr"):
            hicon = _shell.ExtractIconW(kernel32.GetModuleHandleW(None), file, 0)
            if hicon and hicon != 1:
                GdipCreateBitmapFromHICON(hicon, ctypes.byref(bmp))
        else:
            GdipCreateBitmapFromFile(file, ctypes.byref(bmp))
        _custom_bmps[file] = (mt, bmp or None)
        return bmp or None

    class Canvas(object):
        """Холст ARGB с предумноженной прозрачностью; все фигуры сглажены."""
        PARGB = 0x000E200B

        def __init__(self, w, h):
            self.w, self.h = int(w), int(h)
            self.bmp, self.g = _P(), _P()
            GdipCreateBitmapFromScan0(self.w, self.h, 0, self.PARGB, None, ctypes.byref(self.bmp))
            GdipGetImageGraphicsContext(self.bmp, ctypes.byref(self.g))
            GdipSetSmoothingMode(self.g, 4)            # AntiAlias
            GdipSetTextRenderingHint(self.g, 4)        # AntiAlias (ClearType не работает с alpha)
            GdipSetInterpolationMode(self.g, 7)        # HighQualityBicubic
            GdipSetPixelOffsetMode(self.g, 2)

        def _path(self, x, y, w, h, r, corners):
            r = int(max(0, min(r, w // 2, h // 2)))
            d = 2 * r
            path = _P()
            GdipCreatePath(0, ctypes.byref(path))
            for key, ax, ay, start, px, py in (("tl", x, y, 180, x, y),
                                               ("tr", x + w - d, y, 270, x + w, y),
                                               ("br", x + w - d, y + h - d, 0, x + w, y + h),
                                               ("bl", x, y + h - d, 90, x, y + h)):
                if key in corners and r > 0:
                    GdipAddPathArcI(path, int(ax), int(ay), d, d, float(start), 90.0)
                else:
                    GdipAddPathLineI(path, int(px), int(py), int(px), int(py))
            GdipClosePathFigure(path)
            return path

        def fill_rr(self, x, y, w, h, r, color, alpha=1.0, corners="tl tr br bl", copy=False):
            path, br = self._path(x, y, w, h, r, corners), _P()
            GdipCreateSolidFill(argb(color, alpha), ctypes.byref(br))
            if copy:
                GdipSetCompositingMode(self.g, 1)      # SourceCopy: заменить, а не смешать
            GdipFillPath(self.g, br, path)
            if copy:
                GdipSetCompositingMode(self.g, 0)
            GdipDeleteBrush(br)
            GdipDeletePath(path)

        def grad_rr(self, x, y, w, h, r, c1, c2, a1=1.0, a2=1.0, corners="tl tr br bl", copy=False):
            """Скруглённый прямоугольник с вертикальным градиентом c1 -> c2."""
            br = _P()
            rc = RectI(int(x), int(y), int(w), max(2, int(h)))
            st = GdipCreateLineBrushFromRectI(ctypes.byref(rc), argb(c1, a1), argb(c2, a2), 1, 0, ctypes.byref(br))
            if st != 0 or not br:
                return self.fill_rr(x, y, w, h, r, c2, a2, corners, copy)
            path = self._path(x, y, w, h, r, corners)
            if copy:
                GdipSetCompositingMode(self.g, 1)
            GdipFillPath(self.g, br, path)
            if copy:
                GdipSetCompositingMode(self.g, 0)
            GdipDeleteBrush(br)
            GdipDeletePath(path)

        def stroke_rr(self, x, y, w, h, r, color, alpha=1.0, width=1.0, corners="tl tr br bl"):
            path, pen = self._path(x, y, w, h, r, corners), _P()
            GdipCreatePen1(argb(color, alpha), float(width), 2, ctypes.byref(pen))
            GdipDrawPath(self.g, pen, path)
            GdipDeletePen(pen)
            GdipDeletePath(path)

        def line(self, x1, y1, x2, y2, color, alpha=1.0, width=1.5):
            pen = _P()
            GdipCreatePen1(argb(color, alpha), float(width), 2, ctypes.byref(pen))
            GdipSetPenStartCap(pen, 2)                 # скруглённые концы
            GdipSetPenEndCap(pen, 2)
            GdipDrawLineI(self.g, pen, int(x1), int(y1), int(x2), int(y2))
            GdipDeletePen(pen)

        def polyline(self, pts, color, alpha=1.0, width=1.5):
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                self.line(x1, y1, x2, y2, color, alpha, width)

        def ellipse(self, x, y, w, h, color, alpha=1.0, fill=True, width=1.5):
            if fill:
                br = _P()
                GdipCreateSolidFill(argb(color, alpha), ctypes.byref(br))
                GdipFillEllipseI(self.g, br, int(x), int(y), int(w), int(h))
                GdipDeleteBrush(br)
            else:
                pen = _P()
                GdipCreatePen1(argb(color, alpha), float(width), 2, ctypes.byref(pen))
                GdipDrawEllipseI(self.g, pen, int(x), int(y), int(w), int(h))
                GdipDeletePen(pen)

        def pie(self, x, y, w, h, start, sweep, color, alpha=1.0):
            br = _P()
            GdipCreateSolidFill(argb(color, alpha), ctypes.byref(br))
            GdipFillPieI(self.g, br, int(x), int(y), int(w), int(h), float(start), float(sweep))
            GdipDeleteBrush(br)

        def text(self, s, x, y, w, h, color, alpha=1.0, font=("Segoe UI", 13, 0),
                 align=0, valign=1, wrap=False):
            fmt, br = _P(), _P()
            GdipCreateStringFormat(0 if wrap else 0x1000, 0, ctypes.byref(fmt))   # 0x1000 = NoWrap
            GdipSetStringFormatAlign(fmt, align)       # 0 слева, 1 по центру, 2 справа
            GdipSetStringFormatLineAlign(fmt, valign)  # 0 сверху, 1 по центру
            GdipSetStringFormatTrimming(fmt, 3)        # многоточие
            GdipCreateSolidFill(argb(color, alpha), ctypes.byref(br))
            rc = RectF(float(x), float(y), float(w), float(h))
            GdipDrawString(self.g, s, -1, _font(*font), ctypes.byref(rc), fmt, br)
            GdipDeleteBrush(br)
            GdipDeleteStringFormat(fmt)

        def arc(self, x, y, w, h, start, sweep, color, alpha=1.0, width=3.0):
            if abs(sweep) < 0.1:
                return
            pen = _P()
            GdipCreatePen1(argb(color, alpha), float(width), 2, ctypes.byref(pen))
            GdipSetPenStartCap(pen, 2)
            GdipSetPenEndCap(pen, 2)
            GdipDrawArcI(self.g, pen, int(x), int(y), int(w), int(h), float(start), float(sweep))
            GdipDeletePen(pen)

        def icon(self, path, x, y, size):
            ov = ICON_OVR.get(icon_key(path))
            if ov:                                       # значок, выбранный пользователем
                bmp = custom_bitmap(ov)
                if bmp:
                    GdipDrawImageRectI(self.g, bmp, int(x), int(y), int(size), int(size))
                    return
            hicon = get_icon(path, size)
            if not hicon:
                return
            bmp = _gp_icons.get(hicon)
            if bmp is None:
                bmp = _P()
                GdipCreateBitmapFromHICON(hicon, ctypes.byref(bmp))
                _gp_icons[hicon] = bmp
            if bmp:
                GdipDrawImageRectI(self.g, bmp, int(x), int(y), int(size), int(size))

        def hbitmap(self):
            hb = _P()
            GdipCreateHBITMAPFromBitmap(self.bmp, ctypes.byref(hb), 0)
            return hb.value

        def close(self):
            GdipDeleteGraphics(self.g)
            GdipDisposeImage(self.bmp)

    class LayerWin(object):
        """Окно с попиксельной прозрачностью (UpdateLayeredWindow). Одним вызовом
        задаёт и картинку, и положение, и размер - поэтому не мигает."""

        def __init__(self, spec, x, y, w, h):
            NativeWin._ensure_class()
            self.kind, parent, self.after = spec
            self.size = (0, 0)
            ex = WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_LAYERED
            if self.kind == "overlay":
                style, par = WS_POPUP, None
                ex |= WS_EX_TRANSPARENT
            else:
                style, par = WS_CHILD | WS_CLIPSIBLINGS, parent
            self.hwnd = user32.CreateWindowExW(ex, NativeWin.CLASS, "KinDesk", style,
                                               0, 0, 1, 1, par, None,
                                               kernel32.GetModuleHandleW(None), None)
            if not self.hwnd:
                raise OSError("CreateWindowExW: %d" % ctypes.get_last_error())
            self.pos = (int(x), int(y))
            insert = self.after if self.after is not None else HWND_TOP
            user32.SetWindowPos(self.hwnd, insert, 0, 0, 0, 0,
                                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)

        def _abs(self, x, y):
            if self.kind == "overlay":
                return int(x) + ORIGIN[0], int(y) + ORIGIN[1]
            return int(x), int(y)

        def render(self, draw, x, y, w, h):
            """Нарисовать draw(canvas, w, h) и одним вызовом выставить картинку и положение."""
            w, h = max(1, int(w)), max(1, int(h))
            cv = Canvas(w, h)
            try:
                draw(cv, w, h)
                hbm = cv.hbitmap()
            finally:
                cv.close()
            if not hbm:
                return
            screen = user32.GetDC(None)
            mem = gdi32.CreateCompatibleDC(screen)
            old = gdi32.SelectObject(mem, hbm)
            ax, ay = self._abs(x, y)
            ok = user32.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(wt.POINT(ax, ay)),
                                            ctypes.byref(wt.SIZE(w, h)), mem,
                                            ctypes.byref(wt.POINT(0, 0)), 0,
                                            ctypes.byref(BLENDFUNCTION(0, 0, 255, 1)), 2)
            if not ok:
                log("UpdateLayeredWindow failed: %d" % ctypes.get_last_error())
            gdi32.SelectObject(mem, old)
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(None, screen)
            gdi32.DeleteObject(hbm)
            self.pos, self.size = (int(x), int(y)), (w, h)

        def move(self, x, y):
            ax, ay = self._abs(x, y)
            user32.SetWindowPos(self.hwnd, None, ax, ay, 0, 0,
                                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE)
            self.pos = (int(x), int(y))

        def set_visible(self, on):
            user32.ShowWindow(self.hwnd, 8 if on else 0)           # SW_SHOWNA / SW_HIDE

        def keep_above_desktop(self):
            if self.kind == "overlay" and self.after:
                user32.SetWindowPos(self.hwnd, self.after, 0, 0, 0, 0,
                                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

        def destroy(self):
            try:
                user32.DestroyWindow(self.hwnd)
            except Exception:
                pass


def darken(hex_color, k=0.6):
    try:
        h = hex_color.lstrip("#")
        r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
        return "#%02x%02x%02x" % (int(r * k), int(g * k), int(b * k))
    except Exception:
        return "#101010"


class FenceViewClassic(object):
    """Одна область на экране: заголовок (почти непрозрачный) + тело (полупрозрачное)
    + слой со значками (цвет фона области - «прозрачный», поэтому значки не тускнеют)."""

    SYM = ("Segoe UI Symbol", -18, False)
    TTL = ("Segoe UI", -16, True)
    LBL = ("Segoe UI", -12, False)

    def __init__(self, app, f):
        self.app, self.f = app, f
        tr = app.cfg.get("translucent", True)
        self.bar = NativeWin(app.spec, *self._geom("bar"), painter=self.paint_bar,
                             alpha=min(BAR_ALPHA, max(0.4, float(f["alpha"]) + 0.2)) if tr else None)
        self.body = self.icons = None
        if not f.get("collapsed"):
            self.body = NativeWin(app.spec, *self._geom("body"), painter=self.paint_body,
                                  alpha=float(f["alpha"]) if tr else None)
            if tr:
                self.icons = NativeWin(app.spec, *self._geom("body"), painter=self.paint_icons,
                                       key=f["color"])
                self.icons.above(self.body)

    def _geom(self, role):
        f = self.f
        if role == "bar":
            return f["x"], f["y"], f["w"], TITLE_H
        return f["x"], f["y"] + TITLE_H, f["w"], max(10, f["h"] - TITLE_H)

    def place(self):
        self.bar.place(*self._geom("bar"))
        if self.body:
            self.body.place(*self._geom("body"))
        if self.icons:
            self.icons.place(*self._geom("body"))
            self.icons.above(self.body)

    def keep_above_desktop(self):
        self.bar.keep_above_desktop()
        if self.body:
            self.body.keep_above_desktop()
        if self.icons:
            self.icons.above(self.body)

    def update(self):
        return False                           # старый вид проще пересоздать

    def repaint(self):
        for w in (self.body, self.icons):
            if w:
                w.invalidate()

    def paint_bar(self, hdc, w, h):
        f = self.f
        bar, txt = f["bar"], f.get("text", "#FFFFFF")
        sep = darken(bar, 0.75)
        g_fill(hdc, 0, 0, w, h, bar)
        for x in (TITLE_H, w - TITLE_H, w - 2 * TITLE_H):
            g_fill(hdc, x, 5, x + 1, h - 5, sep)
        flags = DT_CENTER | DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX
        sym = get_font(*self.SYM)
        g_text(hdc, "▸" if f.get("collapsed") else "▾", 0, 0, TITLE_H, h, txt, sym, flags)
        label = self.app.eng.title(f) + ("  (%d)" % len(self.app.eng.items(f)) if f.get("collapsed") else "")
        g_text(hdc, label, TITLE_H + 8, 0, w - 2 * TITLE_H - 4, h, txt, get_font(*self.TTL),
               DT_VCENTER | DT_SINGLELINE | DT_NOPREFIX | DT_END_ELLIPSIS)
        g_text(hdc, "◐", w - 2 * TITLE_H, 0, w - TITLE_H, h, txt, sym, flags)
        g_text(hdc, "≡", w - TITLE_H, 0, w, h, txt, sym, flags)

    def paint_body(self, hdc, w, h):
        f = self.f
        g_fill(hdc, 0, 0, w, h, f["color"])
        if not f.get("collapsed"):
            for r in range(GRIP):                  # уголок для изменения размера
                g_fill(hdc, w - 1 - r, h - GRIP + r, w, h - GRIP + r + 1, f["bar"])
            if self.icons is None:                 # без прозрачности значки рисуем прямо в теле
                self.draw_items(hdc)

    def paint_icons(self, hdc, w, h):
        g_fill(hdc, 0, 0, w, h, self.f["color"])   # этот цвет окно считает прозрачным
        self.draw_items(hdc)

    def draw_items(self, hdc):
        f, app = self.f, self.app
        txt = contrast(f["color"])
        hl = blend(f["color"], txt, 0.25)
        font = get_font(*self.LBL)
        isz, labels = int(f.get("icon", 32)), f.get("labels")
        cw, ch = app.eng.cell(f)
        for k, it in enumerate(app.eng.items(f)):
            sx, sy = app.eng.slot(f, k)
            cx, cy = sx, sy - TITLE_H              # в координатах тела
            if (f["id"], it["name"]) in app.sel:
                g_fill(hdc, cx + 2, cy + 2, cx + cw - 2, cy + ch - 2, hl)
            draw_icon(hdc, it["path"], cx + (cw - isz) // 2, cy + 8, isz)
            if labels:
                g_text(hdc, it["label"], cx + 3, cy + isz + 12, cx + cw - 3, cy + ch - 2,
                       txt, font, DT_CENTER | DT_WORDBREAK | DT_NOPREFIX | DT_END_ELLIPSIS)

    def destroy(self):
        for v in (self.bar, self.body, self.icons):
            if v:
                v.destroy()


class FenceViewGP(object):
    """Область одним окном с попиксельной прозрачностью: скруглённые сглаженные края,
    значки без потери яркости, плавное сворачивание. Перерисовывается на месте."""

    @property
    def R(self):
        return sc(16) if self.app.cfg.get("look", "modern") == "modern" else sc(14)

    @property
    def TTL(self):
        return ("Segoe UI", sc(13), 1)

    def __init__(self, app, f):
        self.app, self.f = app, f
        self.vh = self.target()
        self.timer = None
        self.dead = False
        self.win = LayerWin(app.spec, f["x"], f["y"], f["w"], self.vh)
        self.render()

    def target(self):
        return TITLE_H if self.f.get("collapsed") else self.f["h"]

    # --- жизненный цикл ---------------------------------------------------------
    def update(self):
        """Подогнать окно под состояние области (с анимацией высоты). -> True: окно живое."""
        tgt = self.target()
        if tgt != self.vh and self.f["w"] == self.win.size[0] and self.timer is None:
            self.animate()
        elif self.timer is None:
            self.vh = tgt
            self.render()
        return True

    def animate(self):
        self.timer = None
        if self.dead:
            return
        tgt = self.target()
        diff = tgt - self.vh
        if abs(diff) <= 2:
            self.vh = tgt
            self.render()
            self.app.group_follow(self.f, final=True)
            return
        self.vh += int(diff * 0.35) or (1 if diff > 0 else -1)
        self.render()
        self.app.group_follow(self.f)
        self.timer = self.app.root.after(16, self.animate)

    def place(self):
        """Область двигают или растягивают: размер изменился - перерисовать, иначе сдвинуть."""
        f = self.f
        tgt = self.target()
        if (f["w"], tgt) != self.win.size:
            self.vh = tgt
            self.render()
        else:
            self.win.move(f["x"], f["y"])

    def keep_above_desktop(self):
        self.win.keep_above_desktop()

    def repaint(self):
        self.render()

    def render(self):
        f = self.f
        self.win.render(self.draw, f["x"], f["y"], f["w"], self.vh)

    def destroy(self):
        self.dead = True
        if self.timer is not None:
            try:
                self.app.root.after_cancel(self.timer)
            except Exception:
                pass
        self.win.destroy()

    # --- рисование ----------------------------------------------------------------
    def draw_calendar(self, cv, w, h, f, ink, hov):
        s = SCALE[0]
        lay = cal_layout(f)
        y_, m_ = f["cal_y"], f["cal_m"]
        first = int(f.get("first_weekday", 0))

        def hv(act):
            return bool(hov and hov[1] == "wact" and hov[2] == act)
        for nm, act, sign in (("prev", ("cal", "prev"), -1), ("next", ("cal", "next"), 1)):
            r = lay[nm]
            if hv(act):
                cv.fill_rr(r[0], r[1] + sc(2), r[2] - r[0], r[3] - r[1] - sc(4), sc(8), ink, 0.12)
            cx, cy, u = (r[0] + r[2]) / 2.0, (r[1] + r[3]) / 2.0, 3.0 * s
            cv.polyline([(cx - sign * u * 0.6, cy - 1.6 * u), (cx + sign * u * 0.6, cy), (cx - sign * u * 0.6, cy + 1.6 * u)],
                        ink, 0.9, 2.0 * s)
        lb = lay["label"]
        if hv(("cal", "today")):
            cv.fill_rr(lb[0], lb[1] + sc(2), lb[2] - lb[0], lb[3] - lb[1] - sc(4), sc(8), ink, 0.12)
        cv.text("%s %d" % (MONTHS_RU[m_ - 1], y_), lb[0], lb[1], lb[2] - lb[0], lb[3] - lb[1], ink, 1.0,
                ("Segoe UI", sc(14), 1), align=1)
        cw, chh, gx, gy = lay["cw"], lay["ch"], lay["gx"], lay["gy"]
        weekend = blend(ink, f["bar"], 0.55)
        for i in range(7):
            col = weekend if (first + i) % 7 >= 5 else ink
            cv.text(WEEKDAYS_RU[(first + i) % 7], gx + i * cw, lay["wd_y"], cw, sc(24), col, 0.65,
                    ("Segoe UI", sc(11), 1), align=1)
        today = datetime.date.today()
        evs = self.app.all_events()
        for r, week in enumerate(month_grid(y_, m_, first)):
            for c, day in enumerate(week):
                x, y = gx + c * cw, gy + r * chh
                inside = day.month == m_
                if hv(("cal", "day", day.isoformat())):
                    cv.fill_rr(x + sc(2), y + sc(2), cw - sc(4), chh - sc(4), sc(8), ink, 0.12)
                if day == today:
                    d = int(min(cw, chh) - sc(4))
                    cv.ellipse(x + (cw - d) / 2.0, y + (chh - d) / 2.0, d, d, f["bar"], 1.0)
                    col, alpha, bold = f["text"], 1.0, 1
                else:
                    col = weekend if day.weekday() >= 5 else ink
                    alpha, bold = (1.0 if inside else 0.32), 0
                cv.text(str(day.day), x, y, cw, chh, col, alpha, ("Segoe UI", sc(12), bold), align=1)
                if evs and events_on(evs, day):
                    dd = max(3, int(5 * s))
                    cv.ellipse(x + (cw - dd) / 2.0, y + chh - sc(8), dd, dd,
                               f["text"] if day == today else f["bar"], 1.0 if inside else 0.4)

    def draw_todo(self, cv, w, h, f, ink, hov):
        s = SCALE[0]
        tasks = self.app.cfg.get("todo", [])
        lay = todo_layout(f, len(tasks))

        def hv(act):
            return bool(hov and hov[1] == "wact" and hov[2] == act)
        a = lay["add"]
        if hv(("todo", "add")):
            cv.fill_rr(a[0], a[1], a[2] - a[0], a[3] - a[1], sc(9), ink, 0.12)
        cx, cy = a[0] + sc(14), (a[1] + a[3]) / 2.0
        cv.line(cx - 5 * s, cy, cx + 5 * s, cy, f["bar"], 1.0, 2.0 * s)
        cv.line(cx, cy - 5 * s, cx, cy + 5 * s, f["bar"], 1.0, 2.0 * s)
        cv.text("Новая задача", a[0] + sc(30), a[1], a[2] - a[0] - sc(30), a[3] - a[1], ink, 0.75,
                ("Segoe UI", sc(13), 0))
        for i, row, chk, dele in lay["rows"]:
            t = tasks[i]
            done = bool(t.get("d"))
            over = hv(("todo", "toggle", i)) or hv(("todo", "del", i))
            if over:
                cv.fill_rr(row[0], row[1], row[2] - row[0], row[3] - row[1], sc(9), ink, 0.08)
            bw, bh = chk[2] - chk[0], chk[3] - chk[1]
            if done:
                cv.fill_rr(chk[0], chk[1], bw, bh, sc(5), f["bar"], 1.0)
                cv.polyline([(chk[0] + bw * 0.25, chk[1] + bh * 0.52), (chk[0] + bw * 0.43, chk[1] + bh * 0.72),
                             (chk[0] + bw * 0.76, chk[1] + bh * 0.30)], f["text"], 1.0, 2.0 * s)
            else:
                cv.stroke_rr(chk[0], chk[1], bw, bh, sc(5), ink, 0.6, 1.6 * s)
            tx, tw = chk[2] + sc(10), dele[0] - chk[2] - sc(14)
            if t.get("pomos"):
                tw -= sc(34)
                cv.text("×%d" % t["pomos"], dele[0] - sc(36), row[1], sc(34), row[3] - row[1], f["bar"], 1.0,
                        ("Segoe UI", sc(11), 1), align=2)
            cv.text(t["t"], tx, row[1], tw, row[3] - row[1], ink, 0.5 if done else 1.0,
                    ("Segoe UI", sc(13), 0))
            if done:
                mid = (row[1] + row[3]) / 2.0
                cv.line(tx, mid, tx + min(tw, len(t["t"]) * 7.2 * s), mid, ink, 0.5, 1.4 * s)
            if over:
                dx, dy = (dele[0] + dele[2]) / 2.0, (dele[1] + dele[3]) / 2.0
                cv.line(dx - 4 * s, dy - 4 * s, dx + 4 * s, dy + 4 * s, ink, 0.7, 1.8 * s)
                cv.line(dx - 4 * s, dy + 4 * s, dx + 4 * s, dy - 4 * s, ink, 0.7, 1.8 * s)
        if lay["more"] is not None:
            cv.text("и ещё %d…" % (len(tasks) - 12), sc(12), lay["more"], w - sc(24), sc(22), ink, 0.6,
                    ("Segoe UI", sc(11), 0), align=1)
        if not tasks:
            cv.text("Задач пока нет", 0, a[3] + sc(8), w, sc(36), ink, 0.5, ("Segoe UI", sc(12), 0), align=1)

    def draw_note(self, cv, w, h, f, ink, hov):
        s = SCALE[0]
        box = (sc(14), TITLE_H + sc(8), w - sc(28), h - TITLE_H - sc(22))
        txt = f.get("note", "")
        fnt = ("Segoe UI", sc(int(f.get("font", 14))), 0)
        if txt:
            cv.text(txt, box[0], box[1], box[2], box[3], ink, 1.0, fnt, align=0, valign=0, wrap=True)
        else:
            cv.text("Нажмите, чтобы написать…", box[0], box[1], box[2], sc(24), ink, 0.45, fnt, align=0, valign=0)
        for i in (0, 5, 10):
            cv.line(w - sc(6) - sc(i), h - sc(5), w - sc(5), h - sc(6) - sc(i), ink, 0.45, 1.5 * s)

    def draw_timer(self, cv, w, h, f, ink, hov):
        app = self.app
        t, ts, now = app.cfg["timer"], app.tstate, time.time()
        lay = timer_layout(f)

        def hv(act):
            return bool(hov and hov[1] == "wact" and hov[2] == act)
        for key, label in (("pomodoro", "Помидоро"), ("stopwatch", "Секундомер")):
            r = lay["tabs"][key]
            sel = t["mode"] == key
            if sel:
                cv.fill_rr(r[0], r[1], r[2] - r[0], r[3] - r[1], sc(10), f["bar"], 1.0)
            elif hv(("timer", "mode", key)):
                cv.fill_rr(r[0], r[1], r[2] - r[0], r[3] - r[1], sc(10), ink, 0.12)
            cv.text(label, r[0], r[1], r[2] - r[0], r[3] - r[1], f["text"] if sel else ink, 1.0 if sel else 0.7,
                    ("Segoe UI", sc(12), 1 if sel else 0), align=1)
        tr = lay["task"]
        if hv(("timer", "task")):
            cv.fill_rr(tr[0], tr[1], tr[2] - tr[0], tr[3] - tr[1], sc(8), ink, 0.12)
        title = app.task_title(t.get("task")) if t["mode"] == "pomodoro" else "Время идёт вперёд"
        cv.text(("Задача: " + (title or "без задачи")) if t["mode"] == "pomodoro" else title,
                tr[0] + sc(6), tr[1], tr[2] - tr[0] - sc(12), tr[3] - tr[1], ink, 0.8, ("Segoe UI", sc(11), 0),
                align=1)
        rx, ry, rx2, _ = lay["ring"]
        d = rx2 - rx
        inset = sc(5)
        cv.ellipse(rx + inset, ry + inset, d - 2 * inset, d - 2 * inset, ink, 0.16, fill=False, width=sc(7))
        if t["mode"] == "pomodoro":
            total = max(1.0, ts.phase_seconds())
            rem = ts.remaining(now)
            col = f["bar"] if t["phase"] == "work" else "#3FB950"
            cv.arc(rx + inset, ry + inset, d - 2 * inset, d - 2 * inset, -90, 360.0 * rem / total, col, 1.0, sc(7))
            main = fmt_clock(rem + 0.999)
            sub = {"work": "Работа", "short": "Перерыв", "long": "Длинный перерыв"}[t["phase"]]
            sub += "  ·  %d" % t.get("done", 0)
        else:
            el = ts.elapsed(now)
            cv.arc(rx + inset, ry + inset, d - 2 * inset, d - 2 * inset, -90, 360.0 * (el % 60.0) / 60.0,
                   f["bar"], 1.0, sc(7))
            main, sub = fmt_clock(el), "Секундомер"
        cv.text(main, rx, ry + d * 0.22, d, d * 0.36, ink, 1.0, ("Segoe UI", sc(22), 1), align=1)
        cv.text(sub, rx + sc(6), ry + d * 0.60, d - sc(12), sc(18), ink, 0.65, ("Segoe UI", sc(10), 0), align=1)
        sym = ("Segoe UI Symbol", sc(15), 0)
        for key, r in lay["btn"].items():
            if key == "skip" and t["mode"] != "pomodoro":
                continue
            bw = r[2] - r[0]
            if key == "toggle":
                cv.ellipse(r[0], r[1], bw, r[3] - r[1], f["bar"], 1.0)
                glyph, col = ("❚❚" if t["running"] else "▶"), f["text"]
            else:
                if hv(("timer", key)):
                    cv.ellipse(r[0], r[1], bw, r[3] - r[1], ink, 0.14)
                glyph, col = ("↺" if key == "reset" else "⏭"), ink
            cv.text(glyph, r[0], r[1], bw, r[3] - r[1], col, 1.0, sym, align=1)

    def draw_sysmon(self, cv, w, h, f, ink, hov):
        v = self.app.sysvals
        for i, key in enumerate(f.get("metrics", [])):
            r = sysmon_row(f, i)
            lw = r[2] - r[0]
            label, val, frac, extra = "", "", None, ""
            if key == "cpu":
                label, val, frac = "Процессор", "%d%%" % round(v["cpu"]), v["cpu"] / 100.0
            elif key == "ram":
                label, val, frac = "Память", "%d%%" % round(v["ram"]), v["ram"] / 100.0
            elif key == "disk":
                dk = v["disks"][0] if v["disks"] else ("", 0.0, 0.0)
                label = "Диск " + dk[0]
                val, frac = "свободно %.0f ГБ" % dk[2], dk[1] / 100.0
            elif key == "net":
                label = "Сеть"
                val = "↓ %s   ↑ %s" % (fmt_speed(v["down"]), fmt_speed(v["up"]))
            cv.text(label, r[0], r[1], lw // 2, sc(20), ink, 0.85, ("Segoe UI", sc(12), 1))
            cv.text(val, r[0] + lw // 3, r[1], lw - lw // 3, sc(20), ink, 1.0, ("Segoe UI", sc(12), 0), align=2)
            if frac is not None:
                bw, by = lw, r[1] + sc(25)
                cv.fill_rr(r[0], by, bw, sc(8), sc(4), ink, 0.14)
                if frac > 0.005:
                    col = "#E5534B" if frac > 0.85 else f["bar"]
                    cv.fill_rr(r[0], by, max(sc(8), int(bw * min(1.0, frac))), sc(8), sc(4), col, 1.0)

    def draw_clipboard(self, cv, w, h, f, ink, hov):
        app = self.app
        allv = app.cliph.all()
        lay = clip_layout(f, min(len(allv), int(f.get("rows", 8))))

        def hv(act):
            return bool(hov and hov[1] == "wact" and hov[2] == act)
        hd = lay["head"]
        cv.text("Записей: %d" % len(allv), hd[0] + sc(2), hd[1], hd[2] - hd[0] - sc(90), hd[3] - hd[1], ink, 0.7,
                ("Segoe UI", sc(11), 0))
        if allv:
            if hv(("clip", "clear")):
                cv.fill_rr(hd[2] - sc(88), hd[1], sc(88), hd[3] - hd[1], sc(8), ink, 0.12)
            cv.text("Очистить", hd[2] - sc(88), hd[1], sc(88), hd[3] - hd[1], ink, 0.8, ("Segoe UI", sc(11), 0), align=1)
        for i, row, pin, dele in lay["rows"]:
            over = hv(("clip", "copy", i)) or hv(("clip", "pin", i)) or hv(("clip", "del", i))
            pinned = app.cliph.is_pinned(i)
            if over:
                cv.fill_rr(row[0], row[1], row[2] - row[0], row[3] - row[1], sc(8), ink, 0.10)
            text = allv[i].replace("\r", "").replace("\n", " ↵ ").replace("\t", " ")
            tw = (pin[0] if (over or pinned) else row[2]) - row[0] - sc(14)
            cv.text(text, row[0] + sc(6), row[1], tw, row[3] - row[1], ink, 1.0, ("Segoe UI", sc(12), 0))
            if over or pinned:
                cv.text("★" if pinned else "☆", pin[0], pin[1], pin[2] - pin[0], pin[3] - pin[1],
                        f["bar"] if pinned else ink, 1.0 if pinned else 0.7, ("Segoe UI Symbol", sc(13), 0), align=1)
            if over:
                dx, dy = (dele[0] + dele[2]) / 2.0, (dele[1] + dele[3]) / 2.0
                u = 4 * SCALE[0]
                cv.line(dx - u, dy - u, dx + u, dy + u, ink, 0.7, 1.8 * SCALE[0])
                cv.line(dx - u, dy + u, dx + u, dy - u, ink, 0.7, 1.8 * SCALE[0])
        if not allv:
            cv.text("Скопируйте текст — он появится здесь", 0, hd[3] + sc(8), w, sc(40), ink, 0.5,
                    ("Segoe UI", sc(12), 0), align=1)

    def draw_search(self, cv, w, h, f, ink, hov):
        s = SCALE[0]
        r = search_layout(f)
        over = bool(hov and hov[1] == "wact" and hov[2] == ("search", "open"))
        cv.fill_rr(r[0], r[1], r[2] - r[0], r[3] - r[1], (r[3] - r[1]) // 2, ink, 0.20 if over else 0.12)
        cx, cy = r[0] + sc(20), (r[1] + r[3]) / 2.0
        d = int(11 * s)
        cv.ellipse(cx - d / 2.0 - 2 * s, cy - d / 2.0 - 2 * s, d, d, ink, 0.75, fill=False, width=1.8 * s)
        cv.line(cx + 3 * s, cy + 3 * s, cx + 8 * s, cy + 8 * s, ink, 0.75, 2.0 * s)
        hk = self.app.cfg["search"].get("hotkey", "")
        hint = hk if hk and hk != "off" else ""
        cv.text("Найти программу, файл, посчитать…", r[0] + sc(38), r[1], r[2] - r[0] - sc(44) - sc(100),
                r[3] - r[1], ink, 0.8, ("Segoe UI", sc(12), 0))
        if hint:
            cv.text(hint, r[2] - sc(118), r[1], sc(104), r[3] - r[1], ink, 0.4, ("Segoe UI", sc(10), 0), align=2)

    def draw(self, cv, w, h):
        f, app, R = self.f, self.app, self.R
        body_a = float(f.get("alpha", 0.8))
        bar_a = min(0.97, max(0.4, body_a + 0.2))
        txt = f.get("text", "#FFFFFF")
        ink = contrast(f["color"])
        s = SCALE[0]
        hov = app.hover if app.hover and app.hover[0] == f["id"] else None
        compact = h <= TITLE_H + 2                       # свёрнута: только заголовок
        corners = "tl tr br bl" if compact else "tl tr"
        if app.cfg.get("look", "modern") == "modern":
            # современный вид: мягкий градиент «матового стекла», заголовок светлеет к верху
            cv.grad_rr(0, 0, w, h, R, blend(f["color"], "#FFFFFF", 0.07), blend(f["color"], "#000000", 0.16),
                       body_a, body_a)
            cv.grad_rr(0, 0, w, min(h, TITLE_H), R, blend(f["bar"], "#FFFFFF", 0.16), blend(f["bar"], "#000000", 0.06),
                       bar_a, bar_a, corners=corners, copy=True)
            if not compact:
                cv.line(sc(10), TITLE_H, w - sc(10), TITLE_H, "#000000", 0.18, 1.0)
        else:
            cv.fill_rr(0, 0, w, h, R, f["color"], body_a)
            cv.fill_rr(0, 0, w, min(h, TITLE_H), R, f["bar"], bar_a, copy=True, corners=corners)
        # кнопки заголовка: нарисованы линиями, при наведении - подсветка
        pad = sc(3)
        for kind, bx in (("collapse", 0), ("palette", w - 2 * TITLE_H), ("menu", w - TITLE_H)):
            if hov and hov[1] == kind:
                cv.fill_rr(bx + pad, pad, TITLE_H - 2 * pad, TITLE_H - 2 * pad, sc(8), txt, 0.20)
        cx, cy, u = TITLE_H / 2.0, TITLE_H / 2.0, 2.0 * s
        lw = 2.0 * s
        if f.get("collapsed"):
            cv.polyline([(cx - u, cy - 2 * u), (cx + u, cy), (cx - u, cy + 2 * u)], txt, 1.0, lw)
        else:
            cv.polyline([(cx - 2 * u, cy - u), (cx, cy + u), (cx + 2 * u, cy - u)], txt, 1.0, lw)
        px, d = w - 2 * TITLE_H + TITLE_H / 2.0, int(round(12 * s))     # палитра: кольцо с залитой половиной
        cv.ellipse(px - d / 2.0, cy - d / 2.0, d, d, txt, 0.95, fill=False, width=1.6 * s)
        cv.pie(px - d / 2.0, cy - d / 2.0, d, d, 270, 180, txt, 0.95)
        mx = w - TITLE_H + TITLE_H / 2.0                              # меню: три полоски
        for dy in (-4, 0, 4):
            cv.line(mx - 6 * s, cy + dy * s, mx + 6 * s, cy + dy * s, txt, 0.95, 1.7 * s)
        count = f.get("collapsed") and app.eng.has_files(f)
        label = app.eng.title(f) + ("  (%d)" % len(app.eng.items(f)) if count else "")
        gm = group_members(app.cfg, f.get("group")) if f.get("group") else []
        badge = sc(62) if len(gm) > 1 else 0
        cv.text(label, TITLE_H + sc(4), 0, w - 3 * TITLE_H - sc(8) - badge, TITLE_H, txt, 1.0, self.TTL)
        if badge:                                   # цветная точка группы и номер «2/3»
            idx = next(i for i, m in enumerate(gm) if m is f) + 1
            bx = w - 2 * TITLE_H - sc(8)
            cv.text("%d/%d" % (idx, len(gm)), bx - sc(34), 0, sc(34), TITLE_H, txt, 0.85, ("Segoe UI", sc(11), 0), align=2)
            dd = sc(9)
            cv.ellipse(bx - sc(34) - dd - sc(4), (TITLE_H - dd) // 2, dd, dd, group_color(f["group"]), 1.0)
        kind = f.get("kind", "files")
        try:
            if h > TITLE_H + sc(4) and kind in ("calendar", "todo", "note", "timer", "sysmon", "clipboard", "search"):
                getattr(self, "draw_" + kind)(cv, w, h, f, ink, hov)
        except Exception:
            log("draw %s failed:\n%s" % (kind, traceback.format_exc()))
        # значки
        if h > TITLE_H + sc(4) and kind == "files":
            isz, labels = sc(int(f.get("icon", 32))), f.get("labels")
            cw, ch = app.eng.cell(f)
            for k, it in enumerate(app.eng.items(f)):
                sx, sy = app.eng.slot(f, k)
                if sy >= h:
                    break
                selected = (f["id"], it["name"]) in app.sel
                hovered = bool(hov and hov[1] == "item" and hov[2] == it["name"])
                if selected or hovered:
                    cv.fill_rr(sx + sc(2), sy + sc(2), cw - sc(4), ch - sc(4), sc(9), ink,
                               0.28 if (selected and hovered) else (0.20 if selected else 0.10))
                cv.icon(it["path"], sx + (cw - isz) // 2, sy + sc(8), isz)
                if it.get("up"):                         # «на уровень выше»
                    cv.text("↑", sx + (cw - isz) // 2, sy + sc(8), isz, isz, f["bar"], 1.0,
                            ("Segoe UI", max(sc(14), int(isz * 0.6)), 1), align=1)
                if labels:
                    cv.text(it["label"], sx + sc(3), sy + isz + sc(12), cw - sc(6), ch - isz - sc(14),
                            ink, 1.0, ("Segoe UI", sc(11), 0), align=1, valign=0, wrap=True)
            for i in (0, 5, 10):                         # уголок изменения размера
                cv.line(w - sc(6) - sc(i), h - sc(5), w - sc(5), h - sc(6) - sc(i), ink, 0.45, 1.5 * s)
        # рамка и подсветка цели при перетаскивании значка
        cv.stroke_rr(0, 0, w - 1, h - 1, R, ink, 0.18, 1.0)
        if app.hot == f["id"]:
            cv.stroke_rr(1, 1, w - 3, h - 3, R, f["bar"], 0.95, 3.0 * s)


class DockViewGP(object):
    """Панель быстрого доступа: узкая «таблетка» сверху экрана, запуск одним нажатием."""

    def __init__(self, app):
        self.app, self.f = app, app.cfg["dock"]
        self.topmost = bool(self.f.get("topmost"))
        spec = ("overlay", None, HWND_TOPMOST) if self.topmost else app.spec
        d = self.f
        self.win = LayerWin(spec, d["x"], d["y"], d["w"], d["h"])
        self.render()

    def update(self):
        if bool(self.f.get("topmost")) != self.topmost:
            return False                               # смена режима «поверх всех» - пересоздать
        self.render()
        return True

    def render(self):
        d = self.f
        self.win.render(self.draw, d["x"], d["y"], d["w"], d["h"])

    def repaint(self):
        self.render()

    def place(self):
        self.render()

    def keep_above_desktop(self):
        if not self.topmost:
            self.win.keep_above_desktop()

    def destroy(self):
        self.win.destroy()

    def draw(self, cv, w, h):
        d, app = self.f, self.app
        ink = contrast(d["color"])
        s = SCALE[0]
        items = app.eng.items(d)
        rects, add = dock_rects(d, len(items))
        hov = app.hover if app.hover and app.hover[0] == "dock" else None
        R = h // 2
        da = float(d.get("alpha", 0.85))
        if app.cfg.get("look", "modern") == "modern":
            cv.grad_rr(0, 0, w, h, R, blend(d["color"], "#FFFFFF", 0.09), blend(d["color"], "#000000", 0.16), da, da)
        else:
            cv.fill_rr(0, 0, w, h, R, d["color"], da)
        cv.stroke_rr(0, 0, w - 1, h - 1, R, ink, 0.18, 1.0)
        isz = sc(int(d.get("icon", 40)))
        for it, r in zip(items, rects):
            if hov and hov[1] == "dockitem" and hov[2] == it["name"]:
                cv.fill_rr(r[0], r[1], r[2] - r[0], r[3] - r[1], sc(14), ink, 0.16)
            cv.icon(it["path"], r[0] + (r[2] - r[0] - isz) // 2, r[1] + sc(6), isz)
        over = bool(hov and hov[1] == "dockadd")
        cx, cy = (add[0] + add[2]) / 2.0, (add[1] + add[3]) / 2.0
        if over:                                          # едва заметный плюс; ярче только при наведении
            dd = int(18 * s)
            cv.ellipse(cx - dd / 2.0, cy - dd / 2.0, dd, dd, ink, 0.16)
        a = 0.9 if over else 0.28
        cv.line(cx - 4 * s, cy, cx + 4 * s, cy, ink, a, 1.5 * s)
        cv.line(cx, cy - 4 * s, cx, cy + 4 * s, ink, a, 1.5 * s)
        if not items:
            cv.text("Нажмите + или перетащите сюда ярлык", add[2] + sc(4), 0, w - add[2] - sc(14), h, ink, 0.6,
                    ("Segoe UI", sc(12), 0))
        if app.hot == "dock":
            cv.stroke_rr(1, 1, w - 3, h - 3, R, d["bar"], 0.95, 3.0 * s)


WIDGET_POS = {"calendar": (80, 120), "todo": (440, 120), "timer": (800, 120), "note": (80, 520),
              "sysmon": (800, 480), "clipboard": (1160, 120), "search": (1160, 560)}


class UiKit(object):
    """Единый стиль окон и меню: цвета, кнопки, поля ввода, галочки."""

    def pal(self):
        return ui_palette(self.cfg["dock"].get("bar") or "#4C8DFF")

    def ui_window(self, title, resizable=False):
        c = self.pal()
        d = self.tk.Toplevel(self.root)
        d.title(title)
        d.configure(bg=c["bg"])
        d.attributes("-topmost", True)
        d.resizable(resizable, resizable)
        return d

    def ui_label(self, parent, text, bold=False, mute=False, size=10, **kw):
        c = self.pal()
        return self.tk.Label(parent, text=text, bg=c["bg"], fg=c["mute"] if mute else c["fg"],
                             font=("Segoe UI", size, "bold" if bold else "normal"), justify="left", **kw)

    def ui_button(self, parent, text, cmd, accent=False, **kw):
        c = self.pal()
        bg, hi = (c["acc"], c["acc_hi"]) if accent else (c["btn"], c["btn_hi"])
        b = self.tk.Label(parent, text=text, bg=bg, fg="#FFFFFF" if accent else c["fg"], font=("Segoe UI", 10),
                          padx=14, pady=6, cursor="hand2", **kw)
        b.bind("<Enter>", lambda _e: b.configure(bg=hi))
        b.bind("<Leave>", lambda _e: b.configure(bg=bg))
        b.bind("<Button-1>", lambda _e: cmd())
        return b

    def ui_check(self, parent, text, value, cmd):
        """Галочка: cmd(новое значение) вызывается при щелчке."""
        c = self.pal()
        state = {"v": bool(value)}
        lb = self.tk.Label(parent, bg=c["bg"], fg=c["fg"], font=("Segoe UI", 10), anchor="w", cursor="hand2",
                           justify="left", padx=2, pady=3)

        def paint():
            lb.configure(text=("☑  " if state["v"] else "☐  ") + text,
                         fg=c["acc_hi"] if state["v"] else c["fg"])

        def click(_e=None):
            state["v"] = not state["v"]
            paint()
            cmd(state["v"])
        lb.bind("<Button-1>", click)
        paint()
        return lb

    def ui_entry(self, parent, var, width=46):
        c = self.pal()
        return self.tk.Entry(parent, textvariable=var, width=width, bg=c["panel"], fg=c["fg"],
                             insertbackground=c["fg"], relief="flat", font=("Segoe UI", 11),
                             highlightthickness=1, highlightbackground=c["line"], highlightcolor=c["acc"])

    def ui_sep(self, parent):
        return self.tk.Frame(parent, height=1, bg=self.pal()["line"])

    # --- диалоги ---------------------------------------------------------------------
    def ask_choice(self, title, text, buttons=("OK",), away=False):
        tk = self.tk
        res = {"v": buttons[-1]}
        d = self.ui_window(title)
        body = tk.Frame(d, bg=self.pal()["bg"], padx=22, pady=18)
        body.pack()
        self.ui_label(body, text, size=11).pack(anchor="w")
        row = tk.Frame(body, bg=self.pal()["bg"])
        row.pack(anchor="e", pady=(16, 0))

        def pick(b):
            res["v"] = b
            d.destroy()
        for i, b in enumerate(buttons):
            self.ui_button(row, b, lambda b=b: pick(b), accent=(i == 0 and len(buttons) > 1)).pack(side="left", padx=4)
        d.protocol("WM_DELETE_WINDOW", d.destroy)
        d.bind("<Escape>", lambda _e: d.destroy())
        self._place_dialog(d, away)
        d.focus_force()
        self.root.wait_window(d)
        return res["v"]

    def ask_string(self, title, prompt, initial=""):
        tk = self.tk
        res = {"v": None}
        d = self.ui_window(title)
        body = tk.Frame(d, bg=self.pal()["bg"], padx=22, pady=18)
        body.pack()
        self.ui_label(body, prompt, size=11).pack(anchor="w", pady=(0, 8))
        var = tk.StringVar(value=initial)
        e = self.ui_entry(body, var)
        e.pack(fill="x", ipady=5)

        def ok(_e=None):
            res["v"] = var.get()
            d.destroy()
        row = tk.Frame(body, bg=self.pal()["bg"])
        row.pack(anchor="e", pady=(16, 0))
        self.ui_button(row, "OK", ok, accent=True).pack(side="left", padx=4)
        self.ui_button(row, "Отмена", d.destroy).pack(side="left", padx=4)
        d.bind("<Return>", ok)
        d.bind("<Escape>", lambda _e: d.destroy())
        self._place_dialog(d)
        d.focus_force()
        e.focus_set()
        e.select_range(0, "end")
        self.root.wait_window(d)
        return res["v"]

    def ask_text(self, title, prompt, initial=""):
        """Многострочный ввод. -> строка или None (отмена)."""
        tk, c = self.tk, self.pal()
        res = {"v": None}
        d = self.ui_window(title)
        body = tk.Frame(d, bg=c["bg"], padx=22, pady=18)
        body.pack()
        self.ui_label(body, prompt, size=11).pack(anchor="w", pady=(0, 8))
        fr = tk.Frame(body, bg=c["bg"])
        fr.pack()
        t = tk.Text(fr, width=54, height=11, wrap="word", font=("Segoe UI", 11), undo=True, bg=c["panel"],
                    fg=c["fg"], insertbackground=c["fg"], relief="flat", highlightthickness=1,
                    highlightbackground=c["line"], highlightcolor=c["acc"], padx=8, pady=6)
        t.pack(side="left")
        sb = tk.Scrollbar(fr, command=t.yview)
        sb.pack(side="right", fill="y")
        t.configure(yscrollcommand=sb.set)
        t.insert("1.0", initial)

        def ok(_e=None):
            res["v"] = t.get("1.0", "end-1c")
            d.destroy()
            return "break"
        row = tk.Frame(body, bg=c["bg"])
        row.pack(anchor="e", pady=(14, 0))
        self.ui_button(row, "Сохранить  (Ctrl+Enter)", ok, accent=True).pack(side="left", padx=4)
        self.ui_button(row, "Отмена", d.destroy).pack(side="left", padx=4)
        d.bind("<Control-Return>", ok)
        d.bind("<Escape>", lambda _e: d.destroy())
        self._place_dialog(d)
        d.focus_force()
        t.focus_set()
        self.root.wait_window(d)
        return res["v"]

    def toast(self, text, ms=8000):
        """Всплывающее уведомление в правом нижнем углу монитора с курсором; закрывается по клику."""
        try:
            tk, c = self.tk, self.pal()
            t = tk.Toplevel(self.root)
            t.overrideredirect(True)
            t.attributes("-topmost", True)
            fr = tk.Frame(t, bg=c["acc"], padx=0, pady=0)
            fr.pack()
            tk.Frame(fr, width=5, bg=c["acc"]).pack(side="left", fill="y")
            tk.Label(fr, text=text, bg=c["panel"], fg=c["fg"], padx=16, pady=12, justify="left",
                     font=("Segoe UI", 10)).pack(side="left")
            t.update_idletasks()
            w, h = t.winfo_reqwidth(), t.winfo_reqheight()
            l_, t_, r_, b_ = self.work_area()
            t.geometry("+%d+%d" % (r_ - w - 24, b_ - h - 24))
            t.bind("<Button-1>", lambda _e: t.destroy())
            t.after(ms, lambda: t.winfo_exists() and t.destroy())
        except Exception:
            log("toast failed:\n" + traceback.format_exc())


class WidgetLogic(UiKit):
    """Логика виджетов: события календаря, таймер, система, буфер обмена, поиск,
    скрытие по двойному клику, свои значки. Подмешивается в App."""

    def init_widgets(self):
        cfg = self.cfg
        self.tstate = TimerState(cfg["timer"])
        self.cliph = ClipHistory(cfg["clip"])
        self.sysmon = SysMon(sys_readers() if IS_WIN else {})
        self.sysvals = self.sysmon.last
        self.hidden = False
        self.kbd_state = None
        self._save_job = None
        self.drops = None
        self._lmb = False
        self._foreign = False
        self._desk_press = False
        self._drop_until = 0.0
        if IS_WIN and cfg.get("ext_drop", True) and "DropHub" in globals():
            try:
                self.drops = DropHub()
            except Exception:
                log("DropHub failed:\n" + traceback.format_exc())
        self.launcher = None
        self._index, self._index_t, self._index_busy = [], 0.0, False
        self._ics_busy, self._ics_result = False, None
        self._clip_seq = clip_seq() if IS_WIN else None
        self._sys_t = 0.0
        self._last_sec = 0
        ICON_OVR.clear()
        ICON_OVR.update(cfg.get("icons", {}))
        self.ev.hotkey = parse_hotkey(cfg["search"].get("hotkey"))
        self.ev.dbl_on = cfg.get("dblclick", "off") != "off"
        try:
            self.dt.show_icons(True)                     # вдруг в прошлый раз закрылись при скрытых значках
        except Exception:
            pass

    # ---------- общие окна -----------------------------------------------------------
    def work_area(self, x=None, y=None):
        """Рабочая область монитора вокруг точки (по умолчанию - вокруг курсора): (лево, верх, право, низ)."""
        if IS_WIN:
            try:
                if x is None:
                    x, y = self.pointer()
                r = monitor_work(x, y)
                if r:
                    return r
            except Exception:
                log("work_area failed:\n" + traceback.format_exc())
        return 0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight()

    def pointer(self):
        try:
            return self.root.winfo_pointerx(), self.root.winfo_pointery()
        except Exception:
            return 200, 200

    def repaint_kind(self, kind):
        for v in self.views:
            if v.f.get("kind") == kind:
                v.repaint()

    def refit_widgets(self):
        """Высота виджетов, которая зависит от содержимого."""
        for f in self.cfg["fences"]:
            k = f.get("kind", "files")
            if k == "todo":
                f["h"] = widget_height(f, len(self.cfg["todo"]))
            elif k == "clipboard":
                f["h"] = widget_height(f, int(f.get("rows", 8)))
            elif k in ("timer", "sysmon", "search", "calendar"):
                f["h"] = widget_height(f, 0)

    # ---------- группы областей -------------------------------------------------------
    def live_h(self, f):
        """Высота области сейчас на экране (во время анимации - промежуточная)."""
        v = self.view_of(f)
        vh = getattr(v, "vh", None)
        return vh if vh else eff_h(f)

    def group_follow(self, f, final=False):
        """Сосед по группе раскрылся / свернулся: подвинуть остальных, чтобы не перекрывались."""
        if not f.get("group"):
            return
        for m in layout_groups(self.cfg, self.live_h):
            v = self.view_of(m)
            w = getattr(v, "win", None)
            if w is not None:
                w.move(m["x"], m["y"])
            elif v is not None:
                v.place()
        if final:
            self.refresh_zones()
            save_config(self.cfg)

    def fence_label(self, f):
        return f.get("name") or WIDGET_TITLES.get(f.get("kind"), "Область")

    def group_menu(self, f, x, y):
        gid = f.get("group")
        ms = group_members(self.cfg, gid)
        others = [g for g in self.cfg["fences"] if g is not f and not (gid and g.get("group") == gid)]
        add = [("под «%s»" % self.fence_label(g) if not (ms and ms[0].get("gdir") == "h") else
                "после «%s»" % self.fence_label(g), lambda g=g: self.group_with(f, g)) for g in others]
        ent = []
        if len(ms) < 2:
            ent.append(("Сгруппировать с областью:", lambda: None))
            ent += add or [("(других областей пока нет)", lambda: None)]
            ent += [None, ("Подсказка: перетащите заголовок на другую область -", lambda: None),
                    ("они соберутся в группу.", lambda: None)]
            return self.show_popup(ent, *self.pointer())
        lead = ms[0]
        row, acc = lead.get("gdir") == "h", bool(lead.get("gacc"))
        allc = all(m.get("collapsed") for m in ms)
        i = next(k for k, m in enumerate(ms) if m is f)
        ent += [("Свернуть всю группу" if not allc else "Развернуть всю группу", lambda: self.group_toggle_all(gid)),
                (("✓ " if acc else "    ") + "Раскрывать по одной (остальные сворачиваются)", lambda: self.group_set(gid, "gacc", not acc)),
                ("Расположение: " + ("в ряд → в столбец" if row else "в столбец → в ряд"),
                 lambda: self.group_set(gid, "gdir", "v" if row else "h")),
                None]
        if i > 0:
            ent.append(("Поднять в группе" if not row else "Сдвинуть влево", lambda: self.group_move(f, -1)))
        if i < len(ms) - 1:
            ent.append(("Опустить в группе" if not row else "Сдвинуть вправо", lambda: self.group_move(f, 1)))
        if add:
            ent.append(("Добавить в группу область  ▸", lambda: self.show_popup(add, *self.pointer())))
        ent += [None, ("Убрать эту область из группы  (Ctrl + перетаскивание)", lambda: self.ungroup(f)),
                ("Расформировать группу", lambda: self.disband(gid))]
        self.show_popup(ent, *self.pointer())

    def group_set(self, gid, key, val):
        for m in group_members(self.cfg, gid):
            m[key] = val
        layout_groups(self.cfg)
        self.changed()

    def group_move(self, f, d):
        ms = group_members(self.cfg, f.get("group"))
        i = next(k for k, m in enumerate(ms) if m is f)
        j = i + d
        if 0 <= j < len(ms):
            anchor = (ms[0]["x"], ms[0]["y"])
            ms[i], ms[j] = ms[j], ms[i]
            for k, m in enumerate(ms):
                m["gi"] = k
            ms[0]["x"], ms[0]["y"] = anchor                 # якорь группы остаётся на месте
            layout_groups(self.cfg)
            self.changed()

    def group_toggle_all(self, gid):
        ms = group_members(self.cfg, gid)
        collapse = any(not m.get("collapsed") for m in ms)
        for m in ms:
            (self.eng.collapse if collapse else self.eng.expand)(m)
        self.changed()

    def group_target(self, f, x, y):
        """Другая область под курсором (координаты стола) - на неё можно бросить заголовок."""
        for g in reversed(self.cfg["fences"]):
            if g is f or (f.get("group") and g.get("group") == f["group"]):
                continue
            if g["x"] <= x < g["x"] + g["w"] and g["y"] <= y < g["y"] + self.live_h(g):
                return g
        return None

    # ---------- файлы из других программ -------------------------------------------------
    # ---------- клавиатурный режим -------------------------------------------------------
    def kbd_fences(self):
        return [f for f in self.cfg["fences"] if f.get("kind", "files") == "files"]

    def kbd_toggle(self, on=None):
        on = (not self.kbd_state) if on is None else on
        if on == bool(self.kbd_state):
            return
        if on:
            fs = self.kbd_fences()
            if not fs:
                return self.toast("Нет областей с файлами.", 3000)
            self.kbd_state = {"fid": fs[0]["id"], "t": time.time()}
            self.ev.kbd_on = True
            self.kbd_show()
            self.toast("Клавиатура: ←↑↓→ выбор, Tab - следующая область, Enter - открыть,\n"
                       "Backspace - вверх, F2 - имя, Del - удалить, Space - свернуть,\n"
                       "Ctrl+C / X / V - буфер обмена, Esc - выход", 7000)
        else:
            self.ev.kbd_on = False
            self.kbd_state = None
            self.set_hot(None)

    def kbd_fence(self):
        fid = (self.kbd_state or {}).get("fid")
        return next((f for f in self.kbd_fences() if f["id"] == fid), None)

    def kbd_show(self):
        f = self.kbd_fence()
        self.set_hot(f["id"] if f else None)

    def on_key(self, vk, ctrl, shift):
        st = self.kbd_state
        if not st:
            return
        try:
            f = self.kbd_fence()
            fs = self.kbd_fences()
            if vk == 0x1B or f is None:                       # Esc
                return self.kbd_toggle(False)
            if vk == 0x09:                                    # Tab / Shift+Tab
                i = fs.index(f)
                st["fid"] = fs[(i + (-1 if shift else 1)) % len(fs)]["id"]
                self.set_sel(set())
                return self.kbd_show()
            names = [it["name"] for it in self.eng.items(f)]
            cur = next((n for fid, n in self.sel if fid == f["id"]), None)
            i = names.index(cur) if cur in names else -1
            cols = self.eng.cols(f)
            step = {0x25: -1, 0x27: 1, 0x26: -cols, 0x28: cols}.get(vk)
            if step is not None and names:
                j = 0 if i < 0 else max(0, min(len(names) - 1, i + step))
                self.set_sel({(f["id"], names[j])} if names[j] != ".." else set())
            elif vk == 0x0D and cur:                          # Enter
                self.open_item(f, cur)
            elif vk == 0x08:                                  # Backspace
                self.open_item(f, "..") if ".." in names else None
            elif vk == 0x20:                                  # Space
                self.toggle(f)
            elif vk == 0x71 and cur and cur != "..":          # F2
                self.kbd_toggle(False)
                self.rename_item(f, cur)
            elif vk == 0x2E:                                  # Delete
                sel = self.selected_names(f)
                if sel:
                    self.kbd_toggle(False)
                    self.delete_items(f, sel)
            elif ctrl and vk in (0x43, 0x58):                 # Ctrl+C / Ctrl+X
                sel = self.selected_names(f)
                if sel:
                    self.clip([self.item_path(f, n) for n in sel], vk == 0x58)
            elif ctrl and vk == 0x56:
                self.paste_into(f)
            elif ctrl and vk == 0x41:
                self.select_all(f)
            st["t"] = time.time()
        except Exception:
            log("on_key failed:\n" + traceback.format_exc())

    def drop_targets(self):
        """{id: (l, t, r, b)} экранные прямоугольники областей, принимающих файлы."""
        out = {}
        for f in self.cfg["fences"]:
            if f.get("kind", "files") == "files":
                out[f["id"]] = (f["x"] + self.vx, f["y"] + self.vy, f["x"] + f["w"] + self.vx,
                                f["y"] + self.live_h(f) + self.vy)
        d = self.cfg["dock"]
        if d.get("on"):
            out[d["id"]] = (d["x"] + self.vx, d["y"] + self.vy, d["x"] + d["w"] + self.vx, d["y"] + d["h"] + self.vy)
        return out

    def drops_tick(self):
        if self.kbd_state and time.time() - self.kbd_state["t"] > 20:
            self.kbd_toggle(False)
        if not IS_WIN:
            return
        h = self.drops
        now = time.time()
        down = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
        if down == self._lmb and not (h and h.shown):
            return
        px, py = self.pointer()
        if down and not self._lmb:                     # кнопку только что нажали: откуда тянут?
            cls = self.dt.window_at(px, py)[0]
            self._desk_press = cls in ("Progman", "WorkerW")
            self._foreign = cls not in ("Progman", "WorkerW", "KinDeskWnd", "KinDeskDrop", "Shell_TrayWnd") \
                and self.ia.drag is None
        elif not down and self._lmb and self._desk_press:
            self._desk_press = False                   # отпустили значок рабочего стола: проверить сразу,
            for ms in (120, 350, 800):                 # а не ждать обычного цикла синхронизации
                self.root.after(ms, self.fast_sync)
        self._lmb = down
        if h is None or not h.ok:
            return
        if down and self._foreign:
            self._drop_until = now + 0.6
            tg = self.drop_targets()
            fid = next((k for k, (l, t, r, b) in tg.items() if l <= px < r and t <= py < b), None)
            if fid is None:
                if h.shown:
                    h.hide()
                    h.cur = None
            elif h.shown != fid:
                if self.dt.window_at(px, py)[0] in ("Progman", "WorkerW", "KinDeskWnd"):
                    h.show(fid, tg[fid])
            else:
                h.show(fid, tg[fid])                    # держим над областью даже если она сдвинулась
        elif h.shown and now > self._drop_until and not down:
            h.hide()
            h.cur = None
        while h.events:
            e = h.events.popleft()
            if e[0] == "over":
                self.set_hot(e[1])
            elif e[0] == "leave":
                self.set_hot(None)
            elif e[0] == "drop":
                self.set_hot(None)
                self.drop_external(e[1], e[2], e[3])

    def fast_sync(self):
        try:
            if self.ia.drag is None and self.popup is None and self.safe_sync():
                self.refresh()
        except Exception:
            log("fast_sync failed:\n" + traceback.format_exc())

    def drop_external(self, fid, paths, move):
        """Файлы, брошенные из другой программы, - в папку области (или ярлыками на панель)."""
        try:
            d = self.cfg["dock"]
            if fid == d["id"]:
                for pth in paths:
                    self.eng.add_to_dock(pth)
                self.toast("На панель добавлено: %d" % len(paths), 3000)
            else:
                f = next((g for g in self.cfg["fences"] if g["id"] == fid), None)
                if f is None:
                    return
                n = self.eng.paste(f, paths, move)
                self.toast("%s в «%s»: %d" % ("Перемещено" if move else "Скопировано", f["name"], n), 3000)
            self.changed()
        except Exception:
            log("drop_external failed:\n" + traceback.format_exc())

    def set_hot(self, hid):
        if hid == self.hot:
            return
        old, self.hot = self.hot, hid
        for v in self.views:
            if v.f["id"] in (old, hid):
                v.repaint()

    def group_with(self, f, g):
        """Поставить f в группу области g сразу после неё (создав группу, если её не было)."""
        self.ungroup(f, relayout=False)
        gid = g.get("group")
        fresh = not gid
        if fresh:
            gid = uuid.uuid4().hex[:6]
            g["group"] = gid
        ms = [m for m in group_members(self.cfg, gid) if m is not f] or [g]
        ms.insert(next(k for k, m in enumerate(ms) if m is g) + 1, f)
        lead = ms[0]
        for k, m in enumerate(ms):
            m["group"], m["gi"] = gid, k
            m["gdir"], m["gacc"] = lead.get("gdir", "v"), lead.get("gacc", False)
        layout_groups(self.cfg)
        self.changed()
        if fresh:
            self.toast("Область добавлена в группу. Группа двигается целиком за любой заголовок.\n"
                       "Ctrl + перетаскивание заголовка выводит область из группы.\n"
                       "Настройки группы: меню области → «Группа».", 9000)

    def ungroup(self, f, relayout=True):
        gid = f.get("group")
        f["group"] = None
        f.pop("gi", None)
        rest = group_members(self.cfg, gid)
        if len(rest) == 1:
            rest[0]["group"] = None
        if relayout:
            self.changed()

    def disband(self, gid):
        for m in group_members(self.cfg, gid):
            m["group"] = None
        self.changed()

    # ---------- заметки ---------------------------------------------------------------
    def add_note(self):
        n = sum(1 for f in self.cfg["fences"] if f.get("kind") == "note")
        x, y = WIDGET_POS["note"]
        f = make_widget("note", x + 30 * n - self.vx, y + 30 * n - self.vy)
        self.cfg["fences"].append(f)
        self.changed()

    def edit_note(self, f):
        v = self.ask_text("Заметка", "Текст заметки:", f.get("note", ""))
        if v is not None:
            f["note"] = v
            self.changed()

    def delete_note(self, f):
        if f in self.cfg["fences"]:
            self.cfg["fences"].remove(f)
        self.changed()

    # ---------- календарь: события ----------------------------------------------------
    def all_events(self):
        return list(self.cfg["events"]) + list(self.cfg["ics_cache"])

    def day_menu(self, f, iso, x, y):
        day = datetime.date.fromisoformat(iso)
        ent = []
        for e in self.cfg["events"]:
            if events_on([e], day):
                mark = {"yearly": " (каждый год)", "monthly": " (каждый месяц)", "weekly": " (каждую неделю)",
                        "daily": " (каждый день)"}.get(e.get("rep"), "")
                ent.append(("✕  " + e["t"] + mark, lambda e=e: self.del_event(e)))
        for t in events_on(self.cfg["ics_cache"], day):
            ent.append(("•  " + t + "  (из подписки)", lambda: None))
        if ent:
            ent.append(None)
        ent.append(("Добавить событие…", lambda: self.add_event(iso)))
        self.show_popup(ent, x, y)

    def add_event(self, iso=None):
        iso = iso or datetime.date.today().isoformat()
        day = datetime.date.fromisoformat(iso)
        v = self.ask_string("Событие", "Событие на %s:" % day.strftime("%d.%m.%Y"))
        if not v or not v.strip():
            return
        text = v.strip()
        x, y = self.pointer()

        def done(rep):
            self.cfg["events"].append({"date": iso, "t": text, "rep": rep})
            self.changed()
        self.show_popup([("Не повторять", lambda: done("none")), ("Каждый год", lambda: done("yearly")),
                         ("Каждый месяц", lambda: done("monthly")), ("Каждую неделю", lambda: done("weekly")),
                         ("Каждый день", lambda: done("daily"))], x, y)

    def del_event(self, e):
        if e in self.cfg["events"]:
            self.cfg["events"].remove(e)
        self.changed()

    def import_ics(self):
        from tkinter import filedialog
        path = filedialog.askopenfilename(title="Файл календаря (.ics)",
                                          filetypes=[("Календарь iCalendar", "*.ics"), ("Все файлы", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
                found = parse_ics(fh.read())
        except Exception:
            log("ics import failed:\n" + traceback.format_exc())
            return self.toast("Не удалось прочитать файл календаря")
        have = {(e["date"], e["t"], e.get("rep")) for e in self.cfg["events"]}
        added = 0
        for e in found:
            if (e["date"], e["t"], e["rep"]) not in have:
                self.cfg["events"].append(e)
                added += 1
        self.changed()
        self.toast("Календарь: добавлено событий — %d" % added)

    def ics_urls_dialog(self):
        v = self.ask_text("Подписки на календари",
                          "Адреса календарей iCal (.ics), по одному в строке. Подойдёт «секретный адрес в формате iCal»\n"
                          "из настроек Google Календаря, а также любые публичные календари:",
                          "\n".join(self.cfg["ics_urls"]))
        if v is None:
            return
        self.cfg["ics_urls"] = [ln.strip() for ln in v.splitlines() if ln.strip()]
        if not self.cfg["ics_urls"]:
            self.cfg["ics_cache"] = []
        self.changed()
        self.fetch_ics()

    def fetch_ics(self):
        urls = list(self.cfg["ics_urls"])
        if not urls or self._ics_busy:
            return
        self._ics_busy = True

        def work():
            out, ok = [], False
            for u in urls:
                try:
                    import urllib.request
                    if u.lower().startswith("webcal://"):
                        u = "https://" + u[9:]
                    req = urllib.request.Request(u, headers={"User-Agent": "KinDesk"})
                    with urllib.request.urlopen(req, timeout=20) as r:
                        data = r.read(5000000)
                    out += parse_ics(data.decode("utf-8", "replace"))
                    ok = True
                except Exception:
                    log("ics fetch failed (%s):\n%s" % (u, traceback.format_exc()))
            self._ics_result = (ok, out)
        threading.Thread(target=work, daemon=True).start()

    # ---------- таймер ---------------------------------------------------------------
    def task_title(self, tid):
        for t in self.cfg["todo"]:
            if t.get("id") == tid:
                return t["t"]
        return None

    def timer_action(self, f, act):
        ts, now = self.tstate, time.time()
        a = act[1]
        if a == "mode":
            ts.set_mode(act[2])
        elif a == "toggle":
            ts.toggle(now)
        elif a == "reset":
            ts.reset()
        elif a == "skip":
            ts.skip(now)
        elif a == "task":
            return self.task_popup()
        save_config(self.cfg)
        self.repaint_kind("timer")

    def task_popup(self):
        t = self.cfg["timer"]
        x, y = self.pointer()
        ent = [(("✓ " if not t.get("task") else "    ") + "Без задачи", lambda: self.set_timer_task(None))]
        for task in [k for k in self.cfg["todo"] if not k.get("d")][:12]:
            ent.append((("✓ " if t.get("task") == task["id"] else "    ") + task["t"],
                        lambda i=task["id"]: self.set_timer_task(i)))
        self.show_popup(ent, x, y)

    def set_timer_task(self, tid):
        self.cfg["timer"]["task"] = tid
        save_config(self.cfg)
        self.repaint_kind("timer")

    def timer_settings(self):
        t = self.cfg["timer"]
        v = self.ask_string("Таймер", "Работа, короткий перерыв, длинный перерыв (минуты) и сколько помидоров\n"
                                       "до длинного перерыва - через запятую:",
                            "%d, %d, %d, %d" % (t["work"], t["short"], t["long"], t["cycles"]))
        if not v:
            return
        try:
            a = [int(x) for x in v.replace(";", ",").split(",")]
            if len(a) != 4 or any(not 1 <= n <= 240 for n in a):
                raise ValueError(v)
        except ValueError:
            return self.toast("Нужно четыре числа через запятую, например: 25, 5, 15, 4")
        t["work"], t["short"], t["long"], t["cycles"] = a
        if not t["running"]:
            self.tstate.reset()
        self.changed()

    def flip(self, d, key):
        d[key] = not d.get(key)
        self.changed()

    def timer_loop(self, now):
        ts, t = self.tstate, self.cfg["timer"]
        r = ts.tick(now)
        if r:
            _, fin, nxt = r
            if fin == "work":
                for task in self.cfg["todo"]:
                    if task.get("id") == t.get("task"):
                        task["pomos"] = int(task.get("pomos", 0)) + 1
                self.repaint_kind("todo")
            if t.get("sound"):
                beep()
            msg = {"work": "Помидор завершён. Время отдохнуть: %d мин." % (t["long"] if nxt == "long" else t["short"]),
                   "short": "Перерыв закончился. За работу!", "long": "Длинный перерыв закончился. За работу!"}[fin]
            self.toast(msg)
            save_config(self.cfg)
            self.repaint_kind("timer")
        elif t["running"] and int(now) != self._last_sec:
            self._last_sec = int(now)
            self.repaint_kind("timer")

    # ---------- система --------------------------------------------------------------
    def sysmon_menu_toggle(self, f, key):
        cur = list(f.get("metrics", []))
        if key in cur:
            if len(cur) == 1:
                return
            cur.remove(key)
        else:
            cur.append(key)
        f["metrics"] = [k for k, _ in SYSMON_METRICS if k in cur]
        self.refit_widgets()
        self.changed()

    def sysmon_loop(self, now):
        fs = [f for f in self.cfg["fences"] if f.get("kind") == "sysmon"]
        if not fs:
            return
        if now - self._sys_t >= min(int(f.get("interval", 2)) for f in fs):
            self._sys_t = now
            self.sysvals = self.sysmon.sample(now)
            self.repaint_kind("sysmon")

    # ---------- буфер обмена ---------------------------------------------------------
    def clip_action(self, f, act):
        a, allv = act[1], self.cliph.all()
        if a == "copy" and 0 <= act[2] < len(allv):
            try:
                clip_set_text(allv[act[2]])
                self._clip_seq = clip_seq()               # не записывать это же заново
            except Exception:
                log("clip_set_text failed:\n" + traceback.format_exc())
            return
        if a == "pin":
            self.cliph.toggle_pin(act[2])
        elif a == "del":
            self.cliph.delete(act[2])
        elif a == "clear":
            self.cliph.clear()
        save_config(self.cfg)
        self.refresh_zones()
        self.repaint_kind("clipboard")

    def clip_loop(self):
        if not self.widget_on("clipboard"):
            return
        seq = clip_seq()
        if seq == self._clip_seq:
            return
        self._clip_seq = seq
        text = clip_get_text()
        if text is None or text.startswith("\0"):         # не текст или помечено как пароль
            return
        if self.cliph.add(text[:5000]):
            if self.cfg["clip"].get("persist"):
                save_config(self.cfg)
            self.refresh_zones()
            self.repaint_kind("clipboard")

    # ---------- поиск ----------------------------------------------------------------
    def build_index(self):
        if self._index_busy:
            return
        self._index_busy = True
        roots = []
        for env in ("ProgramData", "APPDATA"):
            base = os.environ.get(env)
            if base:
                roots.append((os.path.join(base, "Microsoft", "Windows", "Start Menu", "Programs"), 4))
        roots += [(d, 1) for d in desktop_dirs()]
        roots.append((FENCE_ROOT, 3))
        roots += [(p_, 3) for p_ in self.cfg["search"].get("folders", [])]

        def work():
            try:
                self._index = search_index(roots)
                self._index_t = time.time()
            except Exception:
                log("index failed:\n" + traceback.format_exc())
            self._index_busy = False
        threading.Thread(target=work, daemon=True).start()

    def open_launcher(self):
        if self.launcher is not None:
            try:
                self.launcher.focus_force()
                return
            except Exception:
                self.launcher = None
        if time.time() - self._index_t > 600:
            self.build_index()
        tk = self.tk
        d = tk.Toplevel(self.root)
        d.overrideredirect(True)
        d.attributes("-topmost", True)
        c = self.pal()
        bg = c["bg"]
        outer = tk.Frame(d, bg=c["line"], padx=1, pady=1)
        outer.pack()
        box = tk.Frame(outer, bg=bg, padx=14, pady=12)
        box.pack()
        var = tk.StringVar()
        ent = tk.Entry(box, textvariable=var, width=44, font=("Segoe UI", 17), bg=c["panel"], fg=c["fg"],
                       insertbackground=c["fg"], relief="flat")
        ent.pack(fill="x", ipady=6)
        lb = tk.Listbox(box, width=70, height=8, font=("Segoe UI", 12), bg=bg, fg=c["fg"], bd=0,
                        highlightthickness=0, selectbackground=c["acc"], activestyle="none")
        lb.pack(fill="x", pady=(8, 0))
        rows = []

        def refresh_rows(*_a):
            q = var.get().strip()
            rows[:] = []
            if q:
                val = safe_calc(q)
                if val is not None:
                    rows.append(("=  %s      (Enter - скопировать)" % fmt_number(val), ("copy", fmt_number(val))))
                for label, path in search_rank(self._index, q):
                    rows.append(("%s      %s" % (label, os.path.dirname(path)), ("open", path)))
                rows.append(("Искать в интернете:  " + q, ("web", q)))
            lb.delete(0, "end")
            for r in rows:
                lb.insert("end", r[0])
            if rows:
                lb.selection_set(0)
            lb.configure(height=max(1, len(rows)))

        def close(_e=None):
            self.launcher = None
            try:
                d.destroy()
            except Exception:
                pass

        def run(_e=None):
            sel = lb.curselection()
            if not rows or not sel:
                return "break"
            act = rows[sel[0]][1]
            close()
            if act[0] == "open":
                self.open_path(act[1])
            elif act[0] == "copy":
                try:
                    clip_set_text(act[1])
                except Exception:
                    log("calc copy failed:\n" + traceback.format_exc())
            else:
                import urllib.parse
                import webbrowser
                webbrowser.open(self.cfg["search"]["web"].replace("{q}", urllib.parse.quote(act[1])))
            return "break"

        def move(delta):
            if not rows:
                return "break"
            sel = lb.curselection()
            i = max(0, min(len(rows) - 1, (sel[0] if sel else 0) + delta))
            lb.selection_clear(0, "end")
            lb.selection_set(i)
            lb.see(i)
            return "break"
        var.trace_add("write", refresh_rows)
        ent.bind("<Return>", run)
        ent.bind("<Down>", lambda _e: move(1))
        ent.bind("<Up>", lambda _e: move(-1))
        ent.bind("<Tab>", lambda _e: move(1))
        d.bind("<Escape>", close)
        lb.bind("<ButtonRelease-1>", run)
        d.bind("<FocusOut>", lambda _e: d.after(150, lambda: (d.focus_displayof() is None) and close()))
        d.update_idletasks()
        w, h = d.winfo_reqwidth(), d.winfo_reqheight()
        l_, t_, r_, b_ = self.work_area()
        d.geometry("+%d+%d" % (l_ + (r_ - l_ - w) // 2, t_ + int((b_ - t_) * 0.2)))
        self.launcher = d
        try:                                              # разрешить забрать фокус клавиатуры
            user32.keybd_event(0x12, 0, 0, 0)
            user32.keybd_event(0x12, 0, 2, 0)
        except Exception:
            pass
        d.focus_force()
        ent.focus_force()

    def search_folders_dialog(self):
        v = self.ask_text("Поиск", "Папки, где искать файлы (по одной в строке).\n"
                                    "Меню «Пуск», рабочий стол и области ищутся всегда:",
                          "\n".join(self.cfg["search"].get("folders", [])))
        if v is None:
            return
        self.cfg["search"]["folders"] = [ln.strip() for ln in v.splitlines() if ln.strip()]
        self._index_t = 0.0
        self.build_index()
        self.changed()

    def search_hotkey_popup(self, x, y):
        cur = self.cfg["search"].get("hotkey")

        def pick(name):
            self.cfg["search"]["hotkey"] = name
            self.changed()
            self.toast("Горячая клавиша поиска изменится после перезапуска программы.")
        ent = [(("✓ " if cur == n else "    ") + n, lambda n=n: pick(n)) for n, _ in SEARCH_HOTKEYS]
        ent.append((("✓ " if cur == "off" else "    ") + "Выключена", lambda: pick("off")))
        self.show_popup(ent, x, y)

    def search_web_dialog(self):
        v = self.ask_string("Поиск в интернете", "Адрес поиска ({q} - то, что вы ввели):",
                            self.cfg["search"]["web"])
        if v and "{q}" in v:
            self.cfg["search"]["web"] = v.strip()
            self.changed()

    # ---------- скрытие по двойному клику ------------------------------------------------
    def dblclick_popup(self, x, y):
        cur = self.cfg.get("dblclick", "off")

        def pick(mode):
            if self.hidden:
                self.hidden = False
                self.apply_hidden()
            self.cfg["dblclick"] = mode
            self.ev.dbl_on = mode != "off"
            self.changed()
        self.show_popup([(("✓ " if cur == m else "    ") + n, lambda m=m: pick(m)) for m, n in
                         (("off", "Выключено"), ("fences", "Скрывать области и виджеты"),
                          ("all", "Скрывать области, виджеты и значки"))], x, y)

    def on_dblclick(self, sx, sy):
        if self.cfg.get("dblclick", "off") == "off" or not self.spec:
            return
        if not self.is_free_desktop_point(sx, sy):
            return
        self.hidden = not self.hidden
        self.close_popup()
        self.set_hover(None, 0, 0)
        self.apply_hidden()
        self.refresh_zones()

    def apply_hidden(self):
        on = not self.hidden
        for v in self.all_views():
            w = getattr(v, "win", None)
            if w is not None:
                w.set_visible(on)
        try:
            self.dt.show_icons(on or self.cfg.get("dblclick") != "all")
        except Exception:
            log("hide icons failed:\n" + traceback.format_exc())

    # ---------- свои значки ----------------------------------------------------------
    def pick_icon(self, path):
        from tkinter import filedialog
        src = filedialog.askopenfilename(
            title="Выберите значок", filetypes=[("Значки и картинки", "*.ico *.png *.jpg *.jpeg *.bmp *.gif *.exe *.dll"),
                                                ("Все файлы", "*.*")])
        if not src:
            return
        try:
            dst = src
            if os.path.splitext(src)[1].lower() not in (".exe", ".dll", ".icl", ".scr"):
                os.makedirs(os.path.join(APP_DIR, "icons"), exist_ok=True)
                dst = os.path.join(APP_DIR, "icons", uuid.uuid4().hex[:10] + os.path.splitext(src)[1].lower())
                shutil.copyfile(src, dst)                 # копия: не зависит от исходного файла
            self.cfg["icons"][icon_key(path)] = dst
        except Exception:
            log("pick_icon failed:\n" + traceback.format_exc())
            return self.toast("Не удалось использовать этот файл как значок")
        self.apply_icons()

    def reset_icon(self, path):
        self.cfg["icons"].pop(icon_key(path), None)
        self.apply_icons()

    def apply_icons(self):
        ICON_OVR.clear()
        ICON_OVR.update(self.cfg["icons"])
        self.changed()

    def icon_entries(self, path):
        ent = [("Сменить значок…", lambda: self.pick_icon(path))]
        if icon_key(path) in self.cfg["icons"]:
            ent.append(("Вернуть обычный значок", lambda: self.reset_icon(path)))
        return ent

    # ---------- меню виджетов --------------------------------------------------------
    def widget_menu(self, f, x, y):
        kind = f.get("kind")
        ent = [("Развернуть" if f.get("collapsed") else "Свернуть", lambda: self.toggle(f)),
               ("Цветовая схема  ▸", lambda: self.scheme_popup(f, x, y)),
               ("Прозрачность  ▸", lambda: self.alpha_popup(f, x, y))]
        pick = lambda title, opts, key, after=None: (lambda: self.show_popup(   # noqa: E731
            [(("✓ " if f.get(key) == v else "    ") + n, lambda v=v: self.set_prop(f, key, v)) for n, v in opts], x, y))
        if kind == "calendar":
            sun = f.get("first_weekday") == 6
            ent += [None,
                    ("Добавить событие…", lambda: self.add_event()),
                    ("Импортировать файл .ics…", self.import_ics),
                    ("Подписки на календари…", self.ics_urls_dialog),
                    ("Неделя начинается с: " + ("воскресенья" if sun else "понедельника"),
                     lambda: self.toggle_week(f))]
        elif kind == "todo":
            ent.append(("Очистить выполненные", self.clear_done))
        elif kind == "note":
            ent += [None, ("Редактировать…", lambda: self.edit_note(f)),
                    ("Размер текста  ▸", pick("", [("Мелкий (11)", 11), ("Обычный (14)", 14), ("Крупный (18)", 18),
                                                   ("Огромный (26)", 26)], "font")),
                    ("Новая заметка", self.add_note), ("Удалить эту заметку", lambda: self.delete_note(f))]
        elif kind == "timer":
            t = self.cfg["timer"]
            ent += [None, ("Время и циклы…", self.timer_settings),
                    (("✓ " if t.get("auto") else "    ") + "Сразу запускать следующую фазу", lambda: self.flip(t, "auto")),
                    (("✓ " if t.get("sound") else "    ") + "Звуковой сигнал", lambda: self.flip(t, "sound")),
                    ("Задача для помидоров  ▸", self.task_popup)]
        elif kind == "sysmon":
            ent += [None] + [(("✓ " if k in f.get("metrics", []) else "    ") + n,
                              lambda k=k: self.sysmon_menu_toggle(f, k)) for k, n in SYSMON_METRICS]
            ent.append(("Обновление  ▸", pick("", [("Каждую секунду", 1), ("Каждые 2 секунды", 2),
                                                    ("Каждые 5 секунд", 5)], "interval")))
        elif kind == "clipboard":
            c = self.cfg["clip"]
            ent += [None,
                    ("Строк в списке  ▸", pick("", [("5", 5), ("8", 8), ("12", 12), ("16", 16)], "rows")),
                    ("Хранить записей  ▸", lambda: self.show_popup(
                        [(("✓ " if c["max"] == n else "    ") + str(n), lambda n=n: self.set_clip_max(n))
                         for n in (15, 30, 60, 100)], x, y)),
                    (("✓ " if c.get("persist") else "    ") + "Сохранять историю между запусками",
                     lambda: self.flip(c, "persist")),
                    ("Очистить историю", lambda: self.clip_action(f, ("clip", "clear")))]
        elif kind == "search":
            ent += [None, ("Открыть поиск", self.open_launcher),
                    ("Папки для поиска…", self.search_folders_dialog),
                    ("Горячая клавиша  ▸", lambda: self.search_hotkey_popup(x, y)),
                    ("Адрес поиска в интернете…", self.search_web_dialog)]
        ent += [None, ("Группа  ▸" + ("  (в группе)" if f.get("group") else ""), lambda: self.group_menu(f, x, y)),
                ("Стиль окон  ▸", lambda: self.look_popup(x, y)),
                ("Двойной клик по столу  ▸", lambda: self.dblclick_popup(x, y)),
                ("Виджеты  ▸", lambda: self.widgets_popup(x, y)),
                ("Скрыть виджет", lambda: self.toggle_widget(kind))]
        self.show_popup(ent, x, y)

    def set_prop(self, f, key, val):
        f[key] = val
        self.refit_widgets()
        self.changed()

    def set_clip_max(self, n):
        self.cfg["clip"]["max"] = n
        del self.cliph.d["items"][n:]
        self.changed()

    def widget_tip(self, key):
        act = key[2]
        if act[0] == "cal":
            if act[1] == "day":
                evs = events_on(self.all_events(), datetime.date.fromisoformat(act[2]))
                return "\n".join(evs[:6]) if evs else "Добавить событие"
            return {"prev": "Предыдущий месяц", "next": "Следующий месяц", "today": "Вернуться к текущему месяцу"}.get(act[1])
        if act[0] == "timer":
            return {"toggle": "Старт / пауза", "reset": "Сбросить", "skip": "Пропустить фазу",
                    "task": "Выбрать задачу, под которую считаются помидоры"}.get(act[1])
        if act[0] == "clip":
            if act[1] == "copy":
                allv = self.cliph.all()
                return ("Нажмите, чтобы скопировать:\n" + allv[act[2]][:300]) if act[2] < len(allv) else None
            return {"pin": "Закрепить / открепить", "del": "Удалить из истории", "clear": "Очистить историю"}.get(act[1])
        if act[0] == "search":
            return "Открыть поиск"
        if act[0] == "todo":
            return {"add": "Добавить задачу", "del": "Удалить задачу"}.get(act[1], "Отметить выполненной")
        return None


class App(WidgetLogic):
    def __init__(self):
        import tkinter as tk
        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        first_run = not os.path.exists(CFG_PATH)
        self.cfg = load_config()
        old_scale = float(self.cfg.get("scale", 1.0))
        if abs(old_scale - SCALE[0]) > 0.01:             # изменился масштаб экрана: подогнать размеры
            k = SCALE[0] / old_scale
            for f in self.cfg["fences"]:
                f["w"], f["h"] = int(f["w"] * k), int(f["h"] * k)
            log("ui scale %.2f -> %.2f, fences resized" % (old_scale, SCALE[0]))
        self.cfg["scale"] = SCALE[0]
        self.dt = DesktopListView()
        arrange_off = self.dt.prepare()
        self.vx, self.vy, self.vw, self.vh = virtual_metrics()
        try:                                   # начало координат значков - по факту
            ox, oy = self.dt.origin()
            log("listview origin=(%d,%d), virtual origin=(%d,%d)" % (ox, oy, self.vx, self.vy))
            self.vx, self.vy = ox, oy
        except Exception:
            log("origin failed:\n" + traceback.format_exc())
        ORIGIN[0], ORIGIN[1] = self.vx, self.vy
        self.primary = (-self.vx, -self.vy, user32.GetSystemMetrics(0))    # основной монитор в координатах стола
        log("virtual screen: origin=(%d,%d) size=%dx%d" % (self.vx, self.vy, self.vw, self.vh))
        if self.cfg.get("coord_space") != "desk":        # старый конфиг: координаты были экранными
            for f in self.cfg["fences"]:
                f["x"] -= self.vx
                f["y"] -= self.vy
            self.cfg["coord_space"] = "desk"
            save_config(self.cfg)
            log("config migrated to desktop coordinates")
        choose_fence_root()
        self.startup_backup()
        self.eng = FenceEngine(self.cfg, self.dt)
        self.ia = Interaction(self.cfg, self.eng, self.dt)
        self.ia.bounds = (self.vw, self.vh)
        self.views = []
        self.panel = None
        self.popup = None
        self.dockview = None
        self._day = datetime.date.today()
        self.hover = None                      # (id области, вид, имя) под курсором
        self._tip = None
        self._tip_job = None
        self.hot = None                        # область-цель при перетаскивании значка
        self.view_cls = FenceViewClassic
        self.sel = set()                       # выделенные элементы: {(id области, имя файла)}
        self.anchor = None                     # от какого элемента тянется Shift-выделение
        self.ghost = None                      # «призрак» перетаскиваемого значка
        self.spec = None
        self._swatches = {}
        try:                                   # плавная отрисовка, если GDI+ доступен
            if self.cfg.get("renderer") != "classic" and gp_start():
                self.view_cls = FenceViewGP
        except Exception:
            log("gdi+ init failed:\n" + traceback.format_exc())
        log("renderer: " + self.view_cls.__name__)
        self.ev = InputEvents()
        self.init_widgets()
        self.ev.validate = self.is_free_desktop_point
        start_input_thread(self.ev)

        if not arrange_off:
            self.ask_choice("KinDesk",
                            "Не удалось выключить автоматическое расположение значков.\n"
                            "Выключите вручную: ПКМ по рабочему столу → Вид →\n"
                            "«Автоматическое расположение значков».")
        if not self.cfg["fences"]:
            self.cfg["fences"].append(default_fence("Моя область", 200 - self.vx, 200 - self.vy))
        if not self.resolve_parent():
            self.calibrate()
        try:
            n = self.eng.migrate_legacy()
            if n:
                log("migrated %d legacy members into folders" % n)
                save_config(self.cfg)
        except Exception:
            log("migrate failed:\n" + traceback.format_exc())
        self.safe_sync()
        self.refit_widgets()
        self.refresh()
        if first_run:
            save_config(self.cfg)
            self.show_panel()
        self.root.after(20, self.poll)
        self.root.after(self.cfg.get("sync_ms", 800), self.tick)
        self.root.after(500, self.bg_tick)

    # --- слой «позади значков» -------------------------------------------------
    def resolve_parent(self):
        name = self.cfg.get("parent_mode")
        if not name:
            return False
        for n, res in parent_strategies():
            if n == name:
                try:
                    spec = res()
                except Exception:
                    log("strategy failed:\n" + traceback.format_exc())
                    return False
                if spec:
                    self.spec = spec
                    return True
        return False

    def calibrate(self):
        """Автоматически подобрать способ, при котором области лежат ЗА значками
        (зависит от версии Windows и установленных программ вроде Wallpaper Engine)."""
        self.ask_choice(
            "KinDesk: настройка",
            "Сейчас программа сама проверит, как показывать области на вашем\n"
            "рабочем столе. Это займёт несколько секунд, экран будет мигать\n"
            "цветными прямоугольниками.\n\n"
            "Программа сама свернёт все окна на это время и потом вернёт их.", ("Начать",))
        cw, ch = self.dt.spacing()
        sw, sh = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)    # основной монитор
        ix, iy = 200, 200                                  # экранные координаты
        try:
            for ic in self.dt.snapshot():                  # значок на основном мониторе
                sx, sy = ic["x"] + self.vx, ic["y"] + self.vy
                if 0 <= sx < sw - cw and 0 <= sy < sh - ch:
                    ix, iy = sx, sy
                    break
        except Exception:
            log("calibrate snapshot failed:\n" + traceback.format_exc())
        red_rect = (max(0, ix - 40), max(0, iy - 30), cw + 80, ch + 70)
        cell = (ix, iy, cw, ch)
        blue_rect = (sw // 2 - 100, sh // 2 - 60, 200, 120)

        def pump():
            self.root.update()
            time.sleep(0.35)
            self.root.update()

        tray = user32.FindWindowW("Shell_TrayWnd", None)
        if tray:
            user32.SendMessageW(tray, 0x0111, 419, 0)          # «Свернуть все окна»
        self.root.update()
        time.sleep(1.0)
        self.root.update()
        try:
            for label, (px_, py_) in (("красный", (red_rect[0] + red_rect[2] - 10, red_rect[1] + red_rect[3] - 10)),
                                      ("синий", (blue_rect[0] + blue_rect[2] // 2, blue_rect[1] + blue_rect[3] // 2))):
                log("calibrate: под %s прямоугольником: %s, это рабочий стол: %s"
                    % (label, self.dt.window_at(px_, py_), self.dt.is_desktop_point(px_, py_)))
            log("calibrate: экран %dx%d, значок (%d,%d), ячейка %dx%d" % (sw, sh, ix, iy, cw, ch))
        except Exception:
            log("calibrate coverage check failed:\n" + traceback.format_exc())
        try:
            best, best_key = self._calibrate_loop(red_rect, cell, blue_rect, pump, (sw, sh))
        finally:
            if tray:
                user32.SendMessageW(tray, 0x0111, 416, 0)      # вернуть свёрнутые окна
        return self._calibrate_finish(best)

    def _calibrate_loop(self, red_rect, cell, blue_rect, pump, size):
        best, best_key = None, None
        for idx, (name, res) in enumerate(parent_strategies()):
            try:
                spec = res()
            except Exception:
                log("strategy %s failed:\n%s" % (name, traceback.format_exc()))
                continue
            if not spec:
                log("calibrate: %s -> недоступен" % name)
                continue
            r = probe_spec(spec, red_rect, cell, blue_rect, pump, size, (self.vx, self.vy))
            log("calibrate: %s -> %s" % (name, r))
            ok = r["visible"] and (r["icons_above"] or spec[0] == "overlay")
            if ok:
                key = (spec[0] == "child", r["translucent"], -idx)
                if best_key is None or key > best_key:
                    best, best_key = (name, spec, r), key
        return best, best_key

    def _calibrate_finish(self, best):
        if best is None:
            self.ask_choice(
                "KinDesk",
                "Ни один способ не подошёл. Закройте программу и пришлите файл\n"
                "%s\nразработчику - по нему видно, что именно не сработало." % LOG_PATH)
            return False
        name, spec, r = best
        self.spec = spec
        self.cfg["parent_mode"] = name
        self.cfg["translucent"] = bool(r["translucent"])
        save_config(self.cfg)
        self.ask_choice(
            "KinDesk",
            "Готово. Выбран способ:\n%s\n\nПрозрачность областей: %s%s"
            % (name, "работает" if r["translucent"] else "недоступна (области будут сплошными)",
               "\nЗначки в этом режиме лежат под полупрозрачным слоем, но перетаскиваются как обычно."
               if spec[0] == "overlay" else ""))
        return True

    # --- диалоги и меню (свои, чтобы всегда были поверх и не зависели от фокуса) ---
    def _place_dialog(self, d, away=False):
        d.update_idletasks()
        l_, t_, r_, b_ = self.work_area()                # монитор, где сейчас курсор
        sw, sh = r_ - l_, b_ - t_
        w, h = d.winfo_reqwidth(), d.winfo_reqheight()
        x = l_ + (sw - w) // 2 + (sw // 5 if away else 0)
        y = t_ + (sh - h) // 2 + (sh // 5 if away else 0)
        d.geometry("+%d+%d" % (max(l_, x), max(t_, y)))

    def close_popup(self):
        if self.popup is not None:
            try:
                self.popup.destroy()
            except Exception:
                pass
        self.popup = None
        self.ev.popup = None

    def swatch(self, scheme):
        if scheme[0] not in self._swatches:
            img = self.tk.PhotoImage(width=34, height=14)
            img.put(scheme[1], to=(0, 0, 34, 14))
            img.put(scheme[2], to=(0, 0, 34, 6))
            self._swatches[scheme[0]] = img
        return self._swatches[scheme[0]]

    def show_popup(self, items, x, y):
        """Своё всплывающее меню. items: (текст, действие[, схема-образец]) или None.
        «✓ » / четыре пробела в начале - колонка галочек; «▸» в конце - вложенное меню."""
        self.close_popup()
        tk, c = self.tk, self.pal()
        bg, hi = c["panel"], c["acc"]
        p = tk.Toplevel(self.root)
        p.overrideredirect(True)
        p.attributes("-topmost", True)
        frame = tk.Frame(p, bg=c["line"], padx=1, pady=1)
        frame.pack()
        inner = tk.Frame(frame, bg=bg, padx=4, pady=4)
        inner.pack()
        has_chk = any(it and (it[0].startswith("✓ ") or it[0].startswith("    ")) for it in items)
        for it in items:
            if it is None:
                tk.Frame(inner, height=1, bg=c["line"]).pack(fill="x", pady=4, padx=6)
                continue
            text, chk, arrow = it[0], "", ""
            if text.startswith("✓ "):
                chk, text = "✓", text[2:]
            elif text.startswith("    "):
                text = text[4:]
            text = text.rstrip()
            if text.endswith("▸"):
                text, arrow = text[:-1].rstrip(), "▸"
            row = tk.Frame(inner, bg=bg, cursor="hand2")
            row.pack(fill="x")
            parts = [row]
            if has_chk:
                ck = tk.Label(row, text=chk, width=2, fg=c["acc_hi"], bg=bg, font=("Segoe UI", 10, "bold"))
                ck.pack(side="left")
                parts.append(ck)
            if len(it) > 2 and it[2]:
                s = tk.Label(row, image=self.swatch(it[2]), bg=bg)
                s.pack(side="left", padx=(4, 0), pady=3)
                parts.append(s)
            lb = tk.Label(row, text=text, fg=c["fg"], bg=bg, anchor="w", padx=8, pady=5, font=("Segoe UI", 10))
            lb.pack(side="left", fill="x", expand=True)
            parts.append(lb)
            if arrow:
                ar = tk.Label(row, text=arrow, fg=c["mute"], bg=bg, padx=8)
                ar.pack(side="right")
                parts.append(ar)

            def enter(_e, parts=parts):
                for w in parts:
                    w.configure(bg=hi)

            def leave(_e, parts=parts):
                for w in parts:
                    w.configure(bg=bg)

            def click(_e, cb=it[1]):
                self.close_popup()
                self.root.after(10, cb)
            for w in parts:
                w.bind("<Enter>", enter)
                w.bind("<Leave>", leave)
                w.bind("<Button-1>", click)
        p.update_idletasks()
        w, h = p.winfo_reqwidth(), p.winfo_reqheight()
        l_, t_, r_, b_ = self.work_area(x, y)
        x = max(l_, min(int(x), r_ - w - 4))
        y = max(t_, min(int(y), b_ - h - 4))
        p.geometry("+%d+%d" % (x, y))
        self.popup = p
        self.ev.popup = (x, y, x + w, y + h)

    # --- действия ---------------------------------------------------------------
    def changed(self):
        self.refresh()                                  # окна обновляются сразу,
        if self._save_job is None:                      # а запись на диск - с небольшой задержкой
            self._save_job = self.root.after(300, self.flush_save)

    def flush_save(self):
        self._save_job = None
        try:
            save_config(self.cfg)
        except Exception:
            log("save failed:\n" + traceback.format_exc())

    def fence_menu(self, f, x, y):
        kind = f.get("kind", "files")
        if kind in WIDGET_TITLES:
            return self.widget_menu(f, x, y)
        self.show_popup([
            ("Развернуть" if f.get("collapsed") else "Свернуть", lambda: self.toggle(f)),
            ("Переименовать…", lambda: self.rename(f)),
            ("Цветовая схема  ▸", lambda: self.scheme_popup(f, x, y)),
            ("Свой цвет фона…", lambda: self.custom_color(f)),
            ("Прозрачность  ▸", lambda: self.alpha_popup(f, x, y)),
            ("Размер значков  ▸", lambda: self.icon_popup(f, x, y)),
            ("Подписи: " + ("скрыть" if f.get("labels") else "показать"), lambda: self.toggle_labels(f)),
            ("Правила автораскладки…", lambda: self.edit_rules(f)),
            ("Виджеты  ▸", lambda: self.widgets_popup(x, y)),
            ("Группа  ▸" + ("  (в группе)" if f.get("group") else ""), lambda: self.group_menu(f, x, y)),
            ("Двойной клик по столу  ▸", lambda: self.dblclick_popup(x, y)),
            ("Стиль окон  ▸", lambda: self.look_popup(x, y)),
            ("Открыть папку области", lambda: self.open_path(self.eng.folder(f))),
            ("Вернуть всё на рабочий стол", lambda: self.release_all(f)),
            None,
            ("Удалить область", lambda: self.delete(f)),
        ], x, y)

    # --- виджеты: календарь, список дел, панель быстрого доступа ---------------------
    def widget_on(self, kind):
        if kind == "dock":
            return bool(self.cfg["dock"].get("on"))
        return any(f.get("kind") == kind for f in self.cfg["fences"])

    def toggle_widget(self, kind):
        if kind == "dock":
            d = self.cfg["dock"]
            d["on"] = not d.get("on")
            if d["on"]:
                self.eng.folder(d)
        else:
            cur = [f for f in self.cfg["fences"] if f.get("kind") == kind]
            if cur:                                       # выключить: настройки сохраняются
                for f in cur:
                    self.cfg["fences"].remove(f)
                self.cfg["stash"][kind] = cur if kind == "note" else cur[0]
            else:
                st = self.cfg["stash"].pop(kind, None)
                if kind == "note":
                    fs = st if isinstance(st, list) and st else [None]
                else:
                    fs = [st]
                for i, f in enumerate(fs):
                    if not f:
                        ox, oy = WIDGET_POS.get(kind, (300, 200))
                        f = make_widget(kind, ox - self.vx, oy - self.vy)
                    self.cfg["fences"].append(f)
                if kind == "clipboard":
                    self._clip_seq = None                 # подхватить то, что сейчас в буфере
        self.refit_widgets()
        self.changed()

    def widgets_popup(self, x, y):
        ent = [(("✓ " if self.widget_on(k) else "    ") + name, lambda k=k: self.toggle_widget(k))
               for k, name in WIDGETS]
        ent += [None, ("Ещё одна заметка", self.add_note), ("Открыть поиск", self.open_launcher)]
        self.show_popup(ent, x, y)

    def toggle_week(self, f):
        f["first_weekday"] = 0 if f.get("first_weekday") == 6 else 6
        self.changed()

    def widget_action(self, f, act):
        if act[0] == "cal" and act[1] == "day":
            self.day_menu(f, act[2], *self.pointer())
        elif act[0] == "cal":
            y, m = f["cal_y"], f["cal_m"]
            if act[1] == "prev":
                y, m = (y - 1, 12) if m == 1 else (y, m - 1)
            elif act[1] == "next":
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
            else:
                t = datetime.date.today()
                y, m = t.year, t.month
            f["cal_y"], f["cal_m"] = y, m
            self.refresh_zones()                          # даты в зонах дней поменялись
            for v in self.all_views():
                v.repaint()
        elif act[0] == "note":
            self.edit_note(f)
        elif act[0] == "timer":
            self.timer_action(f, act)
        elif act[0] == "clip":
            self.clip_action(f, act)
        elif act[0] == "search":
            self.open_launcher()
        elif act[0] == "todo":
            if act[1] == "add":
                v = self.ask_string("Новая задача", "Что нужно сделать?")
                if v:
                    self.eng.add_task(v)
            elif act[1] == "toggle":
                self.eng.toggle_task(act[2])
            elif act[1] == "del":
                self.eng.delete_task(act[2])
            self.todo_changed()

    def todo_changed(self):
        for f in self.cfg["fences"]:
            if f.get("kind") == "todo":
                f["h"] = widget_height(f, len(self.cfg["todo"]))
        self.changed()

    def clear_done(self):
        self.eng.clear_done()
        self.todo_changed()

    def todo_menu(self, f, i, x, y):
        tasks = self.cfg["todo"]
        if not 0 <= i < len(tasks):
            return

        def edit():
            v = self.ask_string("Задача", "Текст задачи:", tasks[i]["t"])
            if v:
                self.eng.edit_task(i, v)
                self.todo_changed()

        def move(d):
            self.eng.move_task(i, d)
            self.todo_changed()
        self.show_popup([("Редактировать…", edit), ("Выше", lambda: move(-1)), ("Ниже", lambda: move(1)),
                         None, ("Удалить", lambda: self.widget_action(f, ("todo", "del", i)))], x, y)

    def dock_add(self):
        from tkinter import filedialog
        paths = filedialog.askopenfilenames(
            title="Добавить на панель",
            filetypes=[("Программы и ярлыки", "*.exe *.lnk *.bat *.cmd *.url"), ("Все файлы", "*.*")])
        self.dock_add_paths(paths)

    def dock_add_folder(self):
        from tkinter import filedialog
        p = filedialog.askdirectory(title="Добавить папку на панель")
        self.dock_add_paths([p] if p else [])

    def dock_add_paths(self, paths):
        for p in paths or []:
            try:
                self.eng.add_to_dock(os.path.normpath(p))
            except Exception:
                log("add_to_dock failed:\n" + traceback.format_exc())
        self.changed()

    def dock_item_menu(self, name, x, y):
        d = self.cfg["dock"]

        def remove():
            path = os.path.join(self.eng.folder(d), name)
            try:
                if name.lower().endswith((".lnk", ".url")):
                    os.remove(path)                       # это только ярлык - сам файл не затрагивается
                else:
                    self.eng.release_item(d, name)
            except Exception:
                log("dock remove failed:\n" + traceback.format_exc())
            self.changed()
        full = os.path.join(self.eng.folder(d), name)
        self.show_popup([("Открыть", lambda: self.open_path(full))] + self.icon_entries(full) + [
                         ("Настройки панели…", self.dock_settings),
                         None, ("Убрать с панели", remove),
                         ("Вернуть на рабочий стол", lambda: self.return_item(d, name))], x, y)

    def dock_settings(self):
        """Окно настроек панели: значки, размер, порядок добавления - всё в одном месте."""
        if getattr(self, "dock_win", None) is not None:
            try:
                self.dock_win.deiconify()
                self.dock_win.lift()
                return self.dock_build()
            except Exception:
                self.dock_win = None
        w = self.ui_window("Панель быстрого доступа")
        self.dock_win = w
        w.protocol("WM_DELETE_WINDOW", lambda: (setattr(self, "dock_win", None), w.destroy()))
        self.dock_body = self.tk.Frame(w, bg=self.pal()["bg"], padx=20, pady=16)
        self.dock_body.pack()
        self.dock_build()
        self._place_dialog(w)

    def dock_build(self):
        tk, d, c = self.tk, self.cfg["dock"], self.pal()
        fr = self.dock_body
        for ch in list(fr.winfo_children()):
            ch.destroy()
        if not d.get("on"):
            self.ui_label(fr, "Панель сейчас скрыта.", mute=True).pack(anchor="w")
            self.ui_button(fr, "Показать панель", lambda: (self.toggle_widget("dock"), self.dock_build()),
                           accent=True).pack(anchor="w", pady=6)
        self.ui_label(fr, "Значки на панели", bold=True, size=12).pack(anchor="w")
        items = self.eng.items(d)
        if not items:
            self.ui_label(fr, "Пока пусто. Добавьте программу кнопкой ниже\nили перетащите ярлык на панель.",
                          mute=True).pack(anchor="w", pady=8)
        for it in items:
            row = tk.Frame(fr, bg=c["bg"])
            row.pack(fill="x", pady=3)
            own = icon_key(it["path"]) in self.cfg["icons"]
            self.ui_label(row, item_label(it["name"]) + ("   ★ свой значок" if own else ""), width=32,
                          anchor="w").pack(side="left")
            self.ui_button(row, "Сменить значок…", lambda p_=it["path"]: (self.pick_icon(p_), self.dock_build())).pack(side="left", padx=3)
            if own:
                self.ui_button(row, "Сбросить", lambda p_=it["path"]: (self.reset_icon(p_), self.dock_build())).pack(side="left", padx=3)
            self.ui_button(row, "Убрать", lambda n=it["name"]: (self.dock_remove(n), self.dock_build())).pack(side="left", padx=3)
        add = tk.Frame(fr, bg=c["bg"])
        add.pack(fill="x", pady=(10, 4))
        self.ui_button(add, "＋ Программа…", lambda: (self.dock_add(), self.dock_build()), accent=True).pack(side="left", padx=3)
        self.ui_button(add, "＋ Папка…", lambda: (self.dock_add_folder(), self.dock_build())).pack(side="left", padx=3)
        self.ui_label(fr, "Размер значков", bold=True).pack(anchor="w", pady=(12, 4))
        sz = tk.Frame(fr, bg=c["bg"])
        sz.pack(anchor="w")
        for v in (32, 40, 48, 64):
            cur = int(d.get("icon", 40)) == v
            b_ = self.ui_button(sz, str(v), lambda v=v: (d.__setitem__("icon", v), self.changed(), self.dock_build()), accent=cur)
            b_.pack(side="left", padx=2)
        self.ui_check(fr, "Поверх всех окон", d.get("topmost"),
                      lambda v: (d.__setitem__("topmost", v), self.changed())).pack(anchor="w", pady=(10, 0))
        sch = self.ui_button(fr, "Цветовая схема  ▸", lambda: None)
        sch.bind("<Button-1>", lambda _e: self.scheme_popup(d, sch.winfo_rootx(), sch.winfo_rooty() + sch.winfo_height()))
        sch.pack(anchor="w", pady=(8, 0))

    # ---------- настройки, резервные копии ----------------------------------------------
    def safety_backup(self, tag):
        if self.cfg.get("backup_auto", True):
            save_config(self.cfg)
            make_backup(tag)

    def startup_backup(self):
        cfg = self.cfg
        changed = cfg.get("app_version") != APP_VERSION
        newest = max([b[1] for b in list_backups() if b[2] != "manual"] or [0])
        if cfg.get("backup_auto", True) and os.path.exists(CFG_PATH) and \
                (changed or time.time() - newest > 86400):
            make_backup("update" if changed else "auto")
        cfg["app_version"] = APP_VERSION
        if LOAD_INFO["recovered"]:
            self.root.after(1500, lambda: self.toast("Файл настроек был повреждён. Восстановлено из: %s."
                                                      % LOAD_INFO["recovered"], 12000))

    def restart_app(self):
        """Запустить новую копию после выхода этой (настройки при этом НЕ перезаписываются)."""
        try:
            self.dt.show_icons(True)
            remove_tray()
        except Exception:
            pass
        try:
            import subprocess
            subprocess.Popen(["cmd", "/c", 'ping -n 3 127.0.0.1 >nul & start "" ' + launch_command()],
                             creationflags=0x08000000)
        except Exception:
            log("restart failed:\n" + traceback.format_exc())
        os._exit(0)

    def apply_restore(self, path):
        if self.ask_choice("Восстановление", "Заменить текущие настройки данными из\n%s?\n\n"
                           "Текущие настройки останутся в резервной копии «before-restore».\n"
                           "KinDesk перезапустится." % os.path.basename(path), ("Восстановить", "Отмена")) != "Восстановить":
            return
        if restore_backup(path):
            self.restart_app()
        else:
            self.toast("Этот файл не похож на резервную копию KinDesk.")

    def settings_dialog(self):
        if getattr(self, "set_win", None) is not None:
            try:
                self.set_win.deiconify()
                self.set_win.lift()
                return self.settings_build()
            except Exception:
                self.set_win = None
        w = self.ui_window("Настройки и резервные копии")
        self.set_win = w
        w.protocol("WM_DELETE_WINDOW", lambda: (setattr(self, "set_win", None), w.destroy()))
        self.set_body = self.tk.Frame(w, bg=self.pal()["bg"], padx=20, pady=16)
        self.set_body.pack()
        self.settings_build()
        self._place_dialog(w)

    def settings_build(self):
        tk, c = self.tk, self.pal()
        fr = self.set_body
        for ch in list(fr.winfo_children()):
            ch.destroy()
        self.ui_label(fr, "Хранение настроек", bold=True, size=12).pack(anchor="w")
        self.ui_label(fr, "Все настройки лежат в одном файле: " + CFG_PATH + "\n"
                          "Файлы областей — в папках на диске (их резервные копии не включают).", mute=True).pack(anchor="w", pady=(4, 8))
        top = tk.Frame(fr, bg=c["bg"])
        top.pack(fill="x")
        self.ui_button(top, "Открыть папку настроек", lambda: self.open_path(APP_DIR)).pack(side="left", padx=(0, 6))
        self.ui_button(top, "Экспорт…", self.export_settings).pack(side="left", padx=3)
        self.ui_button(top, "Импорт…", self.import_settings).pack(side="left", padx=3)
        self.ui_check(fr, "Автоматические копии (раз в сутки, перед обновлением и опасными действиями)",
                      self.cfg.get("backup_auto", True), lambda v: self.cfg.__setitem__("backup_auto", v)
                      ).pack(anchor="w", pady=(10, 4))
        self.ui_label(fr, "Резервные копии", bold=True, size=12).pack(anchor="w", pady=(8, 4))
        lb = tk.Listbox(fr, width=70, height=9, bg=c["panel"], fg=c["fg"], bd=0, highlightthickness=1,
                        highlightbackground=c["line"], selectbackground=c["acc"], activestyle="none",
                        font=("Segoe UI", 10))
        lb.pack(fill="x")
        bks = list_backups()
        names = {"auto": "авто", "update": "при обновлении", "manual": "вручную", "before-restore": "перед восстановлением",
                 "before-delete": "перед удалением", "before-release": "перед возвратом значков",
                 "before-tidy": "перед раскладкой"}
        for path, when, tag, size in bks:
            lb.insert("end", "%s    %s    %d КБ" % (time.strftime("%d.%m.%Y %H:%M", time.localtime(when)),
                                                     names.get(tag, tag), max(1, size // 1024)))
        if not bks:
            lb.insert("end", "Копий пока нет")
        row = tk.Frame(fr, bg=c["bg"])
        row.pack(fill="x", pady=(10, 0))

        def sel():
            s = lb.curselection()
            return bks[s[0]][0] if s and bks else None

        def delete():
            pth = sel()
            if pth:
                try:
                    os.remove(pth)
                except OSError:
                    pass
                self.settings_build()
        self.ui_button(row, "Создать копию сейчас", lambda: (save_config(self.cfg), make_backup("manual"),
                                                              self.settings_build()), accent=True).pack(side="left", padx=(0, 6))
        self.ui_button(row, "Восстановить выбранную", lambda: sel() and self.apply_restore(sel())).pack(side="left", padx=3)
        self.ui_button(row, "Удалить", delete).pack(side="left", padx=3)

    def export_settings(self):
        from tkinter import filedialog
        dst = filedialog.asksaveasfilename(title="Экспорт настроек", defaultextension=".zip",
                                           initialfile="kindesk-settings.zip", filetypes=[("Архив настроек", "*.zip")])
        if dst:
            save_config(self.cfg)
            self.toast("Настройки сохранены:\n" + dst if make_backup("manual", dst=dst) else "Не удалось сохранить настройки.")

    def import_settings(self):
        from tkinter import filedialog
        src = filedialog.askopenfilename(title="Импорт настроек", filetypes=[("Архив настроек", "*.zip")])
        if src:
            self.apply_restore(src)

    def dock_remove(self, name):
        d = self.cfg["dock"]
        path = os.path.join(self.eng.folder(d), name)
        try:
            if name.lower().endswith((".lnk", ".url")):
                os.remove(path)
            else:
                self.eng.release_item(d, name)
        except Exception:
            log("dock remove failed:\n" + traceback.format_exc())
        self.changed()

    def dock_menu(self, x, y):
        d = self.cfg["dock"]

        def topmost():
            d["topmost"] = not d.get("topmost")
            self.changed()

        def size_popup():
            def pick(v):
                d["icon"] = v
                self.changed()
            self.show_popup([(("✓ " if int(d.get("icon", 40)) == v else "    ") + n, lambda v=v: pick(v))
                             for n, v in (("Маленькие (32)", 32), ("Средние (40)", 40), ("Крупные (48)", 48),
                                          ("Огромные (64)", 64))], x, y)
        self.show_popup([
            ("Настройки панели и значков…", self.dock_settings),
            None,
            ("Добавить программу…", self.dock_add),
            ("Добавить папку…", self.dock_add_folder),
            None,
            (("✓ " if d.get("topmost") else "    ") + "Поверх всех окон", topmost),
            ("Размер значков  ▸", size_popup),
            ("Цветовая схема  ▸", lambda: self.scheme_popup(d, x, y)),
            ("Прозрачность  ▸", lambda: self.alpha_popup(d, x, y)),
            ("Двойной клик по столу  ▸", lambda: self.dblclick_popup(x, y)),
            None,
            ("Скрыть панель", lambda: self.toggle_widget("dock")),
        ], x, y)

    def open_path(self, path):
        try:
            os.startfile(path)
        except Exception:
            log("open failed %r:\n%s" % (path, traceback.format_exc()))

    def release_all(self, f):
        self.safety_backup("before-release")
        try:
            n = self.eng.release_all(f)
            log("released %d items from %s" % (n, f["name"]))
        except Exception:
            log("release_all failed:\n" + traceback.format_exc())
        self.changed()

    def item_path(self, f, name):
        return os.path.join(self.eng.cur(f), name)

    def set_sel(self, new):
        if new != self.sel:
            self.sel = new
            for v in self.all_views():
                v.repaint()

    def selected_names(self, f):
        keys = set(n for fid, n in self.sel if fid == f["id"])
        return [it["name"] for it in self.eng.items(f) if it["name"] in keys and not it.get("up")]

    def select_all(self, f):
        self.set_sel(set((f["id"], n) for n in [it["name"] for it in self.eng.items(f) if not it.get("up")]))

    def open_item(self, f, name):
        if name == "..":
            self.eng.go_up(f)
            self.set_sel(set())
            self.changed()
        elif os.path.isdir(self.item_path(f, name)):
            self.eng.navigate(f, name)
            self.set_sel(set())
            self.changed()
        else:
            self.open_path(self.item_path(f, name))

    def click_item(self, f, name):
        """Одинарный клик: выделение с Ctrl / Shift, как в Проводнике."""
        if name == "..":
            return
        key = (f["id"], name)
        ctrl, shift = mods()
        if ctrl:
            self.anchor = name
            self.set_sel(self.sel ^ {key})
        elif shift and self.anchor:
            names = [it["name"] for it in self.eng.items(f) if not it.get("up")]
            if self.anchor in names and name in names:
                i, j = sorted((names.index(self.anchor), names.index(name)))
                self.set_sel(set((f["id"], n) for n in names[i:j + 1]))
        else:
            self.anchor = name
            self.set_sel({key})

    def item_menu(self, f, names, x, y):
        one = len(names) == 1
        paths = [self.item_path(f, n) for n in names]
        entries = [("Открыть", lambda: self.open_item(f, names[0]))] if one else []
        entries += [
            ("Показать в проводнике", lambda: self.show_in_folder(f, names[0])) if one else
            ("Показать в проводнике", lambda: self.open_path(self.eng.cur(f))),
            None,
            ("Вырезать", lambda: self.clip(paths, True)),
            ("Копировать", lambda: self.clip(paths, False)),
            None,
        ]
        if one:
            entries.append(("Переименовать…", lambda: self.rename_item(f, names[0])))
            if names[0] != "..":
                entries += self.icon_entries(paths[0])
        entries += [
            ("Удалить" + ("" if one else " (%d)" % len(names)), lambda: self.delete_items(f, names)),
            ("Вернуть на рабочий стол", lambda: self.return_items(f, names)),
        ]
        if one:
            entries += [None, ("Свойства", lambda: self.properties(f, names[0]))]
        self.show_popup(entries, x, y)

    def body_menu(self, f, x, y):
        if f.get("kind", "files") != "files":
            return self.fence_menu(f, x, y)
        self.show_popup([
            ("Вставить", lambda: self.paste_into(f)),
            ("Новая папка", lambda: self.new_folder(f)),
            ("Выделить всё", lambda: self.select_all(f)),
            None,
            ("Открыть эту папку в проводнике", lambda: self.open_path(self.eng.cur(f))),
            ("Меню области  ▸", lambda: self.fence_menu(f, x, y)),
        ], x, y)

    def clip(self, paths, cut):
        try:
            clip_set_files(paths, cut)
        except Exception:
            log("clipboard failed:\n" + traceback.format_exc())

    def paste_into(self, f):
        try:
            files, cut = clip_get_files()
            n = self.eng.paste(f, files, cut)
            log("pasted %d into %s" % (n, f["name"]))
        except Exception:
            log("paste failed:\n" + traceback.format_exc())
        self.changed()

    def new_folder(self, f):
        try:
            name = self.eng.new_folder(f)
            self.set_sel({(f["id"], name)})
        except Exception:
            log("new_folder failed:\n" + traceback.format_exc())
        self.changed()

    def rename_item(self, f, name):
        v = self.ask_string("Переименовать", "Новое имя:", item_label(name))
        if not v or v == item_label(name):
            return
        try:
            new = self.eng.rename_item(f, name, v)
            self.set_sel({(f["id"], new)})
        except (ValueError, OSError) as e:
            self.ask_choice("Переименовать", "Не удалось переименовать: %s" % e)
        self.changed()

    def delete_items(self, f, names):
        what = "«%s»" % item_label(names[0]) if len(names) == 1 else "выбранные элементы (%d)" % len(names)
        if self.ask_choice("Удалить", "Переместить %s в корзину?" % what, ("Удалить", "Отмена")) != "Удалить":
            return
        try:
            if not recycle([self.item_path(f, n) for n in names]):
                log("recycle reported failure")
        except Exception:
            log("recycle failed:\n" + traceback.format_exc())
        self.eng.rescan(f)
        self.set_sel(set())
        self.changed()

    def return_items(self, f, names):
        for n in names:
            try:
                self.eng.release_item(f, n)
            except Exception:
                log("return failed:\n" + traceback.format_exc())
        self.set_sel(set())
        self.changed()

    def properties(self, f, name):
        try:
            shell_properties(self.item_path(f, name))
        except Exception:
            log("properties failed:\n" + traceback.format_exc())

    def show_in_folder(self, f, name):
        try:
            import subprocess
            path = self.item_path(f, name)
            subprocess.Popen(["explorer", path] if os.path.isdir(path) else ["explorer", "/select,", path])
        except Exception:
            log("show_in_folder failed:\n" + traceback.format_exc())

    def return_item(self, f, name, pos=None):
        try:
            self.eng.release_item(f, name, pos)
        except Exception:
            log("return_item failed:\n" + traceback.format_exc())
        self.changed()

    def drop_item(self, f, name, x, y, sx, sy):
        """Значок(и) отпустили в точке (x, y) стола / (sx, sy) экрана."""
        self.close_ghost()
        if name == "..":
            return
        names = self.selected_names(f) if (f["id"], name) in self.sel else [name]
        names = [n for n in names if n != ".."] or [name]
        target = self.ia.fence_at(x, y)
        try:
            if target is f:                    # внутри области: на папку / на «..» - переложить
                z = find_zone(self.ia.zones(), x, y)
                if z and z[0] == "item" and z[1] is f and z[6] not in names:
                    dest = z[6]
                    items = {it["name"]: it for it in self.eng.items(f)}
                    if dest == "..":
                        for n in names:
                            self.eng.move_up(f, n)
                    elif items.get(dest, {}).get("isdir"):
                        for n in names:
                            self.eng.move_into(f, n, dest)
                    else:
                        return
                    self.set_sel(set())
                    self.changed()
                return
            if target is not None:
                for n in names:
                    self.eng.move_item(f, n, target)
                self.set_sel(set())
                self.changed()
            elif self.dt.is_desktop_point(sx, sy):
                for i, n in enumerate(names):
                    self.eng.release_item(f, n, (x + 14 * i, y + 14 * i))
                self.set_sel(set())
                self.changed()
        except Exception:
            log("drop_item failed:\n" + traceback.format_exc())
            self.changed()

    def update_ghost(self, x, y):
        f, name = self.ia.drag["f"], self.ia.drag["name"]
        gw, gh = sc(96), sc(72)
        gx, gy = int(x - gw // 2), int(y - gh // 2)
        tgt = self.ia.fence_at(x, y)
        hot = tgt["id"] if tgt is not None and tgt is not f else None
        if hot != self.hot:                    # подсветить область, куда упадёт значок
            self.hot = hot
            for v in self.all_views():
                v.repaint()
        if self.ghost is None:
            path = self.item_path(f, name)
            nsel = len(self.selected_names(f)) if (f["id"], name) in self.sel else 1
            label = item_label(name) if nsel <= 1 else "%d элем." % nsel
            col, bar = f["color"], f["bar"]
            try:
                if self.view_cls is FenceViewGP:
                    def draw(cv, w, h):
                        cv.fill_rr(0, 0, w, h, sc(14), col, 0.92)
                        cv.stroke_rr(0, 0, w - 1, h - 1, sc(14), bar, 0.9, 2.0 * SCALE[0])
                        cv.icon(path, (w - sc(32)) // 2, sc(8), sc(32))
                        cv.text(label, sc(4), sc(44), w - sc(8), h - sc(46), contrast(col), 1.0,
                                ("Segoe UI", sc(11), 0), align=1, valign=0, wrap=True)
                    self.ghost = LayerWin(("overlay", None, HWND_TOPMOST), gx, gy, gw, gh)
                    self.ghost.render(draw, gx, gy, gw, gh)
                else:
                    def paint(hdc, w, h):
                        g_fill(hdc, 0, 0, w, h, bar)
                        g_fill(hdc, 2, 2, w - 2, h - 2, col)
                        draw_icon(hdc, path, (w - 32) // 2, 6)
                        g_text(hdc, label, 4, 32 + 10, w - 4, h - 3, contrast(col),
                               get_font(*FenceViewClassic.LBL),
                               DT_CENTER | DT_WORDBREAK | DT_NOPREFIX | DT_END_ELLIPSIS)
                    self.ghost = NativeWin(("overlay", None, HWND_TOPMOST), gx, gy, gw, gh, paint, alpha=0.92)
            except Exception:
                log("ghost failed:\n" + traceback.format_exc())
                self.ghost = False
        elif self.ghost:
            if isinstance(self.ghost, NativeWin):
                self.ghost.place(gx, gy, gw, gh)
            else:
                self.ghost.move(gx, gy)

    def close_ghost(self):
        if self.ghost:
            self.ghost.destroy()
        self.ghost = None
        if self.hot is not None:
            self.hot = None
            for v in self.all_views():
                v.repaint()

    def scheme_popup(self, f, x, y):
        def pick(s):
            apply_scheme(f, s)
            self.changed()
        self.show_popup(scheme_items(pick), x, y)

    def scheme_all_popup(self, x, y):
        def pick(s):
            for f in self.cfg["fences"]:
                if f.get("kind") != "note":              # у стикеров свой цвет
                    apply_scheme(f, s)
            apply_scheme(self.cfg["dock"], s)
            self.changed()
        self.show_popup(scheme_items(pick), x, y)

    def look_popup(self, x, y):
        cur = self.cfg.get("look", "modern")

        def pick(v):
            self.cfg["look"] = v
            self.changed()
        self.show_popup([(("✓ " if cur == v else "    ") + n, lambda v=v: pick(v))
                         for v, n in (("modern", "Современный (градиент, мягкие края)"),
                                      ("flat", "Плоский (как раньше)"))], x, y)

    def alpha_popup(self, f, x, y):
        def pick(a):
            f["alpha"] = a
            self.changed()
        cur = float(f.get("alpha", 0.8))
        self.show_popup([(("✓ " if abs(a - cur) < 0.01 else "    ") + "Непрозрачность %d%%" % p,
                          lambda a=a: pick(a)) for p, a in ALPHAS], x, y)

    def icon_popup(self, f, x, y):
        def pick(sz):
            f["icon"] = sz
            self.refit(f)
        cur = int(f.get("icon", 32))
        self.show_popup([(("✓ " if sz == cur else "    ") + name, lambda sz=sz: pick(sz))
                         for name, sz in ICON_SIZES], x, y)

    def toggle_labels(self, f):
        f["labels"] = not f.get("labels")
        self.refit(f)

    def refit(self, f):
        """После смены размера иконок / подписей подогнать высоту области под содержимое."""
        self.eng.rescan(f)
        f["h"] = self.eng.need_h(f)
        self.changed()

    def rename(self, f):
        v = self.ask_string("Название", "Название области:", f["name"])
        if v:
            f["name"] = v
            self.eng.rename_folder(f, v)
            self.changed()

    def custom_color(self, f):
        from tkinter import colorchooser
        v = colorchooser.askcolor(color=f["color"])
        if v and v[1]:
            f["color"], f["bar"], f["text"], f["scheme"] = v[1], darken(v[1], 0.7), "#FFFFFF", "своя"
            self.changed()

    def edit_rules(self, f):
        v = self.ask_string("Правила",
                            "Маски имён через запятую (например: steam, *.pdf, диабло).\n"
                            "Применяются по кнопке «Разложить по правилам» на панели.",
                            ", ".join(f.get("rules", [])))
        if v is not None:
            f["rules"] = [s.strip() for s in v.split(",") if s.strip()]
            save_config(self.cfg)

    def delete(self, f):
        if f.get("kind", "files") != "files":
            return self.toggle_widget(f["kind"])
        if self.ask_choice("Удалить область", "Удалить область «%s»?\nВсе её значки вернутся на рабочий стол."
                           % f["name"], ("Удалить", "Отмена")) != "Удалить":
            return
        self.safety_backup("before-delete")
        try:
            self.eng.release_all(f)            # вернуть файлы на рабочий стол
            os.rmdir(self.eng.folder(f))
        except Exception:
            log("delete release failed:\n" + traceback.format_exc())
        if f in self.cfg["fences"]:
            self.cfg["fences"].remove(f)
        self.changed()

    def add_fence(self):
        n = len(self.cfg["fences"]) + 1
        s = SCHEMES[(n - 1) % len(SCHEMES)]
        off = 150 + 40 * (n % 6)                 # новая область - на основном мониторе
        f = default_fence("Область %d" % n, off - self.vx, off - self.vy)
        apply_scheme(f, s)
        self.cfg["fences"].append(f)
        self.changed()

    def toggle(self, f):
        if f.get("collapsed") and f.get("group") and f.get("gacc"):
            for m in group_members(self.cfg, f["group"]):     # аккордеон: раскрыли одну - остальные свернулись
                if m is not f:
                    self.eng.collapse(m)
        if f.get("collapsed"):
            self.eng.expand(f)
        else:
            self.eng.collapse(f)
        self.changed()

    def toggle_all(self):
        fences = self.cfg["fences"]
        collapse = any(not f.get("collapsed") for f in fences)
        for f in fences:
            if collapse:
                self.eng.collapse(f)
            else:
                self.eng.expand(f)
        self.changed()

    def tidy(self):
        self.safety_backup("before-tidy")
        try:
            self.safe_sync()
            n = self.eng.tidy_by_rules()
        except Exception:
            log("tidy failed:\n" + traceback.format_exc())
            n = 0
        self.changed()
        self.ask_choice("KinDesk", "Перенесено в области по правилам: %d" % n)

    # --- панель ------------------------------------------------------------------
    def show_panel(self):
        tk, c = self.tk, self.pal()
        if self.panel is not None:
            try:
                self.panel.deiconify()
                self.panel.attributes("-topmost", True)
                self.panel.lift()
                self.root.after(400, lambda: self.panel.attributes("-topmost", False))
                return
            except Exception:
                self.panel = None
        p = self.ui_window(APP_NAME)
        p.protocol("WM_DELETE_WINDOW", p.withdraw)
        fr = tk.Frame(p, bg=c["bg"], padx=20, pady=16)
        fr.pack()
        head = tk.Frame(fr, bg=c["bg"])
        head.pack(fill="x")
        self.ui_label(head, APP_NAME, bold=True, size=16).pack(side="left")
        self.ui_label(head, "v" + APP_VERSION, mute=True).pack(side="left", padx=8, pady=(6, 0))
        self.ui_label(fr, "Область двигается за заголовок, размер - за уголок справа внизу.\n"
                          "▾ свернуть / развернуть    ◐ цветовая схема    ≡ меню области\n"
                          "Бросьте значок или файл из другой программы на область - он окажется в её папке.\n"
                          "Клавиатура: Ctrl+Alt+K. Поиск: Ctrl+Alt+Space. Панель: Ctrl+Alt+F.\n"
                          "Свернуть / развернуть все: Ctrl+Alt+G.", mute=True).pack(anchor="w", pady=(8, 12))
        pal_b = self.ui_button(fr, "◐   Цветовая схема для всех областей", lambda: None)
        pal_b.bind("<Button-1>", lambda _e: self.scheme_all_popup(pal_b.winfo_rootx(), pal_b.winfo_rooty() + pal_b.winfo_height()))
        look_b = self.ui_button(fr, "▢   Стиль окон", lambda: None)
        look_b.bind("<Button-1>", lambda _e: self.look_popup(look_b.winfo_rootx(), look_b.winfo_rooty() + look_b.winfo_height()))
        dbl_b = self.ui_button(fr, "⌗   Двойной клик по пустому столу", lambda: None)
        dbl_b.bind("<Button-1>", lambda _e: self.dblclick_popup(dbl_b.winfo_rootx(), dbl_b.winfo_rooty() + dbl_b.winfo_height()))
        rows = [self.ui_button(fr, "＋   Новая область", self.add_fence, accent=True), pal_b, look_b,
                self.ui_button(fr, "⇅   Свернуть / развернуть все", self.toggle_all),
                self.ui_button(fr, "⌕   Поиск", self.open_launcher),
                self.ui_button(fr, "▤   Панель быстрого доступа…", self.dock_settings),
                dbl_b,
                self.ui_button(fr, "⚙   Настройки и резервные копии…", self.settings_dialog),
                self.ui_button(fr, "☰   Перенести значки по правилам", self.tidy),
                self.ui_button(fr, "◎   Перенастроить слой (калибровка)", self.recalibrate)]
        for b_ in rows:
            b_.pack(fill="x", pady=2)
        self.ui_sep(fr).pack(fill="x", pady=10)
        self.ui_label(fr, "Виджеты", bold=True).pack(anchor="w")
        for k, name in WIDGETS:
            self.ui_check(fr, name, self.widget_on(k),
                          lambda v, k=k: (self.toggle_widget(k) if v != self.widget_on(k) else None)).pack(anchor="w")
        self.ui_sep(fr).pack(fill="x", pady=10)
        self.ui_check(fr, "Запускать вместе с Windows", autostart_enabled(), lambda v: set_autostart(v)).pack(anchor="w")
        self.ui_check(fr, "Принимать файлы, перетащенные из других программ (после перезапуска)",
                      self.cfg.get("ext_drop", True), lambda v: self.cfg.__setitem__("ext_drop", v)).pack(anchor="w")
        foot = tk.Frame(fr, bg=c["bg"])
        foot.pack(fill="x", pady=(12, 0))
        self.ui_button(foot, "Скрыть окно", p.withdraw).pack(side="left")
        self.ui_button(foot, "Выход", self.quit_app).pack(side="right")
        self.panel = p
        self._place_dialog(p)

    def toggle_autostart(self):
        try:
            set_autostart(not autostart_enabled())
        except Exception:
            log("autostart failed:\n" + traceback.format_exc())

    def tray_menu(self, x, y):
        on = autostart_enabled()
        self.show_popup([
            ("Открыть панель", self.show_panel),
            ("Поиск…", self.open_launcher),
            ("Настройки панели быстрого доступа…", self.dock_settings),
            ("Настройки и резервные копии…", self.settings_dialog),
            ("Стиль окон  ▸", lambda: self.look_popup(x - 190, y - 100)),
            ("Свернуть / развернуть все", self.toggle_all),
            None,
        ] + [(("✓ " if self.widget_on(k) else "    ") + name, lambda k=k: self.toggle_widget(k))
             for k, name in WIDGETS] + [
            ("Ещё одна заметка", self.add_note),
            ("Двойной клик по столу  ▸", lambda: self.dblclick_popup(x - 190, y - 100)),
            None,
            ("Автозапуск с Windows: " + ("включён ✓" if on else "выключен"), self.toggle_autostart),
            None,
            ("Выход", self.quit_app),
        ], x - 190, y - 420)

    def recalibrate(self):
        if self.calibrate():
            self.refresh()

    # --- основной цикл -----------------------------------------------------------
    def bg_tick(self):
        """Раз в полсекунды: таймер, система, буфер обмена, подписки на календари."""
        try:
            now = time.time()
            self.timer_loop(now)
            self.sysmon_loop(now)
            if IS_WIN:
                self.clip_loop()
            if self._ics_result is not None:
                ok, out = self._ics_result
                self._ics_result, self._ics_busy = None, False
                if ok:
                    self.cfg["ics_cache"], self.cfg["ics_time"] = out, now
                else:
                    self.cfg["ics_time"] = now - 6 * 3600 + 300       # повторить через 5 минут
                save_config(self.cfg)
                self.repaint_kind("calendar")
            if self.cfg["ics_urls"] and now - self.cfg.get("ics_time", 0) > 6 * 3600:
                self.cfg["ics_time"] = now - 6 * 3600 + 300
                self.fetch_ics()
        except Exception:
            log("bg_tick failed:\n" + traceback.format_exc())
        self.root.after(500, self.bg_tick)

    def is_free_desktop_point(self, x, y):
        """Вызывается из потока хука: клик пришёлся на пустое место рабочего стола."""
        try:
            return self.dt.is_desktop_point(x, y) and not self.dt.hit_icon(x, y)
        except Exception:
            return False

    def safe_sync(self):
        try:
            if self.eng.sync():
                save_config(self.cfg)
                return True
        except Exception:
            log("sync failed:\n" + traceback.format_exc())
        return False

    def view_of(self, f):
        for v in self.views:
            if v.f is f:
                return v
        return None

    def pick_cls(self):
        """Плавный вид нужен окнам с прозрачностью; без неё - простой."""
        if self.view_cls is FenceViewGP and not self.cfg.get("translucent", True):
            return FenceViewClassic
        return self.view_cls

    def all_views(self):
        return self.views + ([self.dockview] if self.dockview else [])

    def update_dock(self):
        d = self.cfg["dock"]
        if d.get("on"):
            dock_geom(d, len(self.eng.items(d)), self.primary)

    def refresh(self):
        """Привести окна в соответствие с настройками: существующие обновляются на месте
        (без мигания), лишние удаляются, недостающие создаются."""
        layout_groups(self.cfg, self.live_h)
        old = {v.f["id"]: v for v in self.views}
        self.views = []
        cls = self.pick_cls()
        if self.spec:
            for f in self.cfg["fences"]:
                if cls is not FenceViewGP and f.get("kind", "files") != "files":
                    continue                           # виджеты рисуются только плавным видом
                v = old.pop(f["id"], None)
                try:
                    if v is not None and v.f is f and isinstance(v, cls) and v.update():
                        self.views.append(v)
                        continue
                    if v is not None:
                        v.destroy()
                    self.views.append(cls(self, f))
                except Exception:
                    log("view failed (%s):\n%s" % (cls.__name__, traceback.format_exc()))
                    if cls is FenceViewGP:                  # откат на простой вид до перезапуска
                        self.view_cls = cls = FenceViewClassic
                        try:
                            self.views.append(cls(self, f))
                        except Exception:
                            log("classic view failed:\n" + traceback.format_exc())
        for v in old.values():
            v.destroy()
        # панель быстрого доступа
        d = self.cfg["dock"]
        want = bool(self.spec) and cls is FenceViewGP and bool(d.get("on"))
        self.update_dock()
        try:
            if self.dockview is not None and (not want or not self.dockview.update()):
                self.dockview.destroy()
                self.dockview = None
            if want and self.dockview is None:
                self.dockview = DockViewGP(self)
        except Exception:
            log("dock failed:\n" + traceback.format_exc())
            self.dockview = None
        if self.hidden:
            self.apply_hidden()
        self.refresh_zones()

    def refresh_zones(self):
        """Горячие зоны и окна для хука мыши (в экранных координатах); при скрытии - пусто."""
        d = self.cfg["dock"]
        live = bool(self.spec) and not self.hidden
        self.ev.zones = tuple((z[0], z[1], z[2] + self.vx, z[3] + self.vy,
                               z[4] + self.vx, z[5] + self.vy) + tuple(z[6:])
                              for z in self.ia.zones()) if live else ()
        rects = [(f["x"], f["y"], f["x"] + f["w"], f["y"] + eff_h(f)) for f in self.cfg["fences"]]
        if self.dockview:
            rects.append((d["x"], d["y"], d["x"] + d["w"], d["y"] + d["h"]))
        self.ev.rects = tuple((r[0] + self.vx, r[1] + self.vy, r[2] + self.vx, r[3] + self.vy)
                              for r in rects) if live else ()

    # --- наведение и подсказки -----------------------------------------------------
    TIPS = {"collapse": "Свернуть / развернуть", "palette": "Цветовая схема", "menu": "Меню области"}

    def on_hover(self, x, y, sx, sy):
        if self.ia.drag is not None or self.popup is not None:
            return self.set_hover(None, sx, sy)
        z = find_zone(self.ia.zones(), x, y)
        key = None
        if z and z[0] in ("collapse", "palette", "menu"):
            key = (z[1]["id"], z[0], None)
        elif z and z[0] == "item":
            key = (z[1]["id"], "item", z[6])
        elif z and z[0] == "wact":
            key = (z[1]["id"], "wact", z[6])
        elif z and z[0] == "dockitem":
            key = ("dock", "dockitem", z[6])
        elif z and z[0] == "dockadd":
            key = ("dock", "dockadd", None)
        self.set_hover(key, sx, sy)

    def set_hover(self, key, sx, sy):
        if key == self.hover:
            return
        old, self.hover = self.hover, key
        self.hide_tip()
        for v in self.all_views():
            if v.f["id"] in ((old or (None,))[0], (key or (None,))[0]):
                v.repaint()
        if key is not None:
            self._tip_job = self.root.after(550, lambda: self.show_tip(key, sx, sy))

    WTIPS = {("cal", "prev"): "Предыдущий месяц", ("cal", "next"): "Следующий месяц",
             ("cal", "today"): "Вернуться к текущему месяцу", ("todo", "add"): "Добавить задачу"}

    def tip_text(self, key):
        if key[1] == "wact":
            return self.widget_tip(key)
        if key[1] == "dockitem":
            return item_label(key[2])
        if key[1] == "dockadd":
            return "Добавить программу или папку"
        if key[1] == "item":
            return ("Папка выше" if key[2] == ".." else item_label(key[2]))
        return self.TIPS.get(key[1])

    def show_tip(self, key, sx, sy):
        self._tip_job = None
        if key != self.hover or self.popup is not None:
            return
        text = self.tip_text(key)
        if not text:
            return
        tk = self.tk
        t = tk.Toplevel(self.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        c = self.pal()
        box = tk.Frame(t, bg=c["line"], padx=1, pady=1)
        box.pack()
        tk.Label(box, text=text, bg=c["panel"], fg=c["fg"], padx=10, pady=5, font=("Segoe UI", 9),
                 justify="left").pack()
        t.update_idletasks()
        w, h = t.winfo_reqwidth(), t.winfo_reqheight()
        l_, t_, r_, b_ = self.work_area(sx, sy)
        x = max(l_, min(int(sx) + 14, r_ - w - 4))
        y = max(t_, min(int(sy) + 24, b_ - h - 4))
        t.geometry("+%d+%d" % (x, y))
        self._tip = t

    def hide_tip(self):
        if self._tip_job is not None:
            try:
                self.root.after_cancel(self._tip_job)
            except Exception:
                pass
            self._tip_job = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def after_action(self, act):
        if not act:
            return
        kind, f = act[0], act[1]
        if kind == "toggle":
            self.toggle(f)
        elif kind == "palette":
            self.scheme_popup(f, act[2], act[3])
        elif kind == "menu":
            self.fence_menu(f, act[2], act[3])
        elif kind == "wact":
            self.widget_action(f, act[2])
        elif kind == "dockitem":
            self.open_path(os.path.join(self.eng.folder(self.cfg["dock"]), act[2]))
        elif kind == "dockadd":
            self.dock_add()
        elif kind == "open":
            self.open_item(f, act[2])
        elif kind == "select":
            self.click_item(f, act[2])
        elif kind == "drop":
            self.drop_item(f, act[2], act[3], act[4], act[3] + self.vx, act[4] + self.vy)
        elif kind == "moved" and not f.get("group") and len(act) > 3 and \
                self.group_target(f, act[2], act[3]) is not None:
            tg = self.group_target(f, act[2], act[3])
            self.set_hot(None)
            self.group_with(f, tg)                 # бросили заголовок на другую область: собрать в группу
        else:                                  # moved / resized
            self.set_hot(None)
            self.changed()

    def poll(self):
        try:
            self.drops_tick()
            if self.ev.edit.is_set():
                self.ev.edit.clear()
                self.show_panel()
            if self.ev.all.is_set():
                self.ev.all.clear()
                self.toggle_all()
            if self.ev.kbd.is_set():
                self.ev.kbd.clear()
                self.kbd_toggle()
            if self.ev.search.is_set():
                self.ev.search.clear()
                self.open_launcher()
            while self.ev.q:
                it = self.ev.q.popleft()
                k = it[0]
                if k == "key":
                    self.on_key(it[1], it[2], it[3])
                elif k == "hover":
                    self.on_hover(it[1] - self.vx, it[2] - self.vy, it[1], it[2])
                elif k == "tray":
                    self.tray_menu(it[1], it[2])
                elif k == "dblclick":
                    self.on_dblclick(it[1], it[2])
                elif k == "dismiss":
                    self.close_popup()
                elif k == "press":
                    if self.kbd_state:
                        self.kbd_toggle(False)
                    self.close_popup()
                    self.set_hover(None, 0, 0)
                    z = it[1]
                    if z[0] == "title" and z[1].get("group") and mods()[0]:
                        self.ungroup(z[1], relayout=False)         # Ctrl + заголовок: вытащить из группы
                    if z[0] == "item":
                        ctrl, shift = mods()
                        if z[6] != ".." and not (ctrl or shift) and (z[1]["id"], z[6]) not in self.sel:
                            self.set_sel({(z[1]["id"], z[6])})
                    else:
                        self.set_sel(set())
                    self.ia.press(it[1][0], it[1][1], it[2] - self.vx, it[3] - self.vy,
                                  it[1][6] if len(it[1]) > 6 else None)
                elif k == "move":
                    r = self.ia.move(it[1] - self.vx, it[2] - self.vy)
                    if r == "item":
                        self.update_ghost(it[1] - self.vx, it[2] - self.vy)
                    elif r:
                        gf = self.ia.drag["f"]
                        for m in (group_members(self.cfg, gf.get("group")) or [gf]):
                            v = self.view_of(m)
                            if v:
                                v.place()
                        if self.ia.drag["kind"] == "title" and not gf.get("group"):
                            tg = self.group_target(gf, it[1] - self.vx, it[2] - self.vy)
                            self.set_hot(tg["id"] if tg else None)
                elif k == "release":
                    self.close_ghost() if (self.ia.drag or {}).get("kind") != "item" else None
                    self.after_action(self.ia.release(it[1] - self.vx, it[2] - self.vy))
                elif k == "rclick":
                    z = it[1]
                    if z[0] == "item":
                        if z[6] != "..":
                            if (z[1]["id"], z[6]) not in self.sel:
                                self.set_sel({(z[1]["id"], z[6])})
                            self.item_menu(z[1], self.selected_names(z[1]), it[2], it[3])
                    elif z[0] == "body":
                        self.body_menu(z[1], it[2], it[3])      # для виджетов откроет их меню
                    elif z[0] == "wact" and z[6][0] == "todo" and len(z[6]) == 3:
                        self.todo_menu(z[1], z[6][2], it[2], it[3])
                    elif z[0] == "wact":
                        self.fence_menu(z[1], it[2], it[3])
                    elif z[0] == "dockitem":
                        self.dock_item_menu(z[6], it[2], it[3])
                    elif z[0] in ("dockbody", "dockadd"):
                        self.dock_menu(it[2], it[3])
                    else:
                        self.fence_menu(it[1][1], it[2], it[3])
        except Exception:
            log("poll failed:\n" + traceback.format_exc())
        self.root.after(20, self.poll)

    def tick(self):
        try:
            if self.ia.drag is None and self.spec and self.popup is None:
                self.eng.place_pending()
                if datetime.date.today() != self._day:         # наступил новый день: обновить календарь
                    self._day = datetime.date.today()
                    for v in self.views:
                        if v.f.get("kind") == "calendar":
                            v.repaint()
                if self.safe_sync():
                    self.refresh()
                for v in reversed(self.all_views()):      # верхняя область - выше остальных
                    v.keep_above_desktop()
        except Exception:
            log("tick failed:\n" + traceback.format_exc())
        self.root.after(self.cfg.get("sync_ms", 800), self.tick)

    def quit_app(self):
        try:
            if self.drops:
                self.drops.close()
        except Exception:
            pass
        try:
            save_config(self.cfg)
        except Exception:
            log("quit save failed:\n" + traceback.format_exc())
        try:
            remove_tray()
        except Exception:
            pass
        try:
            self.dt.show_icons(True)
        except Exception:
            pass
        self.dt.close()
        os._exit(0)

    def run(self):
        self.root.mainloop()


# ----------------------------------------------------------------------------
def dump():
    """Диагностика: что видит программа."""
    print("Python: %d-bit" % (ctypes.sizeof(ctypes.c_void_p) * 8))
    print("Виртуальный экран (x, y, ширина, высота):", virtual_metrics(),
          "| основной монитор:", user32.GetSystemMetrics(0), "x", user32.GetSystemMetrics(1))
    dv, host, in_progman = find_defview()
    print("DefView:", dv, "хозяин:", host, "(в Progman)" if in_progman else "(в WorkerW)")
    progman = user32.FindWindowW("Progman", None)
    print("Progman:", progman)
    print("  дочерний WorkerW в Progman:", user32.FindWindowExW(progman, None, "WorkerW", None))
    print("Способы посадить окна позади значков:")
    for name, res in parent_strategies()[:4] + parent_strategies()[5:]:
        try:
            print("  %-34s -> %s" % (name, res()))
        except Exception as e:
            print("  %-34s -> ОШИБКА %s" % (name, e))
    print("Сохранённый способ:", load_config().get("parent_mode"), "| прозрачность:", load_config().get("translucent"))
    d = DesktopListView()
    print("Авторасположение выключено:", d.prepare())
    print("Ячейка (cw, ch):", d.spacing())
    for ic in d.snapshot():
        print("  %-3d %-40s x=%-5d y=%-5d" % (ic["idx"], ic["name"], ic["x"], ic["y"]))
    d.close()


def migrate_autostart():
    """Запись автозапуска под прежним именем заменить на новую."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE | winreg.KEY_QUERY_VALUE) as k:
            try:
                winreg.QueryValueEx(k, LEGACY_NAME)
            except OSError:
                return
            winreg.DeleteValue(k, LEGACY_NAME)
        set_autostart(True)
    except Exception:
        log("migrate_autostart failed:\n" + traceback.format_exc())


def main():
    if not IS_WIN:
        print("KinDesk работает только в Windows 10/11.")
        return 1
    migrate_legacy_name()                      # до первой записи в папку настроек
    migrate_autostart()
    if "--dump" in sys.argv:
        dump()
        return 0
    if "--restore" in sys.argv:                # вернуть ВСЕ файлы из областей на рабочий стол
        cfg = load_config()
        d = DesktopListView()
        d.prepare()
        choose_fence_root()
        eng = FenceEngine(cfg, d)
        lines = ["%s: возвращено на рабочий стол %d" % (f["name"], eng.release_all(f)) for f in cfg["fences"]]
        save_config(cfg)
        d.close()
        print("\n".join(lines))
        if getattr(sys, "frozen", False) or sys.stdout is None:        # без консоли - окошком
            message_box("\n".join(lines) or "Областей нет.")
        return 0
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    apply_scale(detect_scale())
    log("ui scale: %.2f" % SCALE[0])
    if already_running():
        message_box("KinDesk уже запущен.\nЗначок программы - в области уведомлений (возле часов); "
                    "панель - Ctrl+Alt+F.")
        return 0
    try:
        App().run()
    except Exception as e:
        log("fatal:\n" + traceback.format_exc())
        try:
            import tkinter
            from tkinter import messagebox
            r = tkinter.Tk()
            r.withdraw()
            messagebox.showerror("KinDesk", "%s\n\nПодробности: %s" % (e, LOG_PATH))
        except Exception:
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
