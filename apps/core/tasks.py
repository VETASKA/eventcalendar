from celery import shared_task


@shared_task
def ping() -> str:
    """Health check for the worker: `celery -A config call apps.core.tasks.ping`."""
    return "pong"
