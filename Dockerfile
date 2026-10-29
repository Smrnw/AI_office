# AI Office в контейнере.
# Данные (config.json с ключами, задачи, чаты, рабочая папка с кодом) живут в томе /data.
FROM python:3.12-slim

# Node.js нужен только для проверки синтаксиса JS, который пишут агенты (node --check).
# Собрать без него: --build-arg WITH_NODE=0
ARG WITH_NODE=1
# Chromium для автопроверки страниц в браузере (около 400 МБ). Собрать без него: --build-arg WITH_BROWSER=0
ARG WITH_BROWSER=1

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIXEL_OFFICE_DIR=/data \
    PIXEL_OFFICE_HOST=0.0.0.0 \
    PIXEL_OFFICE_PORT=8080 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

RUN if [ "$WITH_NODE" = "1" ]; then \
        apt-get update && apt-get install -y --no-install-recommends nodejs && rm -rf /var/lib/apt/lists/*; \
    fi \
    && groupadd --system --gid 10001 office \
    && useradd --system --uid 10001 --gid office --home-dir /app --shell /usr/sbin/nologin office

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt \
    && if [ "$WITH_BROWSER" = "1" ]; then python -m playwright install --with-deps chromium; fi

COPY pixel_office ./pixel_office
COPY static ./static

RUN mkdir -p /data && chown office:office /data
USER office

EXPOSE 8080
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/api/health', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "pixel_office"]
