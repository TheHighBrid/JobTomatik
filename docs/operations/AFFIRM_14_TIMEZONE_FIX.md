# Affirm application #14 timezone fix (A path)

## Root cause

`backend/app/services/supervised_submission.py`:

```python
def _now() -> datetime:
    return datetime.utcnow()  # naive
```

`backend/app/models/submission_approval.py`:

```python
expires_at = Column(DateTime(timezone=True), ...)
approved_at = Column(DateTime(timezone=True), ...)
```

Every comparison `approval.expires_at <= now` raised:

```text
TypeError: can't compare offset-naive and offset-aware datetimes
```

This stopped both the backend one-click handler and the Celery worker.
Task `33a419ca-36ed-4be0-8e7e-60ce39ef64a1` failed. Application stayed `ready_to_apply`.

## Required code change

In `backend/app/services/supervised_submission.py`:

1. Change the import:

```python
# from
from datetime import datetime, timedelta
# to
from datetime import datetime, timedelta, timezone
# OR (preferred once time_utils lands):
from app.services.time_utils import utc_now
```

2. Replace `_now`:

```python
def _now() -> datetime:
    """Return timezone-aware UTC now.

    SubmissionApproval timestamp columns are DateTime(timezone=True).
    Naive utcnow() caused TypeError on Affirm #14.
    """
    return datetime.now(timezone.utc)
    # or: return utc_now()
```

No other behavior change. No gate or approval ceremony change.

## Parity requirement

After merge:

1. Rebuild **backend and celery_worker** from the **same** commit/image digest.
2. Confirm both containers report the same image ID.
3. Only then re-issue the Affirm #14 supervised submission.

Image drift was the second half of the 10 Oct failure (backend fixed, worker still stale).

## Verification before claiming success

- Approval issuance and validation no longer raise TypeError.
- Worker consumes the task without the datetime exception.
- Application state and evidence are recorded honestly.
- Employer confirmation (thank-you page / confirmation text / ATS ID) is required before status `confirmed`.
- Queued / task success / click are **not** treated as confirmed.

## Next (B)

After A is proven, carve an owner-authorized final-action path that does not force the short-lived approval ceremony for ordinary owner-authorized work, while keeping auth, ownership, idempotency, and evidence.
