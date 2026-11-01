FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY frontend ./frontend

# The actual command differs per service — set in docker-compose.yml.
CMD ["python", "-m", "app.main_api"]
