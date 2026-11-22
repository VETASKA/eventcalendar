"""Background work for the intake queue."""
import logging

from celery import shared_task
from django.db import transaction
from django.utils import timezone

from .fetcher import safe_fetch
from .models import IntakeItem
from .parser import parse

logger = logging.getLogger(__name__)
RETRY_MINUTES = [5, 30, 120]          # a site that is down gets three more tries over ~2.5 hours


@shared_task(bind=True, max_retries=len(RETRY_MINUTES), acks_late=True)
def fetch_page(self, item_id: int) -> str:
    """Fetch a suggested link, read the event from it and put the result into the moderation queue."""
    from .services import process

    item = IntakeItem.objects.filter(pk=item_id).first()
    if item is None or not item.url:
        return "gone"
    r = safe_fetch(item.url)
    fetch = {"at": timezone.now().isoformat(), "final_url": r.url, "status": r.status, "error": r.error}
    parsed = None
    if r.ok:
        parsed = parse(r.html, r.url)
    elif r.temporary:
        if self.request.retries < self.max_retries:
            IntakeItem.objects.filter(pk=item_id).update(status="fetch_error", reason=f"повтор: {r.error}"[:500],
                                                         attempts=item.attempts + 1)
            if self.request.is_eager:       # tests / local runs without a worker: retry at once
                return fetch_page.apply(args=[item_id], retries=self.request.retries + 1).result
            raise self.retry(countdown=RETRY_MINUTES[self.request.retries] * 60)
        fetch["gave_up"] = True
    else:
        fetch["permanent"] = True

    with transaction.atomic():
        item = IntakeItem.objects.select_for_update().get(pk=item_id)
        item.payload = {**item.payload, "fetch": fetch, **({"parsed": parsed} if parsed else {})}
        item.attempts += 1
        process(item)
    logger.info("fetched %s → %s", item.url, item.status)
    return item.status
