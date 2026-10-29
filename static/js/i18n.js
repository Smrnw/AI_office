// Язык интерфейса. Исходные тексты написаны по-русски; для английского их подменяет словарь из i18n-en.js.
// Переводятся и статичная разметка, и всё, что панели дорисовывают позже (включая журнал с сервера):
// за страницей следит MutationObserver. Свои тексты пользователя помечаются data-raw и не трогаются.
import { EXACT, PATTERNS } from './i18n-en.js';

const KEY = 'office-lang';
const CYR = /[А-Яа-яЁё]/;
const ATTRS = ['title', 'placeholder', 'aria-label'];
const SKIP = 'script, style, code, pre, textarea, [data-raw]';
// значки, пробелы и знаки по краям строки: «⚙️ Настройки…» ищется в словаре как «Настройки»
const EDGES = /^([^A-Za-zА-Яа-яЁё0-9«"'(@#/[]*)([\s\S]*?)([\s:.…,;!?]*)$/;

export const LANG = (() => {
    try { return localStorage.getItem(KEY) === 'en' ? 'en' : 'ru'; } catch (e) { return 'ru'; }
})();

const cache = new Map();

function lookup(s) {
    if (Object.prototype.hasOwnProperty.call(EXACT, s)) return EXACT[s];
    for (const [re, rep] of PATTERNS) {
        const m = re.exec(s);
        if (m) return typeof rep === 'function' ? rep(...m.slice(1)) : s.replace(re, rep);
    }
    // составные подписи: «Руководитель, Разработчики», «Тестировщик • Место #3»
    for (const sep of ['; ', ' • ', ', ']) {
        if (!s.includes(sep)) continue;
        const parts = s.split(sep).map(p => CYR.test(p) ? lookup(p) : p);
        if (parts.every(p => p !== null)) return parts.join(sep);
    }
    return null;
}

export function t(s) {
    if (LANG !== 'en' || !s || typeof s !== 'string' || !CYR.test(s)) return s;
    if (cache.has(s)) return cache.get(s);
    let out = translateWhole(s);
    // переносы строк из разметки (абзацы справки) в словаре записаны одним пробелом
    if (out === null && /\s{2,}|\n/.test(s.trim())) {
        out = translateWhole(s.match(/^\s*/)[0] + s.trim().replace(/\s+/g, ' ') + s.match(/\s*$/)[0]);
    }
    if (out === null) out = s;
    if (cache.size > 5000) cache.clear();
    cache.set(s, out);
    return out;
}

function translateWhole(s) {
    const whole = lookup(s.trim());
    if (whole !== null) return s.match(/^\s*/)[0] + whole + s.match(/\s*$/)[0];
    const m = EDGES.exec(s);
    const core = m && m[2] ? lookup(m[2]) : null;
    return core !== null ? m[1] + core + m[3] : null;
}

function skipped(el) {
    return !el || !!el.closest(SKIP);
}

function translateText(node) {
    const v = node.nodeValue;
    if (!v || !CYR.test(v) || skipped(node.parentElement)) return;
    const r = t(v);
    if (r !== v) node.nodeValue = r;
}

function translateAttrs(el) {
    if (el.closest('[data-raw]')) return;      // подсказки у полей ввода переводим, их содержимое - нет
    for (const a of ATTRS) {
        const v = el.getAttribute(a);
        if (v && CYR.test(v)) {
            const r = t(v);
            if (r !== v) el.setAttribute(a, r);
        }
    }
}

export function translateTree(root) {
    if (LANG !== 'en' || !root) return;
    if (root.nodeType === 3) { translateText(root); return; }
    if (root.nodeType !== 1) return;
    translateAttrs(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        if (n.nodeType === 3) translateText(n);
        else translateAttrs(n);
    }
}

export function startI18n() {
    document.documentElement.lang = LANG;
    if (LANG !== 'en') return;
    translateTree(document.body);
    new MutationObserver(list => {
        for (const m of list) {
            if (m.type === 'childList') m.addedNodes.forEach(translateTree);
            else if (m.type === 'characterData') translateText(m.target);
            else if (m.type === 'attributes') translateAttrs(m.target);
        }
    }).observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
}

// выбор запоминается в браузере; страница перезагружается, чтобы всё нарисовать заново
export function rememberLang(lang) {
    try { localStorage.setItem(KEY, lang); } catch (e) { /* приватный режим */ }
}
