# core/worker.py
import hashlib
import hmac
import json
import logging
import queue

import httpx
from datetime import datetime, timezone, timedelta

from .schema import db_conn
import random

import time
import threading

shutdown = threading.Event()

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5
MAX_ATTEMPTS = 5
BACKOFF_SECONDS = [10, 30, 120, 600, 3600]
SCHEDULER_INTERVAL = 5  # seconds

# Shared queue: server.py adds to it, workers read from it.
events = queue.Queue()


def add_to_queue(event_id) -> bool:
    if not event_id:
        logger.warning("add_to_queue called without an event_id")
        return False
    try:
        events.put_nowait(event_id)
    except queue.Full:
        logger.warning("Queue full, could not enqueue event %s", event_id)
        return False
    logger.info("Event queued: %s", event_id)
    return True


def process_event(event_id):
    if not event_id:
        logger.warning("Event ID not provided, worker can't process")
        return None

    conn = None
    try:
        conn, cursor = db_conn()
        cursor.execute("""
            SELECT e.payload, s.url, s.secret
            FROM events e JOIN subscribers s ON s.id = e.subscriber_id
            WHERE e.id = ?
        """, (event_id,))
        row = cursor.fetchone()

        if row is None:
            logger.warning("Event %s or its subscriber not found", event_id)
            return None

        payload, url, secret = row
        return payload, url, secret

    except Exception:
        logger.exception("Failed to load event %s", event_id)
        return None

    finally:
        if conn:
            conn.close()


def build_request(event_id, payload, url, secret):
    if not event_id:
        logger.warning("Event ID not provided")
        return None
    if not payload:
        logger.warning("Payload not provided for event %s", event_id)
        return None
    if not url:
        logger.warning("URL not provided for event %s", event_id)
        return None
    if not secret:
        logger.warning("Secret not provided for event %s", event_id)
        return None

    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.exception("Stored payload for event %s is not valid JSON", event_id)
        return None

    body = json.dumps(data, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    headers = {
        "Content-Type": "application/json",
        "X-RelayFox-Event-Id": str(event_id),
        "X-RelayFox-Signature": f"sha256={signature}",
    }
    return body, headers


def send_request(event_id, url, body, headers):
    """Return (status_code, error_message). One of them is None."""
    try:
        response = httpx.post(
            url,
            content=body,
            headers=headers,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
        )
    except httpx.TimeoutException:
        logger.warning("Timeout delivering event %s to %s", event_id, url)
        return None, "timeout"
    except httpx.HTTPError as e:
        logger.warning("Network error delivering event %s: %s", event_id, e)
        return None, str(e)

    logger.info("Event %s -> %s returned %s", event_id, url, response.status_code)
    return response.status_code, None

def record_attempt(event_id, status_code, error):
    conn = None
    try:
        conn, cursor = db_conn()
        cursor.execute("SELECT COUNT(*) FROM attempts WHERE event_id = ?", (event_id,))
        attempt_number = cursor.fetchone()[0] + 1

        cursor.execute(
            """INSERT INTO attempts
               (event_id, attempt_number, status_code, error_message, attempted_at)
               VALUES (?, ?, ?, ?, ?)""",
            (event_id, attempt_number, status_code, error,
             datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        logger.info("Attempt %s recorded for event %s", attempt_number, event_id)
        return attempt_number
    except Exception:
        logger.exception("Failed to record attempt for event %s", event_id)
        return None
    finally:
        if conn:
            conn.close()

def set_status(event_id, status):
    conn = None
    try:
        conn, cursor = db_conn()
        cursor.execute(
            "UPDATE events SET status = ? WHERE id = ?", (status, event_id)
        )
        conn.commit()
        logger.info("Event %s marked %s", event_id, status)
    except Exception:
        logger.exception("Failed to set event %s to %s", event_id, status)
    finally:
        if conn:
            conn.close()

def classify(status_code, error):
    """Return 'success', 'retry', or 'permanent'."""
    if status_code is None:
        return "retry"  # timeout / network error
    if 200 <= status_code < 300:
        return "success"
    if status_code == 429 or status_code >= 500:
        return "retry"
    return "permanent"  # other 4xx (and unexpected 1xx/3xx)


def schedule_retry(event_id, attempt_number):
    delay = BACKOFF_SECONDS[min(attempt_number - 1, len(BACKOFF_SECONDS) - 1)]
    delay += random.uniform(0, delay * 0.1)  # small jitter
    next_at = datetime.now(timezone.utc) + timedelta(seconds=delay)

    conn = None
    try:
        conn, cursor = db_conn()
        cursor.execute(
            "UPDATE events SET status = 'pending', next_attempt_at = ? WHERE id = ?",
            (next_at.isoformat(), event_id),
        )
        conn.commit()
        logger.info("Event %s retry %d scheduled in %.0fs", event_id, attempt_number, delay)
    except Exception:
        logger.exception("Failed to schedule retry for event %s", event_id)
    finally:
        if conn:
            conn.close()


def requeue_due_events():
    conn = None
    try:
        conn, cursor = db_conn()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """SELECT id FROM events
               WHERE status = 'pending' AND next_attempt_at IS NOT NULL
                 AND next_attempt_at <= ?""",
            (now,),
        )
        due = [row[0] for row in cursor.fetchall()]

        for event_id in due:
            # Clear the timestamp first so the next sweep can't pick it up again
            cursor.execute(
                "UPDATE events SET next_attempt_at = NULL WHERE id = ?", (event_id,)
            )
            conn.commit()
            if add_to_queue(event_id):
                logger.info("Event %s re-queued for retry", event_id)
            else:
                # Queue full: put it back to be picked up on a later sweep
                cursor.execute(
                    "UPDATE events SET next_attempt_at = ? WHERE id = ?", (now, event_id)
                )
                conn.commit()
    except Exception:
        logger.exception("Scheduler sweep failed")
    finally:
        if conn:
            conn.close()


def scheduler():
    while not shutdown.is_set():
        requeue_due_events()
        shutdown.wait(SCHEDULER_INTERVAL)

def recover_events():
    """Run once at startup, before workers start. Nothing is in flight yet,
    so any 'queued' or 'processing' row is left over from a previous run."""
    conn = None
    try:
        conn, cursor = db_conn()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """UPDATE events
               SET status = 'pending', next_attempt_at = ?
               WHERE status IN ('queued', 'processing')
                  OR (status = 'pending' AND next_attempt_at IS NULL)""",
            (now,),
        )
        conn.commit()
        logger.info("Recovery: %d event(s) reset for delivery", cursor.rowcount)
    except Exception:
        logger.exception("Recovery failed")
    finally:
        if conn:
            conn.close()

def claim_event(event_id):
    """Return True if this worker won the event, False if someone else has it."""
    conn = None
    try:
        conn, cursor = db_conn()
        cursor.execute(
            """UPDATE events SET status = 'processing'
               WHERE id = ? AND status IN ('queued', 'pending')""",
            (event_id,),
        )
        conn.commit()
        return cursor.rowcount == 1
    except Exception:
        logger.exception("Failed to claim event %s", event_id)
        return False
    finally:
        if conn:
            conn.close()

def worker():
    while not shutdown.is_set():
        try:
            event_id = events.get(timeout=1)
        except queue.Empty:
            continue

        try:
            if not claim_event(event_id):
                logger.info("Event %s already claimed or finished, skipping", event_id)
                continue

            row = process_event(event_id)
            if row is None:
                set_status(event_id, "failed")
                continue
            payload, url, secret = row

            request = build_request(event_id, payload, url, secret)
            if request is None:
                set_status(event_id, "failed")
                continue
            body, headers = request

            status_code, error = send_request(event_id, url, body, headers)
            attempt_number = record_attempt(event_id, status_code, error)

            outcome = classify(status_code, error)
            if outcome == "success":
                set_status(event_id, "delivered")
            elif outcome == "retry" and attempt_number and attempt_number < MAX_ATTEMPTS:
                schedule_retry(event_id, attempt_number)
            else:
                set_status(event_id, "failed")

        except Exception:
            logger.exception("Worker failed on event %s", event_id)

        finally:
            events.task_done()