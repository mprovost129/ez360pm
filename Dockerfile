FROM python:3.13-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

RUN SECRET_KEY=build-only-not-for-runtime \
    DB_NAME=unused DB_USER=unused DB_PASSWORD=unused \
    ALLOWED_HOSTS=localhost CSRF_TRUSTED_ORIGINS=https://localhost \
    PUBLIC_BASE_URL=https://localhost \
    DJANGO_SETTINGS_MODULE=config.Settings.prod \
    python manage.py collectstatic --noinput

RUN addgroup --system ez360pm \
    && adduser --system --ingroup ez360pm ez360pm \
    && mkdir -p /app/media \
    && chown -R ez360pm:ez360pm /app

USER ez360pm

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; request = urllib.request.Request(f\"http://127.0.0.1:{os.getenv('PORT', '8000')}/health/\", headers={'X-Forwarded-Proto': 'https'}); assert urllib.request.urlopen(request, timeout=4).status == 200"

CMD ["sh", "./bin/start.sh"]
