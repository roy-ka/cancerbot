FROM python:3.12-slim

WORKDIR /app

# Inside /app (not root's home) so it survives the chown below and is
# readable by appuser at runtime — the download itself happens as root,
# before the user switch.
ENV HF_HOME=/app/.cache/huggingface

ARG APT_CACHE_DATE=1
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# CPU-only torch first: pip's default index has no GPU on this container to
# serve, but installs the full CUDA-bundled wheel anyway (~5GB of nvidia-*
# packages) unless the CPU wheel is already satisfied before
# sentence-transformers pulls torch in as a transitive dependency below.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu
# Install scispacy without its entity-linking deps (nmslib-metabrainz fails to build on ARM)
RUN pip install --no-cache-dir --no-deps scispacy==0.5.5 \
 && pip install --no-cache-dir -r requirements.txt

# Bake the reranker model into the image at build time — matches
# en_core_sci_sm's build-time install above, so app.py's eager load at
# startup never hits the network (would otherwise race the 60s healthcheck
# start_period, or fail outright with no egress).
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

COPY app.py synonyms.py .

RUN adduser --disabled-password --gecos "" appuser \
 && chown -R appuser:appuser /app
USER appuser

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
