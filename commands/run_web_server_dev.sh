#!/bin/bash
set -e

echo "Applying database migrations..."
alembic upgrade head

echo "Starting the development server..."
exec uvicorn main:app --host 0.0.0.0 --port 8000 --reload --app-dir /usr/src/app/src
