FROM python:3.9-slim

# تثبيت الأدوات الضرورية
RUN apt-get update && apt-get install -y \
    aria2 \
    p7zip-full \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

CMD ["python", "bot.py"]
