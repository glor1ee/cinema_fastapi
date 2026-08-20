FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.5 \
    POETRY_VIRTUALENVS_CREATE=false

WORKDIR /usr/src/app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev dos2unix \
    && rm -rf /var/lib/apt/lists/*

RUN pip install "poetry==${POETRY_VERSION}"

# Dependencies are installed before the source is copied, so editing code does
# not invalidate the cached dependency layer.
COPY pyproject.toml poetry.lock* ./
RUN poetry install --no-root --no-interaction --no-ansi

COPY alembic.ini pytest.ini ./
COPY commands ./commands
COPY src ./src

RUN dos2unix ./commands/*.sh && chmod +x ./commands/*.sh

ENV PYTHONPATH=/usr/src/app/src

EXPOSE 8000
