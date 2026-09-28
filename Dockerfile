FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 user
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user backend ./backend
COPY --chown=user frontend ./frontend
RUN mkdir -p data && chown -R user /app

USER user
# Render passes the port in $PORT
ENV PORT=10000
EXPOSE 10000
CMD uvicorn backend.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips "*"
