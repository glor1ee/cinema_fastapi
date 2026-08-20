#!/bin/bash
set -e

exec celery -A tasks.celery_app:celery_app worker --loglevel=info
