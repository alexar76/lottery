# AI-Agent Oracle Lottery — anvil chain + one-shot contract deploy.
# Same image serves both compose services:
#   chain  → `entrypoint: anvil` (local EVM)
#   deploy → default entrypoint runs docker-deploy.sh (forge script → /shared)
FROM ghcr.io/foundry-rs/foundry:v1.3.1

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl jq bash ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY src ./src
COPY script ./script
COPY test ./test
COPY foundry.docker.toml ./foundry.toml
COPY docker-deploy.sh ./docker-deploy.sh
RUN chmod +x docker-deploy.sh

# Dependencies (OZ 5.6.1 + forge-std) are resolved at RUN time by docker-deploy.sh
# so it can prefer the monorepo's vendored libs when they are mounted.
ENTRYPOINT ["bash", "./docker-deploy.sh"]
