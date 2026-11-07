FROM python:3.11-slim

# Install system utilities: age CLI (as additional encryption tool), tar, gzip, docker CLI client
RUN apt-get update && apt-get install -y --no-install-recommends \
    age \
    tar \
    gzip \
    curl \
    ca-certificates \
    && curl -fsSL https://download.docker.com/linux/static/stable/x86_64/docker-26.1.4.tgz -o /tmp/docker.tgz \
    || true \
    && if [ -f /tmp/docker.tgz ]; then \
         tar -xzf /tmp/docker.tgz -C /tmp/ && mv /tmp/docker/docker /usr/local/bin/docker && rm -rf /tmp/docker* ; \
       fi \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source code
COPY backupbot/ /app/backupbot/

# Set environment
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

# Volumes for state persistence and working directory
VOLUME ["/var/lib/backupbot", "/var/tmp/backupbot"]

ENTRYPOINT ["python", "-m", "backupbot.cli"]
CMD ["run-scheduler"]
