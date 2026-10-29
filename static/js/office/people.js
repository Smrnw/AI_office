// Сотрудники офиса: внешность из настроек (или по имени и роли), пиксельный спрайт «чиби»
// с крупной головой, портрет для карточек и фигура в полный рост для окна настроек.
//
// Вся отрисовка идёт через функцию P(dx, dy, w, h, цвет) относительно точки между ступнями,
// поэтому один и тот же код рисует и на canvas, и в SVG.
import { R, X, Y, V, hash, shade, isHex } from './core.js';
import { drawChair } from './catalog.js';

export const SKIN = ['#f8d9bf', '#efc29b', '#dda577', '#c08155', '#9a6440', '#6e452b'];
const HAIR = ['#2b1d14', '#4a3020', '#7b4a24', '#b98a4a', '#1f2937', '#9a3a22', '#e8c46a', '#59606b'];
const PANTS = ['#1f2a44', '#2d3340', '#3b3326', '#24324d', '#3a2f4d'];
const ACCENT = ['#ef4444', '#22c55e', '#f59e0b', '#06b6d4', '#a855f7', '#ec4899'];
const OUT = '#0c0f1a';

export const HAIR_STYLES = {
    auto: 'Авто', short: 'Короткая', side: 'На пробор', spiky: 'Ёжик', long: 'Длинные',
    bun: 'Пучок', ponytail: 'Хвост', curly: 'Кудри', bald: 'Лысина',
};
export const OUTFITS = { auto: 'Авто (по роли)', suit: 'Костюм с галстуком', hoodie: 'Худи', shirt: 'Рубашка', tshirt: 'Футболка', sweater: 'Свитер' };
export const ACCESSORIES = { auto: 'Авто (по роли)', none: 'Нет', glasses: 'Очки', headphones: 'Наушники', both: 'Очки и наушники' };

const AUTO_HAIR = ['short', 'side', 'spiky', 'long', 'bun', 'ponytail', 'curly'];
const ROLE_OUTFIT = { planner: 'suit', coder: 'hoodie', qa: 'shirt' };
const ROLE_ACCESSORY = { planner: 'none', coder: 'headphones', qa: 'glasses' };
const cache = {};

export function palFor(a) {
    const key = [a.id, a.shirt, a.hair, a.pants, a.skin, a.hair_style, a.outfit, a.accessory, a.pipeline_type].join('|');
    if (cache[key]) return cache[key];
    const h = hash(String(a.id));
    const role = a.pipeline_type || 'coder';
    const skinIdx = Number.isInteger(a.skin) && a.skin >= 0 && a.skin < SKIN.length ? a.skin : h % SKIN.length;
    const skin = SKIN[skinIdx];
    const accessory = ACCESSORIES[a.accessory] && a.accessory !== 'auto' ? a.accessory : ROLE_ACCESSORY[role] || 'none';
    cache[key] = {
        skin, skinShade: shade(skin, -0.17),
        hair: isHex(a.hair) && a.hair.toLowerCase() !== '#f1f5f9' ? a.hair : HAIR[(h >> 3) % HAIR.length],
        style: HAIR_STYLES[a.hair_style] && a.hair_style !== 'auto' ? a.hair_style : AUTO_HAIR[(h >> 6) % AUTO_HAIR.length],
        outfit: OUTFITS[a.outfit] && a.outfit !== 'auto' ? a.outfit : ROLE_OUTFIT[role] || 'tshirt',
        shirt: isHex(a.shirt) ? a.shirt : '#3b82f6',
        pants: isHex(a.pants) ? a.pants : PANTS[(h >> 9) % PANTS.length],
        accent: ACCENT[(h >> 12) % ACCENT.length],
        glasses: accessory === 'glasses' || accessory === 'both',
        headphones: accessory === 'headphones' || accessory === 'both',
        role,
    };
    return cache[key];
}

function frame(P, x, y, w, h, c) {
    P(x, y, w, 1, c); P(x, y + h - 1, w, 1, c); P(x, y, 1, h, c); P(x + w - 1, y, 1, h, c);
}

/* ---------- голова ---------- */

function hairFront(P, pal, hy) {
    const H = pal.hair, HL = shade(H, 0.3), HD = shade(H, -0.28);
    const st = pal.style;
    if (st === 'bald') {
        P(-11, hy + 7, 2, 5, H); P(9, hy + 7, 2, 5, H);
        P(-5, hy + 1, 5, 2, 'rgba(255,255,255,0.35)');
        return;
    }
    if (st === 'curly') {
        P(-14, hy - 8, 28, 13, OUT); P(-13, hy - 7, 26, 12, H); P(-15, hy - 3, 30, 8, H);
        P(-14, hy + 4, 4, 9, H); P(10, hy + 4, 4, 9, H);
        for (let i = 0; i < 7; i++) P(-11 + i * 4, hy - 5 + (i % 2) * 3, 2, 2, HL);
        for (let i = 0; i < 6; i++) P(-9 + i * 4, hy + 1 + (i % 2), 2, 2, HD);
        return;
    }
    if (st === 'long') { P(-14, hy + 1, 5, 26, OUT); P(9, hy + 1, 5, 26, OUT); P(-13, hy + 2, 4, 24, H); P(9, hy + 2, 4, 24, H); P(-12, hy + 4, 1, 18, HL); }
    if (st === 'ponytail') { P(10, hy + 2, 5, 17, OUT); P(11, hy + 3, 3, 15, H); P(11, hy + 15, 3, 3, HD); P(10, hy + 5, 4, 1, pal.accent); }
    if (st === 'bun') { P(-5, hy - 10, 10, 8, OUT); P(-4, hy - 9, 8, 7, H); P(-3, hy - 8, 3, 1, HL); }
    // шапка волос
    P(-12, hy - 4, 24, 9, OUT);
    P(-11, hy - 3, 22, 8, H);
    P(-11, hy + 4, 3, 7, H); P(8, hy + 4, 3, 7, H);
    P(-7, hy - 2, 9, 1, HL);
    if (st === 'short') { P(-9, hy + 4, 8, 2, H); P(1, hy + 4, 6, 1, H); }
    if (st === 'side') { P(-9, hy + 4, 14, 3, H); P(-9, hy + 7, 5, 2, H); P(4, hy + 4, 1, 1, HD); }
    if (st === 'spiky') {
        P(-10, hy - 7, 4, 5, H); P(-4, hy - 9, 4, 7, H); P(2, hy - 7, 4, 5, H); P(7, hy - 5, 3, 3, H);
        P(-8, hy + 4, 3, 3, H); P(-2, hy + 4, 3, 2, H); P(4, hy + 4, 3, 3, H);
    }
    if (st === 'long' || st === 'bun' || st === 'ponytail') { P(-9, hy + 4, 18, 2, H); P(-3, hy + 4, 2, 3, HD); }
}

function hairBack(P, pal, hy) {
    const H = pal.hair, HL = shade(H, 0.3), HD = shade(H, -0.28);
    const st = pal.style;
    if (st === 'bald') { P(-10, hy, 20, 20, pal.skin); P(-10, hy + 7, 2, 6, H); P(8, hy + 7, 2, 6, H); P(-4, hy + 2, 5, 2, 'rgba(255,255,255,0.3)'); return; }
    if (st === 'curly') { P(-14, hy - 7, 28, 24, OUT); P(-13, hy - 6, 26, 22, H); for (let i = 0; i < 8; i++) P(-11 + (i % 4) * 6, hy - 3 + Math.floor(i / 4) * 8, 2, 2, HL); return; }
    P(-11, hy - 3, 22, 21, H);
    P(-10, hy + 10, 20, 8, HD);
    P(-7, hy - 2, 9, 1, HL);
    if (st === 'long') { P(-12, hy + 8, 24, 18, H); P(-11, hy + 22, 22, 4, HD); }
    else if (st === 'ponytail') { P(-2, hy + 14, 5, 14, H); P(-2, hy + 14, 5, 1, pal.accent); }
    else P(-4, hy + 15, 8, 4, pal.skinShade);                        // затылок и шея
    if (st === 'bun') { P(-4, hy - 9, 8, 7, H); P(-3, hy - 8, 3, 1, HL); }
    if (st === 'spiky') { P(-10, hy - 7, 4, 5, H); P(-4, hy - 9, 4, 7, H); P(2, hy - 7, 4, 5, H); }
}

function drawHead(P, pal, hy, back, look, blink, working) {
    P(-2, hy + 19, 4, 3, pal.skinShade);                              // шея
    if (back) {
        P(-12, hy + 8, 2, 5, pal.skin); P(10, hy + 8, 2, 5, pal.skin);
        P(-11, hy - 1, 22, 22, OUT);
        P(-10, hy, 20, 20, pal.skin);
        hairBack(P, pal, hy);
    } else {
        P(-13, hy + 8, 3, 6, OUT); P(10, hy + 8, 3, 6, OUT);
        P(-12, hy + 9, 2, 4, pal.skin); P(10, hy + 9, 2, 4, pal.skinShade);
        P(-11, hy - 1, 22, 22, OUT);
        P(-10, hy, 20, 20, pal.skin);
        P(6, hy + 3, 4, 16, pal.skinShade);
        P(-7, hy + 18, 14, 2, pal.skinShade);
        const ex = look;
        const brow = shade(pal.hair, -0.2);
        P(-7 + ex, hy + 7, 4, 1, brow); P(3 + ex, hy + 7, 4, 1, brow);
        if (blink) {
            P(-6 + ex, hy + 12, 3, 1, '#1b1f2e'); P(3 + ex, hy + 12, 3, 1, '#1b1f2e');
        } else {
            P(-6 + ex, hy + 9, 3, 4, '#1b1f2e'); P(3 + ex, hy + 9, 3, 4, '#1b1f2e');
            P(-6 + ex, hy + 9, 1, 1, '#ffffff'); P(3 + ex, hy + 9, 1, 1, '#ffffff');
        }
        P(0 + Math.round(ex / 2), hy + 13, 1, 2, pal.skinShade);
        if (working) P(-1 + ex, hy + 16, 3, 1, '#8a3a22');
        else { P(-2 + ex, hy + 16, 4, 1, '#8a3a22'); P(-3 + ex, hy + 15, 1, 1, '#8a3a22'); P(2 + ex, hy + 15, 1, 1, '#8a3a22'); }
        P(-9, hy + 14, 2, 1, 'rgba(255,110,110,0.4)'); P(7, hy + 14, 2, 1, 'rgba(255,110,110,0.4)');
        hairFront(P, pal, hy);
        if (pal.glasses) {
            frame(P, -8 + ex, hy + 8, 6, 6, '#1f2937'); frame(P, 2 + ex, hy + 8, 6, 6, '#1f2937');
            P(-2 + ex, hy + 10, 4, 1, '#1f2937');
            P(-7 + ex, hy + 9, 1, 1, 'rgba(255,255,255,0.7)'); P(3 + ex, hy + 9, 1, 1, 'rgba(255,255,255,0.7)');
        }
    }
    if (pal.headphones && working) {
        P(-12, hy - 6, 24, 2, '#111827'); P(-13, hy - 5, 2, 11, '#111827'); P(11, hy - 5, 2, 11, '#111827');
        P(-15, hy + 6, 5, 9, OUT); P(-14, hy + 7, 3, 7, pal.accent);
        P(10, hy + 6, 5, 9, OUT); P(11, hy + 7, 3, 7, pal.accent);
    }
}

/* ---------- одежда ---------- */

function drawTorso(P, pal, ty, back) {
    const s = pal.shirt, D = shade(s, -0.3), L = shade(s, 0.22);
    P(-10, ty - 1, 20, 15, OUT);
    P(-9, ty, 18, 13, s);
    P(5, ty, 4, 13, D);
    P(-9, ty, 1, 13, L); P(-9, ty, 18, 1, L);
    const o = pal.outfit;
    if (back) {
        if (o === 'suit') P(0, ty + 1, 1, 11, D);
        if (o === 'hoodie') { P(-6, ty, 12, 5, D); P(-5, ty + 1, 10, 3, shade(s, -0.15)); }
        if (o === 'sweater') P(-9, ty + 11, 18, 2, D);
    } else if (o === 'suit') {
        P(-3, ty, 6, 5, '#f1f5f9'); P(-2, ty + 5, 4, 2, '#f1f5f9');
        P(-1, ty + 1, 2, 8, '#7f1d1d'); P(-1.5, ty + 1, 3, 2, '#5b1414');
        P(-4, ty, 1, 7, D); P(3, ty, 1, 7, D);
        P(-5, ty + 9, 1, 1, '#e5e7eb');
    } else if (o === 'hoodie') {
        P(-7, ty - 1, 14, 3, D);
        P(-3, ty + 2, 1, 5, '#e5e7eb'); P(2, ty + 2, 1, 5, '#e5e7eb');
        P(-6, ty + 8, 12, 4, D); P(-5, ty + 9, 10, 2, shade(s, -0.12));
    } else if (o === 'shirt') {
        P(-5, ty, 4, 2, L); P(1, ty, 4, 2, L);
        P(0, ty + 2, 1, 10, D);
        P(-7, ty + 3, 4, 3, D);
    } else if (o === 'tshirt') {
        P(-3, ty, 6, 2, pal.skinShade);
        P(-3, ty + 5, 6, 4, L); P(-1, ty + 6, 2, 2, D);
    } else if (o === 'sweater') {
        P(-4, ty, 8, 2, '#f8fafc');
        for (let i = 0; i < 3; i++) P(-5 + i * 4, ty + 5, 2, 2, L);
        P(-9, ty + 11, 18, 2, D);
    }
    if (!back && (o === 'suit' || o === 'shirt')) { P(-9, ty + 12, 18, 1, '#1f2937'); P(-1, ty + 12, 2, 1, '#d6a84b'); }
}

function sleeve(pal) {
    return pal.outfit === 'tshirt' ? pal.skin : shade(pal.shirt, -0.12);
}

function drawArmsStand(P, pal, ty, sw) {
    const sl = sleeve(pal), top = shade(pal.shirt, -0.12);
    [[-13, sw], [9, -sw]].forEach(([x, o]) => {
        P(x, ty + o, 5, 13, OUT);
        P(x + 1, ty + 1 + o, 3, 10, sl);
        P(x + 1, ty + 1 + o, 3, 3, top);                               // рукав (у футболки короткий)
        P(x + 1, ty + 10 + o, 3, 2, pal.skin);
        if (pal.outfit === 'suit') P(x + 1, ty + 9 + o, 3, 1, '#f1f5f9');
    });
}

function drawLegs(P, pal, step) {
    const l1 = [0, -2, 0, 0][step], l2 = [0, 0, 0, -2][step];
    P(-7, -12, 14, 10, OUT);
    P(-6, -11, 5, 8 + l1, pal.pants); P(1, -11, 5, 8 + l2, pal.pants);
    P(-1, -11, 2, 3, pal.pants);
    P(4, -11, 2, 8 + l2, shade(pal.pants, -0.25));
    P(-7, -4 + l1, 7, 4, OUT); P(-6, -3 + l1, 5, 2, '#1a1410'); P(-6, -3 + l1, 3, 1, '#4b3b2e');
    P(0, -4 + l2, 7, 4, OUT); P(1, -3 + l2, 5, 2, '#1a1410'); P(1, -3 + l2, 3, 1, '#4b3b2e');
}

/* ---------- целиком ---------- */

const TY = -24;          // верх туловища относительно ступней
const HY = TY - 22;      // верх головы

// pose: stand | sitN (лицом к нам за столом) | sitS (спиной к нам)
export function paintPerson(P, pal, o) {
    const step = o.moving ? o.step : 0;
    const bob = o.moving ? (step % 2 ? -1 : 0) : (o.breath ? -1 : 0);
    const back = o.pose === 'sitS' || (o.moving && o.face === 'back');
    const ty = TY + (o.pose === 'sitS' ? 0 : bob);
    if (o.pose === 'stand') drawLegs(P, pal, step);
    if (o.pose === 'sitS') {                                          // руки тянутся к клавиатуре
        const k = o.typing ? 1 : 0, sl = sleeve(pal);
        P(-14, ty - 9 + k, 5, 14, OUT); P(-13, ty - 8 + k, 3, 12, sl); P(-13, ty - 11 + k, 3, 3, pal.skin);
        P(9, ty - 9 + (1 - k), 5, 14, OUT); P(10, ty - 8 + (1 - k), 3, 12, sl); P(10, ty - 11 + (1 - k), 3, 3, pal.skin);
    }
    drawTorso(P, pal, ty, back);
    if (o.pose === 'sitN') {
        const sl = sleeve(pal);
        P(-14, ty + 1, 5, 10, OUT); P(-13, ty + 2, 3, 8, sl);
        P(9, ty + 1, 5, 10, OUT); P(10, ty + 2, 3, 8, sl);
    } else if (o.pose === 'stand') {
        drawArmsStand(P, pal, ty, o.moving ? (step < 2 ? -2 : 2) : 0);
    }
    if (pal.headphones && !o.working && !back) {                     // наушники на шее
        P(-7, ty - 2, 14, 2, '#111827'); P(-9, ty - 1, 4, 4, pal.accent); P(5, ty - 1, 4, 4, pal.accent);
    }
    drawHead(P, pal, ty - 22, back, o.look || 0, o.blink, o.working);
}

export function drawPerson(a, t, hovered) {
    const px = Math.round(a.x), py = Math.round(a.y), pal = a.pal;
    const P = (dx, dy, w, h, c) => R(px + dx, py + dy, w, h, c);
    const G = V.G;
    G.fillStyle = 'rgba(0,0,0,0.32)';
    G.beginPath(); G.ellipse(X(px), Y(py + 1), 13 * V.SC, 4 * V.SC, 0, 0, Math.PI * 2); G.fill();
    if (hovered) {
        G.strokeStyle = 'rgba(94,200,255,0.95)';
        G.lineWidth = Math.max(1.5, 1.3 * V.SC);
        G.beginPath(); G.ellipse(X(px), Y(py + 1), 17 * V.SC, 6 * V.SC, 0, 0, Math.PI * 2); G.stroke();
    }
    if (a.pose === 'sitN') drawChair(px, py - 6, 'N', a.isBoss);
    paintPerson(P, pal, {
        pose: a.pose, moving: a.moving, face: a.face, step: Math.floor(t / 6) % 4,
        breath: Math.sin(t / 30 + a.phase) > 0.75, typing: a.working && Math.floor(t / 5) % 2,
        working: a.working, look: a.moving ? a.dir : 0, blink: (t + a.phase * 50) % 220 < 6,
    });
    if (a.pose === 'sitS') drawChair(px, py, 'S', a.isBoss);
}

/* ---------- SVG: портрет и фигура ---------- */

function svgPainter(ox, oy) {
    const parts = [];
    const P = (x, y, w, h, c) => parts.push('<rect x="' + (x + ox) + '" y="' + (y + oy) + '" width="' + w + '" height="' + h + '" fill="' + c + '"/>');
    return { P, parts };
}

// голова и плечи для карточек и чата
export function portraitSVG(a) {
    const pal = palFor(a);
    const { P, parts } = svgPainter(15, 50);
    parts.push('<rect width="30" height="30" fill="' + shade(pal.shirt, -0.72) + '"/>');
    parts.push('<rect width="30" height="10" fill="' + shade(pal.shirt, -0.62) + '"/>');
    paintPerson(P, pal, { pose: 'stand', working: false });
    return '<svg viewBox="0 0 30 30" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">' + parts.join('') + '</svg>';
}

// фигура в полный рост для окна настроек (поза: стоит или работает за столом)
export function figureSVG(a, working = false) {
    const pal = palFor(a);
    const { P, parts } = svgPainter(18, 58);
    paintPerson(P, pal, { pose: 'stand', working });
    return '<svg viewBox="0 0 36 62" xmlns="http://www.w3.org/2000/svg" shape-rendering="crispEdges">' + parts.join('') + '</svg>';
}
