# 1. Use a slim Python 3.12 image
FROM python:3.12-slim

# 2. Install system dependencies
# We add libglib2.0-0 and libgeos-dev for robust PDF/Image processing
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 3. Set working directory
WORKDIR /app

# 4. Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 5. Copy application code
COPY . .

# 6. Set environment variables
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1
# Ensure Flask knows it's in production mode
ENV FLASK_ENV=production

# 7. Expose port
EXPOSE 8000

# 8. Optimized Gunicorn Command
# --workers 1: Keeps RAM under 512MB
# --timeout 120: Gives Gemini plenty of time for deep extraction
# --threads 2: Allows the app to handle a web click while AI is processing
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "2", "--timeout", "120", "app:create_app()"]