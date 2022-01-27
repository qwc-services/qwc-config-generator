FROM sourcepole/qwc-uwsgi-base:ubuntu-v2022.01.26

ADD . /srv/qwc_service

ARG DEBIAN_FRONTEND=noninteractive

RUN \
    echo "deb http://qgis.org/ubuntu-ltr focal main" > /etc/apt/sources.list.d/qgis.org-debian.list && \
    apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-key 46B5721DBBD2996A && \
    apt-get update && \
    apt-get install -y python3-qgis && \
    python3 -m pip install --no-cache-dir -r /srv/qwc_service/requirements.txt && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# This is needed because the qgis.core library is not capable of running in multiple threads
ENV UWSGI_THREADS=1
