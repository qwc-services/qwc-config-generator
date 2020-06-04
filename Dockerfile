FROM sourcepole/qwc-uwsgi-base:alpine-latest

# Required dependencies for psycopg2-binary
RUN apk add --no-cache postgresql-libs

ADD . /srv/qwc_service

# Install requirements.txt
RUN \
 apk add --no-cache --virtual .build-deps gcc musl-dev postgresql-dev python3-dev && \
 python3 -m pip install --no-cache-dir -r /srv/qwc_service/requirements.txt && \
 apk --purge del .build-deps
