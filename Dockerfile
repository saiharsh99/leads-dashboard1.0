FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ backend/
COPY static/ static/

# Persist the SQLite DB outside the image layer; mount a volume here on hosts
# that support it (Render/Railway/Fly disks) so uploads survive redeploys.
ENV LEADS_DB_PATH=/data/leads.db
RUN mkdir -p /data
VOLUME /data

WORKDIR /app/backend
EXPOSE 8100
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8100}"]
