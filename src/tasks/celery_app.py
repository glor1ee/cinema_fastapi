from celery import Celery
from celery.schedules import crontab

from config.settings import Settings

settings = Settings()

celery_app = Celery(
    "online_cinema",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["tasks.tokens"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


celery_app.conf.beat_schedule = {
    "purge-expired-tokens-every-hour": {
        "task": "tasks.tokens.purge_expired_tokens",
        "schedule": crontab(minute=0),
    },
}
