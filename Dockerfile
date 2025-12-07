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

# Use Python directly - more reliable on Railway
CMD ["python", "app.py"]
