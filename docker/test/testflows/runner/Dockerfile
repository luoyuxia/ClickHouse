# docker build -t clickhouse/testflows-runner .
FROM ubuntu:20.04

RUN sed -i 's|http://archive|http://ru.archive|g' /etc/apt/sources.list

RUN apt-get update \
    && env DEBIAN_FRONTEND=noninteractive apt-get install --yes \
    ca-certificates \
    bash \
    btrfs-progs \
    e2fsprogs \
    iptables \
    xfsprogs \
    tar \
    pigz \
    wget \
    git \
    iproute2 \
    cgroupfs-mount \
    python3-pip \
    tzdata \
    libreadline-dev \
    libicu-dev \
    bsdutils \
    curl \
    liblua5.1-dev \
    luajit \
    libssl-dev \
    libcurl4-openssl-dev \
    gdb \
    && rm -rf \
        /var/lib/apt/lists/* \
        /var/cache/debconf \
        /tmp/* \
    && apt-get clean

ENV TZ=Europe/Moscow
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN pip3 install urllib3 testflows==1.7.20 docker-compose==1.29.1 docker==5.0.0 dicttoxml kazoo tzlocal==2.1 pytz python-dateutil numpy

ENV DOCKER_CHANNEL stable
ENV DOCKER_VERSION 20.10.6

RUN set -eux; \
  \
# this "case" statement is generated via "update.sh"
  \
  if ! wget -nv -O docker.tgz "https://download.docker.com/linux/static/${DOCKER_CHANNEL}/x86_64/docker-${DOCKER_VERSION}.tgz"; then \
    echo >&2 "error: failed to download 'docker-${DOCKER_VERSION}' from '${DOCKER_CHANNEL}' for '${x86_64}'"; \
    exit 1; \
  fi; \
  \
  tar --extract \
    --file docker.tgz \
    --strip-components 1 \
    --directory /usr/local/bin/ \
  ; \
  rm docker.tgz; \
  \
  dockerd --version; \
  docker --version

COPY modprobe.sh /usr/local/bin/modprobe
COPY dockerd-entrypoint.sh /usr/local/bin/
COPY process_testflows_result.py /usr/local/bin/

RUN set -x \
  && addgroup --system dockremap \
    && adduser --system dockremap \
  && adduser dockremap dockremap \
  && echo 'dockremap:165536:65536' >> /etc/subuid \
    && echo 'dockremap:165536:65536' >> /etc/subgid

VOLUME /var/lib/docker
EXPOSE 2375
ENTRYPOINT ["dockerd-entrypoint.sh"]
CMD ["sh", "-c", "python3 regression.py --no-color -o new-fails --local --clickhouse-binary-path ${CLICKHOUSE_TESTS_SERVER_BIN_PATH} --log test.log ${TESTFLOWS_OPTS}; cat test.log | tfs report results --format json > results.json; /usr/local/bin/process_testflows_result.py || echo -e 'failure\tCannot parse results' > check_status.tsv; find * -type f | grep _instances | grep clickhouse-server | xargs -n1 tar -rvf clickhouse_logs.tar; gzip -9 clickhouse_logs.tar"]
