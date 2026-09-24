ARG BUILD_FROM=ghcr.io/home-assistant/alpine:3.19
FROM ${BUILD_FROM}

ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache \
    python3 \
    py3-pip

WORKDIR /app

COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt --break-system-packages

COPY monitor.py .
RUN chmod a+x monitor.py

CMD [ "python3", "/app/monitor.py" ]
