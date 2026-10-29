"""Планировка офиса (data/layout.json): зоны и предметы.

Сервер только проверяет и хранит планировку; геометрию и проходы считает браузер.
Нет файла - офис пустой: пользователь обставляет его сам в редакторе планировки.
"""
import re
from typing import Any, Dict, Optional

from . import settings
from .storage import read_json, write_json

LAYOUT_PATH = settings.DATA_DIR / "layout.json"
ITEM_TYPES = {
    "desk_pod", "desk_single", "boss_desk", "bookshelf", "cooler", "server_rack", "vending", "sofa", "armchair",
    "coffee_table", "floor_lamp", "plant", "plant_big", "whiteboard", "meeting_table", "printer", "coffee_machine",
}
ZONE_STYLES = {"rug_red", "rug_teal", "carpet", "tile", "wood_light", "none"}
DOORS = {"east", "west", "south", "north"}
ACTIVITIES = {
    "work": "работа", "rest": "отдых", "kitchen": "кофе-брейк", "meeting": "обсуждения",
    "private": "личное пространство", "none": "без назначения",
}
ROLES = {"planner": "руководитель", "coder": "разработчики", "qa": "тестировщики"}
# количество столов не ограничиваем: где их ставить, решает человек; это лишь защита от мусора
MAX_ITEMS, MAX_ZONES = 200, 20

ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,24}$")
WORLD_W, WORLD_H = 1600, 900           # размер офиса, как W и H в static/js/office/core.js


class LayoutError(ValueError):
    pass


_layout: Optional[Dict[str, Any]] = None
_rev = 0


def _load() -> None:
    global _layout
    data = read_json(LAYOUT_PATH, None)
    try:
        _layout = validate(data) if data is not None else None
    except LayoutError as e:
        print(f"layout.json не прошёл проверку ({e}), офис будет пустым", flush=True)
        _layout = None


def _num(v: Any, lo: float, hi: float, what: str) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise LayoutError(f"{what}: число вне допустимых пределов")
    return round(float(v), 1)


def validate(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict) or not isinstance(data.get("items"), list) or not isinstance(data.get("zones"), list):
        raise LayoutError("Ожидались списки items и zones")
    if len(data["items"]) > MAX_ITEMS or len(data["zones"]) > MAX_ZONES:
        raise LayoutError("Слишком много предметов или зон")
    items, zones, ids = [], [], set()
    for it in data["items"]:
        if not isinstance(it, dict) or it.get("type") not in ITEM_TYPES:
            raise LayoutError("Неизвестный тип предмета")
        iid = str(it.get("id", ""))
        if not ID_RE.match(iid) or iid in ids:
            raise LayoutError("Неверный или повторяющийся id предмета")
        ids.add(iid)
        items.append({"id": iid, "type": it["type"], "x": _num(it.get("x"), -20, WORLD_W, "x"),
                      "y": _num(it.get("y"), 0, WORLD_H, "y")})
    for z in data["zones"]:
        if not isinstance(z, dict):
            raise LayoutError("Неверная зона")
        zid = str(z.get("id", ""))
        if not ID_RE.match(zid) or zid in ids:
            raise LayoutError("Неверный или повторяющийся id зоны")
        ids.add(zid)
        zones.append({
            "id": zid,
            "label": " ".join(str(z.get("label") or "").split())[:24],
            "x": _num(z.get("x"), 0, WORLD_W, "x"), "y": _num(z.get("y"), 0, WORLD_H, "y"),
            "w": _num(z.get("w"), 40, WORLD_W, "w"), "h": _num(z.get("h"), 40, WORLD_H, "h"),
            "style": z.get("style") if z.get("style") in ZONE_STYLES else "none",
            "walls": bool(z.get("walls")),
            "door": z.get("door") if z.get("door") in DOORS else "east",
            "activity": z.get("activity") if z.get("activity") in ACTIVITIES else "none",
            "roles": sorted({r for r in (z.get("roles") or []) if r in ROLES}) if isinstance(z.get("roles"), list) else [],
            "description": " ".join(str(z.get("description") or "").split())[:300],
        })
    return {"version": 1, "zones": zones, "items": items}


def office_brief() -> str:
    """Описание офиса для агентов: какие есть зоны, что в них делают и кому туда можно."""
    if not _layout:
        return "Офис ещё не обставлен: столов и зон нет."
    zones = _layout["zones"]
    lines = []
    for z in zones:
        if not z.get("label") and not z.get("description"):
            continue
        who = ", ".join(ROLES[r] for r in z.get("roles") or []) or "все"
        act = ACTIVITIES.get(z.get("activity") or "none", "")
        lines.append(f"- {z.get('label') or 'Зона'} ({act}; доступ: {who}): {z.get('description') or 'описания нет'}")
    head = f"Рабочих мест за столами: {seat_count()}."
    return head + ("\n" + "\n".join(lines) if lines else "")


def seat_count() -> int:
    """Рабочих мест за столами (без кабинета руководителя). Пока офис не обставлен, мест нет."""
    if not _layout:
        return 0
    return sum(2 if it["type"] == "desk_pod" else 1 for it in _layout["items"] if it["type"] in ("desk_pod", "desk_single"))


def get() -> Optional[Dict[str, Any]]:
    return _layout


def rev() -> int:
    return _rev


def save(data: Any) -> Dict[str, Any]:
    global _layout, _rev
    clean = validate(data)
    write_json(LAYOUT_PATH, clean)
    _layout = clean
    _rev += 1
    return clean


def reset() -> None:
    global _layout, _rev
    if LAYOUT_PATH.exists():
        LAYOUT_PATH.unlink()
    _layout = None
    _rev += 1


_load()
