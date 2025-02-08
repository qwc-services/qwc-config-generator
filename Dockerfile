FROM sourcepole/qwc-uwsgi-base:alpine-v2025.01.24

WORKDIR /srv/qwc_service
ADD pyproject.toml uv.lock ./

# git: Required for pip with git repos
# postgresql-dev g++ python3-dev: Required for psycopg2
RUN \
    apk add --no-cache --virtual runtime-deps postgresql-libs && \
    apk add --no-cache --virtual build-deps --update git postgresql-dev g++ python3-dev && \
    uv sync --frozen && \
    uv cache clean && \
    apk del build-deps

ADD src /srv/qwc_service/
ADD schemas /srv/qwc_service/schemas

# download JSON schemas for QWC services
ENV JSON_SCHEMAS_PATH=/srv/qwc_service/schemas/
RUN uv run /srv/qwc_service/download_json_schemas.py
