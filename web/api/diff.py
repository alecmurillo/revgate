import json
import sys
import os
import tempfile
import subprocess
from http.server import BaseHTTPRequestHandler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            data = json.loads(body)
            old_csv = data.get("oldCsv", "")
            new_csv = data.get("newCsv", "")
            today = data.get("today", "")

            old_tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
            old_tmp.write(old_csv)
            old_tmp.close()

            new_tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w")
            new_tmp.write(new_csv)
            new_tmp.close()

            args = [sys.executable, "-m", "revgate", "diff", old_tmp.name, new_tmp.name,
                    "--format", "json", "--no-record"]
            if today:
                args.extend(["--today", today])

            result = subprocess.run(args, capture_output=True, text=True,
                                     env={**os.environ, "PYTHONPATH": os.path.dirname(os.path.dirname(os.path.abspath(__file__)))})
            os.unlink(old_tmp.name)
            os.unlink(new_tmp.name)

            try:
                output = json.loads(result.stdout)
                self._send_json(200, output)
            except json.JSONDecodeError:
                self._send_json(500, {"error": "Failed to parse diff output",
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
