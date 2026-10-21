# Base Image
FROM python:3.11-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.2.1 \
    POETRY_HOME="/opt/poetry"

# Poetry's bin directory must be on PATH. Declared in its own ENV so that
# $POETRY_HOME is already resolved when this instruction is evaluated.
# PYTHONPATH points at the src-layout root so `hesedbot.*` absolute imports
# resolve without installing the root package (`--no-root`).
ENV PATH="$POETRY_HOME/bin:$PATH" \
    PYTHONPATH="/app/src"

WORKDIR /app

# Install system dependencies for WeasyPrint and Poetry
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libcairo2 \
    libffi-dev \
    libxml2-dev \
    libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

# Copy project specification files
COPY pyproject.toml poetry.lock* ./

# Lock and install dependencies.
# `poetry lock` regenerates the lockfile inside the image to capture new
# dependencies (e.g., langgraph-checkpoint-redis). Poetry 2.x is required
# because pyproject.toml uses the PEP 621 `[project]` table (poetry-core 2.x).
# No `--without dev`: the project has no dev dependency group.
RUN poetry config virtualenvs.create false \
    && poetry lock \
    && poetry install --no-root

# Copy application source code
COPY src/ ./src/

# Expose API Port
EXPOSE 5000

# Launch Gunicorn
# CRITICAL: Do NOT use --preload. It breaks Redis checkpointer fork-safety.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "hesedbot.api.chat:app"]
