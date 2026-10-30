# receiver.py
from http.server import BaseHTTPRequestHandler, HTTPServer
import sys

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 9001


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)

        print("---- Received ----")
        print("Path:     ", self.path)
        print("Event ID: ", self.headers.get("X-RelayFox-Event-Id"))
        print("Signature:", self.headers.get("X-RelayFox-Signature"))
        print("Body:     ", body.decode("utf-8", errors="replace"))

        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()


if __name__ == "__main__":
    print(f"Receiver listening on http://localhost:{PORT}")
    HTTPServer(("localhost", PORT), Handler).serve_forever()