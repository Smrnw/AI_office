# Образ песочницы для тестов проектов, которые пишут агенты. Собирается автоматически при первом
# запуске проверки, если Docker доступен. Сам код запускается в нём без сети.
FROM python:3.12-slim
RUN pip install --no-cache-dir pytest \
 && apt-get update && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -m runner
USER runner
