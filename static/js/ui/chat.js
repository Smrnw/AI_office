// Правая колонка: каналы, лента сообщений вперемешку с событиями офиса, поле ввода.
import { $, esc, toast } from '../util.js';
import { S, TEAM, STATUS_BUSY } from '../store.js';
import * as api from '../api.js';
import { t as tr } from '../i18n.js';
import { portraitSVG } from '../office/index.js';

let cache = { messages: [], pending: false, pendingAll: [] };
let feedKey = null;
let channelSig = '';

export function renderChannels() {
    const app = S.app;
    const ids = Object.keys(app.agents || {});
    if (S.chatChannel !== TEAM && !app.agents[S.chatChannel]) S.chatChannel = TEAM;
    const busy = ids.filter(id => app.agents[id].status === STATUS_BUSY);
    const heads = app.chat_heads || {};
    const unread = id => (heads[id] || 0) > (S.seenChat[id] || 0) && id !== S.chatChannel;
    const sig = ids.join('|') + '#' + S.chatChannel + '#' + busy.join('|') + '#' + [TEAM, ...ids].filter(unread).join('|');
    if (sig === channelSig) return;
    channelSig = sig;

    const dot = id => unread(id) ? '<span class="unread">•</span>' : '';
    $('channels').innerHTML =
        '<button class="chan' + (S.chatChannel === TEAM ? ' active' : '') + '" data-action="open-chat" data-ch="' + TEAM + '">🚀 Проект' + dot(TEAM) + '</button>' +
        ids.map(id => '<button class="chan' + (S.chatChannel === id ? ' active' : '') + (busy.includes(id) ? ' working' : '') +
            '" data-action="open-chat" data-ch="' + esc(id) + '">@' + esc(id) + dot(id) + '</button>').join('');

    updateComposer();
}

export function updateComposer() {
    const app = S.app;
    const input = $('chatInput');
    const hasTasks = app && (app.tasks || []).length > 0;
    let ph, hint;
    if (S.chatChannel === TEAM) {
        ph = hasTasks ? 'Что доработать?' : 'Опишите проект…';
        hint = hasTasks
            ? 'Сообщение уйдёт руководителю как доработка. <button data-action="new-project">Начать новый проект</button>'
            : 'Первое сообщение запустит проект. Чтобы обратиться к агенту, напишите @Имя.';
    } else {
        const ag = (app.agents || {})[S.chatChannel] || {};
        const byType = {
            planner: 'Опишите доработку — руководитель разобьёт её на задачи.',
            coder: 'Попросите изменить код или задайте вопрос.',
            qa: 'Попросите проверить код или разобрать ошибку.'
        };
        ph = byType[ag.pipeline_type] || 'Напишите сообщение…';
        hint = 'Личный диалог с <b>@' + esc(S.chatChannel) + '</b>. Если попросите что-то изменить, агент заведёт задачу.';
    }
    input.placeholder = ph;
    $('chatHint').innerHTML = hint;
}

export function openChat(channel) {
    S.chatChannel = channel;
    channelSig = '';
    feedKey = null;
    cache = { messages: [], pending: false, pendingAll: cache.pendingAll };
    if (S.app) {
        renderChannels();
        renderChat();
        document.dispatchEvent(new CustomEvent('office:channel'));
    }
    pollChat();
    $('chatInput').focus();
}

export async function pollChat() {
    const ch = S.chatChannel;
    try {
        const d = await api.get('/api/chat?agent_id=' + encodeURIComponent(ch));
        if (ch !== S.chatChannel) return;     // пока ждали, пользователь переключил канал
        cache = { messages: d.messages || [], pending: !!d.pending, pendingAll: d.pending_all || [] };
        S.seenChat[ch] = cache.messages.length ? cache.messages[cache.messages.length - 1].id : 0;
        renderChat();
    } catch (e) { /* связь проверяет опрос состояния */ }
}

function authorClass(a) {
    return a && a.pipeline_type === 'coder' ? ' coder' : a && a.pipeline_type === 'qa' ? ' qa' : '';
}

// файлы из сообщения агента: клик скачивает файл, значок 📌 открывает задачу
function filesBlock(tasks) {
    if (!tasks || !tasks.length) return '';
    const existing = new Set((S.app.files || []).map(f => f.name));
    const chips = tasks.map(t => {
        const name = String(t.filename || '');
        const dl = existing.has(name)
            ? '<a class="file-chip" href="/api/file/download?name=' + encodeURIComponent(name) + '" download title="Скачать ' + esc(name) + '">⬇ ' + esc(name) + '</a>'
            : '<span class="file-chip pending" title="Файл ещё пишется">⏳ ' + esc(name) + '</span>';
        return '<div class="file-line">' + dl +
            '<button class="task-link" data-action="open-task" data-tf="' + esc(t.task_file) + '" data-st="" title="Открыть задачу #' + esc(t.id) + '">📌 #' + esc(t.id) + '</button></div>';
    }).join('');
    const zip = tasks.length > 1 && tasks.every(t => existing.has(String(t.filename)))
        ? '<a class="file-chip zip" href="/api/download-zip" download>📦 Скачать всё (ZIP)</a>' : '';
    return '<div class="msg-tasks">' + chips + zip + '</div>';
}

const CHECK_STEPS = {
    syntax: 'Синтаксис', security: 'Безопасность', tests: 'Автотесты', browser: 'Браузер', vision: 'Скриншот глазами модели'
};
const LEVEL_ICON = { error: '❌', warning: '⚠️', info: 'ℹ️' };

// отчёт автопроверки: скриншоты (клик открывает в полный размер), шаги проверки и главные замечания
function checkBlock(c, msgId) {
    if (!c) return '';
    const shot = n => '/api/checks/shot?folder=' + encodeURIComponent(c.folder || '') + '&name=' + encodeURIComponent(n) + '&v=' + msgId;
    const shots = (c.shots || []).slice(0, 4).map(n =>
        '<a href="' + shot(n) + '" target="_blank" rel="noopener" title="Открыть скриншот"><img src="' + shot(n) + '" alt="" loading="lazy"></a>').join('');
    const steps = Object.entries(c.steps || {}).map(([k, v]) =>
        '<li><b>' + esc(CHECK_STEPS[k] || k) + '</b>: ' + esc(v) + '</li>').join('');
    const items = (c.items || []).map(i =>
        '<li class="lv-' + esc(i.level) + '">' + (LEVEL_ICON[i.level] || '') + ' ' + esc(i.text) + '</li>').join('');
    return '<div class="check-report">' + (shots ? '<div class="check-shots">' + shots + '</div>' : '') +
        '<ul class="check-steps">' + steps + '</ul>' + (items ? '<ul class="check-items">' + items + '</ul>' : '') + '</div>';
}

// прогресс автопилота: требования к цели с отметками
function autopilotBlock(a) {
    if (!a || !a.requirements || !a.requirements.length) return '';
    const done = a.requirements.filter(r => r.done).length;
    return '<div class="ap-report"><div class="ap-head">🎯 <span data-raw>' + esc(a.goal) + '</span></div>' +
        '<div class="ap-bar"><i style="width:' + Math.round(done * 100 / a.requirements.length) + '%"></i></div>' +
        '<ul>' + a.requirements.map(r => '<li class="' + (r.done ? 'ok' : '') + '"' + (r.note ? ' title="' + esc(r.note) + '"' : '') + '>' +
            (r.done ? '✅' : '⬜') + ' <span data-raw>' + esc(r.text) + '</span></li>').join('') + '</ul></div>';
}

export function renderChat() {
    const app = S.app;
    if (!app) return;
    // в чате только реплики людей и агентов; события офиса живут во вкладке «Журнал»
    let html = cache.messages.filter(m => m.role !== 'system').map(m => {
        if (m.role === 'user') {
            const to = S.chatChannel !== TEAM ? '@' + S.chatChannel
                : (m.to && m.to.length ? m.to.map(id => '@' + id).join(', ') : 'Команде');
            return '<div class="row me"><div class="bubble"><div class="who"><span>Вы → ' + esc(to) + '</span><span>' + esc(m.ts) + '</span></div><span data-raw>' + esc(m.text) + '</span></div></div>';
        }
        const who = (app.agents || {})[m.author] || { id: m.author, shirt: '#3b82f6', hair: '#f1f5f9' };
        return '<div class="row"><div class="avatar">' + portraitSVG(who) + '</div><div class="bubble"><div class="who"><span class="name' + authorClass(who) + '">[' + esc(who.id) + ']</span><span>' + esc(m.ts) + '</span></div>' +
            esc(m.text) + filesBlock(m.tasks) + checkBlock(m.check, m.id) + autopilotBlock(m.autopilot) + '</div></div>';
    }).join('');

    if (cache.pending) html += '<div class="row"><div class="bubble"><span class="typing-dots"><i></i><i></i><i></i></span></div></div>';
    if (!html) {
        html = S.chatChannel === TEAM
            ? '<div class="empty-note">Здесь пока тихо.</div>'
            : '<div class="empty-note">Начните диалог с @' + esc(S.chatChannel) + '.</div>';
    }

    $('chatSend').disabled = cache.pending;
    const feed = $('chatFeed');
    const key = S.chatChannel + '|' + html;
    if (key === feedKey) return;
    // прокручиваем вниз, только если человек и так был внизу (или это первая отрисовка)
    const stick = feedKey === null || feed.scrollHeight - feed.scrollTop - feed.clientHeight < 90;
    feedKey = key;
    feed.innerHTML = html;
    if (stick) feed.scrollTop = feed.scrollHeight;
}

export function resetFeed() { feedKey = null; }

export async function sendChat() {
    const input = $('chatInput');
    const text = input.value.trim();
    if (!text || cache.pending) return;

    // /new стирает доску, поэтому спрашиваем, если там уже что-то есть
    if (S.chatChannel === TEAM && text.toLowerCase().startsWith('/new') && (S.app.tasks || []).length &&
        !confirm(tr('Новый проект очистит доску задач. Продолжить?'))) return;

    input.value = '';
    input.style.height = '';
    try {
        const data = await api.post('/api/chat', { agent_id: S.chatChannel, message: text });
        if (!data.ok) {
            toast(data.error || 'Не удалось отправить сообщение', 'err');
            input.value = text;
            return;
        }
    } catch (e) {
        toast(e.message || 'Нет связи с сервером', 'err');
        input.value = text;
        return;
    }
    await pollChat();
    document.dispatchEvent(new CustomEvent('office:refresh'));
}

export async function clearChat() {
    if (!confirm(tr('Очистить историю этого чата?'))) return;
    await api.post('/api/chat/clear', { agent_id: S.chatChannel });
    feedKey = null;
    pollChat();
}

export function startNewProjectDraft() {
    openChat(TEAM);
    const input = $('chatInput');
    input.value = '/new ';
    input.focus();
}
