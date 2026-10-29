// Редактор планировки: зоны, мебель, столы. Всё меняется в черновике, на сервер уходит
// только по кнопке «Сохранить». Количество столов не ограничено: где их ставить, решает
// человек, а редактор лишь подсвечивает пересечения и места, к которым нельзя пройти.
import { W, H, WALL_Y } from './core.js';
import { t as tr } from '../i18n.js';
import {
    ITEMS, ITEM_TYPES, ZONE_STYLES, DOOR_SIDES, ZONE_ACTIVITIES, ROLE_NAMES, EMPTY_LAYOUT, footprint, zoneWalls, rectsOverlap
} from './catalog.js';
import {
    scene, buildScene, cloneLayout, placementProblem, findFreeSpot, freeDeskSlots, deskCount, unreachableSeats, nextDeskHint,
    newId, MAX_ITEMS, MAX_ZONES
} from './scene.js';

const SNAP = 4;
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const snap = v => Math.round(v / SNAP) * SNAP;

export const editor = { active: false, sel: null, drag: null, problems: {}, unreachable: [], saved: null };
let hooks = { toast: () => {}, save: async () => {}, changed: () => {} };
const $ = id => document.getElementById(id);

export function initEditor(h) { hooks = { ...hooks, ...h }; }

function rebuild() {
    buildScene(scene.layout, true);
    editor.unreachable = unreachableSeats();
    editor.problems = {};
    scene.layout.items.forEach(it => {
        const p = placementProblem(scene.layout, it);
        if (p) editor.problems[it.id] = p;
    });
    hooks.changed();
}

export function openEditor(savedLayout) {
    editor.active = true;
    editor.saved = cloneLayout(savedLayout || scene.layout);
    editor.sel = null;
    buildScene(cloneLayout(editor.saved), true);
    rebuild();
    $('layoutPanel').hidden = false;
    $('officeBox').classList.add('editing');
    renderPanel();
}

export function closeEditor(restore = true) {
    editor.active = false;
    editor.sel = null;
    editor.drag = null;
    if (restore && editor.saved) { buildScene(editor.saved); hooks.changed(); }
    $('layoutPanel').hidden = true;
    $('officeBox').classList.remove('editing');
}

/* ---------- панель ---------- */

function findSel() {
    if (!editor.sel) return null;
    const list = editor.sel.kind === 'zone' ? scene.layout.zones : scene.layout.items;
    return list.find(x => x.id === editor.sel.id) || null;
}

function options(map, current) {
    return Object.entries(map).map(([k, v]) => '<option value="' + k + '"' + (current === k ? ' selected' : '') + '>' + esc(typeof v === 'string' ? v : v.label) + '</option>').join('');
}

export function renderPanel() {
    if (!editor.active) return;
    const l = scene.layout;
    const free = freeDeskSlots(l);
    $('lpDesks').textContent = deskCount(l);
    $('lpDesksHint').textContent = 'рабочих мест: ' + scene.seats.length +
        (free ? ' · свободного места ещё на ' + (free >= 8 ? '8+' : free) : ' · свободного места нет, новые встанут поверх');
    $('lpMinus').disabled = deskCount(l) === 0;
    $('lpPlus').disabled = false;

    $('lpPalette').innerHTML = ITEM_TYPES.map(t =>
        '<button class="lp-item" data-action="layout-add" data-type="' + t + '" title="Добавить: ' + esc(ITEMS[t].label) + '">' +
        '<span>' + ITEMS[t].icon + '</span>' + esc(ITEMS[t].label) + '</button>').join('');

    const s = findSel();
    let props = '<div class="lp-muted">Кликните предмет или зону, чтобы выбрать. Тяните мышью, чтобы переставить; угол зоны — изменить размер. Стрелки двигают, Delete удаляет.</div>';
    if (s && editor.sel.kind === 'zone') {
        const roles = Array.isArray(s.roles) ? s.roles : [];
        props = '<div class="lp-title">Зона</div>' +
            '<label>Название<input class="std-input" data-zone-field="label" maxlength="24" value="' + esc(s.label) + '"></label>' +
            '<label>Описание для агентов<textarea class="std-input" data-zone-field="description" rows="3" maxlength="300" placeholder="Что это за место и что здесь делают">' + esc(s.description) + '</textarea></label>' +
            '<label>Чем здесь заняты<select class="std-input" data-zone-field="activity">' + options(ZONE_ACTIVITIES, s.activity || 'none') + '</select></label>' +
            '<div class="lp-roles"><span>Кому можно заходить</span>' +
            Object.entries(ROLE_NAMES).map(([r, name]) =>
                '<label class="lp-check"><input type="checkbox" data-zone-role="' + r + '"' + (!roles.length || roles.includes(r) ? ' checked' : '') + '> ' + esc(name) + '</label>').join('') +
            '</div>' +
            '<label>Покрытие<select class="std-input" data-zone-field="style">' + options(ZONE_STYLES, s.style) + '</select></label>' +
            '<label class="lp-check"><input type="checkbox" data-zone-field="walls"' + (s.walls ? ' checked' : '') + '> Стеклянные стены</label>' +
            (s.walls ? '<label>Дверь<select class="std-input" data-zone-field="door">' + options(DOOR_SIDES, s.door) + '</select></label>' : '') +
            '<button class="btn btn-danger" data-action="layout-delete">🗑 Удалить зону</button>';
    } else if (s) {
        const def = ITEMS[s.type];
        props = '<div class="lp-title">' + def.icon + ' ' + esc(def.label) + '</div>' +
            (def.seats ? '<div class="lp-muted">Мест: ' + def.seats(s).length + '</div>' : '') +
            (editor.problems[s.id] ? '<div class="lp-warn">⚠️ ' + esc(editor.problems[s.id]) + '</div>' : '') +
            '<button class="btn btn-danger" data-action="layout-delete">🗑 Удалить</button>';
    }
    $('lpProps').innerHTML = props;

    const warn = [];
    const bad = Object.keys(editor.problems).length;
    if (bad) warn.push('🟥 Предметов с пересечениями: ' + bad + ' — они подсвечены красным');
    if (editor.unreachable.length) warn.push('⚠️ К ' + editor.unreachable.length + ' мест(ам) нельзя пройти — агенты пойдут к ним напрямую');
    if (!scene.bossSeat) warn.push('ℹ️ Нет стола руководителя: руководитель сядет за обычный стол');
    $('lpWarn').innerHTML = warn.map(esc).join('<br>');
}

/* ---------- действия ---------- */

function clampInside(it) {
    const def = ITEMS[it.type];
    it.x = Math.max(6, Math.min(W - 6 - def.w, it.x));
    it.y = Math.max(WALL_Y, Math.min(H - 4 - def.d, it.y));
}

function addItem(type, near) {
    const l = scene.layout;
    if (l.items.length >= MAX_ITEMS) { hooks.toast('Слишком много предметов (максимум ' + MAX_ITEMS + ')', 'err'); return; }
    const hint = near || { x: W / 2, y: (H + WALL_Y) / 2 };
    let p = findFreeSpot(l, type, hint);
    if (!p) {
        // места нет - всё равно ставим в центр лесенкой (чтобы новые не легли стопкой), человек сам передвинет
        const k = Object.keys(editor.problems).length;
        p = { x: snap(W / 2 - ITEMS[type].w / 2 + (k % 6) * 16), y: snap(300 + (k % 6) * 12) };
        hooks.toast('Свободного места нет: «' + ITEMS[type].label + '» поставлен поверх, передвиньте его', 'info');
    }
    const it = { id: newId('i'), type, x: p.x, y: p.y };
    clampInside(it);
    l.items.push(it);
    editor.sel = { kind: 'item', id: it.id };
    rebuild();
    renderPanel();
}

export const editorActions = {
    'layout-close': () => { closeEditor(true); },
    'layout-cancel': () => { closeEditor(true); },
    'layout-reset': () => {
        if (!confirm(tr('Убрать из офиса все зоны, столы и мебель? Изменения сохранятся только после «Сохранить».'))) return;
        buildScene(cloneLayout(EMPTY_LAYOUT), true);
        editor.sel = null;
        rebuild();
        renderPanel();
    },
    'layout-save': async () => {
        const bad = Object.keys(editor.problems).length;
        const ok = await hooks.save(cloneLayout(scene.layout));
        if (!ok) return;
        if (bad) hooks.toast('Сохранено. Внимание: у ' + bad + ' предметов есть пересечения', 'info');
        editor.saved = cloneLayout(scene.layout);
        closeEditor(false);
    },
    'layout-add': el => addItem(el.dataset.type),
    'layout-add-zone': () => {
        const l = scene.layout;
        if (l.zones.length >= MAX_ZONES) { hooks.toast('Слишком много зон', 'err'); return; }
        const z = {
            id: newId('z'), label: 'Новая зона', x: 420, y: 250, w: 180, h: 130, style: 'carpet', walls: false, door: 'south',
            activity: 'meeting', roles: [], description: '',
        };
        l.zones.push(z);
        editor.sel = { kind: 'zone', id: z.id };
        rebuild();
        renderPanel();
    },
    'layout-delete': () => deleteSelected(),
    'desks-plus': () => addItem('desk_pod', nextDeskHint(scene.layout)),
    'desks-minus': () => {
        const l = scene.layout;
        const idx = l.items.map(it => it.type).lastIndexOf('desk_pod');
        if (idx < 0) return;
        l.items.splice(idx, 1);
        editor.sel = null;
        rebuild();
        renderPanel();
    },
};

function deleteSelected() {
    const s = findSel();
    if (!s) return;
    const list = editor.sel.kind === 'zone' ? scene.layout.zones : scene.layout.items;
    list.splice(list.indexOf(s), 1);
    editor.sel = null;
    rebuild();
    renderPanel();
}

// поля зоны из панели: название и описание меняются на лету, остальное - по change
export function onPanelInput(el) {
    const s = findSel();
    if (!s || editor.sel.kind !== 'zone') return;
    if (el.dataset.zoneRole) {
        const boxes = [...document.querySelectorAll('[data-zone-role]')];
        const picked = boxes.filter(b => b.checked).map(b => b.dataset.zoneRole);
        if (!picked.length) { el.checked = true; hooks.toast('Хотя бы одна роль должна иметь доступ', 'info'); return; }
        s.roles = picked.length === boxes.length ? [] : picked;
        rebuild();
        return;
    }
    const f = el.dataset.zoneField;
    const old = { ...s };
    s[f] = el.type === 'checkbox' ? el.checked : el.value;
    if ((f === 'walls' || f === 'door') && zoneProblem(s)) {
        hooks.toast(zoneProblem(s), 'err');
        Object.assign(s, old);
    }
    rebuild();
    if (f !== 'label' && f !== 'description') renderPanel();
}

/* ---------- мышь ---------- */

function itemBox(it) {
    const d = ITEMS[it.type];
    return [it.x, it.y - d.h - 4, d.w, d.d + d.h + 4];
}

function hit(p) {
    const inR = r => p.x >= r[0] && p.x <= r[0] + r[2] && p.y >= r[1] && p.y <= r[1] + r[3];
    const sel = findSel();
    if (sel && editor.sel.kind === 'zone' && Math.abs(p.x - (sel.x + sel.w)) < 8 && Math.abs(p.y - (sel.y + sel.h)) < 8) {
        return { kind: 'zone', id: sel.id, mode: 'resize' };
    }
    const items = scene.layout.items.filter(it => inR(itemBox(it))).sort((a, b) => (b.y + ITEMS[b.type].d) - (a.y + ITEMS[a.type].d));
    if (items.length) return { kind: 'item', id: items[0].id, mode: 'move' };
    const zones = scene.layout.zones.filter(z => inR([z.x, z.y, z.w, z.h])).sort((a, b) => a.w * a.h - b.w * b.h);
    if (zones.length) return { kind: 'zone', id: zones[0].id, mode: 'move' };
    return null;
}

// зона должна оставаться внутри офиса и не быть крошечной; остальное - на усмотрение человека
function zoneProblem(z) {
    if (z.x < 0 || z.y < WALL_Y || z.x + z.w > W || z.y + z.h > H) return 'Зона выходит за пределы офиса';
    if (z.w < 60 || z.h < 50) return 'Зона слишком маленькая';
    for (const s of zoneWalls(z)) {
        for (const it of scene.layout.items) {
            if (rectsOverlap([s.x, s.y, s.w, s.h], footprint(it))) return 'Стена зоны проходит через «' + ITEMS[it.type].label + '»';
        }
    }
    return '';
}

export function pointerDown(p) {
    const h = hit(p);
    editor.sel = h ? { kind: h.kind, id: h.id } : null;
    const s = findSel();
    if (s) editor.drag = { ...h, ox: p.x - s.x, oy: p.y - s.y, orig: { ...s } };
    renderPanel();
    return !!s;
}

export function pointerMove(p) {
    const d = editor.drag;
    if (!d) return false;
    const s = findSel();
    if (!s) return false;
    if (d.kind === 'zone' && d.mode === 'resize') {
        s.w = Math.max(60, Math.min(W - s.x, snap(p.x - s.x)));
        s.h = Math.max(50, Math.min(H - s.y, snap(p.y - s.y)));
    } else if (d.kind === 'zone') {
        s.x = Math.max(0, Math.min(W - s.w, snap(p.x - d.ox)));
        s.y = Math.max(WALL_Y, Math.min(H - s.h, snap(p.y - d.oy)));
    } else {
        s.x = snap(p.x - d.ox);
        s.y = snap(p.y - d.oy);
        clampInside(s);
    }
    rebuild();
    return true;
}

export function pointerUp() {
    const d = editor.drag;
    editor.drag = null;
    if (!d) return;
    const s = findSel();
    // стены зоны, разрезающие мебель, выглядят странно: такую правку откатываем
    if (s && d.kind === 'zone' && s.walls && zoneProblem(s)) {
        hooks.toast(zoneProblem(s), 'err');
        Object.assign(s, d.orig);
    }
    rebuild();
    renderPanel();
}

export function editorKey(e) {
    if (!editor.active) return false;
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'select' || tag === 'textarea') return false;
    if (e.key === 'Delete' || e.key === 'Backspace') { deleteSelected(); return true; }
    const s = findSel();
    const moves = { ArrowLeft: [-SNAP, 0], ArrowRight: [SNAP, 0], ArrowUp: [0, -SNAP], ArrowDown: [0, SNAP] };
    if (s && moves[e.key]) {
        s.x += moves[e.key][0]; s.y += moves[e.key][1];
        if (editor.sel.kind === 'item') clampInside(s);
        rebuild();
        renderPanel();
        return true;
    }
    return false;
}
