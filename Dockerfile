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
COPY mikrotik_grabber ./mikrotik_grabber
COPY run.py .

# Create output directory for downloads
RUN mkdir -p /app/mikrotik_archive

# Expose volume for persistent downloads and manifest.json
VOLUME ["/app/mikrotik_archive"]

# Headless only - the GUI subcommand needs tkinter/a display, which this
# slim image intentionally doesn't have. Default: one watch check per run,
# suited to being invoked on a schedule (see docker-compose.yml / cron).
# Override with docker run ... python run.py --help for the full command set.
ENTRYPOINT ["python", "run.py"]
CMD ["watch", "--once", "--output", "/app/mikrotik_archive"]
