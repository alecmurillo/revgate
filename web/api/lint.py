import json
import sys
import os
import tempfile
import subprocess
from http.server import BaseHTTPRequestHandler

# Add the parent directory to sys.path so we can import revgate
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
            csv_content = data.get("csv", "")
            today = data.get("today", "")

            # Write CSV to temp file
            tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
            tmp.write(csv_content)
            tmp.close()

            # Run revgate lint
            args = [sys.executable, "-m", "revgate", "lint", tmp.name,
                    "--format", "json", "--no-record"]
            if today:
                args.extend(["--today", today])

            result = subprocess.run(args, capture_output=True, text=True,
                                     env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))})
            os.unlink(tmp.name)

            try:
                output = json.loads(result.stdout)
                self._send_json(200, output)
            except json.JSONDecodeError:
                self._send_json(500, {"error": "Failed to parse revgate output",
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
