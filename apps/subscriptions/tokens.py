from django.core import signing


def unsubscribe_token(sub) -> str:
    return signing.dumps(sub.pk, salt="unsubscribe")


def read_unsubscribe(token: str):
    try:
        return signing.loads(token, salt="unsubscribe")
    except signing.BadSignature:
        return None


def confirm_token(sub, filters: dict, digest: bool, reminder_id=None) -> str:
    return signing.dumps({"s": sub.pk, "f": filters, "d": digest, "r": reminder_id}, salt="subscribe")


def read_confirm(token: str):
    try:
        return signing.loads(token, salt="subscribe", max_age=7 * 24 * 3600)
    except signing.BadSignature:
        return None
