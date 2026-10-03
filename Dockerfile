FROM python:3.12-slim

# ffmpeg for clipping / transcoding
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY engine/ engine/
COPY app/ app/
COPY web/ web/
COPY README.md .

ENV LLM_PROVIDER=gemini
# Render injects $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port $PORT"]
