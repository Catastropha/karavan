FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/karavan

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p repos

EXPOSE 8000

RUN mkdir -p /root/.ssh
CMD ["sh", "-c", "chmod 600 /root/.ssh/id_ed25519 && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
