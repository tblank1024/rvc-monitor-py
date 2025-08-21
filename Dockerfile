# rvc2mqtt from linuxkidd into docker image
FROM python:3.11-slim-bookworm

ARG SRCDATA=usr/bin
WORKDIR /app/rvc2mqtt

COPY $SRCDATA/datafile.txt .
COPY $SRCDATA/rvc2mqtt.py .
COPY $SRCDATA/rvc-spec.yml .
COPY requirements.txt .

# Install system dependencies for CAN
RUN apt-get update && apt-get install -y \
    can-utils \
    iproute2 \
    net-tools \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN python -m pip install -r requirements.txt

# Set environment variables with defaults
ENV MQTT_BROKER=localhost
ENV CAN_INTERFACE=can0
ENV MQTT_TOPIC=RVC
ENV DEBUG_LEVEL=0
ENV MQTT_OUTPUT=1
ENV SCREEN_OUTPUT=0

CMD ["python3", "rvc2mqtt.py", "-s", "./rvc-spec.yml"]

