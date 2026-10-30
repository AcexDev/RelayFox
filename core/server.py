# core/server.py
import json
import logging
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

from .logging_config import setup_logging
from .migrations import run_migrations
from .schema import db_conn
from .worker import add_to_queue, worker, scheduler, recover_events, shutdown
import threading
import os
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MAX_BODY_BYTES = 1_000_000  # 1 MB
HOST, PORT = "localhost", 8000

WORKER_COUNT = int(os.getenv("WORKER_COUNT", "2"))


class WebhookRequestHandler(BaseHTTPRequestHandler):
    def _send_json(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json_body(self):
        """Return (data, None) on success or (None, (status, error_body)) on failure."""
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            return None, (411, {"Error": "Content-Length header required"})

        if length <= 0:
            return None, (400, {"Error": "Request body is empty"})
        if length > MAX_BODY_BYTES:
            return None, (413, {"Error": "Request body too large"})

        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            logger.warning("Malformed JSON rejected: %s", e)
            return None, (400, {"Error": "Invalid JSON"})

        if not isinstance(data, dict):
            logger.warning("Rejected body: not a JSON object")
            return None, (400, {"Error": "Body must be a JSON object"})

        return data, None

    def do_GET(self):
        if self.path == "/":
            self._send_json(200, {"Service": "RelayFox", "Status": "Active"})
        else:
            self._send_json(404, {"Error": "Page not found"})

    def do_POST(self):
        if self.path != "/events":
            self._send_json(404, {"Error": "Page not found"})
            return

        raw_data, error = self._read_json_body()
        if error:
            self._send_json(*error)
            return

        status, body = handle_events(raw_data)
        self._send_json(status, body)


def handle_events(raw_data):
    subscriber_id = raw_data.get("subscriber_id")
    if not subscriber_id:
        logger.warning("Rejected event: missing subscriber_id")
        return 400, {"Error": "subscriber_id is required"}

    payload = json.dumps(raw_data.get("payload", {}))
    created_at = datetime.now(timezone.utc).isoformat()
    conn = None

    try:
        conn, cursor = db_conn()

        cursor.execute(
            "SELECT 1 FROM subscribers WHERE id = ? AND enabled = '1'",
            (subscriber_id,),
        )
        if cursor.fetchone() is None:
            logger.warning("Rejected event: unknown subscriber %s", subscriber_id)
            return 404, {"Error": "Unknown subscriber"}

        cursor.execute(
            """INSERT INTO events(subscriber_id, payload, status, created_at)
               VALUES(?, ?, ?, ?)""",
            (subscriber_id, payload, "queued", created_at),
        )
        event_id = cursor.lastrowid
        conn.commit()
        logger.info("Event %s stored for subscriber %s", event_id, subscriber_id)

        if add_to_queue(event_id):
            return 202, {"event_id": event_id, "status": "queued"}
        return 503, {"event_id": event_id, "status": "queue_full"}

    except Exception:
        if conn:
            conn.rollback()
        logger.exception("Failed to handle event for subscriber %s", subscriber_id)
        return 500, {"Error": "Internal Server Error"}

    finally:
        if conn:
            conn.close()


def init_db():
    conn, _ = db_conn()
    try:
        run_migrations(conn)
    finally:
        conn.close()


def run():
    setup_logging()
    logger.info("Server starting...")
    init_db()
    recover_events()

    threads = [threading.Thread(target=worker) for _ in range(WORKER_COUNT)]
    threads.append(threading.Thread(target=scheduler))
    for t in threads:
        t.start()

    httpd = HTTPServer((HOST, PORT), WebhookRequestHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        httpd.server_close()   # stop accepting requests
        shutdown.set()         # tell workers and scheduler to stop
        for t in threads:
            t.join(timeout=10)
            if t.is_alive():
                logger.warning("Thread %s did not stop", t.name)
        logger.info("Shutdown complete")


if __name__ == "__main__":
    run()