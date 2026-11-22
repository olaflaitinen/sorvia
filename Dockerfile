# Sorvia API image.
FROM python:3.12-slim-bookworm AS build
WORKDIR /src
RUN pip install --no-cache-dir build==1.2.2
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SORVIA_MIGRATIONS_DIR=/app/db/migrations \
    SORVIA_STATIC_SQL_PATH=/app/benchmark/data/az_text2sql_v1.jsonl
RUN useradd --create-home --uid 10001 sorvia
WORKDIR /app
COPY --from=build /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl && rm -f /tmp/*.whl
COPY db/migrations ./db/migrations
COPY benchmark/data ./benchmark/data
COPY docker/entrypoint-init.sh /usr/local/bin/sorvia-init
USER sorvia
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"
CMD ["sorvia", "serve", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
