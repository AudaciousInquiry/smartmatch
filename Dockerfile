FROM python:3.12-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install -r requirements.txt

# Copy the application
COPY . .

# Note: We aren't hardcoding env vars - let docker-compose handle them

# Default: Run FastAPI web service
CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8000"]

# Alternative: Uncomment this line and comment the above to run command-line mode
# Note: When switching back and forth, also need to run: docker compose down && docker compose up -d --build
# TODO: Maybe use a profile instead in the future...
# CMD ["python", "main.py"]

# For command-line with flags, use docker-compose override, e.g.:
# docker compose run app python main.py --email
