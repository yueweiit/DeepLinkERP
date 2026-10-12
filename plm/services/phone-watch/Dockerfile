FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV HOST=0.0.0.0
ENV PORT=8000
ENV PYTHON_BIN=python3

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt \
    && python -m playwright install --with-deps chromium

COPY . .

EXPOSE 8000

CMD ["python", "-m", "phone_watch", "serve", "--host", "0.0.0.0", "--port", "8000"]
