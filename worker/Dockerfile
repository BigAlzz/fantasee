# Python environment for the worker
FROM python:3.12-slim AS base

# Install FFmpeg and other dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY worker/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy worker source code
COPY worker/ ./worker/
COPY prisma/ ./prisma/

# Copy necessary scripts or DB check files if needed
COPY check_db.py .

# Environment variables
ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL="file:../dev.db"

# Command to run the worker
CMD ["python", "worker/main.py"]
