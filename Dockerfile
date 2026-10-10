# syntax=docker/dockerfile:1

# ---------------------------------------------------------------- web build
FROM node:22-alpine AS web
WORKDIR /web

# npmmirror keeps the build fast on CN networks; override with
#   --build-arg NPM_REGISTRY=https://registry.npmjs.org
ARG NPM_REGISTRY=https://registry.npmmirror.com
COPY web/package.json web/package-lock.json* ./
RUN npm install --registry=${NPM_REGISTRY} --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ------------------------------------------------------------ python runtime
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/app/data \
    WEB_DIST=/app/web/dist

WORKDIR /app

COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./
COPY --from=web /web/dist ./web/dist

# unprivileged runtime user; ./data is bind-mounted by compose
RUN useradd --system --uid 10001 --home /app app \
    && mkdir -p /app/data \
    && chown -R app:app /app
USER app

EXPOSE 8000

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).status == 200 else 1)"

# --proxy-headers so X-Forwarded-* from Nginx are honoured (scheme/host/ip)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", "--no-server-header"]
