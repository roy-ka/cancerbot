FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
     build-essential \
     gcc \
     g++ \
     pkg-config \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -U pip wheel setuptools \
  && pip install --no-cache-dir -r requirements.txt \
  && pip install --no-cache-dir https://s3-us-west-2.amazonaws.com/ai2-s2-scispacy/releases/v0.5.4/en_core_sci_sm-0.5.4.tar.gz

COPY . .

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8011"]