"""
Standalone HTTP Server for NexusGrid Tactics (Multiplayer Turn-Based Strategy for Humans & AI Agents).
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import strategy_game_engine


class GameHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle(self, method: str):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/game"
        if route in ("/", "/game", "/index.html"):
            body = strategy_game_engine.GAME_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        params = {k: v[0] for k, v in parse_qs(parsed.query).items() if v}
        if method == "POST":
            length = int(self.headers.get("Content-Length", "0") or "0")
            if 0 < length <= 65536:
                raw = self.rfile.read(length)
                try:
                    params.update(json.loads(raw.decode("utf-8")))
                except Exception:
                    pass
        st, out = strategy_game_engine.handle_game_api(method, route, params)
        body = json.dumps(out, indent=2).encode("utf-8")
        self.send_response(st)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("0.0.0.0", 8402), GameHandler)
    print("NexusGrid Tactics server listening on http://127.0.0.1:8402/game")
    srv.serve_forever()
