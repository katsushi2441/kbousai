#!/usr/bin/env python3
"""行政の MCP と自社の MCP を並べて使う AI エージェントを、その場で動かして画面に見せるビューア。

録画（kargov）用。作り物の再生ではなく、ボタンを押すたびに本当に claude -p を起動し、
stream-json の1行ごとに SSE で画面へ流す。

  /usr/bin/python3 server.py [port]   既定 18348・127.0.0.1 のみ
  GET /           画面
  GET /run?q=...  エージェントを起動して、イベントを SSE で返す
"""
import json
import os
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
DEMO = os.path.dirname(HERE)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 18348
TOOLS = ",".join(["mcp__kbousai__bousai_ask", "mcp__kbousai__bousai_facts"] + [
    f"mcp__mlit__{t}" for t in ("search", "search_by_location_point_distance", "search_by_location_rectangle",
                               "get_data", "get_data_summary", "get_count_data", "search_by_attribute",
                               "get_data_catalog_summary", "normalize_codes")])


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/":
            body = open(os.path.join(HERE, "index.html"), "rb").read()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
            return
        if u.path == "/run":
            q = urllib.parse.parse_qs(u.query).get("q", [""])[0].strip()
            if not q:
                self.send_error(400, "q がありません"); return
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache"); self.end_headers()
            p = subprocess.Popen(
                ["claude", "-p", q, "--mcp-config", os.path.join(DEMO, "mcp.json"), "--strict-mcp-config",
                 "--allowedTools", TOOLS, "--output-format", "stream-json", "--verbose"],
                cwd=os.path.join(DEMO, "mlit-dpf-mcp"), stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            try:
                for line in p.stdout:
                    line = line.strip()
                    if line:
                        self.wfile.write(f"data: {line}\n\n".encode()); self.wfile.flush()
                self.wfile.write(b"event: done\ndata: {}\n\n"); self.wfile.flush()
            except BrokenPipeError:
                p.terminate()
            return
        self.send_error(404)


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
