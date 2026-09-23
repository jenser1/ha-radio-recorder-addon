FROM ghcr.io/home-assistant/base:latest

RUN apk add --no-cache ffmpeg python3 py3-pip tzdata

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip3 install --no-cache-dir --break-system-packages -r /app/requirements.txt

COPY app.py /app/app.py
COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
