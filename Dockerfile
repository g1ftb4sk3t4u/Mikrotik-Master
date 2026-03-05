FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY mikrotik_master.py .
COPY run.py .

# Create output directory for downloads
RUN mkdir -p /app/mikrotik_archive

# Set default environment variables (can be overridden at runtime)
ENV OUTPUT_DIR=/app/mikrotik_archive \
    START_VERSION=3.31.1 \
    END_VERSION=7.50 \
    TEST_WORKERS=16 \
    DL_WORKERS=8 \
    MAX_RETRIES=3

# Expose volume for persistent downloads and JSON state
VOLUME ["/app/mikrotik_archive"]

# Default to CLI mode with full scan
# Override with docker run ... python run.py --help for usage
ENTRYPOINT ["python", "run.py"]
CMD ["--cli", "--output", "/app/mikrotik_archive", "--start", "3.31.1", "--end", "7.50", "--test-workers", "16", "--dl-workers", "8"]
