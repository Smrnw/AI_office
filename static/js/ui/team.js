// Левая колонка: карточки агентов и файлы рабочей папки.
import { $, esc, fmtSize, fileExt, setHTML } from '../util.js';
import { S, STATUS_BUSY, STATUS_ERROR } from '../store.js';
import { portraitSVG, seatLabel } from '../office/index.js';

const TYPE_LABEL = { planner: 'Руководитель', coder: 'Разработчик', qa: 'Тестировщик' };

export function renderAgents() {
    const app = S.app;
    const entries = Object.entries(app.agents || {});
    $('agentsCount').textContent = entries.length ? '(' + entries.length + ')' : '';
    const models = app.models || [];
    const html = entries.map(([id, a]) => {
        const busy = a.status === STATUS_BUSY || a.status === 'Идёт', err = a.status === STATUS_ERROR;
        const opts = models.map(m =>
            '<option value="' + esc(m.id) + '"' + (m.id === a.model_ref ? ' selected' : '') + '>' + esc(m.name) + '</option>').join('');
        const stateCls = busy ? 'busy' : err ? 'err' : 'free';
        return '<div class="agent-card' + (busy ? ' working' : '') + (err ? ' error' : '') + (id === S.chatChannel ? ' chosen' : '') +
            '" data-action="open-chat" data-ch="' + esc(id) + '" title="Написать ' + esc(id) + '">' +
            '<div class="avatar">' + portraitSVG(a) + '</div>' +
            '<div class="agent-name">' + esc(id) + (a.temp ? ' <span class="temp-badge" title="Нанят на время работы: уйдёт, когда работа закончится">врем.</span>' : '') + '</div>' +
            '<button class="icon-btn sm" data-action="settings" data-tab="tab-agents" title="Настройки агента">⋮</button>' +
            '<div class="agent-role">' + esc(a.role || TYPE_LABEL[a.pipeline_type] || '') + ' • ' + esc(seatLabel(id)) + '</div>' +
            '<div class="agent-state ' + stateCls + '">' + (busy ? '<i class="spin"></i>' : '') + esc(a.status) +
            (busy || err ? '<span class="act" title="' + esc(a.action) + '">· ' + esc(a.action) + '</span>' : '') + '</div>' +
            '<select class="model-pill" data-change="agent-model" data-agent="' + esc(id) + '" title="Нейросеть агента">' + opts + '</select>' +
            '</div>';
    }).join('') || '<div class="empty-note">Агентов нет.<br><button class="mini-btn" data-action="settings" data-tab="tab-agents">Нанять сотрудников</button></div>';
    // не трогаем DOM, пока пользователь выбирает модель в выпадашке, иначе список схлопнется
    if (document.activeElement && document.activeElement.classList.contains('model-pill')) return;
    setHTML('agentsList', html);
}

let filesFilter = '';
export function setFilesFilter(value) {
    filesFilter = value.trim().toLowerCase();
    renderFiles();
}

/* ---------- дерево файлов: папки сворачиваются, папка текущего проекта открыта ---------- */

const expanded = new Set();
const collapsed = new Set();

export function toggleDir(path) {
    if (isOpen(path)) { expanded.delete(path); collapsed.add(path); } else { collapsed.delete(path); expanded.add(path); }
    renderFiles();
}

function isOpen(path) {
    if (collapsed.has(path)) return false;
    if (expanded.has(path)) return true;
    const proj = (S.app && S.app.project_dir) || '';
    return !!proj && (proj === path || proj.startsWith(path + '/'));      // по умолчанию открыт текущий проект
}

function buildTree(files, dirs) {
    const root = { name: '', path: '', dirs: new Map(), files: [] };
    const dirNode = path => {
        let node = root, acc = '';
        for (const part of path.split('/')) {
            acc = acc ? acc + '/' + part : part;
            if (!node.dirs.has(part)) node.dirs.set(part, { name: part, path: acc, dirs: new Map(), files: [] });
            node = node.dirs.get(part);
        }
        return node;
    };
    dirs.forEach(d => dirNode(d));
    files.forEach(f => {
        const slash = f.name.lastIndexOf('/');
        (slash > 0 ? dirNode(f.name.slice(0, slash)) : root).files.push(f);
    });
    return root;
}

function countFiles(node) {
    let n = node.files.length;
    node.dirs.forEach(d => { n += countFiles(d); });
    return n;
}

function renderNode(node, depth, rows, now, forceOpen) {
    const pad = 'padding-left:' + (8 + depth * 14) + 'px';
    [...node.dirs.values()].sort((a, b) => a.name.localeCompare(b.name)).forEach(d => {
        const open = forceOpen || isOpen(d.path);
        const isProject = S.app.project_dir === d.path;
        rows.push('<div class="folder-row' + (isProject ? ' current' : '') + '" style="' + pad + '" data-action="toggle-dir" data-dir="' + esc(d.path) + '" title="' + esc(d.path) + '/">' +
            '<span class="chev">' + (open ? '▾' : '▸') + '</span><span class="folder-ico">' + (open ? '📂' : '📁') + '</span>' +
            '<span class="file-name">' + esc(d.name) + '</span>' +
            (isProject ? '<span class="proj-badge">проект</span>'
                : depth === 0 ? '<button class="proj-open" data-action="select-project" data-dir="' + esc(d.path) + '" title="Сделать текущим проектом">открыть</button>' : '') +
            '<span class="file-size">' + countFiles(d) + '</span></div>');
        if (open) renderNode(d, depth + 1, rows, now, forceOpen);
    });
    node.files.forEach(f => {
        const ext = fileExt(f.name);
        const fresh = now - (f.mtime_ts || 0) < 20;
        rows.push('<div class="file-row' + (fresh ? ' fresh' : '') + '" style="' + pad + '" data-action="open-file" data-file="' + esc(f.name) + '" title="' + esc(f.name) + ' • изменён в ' + esc(f.mtime) + '">' +
            '<span class="file-ico ' + esc(ext) + '">' + esc(ext.slice(0, 4)) + '</span>' +
            '<span class="file-name">' + esc(f.name.split('/').pop()) + '</span>' +
            '<span class="file-size">' + fmtSize(f.size) + '</span></div>');
    });
}

export function renderFiles() {
    const app = S.app;
    if (!app) return;
    const all = app.files || [];
    const files = all.filter(f => !filesFilter || f.name.toLowerCase().includes(filesFilter));
    const dirs = filesFilter ? [] : (app.dirs || []);
    $('filesCount').textContent = all.length + ' шт.';
    const rows = [];
    // при поиске показываем найденное вместе с путём, все папки раскрыты
    renderNode(buildTree(files, dirs), 0, rows, app.server_time || Date.now() / 1000, !!filesFilter);
    setHTML('filesBox', rows.join('') || '<div class="empty-note">' + (filesFilter ? 'Ничего не найдено' : 'Файлов пока нет.<br>Каждый новый проект агенты создают в своей папке.') + '</div>');
}
