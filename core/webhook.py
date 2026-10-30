from http.client import HTTPConnection
import json
import uuid

def fire_webhook(url, payload, port=None):
    try:
        body = json.dumps(payload).encode('utf-8')
        headers = {
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            }
        conn = HTTPConnection(url, port)
            
        # conn.request("POST", "/5af21cec-5a3c-4cbb-a25e-5c5b780dea8e", body=body, headers=headers)
        conn.request("POST", "/event", body=body, headers=headers)
        # conn.request("GET", "/home")
        response = conn.getresponse()
        if str(response.status).startswith("2"):
            print(f"{response.status}: {response.reason}")
            print(response.read().decode())
        else:
            return (response.status, response.reason)
        
    finally:
        conn.close()

payload = {
    "event": "subscriber.created",
    "data": {
        "subscriber_id": uuid.uuid4().hex,
        # "event_type":

        
    }

}