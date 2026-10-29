// Сцена, собранная из планировки: места для сидения, препятствия, сетка для поиска пути,
// точки, куда гуляют свободные агенты. Плюс проверки для редактора: влезает ли предмет,
// сколько ещё столов поместится, авторасстановка.
import { W, H, WALL_Y } from './core.js';
import { ITEMS, EMPTY_LAYOUT, FLOOR, footprint, solidRect, rectsOverlap, zoneWalls } from './catalog.js';

export const CELL = 12;
const GW = Math.ceil(W / CELL), GH = Math.ceil(H / CELL);
export const MAX_ITEMS = 200, MAX_ZONES = 20;

// самая «узкая» зона, в которую попадает точка (зона внутри зоны важнее внешней)
export function zoneAt(layout, x, y) {
    let best = null;
    layout.zones.forEach(z => {
        if (x >= z.x && x <= z.x + z.w && y >= z.y && y <= z.y + z.h && (!best || z.w * z.h < best.w * best.h)) best = z;
    });
    return best;
}

export let scene = null;
let blocked = new Uint8Array(GW * GH);

export function cloneLayout(l) { return JSON.parse(JSON.stringify(l)); }

function mix32(n) {
    n = Math.imul((n | 0) ^ ((n | 0) >>> 16), 0x45d9f3b);
    return ((n ^ (n >>> 13)) >>> 0);
}

// own = true: редактор передаёт свой черновик и меняет его на месте, копия не нужна
export function normalizeLayout(raw, own = false) {
    const ok = raw && Array.isArray(raw.items) && Array.isArray(raw.zones);
    const l = ok ? (own ? raw : cloneLayout(raw)) : cloneLayout(EMPTY_LAYOUT);
    l.items = l.items.filter(it => ITEMS[it.type] && Number.isFinite(it.x) && Number.isFinite(it.y));
    l.zones = l.zones.filter(z => [z.x, z.y, z.w, z.h].every(Number.isFinite));
    return l;
}

// все прямоугольники, которые нельзя проходить: предметы, кресла у столов и стены зон
function obstacleRects(layout) {
    const rects = layout.items.map(it => footprint(it));
    layout.items.forEach(it => {
        const def = ITEMS[it.type];
        if (!def.seats) return;
        def.seats(it).forEach(s => rects.push(s.side === 'N' ? [s.x - 12, s.y - 12, 24, 8] : [s.x - 13, s.y - 6, 26, 9]));
    });
    layout.zones.forEach(z => zoneWalls(z).forEach(s => rects.push([s.x, s.y, s.w, s.h])));
    return rects;
}

function buildGrid(layout) {
    blocked = new Uint8Array(GW * GH);
    // запас на размер человека: в ширину он больше, а по глубине важна только линия ступней
    const PADX = 11, PADY = 6;
    obstacleRects(layout).forEach(b => {
        const x0 = Math.floor((b[0] - PADX) / CELL), x1 = Math.floor((b[0] + b[2] + PADX) / CELL);
        const y0 = Math.floor((b[1] - PADY) / CELL), y1 = Math.floor((b[1] + b[3] + PADY) / CELL);
        for (let cy = Math.max(0, y0); cy <= Math.min(GH - 1, y1); cy++)
            for (let cx = Math.max(0, x0); cx <= Math.min(GW - 1, x1); cx++) blocked[cy * GW + cx] = 1;
    });
    for (let cx = 0; cx < GW; cx++) {
        for (let cy = 0; cy < Math.ceil((WALL_Y + 18) / CELL); cy++) blocked[cy * GW + cx] = 1;
        blocked[(GH - 1) * GW + cx] = 1;
    }
    for (let cy = 0; cy < GH; cy++) { blocked[cy * GW] = 1; blocked[cy * GW + GW - 1] = 1; }
}

export function buildScene(raw, own = false) {
    const layout = normalizeLayout(raw, own);
    buildGrid(layout);
    const seats = [];
    let bossSeat = null;
    layout.items.forEach(it => {
        const def = ITEMS[it.type];
        if (!def.seats) return;
        def.seats(it).forEach(s => {
            const seat = settleApproach({ ...s, item: it.id });
            if (s.boss) { if (!bossSeat) bossSeat = seat; } else seats.push(seat);
        });
    });
    // точки для прогулок: перед кулером, кофемашиной, диваном, доской и в центре зон
    const spots = [];
    layout.items.forEach(it => {
        const def = ITEMS[it.type];
        if (def.desk || def.boss) return;
        const p = { x: it.x + def.w / 2, y: it.y + def.d + 16 };
        if (isFree(p.x, p.y)) spots.push(p);
    });
    // в каждой зоне - несколько точек, чтобы туда было куда прийти
    layout.zones.forEach((z, zi) => {
        const want = [{ x: z.x + z.w / 2, y: z.y + z.h * 0.7 }];
        for (let k = 0; k < 12 && want.length < 4; k++) {
            want.push({ x: z.x + 16 + (mix32(zi * 31 + k) % Math.max(1, z.w - 32)), y: z.y + 16 + (mix32(zi * 17 + k * 7) % Math.max(1, z.h - 32)) });
        }
        want.forEach(p => { if (isFree(p.x, p.y)) spots.push(p); });
    });
    for (let i = 0; spots.length < 8 && i < 400; i++) {
        const p = { x: 30 + (i * 97) % (W - 60), y: WALL_Y + 40 + (i * 53) % (H - WALL_Y - 60) };
        if (isFree(p.x, p.y)) spots.push(p);
    }
    // точки в «карманах» (например, под диваном) свободны, но туда не дойти - такие выбрасываем
    const reachable = reachFilter(spots.map(p => ({ sx: p.x, sy: p.y, p })), true).map(o => o.p);
    reachable.forEach(p => { p.zone = zoneAt(layout, p.x, p.y); });
    scene = { layout, seats, bossSeat, spots: reachable };
    return scene;
}

/* ---------- поиск пути: A* по сетке, потом спрямление ---------- */

export function isFree(x, y) {
    const cx = Math.floor(x / CELL), cy = Math.floor(y / CELL);
    if (cx < 0 || cy < 0 || cx >= GW || cy >= GH) return false;
    return !blocked[cy * GW + cx];
}

function nearestFree(x, y) {
    const cx = Math.max(0, Math.min(GW - 1, Math.floor(x / CELL)));
    const cy = Math.max(0, Math.min(GH - 1, Math.floor(y / CELL)));
    if (!blocked[cy * GW + cx]) return [cx, cy];
    // ближайшая по настоящему расстоянию свободная клетка (а не первая попавшаяся в кольце):
    // иначе человек, вставая из-за стола, мог «выйти» на другую сторону стола прямо сквозь него
    let best = null, bestD = Infinity;
    for (let dy = -12; dy <= 12; dy++) for (let dx = -12; dx <= 12; dx++) {
        const nx = cx + dx, ny = cy + dy;
        if (nx < 0 || ny < 0 || nx >= GW || ny >= GH || blocked[ny * GW + nx]) continue;
        const d = Math.hypot(nx * CELL + CELL / 2 - x, ny * CELL + CELL / 2 - y);
        if (d < bestD) { bestD = d; best = [nx, ny]; }
    }
    return best || [cx, cy];
}

function lineClear(x0, y0, x1, y1) {
    const n = Math.ceil(Math.hypot(x1 - x0, y1 - y0) / 5);
    for (let i = 1; i < n; i++) {
        const t = i / n;
        if (!isFree(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)) return false;
    }
    return true;
}

function astar(sx, sy, gx, gy) {
    const start = sy * GW + sx, goal = gy * GW + gx;
    const g = new Float32Array(GW * GH).fill(Infinity);
    const from = new Int32Array(GW * GH).fill(-1);
    const open = [start], inOpen = new Uint8Array(GW * GH);
    g[start] = 0;
    const heur = i => Math.hypot((i % GW) - gx, Math.floor(i / GW) - gy);
    while (open.length) {
        let bi = 0;
        for (let i = 1; i < open.length; i++) if (g[open[i]] + heur(open[i]) < g[open[bi]] + heur(open[bi])) bi = i;
        const cur = open.splice(bi, 1)[0];
        inOpen[cur] = 0;
        if (cur === goal) return from;
        const cx = cur % GW, cy = Math.floor(cur / GW);
        for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
            if (!dx && !dy) continue;
            const nx = cx + dx, ny = cy + dy;
            if (nx < 0 || ny < 0 || nx >= GW || ny >= GH || blocked[ny * GW + nx]) continue;
            if (dx && dy && (blocked[cy * GW + nx] || blocked[ny * GW + cx])) continue;
            const ni = ny * GW + nx, ng = g[cur] + (dx && dy ? 1.414 : 1);
            if (ng < g[ni]) { g[ni] = ng; from[ni] = cur; if (!inOpen[ni]) { open.push(ni); inOpen[ni] = 1; } }
        }
    }
    return null;
}

// маршрут в обход препятствий или null, если пройти нельзя (тогда сквозь мебель не идём)
export function findPath(ax, ay, bx, by) {
    const [sx, sy] = nearestFree(ax, ay), [gx, gy] = nearestFree(bx, by);
    const from = astar(sx, sy, gx, gy);
    if (!from) return null;
    let pts = [];
    for (let c = gy * GW + gx; c !== -1; c = from[c]) pts.push({ x: (c % GW) * CELL + CELL / 2, y: Math.floor(c / GW) * CELL + CELL / 2 });
    pts.reverse();
    pts[pts.length - 1] = { x: bx, y: by };
    const out = [];
    let cur = { x: ax, y: ay }, i = 0;
    while (i < pts.length) {
        let far = i;
        for (let k = pts.length - 1; k > i; k--) if (lineClear(cur.x, cur.y, pts[k].x, pts[k].y)) { far = k; break; }
        out.push(pts[far]);
        cur = pts[far];
        i = far + 1;
    }
    return out;
}

// точка подхода к месту могла попасть в занятую клетку сетки (кресло соседа, округление):
// отодвигаем её от стола, пока не станет свободной, иначе к месту не дойти
function settleApproach(s) {
    const dir = s.side === 'N' ? -1 : 1;
    for (let i = 0; i < 6 && !isFree(s.sx, s.sy); i++) s.sy += dir * 6;
    return s;
}

function allSeats(layout) {
    const out = [];
    layout.items.forEach(it => { if (ITEMS[it.type].seats) out.push(...ITEMS[it.type].seats(it).map(settleApproach)); });
    return out;
}

// сколько мест в планировке недоступно; сетка временно строится под эту планировку
function unreachableCount(layout) {
    buildGrid(layout);
    return reachFilter(allSeats(layout)).length;
}

// до каких мест нельзя дойти (например, стол замурован мебелью)
export function unreachableSeats() {
    if (!scene) return [];
    return reachFilter(scene.seats.concat(scene.bossSeat ? [scene.bossSeat] : []));
}

// по умолчанию возвращает недоступные точки (их подсвечивает редактор); keep = true - наоборот, доступные
function reachFilter(all, keep = false) {
    const [sx, sy] = nearestFree(W / 2, H - 40);
    const seen = new Uint8Array(GW * GH), queue = [sy * GW + sx];
    seen[queue[0]] = 1;
    while (queue.length) {
        const c = queue.pop(), cx = c % GW, cy = Math.floor(c / GW);
        [[1, 0], [-1, 0], [0, 1], [0, -1]].forEach(([dx, dy]) => {
            const nx = cx + dx, ny = cy + dy, ni = ny * GW + nx;
            if (nx >= 0 && ny >= 0 && nx < GW && ny < GH && !blocked[ni] && !seen[ni]) { seen[ni] = 1; queue.push(ni); }
        });
    }
    return all.filter(s => {
        const cx = Math.floor(s.sx / CELL), cy = Math.floor(s.sy / CELL);
        const ok = cx >= 0 && cy >= 0 && cx < GW && cy < GH && !!seen[cy * GW + cx];
        return keep ? ok : !ok;
    });
}

/* ---------- проверки для редактора ---------- */

// у стены может стоять только «настенная» мебель; остальным нужен проход вдоль стены
function insideFloor(r, wallItem) {
    return r[0] >= 0 && r[0] + r[2] <= W && r[1] + r[3] <= H && r[1] >= (wallItem ? WALL_Y - 4 : WALL_Y + 6);
}

// причина, по которой предмет нельзя поставить сюда, или '' если можно
export function placementProblem(layout, item) {
    const def = ITEMS[item.type];
    const fp = footprint(item), solid = solidRect(item);
    if (fp[0] < FLOOR.x0 || fp[0] + fp[2] > FLOOR.x1 || fp[1] < FLOOR.y0 || fp[1] + fp[3] > FLOOR.y1) return 'выходит за пределы офиса';
    if (!insideFloor(solid, def.wall)) return 'не хватает места для кресел и прохода';
    for (const other of layout.items) {
        if (other.id === item.id) continue;
        if (rectsOverlap(solid, solidRect(other))) return 'пересекается с «' + ITEMS[other.type].label + '»';
    }
    for (const z of layout.zones) {
        for (const s of zoneWalls(z)) if (rectsOverlap(fp, [s.x, s.y, s.w, s.h])) return 'стоит на стене зоны «' + (z.label || 'без имени') + '»';
    }
    return '';
}

export function deskCount(layout) {
    return layout.items.filter(it => it.type === 'desk_pod').length;
}

// ищем свободное место для нового предмета: сначала рядом с подсказкой, потом по всему полу
export function findFreeSpot(layout, type, near) {
    const def = ITEMS[type];
    const cand = [];
    for (let y = FLOOR.y0 + 4; y + def.d <= FLOOR.y1; y += 8) {
        for (let x = FLOOR.x0 + 4; x + def.w <= FLOOR.x1; x += 8) cand.push({ x, y });
    }
    if (near) cand.sort((a, b) => Math.hypot(a.x - near.x, a.y - near.y) - Math.hypot(b.x - near.x, b.y - near.y));
    // новое место не должно перекрыть проход к уже стоящим столам, а к нему самому нужно подойти
    const base = unreachableCount(layout);
    let found = null;
    for (const p of cand) {
        const it = { id: '__probe', type, x: p.x, y: p.y };
        if (placementProblem(layout, it)) continue;
        if (unreachableCount({ ...layout, items: layout.items.concat([it]) }) <= base) { found = p; break; }
    }
    buildGrid(scene ? scene.layout : layout);       // вернуть сетку текущей планировки
    return found;
}

// куда ставить следующий блок столов: правее последнего, чтобы ряды росли аккуратно
export function nextDeskHint(layout) {
    const last = layout.items.filter(it => it.type === 'desk_pod').pop();
    return last ? { x: last.x + 120, y: last.y } : { x: 700, y: 400 };
}

// сколько ещё блоков столов можно добавить (жадно, по одному, тем же способом, что и кнопка «+»)
// это только подсказка: ставить больше можно, лишние столы подсветятся красным
export function freeDeskSlots(layout, maxProbe = 8) {
    const probe = cloneLayout(layout);
    let n = 0;
    while (n < maxProbe) {
        const p = findFreeSpot(probe, 'desk_pod', nextDeskHint(probe));
        if (!p) break;
        probe.items.push({ id: '__p' + n, type: 'desk_pod', x: p.x, y: p.y });
        n++;
    }
    return n;
}

let idSeq = Date.now() % 100000;
export function newId(prefix) { return prefix + (idSeq++).toString(36); }
