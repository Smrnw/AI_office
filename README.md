# AI Office

**English** · [Русский](README.ru.md)

A team of AI agents working in a pixel-art office. You describe a project in the chat; the manager
splits it into tasks, developers write the code, a tester reviews it, and an automatic check opens
the result in a real browser, runs the tests and looks for vulnerabilities. You watch it all happen
on a kanban board and in a live office where every agent walks to their desk before starting work.

![AI Office](docs/screenshots/main-en.png)

## Features

- **A real team.** Manager, developers, testers and specialists (UI designer, DevOps, technical writer,
  security reviewer). Each role takes its own work; specialists pick their own files first.
- **Any model.** Google Gemini, Anthropic, OpenAI, OpenRouter, Ollama or any OpenAI-compatible API.
  A built-in demo provider works without keys or internet.
- **Automatic checks.** Syntax of every file, automated tests in a throwaway copy (in Docker without
  network if available), pages opened in Edge/Chrome with console errors, broken files and button
  clicks, desktop and phone screenshots reviewed by a vision model, and a security scan
  (secrets in code, XSS, SQL injection, `eval`, bandit). Errors go back to developers automatically.
- **Autopilot.** `/auto <goal>` — the manager turns the goal into requirements and keeps assigning
  tasks round after round until the goal is reached, within limits on rounds, tokens and time.
  A project version is saved before every round; roll back from the project menu.
- **Self-managing office.** Hires temporary staff when the queue grows, hires specialists when their
  files pile up, lets them go when the work is done and adds desks when seats run out (once you have
  furnished the office).
- **Projects and history.** Every project lives in its own folder with its own Git repository
  (no Git installation needed) — one commit per accepted task, authored by the agent.
- **Notifications.** Telegram and email: project ready, autopilot finished, errors, questions from
  the team. Reply to the Telegram bot and your message goes straight to the team chat.
- **Your office, your way.** Nothing is pre-built: you write every role's system prompt yourself and
  furnish the office in the layout editor (zones, furniture, desks). Agent appearance editor, light and
  dark themes, Russian and English interface.
- **Plain files, no database.** Everything is stored in the `data/` folder next to the code.

## Quick start

Download the code: **Code → Download ZIP** on [the project page](https://github.com/Smrnw/AI_office) and unpack it, or

```bash
git clone https://github.com/Smrnw/AI_office.git
```

### Windows

1. Install [Python 3.10+](https://www.python.org/downloads/) (or let the installer do it via winget).
2. Double-click **`install.bat`**. It creates `.venv`, installs dependencies, adds an **AI Office**
   shortcut to the desktop and the Start menu, and opens the office in your browser.
3. The setup wizard asks for the office name, language, model, folders and team, and for a system
   prompt for every role you hire — there are no built-in prompts. Choose the *Demo* model to try it
   without an API key. Then the layout editor opens: the office starts empty, place desks and zones.

Later, start the office with the shortcut or `start.bat`. The server runs in a minimised window;
close it to stop the office.

### Linux (Docker)

```bash
sudo ./deploy/install.sh            # this machine only: http://127.0.0.1:8080
sudo ./deploy/install.sh --lan      # reachable from the local network (token required)
```

The script installs Docker if needed, generates an access token, builds the image and prints a
login link. Manage it with `pixel-office status | logs | restart | stop | url | backup`.

### Manually

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip
.venv/bin/python -m pixel_office               # http://127.0.0.1:8080
```

Browser checks use an installed Edge or Chrome. On a machine without them run
`python -m playwright install chromium`.

## Using it

| In the chat | What happens |
|---|---|
| First message in **Project** | A new project: plan, tasks, code, review, automatic check |
| Any later message | A revision of the current project |
| `@Coder_1 how does the form work?` | The named agent answers |
| `/new <idea>` | A new project with a clean board |
| `/auto <goal>` | Autopilot drives the project to the goal |
| `hire a designer` | The manager adds a permanent team member (the role needs your prompt) |

Drag kanban cards between columns (for example, back to *Queue* with a comment for the agent).
Switch projects from the project chip in the header; there you will also find the autopilot,
project versions and the Git history.

## Configuration

Settings live in the interface (**☰ → Settings**) and are saved to `data/config.json`.
Server options come from environment variables or a `.env` file (see `.env.example`):

| Variable | Meaning |
|---|---|
| `PIXEL_OFFICE_DIR` | Data folder. Default: `data/` next to the code |
| `PIXEL_OFFICE_HOST`, `PIXEL_OFFICE_PORT` | Address and port. Default: `127.0.0.1:8080` |
| `PIXEL_OFFICE_TOKEN` | Access token. Required when listening on anything but localhost |
| `PIXEL_OFFICE_ALLOWED_HOSTS` | Extra host names, e.g. `office.lan` |
| `<PROVIDER_ID>_API_KEY` | Provider key from the environment instead of `config.json` |

`data/` holds everything: config with API keys, tasks, chats, project code, versions, check
reports and logs. Back it up by copying the folder. **Never publish `data/`.**

## Security

The server is meant for localhost or a trusted network. It checks the `Host` header (DNS
rebinding), accepts state-changing requests only from its own origin with a custom header (CSRF),
refuses to listen on a network address without a token, keeps API keys, the bot token and the
SMTP password on the server, and serves generated pages in a CSP sandbox. Agents can only write
inside the workspace and never into `.git`; Git hooks are never executed.

Project code is executed only by the automatic check, in a throwaway copy. Without Docker this is
an ordinary process with a timeout and an empty environment — not a full sandbox. Choose
**Docker only** in *Settings → Checks* if that matters to you. Details: [SECURITY.md](SECURITY.md).

## Development

```bash
.venv/bin/python -m pytest
```

The tests run the whole team on the demo provider, including the browser checks.

```
pixel_office/   backend (FastAPI): agents, checks, LLM clients, API, storage
static/         frontend without a build step: ES modules, canvas office, i18n
deploy/         Windows and Linux installers
tests/          pytest
docs/           screenshots and the GitHub page text
```

## Versions

Current version: see the menu or `pixel_office/__init__.py`. What changed: [CHANGELOG.md](CHANGELOG.md).

## License

[PolyForm Noncommercial 1.0.0](LICENSE). Free for personal, educational, research and
nonprofit use. Selling, reselling, rebranding, offering it as a paid service or any other
commercial use requires a separate license — contact the author via [GitHub](https://github.com/Smrnw).
