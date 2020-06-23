FROM sourcepole/qwc-uwsgi-base:ubuntu-latest

# Required dependencies for psycopg2-binary
# RUN apk add --no-cache postgresql-libs
ARG DEBIAN_FRONTEND=noninteractive

RUN echo "deb http://qgis.org/ubuntu-ltr bionic main" > /etc/apt/sources.list.d/qgis.org-debian.list
RUN apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-key 51F523511C7028C3

RUN apt-get update && apt-get install -y python3-qgis

ADD . /srv/qwc_service

# Install requirements.txt
RUN python3 -m pip install --no-cache-dir -r /srv/qwc_service/requirements.txt
