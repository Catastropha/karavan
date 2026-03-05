FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git openssh-client \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash karavan

WORKDIR /opt/karavan

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p repos && chown -R karavan:karavan /opt/karavan

USER karavan
RUN mkdir -p /home/karavan/.ssh

EXPOSE 8000

CMD ["sh", "-c", "cp /tmp/ssh_key/id_ed25519 /home/karavan/.ssh/id_ed25519 && chmod 600 /home/karavan/.ssh/id_ed25519 && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
