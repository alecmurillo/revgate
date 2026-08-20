import json
import sys
import os
import subprocess
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        try:
            args = [sys.executable, "-m", "revgate", "redteam",
                    "--target", "demo", "--format", "json", "--no-record"]

            result = subprocess.run(args, capture_output=True, text=True,
                                     env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))})

            try:
                output = json.loads(result.stdout)
                self._send_json(200, output)
            except json.JSONDecodeError:
                self._send_json(500, {"error": "Failed to parse redteam output",
                                      "stdout": result.stdout[:500],
                                      "stderr": result.stderr[:500]})
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
