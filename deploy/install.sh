#!/usr/bin/env bash
# Автоустановка AI Office на Linux в Docker.
#
#   sudo ./deploy/install.sh                 # только для этой машины: http://127.0.0.1:8080
#   sudo ./deploy/install.sh --lan           # доступ из локальной сети
#   sudo ./deploy/install.sh --lan --host office.example.com --port 9000
#   sudo ./deploy/install.sh --uninstall [--purge]
#
# Повторный запуск обновляет установку: код копируется заново, образ пересобирается,
# данные (config.json, задачи, рабочая папка) и токен сохраняются.
set -euo pipefail

INSTALL_DIR="/opt/pixel-office"
PORT=""
BIND=""
TOKEN=""
EXTRA_HOSTS=()
IMPORT_CONFIG=""
WITH_NODE=""
ASSUME_YES=0
UNINSTALL=0
PURGE=0
APP_UID=10001
CONTAINER=pixel-office
WRAPPER=/usr/local/bin/pixel-office

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ORIG_ARGS=("$@")      # для перезапуска через sudo: разбор параметров ниже их съедает

# ---------------------------------------------------------------- вывод

if [ -t 1 ]; then C_OK=$'\e[32m'; C_WARN=$'\e[33m'; C_ERR=$'\e[31m'; C_B=$'\e[1m'; C_0=$'\e[0m'
else C_OK=""; C_WARN=""; C_ERR=""; C_B=""; C_0=""; fi
info() { printf '%s==>%s %s\n' "$C_B" "$C_0" "$*"; }
ok()   { printf '%s ✔%s %s\n' "$C_OK" "$C_0" "$*"; }
warn() { printf '%s ! %s%s\n' "$C_WARN" "$*" "$C_0" >&2; }
die()  { printf '%s ✘ %s%s\n' "$C_ERR" "$*" "$C_0" >&2; exit 1; }

usage() {
    cat <<EOF
Установка AI Office в Docker.

Использование: sudo $0 [параметры]

  --dir DIR             куда установить (по умолчанию $INSTALL_DIR)
  --port N              порт на этой машине (по умолчанию 8080)
  --lan                 открыть доступ из сети (по умолчанию только 127.0.0.1)
  --local               снова закрыть доступ из сети
  --host ИМЯ            доменное имя или IP, по которому открывают офис (можно несколько раз)
  --token СТРОКА        свой токен доступа (по умолчанию генерируется и сохраняется)
  --import-config ФАЙЛ  взять готовый config.json (провайдеры, ключи, агенты)
  --no-node             собрать образ без Node.js (без проверки синтаксиса JS)
  -y, --yes             не задавать вопросов (например, ставить Docker без подтверждения)
  --uninstall           остановить и удалить контейнер и команду pixel-office
  --purge               вместе с --uninstall удалить и данные ($INSTALL_DIR)
  -h, --help            эта справка
EOF
}

# ---------------------------------------------------------------- параметры

while [ $# -gt 0 ]; do
    case "$1" in
        --dir) INSTALL_DIR="${2:?}"; shift 2 ;;
        --port) PORT="${2:?}"; shift 2 ;;
        --lan) BIND="0.0.0.0"; shift ;;
        --local) BIND="127.0.0.1"; shift ;;
        --host) EXTRA_HOSTS+=("${2:?}"); shift 2 ;;
        --token) TOKEN="${2:?}"; shift 2 ;;
        --import-config) IMPORT_CONFIG="${2:?}"; shift 2 ;;
        --no-node) WITH_NODE=0; shift ;;
        -y|--yes) ASSUME_YES=1; shift ;;
        --uninstall) UNINSTALL=1; shift ;;
        --purge) PURGE=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "Неизвестный параметр: $1" ;;
    esac
done

if [ -n "$PORT" ] && ! [[ "$PORT" =~ ^[0-9]+$ && "$PORT" -ge 1 && "$PORT" -le 65535 ]]; then
    die "Порт должен быть числом от 1 до 65535"
fi
if [ -n "$TOKEN" ] && ! [[ "$TOKEN" =~ ^[A-Za-z0-9._~-]{16,}$ ]]; then
    die "Токен: минимум 16 символов, только латиница, цифры и . _ ~ -"
fi
for h in "${EXTRA_HOSTS[@]+"${EXTRA_HOSTS[@]}"}"; do
    [[ "$h" =~ ^[A-Za-z0-9.:-]+$ ]] || die "Недопустимое имя хоста: $h"
done
case "$INSTALL_DIR" in /*) ;; *) die "--dir: нужен абсолютный путь" ;; esac
[ "$INSTALL_DIR" != "/" ] || die "--dir: нельзя ставить в корень"

if [ "$(id -u)" -ne 0 ]; then
    command -v sudo >/dev/null 2>&1 || die "Запустите от root"
    info "Нужны права администратора, перезапускаю через sudo"
    exec sudo -- "$0" "${ORIG_ARGS[@]+"${ORIG_ARGS[@]}"}"
fi

confirm() {
    [ "$ASSUME_YES" -eq 1 ] && return 0
    [ -t 0 ] || return 1
    local answer
    read -r -p "$1 [y/N] " answer
    [[ "$answer" =~ ^[YyДд] ]]
}

# ---------------------------------------------------------------- Docker

COMPOSE=()
detect_compose() {
    if docker compose version >/dev/null 2>&1; then COMPOSE=(docker compose)
    elif command -v docker-compose >/dev/null 2>&1; then COMPOSE=(docker-compose)
    else COMPOSE=(); fi
}

download() {   # download URL FILE
    if command -v curl >/dev/null 2>&1; then curl -fsSL "$1" -o "$2"
    elif command -v wget >/dev/null 2>&1; then wget -qO "$2" "$1"
    else die "Нужен curl или wget"; fi
}

install_compose_plugin() {
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq && (apt-get install -y -qq docker-compose-plugin || apt-get install -y -qq docker-compose-v2)
    elif command -v dnf >/dev/null 2>&1; then dnf install -y -q docker-compose-plugin
    elif command -v yum >/dev/null 2>&1; then yum install -y -q docker-compose-plugin
    elif command -v apk >/dev/null 2>&1; then apk add --no-cache docker-cli-compose
    elif command -v pacman >/dev/null 2>&1; then pacman -Sy --noconfirm docker-compose
    else return 1; fi
}

ensure_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        warn "Docker не установлен."
        confirm "Установить Docker официальным скриптом get.docker.com?" \
            || die "Без Docker установка невозможна. Поставьте его и запустите скрипт снова (или добавьте --yes)."
        local tmp
        tmp="$(mktemp)"
        download https://get.docker.com "$tmp"
        sh "$tmp"
        rm -f "$tmp"
    fi
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        systemctl enable --now docker >/dev/null 2>&1 || true
    fi
    docker info >/dev/null 2>&1 || die "Docker установлен, но демон не отвечает (systemctl status docker)"
    detect_compose
    if [ ${#COMPOSE[@]} -eq 0 ]; then
        info "Ставлю Docker Compose"
        install_compose_plugin || die "Не удалось поставить Docker Compose, установите его вручную"
        detect_compose
        [ ${#COMPOSE[@]} -gt 0 ] || die "Docker Compose не найден"
    fi
    ok "Docker $(docker version --format '{{.Server.Version}}' 2>/dev/null), ${COMPOSE[*]}"
}

dc() { "${COMPOSE[@]}" --project-directory "$INSTALL_DIR" -f "$INSTALL_DIR/docker-compose.yml" "$@"; }

# ---------------------------------------------------------------- удаление

if [ "$UNINSTALL" -eq 1 ]; then
    detect_compose
    if [ -f "$INSTALL_DIR/docker-compose.yml" ] && [ ${#COMPOSE[@]} -gt 0 ]; then
        info "Останавливаю контейнер"
        dc down --rmi local || true
    fi
    rm -f "$WRAPPER"
    if [ "$PURGE" -eq 1 ]; then
        confirm "Удалить $INSTALL_DIR вместе с данными (config.json с ключами, задачи, код)?" \
            || die "Отменено. Данные остались в $INSTALL_DIR"
        rm -rf -- "$INSTALL_DIR"
        ok "Удалено полностью"
    else
        ok "Контейнер удалён. Данные остались в $INSTALL_DIR/data (удалить: --uninstall --purge)"
    fi
    exit 0
fi

# ---------------------------------------------------------------- установка

[ -f "$SRC_DIR/Dockerfile" ] && [ -d "$SRC_DIR/pixel_office" ] || die "Запускайте скрипт из папки проекта: deploy/install.sh"
ensure_docker

info "Копирую код в $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
if [ "$(cd "$INSTALL_DIR" && pwd -P)" != "$(cd "$SRC_DIR" && pwd -P)" ]; then
    # старый код убираем, данные и настройки не трогаем
    rm -rf -- "$INSTALL_DIR/pixel_office" "$INSTALL_DIR/static" "$INSTALL_DIR/deploy"
    tar -C "$SRC_DIR" \
        --exclude=./.venv --exclude=./.git --exclude=./.claude --exclude=./data --exclude=./data-dev \
        --exclude=./.env --exclude='*.bat' --exclude='__pycache__' --exclude='*.pyc' --exclude=./.pytest_cache \
        -cf - . | tar -C "$INSTALL_DIR" -xf -
fi
chmod 755 "$INSTALL_DIR"

DATA_DIR="$INSTALL_DIR/data"
mkdir -p "$DATA_DIR"
if [ -n "$IMPORT_CONFIG" ]; then
    [ -f "$IMPORT_CONFIG" ] || die "Нет файла $IMPORT_CONFIG"
    if [ -f "$DATA_DIR/config.json" ]; then
        cp "$DATA_DIR/config.json" "$DATA_DIR/config.json.bak.$(date +%Y%m%d%H%M%S)"
        warn "Старый config.json сохранён рядом как .bak"
    fi
    # пути с Windows внутри контейнера не работают: сбрасываем на папки по умолчанию в /data
    if command -v python3 >/dev/null 2>&1; then
        python3 - "$IMPORT_CONFIG" "$DATA_DIR/config.json" <<'PY'
import json, sys
cfg = json.load(open(sys.argv[1], encoding="utf-8-sig"))   # файл из Блокнота Windows бывает с BOM
cfg["workspace_dir"] = ""
cfg["tasks_dir"] = ""
json.dump(cfg, open(sys.argv[2], "w", encoding="utf-8"), ensure_ascii=False, indent=2)
PY
    else
        cp "$IMPORT_CONFIG" "$DATA_DIR/config.json"
        warn "python3 не найден: проверьте в Настройках рабочую папку (пути с Windows в контейнере не работают)"
    fi
    ok "Импортирован config.json"
fi
# в контейнере офис работает от пользователя $APP_UID, ему нужна запись в данные
chown -R "$APP_UID:$APP_UID" "$DATA_DIR"
chmod 750 "$DATA_DIR"

# ---------------------------------------------------------------- .env

ENV_FILE="$INSTALL_DIR/.env"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

env_get() { sed -n "s/^$1=//p" "$ENV_FILE" | tail -n 1; }
env_set() {   # env_set KEY VALUE: заменить строку или дописать
    local tmp
    tmp="$(mktemp)"
    grep -v "^$1=" "$ENV_FILE" > "$tmp" || true
    printf '%s=%s\n' "$1" "$2" >> "$tmp"
    cat "$tmp" > "$ENV_FILE"
    rm -f "$tmp"
}

gen_token() {
    if command -v openssl >/dev/null 2>&1; then openssl rand -hex 24
    else head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n'; fi
}

[ -n "$TOKEN" ] || TOKEN="$(env_get PIXEL_OFFICE_TOKEN)"
[ -n "$TOKEN" ] || TOKEN="$(gen_token)"
[ -n "$PORT" ] || PORT="$(env_get PO_PORT)"
[ -n "$PORT" ] || PORT=8080
[ -n "$BIND" ] || BIND="$(env_get PO_BIND)"
[ -n "$BIND" ] || BIND=127.0.0.1
[ -n "$WITH_NODE" ] || WITH_NODE="$(env_get PO_WITH_NODE)"
[ -n "$WITH_NODE" ] || WITH_NODE=1

# имена, под которыми офис будут открывать: без них сервер отклонит запрос (защита от DNS rebinding)
HOSTS=()
for h in $(env_get PIXEL_OFFICE_ALLOWED_HOSTS | tr ',' ' '); do HOSTS+=("$h"); done
HOSTS+=("${EXTRA_HOSTS[@]+"${EXTRA_HOSTS[@]}"}")
if [ "$BIND" = "0.0.0.0" ]; then
    HOSTS+=("$(hostname 2>/dev/null || true)" "$(hostname -f 2>/dev/null || true)")
    # адреса реальных сетевых карт; мосты Docker и виртуалок в список не нужны
    if command -v ip >/dev/null 2>&1; then
        for ip in $(ip -o -4 addr show scope global \
                    | awk '$2 !~ /^(docker|br-|veth|virbr|cni|flannel|lxc)/ {print $4}' | cut -d/ -f1); do
            HOSTS+=("$ip")
        done
    elif hostname -I >/dev/null 2>&1; then
        for ip in $(hostname -I); do HOSTS+=("$ip"); done
    fi
fi
ALLOWED="$(printf '%s\n' "${HOSTS[@]+"${HOSTS[@]}"}" | tr 'A-Z' 'a-z' | grep -E '^[a-z0-9.:-]+$' | grep -vE '^(localhost|127\.0\.0\.1)$' | sort -u | paste -sd, - || true)"

env_set PIXEL_OFFICE_TOKEN "$TOKEN"
env_set PIXEL_OFFICE_ALLOWED_HOSTS "$ALLOWED"
env_set PO_PORT "$PORT"
env_set PO_BIND "$BIND"
env_set PO_WITH_NODE "$WITH_NODE"
ok "Настройки записаны в $ENV_FILE"

# ---------------------------------------------------------------- сборка и запуск

info "Собираю образ и запускаю контейнер (первый раз это займёт пару минут)"
dc up -d --build --remove-orphans

info "Жду, пока офис ответит"
status=""
for _ in $(seq 1 60); do
    status="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$CONTAINER" 2>/dev/null || true)"
    [ "$status" = "healthy" ] && break
    if [ "$status" = "exited" ] || [ "$status" = "dead" ]; then break; fi
    sleep 2
done
if [ "$status" != "healthy" ]; then
    dc logs --tail=60 || true
    die "Контейнер не поднялся (состояние: ${status:-нет}). Логи выше."
fi
ok "Офис работает"

# ---------------------------------------------------------------- брандмауэр

if [ "$BIND" = "0.0.0.0" ] && command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -q "Status: active"; then
    if confirm "Открыть порт $PORT/tcp в ufw?"; then
        ufw allow "$PORT/tcp" >/dev/null && ok "Порт $PORT открыт в ufw"
    else
        warn "ufw включён: откройте порт сами — ufw allow $PORT/tcp"
    fi
fi

# ---------------------------------------------------------------- команда управления

COMPOSE_CMD="${COMPOSE[*]}"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env bash
# Управление AI Office (создано deploy/install.sh)
set -euo pipefail
DIR="$INSTALL_DIR"
dc() { $COMPOSE_CMD --project-directory "\$DIR" -f "\$DIR/docker-compose.yml" "\$@"; }
token() { sed -n 's/^PIXEL_OFFICE_TOKEN=//p' "\$DIR/.env" | tail -n 1; }
case "\${1:-help}" in
    start)   dc up -d ;;
    stop)    dc stop ;;
    restart) dc restart ;;
    status)  dc ps ;;
    logs)    dc logs -f --tail=200 ;;
    url)     port=\$(sed -n 's/^PO_PORT=//p' "\$DIR/.env" | tail -n 1)
             echo "http://localhost:\${port:-8080}/?token=\$(token)" ;;
    token)   token ;;
    backup)  mkdir -p "\$DIR/backups"
             f="\$DIR/backups/data-\$(date +%Y%m%d-%H%M%S).tar.gz"
             tar -C "\$DIR" -czf "\$f" data && chmod 600 "\$f" && echo "Копия данных: \$f" ;;
    *)       echo "pixel-office start|stop|restart|status|logs|url|token|backup"
             echo "Обновление: скачайте новую версию и снова запустите deploy/install.sh" ;;
esac
EOF
chmod 755 "$WRAPPER"
ok "Команда управления: pixel-office start|stop|restart|status|logs|url|token|backup"

# ---------------------------------------------------------------- итог

echo
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$INSTALL_DIR/pixel_office/__init__.py")"
printf '%sAI Office %s готов.%s Откройте (токен запомнится в браузере):\n' "$C_B" "$VERSION" "$C_0"
if [ "$BIND" = "0.0.0.0" ]; then
    IFS=',' read -r -a shown <<< "$ALLOWED"
    for h in "${shown[@]+"${shown[@]}"}"; do
        [[ "$h" == *:* ]] && continue      # IPv6 пропускаем, чтобы не путать
        echo "  http://$h:$PORT/?token=$TOKEN"
    done
fi
echo "  http://localhost:$PORT/?token=$TOKEN   (с этой машины)"
echo
echo "Данные: $DATA_DIR (config.json с ключами, задачи, рабочая папка workspace/)"
echo "Ollama на этом же сервере: в Настройках укажите http://host.docker.internal:11434/v1/chat/completions"
[ "$BIND" = "0.0.0.0" ] || echo "Доступ из сети выключен. Включить: sudo $0 --lan"
