FROM amazonlinux
RUN yum install -y python27-pip && \
    pip install --upgrade pip boto3 moto coverage pyaml
WORKDIR /root
ENTRYPOINT [ "bash", "test/test.sh" ]
ENV MOCK_XRAY TRUE
ENV SQUELCH_XRAY TRUE
COPY . .
