FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt

COPY gateway.py ./
COPY shenyu_gateway ./shenyu_gateway
COPY admin/dist ./admin/dist

EXPOSE 8010

CMD ["uvicorn", "gateway:app", "--host", "0.0.0.0", "--port", "8010"]
