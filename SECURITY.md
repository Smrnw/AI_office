# Security / Безопасность

## Reporting a vulnerability

Please do not open a public issue. Use [Report a vulnerability](https://github.com/Smrnw/AI_office/security/advisories/new)
(a private advisory) and describe the steps to reproduce. I will answer as soon as I can.

Пожалуйста, не создавайте публичный issue. Используйте [Report a vulnerability](https://github.com/Smrnw/AI_office/security/advisories/new)
(приватное сообщение) и опишите, как воспроизвести проблему. Отвечу, как только смогу.

## Threat model

AI Office runs on your machine or in a trusted network. The main risks it is built to withstand:

| Threat | Protection |
|---|---|
| A website open in the same browser calls the local API (CSRF, DNS rebinding) | `Host` allow-list; state-changing requests need the own `Origin` and the `X-Requested-With` header; no CORS |
| The office reachable from the network | The server refuses to listen on a non-loopback address without `PIXEL_OFFICE_TOKEN`; the token is compared in constant time and stored in an `HttpOnly`, `SameSite=Strict` cookie |
| Secrets leaking to the browser or logs | API keys, the Telegram token and the SMTP password never leave the server; the bot token is masked in error messages |
| A changed server URL steals a saved secret | A saved API key or SMTP password is dropped when the provider URL or the SMTP server changes |
| Generated code attacks the office UI | Generated pages are served with `Content-Security-Policy: sandbox` under a random per-run key and get an opaque origin |
| Prompt injection makes an agent write outside the project | All paths go through one check: no `..`, no reserved Windows names, no symlink escape, no `.git` (including `.git.` and 8.3 short names) |
| Git hooks as a code execution path | Hooks are never run; `.git` is not writable by agents |
| Generated pages probing the local network during the browser check | Requests to private, loopback and link-local addresses and `*.local`/`*.lan` names are blocked |
| Credentials over plain SMTP | Login without TLS is refused |

## Known limitations

- **Running project tests without Docker is not a sandbox.** The automatic check runs tests in a
  throwaway copy of the project with a timeout and an empty environment, but the process has the
  same file system access as your user. Use *Settings → Checks → Docker only* or turn the tests off
  if you run untrusted goals.
- The browser check lets generated pages reach the public internet (fonts, CDNs).
- Anyone who can open the office UI controls it. Do not expose it to the internet; use the token and
  a reverse proxy with TLS if you need remote access.
- `data/config.json` stores API keys in plain text. Keep the `data/` folder private.
