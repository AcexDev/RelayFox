from http.client import HTTPSConnection, HTTPConnection
import json
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)

def fire_webhook(url: str, payload, port=None):
    # conn = None
    try:
        body = json.dumps(payload).encode('utf-8')
        headers = {
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            }
        conn = HTTPConnection(url, port)
            
        # conn.request("POST", "/5af21cec-5a3c-4cbb-a25e-5c5b780dea8e", body=body, headers=headers)
        conn.request("POST", "/events", body=body, headers=headers)
        
        response = conn.getresponse()
        
        print(f"{response.status}: {response.reason}")
        print(response.read().decode())
        
    finally:
        conn.close()

# fire_webhook("webhook.site", {"Case": "Test"})
# print(fire_webhook("localhost", payload={"Case": "Test"}, port=8000))

test_payload = {
    "event_type": "user.created",
    "event_id": "7a21d3f5-0d38-4cf2-a743-479c7g416b5f",
    "subscriber_id": 1,
    "payload": {
        "user": {
            "id": 21,
            "email":"zen@example.com",
            "name": "Zen Doe"
        }
    },
    "occured_at": datetime.now(timezone.utc).isoformat()
}

test_payload2 = {
    "event_type": "user.created",
    "event_id": "7a21d4g5-0d38-4cf2-a743-231c8d216b5n",
    "subscriber_id": 2,
    "payload": {
        "user": {
            "id": 22,
            "email":"testuser2@example.com",
            "name": "Test User"
        }
    },
    "occured_at": datetime.now(timezone.utc).isoformat()
}

fire_webhook("localhost", payload=test_payload, port=8000)
