FROM python:3.10-slim

# Install system dependencies for libraw
RUN apt-get update && apt-get install -y \
    libraw-dev libglib2.0-0 gcc g++ \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

EXPOSE 3000
CMD ["python", "app.py"]

