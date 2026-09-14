FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install system deps for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev && rm -rf /var/lib/apt/lists/*

# Install Python deps
RUN pip install --no-cache-dir alembic sqlalchemy psycopg2-binary python-dotenv

# Copy project files
COPY pyproject.toml ./
COPY src/ ./src/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY .env.example ./.env.example

# Install project in editable mode
RUN pip install --no-cache-dir -e .

# Load env vars at runtime
ENV PYTHONPATH=/app

ENTRYPOINT ["tail", "-f", "/dev/null"]