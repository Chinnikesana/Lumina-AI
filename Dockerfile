# Use official Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install system dependencies required for pdfium/pymupdf/spacy if needed
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt


# Copy the rest of the backend application
COPY . .

# Expose the port (Render uses the PORT environment variable)
EXPOSE $PORT

# Run the FastAPI application using Uvicorn
# We bind to 0.0.0.0 and use the PORT environment variable for Render compatibility
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
