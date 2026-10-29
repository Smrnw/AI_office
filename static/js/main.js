// Точка входа интерфейса: опрос сервера, отрисовка панелей, обработка кликов и клавиш.
import { $, esc, toast } from './util.js';
import { LANG, t as tr, startI18n, rememberLang } from './i18n.js';
import { S, TEAM } from './store.js';
import * as api from './api.js';
import {
    startOffice, syncAgents, say, toggleFullscreen, setLayout, openLayoutEditor, editorActions, onPanelInput, viewActions,
    refreshBackdrop, layoutWithMoreDesks, editorOpen
} from './office/index.js';
import { renderAgents, renderFiles, setFilesFilter, toggleDir } from './ui/team.js';
import {
    renderKanban, renderLimits, renderLog, renderHud, renderTopbar, initDragAndDrop,
    pushEvents, resetEvents, tickTimer
} from './ui/board.js';
import {
    renderChannels, renderChat, openChat, pollChat, sendChat, clearChat, startNewProjectDraft, resetFeed, updateComposer
} from './ui/chat.js';
import * as modals from './ui/modals.js';
import { openSettings, settingsActions, onAgentTypeChange, onLookChange } from './ui/settings.js';
import { openSetup, setupActions, setupChanges } from './ui/setup.js';

/* ------------------------------------------------------------------
   Опрос сервера
------------------------------------------------------------------- */

let polling = false;

function setOnline(ok) {
    if (ok === S.online) return;
    S.online = ok;
    toast(ok ? 'Связь с сервером восстановлена' : 'Нет связи с сервером, пробую снова…', ok ? 'ok' : 'err');
    if (S.app) renderTopbar();
}

// реплика над головой по событию вида "💻 [Coder_1] Берёт #401 ..."
function bubbleFromEvent(e) {
    const m = /^(\S+)\s+\[([^\]]+)\]\s*(.*)$/.exec(e.text);
    if (!m || !S.app || !S.app.agents[m[2]]) return;
    say(m[2], m[1] + ' ' + m[3].replace(/\s*\(.*$/, ''), 4.5);
}

function handleEvents(data) {
    const fresh = data.events || [];
    if (!S.lastEventId) {
        resetEvents(fresh);
    } else {
        pushEvents(fresh);
        fresh.forEach(e => {
            bubbleFromEvent(e);
            if (e.text.startsWith('🎉')) toast(e.text.replace(/^🎉\s*/, '🎉 '), 'ok');
            if (e.text.includes('[Диспетчер]')) toast(e.text, 'err');
        });
    }
    if (fresh.length) S.lastEventId = fresh[fresh.length - 1].id;
}

async function pollState() {
    if (polling) return;
    polling = true;
    let data;
    try {
        // видимая вкладка сообщает серверу, что офис смотрят: тогда агенты садятся за стол перед работой
        const viewer = document.hidden ? {} : { 'X-Office-Viewer': '1' };
        data = await api.get('/api/state' + (S.lastEventId ? '?since_event=' + S.lastEventId : ''), viewer);
        setOnline(true);
    } catch (e) {
        setOnline(false);
        return;
    } finally {
        polling = false;
    }
    // сервер перезапустился: номера событий начались заново
    if (S.bootId && data.preview_key !== S.bootId) {
        S.lastEventId = 0;
        S.bootId = data.preview_key;
        return pollState();
    }
    S.bootId = data.preview_key;
    data.received_at = Date.now() / 1000;
    const first = !S.app;
    // язык хранится на сервере: если в этом браузере выбран другой, подстраиваемся
    if (first && data.language && data.language !== LANG) {
        rememberLang(data.language);
        location.reload();
        return;
    }
    S.app = data;
    if (first) S.seenChat = { ...(data.chat_heads || {}) };
    // новый офис без штата: сразу предлагаем первоначальную настройку
    if (first && data.needs_setup) openSetup();
    if (data.layout_rev !== S.layoutRev) loadLayout(data.layout_rev);
    handleEvents(data);
    render();
}

async function loadLayout(rev) {
    S.layoutRev = rev;
    try {
        const d = await api.get('/api/layout');
        setLayout(d.layout);
    } catch (e) { S.layoutRev = null; }
}

async function saveLayout(layout) {
    try {
        const d = await api.post('/api/layout', { layout });
        S.layoutRev = d.rev;
        toast('Планировка сохранена');
        return true;
    } catch (e) {
        toast('Не удалось сохранить планировку: ' + e.message, 'err');
        return false;
    }
}

// новым сотрудникам не хватает столов: офис ставит блоки столов сам, тем же способом, что и кнопка «+»
let handledDeskRequest = null;
function handleDeskRequest() {
    const req = S.app.layout_request;
    if (!req || req.id === handledDeskRequest || editorOpen()) return;
    handledDeskRequest = req.id;
    const layout = layoutWithMoreDesks(req.desks);
    if (!layout) {
        toast(tr('Новым сотрудникам не хватает столов, а свободного места нет — расширьте офис в планировке'), 'err');
        return;
    }
    api.post('/api/layout', { layout }).then(d => {
        S.layoutRev = d.rev;
        setLayout(layout);
        toast(tr('Офис расширен: поставлены новые рабочие столы'));
    }).catch(e => toast(e.message, 'err'));
}

function render() {
    syncAgents(S.app.agents);
    handleDeskRequest();
    renderTopbar();
    renderAgents();
    renderFiles();
    renderKanban();
    renderHud();
    if (S.bottomTab === 'limits') renderLimits();
    renderLog();
    renderChannels();
    renderChat();
}

async function loop() {
    await pollState();
    if (S.online) await pollChat();
    setTimeout(loop, document.hidden ? 4000 : 1000);
}

document.addEventListener('office:refresh', () => { pollState(); });
document.addEventListener('office:channel', () => { renderAgents(); });
setInterval(tickTimer, 1000);

/* ------------------------------------------------------------------
   Действия по клику: data-action="имя" на любом элементе
------------------------------------------------------------------- */

function closeMenus(except) {
    document.querySelectorAll('.menu').forEach(m => { if (m !== except) m.hidden = true; });
}

async function postAndRefresh(path, body, okMsg) {
    try {
        const d = await api.post(path, body);
        if (d && d.ok === false) toast(d.error || 'Не получилось', 'err');
        else if (okMsg) toast(okMsg, 'info');
    } catch (e) {
        toast(e.message, 'err');
    }
    pollState();
}

const actions = {
    'menu': el => {
        const menu = $(el.dataset.menu);
        closeMenus(menu);
        menu.hidden = !menu.hidden;
    },
    'settings': el => openSettings(el.dataset.tab || 'tab-general'),
    'help': () => modals.openModal('helpModal'),
    'set-lang': async el => {
        const lang = el.dataset.lang;
        if (lang === LANG) return;
        try {
            await api.post('/api/office/language', { language: lang });
        } catch (e) { toast(e.message, 'err'); return; }
        rememberLang(lang);
        location.reload();
    },
    'toggle-theme': () => applyTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark', true),
    'close-modal': el => modals.closeModal(el.closest('.modal-backdrop').id),
    'mtab': el => modals.switchModalTab(el),
    'download-zip': () => { window.location.href = '/api/download-zip'; },
    'preview': () => modals.preview(),
    'new-project': () => startNewProjectDraft(),
    'clear-chat': () => clearChat(),
    'reset-board': async () => {
        if (!confirm(tr('Удалить все задачи с доски и очистить журнал? Файлы кода останутся.'))) return;
        await postAndRefresh('/api/reset', {}, 'Доска очищена');
        resetEvents([]);
        resetFeed();
    },
    'reset-usage': () => confirm(tr('Обнулить счётчики токенов по всем моделям?')) && postAndRefresh('/api/usage/reset', {}, 'Счётчики обнулены'),
    'stop': () => postAndRefresh('/api/stop', {}, 'Останавливаю агентов…'),
    'run-check': () => postAndRefresh('/api/checks/run', {}, 'Тестировщик начал проверку проекта'),
    'resume': () => postAndRefresh('/api/resume', {}, 'Работа продолжается'),
    'fullscreen': () => toggleFullscreen($('officeBox')),
    'tab': el => {
        S.bottomTab = el.dataset.tab;
        document.querySelectorAll('.bottom-panel .tab').forEach(t => t.classList.toggle('active', t.dataset.tab === S.bottomTab));
        document.querySelectorAll('.bottom-panel [data-pane]').forEach(p => { p.hidden = p.dataset.pane !== S.bottomTab; });
        if (S.app) { renderLimits(); renderLog(); }
    },
    ...editorActions,
    ...viewActions,
    'layout-open': () => openLayoutEditor(),
    'open-chat': el => openChat(el.dataset.ch),
    'send': () => sendChat(),
    'rename-office': async () => {
        const name = prompt(tr('Название офиса (пусто — «AI Office»):'), $('officeName').textContent);
        if (name === null) return;
        try {
            const d = await api.post('/api/office/name', { name });
            $('officeName').textContent = d.name;
            document.title = d.name;
            toast('Офис переименован');
        } catch (e) { toast(e.message, 'err'); }
    },
    'open-task': el => modals.openTask(el.dataset.tf, el.dataset.st),
    'task-save': () => modals.saveTask(),
    'task-return': () => modals.returnTask(),
    'task-save-code': () => modals.saveTaskCode(),
    'task-delete': () => modals.deleteTask(),
    'task-copy-code': () => modals.copyTaskCode(),
    'open-file': el => modals.openFile(el.dataset.file),
    'toggle-dir': el => toggleDir(el.dataset.dir),
    'autopilot-current': async () => {
        const goal = prompt(tr('Цель для автопилота: что должно получиться в итоге?'));
        if (goal && goal.trim()) postAndRefresh('/api/autopilot/start', { goal: goal.trim(), current_project: true }, tr('Автопилот запущен'));
    },
    'restore-version': el => {
        if (confirm(tr('Откатить проект к этой версии? Текущее состояние тоже сохранится версией.'))) {
            postAndRefresh('/api/versions/restore', { folder: el.dataset.dir, version: el.dataset.version }, tr('Проект откатан'));
        }
    },
    'git-log': async el => {
        try {
            const d = await api.get('/api/git/log?folder=' + encodeURIComponent(el.dataset.dir));
            const when = ts => new Date(ts * 1000).toLocaleString();
            $('gitSub').textContent = d.folder + '/';
            $('gitLog').innerHTML = d.commits.length
                ? d.commits.map(c => '<div class="git-row"><div class="git-msg" data-raw>' + esc(c.message.split('\n')[0]) + '</div>' +
                    '<div class="git-meta"><code>' + esc(c.sha) + '</code> · ' + esc(c.author) + ' · ' + esc(when(c.time)) + '</div></div>').join('')
                : '<div class="empty-note">' + esc(tr(d.enabled ? 'Коммитов пока нет: они появятся, когда задачи этого проекта будут приняты.' : 'История Git выключена в настройках.')) + '</div>';
            modals.openModal('gitModal');
        } catch (e) { toast(e.message, 'err'); }
    },
    'select-project': el => postAndRefresh('/api/project/select', { folder: el.dataset.dir }, tr('Текущий проект') + ': ' + el.dataset.dir),
    'new-file': () => {
        const name = prompt(tr('Имя нового файла (можно с папкой, например src/app.js):'));
        if (name && name.trim()) modals.openFile(name.trim(), true);
    },
    'file-save': () => modals.saveFile(),
    'file-delete': () => modals.deleteFile(),
    'file-copy': () => modals.copyFile(),
    'file-preview': () => modals.previewOpened(),
    ...settingsActions,
    ...setupActions,
    'setup-open': () => {
        const staff = Object.keys((S.app && S.app.agents) || {}).length;
        if (!staff || confirm(tr('Мастер заново соберёт команду и нейросети. Текущие сотрудники и провайдеры будут заменены. Продолжить?'))) openSetup();
    },
};

const changeActions = {
    'agent-model': el => postAndRefresh('/api/agent/model', { agent_id: el.dataset.agent, model_ref: el.value }, 'Модель агента изменена'),
    'cfg-type': el => { onAgentTypeChange(el); onLookChange(el); },
    'cfg-look': el => onLookChange(el),
    ...setupChanges,
};

document.addEventListener('click', e => {
    // клик по затемнённому фону закрывает окно
    if (e.target.classList && e.target.classList.contains('modal-backdrop')) {
        modals.closeModal(e.target.id);
        return;
    }
    const el = e.target.closest('[data-action]');
    if (!el) { closeMenus(); return; }
    // выпадающие списки внутри карточек не должны открывать саму карточку
    if (el !== e.target && e.target.closest('select, input, textarea')) return;
    const fn = actions[el.dataset.action];
    if (!fn) return;
    if (el.dataset.action !== 'menu') closeMenus();
    e.preventDefault();
    fn(el, e);
});

document.addEventListener('change', e => {
    if (e.target.dataset && (e.target.dataset.zoneField || e.target.dataset.zoneRole)) { onPanelInput(e.target); return; }
    const el = e.target.closest('[data-change]');
    if (el && changeActions[el.dataset.change]) changeActions[el.dataset.change](el);
});
// название и описание зоны меняются прямо при наборе
document.addEventListener('input', e => {
    const f = e.target.dataset && e.target.dataset.zoneField;
    if (f === 'label' || f === 'description') onPanelInput(e.target);
});

// Enter на карточке задачи открывает её (карточки фокусируются с клавиатуры)
document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.classList && e.target.classList.contains('task-card')) {
        modals.openTask(e.target.dataset.tf, e.target.dataset.st);
    }
});

/* ------------------------------------------------------------------
   Клавиатура
------------------------------------------------------------------- */

document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        closeMenus();
        if (modals.anyModalOpen()) modals.closeAllModals();
        return;
    }
    if (e.key === 'F1') { e.preventDefault(); modals.openModal('helpModal'); return; }
    const mod = e.ctrlKey || e.metaKey;
    if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); $('chatInput').focus(); return; }
    if (mod && e.key.toLowerCase() === 's' && modals.currentModalSave()) e.preventDefault();
});

const input = $('chatInput');
input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
        e.preventDefault();
        sendChat();
    }
});
input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = Math.min(input.scrollHeight, 150) + 'px';
});
$('filesFilter').addEventListener('input', e => setFilesFilter(e.target.value));

/* ------------------------------------------------------------------
   Старт
------------------------------------------------------------------- */

// тема: светлая по умолчанию, выбор запоминается в этом браузере
function applyTheme(theme, remember) {
    if (theme === 'dark') document.documentElement.dataset.theme = 'dark';
    else delete document.documentElement.dataset.theme;
    if (remember) { try { localStorage.setItem('office-theme', theme); } catch (e) { /* приватный режим */ } }
    refreshBackdrop();
}
try { applyTheme(localStorage.getItem('office-theme') || 'light', false); } catch (e) { applyTheme('light', false); }

startI18n();
document.querySelectorAll('[data-action="set-lang"]').forEach(b => b.classList.toggle('on', b.dataset.lang === LANG));

startOffice($('officeCanvas'), {
    onAgentClick: id => openChat(id),
    // человечек сел за стол: сервер может начинать работу
    onArrive: id => { api.post('/api/agent/arrived', { agent_id: id }).catch(() => {}); },
    toast,
    saveLayout,
});
initDragAndDrop();
S.chatChannel = TEAM;
updateComposer();
loop();
