// Окна: общая механика, карточка задачи, просмотр файла.
import { $, toast, copyText, fileExt } from '../util.js';
import { S } from '../store.js';
import * as api from '../api.js';
import { t as tr } from '../i18n.js';

/* ---------- общая механика ---------- */

let lastFocus = null;

export function openModal(id) {
    lastFocus = document.activeElement;
    $(id).classList.add('active');
}

export function closeModal(id) {
    const el = id ? $(id) : document.querySelector('.modal-backdrop.active:last-of-type');
    if (el) el.classList.remove('active');
    if (lastFocus && lastFocus.focus) lastFocus.focus();
}

export function closeAllModals() {
    document.querySelectorAll('.modal-backdrop.active').forEach(m => m.classList.remove('active'));
}

export function anyModalOpen() {
    return !!document.querySelector('.modal-backdrop.active');
}

// вкладки внутри окна: кнопка .mtab[data-target] показывает блок с таким id
export function switchModalTab(btn) {
    const box = btn.closest('.modal-box');
    box.querySelectorAll('.mtab').forEach(b => b.classList.toggle('active', b === btn));
    box.querySelectorAll('.mtab-content').forEach(c => c.classList.toggle('active', c.id === btn.dataset.target));
}

export function showModalTab(modalId, target) {
    const btn = $(modalId).querySelector('.mtab[data-target="' + target + '"]');
    if (btn) switchModalTab(btn);
}

const refresh = () => document.dispatchEvent(new CustomEvent('office:refresh'));

/* ---------- карточка задачи ---------- */

const task = { file: '', status: '', code: '', codeLoaded: '' };

export async function openTask(taskFile, status) {
    let data;
    try {
        data = await api.get('/api/task-file?task_file=' + encodeURIComponent(taskFile) + '&status=' + encodeURIComponent(status || ''));
    } catch (e) {
        toast('Не удалось открыть задачу: ' + e.message, 'err');
        return;
    }
    const t = data.task;
    task.file = t.task_file;
    task.status = t.status;
    task.code = t.filename;
    task.codeLoaded = data.code_exists ? data.code_content : '';
    $('taskTitle').textContent = '📌 #' + t.id + ': ' + t.title;
    $('taskPath').textContent = data.task_path;
    $('taskStatus').value = t.status;
    $('taskRaw').value = t.raw_content;
    $('taskComment').value = '';
    $('taskMsg').textContent = data.busy ? '⏳ Над задачей сейчас работает агент — правки сохранить не получится' : '';
    $('taskMsg').classList.toggle('err', !!data.busy);
    $('taskCodeName').textContent = t.filename;
    $('taskCode').value = task.codeLoaded;
    $('taskCodeMsg').textContent = data.code_exists ? '' : 'Код ещё не написан';
    showModalTab('taskModal', 'ptab-ticket');
    openModal('taskModal');
}

export async function saveTask() {
    try {
        const d = await api.post('/api/task-file', {
            task_file: task.file,
            new_status: $('taskStatus').value, raw_content: $('taskRaw').value
        });
        task.status = d.new_status;
        $('taskPath').textContent = d.task_path;
        $('taskMsg').classList.remove('err');
        $('taskMsg').textContent = '✅ Сохранено (' + d.new_status + ')';
        refresh();
    } catch (e) {
        $('taskMsg').classList.add('err');
        $('taskMsg').textContent = '⚠️ ' + e.message;
    }
}

// вернуть задачу в очередь с комментарием: диспетчер снимет паузу, свободный агент возьмёт её сразу
export async function returnTask() {
    const comment = $('taskComment').value.trim();
    try {
        await api.post('/api/task/move', { task_file: task.file, new_status: 'todo', comment });
        closeModal('taskModal');
        toast('Задача вернулась в очередь — агенты возьмут её в работу', 'info');
        refresh();
    } catch (e) {
        $('taskMsg').classList.add('err');
        $('taskMsg').textContent = '⚠️ ' + e.message;
    }
}

export async function saveTaskCode() {
    try {
        await api.post('/api/file', { filename: task.code, content: $('taskCode').value });
        $('taskCodeMsg').textContent = '💾 Код сохранён';
        refresh();
    } catch (e) {
        toast(e.message, 'err');
    }
}

export async function deleteTask() {
    if (!confirm(tr('Удалить задачу? Файл кода останется в рабочей папке.'))) return;
    try {
        await api.post('/api/task/delete', { task_file: task.file });
        closeModal('taskModal');
        toast('Задача удалена', 'info');
        refresh();
    } catch (e) {
        toast(e.message, 'err');
    }
}

export async function copyTaskCode() {
    toast(await copyText($('taskCode').value) ? 'Код скопирован' : 'Не удалось скопировать', 'info');
}

/* ---------- просмотр файла ---------- */

let openedFile = '';

export async function openFile(name, isNew = false) {
    let content = '';
    if (!isNew) {
        try {
            content = (await api.get('/api/file?name=' + encodeURIComponent(name))).content;
        } catch (e) {
            toast(e.message, 'err');
            return;
        }
    }
    openedFile = name;
    $('codeTitle').textContent = (isNew ? '📝 Новый файл: ' : '📄 ') + name;
    $('codeSub').textContent = (S.app ? S.app.workspace_dir + ' / ' : '') + name;
    $('codeArea').value = content;
    $('codeMsg').textContent = '';
    $('codePreviewBtn').hidden = !['html', 'htm', 'svg'].includes(fileExt(name));
    openModal('codeModal');
    $('codeArea').focus();
}

export async function saveFile() {
    try {
        await api.post('/api/file', { filename: openedFile, content: $('codeArea').value });
        $('codeMsg').textContent = '💾 Сохранено';
        refresh();
    } catch (e) {
        toast(e.message, 'err');
    }
}

export async function deleteFile() {
    if (!confirm(tr('Удалить файл') + ' ' + openedFile + '?')) return;
    try {
        await api.post('/api/file/delete', { filename: openedFile });
        closeModal('codeModal');
        toast('Файл удалён', 'info');
        refresh();
    } catch (e) {
        toast(e.message, 'err');
    }
}

export async function copyFile() {
    toast(await copyText($('codeArea').value) ? 'Скопировано' : 'Не удалось скопировать', 'info');
}

export function previewOpened() { preview(openedFile); }

// страница открывается в песочнице на отдельном адресе: сгенерированный код не получит доступ к API офиса
export function preview(name) {
    const app = S.app;
    if (!app) return;
    // сначала ищем страницу в папке текущего проекта, потом где угодно
    const names = (app.files || []).map(f => f.name);
    const proj = app.project_dir ? names.filter(n => n.startsWith(app.project_dir + '/')) : [];
    const target = name || [proj, names].map(list =>
        list.find(n => /(^|\/)index\.html?$/i.test(n)) || list.find(n => /\.html?$/i.test(n))).find(Boolean);
    if (!target) {
        toast('В проекте пока нет HTML-страницы', 'info');
        return;
    }
    const url = '/preview/' + encodeURIComponent(app.preview_key) + '/' + target.split('/').map(encodeURIComponent).join('/');
    window.open(url, '_blank', 'noopener');
}

export function currentModalSave() {
    if ($('codeModal').classList.contains('active')) { saveFile(); return true; }
    if ($('taskModal').classList.contains('active')) {
        if ($('ptab-code').classList.contains('active')) saveTaskCode(); else saveTask();
        return true;
    }
    return false;
}
