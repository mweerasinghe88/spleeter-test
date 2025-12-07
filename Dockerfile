FROM python:3.10-slim

# Install ffmpeg
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY . .

EXPOSE 5000

# Use shell to expand $PORT, fallback to 5000
CMD ["/bin/sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-5000} --timeout 300 --workers 1 app:app"]
