FROM node:20-slim AS admin-builder

WORKDIR /admin

COPY admin/package*.json ./
RUN npm ci

COPY admin ./
RUN npm run build

FROM node:20-slim AS pwa-builder

WORKDIR /pwa

ARG SOURCE_COMMIT=""
ENV PWA_BUILD_COMMIT=${SOURCE_COMMIT}

COPY pwa/package*.json ./
RUN npm ci

COPY pwa ./
RUN npm run build

FROM debian:trixie-slim AS sqlite-builder

ARG SQLITE_VERSION=3510300
ARG SQLITE_SOURCE_SHA3=32d5424f97e0a7fc5ed2f6335afbb58be4e0298bd7117a34e39d345ff13d859e

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl build-essential openssl \
    && curl -fsSL --retry 5 --retry-all-errors \
         "https://sqlite.org/2026/sqlite-autoconf-${SQLITE_VERSION}.tar.gz" \
         -o /tmp/sqlite.tar.gz \
    && mkdir -p /tmp/sqlite-src \
    && tar -xzf /tmp/sqlite.tar.gz --strip-components=1 -C /tmp/sqlite-src \
    && test "$(openssl dgst -sha3-256 /tmp/sqlite-src/sqlite3.c | awk "{print \$2}")" = "$SQLITE_SOURCE_SHA3" \
    && cd /tmp/sqlite-src \
    && ./configure --prefix=/opt/sqlite --enable-shared --disable-static \
    && make -j"$(nproc)" \
    && make install \
    && rm -rf /var/lib/apt/lists/* /tmp/sqlite.tar.gz /tmp/sqlite-src

FROM python:3.12-slim

# SQLite 3.51.3 is the first release with the upstream WAL-reset corruption
# fix. LD_LIBRARY_PATH makes Python's _sqlite3 load this built library, not the
# base image's distro copy. The final RUN proves the linked runtime identity.
COPY --from=sqlite-builder /opt/sqlite /opt/sqlite
ENV LD_LIBRARY_PATH=/opt/sqlite/lib
RUN python -c "import sqlite3; source=sqlite3.connect(':memory:').execute('select sqlite_source_id()').fetchone()[0]; assert sqlite3.sqlite_version_info >= (3,51,3); assert source.startswith('2026-03-13'); print('SQLite', sqlite3.sqlite_version, source)" \
    && ldd "$(python -c 'import _sqlite3; print(_sqlite3.__file__)')" | grep '/opt/sqlite/lib/libsqlite3.so'

WORKDIR /app

# Coolify/CI can pass SOURCE_COMMIT at build time; the resident home then
# shows the exact source revision even though the production image omits .git.
ARG SOURCE_COMMIT=""
ENV SOURCE_COMMIT=${SOURCE_COMMIT}

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt

COPY gateway.py ./
COPY shenyu_gateway ./shenyu_gateway
COPY resident_home_manifest.json resident_home_changes.jsonl project_delivery_log.jsonl ./
# The resident-home fingerprint check hashes every file in the manifest
# source_globs. Any manifest source that is not otherwise shipped must be
# copied here, or production permanently shows those components as 待复核.
# The Dockerfile itself must NOT be copied or fingerprinted: Coolify rewrites
# it at build time, injecting every configured env var as ARG lines (secrets
# included), so the in-container copy never matches the repository version.
COPY pwa/src/meta/roomEntry.ts ./pwa/src/meta/roomEntry.ts
COPY README.md DOCS_MAP.md ./
COPY docs/architecture/SYSTEM_ZONES.md ./docs/architecture/SYSTEM_ZONES.md
COPY scripts/backfill_chat_archive.py ./scripts/backfill_chat_archive.py
COPY scripts/local_chat_archive.py ./scripts/local_chat_archive.py
COPY scripts/resident_home.py ./scripts/resident_home.py
COPY --from=admin-builder /admin/dist ./admin/dist
COPY --from=pwa-builder /pwa/dist ./pwa/dist

EXPOSE 8010

CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8010"]
