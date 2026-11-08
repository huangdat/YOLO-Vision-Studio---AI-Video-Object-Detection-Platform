FROM python:3.11-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    AI_DEVICE=auto \
    AI_MODEL_CACHE_DIR=/data/models \
    AI_TEMP_DIR=/data/temp \
    AI_OUTPUT_DIR=/data/outputs \
    AI_LOCAL_INPUT_DIR=/data/inputs \
    AI_CPU_THREADS=4 \
    OMP_NUM_THREADS=4

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 worker \
    && mkdir -p /data/models /data/temp /data/outputs /data/inputs \
    && chown -R worker:worker /data

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('AI_WORKER_PORT', '8000') + '/health', timeout=3)"

CMD ["python", "-m", "app"]

# Optional lightweight HTTP image: docker build --target base ...
FROM runtime AS base
COPY --chown=worker:worker app ./app
USER worker

# Default image includes CPU inference dependencies, but loads no models at startup.
FROM runtime AS cpu
COPY requirements-ai-cpu.txt requirements-ai.txt ./
RUN pip install --no-cache-dir -r requirements-ai-cpu.txt \
    && pip install --no-cache-dir -r requirements-ai.txt \
    && pip check
COPY --chown=worker:worker app ./app
USER worker
