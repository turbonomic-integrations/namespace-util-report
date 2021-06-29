FROM python:3.8-alpine AS compile-image

RUN apk add --update --no-cache gcc musl-dev libc-dev libxslt-dev libffi-dev openssl-dev python3-dev rust cargo
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --upgrade pip && \
    pip install 'vmtconnect>3.2,<4' && \
    pip install 'umsg>=1,<2' && \
    pip install dateutils && \
    pip install 'pyyaml>5.3,<6' && \
    pip install openpyxl


FROM python:3.8-alpine
COPY --from=compile-image /opt/venv /opt/venv
COPY ./namespace-util.py ./sendmail.py /opt/turbonomic/namespace_util/
RUN apk update && \
    apk --no-cache add bash git openssh augeas shadow jq curl && \
    groupadd -g 1000 turbo && \
    useradd -r -m -p '' -u 1000 -g 1000 -c 'Turbo User' -s /bin/bash turbo && \
    chown -R turbo:turbo /opt/turbonomic/namespace_util && \
    chmod 555 /opt/turbonomic/namespace_util/* && \
    rm -rf /var/cache/apk/* && \
    rm -rf /svc && \ 
    rm -rf /tmp/* && \
    rm -rf /root/.[a-zA-Z_-]*

ENV PATH="/opt/venv/bin:$PATH"
ENTRYPOINT ["/opt/turbonomic/namespace_util/namespace-util.py"]

