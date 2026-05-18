FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir \
    "notion-client>=3.0.0" \
    "python-dotenv>=1.2.2" \
    "slack-sdk>=3.41.0"

COPY main.py .

ENTRYPOINT ["python", "/app/main.py"]
