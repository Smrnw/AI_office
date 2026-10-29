// Мелкие помощники для интерфейса.

export const $ = id => document.getElementById(id);

// экранирование для вставки в HTML и в атрибуты
export function esc(str) {
    return String(str ?? '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;')
        .replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

export function fmtSize(n) {
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(1) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
}

export function fmtNum(n) {
    n = Number(n) || 0;
    if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + 'K';
    return String(n);
}

export const fmtFull = n => Number(n || 0).toLocaleString('ru-RU');

export function fmtDuration(sec) {
    sec = Math.max(0, Math.floor(sec));
    const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m) + ':' + String(s).padStart(2, '0');
}

export function toast(msg, kind = 'ok') {
    let box = $('toastBox');
    if (!box) {
        box = document.createElement('div');
        box.id = 'toastBox';
        box.className = 'toast-box';
        document.body.appendChild(box);
    }
    const el = document.createElement('div');
    el.className = 'toast ' + kind;
    el.textContent = msg;
    box.appendChild(el);
    setTimeout(() => el.remove(), kind === 'err' ? 6000 : 4200);
}

// перерисовываем кусок страницы, только если разметка реально изменилась (нет мерцания, скролл не прыгает)
const htmlCache = {};
export function setHTML(id, html) {
    if (htmlCache[id] === html) return false;
    htmlCache[id] = html;
    $(id).innerHTML = html;
    return true;
}

export function fileExt(name) {
    const base = String(name).split('/').pop();
    return base.includes('.') ? base.split('.').pop().toLowerCase() : '';
}

export async function copyText(text) {
    try {
        await navigator.clipboard.writeText(text);
        return true;
    } catch (e) {
        return false;
    }
}

export const reduceMotion = !!(window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches);
