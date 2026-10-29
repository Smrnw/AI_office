// Поведение сотрудников: идут к своему столу, когда получили задачу, свободные гуляют.
// Пока агент не сел за стол, сервер не начинает работу: мы сообщаем ему о прибытии.
import { hash } from './core.js';
import { palFor } from './people.js';
import { scene, findPath } from './scene.js';
import { ZONE_ACTIVITIES, zoneAllows } from './catalog.js';

export const sprites = {};      // id агента -> спрайт
let seatOf = {};                // id агента -> место
let seatSig = '';
let onArrive = () => {};

export function seatMap() { return seatOf; }
export function setArrivalHandler(fn) { onArrive = fn; }

// руководитель (первый planner) садится в кабинет, остальные по desk_idx, при конфликте - следующее свободное
function assignSeats(entries) {
    seatOf = {};
    if (!scene) return;
    const taken = new Set();
    const seats = scene.seats;
    const boss = entries.find(([, a]) => a.pipeline_type === 'planner');
    if (boss && scene.bossSeat) seatOf[boss[0]] = scene.bossSeat;
    entries.filter(([k]) => seatOf[k] === undefined)
        .sort((a, b) => (a[1].desk_idx || 0) - (b[1].desk_idx || 0))
        .forEach(([k, a]) => {
            if (!seats.length) return;
            let idx = (parseInt(a.desk_idx, 10) || 0) % seats.length;
            for (let tries = 0; tries < seats.length && taken.has(idx); tries++) idx = (idx + 1) % seats.length;
            if (!taken.has(idx)) { taken.add(idx); seatOf[k] = seats[idx]; }
        });
}

function spawnSprite(id) {
    const seat = seatOf[id];
    const spots = scene.spots.length ? scene.spots : [{ x: 480, y: 400 }];
    const spot = spots[hash(id) % spots.length];
    return {
        id, x: seat ? seat.x : spot.x, y: seat ? seat.y : spot.y,
        route: [], goal: seat ? 'seat' : 'spot', atGoal: true,
        nextWalk: performance.now() / 1000 + 3 + (hash(id) % 12), leaveAt: 0,
        moving: false, dir: 1, face: 'front', pose: 'stand',
        phase: (hash(id) % 628) / 100, working: false, walking: false, reported: false
    };
}

function sendTo(a, kind) {
    const seat = seatOf[a.id];
    // сидящий сначала отходит от стола к «подходу» своего места, а уже оттуда ищет путь:
    // иначе маршрут мог начаться с клетки по другую сторону стола, прямо сквозь мебель
    const head = (a.pose !== 'stand' && a.sitSeat) ? [{ x: a.sitSeat.sx, y: a.sitSeat.sy }] : [];
    const from = head.length ? head[0] : a;
    a.atGoal = false;
    if (kind === 'seat' && seat) {
        a.goal = 'seat';
        const path = findPath(from.x, from.y, seat.sx, seat.sy);
        // к своему столу попасть нужно в любом случае; если проход закрыт мебелью, идём напрямую
        a.route = head.concat(path || [{ x: seat.sx, y: seat.sy }], [{ x: seat.x, y: seat.y, final: true }]);
        return;
    }
    const spot = pickSpot(a);
    const path = findPath(from.x, from.y, spot.x, spot.y);
    a.goal = 'spot';
    if (!path) {                       // туда не пройти: стоим и через пару секунд выберем другое место
        a.route = head;
        a.goalSpot = null;
        a.leaveAt = performance.now() / 1000 + 3;
        return;
    }
    a.route = head.concat(path);
    a.goalSpot = spot;
}

// куда пойти погулять: только в зоны, куда агенту можно, и охотнее туда, где отдыхают
function pickSpot(a) {
    const all = scene.spots.length ? scene.spots : [{ x: 480, y: 400, zone: null }];
    const allowed = all.filter(p => zoneAllows(p.zone, a.ptype) && Math.hypot(p.x - a.x, p.y - a.y) > 50);
    const pool = allowed.length ? allowed : all;
    const weight = p => (p.zone && ZONE_ACTIVITIES[p.zone.activity] ? ZONE_ACTIVITIES[p.zone.activity].weight : 1);
    let r = Math.random() * pool.reduce((s, p) => s + weight(p), 0);
    for (const p of pool) { r -= weight(p); if (r <= 0) return p; }
    return pool[pool.length - 1];
}

// пришёл в зону - коротко говорит, чем там занимается
function arrivedAtSpot(a) {
    const z = a.goalSpot && a.goalSpot.zone;
    const act = z && ZONE_ACTIVITIES[z.activity];
    if (act && act.bubble && Math.random() < 0.6) say(a.id, act.bubble, 3.5);
}

function seated(a) {
    return a.atGoal && !a.moving && a.goal === 'seat';
}

function think(a, now) {
    const seat = seatOf[a.id];
    const needDesk = a.working || a.walking;
    if (!a.walking) a.reported = false;
    if (needDesk) {
        if (seat && a.goal !== 'seat') sendTo(a, 'seat');
        if (a.walking && !a.reported && (!seat || seated(a))) {
            a.reported = true;
            onArrive(a.id);
        }
        return;
    }
    if (!a.atGoal) return;
    if (a.goal === 'seat' && seat && now > a.nextWalk) sendTo(a, 'spot');
    else if (a.goal === 'spot' && now > a.leaveAt) sendTo(a, seat ? 'seat' : 'spot');
}

export function updateSprites(dt) {
    if (!scene) return;
    const now = performance.now() / 1000;
    const speed = 95;
    Object.values(sprites).forEach(a => {
        think(a, now);
        const next = a.route[0];
        if (next) {
            const dx = next.x - a.x, dy = next.y - a.y, dist = Math.hypot(dx, dy);
            if (dist < 1.2) {
                a.x = next.x; a.y = next.y;
                a.route.shift();
            } else {
                // к столу торопимся, гуляем спокойно
                const v = (a.walking || a.working ? 130 : speed) * dt;
                const len = Math.min(dist, v);
                a.x += dx / dist * len; a.y += dy / dist * len;
                if (Math.abs(dx) > 0.4) a.dir = dx > 0 ? 1 : -1;
                a.face = dy < -Math.abs(dx) * 0.6 ? 'back' : 'front';
            }
            a.moving = true;
        } else {
            if (a.moving || !a.atGoal) {
                a.atGoal = true;
                if (a.goal === 'seat') a.nextWalk = now + 14 + Math.random() * 30;
                else { a.leaveAt = now + 5 + Math.random() * 8; arrivedAtSpot(a); }
            }
            a.moving = false;
        }
        const seat = seatOf[a.id];
        a.pose = (seated(a) && seat) ? (seat.side === 'N' ? 'sitN' : 'sitS') : 'stand';
        if (a.pose !== 'stand') a.sitSeat = seat;      // откуда вставать: через подход этого места
    });
}

// короткое имя модели для подписи над головой: "Gemini 2.5 Pro" -> "g-2.5-pro"
function modelShort(name) {
    const s = String(name || '').toLowerCase().replace(/\(.*?\)/g, '').trim();
    if (!s) return '';
    const words = s.split(/[\s_/]+/).filter(Boolean);
    if (words.length === 1) return words[0].slice(0, 14);
    return (words[0][0] + '-' + words.slice(1).join('-')).slice(0, 14);
}

// подтягиваем спрайты под список агентов с сервера (и под текущую планировку)
export function syncAgents(agents, force = false) {
    if (!scene) return;
    const entries = Object.entries(agents || {});
    const sig = entries.map(([k, a]) => k + ':' + a.pipeline_type + ':' + a.desk_idx).join('|');
    if (force || sig !== seatSig) {
        seatSig = sig;
        assignSeats(entries);
    }
    entries.forEach(([k, a]) => {
        const sp = sprites[k] || (sprites[k] = spawnSprite(k));
        sp.working = a.status === 'Работает';
        sp.walking = a.status === 'Идёт';
        sp.action = a.action;
        sp.role = a.role;
        sp.ptype = a.pipeline_type;
        sp.pal = palFor(a);
        sp.modelShort = modelShort(a.model_name || a.model_ref);
        sp.isBoss = !!(seatOf[k] && seatOf[k].boss);
        if (sp.seatRef !== seatOf[k]) {
            const first = sp.seatRef === undefined;
            const seat = seatOf[k];
            sp.seatRef = seat;
            // планировку перечитали, а место осталось тем же: человек продолжает сидеть
            const alreadyThere = seat && sp.atGoal && sp.goal === 'seat' && Math.hypot(sp.x - seat.x, sp.y - seat.y) < 2;
            if (!first && !alreadyThere) sendTo(sp, seat ? 'seat' : 'spot');
        }
    });
    Object.keys(sprites).forEach(k => { if (!agents || !agents[k]) delete sprites[k]; });
}

export function say(id, text, seconds = 5) {
    const sp = sprites[id];
    if (!sp || !text) return;
    const now = performance.now() / 1000;
    sp.bubble = { text: String(text), from: now, until: now + seconds };
}

export function seatLabel(id) {
    const seat = seatOf[id];
    if (!seat) return 'без места';
    return seat.boss ? 'Кабинет' : 'Место #' + (scene.seats.indexOf(seat) + 1);
}

export function hitAgent(p) {
    const list = Object.values(sprites).sort((a, b) => b.y - a.y);
    return list.find(a => Math.abs(p.x - a.x) < 18 && p.y > a.y - 60 && p.y < a.y + 6) || null;
}
