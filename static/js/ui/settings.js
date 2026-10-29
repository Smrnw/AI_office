// Окно настроек: папки, провайдеры, модели, агенты. Сохраняет всё одним запросом в config.json.
import { $, esc, toast } from '../util.js';
import { S } from '../store.js';
import * as api from '../api.js';
import { t as tr } from '../i18n.js';
import { portraitSVG, figureSVG, seatCount, SKIN, HAIR_STYLES, OUTFITS, ACCESSORIES } from '../office/index.js';
import { openModal, closeModal, showModalTab } from './modals.js';

const API_TYPES = [
    { v: 'openai_compatible', label: 'OpenAI-совместимый (OpenAI, OpenRouter, Ollama…)' },
    { v: 'anthropic', label: 'Anthropic Messages API' },
    { v: 'gemini', label: 'Google Gemini' },
    { v: 'demo', label: 'Демо (без ключа и сети)' },
];

const PROVIDER_TEMPLATES = [
    { id: 'gemini', name: 'Google Gemini', api_type: 'gemini', base_url: '' },
    { id: 'anthropic', name: 'Anthropic', api_type: 'anthropic', base_url: 'https://api.anthropic.com/v1/messages' },
    { id: 'openai', name: 'OpenAI', api_type: 'openai_compatible', base_url: 'https://api.openai.com/v1/chat/completions' },
    { id: 'openrouter', name: 'OpenRouter', api_type: 'openai_compatible', base_url: 'https://openrouter.ai/api/v1/chat/completions' },
    { id: 'ollama', name: 'Ollama (локально)', api_type: 'openai_compatible', base_url: 'http://localhost:11434/v1/chat/completions' },
    { id: 'demo', name: 'Демо', api_type: 'demo', base_url: '' },
];

// шаблоны промптов ролей приходят с сервера (config.role_defaults + правки config.role_prompts)
let roleDefaults = {}, rolePrompts = {};
const TYPE_KIND = { planner: 'planner', coder: 'developer', qa: 'qa' };
const kindOf = a => (a.specialty && roleDefaults[a.specialty]) ? a.specialty : (TYPE_KIND[a.pipeline_type] || 'developer');
const roleText = kind => rolePrompts[kind] || '';

let providers = [], models = [], agents = [];

const clone = v => JSON.parse(JSON.stringify(v || []));

function readDom() {
    const q = (root, sel) => root.querySelector(sel);
    providers = [...document.querySelectorAll('#providersEditor .edit-row')].map((r, i) => ({
        has_key: providers[i] ? !!providers[i].has_key : false,
        id: q(r, '.p-id').value.trim(),
        name: q(r, '.p-name').value.trim(),
        api_type: q(r, '.p-type').value,
        api_key: q(r, '.p-key').value.trim(),
        base_url: q(r, '.p-url').value.trim(),
    }));
    models = [...document.querySelectorAll('#modelsEditor .edit-row')].map(r => ({
        id: q(r, '.m-id').value.trim(),
        name: q(r, '.m-name').value.trim(),
        provider: q(r, '.m-prov').value,
        model_id: q(r, '.m-api').value.trim(),
        token_limit: parseInt(q(r, '.m-limit').value, 10) || 0,
    }));
    agents = [...document.querySelectorAll('#agentsEditor .agent-edit-card')].map(c => ({
        id: q(c, '.ag-id').value.trim(),
        tag: q(c, '.ag-tag').value.trim(),
        role: q(c, '.ag-role').value.trim(),
        pipeline_type: q(c, '.ag-type').value,
        model_ref: q(c, '.ag-model').value,
        desk_idx: parseInt(q(c, '.ag-desk').value, 10) || 0,
        shirt: q(c, '.ag-shirt').value,
        hair: q(c, '.ag-hair').value,
        pants: q(c, '.ag-pants').value,
        skin: parseInt(q(c, '.ag-skin').value, 10),
        hair_style: q(c, '.ag-hairstyle').value,
        outfit: q(c, '.ag-outfit').value,
        accessory: q(c, '.ag-accessory').value,
        prompt: q(c, '.ag-prompt').value.trim(),
        specialty: q(c, '.ag-spec').value,
        temp: q(c, '.ag-temp').checked,
    }));
}

function renderProviders() {
    $('providerTemplates').innerHTML = PROVIDER_TEMPLATES.map((t, i) =>
        '<button class="mini-btn" data-action="cfg-add-provider" data-tpl="' + i + '">+ ' + esc(t.name) + '</button>').join('') +
        '<button class="mini-btn" data-action="cfg-add-provider" data-tpl="-1">+ Свой</button>';
    $('providersEditor').innerHTML = providers.map((p, i) => {
        const types = API_TYPES.map(t => '<option value="' + t.v + '"' + (t.v === p.api_type ? ' selected' : '') + '>' + esc(t.label) + '</option>').join('');
        const keyState = p.api_type === 'demo' ? '' : p.has_key
            ? '<span class="key-state ok">● ключ сохранён</span>' : '<span class="key-state no">● ключа нет</span>';
        return '<div class="edit-row provider">' +
            '<div class="field-box"><label>ID</label><input class="std-input p-id" value="' + esc(p.id) + '" placeholder="openai"></div>' +
            '<div class="field-box"><label>Название</label><input class="std-input p-name" value="' + esc(p.name) + '"></div>' +
            '<div class="field-box"><label>Протокол API</label><select class="std-input p-type">' + types + '</select></div>' +
            '<div class="field-box"><label>API-ключ ' + keyState + '</label><div class="input-with-eye">' +
            '<input type="password" autocomplete="off" class="std-input p-key" value="' + esc(p.api_key) + '" placeholder="' + (p.has_key ? 'пусто — оставить сохранённый' : 'sk-…') + '">' +
            '<button class="btn btn-ghost" data-action="toggle-key" title="Показать ключ">👁</button></div></div>' +
            '<div class="field-box"><label>Base URL</label><input class="std-input p-url" value="' + esc(p.base_url) + '" placeholder="https://…/v1/chat/completions"></div>' +
            '<button class="btn btn-danger btn-del" data-action="cfg-del-provider" data-idx="' + i + '" title="Удалить">✕</button></div>';
    }).join('') || '<div class="empty-note">Нет провайдеров — добавьте шаблон выше.</div>';
}

function renderModels() {
    $('modelsEditor').innerHTML = models.map((m, i) => {
        const provs = providers.map(p => '<option value="' + esc(p.id) + '"' + (p.id === m.provider ? ' selected' : '') + '>' + esc(p.name || p.id) + '</option>').join('');
        return '<div class="edit-row model">' +
            '<div class="field-box"><label>ID</label><input class="std-input m-id" value="' + esc(m.id) + '" placeholder="gpt-main"></div>' +
            '<div class="field-box"><label>Название</label><input class="std-input m-name" value="' + esc(m.name) + '"></div>' +
            '<div class="field-box"><label>Провайдер</label><select class="std-input m-prov">' + provs + '</select></div>' +
            '<div class="field-box"><label>Model ID у провайдера</label><input class="std-input m-api" value="' + esc(m.model_id) + '" placeholder="gpt-4o-mini"></div>' +
            '<div class="field-box"><label>Лимит токенов</label><input type="number" min="0" step="1000" class="std-input m-limit" value="' + esc(m.token_limit || 1000000) + '"></div>' +
            '<button class="btn btn-danger btn-del" data-action="cfg-del-model" data-idx="' + i + '" title="Удалить">✕</button></div>';
    }).join('') || '<div class="empty-note">Нет моделей. Нажмите «+ Добавить модель».</div>';
}

const SPECIALTIES = {
    '': 'Нет — любые файлы',
    designer: 'Дизайн и вёрстка (HTML, CSS)',
    devops: 'DevOps (Docker, скрипты, CI)',
    writer: 'Документация (README, тексты)',
    security: 'Безопасность (для тестировщика)',
};

const opts = (map, cur) => Object.entries(map).map(([k, v]) => '<option value="' + k + '"' + (k === cur ? ' selected' : '') + '>' + esc(v) + '</option>').join('');

// внешность: превью в полный рост (обычный вид и за работой) и все настройки рядом
function lookEditor(a) {
    const skin = Number.isInteger(Number(a.skin)) ? Number(a.skin) : -1;
    const swatches = '<button class="skin-sw auto' + (skin < 0 ? ' on' : '') + '" data-action="cfg-skin" data-skin="-1" title="Авто">A</button>' +
        SKIN.map((c, k) => '<button class="skin-sw' + (skin === k ? ' on' : '') + '" data-action="cfg-skin" data-skin="' + k + '" style="background:' + c + '" title="Тон ' + (k + 1) + '"></button>').join('');
    return '<div class="look-box">' +
        '<div class="look-preview"><div class="look-fig">' + figureSVG(a) + '</div><div class="look-fig">' + figureSVG(a, true) + '</div>' +
        '<small>обычно · за работой</small></div>' +
        '<div class="look-fields">' +
        '<div class="field-box"><label>Причёска</label><select class="std-input ag-hairstyle" data-change="cfg-look">' + opts(HAIR_STYLES, a.hair_style || 'auto') + '</select></div>' +
        '<div class="field-box"><label>Одежда</label><select class="std-input ag-outfit" data-change="cfg-look">' + opts(OUTFITS, a.outfit || 'auto') + '</select></div>' +
        '<div class="field-box"><label>Аксессуары</label><select class="std-input ag-accessory" data-change="cfg-look">' + opts(ACCESSORIES, a.accessory || 'auto') + '</select></div>' +
        '<div class="field-box"><label>Цвета</label><div class="color-pair-box">' +
        '<label class="color-item"><input type="color" class="ag-shirt" data-change="cfg-look" value="' + esc(a.shirt || '#3b82f6') + '"> Верх</label>' +
        '<label class="color-item"><input type="color" class="ag-pants" data-change="cfg-look" value="' + esc(a.pants || '#2d3340') + '"> Низ</label>' +
        '<label class="color-item"><input type="color" class="ag-hair" data-change="cfg-look" value="' + esc(a.hair || '#f1f5f9') + '"> Волосы</label></div></div>' +
        '<div class="field-box span-all"><label>Тон кожи</label><div class="skin-row">' + swatches + '<input type="hidden" class="ag-skin" value="' + skin + '"></div></div>' +
        '</div></div>';
}

function renderAgentsEditor() {
    $('agentsEditor').innerHTML = agents.map((a, i) => {
        const mods = models.map(m => '<option value="' + esc(m.id) + '"' + (m.id === a.model_ref ? ' selected' : '') + '>' + esc(m.name) + ' (' + esc(m.provider) + ')</option>').join('');
        // число мест берём из планировки офиса
        const desks = Array.from({ length: Math.max(1, seatCount(), Number(a.desk_idx) + 1) }, (_, d) => d).map(d => '<option value="' + d + '"' + (Number(a.desk_idx) === d ? ' selected' : '') + '>Место #' + (d + 1) + '</option>').join('');
        const type = v => (a.pipeline_type === v ? ' selected' : '');
        return '<div class="agent-edit-card">' +
            '<div class="agent-card-header"><div class="agent-card-badge"><div class="avatar">' + portraitSVG(a) + '</div>' +
            '<span>' + esc(a.id) + '</span><small>' + esc(a.role) + '</small></div>' +
            '<button class="btn btn-danger" data-action="cfg-del-agent" data-idx="' + i + '">🗑 Уволить</button></div>' +
            '<div class="agent-fields-grid">' +
            '<div class="field-box"><label>Имя (ID)</label><input class="std-input ag-id" value="' + esc(a.id) + '" maxlength="40"></div>' +
            '<div class="field-box"><label>Бейдж</label><input class="std-input ag-tag" value="' + esc(a.tag) + '" maxlength="40"></div>' +
            '<div class="field-box"><label>Должность</label><input class="std-input ag-role" value="' + esc(a.role) + '" maxlength="60"></div>' +
            '<div class="field-box"><label>Роль в работе</label><select class="std-input ag-type" data-change="cfg-type" data-idx="' + i + '">' +
            '<option value="planner"' + type('planner') + '>Planner — руководитель</option>' +
            '<option value="coder"' + type('coder') + '>Coder — разработчик</option>' +
            '<option value="qa"' + type('qa') + '>QA — тестировщик</option></select></div>' +
            '<div class="field-box span-2"><label>Нейросеть</label><select class="std-input ag-model">' + mods + '</select></div>' +
            '<div class="field-box"><label>Место в офисе</label><select class="std-input ag-desk">' + desks + '</select></div>' +
            '<div class="field-box span-2"><label>Специализация</label><select class="std-input ag-spec">' + opts(SPECIALTIES, a.specialty || '') + '</select></div>' +
            '<label class="field-box temp-box"><span><input type="checkbox" class="ag-temp"' + (a.temp ? ' checked' : '') + '> Временный</span>' +
            '<small>уйдёт, когда работа закончится</small></label>' +
            '</div>' + lookEditor(a) +
            '<div><div class="ag-prompt-label">Системный промпт</div>' +
            '<textarea class="std-input ag-prompt" maxlength="20000" placeholder="' + esc(roleText(kindOf(a))
                ? tr('Пусто — работает по промпту роли') + ' «' + tr(((roleDefaults[kindOf(a)] || {}).title) || '') + '»: ' + roleText(kindOf(a))
                : tr('Напишите промпт агенту или его роли во вкладке «Роли и промпты» — без него сохранить нельзя')) + '">' + esc(a.prompt) + '</textarea></div></div>';
    }).join('') || '<div class="empty-note">Нет агентов. Нажмите «+ Нанять агента».</div>';
}

function renderAll() {
    renderProviders();
    renderModels();
    renderAgentsEditor();
}

export function openSettings(tab = 'tab-general') {
    const cfg = S.app && S.app.config;
    if (!cfg) return;
    $('cfgMsg').textContent = '';
    $('cfgMsg').classList.remove('err');
    $('cfgPath').textContent = S.app.config_path;
    $('cfgWorkspace').value = cfg.workspace_dir || '';
    $('cfgTasks').value = cfg.tasks_dir || '';
    fillChecks(cfg.checks || {});
    roleDefaults = cfg.role_defaults || {};
    rolePrompts = { ...(cfg.role_prompts || {}) };
    renderRoles();
    const ap = cfg.autopilot || {};
    $('apCycles').value = ap.max_cycles ?? 5;
    $('apTasks').value = ap.max_tasks ?? 4;
    $('apTokens').value = ap.max_tokens ?? 500000;
    $('apMinutes').value = ap.max_minutes ?? 90;
    const st = cfg.staffing || {};
    $('stAutoHire').checked = st.auto_hire !== false;
    $('stDismiss').checked = st.dismiss_temps !== false;
    $('stDesks').checked = st.auto_desks !== false;
    $('stMax').value = st.max_agents ?? 8;
    fillNotify(cfg.notify || {}, cfg.git || {});
    providers = clone(cfg.providers);
    models = clone(cfg.models);
    agents = clone(cfg.agents);
    renderAll();
    showModalTab('settingsModal', tab);
    openModal('settingsModal');
}

/* ---------- роли и промпты ---------- */

function renderRoles() {
    const typeName = { planner: 'Planner — руководитель', coder: 'Coder — разработчик', qa: 'QA — тестировщик' };
    $('rolesEditor').innerHTML = Object.entries(roleDefaults).map(([kind, r]) =>
        '<div class="role-card" data-kind="' + esc(kind) + '">' +
        '<div class="role-head"><b>' + esc(r.title) + '</b><small>' + esc(typeName[r.type] || r.type) + '</small>' +
        (rolePrompts[kind] ? '' : '<span class="role-custom empty">' + esc(tr('не написан')) + '</span>') + '</div>' +
        '<textarea class="std-input role-prompt" maxlength="20000" placeholder="' +
        esc(tr('Опишите роль своими словами: кто это, за что отвечает, как работает и на что обращает внимание')) + '">' +
        esc(roleText(kind)) + '</textarea></div>').join('');
}

function readRoles() {
    const out = {};
    document.querySelectorAll('#rolesEditor .role-card').forEach(c => {
        const text = c.querySelector('.role-prompt').value.trim();
        if (text) out[c.dataset.kind] = text;
    });
    rolePrompts = out;
    return out;
}

/* ---------- автопроверка ---------- */

const CHECK_BOXES = {
    enabled: 'chkEnabled', tests: 'chkTests', write_tests: 'chkWriteTests',
    browser: 'chkBrowser', vision: 'chkVision', security: 'chkSecurity'
};

function fillChecks(c) {
    Object.entries(CHECK_BOXES).forEach(([k, id]) => { $(id).checked = c[k] !== false; });
    $('chkRounds').value = c.auto_fix_rounds ?? 2;
    $('chkSandbox').value = c.sandbox || 'auto';
    $('chkStatus').textContent = '';
    // что из инструментов проверки есть на этом компьютере
    api.get('/api/checks').then(d => {
        const mark = (ok, yes, no) => '<span class="' + (ok ? 'ok' : 'off') + '">' + (ok ? '✅ ' + yes : '⚪ ' + no) + '</span>';
        $('chkStatus').innerHTML =
            mark(d.browser, 'Браузер для проверки установлен', 'Playwright не установлен — проверка в браузере пропускается') +
            mark(d.docker, 'Docker запущен — тесты идут в контейнере без сети', 'Docker не запущен — тесты идут без Docker') +
            mark(d.bandit, 'bandit установлен', 'bandit не установлен — только встроенные правила безопасности');
    }).catch(() => {});
}

function readChecks() {
    const out = {};
    Object.entries(CHECK_BOXES).forEach(([k, id]) => { out[k] = $(id).checked; });
    out.auto_fix_rounds = Math.max(0, Math.min(5, parseInt($('chkRounds').value, 10) || 0));
    out.sandbox = $('chkSandbox').value;
    return out;
}

function uniqueId(base, list) {
    let id = base, n = 2;
    while (list.some(x => x.id === id)) id = base + '_' + n++;
    return id;
}

export const settingsActions = {
    'cfg-add-provider': el => {
        readDom();
        const tpl = PROVIDER_TEMPLATES[Number(el.dataset.tpl)] || { id: 'custom', name: 'Свой провайдер', api_type: 'openai_compatible', base_url: '' };
        providers.push({ ...tpl, id: uniqueId(tpl.id, providers), api_key: '', has_key: false });
        renderAll();
    },
    'cfg-del-provider': el => { readDom(); providers.splice(Number(el.dataset.idx), 1); renderAll(); },
    'cfg-add-model': () => {
        readDom();
        models.push({ id: uniqueId('model', models), name: 'Новая модель', provider: (providers[0] || {}).id || '', model_id: '', token_limit: 1000000 });
        renderAll();
        showModalTab('settingsModal', 'tab-models');
    },
    'cfg-del-model': el => { readDom(); models.splice(Number(el.dataset.idx), 1); renderAll(); },
    'cfg-add-agent': () => {
        readDom();
        const palette = ['#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#06b6d4', '#ef4444', '#84cc16'];
        let n = agents.length + 1;
        while (agents.some(a => a.id === 'Agent_' + n)) n++;
        const used = new Set(agents.map(a => Number(a.desk_idx)));
        const seats = Math.max(1, seatCount());
        const desk = Array.from({ length: seats }, (_, d) => d).find(d => !used.has(d)) ?? (n - 1) % seats;
        agents.push({
            id: 'Agent_' + n, tag: 'dev', role: 'Разработчик', pipeline_type: 'coder',
            model_ref: (models[0] || {}).id || '', desk_idx: desk, shirt: palette[n % palette.length], hair: '#f1f5f9',
            prompt: '',
        });
        renderAll();
        showModalTab('settingsModal', 'tab-agents');
    },
    'cfg-del-agent': el => { readDom(); agents.splice(Number(el.dataset.idx), 1); renderAll(); },
    'cfg-skin': el => {
        const row = el.closest('.skin-row');
        row.querySelector('.ag-skin').value = el.dataset.skin;
        row.querySelectorAll('.skin-sw').forEach(b => b.classList.toggle('on', b === el));
        onLookChange(el);
    },
    'toggle-key': el => {
        const inp = el.parentElement.querySelector('input');
        inp.type = inp.type === 'password' ? 'text' : 'password';
    },
    'cfg-save': saveSettings,
    'notify-test': testNotify,
};

// перерисовать превью внешности в карточке агента после любой правки
export function onLookChange(el) {
    const card = el.closest('.agent-edit-card');
    if (!card) return;
    readDom();
    const a = agents[[...document.querySelectorAll('#agentsEditor .agent-edit-card')].indexOf(card)];
    if (!a) return;
    const figs = card.querySelectorAll('.look-fig');
    figs[0].innerHTML = figureSVG(a);
    figs[1].innerHTML = figureSVG(a, true);
    card.querySelector('.agent-card-badge .avatar').innerHTML = portraitSVG(a);
}

// смена роли подставляет типовой промпт, если пользователь его ещё не правил
export function onAgentTypeChange(el) {
    const card = el.closest('.agent-edit-card');
    const prompt = card.querySelector('.ag-prompt');
    // промпт, совпадающий с шаблоном какой-то роли, очищаем: пустой промпт и так берёт шаблон новой роли
    const known = Object.keys(roleDefaults).map(roleText);
    if (known.includes(prompt.value.trim())) prompt.value = '';
    readDom();
    renderAgentsEditor();
}

/* ---------- уведомления и Git ---------- */

function fillNotify(n, git) {
    const tg = n.telegram || {}, em = n.email || {}, ev = n.events || {};
    $('ntTgOn').checked = !!tg.enabled;
    $('ntTgReplies').checked = tg.replies !== false;
    $('ntTgToken').value = '';
    $('ntTgToken').placeholder = tg.has_token ? 'пусто — оставить сохранённый' : '123456:ABC…';
    $('ntTgTokenState').textContent = tg.has_token ? '● сохранён' : '';
    $('ntTgChat').value = tg.chat_id || '';
    $('ntEmOn').checked = !!em.enabled;
    $('ntEmHost').value = em.host || '';
    $('ntEmPort').value = em.port || 587;
    $('ntEmSec').value = em.security || 'starttls';
    $('ntEmUser').value = em.username || '';
    $('ntEmPass').value = '';
    $('ntEmPass').placeholder = em.has_password ? 'пусто — оставить сохранённый' : '';
    $('ntEmPassState').textContent = em.has_password ? '● сохранён' : '';
    $('ntEmFrom').value = em.sender || '';
    $('ntEmTo').value = em.to || '';
    $('ntEvDone').checked = ev.project_done !== false;
    $('ntEvAuto').checked = ev.autopilot !== false;
    $('ntEvErr').checked = ev.errors !== false;
    $('ntEvQ').checked = ev.questions !== false;
    $('gitOn').checked = git.enabled !== false;
}

function readNotify() {
    return {
        telegram: { enabled: $('ntTgOn').checked, replies: $('ntTgReplies').checked, token: $('ntTgToken').value.trim(), chat_id: $('ntTgChat').value.trim() },
        email: {
            enabled: $('ntEmOn').checked, host: $('ntEmHost').value.trim(), port: parseInt($('ntEmPort').value, 10) || 587,
            security: $('ntEmSec').value, username: $('ntEmUser').value.trim(), password: $('ntEmPass').value,
            sender: $('ntEmFrom').value.trim(), to: $('ntEmTo').value.trim(),
        },
        events: { project_done: $('ntEvDone').checked, autopilot: $('ntEvAuto').checked, errors: $('ntEvErr').checked, questions: $('ntEvQ').checked },
    };
}

// «Проверить»: сначала сохраняем то, что введено, затем шлём проверочное сообщение
async function testNotify(el) {
    try {
        await api.post('/api/config', buildPayload());
        const d = await api.post('/api/notify/test', { channel: el.dataset.channel });
        if (d.ok) toast('Проверочное сообщение отправлено');
        else toast(d.error || 'Не получилось', 'err');
    } catch (e) {
        toast(e.message, 'err');
    }
}

function buildPayload() {
    readDom();
    return {
        workspace_dir: $('cfgWorkspace').value.trim(),
        tasks_dir: $('cfgTasks').value.trim(),
        providers: providers.map(({ has_key, ...p }) => p),
        models, agents,
        checks: readChecks(),
        autopilot: {
            max_cycles: parseInt($('apCycles').value, 10) || 5,
            max_tasks: parseInt($('apTasks').value, 10) || 4,
            max_tokens: parseInt($('apTokens').value, 10) || 500000,
            max_minutes: parseInt($('apMinutes').value, 10) || 90,
        },
        staffing: {
            auto_hire: $('stAutoHire').checked,
            dismiss_temps: $('stDismiss').checked,
            auto_desks: $('stDesks').checked,
            max_agents: parseInt($('stMax').value, 10) || 8,
        },
        notify: readNotify(),
        role_prompts: readRoles(),
        git: { enabled: $('gitOn').checked },
    };
}

async function saveSettings() {
    const payload = buildPayload();
    try {
        await api.post('/api/config', payload);
    } catch (e) {
        $('cfgMsg').classList.add('err');
        $('cfgMsg').textContent = '⚠️ ' + e.message;
        return;
    }
    $('cfgMsg').classList.remove('err');
    $('cfgMsg').textContent = '✅ Сохранено';
    toast('Настройки сохранены');
    setTimeout(() => closeModal('settingsModal'), 300);
    document.dispatchEvent(new CustomEvent('office:refresh'));
}
