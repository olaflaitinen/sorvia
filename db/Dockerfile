# PostgreSQL 16 with the extensions Sorvia needs: pgvector (schema retrieval)
# and HypoPG (hypothetical indexes for the index advisor).
FROM postgres:16-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends postgresql-16-pgvector postgresql-16-hypopg \
 && rm -rf /var/lib/apt/lists/*

CMD ["postgres", "-c", "shared_preload_libraries=pg_stat_statements", "-c", "timezone=Asia/Baku"]
