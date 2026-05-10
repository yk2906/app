FROM python:3.11-alpine
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY fetch_and_notify.py .

ENTRYPOINT ["python", "/app/fetch_and_notify.py"]
