# Use an official Python runtime as a base image
FROM python:3.12-slim

# Install system dependencies for pyrosm and geopandas
RUN apt-get update && apt-get install -y \
    build-essential \  
    libspatialindex-dev \
    gdal-bin \
    libgdal-dev \
    spatialite-bin \
    redis-server \
    && rm -rf /var/lib/apt/lists/*

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# Set work directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose the Flask port
EXPOSE 5000

# Run the application
CMD ["python", "app.py"]
