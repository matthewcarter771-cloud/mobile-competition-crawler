# Same Python version as the local venv
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY crawler ./crawler

CMD ["python", "-m", "crawler.run"]
