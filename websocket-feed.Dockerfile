FROM ubuntu:bionic
RUN apt update && \
    apt install -y python-pip && \
    pip install SimpleWebSocketServer boto3 && \
    apt clean
RUN mkdir /app
COPY *py ssl_key.pem ssl_cert.pem /app/
WORKDIR /app
ENTRYPOINT [ "python", "WebSocketScoreFeed.py"]
