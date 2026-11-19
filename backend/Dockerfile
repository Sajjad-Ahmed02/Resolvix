# Resolvix backend image.
#
# The CPU-only PyTorch wheel is installed first so the image does not pull the
# much larger CUDA runtime while still satisfying the pinned requirements.
FROM python:3.14-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/home/resolvix/.cache/huggingface

# libgomp is required by the CPU PyTorch build.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 resolvix

WORKDIR /app

COPY requirements.txt ./
# Pin the +cpu local version explicitly: plain "torch==2.15.0" from PyPI pulls
# the CUDA runtime and NVIDIA wheels, which are unnecessary for CPU embeddings.
RUN pip install --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple "torch==2.15.0+cpu"
RUN pip install -r requirements.txt

COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
COPY scripts ./scripts
COPY docker/entrypoint.sh /usr/local/bin/resolvix-entrypoint

RUN chmod +x /usr/local/bin/resolvix-entrypoint \
    && mkdir -p /home/resolvix/.cache/huggingface \
    && chown -R resolvix:resolvix /app /home/resolvix

USER resolvix

EXPOSE 8000

ENTRYPOINT ["resolvix-entrypoint"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
