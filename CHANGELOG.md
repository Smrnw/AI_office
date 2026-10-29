# Changelog / История версий

Versions follow [Semantic Versioning](https://semver.org): **MAJOR** — incompatible changes to the
data folder or the API, **MINOR** — new features, **PATCH** — fixes. The version lives in one place,
`pixel_office/__init__.py`; it is shown in the menu, the help window, `/api/health` and the installers.

Нумерация по [семантическому версионированию](https://semver.org/lang/ru/): **MAJOR** — несовместимые
изменения папки данных или API, **MINOR** — новые возможности, **PATCH** — исправления. Версия записана в
одном месте — `pixel_office/__init__.py`; её показывают меню, справка, `/api/health` и установщики.

## [1.0.0] — 2026-10-29

First public release. / Первый публичный выпуск.

- A team of AI agents in a pixel-art office: manager, developers, testers and specialists
  (UI designer, DevOps, technical writer, security reviewer).
- Providers: Google Gemini, Anthropic, OpenAI, OpenRouter, Ollama, any OpenAI-compatible API, demo.
- Kanban with drag and drop, manual returns with comments, tasks as plain text files.
- Projects in separate folders with switching, per-project Git history (one commit per accepted task).
- Automatic checks: syntax, tests in a throwaway copy (Docker without network when available),
  browser check with screenshots reviewed by a vision model, security scan; errors go back to developers.
- Autopilot: goal → requirements → rounds of tasks within limits; project versions with rollback.
- Self-managing staff and desks; setup wizard on the first launch.
- No built-in prompts, team or office: the user writes every role's prompt (the wizard does not continue
  without them) and furnishes the empty office in the layout editor.
- Notifications to Telegram and email, replies from Telegram to the team chat.
- Layout editor, agent appearance editor, light and dark themes, Russian and English interface.
- Windows installer with a desktop shortcut, Linux installer with Docker.

[1.0.0]: https://github.com/Smrnw/AI_office/releases/tag/v1.0.0
