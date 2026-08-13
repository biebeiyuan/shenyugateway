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

FROM python:3.12-slim

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
COPY scripts/resident_home.py ./scripts/resident_home.py
COPY --from=admin-builder /admin/dist ./admin/dist
COPY --from=pwa-builder /pwa/dist ./pwa/dist

EXPOSE 8010

CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8010"]
