FROM harbor.dataknife.net/dockerhub/library/python:3.12-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SLASHBAY_HOST=0.0.0.0 \
    SLASHBAY_PORT=8080

COPY pyproject.toml README.md LICENSE /app/
COPY src/ /app/src/

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 1000 slashbay \
    && mkdir -p /data \
    && chown -R slashbay:slashbay /app /data

USER slashbay
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz')"

CMD ["uvicorn", "slashbay.app:app", "--host", "0.0.0.0", "--port", "8080"]
