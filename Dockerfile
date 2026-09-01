FROM python:3.12-slim-bookworm AS builder
WORKDIR /app
ARG APT_CACHE_DATE=1
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    gcc g++ build-essential pkg-config \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
# pip/setuptools/wheel are build-time only — the running app never imports
# them — so they're uninstalled right after installing requirements.txt.
# This is what actually closes the Trivy findings on pip's own vendored
# msgpack (pip bundles a copy for its internal HTTP cache; the latest pip
# release still ships a vulnerable version, so pinning/upgrading pip alone
# can't fix it) and on setuptools itself. Verified all of requirements.txt
# still imports fine with none of the three present.
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt \
    && python -m pip uninstall -y pip setuptools wheel

FROM python:3.12-slim-bookworm
ARG APT_CACHE_DATE=1
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --shell /bin/sh appuser
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
COPY . .
RUN chmod +x start.sh && chown -R appuser:appuser /app /opt/venv
USER appuser
CMD ["./start.sh"]
