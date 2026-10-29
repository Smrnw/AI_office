// Каталог предметов офиса: размеры, места для сидения, отрисовка. Плюс стандартная планировка.
//
// У предмета есть «след» на полу (x, y, w, d) и высота h: крышка рисуется над следом,
// передняя грань доходит до y + d. По y + d предметы и люди сортируются по глубине.
import { W, H, WALL_Y, R, RO, box, mix, shade, softShadow, groundShadow, PAL, text } from './core.js';

/* ------------------------------------------------------------------
   Мелкие детали, из которых собираются столы
------------------------------------------------------------------- */

const CODE_COLORS = ['#38bdf8', '#a78bfa', '#34d399', '#fbbf24', '#f472b6', '#e2e8f0'];

// монитор. facing 'S' — экраном к зрителю, 'N' — спиной
export function drawMonitor(cx, baseY, facing, active, seed, t, wide = false) {
    const mw = wide ? 40 : 34, mh = 24;
    const x = cx - mw / 2, y = baseY - mh - 4;
    // подставка: ножка и основание
    R(cx - 2, baseY - 5, 4, 5, '#1b2230');
    R(cx - 8, baseY - 1, 16, 2, '#11151d');
    R(cx - 7, baseY - 1, 14, 1, '#3a4458');
    if (facing === 'N') {
        RO(x, y, mw, mh, '#5b6577', '#151a24');                                 // светлый пластиковый корпус
        R(x + 2, y + 2, mw - 4, 2, '#7d889b');
        R(x + mw - 5, y + 2, 3, mh - 4, '#485163');
        for (let i = 0; i < 4; i++) R(x + 6 + i * 3, y + 6, 1, 6, '#3b4252');   // вентиляция
        R(cx + mw / 2 - 9, y + mh - 6, 4, 2, active ? '#5ec8ff' : '#4b5568');      // светодиод
        return;
    }
    RO(x, y, mw, mh, '#1a202c', '#07090e');
    R(x + 2, y + 2, mw - 4, mh - 5, active ? '#0b1a33' : '#0f1522');
    if (active) {
        const base = Math.floor(t / 8);
        for (let i = 0; i < 6; i++) {
            const h = mix(base + i * 17 + seed * 5);
            const indent = (h % 3) * 3;
            R(x + 4 + indent, y + 4 + i * 2.6, Math.min(3 + (h >> 3) % 15, mw - 9 - indent), 1.4, CODE_COLORS[(h >> 7) % 6]);
        }
        if (Math.floor(t / 18) % 2 === 0) R(x + 4, y + mh - 6, 2, 1.6, '#f8fafc');
        R(x + 2, y + 2, mw - 4, 1, 'rgba(255,255,255,0.10)');
    } else {
        // заставка: медленно плавающий логотип
        const px = x + 4 + Math.abs(((t / 4 + seed * 9) % (2 * (mw - 12))) - (mw - 12));
        const py = y + 4 + Math.abs(((t / 5 + seed * 5) % 26) - 13);
        R(px, py, 4, 3, '#26344d');
        R(x + 2, y + 2, mw - 4, 1, 'rgba(255,255,255,0.05)');
    }
    R(x + mw / 2 - 1, y + mh - 2, 2, 1, '#4b5568');              // логотип на рамке
}

function keyboard(cx, y) {
    RO(cx - 15, y, 30, 7, '#d6dce5', '#5b6676');
    for (let r = 0; r < 2; r++) for (let k = 0; k < 7; k++) R(cx - 13 + k * 4, y + 1.5 + r * 2.4, 3, 1.4, '#9aa5b5');
}

function mouse(x, y) {
    RO(x, y, 5, 6, '#e8edf3', '#5b6676');
    R(x + 2, y + 1, 1, 2, '#9aa5b5');
}

function mug(x, y, color, steam, t) {
    RO(x, y, 7, 8, color, '#4a3a2a');
    R(x + 7, y + 2, 2, 4, color);
    R(x + 1, y + 1, 5, 2, '#5b3418');
    if (steam) {
        const k = Math.floor(t / 10) % 3;
        R(x + 2 + (k === 1 ? 1 : 0), y - 4, 1, 2, 'rgba(255,255,255,0.35)');
        R(x + 4 - (k === 2 ? 1 : 0), y - 7, 1, 2, 'rgba(255,255,255,0.25)');
    }
}

function papers(x, y) {
    R(x + 1, y + 1, 14, 10, 'rgba(0,0,0,0.25)');
    RO(x, y, 14, 10, '#f5f1e6', '#a59c86');
    for (let i = 0; i < 3; i++) R(x + 2, y + 2.5 + i * 2.4, 9 - i * 2, 0.8, '#9a917a');
}

function succulent(x, y) {
    RO(x, y + 4, 8, 6, '#c9734a', '#5a2c18');
    R(x + 1, y + 1, 2, 4, '#3f9a52'); R(x + 3, y - 1, 2, 6, '#56b866'); R(x + 5, y + 1, 2, 4, '#3f9a52');
}

// офисное кресло. side 'N' — спинка над плечами сидящего лицом к нам, 'S' — вид со спины
export function drawChair(x, y, side, boss = false) {
    if (boss) {
        const c = '#8a1d1d', d = '#4d0d0d', hi = '#c24444';
        if (side === 'N') {
            RO(x - 15, y - 54, 30, 34, c, d); R(x - 13, y - 52, 26, 2, hi);
            R(x - 10, y - 46, 1, 20, shade(c, -0.25)); R(x + 9, y - 46, 1, 20, shade(c, -0.25));
            return;
        }
        RO(x - 17, y - 34, 34, 30, c, d); R(x - 15, y - 32, 30, 2, hi);
        for (let i = 0; i < 3; i++) R(x - 12 + i * 10, y - 26, 2, 2, shade(c, -0.35));   // стёжка
        RO(x - 20, y - 22, 5, 16, '#5c1111', d); RO(x + 15, y - 22, 5, 16, '#5c1111', d);
        R(x - 2, y - 4, 4, 4, '#2a2f3a');
        R(x - 11, y, 22, 2, '#1a1e27'); R(x - 12, y + 1, 3, 2, '#0b0e14'); R(x + 9, y + 1, 3, 2, '#0b0e14');
        return;
    }
    const c = '#3a4866', d = '#0d1119', hi = '#6175a0';
    if (side === 'N') {
        // спинка кресла за столом: ниже монитора и светлее его корпуса, чтобы они не сливались
        RO(x - 11, y - 44, 22, 20, c, d); R(x - 9, y - 42, 18, 2, hi);
        R(x - 9, y - 36, 18, 1, shade(c, -0.25)); R(x - 9, y - 31, 18, 1, shade(c, -0.25));
        R(x - 13, y - 30, 3, 8, '#1c2332'); R(x + 10, y - 30, 3, 8, '#1c2332');
        return;
    }
    RO(x - 14, y - 28, 28, 22, c, d); R(x - 12, y - 26, 24, 2, hi); R(x - 8, y - 20, 16, 1, shade(c, -0.3));
    RO(x - 16, y - 16, 4, 9, '#1c2332', d); RO(x + 12, y - 16, 4, 9, '#1c2332', d);
    R(x - 1.5, y - 6, 3, 5, '#3a4458');
    R(x - 11, y - 1, 22, 2, '#151a24');
    R(x - 12, y + 1, 3, 2, '#05070b'); R(x - 1.5, y + 1.5, 3, 2, '#05070b'); R(x + 9, y + 1, 3, 2, '#05070b');
}

// один стол для одного места. north - место с северной стороны (человек лицом к нам)
function deskHalf(x, y, w, north, seed, occ, t) {
    softShadow(x - 3, y + 22 - 2, w + 8, 9, 0.38);
    box(x, y, w, 22, 20, PAL.wood);
    for (let i = 0; i < 3; i++) R(x + 6 + (mix(seed + i) % (w - 30)), y - 15 + i * 6, 18, 0.7, 'rgba(90,50,20,0.35)');   // волокна
    R(x + 3, y + 22, 4, 3, '#2b1a0d'); R(x + w - 7, y + 22, 4, 3, '#2b1a0d');                                       // ножки
    const top = y - 20, cx = x + w / 2, working = !!(occ && occ.working);
    if (north) {
        drawMonitor(cx, top + 15, 'N', working, seed, t);
        keyboard(cx, top + 2);
        mouse(cx + 19, top + 2);
        mug(x + 6, top + 10, '#f4f1e8', working, t);
        if (seed % 2) papers(x + w - 22, top + 9); else succulent(x + w - 16, top + 7);
        if (occ && occ.pose === 'sitN') {                         // руки на клавиатуре
            const k = working && Math.floor(t / 5) % 2;
            R(cx - 11, top + 2 + (k ? 1 : 0), 4, 3, occ.pal.skin); R(cx + 7, top + 2 + (k ? 0 : 1), 4, 3, occ.pal.skin);
        }
    } else {
        mug(x + 6, top + 3, ['#f4f1e8', '#fca5a5', '#93c5fd'][seed % 3], working, t);
        if (seed % 2) papers(x + w - 22, top + 2); else succulent(x + w - 16, top + 1);
        drawMonitor(cx, top + 13, 'S', working, seed, t, seed % 3 === 0);
        keyboard(cx, top + 14);
        mouse(cx + 19, top + 14);
    }
}

function divider(x, y, w) {
    const h = 40, d = 6, front = y - h + d;
    R(x, front, w, h, 'rgba(165,215,245,0.22)');
    R(x, y - h, w, d, '#aec2d6'); R(x, y - h, w, 1, '#eef5fb');
    R(x, front, w, 2, '#6f87a0'); R(x, y + d - 4, w, 4, '#4c6078');
    R(x, front, 3, h, '#6f87a0'); R(x + w - 3, front, 3, h, '#6f87a0');
    for (let k = 0; k < 4; k++) R(x + 14 + k * 26, front + 5, 5, h - 14, 'rgba(255,255,255,0.12)');
}

/* ------------------------------------------------------------------
   Каталог
------------------------------------------------------------------- */

const POD_W = 104, POD_D = 50;

function seatsPod(it) {
    return [
        { side: 'N', x: it.x + POD_W / 2, y: it.y - 8, sx: it.x + POD_W / 2, sy: it.y - 34 },
        { side: 'S', x: it.x + POD_W / 2, y: it.y + POD_D + 22, sx: it.x + POD_W / 2, sy: it.y + POD_D + 48 },
    ];
}

export const ITEMS = {
    desk_pod: {
        label: 'Двойной стол', icon: '🖥', w: POD_W, d: POD_D, h: 20, desk: true,
        solid: it => [it.x - 8, it.y - 40, POD_W + 16, POD_D + 90],
        seats: seatsPod,
        draw(it, ctx) {
            const [n, s] = ctx.occ;
            deskHalf(it.x, it.y, POD_W, true, ctx.seed, n, ctx.t);
            divider(it.x - 4, it.y + 22, POD_W + 8);
            deskHalf(it.x, it.y + 28, POD_W, false, ctx.seed + 1, s, ctx.t);
        },
    },
    desk_single: {
        label: 'Одиночный стол', icon: '💻', w: POD_W, d: 22, h: 20, desk: true,
        solid: it => [it.x - 8, it.y - 6, POD_W + 16, 72],
        seats: it => [{ side: 'S', x: it.x + POD_W / 2, y: it.y + 44, sx: it.x + POD_W / 2, sy: it.y + 70 }],
        draw(it, ctx) { deskHalf(it.x, it.y, POD_W, false, ctx.seed, ctx.occ[0], ctx.t); },
    },
    boss_desk: {
        label: 'Стол руководителя', icon: '👔', w: 140, d: 40, h: 22, boss: true,
        solid: it => [it.x - 8, it.y - 14, 156, 106],
        seats: it => [{ side: 'S', boss: true, x: it.x + 70, y: it.y + 64, sx: it.x + 70, sy: it.y + 90 }],
        // обычный рабочий стол чуть побольше остальных: тумба с ящиками, монитор, лампа, книги
        draw(it, ctx) {
            const { x, y } = it, occ = ctx.occ[0], working = !!(occ && occ.working), t = ctx.t;
            softShadow(x - 4, y + 36, 148, 12, 0.42);
            box(x, y, 140, 40, 22, PAL.wood);
            for (let i = 0; i < 4; i++) R(x + 8 + (mix(it.x + i) % 100), y - 16 + i * 8, 22, 0.7, 'rgba(90,50,20,0.35)');
            // ножка слева, тумба с ящиками справа
            R(x + 3, y + 19, 5, 21, '#6b4325'); R(x + 3, y + 19, 1, 21, '#93623b');
            R(x + 8, y + 20, 86, 8, 'rgba(0,0,0,0.18)');
            for (let i = 0; i < 2; i++) {
                RO(x + 98, y + 20 + i * 10, 38, 10, '#9a6639', '#3b2414');
                R(x + 113, y + 24 + i * 10, 8, 2, '#c7ccd4');
            }
            // на столе
            for (let i = 0; i < 3; i++) RO(x + 8, y - 4 - i * 4, 22 - i * 2, 5, ['#3a6ea5', '#b5483a', '#4f8a5b'][i], '#1a1a24');
            papers(x + 34, y - 16);
            mug(x + 38, y + 2, '#f4f1e8', working, t);
            drawMonitor(x + 70, y + 2, 'S', working, 97, t, true);
            keyboard(x + 70, y + 5);
            mouse(x + 89, y + 5);
            R(x + 114, y - 4, 12, 3, '#1f2937'); R(x + 119, y - 16, 2, 12, '#374151');           // лампа
            RO(x + 112, y - 21, 14, 7, '#1f2937', '#05070b'); R(x + 114, y - 15, 10, 1, '#fff1b8');
            succulent(x + 128, y - 2);
        },
    },
    bookshelf: {
        label: 'Книжный шкаф', icon: '📚', w: 78, d: 24, h: 112, wall: true,
        draw(it) {
            const { x, y } = it;
            softShadow(x, y + 22, 84, 12, 0.35);
            box(x, y, 78, 24, 112, { top: '#6a4528', front: '#4a2f1b', edge: '#1d1108', dark: '#3a2413', hi: '#8a5d38', lip: '#5c3a22' });
            const COVERS = ['#b5483a', '#3a6ea5', '#d9a441', '#4f8a5b', '#8a5fb0', '#c9c2b0', '#2f4858', '#d97a3a'];
            for (let row = 0; row < 4; row++) {
                const shelfY = y - 88 + row * 26 + 20;
                R(x + 3, shelfY, 72, 3, '#2a190c');
                R(x + 3, shelfY + 3, 72, 1, '#7d5234');
                let bx = x + 5, k = 0;
                while (bx < x + 70) {
                    const n = mix(it.x * 7 + row * 31 + k);
                    const bw = 3 + n % 4, bh = 12 + (n >> 4) % 7;
                    if ((n >> 9) % 9 === 0) { bx += 4; k++; continue; }                // пустое место на полке
                    const lean = (n >> 12) % 11 === 0;
                    const col = COVERS[(n >> 6) % COVERS.length];
                    R(bx, shelfY - bh + (lean ? 2 : 0), bw, bh - (lean ? 2 : 0), col);
                    R(bx, shelfY - bh + (lean ? 2 : 0), 1, bh - (lean ? 2 : 0), 'rgba(255,255,255,0.22)');
                    R(bx, shelfY - bh + 3 + (lean ? 2 : 0), bw, 1, 'rgba(0,0,0,0.25)');
                    bx += bw + 1; k++;
                }
            }
        },
    },
    cooler: {
        label: 'Кулер', icon: '💧', w: 26, d: 16, h: 40, wall: true,
        draw(it, ctx) {
            const { x, y } = it;
            groundShadow(x + 13, y + 15, 16, 4, 0.4);
            box(x, y, 26, 16, 40, PAL.white);
            RO(x + 5, y - 30, 16, 8, '#2a3446', '#11151d');                                 // ниша с краниками
            R(x + 8, y - 26, 3, 3, '#38bdf8'); R(x + 15, y - 26, 3, 3, '#ef4444');
            RO(x + 4, y - 72, 18, 30, 'rgba(125,205,255,0.55)', 'rgba(60,120,170,0.8)');    // бутыль
            R(x + 6, y - 70, 3, 24, 'rgba(255,255,255,0.45)');
            R(x + 9, y - 76, 8, 4, '#8895a6');
            R(x + 13, y - 48 - ((ctx.t % 80) / 80) * 20, 2, 2, 'rgba(255,255,255,0.75)');   // пузырёк
        },
    },
    server_rack: {
        label: 'Серверная стойка', icon: '🗄', w: 56, d: 22, h: 112, wall: true,
        draw(it, ctx) {
            const { x, y } = it;
            softShadow(x - 4, y + 20, 64, 14, 0.4);
            box(x, y, 56, 22, 112, PAL.metal);
            for (let u = 0; u < 7; u++) {
                const uy = y - 84 + u * 13;
                RO(x + 4, uy, 48, 11, '#141922', '#05070b');
                for (let v = 0; v < 6; v++) R(x + 7 + v * 3, uy + 3, 1.5, 5, '#2c3646');
                for (let k = 0; k < 3; k++) {
                    const on = mix(u * 3 + k + Math.floor(ctx.t / 18) + it.x) % 3 !== 0;
                    R(x + 34 + k * 5, uy + 4, 3, 3, on ? (k === 2 ? '#fbbf24' : '#22c55e') : '#14301d');
                }
            }
        },
    },
    vending: {
        label: 'Автомат с едой', icon: '🥤', w: 46, d: 26, h: 92, wall: true,
        draw(it) {
            const { x, y } = it;
            softShadow(x - 3, y + 24, 54, 12, 0.4);
            box(x, y, 46, 26, 92, { top: '#c0392b', front: '#a93226', edge: '#3d0f0b', dark: '#7b241c', hi: '#e74c3c', lip: '#c0392b' });
            RO(x + 4, y - 62, 28, 52, '#13202f', '#05070b');
            const SN = ['#f59e0b', '#22c55e', '#3b82f6', '#ec4899', '#eab308', '#a855f7'];
            for (let r = 0; r < 5; r++) for (let c = 0; c < 4; c++) R(x + 6 + c * 6.5, y - 59 + r * 10, 4, 6, SN[(r * 4 + c + it.x) % SN.length]);
            R(x + 4, y - 62, 3, 52, 'rgba(255,255,255,0.12)');
            RO(x + 35, y - 58, 8, 14, '#2a2f3a', '#05070b'); R(x + 37, y - 55, 4, 2, '#22c55e');
            RO(x + 6, y - 6, 24, 6, '#0b0e14', '#05070b');
        },
    },
    sofa: {
        label: 'Диван', icon: '🛋', w: 180, d: 48, h: 26,
        draw(it) {
            const { x, y } = it;
            const RED = { top: '#9d2a2a', front: '#7c1d1d', edge: '#3a0b0b', dark: '#5f1515', hi: '#c24444', lip: '#8a2222' };
            softShadow(x, y + 44, 182, 14, 0.4);
            box(x + 6, y, 168, 12, 38, RED);                                   // спинка
            box(x + 6, y + 12, 168, 36, 16, RED);                              // сиденье
            box(x, y, 14, 48, 26, RED); box(x + 166, y, 14, 48, 26, RED);      // подлокотники
            for (let c = 0; c < 3; c++) {
                RO(x + 19 + c * 50, y - 22, 46, 20, '#b83a3a', '#5f1515'); R(x + 20 + c * 50, y - 21, 44, 2, '#d86a6a');
                RO(x + 19 + c * 50, y, 46, 26, '#c24444', '#5f1515'); R(x + 20 + c * 50, y + 1, 44, 2, '#dc7070');
            }
            RO(x + 26, y - 4, 16, 14, '#e8b04a', '#7a5a1c'); R(x + 27, y - 3, 14, 2, '#f5cf7e');
        },
    },
    armchair: {
        label: 'Кресло', icon: '💺', w: 46, d: 40, h: 22,
        draw(it) {
            const { x, y } = it;
            const C = { top: '#2f6d6a', front: '#21504e', edge: '#0c2423', dark: '#183b39', hi: '#4a9a95', lip: '#2a605d' };
            softShadow(x, y + 36, 48, 10, 0.4);
            box(x + 4, y, 38, 10, 34, C); box(x + 4, y + 10, 38, 30, 14, C);
            box(x, y, 8, 40, 22, C); box(x + 38, y, 8, 40, 22, C);
        },
    },
    coffee_table: {
        label: 'Журнальный столик', icon: '☕', w: 64, d: 30, h: 14,
        draw(it, ctx) {
            const { x, y } = it;
            softShadow(x - 2, y + 26, 68, 10, 0.35);
            box(x, y, 64, 30, 14, { top: '#a8713f', front: '#6c4527', edge: '#2a1a0c', dark: '#563820', hi: '#c99060', lip: '#8a5a32' });
            RO(x + 8, y - 10, 20, 12, '#3a6ea5', '#1a3352'); R(x + 9, y - 9, 18, 2, '#6fa0d6');
            mug(x + 38, y - 10, '#f4f1e8', true, ctx.t);
        },
    },
    floor_lamp: {
        label: 'Торшер', icon: '💡', w: 26, d: 14, h: 16,
        draw(it) {
            const { x, y } = it;
            groundShadow(x + 13, y + 13, 20, 4, 0.45);
            box(x, y, 26, 14, 16, PAL.darkwood);
            R(x + 12, y - 70, 3, 56, '#6b6b7a');
            RO(x, y - 90, 26, 22, '#f3d58a', '#9a7a32'); R(x + 2, y - 88, 22, 14, '#fff0b8');
        },
    },
    plant: {
        label: 'Растение', icon: '🪴', w: 24, d: 16, h: 16,
        draw(it) { plantArt(it.x, it.y, 1); },
    },
    plant_big: {
        label: 'Большое растение', icon: '🌿', w: 32, d: 20, h: 20,
        draw(it) { plantArt(it.x, it.y, 1.3); },
    },
    whiteboard: {
        label: 'Доска для идей', icon: '📋', w: 96, d: 10, h: 74,
        draw(it, ctx) {
            const { x, y } = it;
            softShadow(x, y + 8, 96, 8, 0.3);
            R(x + 6, y - 20, 3, 28, '#4b5563'); R(x + 87, y - 20, 3, 28, '#4b5563');                 // ножки
            R(x + 2, y + 6, 12, 2, '#374151'); R(x + 82, y + 6, 12, 2, '#374151');
            RO(x, y - 74, 96, 56, '#f8fafc', '#64748b');
            R(x + 2, y - 72, 92, 2, '#ffffff');
            // каракули с планом спринта
            const s = it.x + it.y;
            R(x + 8, y - 66, 26, 2, '#2563eb'); R(x + 8, y - 61, 18, 1.5, '#64748b'); R(x + 8, y - 57, 22, 1.5, '#64748b');
            for (let i = 0; i < 3; i++) {
                RO(x + 46 + i * 15, y - 66, 12, 10, ['#fde68a', '#bbf7d0', '#fbcfe8'][(i + s) % 3], 'rgba(0,0,0,0.2)');
            }
            R(x + 10, y - 44, 70, 1.5, '#ef4444'); R(x + 78, y - 46, 2, 5, '#ef4444');
            R(x + 14, y - 38, 30, 1.5, '#16a34a');
            RO(x + 30, y - 20, 36, 3, '#cbd5e1', '#64748b');                                          // полочка
            R(x + 34, y - 21, 6, 2, '#2563eb'); R(x + 42, y - 21, 6, 2, '#dc2626');
            void ctx;
        },
    },
    meeting_table: {
        label: 'Переговорный стол', icon: '🤝', w: 150, d: 60, h: 20,
        solid: it => [it.x - 18, it.y - 26, 186, 112],
        draw(it) {
            const { x, y } = it;
            for (let i = 0; i < 3; i++) drawChair(x + 30 + i * 45, y - 2, 'N');
            softShadow(x - 3, y + 56, 156, 12, 0.4);
            box(x, y, 150, 60, 20, { top: '#e7e1d6', front: '#9c8f7a', edge: '#3c3328', dark: '#7d715f', hi: '#ffffff', lip: '#bdb3a2' });
            R(x + 60, y - 6, 30, 3, '#1f2937');                                                        // спикерфон
            for (let i = 0; i < 4; i++) papers(x + 12 + i * 34, y - 16 + (i % 2) * 18);
            for (let i = 0; i < 3; i++) drawChair(x + 30 + i * 45, y + 84, 'S');
        },
    },
    printer: {
        label: 'Принтер', icon: '🖨', w: 46, d: 28, h: 34,
        draw(it, ctx) {
            const { x, y } = it;
            softShadow(x - 2, y + 26, 52, 10, 0.4);
            box(x, y, 46, 28, 18, PAL.darkwood);
            box(x + 4, y - 16, 38, 22, 16, PAL.white);
            RO(x + 10, y - 34, 26, 4, '#9ca3af', '#4b5563');
            R(x + 12, y - 38 + (Math.floor(ctx.t / 30) % 4), 22, 4, '#ffffff');
            R(x + 34, y - 26, 3, 2, Math.floor(ctx.t / 20) % 2 ? '#22c55e' : '#14532d');
        },
    },
    coffee_machine: {
        label: 'Кофемашина', icon: '☕', w: 52, d: 26, h: 30,
        draw(it, ctx) {
            const { x, y } = it;
            softShadow(x - 2, y + 24, 58, 10, 0.4);
            box(x, y, 52, 26, 30, PAL.wood);
            RO(x + 12, y - 58, 28, 30, '#1f2937', '#05070b');
            RO(x + 15, y - 54, 22, 8, '#374151', '#05070b'); R(x + 17, y - 52, 6, 3, '#22d3ee');
            R(x + 22, y - 44, 8, 4, '#4b5563');
            mug(x + 22, y - 38, '#f4f1e8', Math.floor(ctx.t / 200) % 2 === 0, ctx.t);
            RO(x + 2, y - 26, 8, 10, '#fef3c7', '#78350f');
        },
    },
};

function plantArt(x, y, s) {
    groundShadow(x + 12 * s, y + 16 * s, 16 * s, 4.4 * s, 0.5);
    RO(x, y, 24 * s, 16 * s, '#dfe5ee', '#5b6676');
    R(x + 17 * s, y + 1, 6 * s, 16 * s - 2, '#b4bdcb');
    R(x + 1, y + 1, 2 * s, 16 * s - 2, '#f6f8fb');
    RO(x - 1, y - 2, 26 * s, 5, '#f8fafc', '#5b6676');
    R(x + 1, y - 1, 24 * s - 2, 2, '#3a2a1c');
    const leaf = ['#14532d', '#166534', '#15803d', '#22a04d', '#4ade80'];
    for (let i = 0; i < 11; i++) {
        const lx = x + 12 * s + (i - 5) * 4.4 * s;
        const len = (16 - Math.abs(i - 5) * 2.4) * s;
        const ly = y - 2 - len - (i % 2) * 3 * s;
        R(lx - 2.5 * s, ly, 5 * s, len + 2, leaf[i % 5]);
        R(lx - 2.5 * s, ly, 1.2 * s, len, 'rgba(255,255,255,0.12)');
    }
}

export const ITEM_TYPES = Object.keys(ITEMS);

/* ------------------------------------------------------------------
   Зоны: покрытие пола, стеклянные стены, табличка
------------------------------------------------------------------- */

export const ZONE_STYLES = {
    rug_red: 'Красный ковёр',
    rug_teal: 'Бирюзовый ковёр',
    carpet: 'Серое ковролиновое покрытие',
    tile: 'Плитка',
    wood_light: 'Светлый паркет',
    none: 'Без покрытия',
};

export const DOOR_SIDES = { east: 'справа', west: 'слева', south: 'снизу', north: 'сверху' };

// чем занимаются в зоне: от этого зависит, куда свободные агенты ходят и что говорят, придя туда
export const ZONE_ACTIVITIES = {
    work: { label: 'Работа', bubble: '💻 Думаю над задачей', weight: 1 },
    rest: { label: 'Отдых', bubble: '🛋 Небольшой перерыв', weight: 3 },
    kitchen: { label: 'Кофе-брейк', bubble: '☕ За кофе', weight: 3 },
    meeting: { label: 'Обсуждения', bubble: '🗣 Обсуждаю идеи', weight: 2 },
    private: { label: 'Личное пространство', bubble: '', weight: 1 },
    none: { label: 'Без назначения', bubble: '', weight: 1 },
};

export const ROLE_NAMES = { planner: 'Руководитель', coder: 'Разработчики', qa: 'Тестировщики' };

// кому можно в зону: пустой список ролей - всем
export function zoneAllows(zone, role) {
    return !zone || !Array.isArray(zone.roles) || !zone.roles.length || zone.roles.includes(role);
}

export function zoneAccessText(zone) {
    if (!zone.roles || !zone.roles.length) return 'всем';
    return zone.roles.map(r => ROLE_NAMES[r] || r).join(', ');
}
export const WALL_T = 10;          // толщина стеклянной стены
export const DOOR_W = 80;

export function paintZoneFloor(z) {
    const { x, y, w, h } = z;
    if (z.style === 'rug_red' || z.style === 'rug_teal') {
        const red = z.style === 'rug_red';
        const m = 16, top = Math.min(56, h * 0.25);
        const rx = x + m, ry = y + top, rw = w - 2 * m, rh = h - top - m;
        if (rw < 30 || rh < 20) return;
        const C = red ? ['#7a1c1c', '#a52a2a', '#8f2323', '#d8a24a', '#e8c27a'] : ['#24434b', '#2f5c66', '#285059', '#7dd3c8', '#a7e8df'];
        R(rx - 3, ry - 2, rw + 6, rh + 6, 'rgba(0,0,0,0.25)');
        R(rx, ry, rw, rh, C[0]); R(rx + 5, ry + 5, rw - 10, rh - 10, C[1]);
        R(rx + 11, ry + 11, rw - 22, rh - 22, C[0]); R(rx + 16, ry + 16, rw - 32, rh - 32, C[2]);
        const n = Math.max(1, Math.floor((rw - 60) / 42));
        for (let i = 0; i < n; i++) {
            const cx = rx + rw / 2 + (i - (n - 1) / 2) * 42, cy = ry + rh / 2;
            R(cx - 2, cy - 11, 4, 22, C[3]); R(cx - 11, cy - 2, 22, 4, C[3]); R(cx - 5, cy - 5, 10, 10, C[0]);
        }
        for (let i = 8; i < rw - 8; i += 12) { R(rx + i, ry + 8, 4, 2, C[4]); R(rx + i, ry + rh - 10, 4, 2, C[4]); }
        for (let i = 0; i < rw; i += 8) { R(rx + i + 2, ry - 3, 2, 3, C[4]); R(rx + i + 2, ry + rh, 2, 3, C[4]); }
    } else if (z.style === 'carpet') {
        R(x, y, w, h, '#3b4456');
        for (let i = 0; i < 80; i++) { const n = mix(i * 13 + x); R(x + n % w, y + (n >> 8) % h, 2, 1, 'rgba(255,255,255,0.05)'); }
    } else if (z.style === 'tile') {
        for (let ty = 0; ty < h; ty += 16) for (let tx = 0; tx < w; tx += 16) {
            R(x + tx, y + ty, Math.min(16, w - tx), Math.min(16, h - ty), ((tx + ty) / 16) % 2 ? '#c9d2dc' : '#dde3ea');
        }
        for (let ty = 0; ty < h; ty += 16) R(x, y + ty, w, 1, 'rgba(0,0,0,0.12)');
        for (let tx = 0; tx < w; tx += 16) R(x + tx, y, 1, h, 'rgba(0,0,0,0.12)');
    } else if (z.style === 'wood_light') {
        for (let r = 0; r * 12 < h; r++) {
            let px = -((r * 37) % 70), i = 0;
            while (px < w) {
                const pw = Math.min(70, w - Math.max(0, px));
                R(x + Math.max(0, px), y + r * 12, pw, Math.min(12, h - r * 12), ['#c9a173', '#bf9666', '#d2ab7d'][mix(r * 5 + i) % 3]);
                R(x + Math.max(0, px), y + r * 12, 1, Math.min(12, h - r * 12), 'rgba(0,0,0,0.15)');
                px += 70; i++;
            }
            R(x, y + r * 12 + 11, w, 1, 'rgba(0,0,0,0.12)');
        }
    }
}

// стены зоны как набор прямоугольников на полу; door - сторона с проёмом
export function zoneWalls(z) {
    if (!z.walls) return [];
    const out = [];
    const sides = {
        north: z.y > WALL_Y + 6 ? [z.x, z.y - WALL_T / 2, z.w, WALL_T, 'h'] : null,
        south: z.y + z.h < H - 6 ? [z.x, z.y + z.h - WALL_T / 2, z.w, WALL_T, 'h'] : null,
        west: z.x > 6 ? [z.x - WALL_T / 2, z.y, WALL_T, z.h, 'v'] : null,
        east: z.x + z.w < W - 6 ? [z.x + z.w - WALL_T / 2, z.y, WALL_T, z.h, 'v'] : null,
    };
    Object.entries(sides).forEach(([side, r]) => {
        if (!r) return;
        const [x, y, w, h, dir] = r;
        if (side !== z.door) { out.push({ x, y, w, h, dir, side }); return; }
        const len = dir === 'h' ? w : h;
        const a = Math.max(0, (len - DOOR_W) / 2);
        if (dir === 'h') {
            out.push({ x, y, w: a, h, dir, side, doorEnd: 'right' });
            out.push({ x: x + a + DOOR_W, y, w: w - a - DOOR_W, h, dir, side, doorEnd: 'left' });
        } else {
            out.push({ x, y, w, h: a, dir, side, doorEnd: 'bottom' });
            out.push({ x, y: y + a + DOOR_W, w, h: h - a - DOOR_W, dir, side, doorEnd: 'top' });
        }
    });
    return out.filter(s => s.w > 2 && s.h > 2);
}

const FRAME = '#8ea3ba', CAP = '#cbd8e6', GLASS = 'rgba(160,215,245,0.30)', WALL_H = 36;

// горизонтальная стеклянная стена (видна передняя грань)
export function drawWallH(s) {
    const top = s.y + s.h - WALL_H;
    softShadow(s.x, s.y + s.h, s.w, 10, 0.4);
    R(s.x, top - s.h + 2, s.w, s.h - 2, CAP); R(s.x, top - s.h + 2, s.w, 1, '#f1f6fb');
    R(s.x, top, s.w, 20, GLASS);
    for (let px = s.x; px < s.x + s.w; px += 46) R(px, top, 2, 20, FRAME);
    for (let px = s.x + 9; px < s.x + s.w - 6; px += 46) R(px, top + 3, 4, 14, 'rgba(255,255,255,0.18)');
    R(s.x, top, s.w, 2, FRAME);
    R(s.x, top + 20, s.w, 2, '#5d6e88');
    R(s.x, top + 22, s.w, WALL_H - 22, '#3b465c'); R(s.x, top + 22, s.w, 1, '#6b7d99');
    if (s.doorEnd === 'left') R(s.x, top - s.h + 2, 3, WALL_H + s.h - 2, '#5d6e88');
    if (s.doorEnd === 'right') R(s.x + s.w - 3, top - s.h + 2, 3, WALL_H + s.h - 2, '#2e3748');
}

// кусок вертикальной стены (видна только верхняя кромка), рисуется полосами для сортировки по глубине
export function drawWallV(s, y0, y1) {
    const ly = y0 - WALL_H, len = y1 - y0;
    R(s.x + s.w, y0, 7, len, 'rgba(0,0,0,0.18)');
    R(s.x, ly, s.w, len, GLASS);
    R(s.x, ly, 2, len, FRAME); R(s.x + s.w - 2, ly, 2, len, FRAME);
    R(s.x + 3, ly, 2, len, 'rgba(255,255,255,0.22)');
    for (let yy = Math.ceil(y0 / 28) * 28; yy < y1; yy += 28) R(s.x, yy - WALL_H, s.w, 3, FRAME);
    if (s.doorEnd === 'bottom' && y1 >= s.y + s.h - 0.5) {
        R(s.x, s.y + s.h - WALL_H, s.w, WALL_H, '#44506a'); R(s.x, s.y + s.h - WALL_H, s.w, 3, FRAME);
    }
    if (s.doorEnd === 'top' && y0 <= s.y + 0.5) R(s.x, s.y - WALL_H, s.w, 3, CAP);
}

export function drawZoneLabel(z) {
    if (!z.label) return;
    const walls = zoneWalls(z).filter(s => s.side === 'south');
    const str = z.label.toUpperCase().slice(0, 24);
    const w = Math.max(40, str.length * 5 + 14);
    if (walls.length) {
        const s = walls.reduce((a, b) => (b.w > a.w ? b : a));
        const px = s.x + Math.min(30, s.w / 4), py = s.y + s.h - WALL_H + 24;
        RO(px, py, w, 9, '#d6a84b', '#7a5a1c');
        text(str, px + w / 2, py + 4.8, 6.2, '#3b2a08');
    } else {
        R(z.x + 6, z.y + 6, w, 11, 'rgba(10,14,28,0.55)');
        text(str, z.x + 6 + w / 2, z.y + 11.8, 6.4, 'rgba(226,232,240,0.85)');
    }
}

/* ------------------------------------------------------------------
   Геометрия для размещения и стандартная планировка
------------------------------------------------------------------- */

export function footprint(it) {
    const d = ITEMS[it.type];
    return [it.x, it.y, d.w, d.d];
}

// прямоугольник, который предмет занимает вместе с креслами и проходом: два таких не пересекаются
export function solidRect(it) {
    const d = ITEMS[it.type];
    return d.solid ? d.solid(it) : [it.x - 3, it.y - 2, d.w + 6, d.d + 6];
}

export function rectsOverlap(a, b) {
    return a[0] < b[0] + b[2] && b[0] < a[0] + a[2] && a[1] < b[1] + b[3] && b[1] < a[1] + a[3];
}

export const FLOOR = { x0: 6, y0: WALL_Y, x1: W - 6, y1: H - 4 };

// новый офис пустой: зоны, столы и мебель пользователь расставляет сам в редакторе планировки
export const EMPTY_LAYOUT = { version: 1, zones: [], items: [] };
