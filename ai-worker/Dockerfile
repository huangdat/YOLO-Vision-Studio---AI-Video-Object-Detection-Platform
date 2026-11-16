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
# PyTorch build: cpu (default) or cu126 for NVIDIA GPUs (docs/hybrid-tracking-gpu-architecture.md).
# The GPU build is several GB larger; it is only used with compose.gpu.yaml.
ARG TORCH_VARIANT=cpu
COPY requirements-ai-cpu.txt requirements-ai-cu126.txt requirements-ai.txt ./
RUN case "$TORCH_VARIANT" in cpu|cu126) ;; *) echo "TORCH_VARIANT must be cpu or cu126" >&2; exit 1;; esac \
    && pip install --no-cache-dir -r "requirements-ai-${TORCH_VARIANT}.txt" \
    && pip install --no-cache-dir -r requirements-ai.txt \
    && pip check
# Optional OpenVINO INT8 runtime (docs/quantization-phase2.md). Off by default, so the default image
# and its cached layers are unchanged; build with --build-arg INSTALL_OPENVINO=true to add it.
# INT8 is still only used when AI_MODEL_PRECISION=int8 and an exported artifact exists.
ARG INSTALL_OPENVINO=false
COPY requirements-quantization.txt ./
RUN if [ "$INSTALL_OPENVINO" = "true" ]; then \
        pip install --no-cache-dir -r requirements-quantization.txt && pip check; \
    elif [ "$INSTALL_OPENVINO" != "false" ]; then \
        echo "INSTALL_OPENVINO must be true or false" >&2; exit 1; \
    fi
COPY --chown=worker:worker app ./app
USER worker
