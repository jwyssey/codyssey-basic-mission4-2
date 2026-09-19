# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=UTC \
    LANG=C.UTF-8

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash procps iproute2 libstdc++6 tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 analyst \
    && useradd --uid 1000 --gid 1000 --create-home analyst \
    && mkdir -p /data /opt/mission \
    && chown analyst:analyst /data

WORKDIR /opt/mission
COPY bin/ bin/
COPY lib/ lib/
COPY scripts/ scripts/
COPY tests/ tests/
COPY docker/ docker/

# The supplied ZIP is mounted at runtime, never copied into the image.
# Named volume initialization preserves /data's non-root ownership.
USER 1000:1000
ENTRYPOINT ["python3", "docker/entrypoint.py"]
CMD ["doctor"]
