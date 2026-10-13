# AI-Agent Oracle Lottery — example autonomous agent participant
FROM python:3.12-slim

WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml ./
COPY ailottery_agent ./ailottery_agent
RUN pip install --no-cache-dir -e .

RUN useradd -u 10001 -m agent
USER 10001

ENTRYPOINT ["python", "-m", "ailottery_agent"]
