// Общие примитивы рисования. Мир логический 1600x900 (16:9), на экран переводится
// через масштаб V.SC и отступы V.OX/V.OY; края прямоугольников округляются до
// физических пикселей, поэтому пиксель-арт остаётся чётким на любом экране.

import { t as tr } from '../i18n.js';

export const W = 1600, H = 900;
export const WALL_Y = 150;            // где стена встречается с полом
export const FONT = '"Segoe UI", -apple-system, Roboto, Helvetica, Arial, sans-serif';

// SC - масштаб мира (с учётом приближения камеры), LS - масштаб подписей поверх сцены
export const V = { G: null, SC: 1, OX: 0, OY: 0, DPR: 1, LS: 1 };

export function X(v) { return Math.round(V.OX + v * V.SC); }
export function Y(v) { return Math.round(V.OY + v * V.SC); }

export function R(x, y, w, h, color) {
    const x0 = X(x), y0 = Y(y), x1 = X(x + w), y1 = Y(y + h);
    V.G.fillStyle = color;
    V.G.fillRect(x0, y0, Math.max(1, x1 - x0), Math.max(1, y1 - y0));
}

// прямоугольник с контуром: основа почти всего пиксель-арта
export function RO(x, y, w, h, fill, outline) {
    R(x, y, w, h, outline);
    R(x + 1, y + 1, w - 2, h - 2, fill);
}

// дешёвый детерминированный «рандом», чтобы декор не прыгал между кадрами
export function mix(n) {
    n = Math.imul((n | 0) ^ ((n | 0) >>> 16), 0x45d9f3b);
    n = Math.imul(n ^ (n >>> 16), 0x45d9f3b);
    return (n ^ (n >>> 16)) >>> 0;
}

export function hash(str) {
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
}

export const isHex = c => /^#[0-9a-fA-F]{6}$/.test(c || '');

// осветлить (f > 0) или затемнить (f < 0) цвет вида #rrggbb
export function shade(hex, f) {
    if (!isHex(hex)) hex = '#3b82f6';
    const n = parseInt(hex.slice(1), 16);
    const c = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(v =>
        Math.max(0, Math.min(255, Math.round(f < 0 ? v * (1 + f) : v + (255 - v) * f))));
    return '#' + c.map(v => v.toString(16).padStart(2, '0')).join('');
}

export function clip(str, n) {
    str = String(str || '');
    return str.length > n ? str.slice(0, n - 1) + '…' : str;
}

export function softShadow(x, y, w, h, alpha) {
    const G = V.G;
    const g = G.createLinearGradient(0, Y(y), 0, Y(y + h));
    g.addColorStop(0, 'rgba(0,0,0,' + (alpha || 0.35) + ')');
    g.addColorStop(1, 'rgba(0,0,0,0)');
    G.fillStyle = g;
    G.fillRect(X(x), Y(y), Math.max(1, X(x + w) - X(x)), Math.max(1, Y(y + h) - Y(y)));
}

export function groundShadow(cx, cy, rx, ry, alpha) {
    const G = V.G;
    G.fillStyle = 'rgba(0,0,0,' + alpha + ')';
    G.beginPath();
    G.ellipse(X(cx), Y(cy), rx * V.SC, ry * V.SC, 0, 0, Math.PI * 2);
    G.fill();
}

export function glow(cx, cy, radius, rgba) {
    const G = V.G;
    const g = G.createRadialGradient(X(cx), Y(cy), 0, X(cx), Y(cy), radius * V.SC);
    g.addColorStop(0, rgba);
    g.addColorStop(1, 'rgba(0,0,0,0)');
    G.fillStyle = g;
    G.fillRect(X(cx - radius), Y(cy - radius), Math.round(radius * 2 * V.SC), Math.round(radius * 2 * V.SC));
}

// объёмная коробка в виде «три четверти»: крышка y-h..y-h+d, передняя грань до y+d
export function box(x, y, w, d, h, c) {
    R(x, y - h, w, d + h, c.edge);                 // контур
    R(x + 1, y - h + 1, w - 2, d - 1, c.top);
    R(x + 1, y - h + 1, w - 2, 1, c.hi);
    R(x + 1, y - h + d, w - 2, h - 1, c.front);
    R(x + 1, y - h + d, w - 2, 1, c.lip || c.hi);
    R(x + w - 3, y - h + d + 1, 2, h - 2, c.dark);
}

export function pillPath(x, y, w, h, r) {
    const G = V.G;
    G.beginPath();
    if (G.roundRect) G.roundRect(x, y, w, h, r); else G.rect(x, y, w, h);
}

export function text(str, x, y, size, color, weight = 700, align = 'center') {
    const G = V.G;
    G.font = weight + ' ' + (size * V.SC) + 'px ' + FONT;
    G.fillStyle = color;
    G.textAlign = align;
    G.textBaseline = 'middle';
    G.fillText(tr(str), X(x), Y(y));
    G.textBaseline = 'alphabetic';
    G.textAlign = 'left';
}

// рисуем в другой canvas, временно подменяя контекст и отступы
export function paintInto(target, ox, oy, fn) {
    const saved = { g: V.G, ox: V.OX, oy: V.OY };
    V.G = target.getContext('2d');
    V.OX = ox; V.OY = oy;
    try { fn(); } finally { V.G = saved.g; V.OX = saved.ox; V.OY = saved.oy; }
}

export const PAL = {
    wood: { top: '#c08a55', front: '#86562f', edge: '#3b2414', dark: '#6b4325', hi: '#e2b07a', lip: '#a06a3d' },
    darkwood: { top: '#6e4528', front: '#4a2c17', edge: '#1f1209', dark: '#3a2211', hi: '#93623b', lip: '#5c3820' },
    white: { top: '#eef2f6', front: '#cfd7e1', edge: '#5b6676', dark: '#b3bdca', hi: '#ffffff', lip: '#dfe5ec' },
    metal: { top: '#4a5366', front: '#2f3646', edge: '#11151d', dark: '#232936', hi: '#6c7891', lip: '#3a4256' },
};
