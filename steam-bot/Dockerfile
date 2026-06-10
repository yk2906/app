FROM python:3.11-alpine
ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache git

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY batch_sync.py .

CMD ["python", "main.py"]