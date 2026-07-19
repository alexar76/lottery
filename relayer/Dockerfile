# AI-Agent Oracle Lottery — economy engine + relayer
FROM python:3.12-slim

WORKDIR /app

# build deps for cytoolz/eth-hash wheels + lru-dict (web3 dependency)
RUN apt-get update && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY ailottery_relayer ./ailottery_relayer
RUN pip install --no-cache-dir -e .

# the lottery config (sponsor.yaml) is mounted/copied at ../config in the repo;
# compose mounts it read-only at /app/config and sets SPONSOR_YAML.
ENV SPONSOR_YAML=/app/config/sponsor.yaml \
    ECONOMICS_YAML=/app/config/economics.yaml \
    SERVE_HOST=0.0.0.0 \
    SERVE_PORT=8090

RUN useradd -u 10001 -m relayer
USER 10001

EXPOSE 8090
HEALTHCHECK --interval=15s --timeout=4s --start-period=30s --retries=5 \
    CMD curl -fsS http://127.0.0.1:8090/healthz || exit 1

ENTRYPOINT ["python", "-m", "ailottery_relayer"]
CMD ["run"]
