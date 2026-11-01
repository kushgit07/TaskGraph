# Dockerfile for the Render (Docker runtime) collapsed deployment.
# Runs orchestrator + worker as background loops inside the API process
# (deploy/render/app_combined.py) since Render's free tier doesn't offer
# a separate free background-worker service.
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY frontend ./frontend
COPY deploy/render/app_combined.py ./app_combined.py

ENV PORT=8000
EXPOSE 8000
CMD uvicorn app_combined:app --host 0.0.0.0 --port ${PORT}
