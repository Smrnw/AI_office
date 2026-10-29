// Общее состояние интерфейса: последний ответ сервера и выбор пользователя.

export const TEAM = '__team__';        // общий канал «Проект» (так же называется на сервере)

export const S = {
    app: null,              // последний ответ /api/state
    online: true,
    chatChannel: TEAM,
    layoutRev: null,
    bottomTab: 'kanban',
    lastEventId: 0,
    seenChat: {},           // канал -> id последнего прочитанного сообщения
};

export const STATUS_BUSY = 'Работает';
export const STATUS_ERROR = 'Ошибка';
