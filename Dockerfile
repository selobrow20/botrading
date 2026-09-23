# Gunakan Python 3.12 slim sebagai base image
FROM python:3.12-slim

# Set timezone ke Asia/Jakarta (WIB) agar jam bursa tepat
ENV TZ=Asia/Jakarta
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install tzdata dan dependensi sistem
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    curl \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set direktori kerja
WORKDIR /app

# Salin dependensi dan install
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Salin seluruh kode proyek
COPY . .

# Buat direktori data, logs, dan reports
RUN mkdir -p /app/data /app/logs /app/reports

# Jalankan Scheduler Jam Bursa dan Listener Telegram bersamaan
CMD ["python", "main.py", "run-all"]
