FROM sourcepole/qwc-uwsgi-base:ubuntu-v2023.10.26

ADD . /srv/qwc_service

ARG DEBIAN_FRONTEND=noninteractive

# git: Required for pip with git repos
# libpq-dev g++ python3-dev: Required for psycopg2
RUN \
    echo "deb http://qgis.org/ubuntu-ltr jammy main" > /etc/apt/sources.list.d/qgis.org-debian.list && \
    apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-key D155B8E6A419C5BE && \
    apt-get update && \
    apt-get install -y libpq-dev g++ python3-dev && \
    python3 -m pip install --no-cache-dir -r /srv/qwc_service/requirements.txt && \
    apt-get purge -y libpq-dev g++ python3-dev && \
    apt-get install -y python3-qgis && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# This is needed because the qgis.core library is not capable of running in multiple threads
ENV UWSGI_THREADS=1

# download JSON schemas for QWC services
ENV JSON_SCHEMAS_PATH=/srv/qwc_service/schemas/
RUN python3 /srv/qwc_service/download_json_schemas.py
