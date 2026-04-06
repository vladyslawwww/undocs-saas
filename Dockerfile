# Use a slim Python 3.12 image
FROM python:3.12-slim

# Install system dependencies for PyMuPDF and Postgres
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Set environment variables for production
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

# Expose port 8000
EXPOSE 8000

# Use Gunicorn as the production-grade WSGI server
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:create_app()"]