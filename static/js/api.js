// Обёртка над fetch. Изменяющие запросы несут заголовок X-Requested-With:
// сервер принимает их только с этой страницы (защита от CSRF).

export class ApiError extends Error {
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}

async function parse(res) {
    let data = null;
    try { data = await res.json(); } catch (e) { /* не JSON */ }
    if (!res.ok) {
        const detail = data && (data.detail || data.error);
        throw new ApiError(typeof detail === 'string' ? detail : 'Ошибка сервера (' + res.status + ')', res.status);
    }
    return data;
}

export async function get(path, headers = {}) {
    return parse(await fetch(path, { credentials: 'same-origin', headers }));
}

export async function post(path, body) {
    return parse(await fetch(path, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-Requested-With': 'pixel-office' },
        body: JSON.stringify(body ?? {})
    }));
}
