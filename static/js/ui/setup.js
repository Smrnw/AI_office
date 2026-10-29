// Мастер первоначальной настройки: офис, нейросеть, папки, команда с промптами, автоматизация.
// Открывается сам, когда офис новый (штата нет), и из меню ☰ → «Мастер настройки».
import { $, esc, toast } from '../util.js';
import * as api from '../api.js';
import { t as tr, LANG, rememberLang } from '../i18n.js';
import { openModal, closeModal } from './modals.js';
import { openLayoutEditor } from '../office/index.js';

const STEPS = ['Офис', 'Нейросеть', 'Папки', 'Команда', 'Готово'];
const TEAM_DEFAULT = { developer: 1, qa: 1, designer: 0, devops: 0, writer: 0, security: 0 };

let info = null;
let step = 0;
let answers = null;

function fresh() {
    return {
        office_name: info.office_name || 'AI Office', language: info.language || LANG,
        provider: { template: 'demo', api_key: '', base_url: '', model_id: '' },
        workspace_dir: '', tasks_dir: '',
        team: { ...TEAM_DEFAULT },
        role_prompts: { ...(info.role_prompts || {}) },
        options: { checks: true, auto_hire: true },
    };
}

export async function openSetup() {
    try {
        info = await api.get('/api/setup');
    } catch (e) { toast(e.message, 'err'); return; }
    answers = fresh();
    step = 0;
    missingShown = false;
    render();
    openModal('setupModal');
}

/* ---------- шаги ---------- */

function stepOffice() {
    const lang = l => '<label class="radio-pill"><input type="radio" name="suLang" value="' + l + '"' + (answers.language === l ? ' checked' : '') + '> ' + (l === 'ru' ? 'Русский' : 'English') + '</label>';
    return '<p class="su-lead">Несколько вопросов — и офис готов к работе. Всё можно поменять позже в Настройках.</p>' +
        '<div class="field-box"><label for="suName">🏢 Как назовём офис?</label><input id="suName" class="std-input" maxlength="60" value="' + esc(answers.office_name) + '"></div>' +
        '<div class="field-box"><label>🌐 Язык интерфейса и агентов</label><div class="radio-row">' + lang('ru') + lang('en') + '</div></div>';
}

function stepModel() {
    const p = answers.provider;
    const hint = info.hints[p.template] || {};
    const needsKey = !['demo', 'ollama'].includes(p.template);
    const needsUrl = ['custom', 'ollama', 'openai', 'openrouter'].includes(p.template);
    return '<p class="su-lead">На какой нейросети будут работать агенты. Демо отвечает заготовками без ключа — удобно, чтобы осмотреться.</p>' +
        '<div class="field-box"><label for="suProv">🤖 Провайдер</label><select id="suProv" class="std-input" data-change="su-provider">' +
        info.providers.map(x => '<option value="' + esc(x.id) + '"' + (x.id === p.template ? ' selected' : '') + '>' + esc(x.name) + '</option>').join('') + '</select></div>' +
        (p.template === 'demo' ? '' :
            (needsKey ? '<div class="field-box"><label for="suKey">🔑 API-ключ</label><input id="suKey" class="std-input" type="password" autocomplete="off" value="' + esc(p.api_key) + '"></div>' : '') +
            (needsUrl ? '<div class="field-box"><label for="suUrl">🔗 Адрес API (Base URL)</label><input id="suUrl" class="std-input" placeholder="' + esc(hint.base_url || 'https://…/v1/chat/completions') + '" value="' + esc(p.base_url) + '"></div>' : '') +
            '<div class="field-box"><label for="suModel">🧠 ID модели</label><input id="suModel" class="std-input" placeholder="' + esc(hint.model_id || '') + '" value="' + esc(p.model_id) + '">' +
            '<small class="su-note">Пример: ' + esc(hint.model_id || '—') + '. Точное название смотрите у провайдера.</small></div>') +
        '<div class="su-test"><button class="btn btn-ghost" data-action="su-test">⚡ Проверить связь</button><span id="suTestMsg"></span></div>';
}

function stepDirs() {
    return '<p class="su-lead">Где хранить код проектов и задачи. Пусто — внутри папки данных офиса, это подходит почти всем.</p>' +
        '<div class="field-box"><label for="suWs">📂 Рабочая папка кода</label><input id="suWs" class="std-input" placeholder="' + esc(info.default_dirs.workspace) + '" value="' + esc(answers.workspace_dir) + '"></div>' +
        '<div class="field-box"><label for="suTasks">📋 Папка задач</label><input id="suTasks" class="std-input" placeholder="' + esc(info.default_dirs.tasks) + '" value="' + esc(answers.tasks_dir) + '"></div>' +
        '<small class="su-note">Если указываете свою папку — полный путь, например D:/Projects/workspace.</small>';
}

function stepTeam() {
    const roles = info.roles;
    // промпт пишет сам пользователь: поле видно, только когда роль кого-то нанимает
    const row = kind => {
        const r = roles[kind];
        const fixed = kind === 'planner';
        const count = fixed ? 1 : answers.team[kind];
        const prompt = answers.role_prompts[kind] || '';
        const missing = count > 0 && !prompt.trim() && missingShown;
        return '<div class="su-role' + (missing ? ' missing' : '') + '">' +
            '<div class="su-role-head"><b>' + esc(r.title) + '</b>' +
            (fixed ? '<span class="su-count">1</span>'
                : '<input class="std-input su-count-in" type="number" min="0" max="6" data-kind="' + esc(kind) + '" data-change="su-count" value="' + count + '">') +
            '</div>' +
            (count > 0 ? '<textarea class="std-input su-prompt" data-kind="' + esc(kind) + '" maxlength="20000" placeholder="' +
                esc(tr('Опишите роль своими словами: кто это, за что отвечает, как работает и на что обращает внимание')) + '">' + esc(prompt) + '</textarea>' : '') +
            '</div>';
    };
    return '<p class="su-lead">Кого нанять и как им работать. Для каждой роли, на которую вы кого-то берёте, напишите системный промпт — готовых нет. Руководитель планирует и раздаёт задачи, разработчики пишут код, тестировщики проверяют; специалисты берут свои файлы: дизайнер — HTML и CSS, DevOps — Docker и скрипты, писатель — документацию.</p>' +
        Object.keys(roles).map(row).join('') +
        (missingShown && missingRoles().length ? '<div class="su-error">' + esc(tr('Напишите промпт для ролей')) + ': ' + esc(missingRoles().map(k => tr(roles[k].title)).join(', ')) + '</div>' : '');
}

function stepDone() {
    const team = (1 + Object.values(answers.team).reduce((a, b) => a + Number(b || 0), 0)) + ' ' + tr('сотрудников');
    const prov = (info.providers.find(p => p.id === answers.provider.template) || {}).name || '';
    return '<p class="su-lead">Почти всё. Последние настройки — их тоже можно поменять потом.</p>' +
        '<div class="chk-list">' +
        '<label class="chk-row"><input type="checkbox" id="suChecks"' + (answers.options.checks ? ' checked' : '') + '><span><b>Проверять проекты автоматически</b><small>Тестировщик запускает тесты, открывает страницы в браузере и ищет уязвимости</small></span></label>' +
        '<label class="chk-row"><input type="checkbox" id="suHire"' + (answers.options.auto_hire ? ' checked' : '') + '><span><b>Нанимать людей под нагрузку</b><small>Когда задач много, руководитель сам берёт временных сотрудников</small></span></label>' +
        '</div>' +
        '<ul class="su-summary"><li>🏢 <span data-raw>' + esc(answers.office_name || 'AI Office') + '</span></li><li>🤖 ' + esc(prov) +
        (answers.provider.model_id ? ' · <span data-raw>' + esc(answers.provider.model_id) + '</span>' : '') + '</li><li>👥 ' + esc(team) + '</li>' +
        '<li>📂 <span data-raw>' + esc(answers.workspace_dir || info.default_dirs.workspace) + '</span></li></ul>';
}

const RENDER = [stepOffice, stepModel, stepDirs, stepTeam, stepDone];
const TEAM_STEP = 3;
let missingShown = false;

// роли, на которые кого-то нанимают, но промпт не написан (руководитель есть всегда)
function missingRoles() {
    return Object.keys(info.roles).filter(k =>
        (k === 'planner' || Number(answers.team[k] || 0) > 0) && !(answers.role_prompts[k] || '').trim());
}

function render() {
    $('setupSteps').innerHTML = STEPS.map((s, i) =>
        '<span class="su-step' + (i === step ? ' on' : i < step ? ' done' : '') + '">' + (i + 1) + '. ' + esc(s) + '</span>').join('');
    $('setupBody').innerHTML = RENDER[step]();
    $('setupBack').hidden = step === 0;
    $('setupNext').hidden = step === STEPS.length - 1;
    $('setupFinish').hidden = step !== STEPS.length - 1;
}

/* ---------- чтение полей текущего шага ---------- */

function read() {
    const v = id => ($(id) ? $(id).value.trim() : null);
    if (step === 0) {
        answers.office_name = v('suName') || 'AI Office';
        const lang = document.querySelector('input[name="suLang"]:checked');
        if (lang) answers.language = lang.value;
    } else if (step === 1) {
        const p = answers.provider;
        p.template = v('suProv') || p.template;
        if ($('suKey')) p.api_key = v('suKey');
        if ($('suUrl')) p.base_url = v('suUrl');
        if ($('suModel')) p.model_id = v('suModel');
    } else if (step === 2) {
        answers.workspace_dir = v('suWs');
        answers.tasks_dir = v('suTasks');
    } else if (step === 3) {
        document.querySelectorAll('.su-count-in').forEach(el => {
            answers.team[el.dataset.kind] = Math.max(0, Math.min(6, parseInt(el.value, 10) || 0));
        });
        document.querySelectorAll('.su-prompt').forEach(el => {
            const text = el.value.trim();
            if (text) answers.role_prompts[el.dataset.kind] = text;
            else delete answers.role_prompts[el.dataset.kind];
        });
    } else if (step === 4) {
        answers.options.checks = $('suChecks').checked;
        answers.options.auto_hire = $('suHire').checked;
    }
}

async function finish() {
    read();
    $('setupFinish').disabled = true;
    try {
        await api.post('/api/setup', answers);
    } catch (e) {
        toast(e.message, 'err');
        $('setupFinish').disabled = false;
        return;
    }
    $('setupFinish').disabled = false;
    closeModal('setupModal');
    if (answers.language !== LANG) {
        rememberLang(answers.language);
        location.reload();
        return;
    }
    document.dispatchEvent(new CustomEvent('office:refresh'));
    // офис пока пустой: сразу открываем планировку, чтобы расставить столы для команды
    const seats = Object.values(answers.team).reduce((a, b) => a + Number(b || 0), 0);
    setTimeout(() => openLayoutEditor(), 600);
    toast(tr('Команда нанята. Теперь обставьте офис') + ': ' + seats + ' ' + tr('рабочих мест, зоны и мебель'), 'info');
}

export const setupActions = {
    'setup-next': () => {
        read();
        if (step === TEAM_STEP && missingRoles().length) {
            missingShown = true;               // без промптов дальше нельзя: подсвечиваем пустые поля
            render();
            const first = document.querySelector('.su-prompt:placeholder-shown');
            if (first) first.focus();
            return;
        }
        step = Math.min(STEPS.length - 1, step + 1);
        render();
    },
    'setup-back': () => { read(); step = Math.max(0, step - 1); render(); },
    'setup-finish': () => finish(),
    'su-test': async () => {
        read();
        const msg = $('suTestMsg');
        msg.className = '';
        msg.textContent = tr('Проверяю…');
        try {
            const d = await api.post('/api/setup/test', answers.provider);
            msg.className = d.ok ? 'ok' : 'err';
            msg.textContent = d.ok ? '✅ ' + tr('Нейросеть ответила') + ': ' + d.reply : '⚠️ ' + d.error;
        } catch (e) {
            msg.className = 'err';
            msg.textContent = '⚠️ ' + e.message;
        }
    },
};

export const setupChanges = {
    // число сотрудников роли поменялось: показать или спрятать поле её промпта
    'su-count': () => { read(); render(); },
    'su-provider': el => {
        read();
        answers.provider = { template: el.value, api_key: '', base_url: '', model_id: (info.hints[el.value] || {}).model_id || '' };
        render();
    },
};
