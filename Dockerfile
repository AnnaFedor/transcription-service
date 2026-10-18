# syntax=docker/dockerfile:1

ARG WHISPER_MODEL=small

# --- builder: install locked dependencies into /app/.venv -------------------------------------------------------
FROM python:3.13-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies first so this layer stays cached while only application code changes.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app/ app/
COPY main.py ./

# --- model: download the Whisper weights at build time -----------------------------------------------------------
FROM builder AS model
ARG WHISPER_MODEL
# The download runs as root and leaves some cache files owner-only; make them readable for the non-root runtime user.
RUN .venv/bin/python -c "from faster_whisper import WhisperModel; WhisperModel('${WHISPER_MODEL}', device='cpu', compute_type='int8', download_root='/models')" \
    && chmod -R a+rX /models

# --- runtime: slim image with venv, code and model, running as non-root ----------------------------------------
FROM python:3.13-slim AS runtime
ARG WHISPER_MODEL
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app \
    && mkdir /data && chown app /data
WORKDIR /app
COPY --from=builder /app/.venv .venv
COPY --from=builder /app/app app
COPY --from=builder /app/main.py .
COPY --from=model /models /models

ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    HOST=0.0.0.0 \
    PORT=8000 \
    WHISPER_MODEL=${WHISPER_MODEL} \
    WHISPER_DOWNLOAD_ROOT=/models \
    HF_HUB_OFFLINE=1

USER app
EXPOSE 8000
VOLUME /data
# slim images have no curl, so the healthcheck uses Python's standard library.
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status == 200 else 1)"
CMD ["python", "main.py"]
