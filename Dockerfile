FROM python:3.12-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the application
COPY . .

# Note: We aren't hardcoding env vars - let docker-compose handle them

CMD ["python", "main.py"]
