FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps for psycopg2 + lzma
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev liblzma-dev && rm -rf /var/lib/apt/lists/*

# Install Python deps
RUN pip install --no-cache-dir alembic sqlalchemy psycopg2-binary python-dotenv

# Install crawler dependencies (httpx, beautifulsoup4, lxml)
RUN pip install --no-cache-dir httpx beautifulsoup4 lxml

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY .env.example ./.env.example

# Install ingestor project
RUN pip install --no-cache-dir -e .

# Crawler source is mounted as volume at runtime (docker-compose.yml)
# PYTHONPATH includes /app/crawler for importing crawler_dadosabertos_cwb
ENV PYTHONPATH=/app:/app/crawler

# Default: run scheduler (ingestao 1x/dia via INGESTION_SCHEDULE)
# Override for manual: docker compose run --rm --entrypoint python app -m src.ingestor --once
ENTRYPOINT ["python", "-m", "src.ingestor"]
CMD []