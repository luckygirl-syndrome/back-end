FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# torch 제외 먼저 설치 후, torch만 CUDA 휠로 설치 (pip이 CPU 휠로 덮어쓰지 않도록)
RUN pip install --upgrade pip && \
    grep -v "^torch==" requirements.txt > /tmp/req_no_torch.txt && \
    pip install -r /tmp/req_no_torch.txt && \
    pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cu121

COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
