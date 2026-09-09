FROM python:3.11-slim

WORKDIR /app

# 安装 IPQuality 脚本所需的必要 Linux 依赖: bash, curl, jq, netcat, bind9-host 等
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    curl \
    ca-certificates \
    jq \
    dnsutils \
    netcat-openbsd \
    iproute2 \
    procps \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

VOLUME ["/app/data"]

CMD ["python", "main.py"]
