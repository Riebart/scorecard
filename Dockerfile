FROM amazonlinux
RUN yum install -y python27-pip && \
    pip install --upgrade pip boto3 moto coverage pyaml
WORKDIR /root
ENTRYPOINT [ "bash", "test.sh" ]
ENV MOCK_XRAY TRUE
COPY . .
