#rvc2mqtt from linuxkid into docker image
FROM python:3.10-slim-buster

ARG SRCDATA=usr/bin
WORKDIR /app/rvc2mqtt

COPY $SRCDATA/datafile.txt .
COPY $SRCDATA/rvc2mqtt.py .
COPY $SRCDATA/rvc-spec.yml .
COPY requirements.txt .

#ruamel installed independently since there is no C complier
RUN python -m pip install --no-deps ruamel.yaml

RUN python -m pip install -r requirements.txt

CMD python3 rvc2mqtt.py -o0 -d4 -m1 -s/app/rvc2mqtt/rvc-spec.yml

