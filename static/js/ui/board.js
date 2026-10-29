// Нижняя панель: канбан с перетаскиванием, лимиты нейросетей, журнал. Плюс HUD поверх офиса.
import { $, esc, fmtFull, fmtNum, fmtDuration, setHTML, toast, reduceMotion } from '../util.js';
import { S, STATUS_BUSY } from '../store.js';
import * as api from '../api.js';
import { t as tr } from '../i18n.js';

const COLS = ['todo', 'in_progress', 'testing', 'done'];
const STATE_TAG = {
    todo: ['В очереди', ''],
    in_progress: ['Работает', ''],
    testing: ['На проверке', 'review'],
    done: ['Готово', 'ok']
};

/* ---------- канбан ---------- */

let cardRects = {};
let kanbanReady = false;

// запоминаем места карточек, после перерисовки они плавно «переезжают» на новые (приём FLIP)
function rememberCards() {
    cardRects = {};
    document.querySelectorAll('.task-card[data-tf]').forEach(el => { cardRects[el.dataset.tf] = el.getBoundingClientRect(); });
}

function animateCards() {
    if (reduceMotion || !kanbanReady) return;
    document.querySelectorAll('.task-card[data-tf]').forEach(el => {
        const was = cardRects[el.dataset.tf];
        if (!was) {
            el.animate([{ opacity: 0, transform: 'scale(0.92)' }, { opacity: 1, transform: 'none' }], { duration: 260, easing: 'ease-out' });
            return;
        }
        const now = el.getBoundingClientRect();
        const dx = was.left - now.left, dy = was.top - now.top;
        if (Math.abs(dx) < 2 && Math.abs(dy) < 2) return;
        el.animate([{ transform: 'translate(' + dx + 'px,' + dy + 'px)' }, { transform: 'none' }], { duration: 480, easing: 'cubic-bezier(.2,.8,.2,1)' });
    });
}

function cardHTML(t) {
    const q = t.qa_notes || '';
    const warn = /^(❌|⚠|↩)/.test(q);
    const busy = !!t.busy;
    const who = (busy && t.worker) ? t.worker : (t.assigned_to || '');
    const [label, cls] = STATE_TAG[t.status] || ['', ''];
    const worker = busy && S.app.agents ? S.app.agents[t.worker] : null;
    const walking = worker && worker.status === 'Идёт';
    const text = walking ? 'Идёт к столу' : busy && t.status === 'testing' ? 'Проверяет' : busy && t.status === 'todo' ? 'Берёт в работу' : label;
    const stateTag = '<span class="tag state ' + cls + '">' + (busy ? '<i class="spin"></i>' : '') + text + '</span>';
    const note = q && (warn || t.status === 'todo') ? '<div class="task-note">' + esc(q.slice(0, 140)) + '</div>' : '';
    return '<div class="task-card st-' + esc(t.status) + (busy ? ' busy' : '') + '" tabindex="0"' +
        ' data-action="open-task" data-tf="' + esc(t.task_file) + '" data-st="' + esc(t.status) + '" title="' + esc(q || t.spec || t.task_file) + '">' +
        '<div class="task-head"><span class="task-id">#' + esc(t.id) + '</span><span class="task-title">' + esc(t.title) + '</span></div>' +
        '<div class="task-tags"><span class="tag file" title="' + esc(t.filename) + '">' + esc(t.filename.split('/').pop()) + '</span>' + stateTag +
        (who ? '<span class="tag who">' + esc(who) + '</span>' : '') +
        (t.attempts > 1 ? '<span class="tag retry">×' + t.attempts + '</span>' : '') + '</div>' + note + '</div>';
}

export function renderKanban() {
    if (drag && drag.active) return;          // не трогаем доску, пока карточку тянут
    const tasks = S.app.tasks || [];
    rememberCards();
    let changed = false;
    COLS.forEach(col => {
        const list = tasks.filter(t => t.status === col);
        $('cnt-' + col).textContent = list.length;
        const empty = col === 'todo' && !tasks.length
            ? '<div class="empty-note">Задач нет.<br>Опишите проект в чате справа.</div>'
            : '<div class="empty-note">Пусто</div>';
        if (setHTML('col-' + col, list.map(cardHTML).join('') || empty)) changed = true;
    });
    if (changed) animateCards();
    kanbanReady = true;

    const done = tasks.filter(t => t.status === 'done').length;
    const pct = tasks.length ? Math.round(done * 100 / tasks.length) : 0;
    $('kanBar').style.width = pct + '%';
    $('kanPct').textContent = pct + '%';
}

/* ---------- перетаскивание карточек ----------
   Своё, на событиях указателя: работает и мышью, и пальцем, а пока карточку тянут,
   доска не перерисовывается (иначе опрос сервера раз в секунду обрывал бы перетаскивание). */

let drag = null;
let swallowClick = false;

function columnAt(x, y) {
    const el = document.elementFromPoint(x, y);
    return el ? el.closest('.kan-col') : null;
}

function canDrop(col) {
    return col && col.dataset.col !== 'in_progress' && col.dataset.col !== drag.from;
}

function highlight(col) {
    document.querySelectorAll('.kan-col').forEach(c => {
        c.classList.toggle('drop-ok', c === col && canDrop(c));
        c.classList.toggle('drop-no', c === col && !canDrop(c));
    });
}

function endDrag() {
    if (!drag) return;
    if (drag.ghost) drag.ghost.remove();
    drag.card.classList.remove('dragging');
    document.querySelectorAll('.kan-col').forEach(c => c.classList.remove('drop-ok', 'drop-no'));
    document.body.classList.remove('dragging-card');
    drag = null;
}

async function dropTo(job, target) {
    if (target === 'in_progress') { toast('В работу задачи берут сами агенты — перенесите в «Очередь»', 'info'); return; }
    // при возврате на доработку можно сразу сказать агенту, что исправить
    let comment = '';
    if (target === 'todo' && job.from !== 'todo') {
        comment = prompt(tr('Что доработать? Агент увидит этот комментарий (можно оставить пустым).'), '');
        if (comment === null) return;
    }
    try {
        await api.post('/api/task/move', { task_file: job.tf, new_status: target, comment });
        toast(target === 'todo' ? 'Задача вернулась в очередь — агенты возьмут её в работу' : 'Задача перенесена', 'info');
    } catch (err) {
        toast(err.message, 'err');
    }
    document.dispatchEvent(new CustomEvent('office:refresh'));
}

export function initDragAndDrop() {
    const board = $('kanban');
    board.addEventListener('pointerdown', e => {
        if (e.button !== 0) return;
        const card = e.target.closest('.task-card');
        if (!card) return;
        if (card.classList.contains('busy')) return;          // над ней работает агент
        drag = { card, tf: card.dataset.tf, from: card.dataset.st, sx: e.clientX, sy: e.clientY, active: false };
    });
    document.addEventListener('pointermove', e => {
        if (!drag) return;
        if (!drag.active) {
            if (Math.hypot(e.clientX - drag.sx, e.clientY - drag.sy) < 6) return;
            const r = drag.card.getBoundingClientRect();
            drag.active = true;
            drag.dx = drag.sx - r.left;
            drag.dy = drag.sy - r.top;
            drag.ghost = drag.card.cloneNode(true);
            drag.ghost.classList.add('drag-ghost');
            drag.ghost.style.width = r.width + 'px';
            document.body.appendChild(drag.ghost);
            drag.card.classList.add('dragging');
            document.body.classList.add('dragging-card');
        }
        drag.ghost.style.left = (e.clientX - drag.dx) + 'px';
        drag.ghost.style.top = (e.clientY - drag.dy) + 'px';
        highlight(columnAt(e.clientX, e.clientY));
    });
    document.addEventListener('pointerup', e => {
        if (!drag) return;
        const job = drag;
        if (!job.active) { drag = null; return; }
        const col = columnAt(e.clientX, e.clientY);
        const ok = canDrop(col);
        const target = col && col.dataset.col;
        endDrag();
        swallowClick = true;                                 // отпускание после перетаскивания - не клик по карточке
        setTimeout(() => { swallowClick = false; }, 0);
        if (target && (ok || target === 'in_progress')) dropTo(job, target);
    });
    document.addEventListener('pointercancel', endDrag);
    document.addEventListener('keydown', e => { if (e.key === 'Escape') endDrag(); });
    board.addEventListener('click', e => {
        if (swallowClick) { e.stopPropagation(); e.preventDefault(); swallowClick = false; }
    }, true);
}

/* ---------- лимиты и журнал ---------- */

export function renderLimits() {
    const rows = S.app.usage || [];
    setHTML('limitsGrid', rows.map(u => {
        const cls = u.pct >= 85 ? 'bad' : u.pct >= 60 ? 'warn' : '';
        const left = u.used >= u.limit ? 'лимит исчерпан' : 'осталось ' + fmtFull(u.limit - u.used);
        return '<div class="limit-card ' + cls + '" title="' + esc(u.model_id) + ' • запросов: ' + fmtFull(u.calls) + (u.exact ? ' • точный расход от провайдера' : ' • оценка по длине текста') + '">' +
            '<div class="limit-top"><span class="limit-name">' + esc(u.name) + '</span><span class="limit-prov">' + esc(u.provider) + '</span></div>' +
            '<div class="limit-nums"><b>' + fmtFull(u.used) + '</b> / ' + fmtFull(u.limit) + '</div>' +
            '<div class="limit-bar"><i style="width:' + Math.min(100, u.pct) + '%"></i></div>' +
            '<div class="limit-foot"><span>вход ' + fmtNum(u.in) + ' • выход ' + fmtNum(u.out) + ' • ' + left + '</span><span class="limit-pct">' + u.pct + '%</span></div>' +
            '</div>';
    }).join('') || '<div class="empty-note" style="grid-column:1/-1">Расход токенов появится после первого запроса к нейросети.</div>');
}

export function eventClass(text) {
    if (/✅|🎉|☑/.test(text)) return ' good';
    if (/❌|⚠|🛑|🔴/.test(text)) return ' bad';
    return '';
}

let logEvents = [];
export function pushEvents(events) {
    logEvents = logEvents.concat(events).slice(-300);
}
export function resetEvents(events) {
    logEvents = events.slice(-300);
}
export function renderLog() {
    if (S.bottomTab !== 'log') return;
    const box = $('logList');
    const stick = box.scrollHeight - box.scrollTop - box.clientHeight < 40;
    const changed = setHTML('logList', logEvents.map(e =>
        '<div class="log-line' + eventClass(e.text) + '"><time>' + esc(e.ts) + '</time><span>' + esc(e.text) + '</span></div>').join('')
        || '<div class="empty-note">Журнал пуст</div>');
    if (changed && stick) box.scrollTop = box.scrollHeight;
}

/* ---------- HUD поверх офиса и верхняя панель ---------- */

export function renderHud() {
    const app = S.app;
    const tasks = app.tasks || [];
    const done = tasks.filter(t => t.status === 'done').length;
    const pct = tasks.length ? Math.round(done * 100 / tasks.length) : 0;
    const working = Object.values(app.agents || {}).filter(a => a.status === STATUS_BUSY).length;
    const m = app.metrics || {};
    let html = '<div class="stat" title="Готово задач">📋 <b>' + done + '/' + tasks.length + '</b><span class="hud-bar"><i style="width:' + pct + '%"></i></span></div>' +
        '<div class="stat' + (working ? ' live' : '') + '" title="Агентов в работе">' + (working ? '<i class="spin"></i>' : '👥') + ' <b>' + working + '</b></div>' +
        '<div class="stat" title="Токенов потрачено (вход + выход)">🔥 <b>' + fmtNum((m.tokens_in || 0) + (m.tokens_out || 0)) + '</b></div>' +
        '<div class="stat" title="Файлов в рабочей папке">📄 <b>' + (m.files_total || 0) + '</b></div>';
    if (app.paused && app.open_tasks > 0) html += '<div class="stat warn">⏸ пауза</div>';
    if (app.run_started_at) html += '<div class="stat" title="Время работы">⏱ <b id="hudTimer"></b></div>';
    setHTML('statusbar', html);
    tickTimer();
}

// таймер обновляем отдельно, чтобы спиннер в HUD не перезапускался каждую секунду
export function tickTimer() {
    const el = $('hudTimer');
    const app = S.app;
    if (el && app && app.run_started_at) {
        const skew = (app.server_time || 0) - (app.received_at || 0);
        el.textContent = fmtDuration(Date.now() / 1000 + skew - app.run_started_at);
    }
}

// текущий проект в шапке; клик открывает список всех проектов, чтобы вернуться к любому
let projectsSig = '';
function renderAutopilot(app) {
    const a = app.autopilot || {};
    const active = ['planning', 'review', 'working'].includes(a.status);
    const chip = $('autopilotChip');
    chip.hidden = !active;
    if (!active) return;
    const reqs = a.requirements || [];
    const stage = { planning: 'готовит проект', review: 'оценивает', working: 'команда работает' }[a.status];
    chip.textContent = '🤖 Автопилот · круг ' + a.cycle + '/' + a.max_cycles +
        (reqs.length ? ' · ' + reqs.filter(r => r.done).length + '/' + reqs.length : '') + ' · ' + stage;
    chip.title = a.goal || '';
}

function renderProjects(app) {
    renderAutopilot(app);
    document.querySelectorAll('.app-version').forEach(el => { el.textContent = app.version ? 'v' + app.version : ''; });
    const list = app.projects || [];
    const current = list.find(p => p.current);
    $('ideaChip').textContent = current ? '📁 ' + current.idea : (app.project_idea ? '🚀 ' + app.project_idea : (list.length ? '📁 Выбрать проект' : ''));
    const sig = JSON.stringify([list, app.versions]);
    if (sig === projectsSig) return;
    projectsSig = sig;
    const vers = app.versions || [];
    const when = ts => new Date(ts * 1000).toLocaleString([], { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
    // сверху - действия с текущим проектом под его названием, ниже - список всех проектов
    $('projectMenu').innerHTML = (current
        ? '<div class="proj-current"><small>' + esc(tr('Текущий проект')) + '</small><b data-raw>' + esc(current.idea) + '</b>' +
          '<code data-raw>' + esc(current.folder) + '/</code></div>' +
          '<button data-action="autopilot-current">🤖 Автопилот для этого проекта…</button>' +
          '<button data-action="git-log" data-dir="' + esc(current.folder) + '">📜 История изменений (Git)</button>' +
          (vers.length ? '<div class="menu-title">Сохранённые версии для отката</div>' + vers.map(v =>
              '<button class="proj-item" data-action="restore-version" data-version="' + esc(v.id) + '" data-dir="' + esc(current.folder) + '" title="Откатить проект к этой версии">' +
              '<b>↩ ' + esc(when(v.created)) + '</b><small>' + esc(v.note) + ' · ' + esc(v.files) + ' ф.</small></button>').join('') : '') +
          '<hr>'
        : '') +
        '<div class="menu-title">Все проекты</div>' +
        [...list].sort((a, b) => b.updated - a.updated).map(p =>
            '<button class="proj-item' + (p.current ? ' current' : '') + '" data-action="select-project" data-dir="' + esc(p.folder) + '">' +
            '<b>' + (p.current ? '✓ ' : '') + esc(p.folder) + '</b><small>' + esc(p.idea) + '</small></button>').join('') +
        '<hr><button data-action="new-project">🚀 Новый проект…</button>';
}

export function renderTopbar() {
    const app = S.app;
    const stopped = !!app.paused && app.open_tasks > 0;
    $('btnStop').hidden = !app.is_running || stopped;
    $('btnResume').hidden = !stopped;
    renderProjects(app);
    if (app.office_name && $('officeName').textContent !== app.office_name) {
        $('officeName').textContent = app.office_name;
        document.title = app.office_name;
    }
    const live = $('live');
    live.classList.toggle('busy', !!app.is_running && S.online);
    live.classList.toggle('paused', stopped && S.online);
    live.classList.toggle('offline', !S.online);
    $('liveText').textContent = !S.online ? 'Нет связи' : app.is_running ? 'Команда работает' : stopped ? 'Пауза' : 'Свободно';
}
