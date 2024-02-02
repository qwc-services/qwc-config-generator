FROM sourcepole/qwc-uwsgi-base:alpine-v2023.10.26

ADD requirements.txt /srv/qwc_service/requirements.txt

# git: Required for pip with git repos
# postgresql-dev g++ python3-dev: Required for psycopg2
RUN \
    apk add --no-cache --virtual runtime-deps postgresql-libs && \
    apk add --no-cache --virtual build-deps --update git postgresql-dev g++ python3-dev && \
    pip3 install --no-cache-dir -r /srv/qwc_service/requirements.txt && \
    apk del build-deps

ADD src /srv/qwc_service/
ADD schemas /srv/qwc_service/schemas

# download JSON schemas for QWC services
ENV JSON_SCHEMAS_PATH=/srv/qwc_service/schemas/
RUN python3 /srv/qwc_service/download_json_schemas.py
