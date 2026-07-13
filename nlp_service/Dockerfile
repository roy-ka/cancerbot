FROM python:3.12-slim

WORKDIR /app

ARG APT_CACHE_DATE=1
RUN apt-get update && apt-get upgrade -y && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# Install scispacy without its entity-linking deps (nmslib-metabrainz fails to build on ARM)
RUN pip install --no-cache-dir --no-deps scispacy==0.5.5 \
 && pip install --no-cache-dir -r requirements.txt

COPY app.py synonyms.py .

RUN adduser --disabled-password --gecos "" appuser
USER appuser

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100"]
