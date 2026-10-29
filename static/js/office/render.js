// Сборка кадра: кэш стены и пола, предметы и люди по глубине, свет, подписи, реплики.
import { W, H, WALL_Y, FONT, V, X, Y, R, glow, clip, pillPath, paintInto } from './core.js';
import { ITEMS, paintZoneFloor, zoneWalls, drawWallH, drawWallV, drawZoneLabel, drawChair, solidRect } from './catalog.js';
import { SKY, skyPhase, paintWall, paintFloor, drawClockHands } from './room.js';
import { drawPerson } from './people.js';
import { t as tr } from '../i18n.js';
import { scene } from './scene.js';

let canvas = null, ctx = null;
let bgLayer = null, bgScale = 0, layerPhase = '', layerSig = '', bgDue = 0;
let lights = [], stars = [];
let hoverId = null;

/* ---------- камера ----------
   Офис больше окна: по нему можно ходить во все стороны (перетаскивание), отдалять до
   всего офиса целиком и приближать в 3 раза. «Обычный» масштаб - как у прежнего офиса. */

export const camera = { sc: 0, cx: 0, cy: 0, min: 1, comfort: 1, max: 3 };
const HOME = { x: 560, y: 360 };               // куда смотрит камера по умолчанию: кабинет и рабочие столы
const BG_MAX_PIXELS = 4096;                    // фон шире этого не рисуем, а растягиваем по пикселям
export let backdrop = '#d9e1ec';               // цвет вокруг офиса, когда он отдалён

export function initRenderer(el) {
    canvas = el;
    ctx = V.G = el.getContext('2d');
    refreshBackdrop();
}

export function refreshBackdrop() {
    const v = getComputedStyle(document.documentElement).getPropertyValue('--office-backdrop').trim();
    if (v) backdrop = v;
}

export function setHover(id) { hoverId = id; }

function applyCamera() {
    if (!canvas || !canvas.width) return;
    const nw = canvas.width, nh = canvas.height;
    camera.min = Math.min(nw / W, nh / H);                       // весь офис в кадре
    camera.comfort = Math.max(camera.min, nh / 560);              // обычная плотность
    camera.max = camera.comfort * 3;
    if (!camera.sc) { camera.sc = camera.comfort; camera.cx = HOME.x; camera.cy = HOME.y; }
    camera.sc = Math.max(camera.min, Math.min(camera.max, camera.sc));
    V.SC = camera.sc;
    // если офис уже кадра - держим его по центру, иначе не даём уехать за край
    const hw = nw / (2 * V.SC), hh = nh / (2 * V.SC);
    camera.cx = hw * 2 >= W ? W / 2 : Math.max(hw, Math.min(W - hw, camera.cx));
    camera.cy = hh * 2 >= H ? H / 2 : Math.max(hh, Math.min(H - hh, camera.cy));
    V.OX = Math.round(nw / 2 - camera.cx * V.SC);
    V.OY = Math.round(nh / 2 - camera.cy * V.SC);
    // подписи меняются с масштабом, но остаются читаемыми и не раздуваются
    V.LS = Math.max(camera.comfort * 0.75, Math.min(V.SC, camera.comfort * 1.35));
}

export function resizeCanvas() {
    const box = canvas.parentElement;
    const cw = box.clientWidth, ch = box.clientHeight;
    if (!cw || !ch) return;
    V.DPR = window.devicePixelRatio || 1;
    const nw = Math.round(cw * V.DPR), nh = Math.round(ch * V.DPR);
    if (nw === canvas.width && nh === canvas.height && bgLayer) return;
    canvas.width = nw;
    canvas.height = nh;
    applyCamera();
    bgDue = 0;                                   // фон под новый масштаб - сразу
}

// zoomAt: точка под курсором остаётся на месте; factor > 1 - приблизить
export function zoomAt(clientX, clientY, factor) {
    const before = toWorld(clientX, clientY);
    camera.sc *= factor;
    applyCamera();
    const after = toWorld(clientX, clientY);
    camera.cx += before.x - after.x;
    camera.cy += before.y - after.y;
    applyCamera();
    bgDue = performance.now() + 180;             // фон перерисуем, когда колесо успокоится
}

export function zoomCenter(factor) {
    const r = canvas.getBoundingClientRect();
    zoomAt(r.left + r.width / 2, r.top + r.height / 2, factor);
}

export function panBy(dxCss, dyCss) {
    camera.cx -= dxCss * V.DPR / V.SC;
    camera.cy -= dyCss * V.DPR / V.SC;
    applyCamera();
}

// обычный вид: привычный масштаб, кабинет и рабочие столы в кадре
export function resetView() {
    camera.sc = camera.comfort;
    camera.cx = HOME.x;
    camera.cy = HOME.y;
    applyCamera();
    bgDue = performance.now() + 50;
}

// весь офис целиком
export function showWholeOffice() {
    camera.sc = camera.min;
    camera.cx = W / 2;
    camera.cy = H / 2;
    applyCamera();
    bgDue = performance.now() + 50;
}

export function toWorld(clientX, clientY) {
    const r = canvas.getBoundingClientRect();
    const dx = (clientX - r.left) * (canvas.width / r.width);
    const dy = (clientY - r.top) * (canvas.height / r.height);
    return { x: (dx - V.OX) / V.SC, y: (dy - V.OY) / V.SC };
}

// стена и пол рисуются один раз в кэш всего мира; при сдвиге камеры его просто переносим
function buildBackground() {
    const phase = skyPhase(), sky = SKY[phase];
    layerPhase = phase;
    layerSig = JSON.stringify(scene.layout.zones);
    bgScale = Math.min(V.SC, BG_MAX_PIXELS / W);
    lights = []; stars = [];
    bgLayer = document.createElement('canvas');
    bgLayer.width = Math.ceil(W * bgScale);
    bgLayer.height = Math.ceil(H * bgScale);
    const savedSC = V.SC;
    V.SC = bgScale;
    try {
        paintInto(bgLayer, 0, 0, () => {
            const G = V.G;
            paintWall(sky, phase, lights, stars);
            G.save();
            G.beginPath();
            G.rect(0, Y(WALL_Y - 6), bgLayer.width, bgLayer.height);
            G.clip();
            paintFloor(sky);
            scene.layout.zones.forEach(z => paintZoneFloor(z));
            scene.layout.zones.filter(z => !zoneWalls(z).some(s => s.side === 'south')).forEach(drawZoneLabel);
            G.restore();
        });
    } finally {
        V.SC = savedSC;
    }
}

// пересобрать кэш, если поменялся масштаб (после паузы), время суток или зоны
export function ensureLayers() {
    if (!scene) return false;
    resizeCanvas();
    if (!canvas.width) return false;
    applyCamera();
    const wanted = Math.min(V.SC, BG_MAX_PIXELS / W);
    const stale = layerPhase !== skyPhase() || layerSig !== JSON.stringify(scene.layout.zones);
    if (!bgLayer || stale || (Math.abs(wanted - bgScale) > 0.001 && performance.now() >= bgDue)) buildBackground();
    return !!bgLayer;
}

/* ---------- подписи и реплики ---------- */

function drawLabel(a, t) {
    const G = V.G, SC = V.LS;          // размер подписи растёт с приближением, но ограниченно
    const fs1 = Math.max(9 * V.DPR, 8.4 * SC), fs2 = Math.max(8 * V.DPR, 7.2 * SC);
    const hovered = hoverId === a.id;
    const l1 = clip(a.id, 16);
    const tag = a.modelShort ? ' (' + clip(tr(a.modelShort), 14) + ')' : '';
    const status = tr(a.walking ? 'Идёт к столу' : a.working ? (a.action || 'Работает') : a.role || '');
    const l2 = (a.working || a.walking || hovered) ? clip(status, 30) : '';
    G.textAlign = 'left';
    G.textBaseline = 'alphabetic';
    G.font = '700 ' + fs1 + 'px ' + FONT;
    const w1 = G.measureText(l1).width;
    G.font = '500 ' + fs2 + 'px ' + FONT;
    const wt = tag ? G.measureText(tag).width : 0;
    const w2 = l2 ? G.measureText(l2).width : 0;
    const padX = 5.4 * SC, padY = 2.8 * SC, dot = 7.2 * SC;
    const w = Math.max(w1 + wt + dot, w2) + padX * 2;
    const h = fs1 + (l2 ? fs2 + SC : 0) + padY * 2;
    const below = a.pose === 'sitS';
    let x = X(a.x) - w / 2;
    let y = below ? Y(a.y + 6) + 3 * SC : Y(a.y - 58) - h - 2 * SC;
    if (x + w < 0 || x > canvas.width || y + h < 0 || y > canvas.height) return;     // агент за кадром

    pillPath(x, y, w, h, 4 * SC);
    G.fillStyle = 'rgba(10,14,28,0.9)';
    G.fill();
    G.lineWidth = Math.max(1, SC * 0.85);
    G.strokeStyle = a.working ? '#f2b84b' : a.walking ? '#5ec8ff' : (a.isBoss ? '#ef4444' : 'rgba(120,135,170,0.6)');
    G.stroke();
    const busy = a.working || a.walking;
    const pulse = busy ? (0.55 + 0.45 * Math.abs(Math.sin(t / 14))) : 1;
    G.fillStyle = a.working ? 'rgba(242,184,75,' + pulse.toFixed(2) + ')' : a.walking ? 'rgba(94,200,255,' + pulse.toFixed(2) + ')' : '#46d39a';
    G.beginPath();
    G.arc(x + padX + 2.4 * SC, y + padY + fs1 * 0.58, 2.1 * SC, 0, Math.PI * 2);
    G.fill();
    G.font = '700 ' + fs1 + 'px ' + FONT;
    G.fillStyle = a.working ? '#ffe3a0' : '#f1f5f9';
    G.fillText(l1, x + padX + dot, y + padY + fs1 * 0.86);
    if (tag) {
        G.font = '500 ' + fs2 + 'px ' + FONT;
        G.fillStyle = '#7dd3fc';
        G.fillText(tag, x + padX + dot + w1, y + padY + fs1 * 0.86);
    }
    if (l2) {
        G.font = '500 ' + fs2 + 'px ' + FONT;
        G.fillStyle = '#aab6cc';
        G.fillText(l2, x + padX, y + padY + fs1 + fs2 * 0.95 + SC * 0.5);
    }
}

function drawBubble(a, nowSec) {
    if (!a.bubble || nowSec > a.bubble.until) return;
    const G = V.G, SC = V.LS;
    const alpha = Math.min(1, (a.bubble.until - nowSec) / 0.6, (nowSec - a.bubble.from) / 0.25);
    const fs = Math.max(9 * V.DPR, 8 * SC);
    G.font = '600 ' + fs + 'px ' + FONT;
    const str = clip(tr(a.bubble.text), 34);
    const w = G.measureText(str).width + 12 * SC, h = fs + 9 * SC;
    const x = X(a.x) - w / 2;
    const y = (a.pose === 'sitS' ? Y(a.y - 66) : Y(a.y - 78)) - h;
    if (x + w < 0 || x > canvas.width || y + h < 0 || y > canvas.height) return;
    G.globalAlpha = Math.max(0, alpha);
    pillPath(x, y, w, h, 6 * SC);
    G.fillStyle = '#f8fafc';
    G.fill();
    G.beginPath();
    G.moveTo(X(a.x) - 4 * SC, y + h - 1); G.lineTo(X(a.x), y + h + 5 * SC); G.lineTo(X(a.x) + 4 * SC, y + h - 1);
    G.fill();
    G.fillStyle = '#0f172a';
    G.textAlign = 'center';
    G.fillText(str, x + w / 2, y + h / 2 + fs * 0.35);
    G.textAlign = 'left';
    G.globalAlpha = 1;
}

/* ---------- кадр ---------- */

export function renderFrame(t, list, seatOf, editor) {
    const sky = SKY[layerPhase], G = ctx, SC = V.SC;
    V.G = ctx;
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.fillStyle = backdrop;
    ctx.fillRect(0, 0, canvas.width, canvas.height);

    const edit = editor && editor.active;
    // фон из кэша: при сдвиге камеры просто переносим, при масштабе растягиваем без размытия
    const same = Math.abs(bgScale - SC) < 0.001;
    ctx.imageSmoothingEnabled = !same && bgScale > SC;
    if (same) ctx.drawImage(bgLayer, V.OX, V.OY);
    else ctx.drawImage(bgLayer, V.OX, V.OY, Math.round(W * SC), Math.round(H * SC));
    ctx.imageSmoothingEnabled = true;

    ctx.save();
    ctx.beginPath();
    ctx.rect(V.OX, V.OY, Math.round(W * SC), Math.round(H * SC));
    ctx.clip();

    // живая часть стены: звёзды, окна в домах, стрелки часов
    if (sky.stars) stars.forEach(s => R(s.x, s.y, 2, 2, 'rgba(255,255,255,' + (0.3 + 0.7 * Math.abs(Math.sin((t + s.s) / 40))).toFixed(2) + ')'));
    if (sky.lit) lights.forEach(l => { if ((t + l.s) % 320 < 296) R(l.x, l.y, 3, 3, l.c); });
    drawClockHands(G, X, Y, SC);

    // кто где сидит
    const occupant = seat => list.find(a => seatOf[a.id] === seat && a.pose !== 'stand');
    const seatsByItem = {};
    scene.seats.concat(scene.bossSeat ? [scene.bossSeat] : []).forEach(s => (seatsByItem[s.item] = seatsByItem[s.item] || []).push(s));

    const ents = [];
    scene.layout.items.forEach((it, idx) => {
        const def = ITEMS[it.type];
        const seats = seatsByItem[it.id] || [];
        const occ = seats.map(occupant);
        ents.push({ y: it.y + def.d, draw: () => def.draw(it, { t, seed: idx * 3 + 1, occ }) });
        seats.forEach((s, i) => { if (!occ[i]) ents.push({ y: s.y - 1, draw: () => drawChair(s.x, s.y, s.side, !!s.boss) }); });
    });
    scene.layout.zones.forEach(z => {
        const walls = zoneWalls(z);
        const south = walls.filter(s => s.side === 'south');
        const labelWall = south.length ? south.reduce((a, b) => (b.w > a.w ? b : a)) : null;
        walls.forEach(s => {
            if (s.dir === 'h') {
                ents.push({ y: s.y + s.h, draw: () => { drawWallH(s); if (s === labelWall) drawZoneLabel(z); } });
            } else {
                for (let y0 = s.y; y0 < s.y + s.h; y0 += 24) {
                    const y1 = Math.min(s.y + s.h, y0 + 24);
                    ents.push({ y: y1, draw: () => drawWallV(s, y0, y1) });
                }
            }
        });
    });
    list.forEach(a => ents.push({ y: a.y + 0.5, draw: () => { if (edit) G.globalAlpha = 0.45; drawPerson(a, t, hoverId === a.id); G.globalAlpha = 1; } }));
    ents.sort((p, q) => p.y - q.y).forEach(e => e.draw());

    ctx.fillStyle = sky.tint;
    ctx.fillRect(V.OX, V.OY, Math.round(W * SC), Math.round(H * SC));

    // свет: мониторы работающих, лампы
    ctx.globalCompositeOperation = 'lighter';
    const night = layerPhase === 'night' || layerPhase === 'dusk';
    const pulse = (0.12 + 0.03 * Math.sin(t / 12)).toFixed(3);
    list.forEach(a => {
        const s = seatOf[a.id];
        if (!a.working || !s || a.pose === 'stand') return;
        glow(s.x, s.side === 'N' ? s.y - 14 : s.y - 50, s.side === 'N' ? 50 : 66, 'rgba(70,170,255,' + pulse + ')');
    });
    scene.layout.items.forEach(it => {
        if (it.type === 'floor_lamp') glow(it.x + 13, it.y - 80, night ? 110 : 55, night ? 'rgba(255,200,110,0.22)' : 'rgba(255,200,110,0.06)');
        if (it.type === 'boss_desk') glow(it.x + 119, it.y - 12, night ? 50 : 25, 'rgba(255,215,120,0.16)');
        if (it.type === 'vending') glow(it.x + 18, it.y - 36, 50, night ? 'rgba(120,200,255,0.12)' : 'rgba(120,200,255,0.04)');
    });
    ctx.globalCompositeOperation = 'source-over';

    // виньетка
    const cx = X(W / 2), cy = Y(H / 2);
    const vg = ctx.createRadialGradient(cx, cy, Math.min(W, H) * SC * 0.4, cx, cy, W * SC * 0.64);
    vg.addColorStop(0, 'rgba(0,0,0,0)');
    vg.addColorStop(1, 'rgba(2,4,14,0.45)');
    ctx.fillStyle = vg;
    ctx.fillRect(V.OX, V.OY, Math.round(W * SC), Math.round(H * SC));

    if (edit) drawEditorOverlay(editor);
    else {
        list.slice().sort((p, q) => p.y - q.y).forEach(a => drawLabel(a, t));
        const nowSec = performance.now() / 1000;
        list.forEach(a => drawBubble(a, nowSec));
        // подсказка, что делать дальше: сначала обставить офис, потом нанять людей
        const hint = !scene.layout.items.length
            ? ['Офис пока пустой', 'Нажмите «✏️ Планировка» и расставьте столы, мебель и зоны']
            : !list.length ? ['В офисе пока никого нет', 'Откройте Настройки → Агенты и наймите сотрудников'] : null;
        if (hint) {
            ctx.textAlign = 'center';
            ctx.font = '600 ' + (14 * SC) + 'px ' + FONT;
            ctx.fillStyle = 'rgba(241,245,249,0.92)';
            ctx.fillText(tr(hint[0]), X(W / 2), Y(H / 2 - 4));
            ctx.font = '500 ' + (10.5 * SC) + 'px ' + FONT;
            ctx.fillStyle = 'rgba(170,182,204,0.85)';
            ctx.fillText(tr(hint[1]), X(W / 2), Y(H / 2 + 16));
            ctx.textAlign = 'left';
        }
    }
    ctx.restore();
}

/* ---------- слой редактора планировки ---------- */

function strokeRect(r, color, width = 1, dash = null) {
    const G = V.G;
    G.strokeStyle = color;
    G.lineWidth = Math.max(1, width * V.DPR);
    G.setLineDash(dash ? dash.map(d => d * V.DPR) : []);
    G.strokeRect(X(r[0]) + 0.5, Y(r[1]) + 0.5, X(r[0] + r[2]) - X(r[0]), Y(r[1] + r[3]) - Y(r[1]));
    G.setLineDash([]);
}

function drawEditorOverlay(ed) {
    const G = V.G;
    // сетка-подсказка
    G.fillStyle = 'rgba(94,200,255,0.06)';
    for (let x = 0; x < W; x += 24) G.fillRect(X(x), Y(WALL_Y), 1, Math.round((H - WALL_Y) * V.SC));
    for (let y = WALL_Y; y < H; y += 24) G.fillRect(X(0), Y(y), Math.round(W * V.SC), 1);

    scene.layout.zones.forEach(z => {
        const sel = ed.sel && ed.sel.kind === 'zone' && ed.sel.id === z.id;
        strokeRect([z.x, z.y, z.w, z.h], sel ? '#5ec8ff' : 'rgba(167,139,250,0.85)', sel ? 2 : 1.2, [6, 4]);
        if (sel) {
            G.fillStyle = '#5ec8ff';
            G.fillRect(X(z.x + z.w) - 5 * V.DPR, Y(z.y + z.h) - 5 * V.DPR, 10 * V.DPR, 10 * V.DPR);
        }
    });
    scene.layout.items.forEach(it => {
        const sel = ed.sel && ed.sel.kind === 'item' && ed.sel.id === it.id;
        const bad = !!(ed.problems && ed.problems[it.id]);
        strokeRect(solidRect(it), bad ? '#f87171' : sel ? '#5ec8ff' : 'rgba(148,163,184,0.45)', sel || bad ? 2 : 1, sel ? null : [3, 3]);
    });
    (ed.unreachable || []).forEach(s => {
        G.fillStyle = 'rgba(248,113,113,0.9)';
        G.beginPath(); G.arc(X(s.x), Y(s.y - 20), 6 * V.SC, 0, Math.PI * 2); G.fill();
    });
    scene.seats.forEach((s, i) => {
        G.font = '700 ' + (7 * V.SC) + 'px ' + FONT;
        G.fillStyle = 'rgba(94,200,255,0.95)';
        G.textAlign = 'center';
        G.fillText('#' + (i + 1), X(s.x), Y(s.side === 'N' ? s.y - 42 : s.y + 12));
        G.textAlign = 'left';
    });
}
