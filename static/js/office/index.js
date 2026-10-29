// Офис: цикл кадров, мышь, редактор планировки. Наружу отдаёт простое API для интерфейса.
import {
    initRenderer, ensureLayers, renderFrame, resizeCanvas, setHover, toWorld, zoomAt, zoomCenter, panBy, resetView, camera,
    showWholeOffice, refreshBackdrop
} from './render.js';

export { refreshBackdrop };
import { sprites, seatMap, syncAgents as syncSprites, say, hitAgent, seatLabel, updateSprites, setArrivalHandler } from './sprites.js';
import { scene, buildScene, zoneAt, cloneLayout, findFreeSpot, nextDeskHint, newId } from './scene.js';
import { ZONE_ACTIVITIES, zoneAccessText } from './catalog.js';
import { editor, initEditor, openEditor, editorActions, pointerDown, pointerMove, pointerUp, editorKey, onPanelInput } from './editor.js';

export { say, seatLabel, editorActions, onPanelInput };
export { portraitSVG, figureSVG, SKIN, HAIR_STYLES, OUTFITS, ACCESSORIES } from './people.js';

let lastFrame = performance.now(), tick = 0;
let lastAgents = {};
let layoutJson = '';

function frame(nowMs) {
    const dt = Math.min(0.05, (nowMs - lastFrame) / 1000);
    lastFrame = nowMs;
    tick += dt * 60;                    // анимации считаем в «кадрах при 60 fps»
    if (ensureLayers()) {
        if (!editor.active) updateSprites(dt);
        renderFrame(tick, Object.values(sprites), seatMap(), editor);
    }
    requestAnimationFrame(frame);
}

export function syncAgents(agents) {
    lastAgents = agents || {};
    syncSprites(lastAgents);
}

// планировка пришла с сервера (или null - стандартная)
export function setLayout(layout) {
    const json = JSON.stringify(layout || null);
    if (json === layoutJson || editor.active) return;
    layoutJson = json;
    buildScene(layout);
    syncSprites(lastAgents, true);
}

export function seatCount() { return scene ? scene.seats.length : 8; }
export function editorOpen() { return editor.active; }

// офис сам расширяется: n новых блоков столов туда, где есть место и проход (как кнопка «+» в редакторе).
// Возвращает новую планировку или null, если места нет совсем
export function layoutWithMoreDesks(n) {
    if (!scene || editor.active) return null;
    const layout = cloneLayout(scene.layout);
    let added = 0;
    for (let i = 0; i < n; i++) {
        const p = findFreeSpot(layout, 'desk_pod', nextDeskHint(layout));
        if (!p) break;
        layout.items.push({ id: newId('i'), type: 'desk_pod', x: p.x, y: p.y });
        added++;
    }
    return added ? layout : null;
}

export function startOffice(canvas, opts) {
    initRenderer(canvas);
    buildScene(null);
    setArrivalHandler(opts.onArrive);
    initEditor({
        toast: opts.toast,
        save: async layout => {
            const ok = await opts.saveLayout(layout);
            if (ok) { layoutJson = JSON.stringify(layout); syncSprites(lastAgents, true); }
            return ok;
        },
        changed: () => syncSprites(lastAgents, true),
    });
    if (window.ResizeObserver) new ResizeObserver(resizeCanvas).observe(canvas.parentElement);
    window.addEventListener('resize', resizeCanvas);

    // мышь и пальцы: колесо и щипок - масштаб, перетаскивание пустого места - сдвиг вида,
    // короткий клик по человечку - открыть его чат; в редакторе тянутся предметы
    const pointers = new Map();
    let pan = null, pinch = null, swallowClick = false;

    canvas.addEventListener('pointerdown', e => {
        pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        canvas.setPointerCapture(e.pointerId);
        showZoneTip(null);
        if (pointers.size === 2) {
            const [a, b] = [...pointers.values()];
            pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y), mx: (a.x + b.x) / 2, my: (a.y + b.y) / 2 };
            pan = null;
            return;
        }
        if (editor.active && e.button === 0 && pointerDown(toWorld(e.clientX, e.clientY))) return;
        if (e.button === 0 || e.button === 1) pan = { x: e.clientX, y: e.clientY, moved: false };
    });
    canvas.addEventListener('pointermove', e => {
        if (pointers.has(e.pointerId)) pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        if (pinch && pointers.size === 2) {
            const [a, b] = [...pointers.values()];
            const dist = Math.hypot(a.x - b.x, a.y - b.y), mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
            panBy(mx - pinch.mx, my - pinch.my);
            if (pinch.dist > 0) zoomAt(mx, my, dist / pinch.dist);
            pinch = { dist, mx, my };
            swallowClick = true;
            return;
        }
        const p = toWorld(e.clientX, e.clientY);
        if (editor.active && editor.drag) {
            pointerMove(p);
            canvas.style.cursor = 'grabbing';
            return;
        }
        if (pan) {
            const dx = e.clientX - pan.x, dy = e.clientY - pan.y;
            if (!pan.moved && Math.hypot(dx, dy) > 4) pan.moved = true;
            if (pan.moved) {
                panBy(dx, dy);
                pan.x = e.clientX; pan.y = e.clientY;
                canvas.style.cursor = 'grabbing';
                return;
            }
        }
        if (editor.active) { canvas.style.cursor = 'default'; return; }
        const a = hitAgent(p);
        setHover(a ? a.id : null);
        canvas.style.cursor = a ? 'pointer' : 'grab';
        showZoneTip(a ? null : zoneAt(scene.layout, p.x, p.y), e, canvas.getBoundingClientRect());
    });
    const release = e => {
        pointers.delete(e.pointerId);
        if (pointers.size < 2) pinch = null;
        if (editor.active && editor.drag) pointerUp();
        if (pan && pan.moved) swallowClick = true;           // отпустили после сдвига - это не клик
        pan = null;
        canvas.style.cursor = editor.active ? 'default' : 'grab';
    };
    canvas.addEventListener('pointerup', release);
    canvas.addEventListener('pointercancel', release);
    canvas.addEventListener('mouseleave', () => { setHover(null); showZoneTip(null); });
    canvas.addEventListener('click', e => {
        if (swallowClick) { swallowClick = false; return; }
        if (editor.active) return;
        const a = hitAgent(toWorld(e.clientX, e.clientY));
        if (a) opts.onAgentClick(a.id);
    });
    canvas.addEventListener('dblclick', e => {
        if (!editor.active && !hitAgent(toWorld(e.clientX, e.clientY))) resetView();
    });
    canvas.addEventListener('wheel', e => {
        e.preventDefault();
        zoomAt(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0015));
        showZoneTip(null);
    }, { passive: false });
    document.addEventListener('keydown', e => { if (editorKey(e)) e.preventDefault(); });

    resizeCanvas();
    requestAnimationFrame(frame);
}

export function openLayoutEditor() {
    showZoneTip(null);
    openEditor(scene.layout);
}

// подсказка о зоне под курсором: что это за место, кому можно, чем заняты
let tip = null, tipZone = null;
const escHtml = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function showZoneTip(zone, e, rect) {
    if (!tip) {
        tip = document.createElement('div');
        tip.className = 'zone-tip';
        tip.hidden = true;
        document.getElementById('officeBox').appendChild(tip);
    }
    if (!zone || (!zone.label && !zone.description)) { tip.hidden = true; tipZone = null; return; }
    if (zone !== tipZone) {
        tipZone = zone;
        const act = ZONE_ACTIVITIES[zone.activity];
        tip.innerHTML = '<b>' + escHtml(zone.label || 'Зона') + '</b>' + escHtml(zone.description || '') +
            '<div class="zt-meta">Можно: <span>' + escHtml(zoneAccessText(zone)) + '</span>' +
            (act && zone.activity !== 'none' ? ' · Занятие: <span>' + escHtml(act.label) + '</span>' : '') + '</div>';
    }
    tip.hidden = false;
    const x = e.clientX - rect.left + 14, y = e.clientY - rect.top + 16;
    tip.style.left = Math.min(x, rect.width - tip.offsetWidth - 8) + 'px';
    tip.style.top = Math.min(y, rect.height - tip.offsetHeight - 8) + 'px';
}

// кнопки масштаба в углу офиса
export const viewActions = {
    'office-zoom-in': () => zoomCenter(1.25),
    'office-zoom-out': () => zoomCenter(1 / 1.25),
    // ⤢ переключает «весь офис» и обычный вид
    'office-zoom-reset': () => (camera.sc <= camera.min * 1.02 ? resetView() : showWholeOffice()),
};
export function toggleFullscreen(box) {
    if (document.fullscreenElement) document.exitFullscreen();
    else if (box.requestFullscreen) box.requestFullscreen();
}
