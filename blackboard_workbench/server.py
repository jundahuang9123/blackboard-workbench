"""Local-only HTTP application. No third-party dependency for viewing/reviewing."""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import sys
from urllib.parse import urlsplit
from .adapter import demo
from .store import Store, Conflict
from .jobs import Jobs


class App:
    def __init__(self, data_dir, upstream=None, python=None):
        self.store = Store(Path(data_dir) / "workbench.sqlite3")
        self.jobs = Jobs(self.store, data_dir, upstream, python)
        self.token = secrets.token_urlsafe(32)


def handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def response(self, status, value, content_type="application/json", attachment=None):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode() if content_type == "application/json" else value
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if attachment:
                self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
            self.end_headers()
            self.wfile.write(body)

        def check_host(self):
            host = self.headers.get("Host", "")
            if host not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}:
                raise PermissionError("Localhost access only.")
            origin = self.headers.get("Origin")
            if origin and origin != f"http://{host}":
                raise PermissionError("Cross-origin requests are not allowed.")

        def do_GET(self):
            self.dispatch(False)

        def do_POST(self):
            self.dispatch(True)

        def dispatch(self, post):
            try:
                self.check_host()
                route = urlsplit(self.path).path
                parts = route.strip("/").split("/")
                body = None
                if post:
                    if not hmac.compare_digest(self.headers.get("X-Workbench-Token", ""), app.token):
                        raise PermissionError("Refresh the workbench before submitting.")
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 1 or length > 20_000_000:
                        raise ValueError("Request must be between 1 byte and 20 MB.")
                    body = json.loads(self.rfile.read(length), parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Non-finite JSON numbers are not supported.")))
                    if not isinstance(body, dict):
                        raise ValueError("Expected a JSON object.")
                if route == "/api/config" and not post:
                    self.response(200, {"token": app.token, **app.jobs.setup()})
                elif route == "/api/runs" and not post:
                    self.response(200, app.store.list_runs())
                elif route == "/api/import" and post:
                    self.response(201, app.store.import_run(body.get("raw"), body.get("title")))
                elif route == "/api/demo" and post:
                    self.response(201, app.store.import_run(demo(), "Coordinate example · synthetic demo", "synthetic_demo"))
                elif len(parts) in {3, 4} and parts[:2] == ["api", "runs"] and not post:
                    run = app.store.run(parts[2])
                    if len(parts) == 4 and parts[3] == "export":
                        self.response(200, {"schema": "blackboard-review-bundle-v1", "run": run}, attachment=f"blackboard-review-{run['id'][:8]}.json")
                    elif len(parts) == 3:
                        self.response(200, run)
                    else:
                        raise KeyError("Route not found.")
                elif len(parts) == 6 and parts[:2] == ["api", "runs"] and parts[3] == "items" and post and parts[5] in {"comment", "decision"}:
                    self.response(201, app.store.event(parts[2], parts[4], body, parts[5]))
                elif route == "/api/jobs":
                    self.response(201, app.jobs.start(body)) if post else self.response(200, app.store.jobs())
                elif len(parts) == 4 and parts[:2] == ["api", "jobs"] and parts[3] == "cancel" and post:
                    app.jobs.cancel(parts[2])
                    self.response(200, {"message": "Cancellation requested."})
                elif not post and route in {"/", "/app.js", "/style.css"}:
                    filename = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css"}[route]
                    mime = {"/": "text/html; charset=utf-8", "/app.js": "text/javascript; charset=utf-8", "/style.css": "text/css; charset=utf-8"}[route]
                    self.response(200, (Path(__file__).parent / "static" / filename).read_bytes(), mime)
                else:
                    raise KeyError("Route not found.")
            except PermissionError as exc:
                self.response(403, {"error": str(exc)})
            except Conflict as exc:
                self.response(409, {"error": str(exc)})
            except KeyError as exc:
                self.response(404, {"error": str(exc)})
            except (ValueError, TypeError) as exc:
                self.response(400, {"error": str(exc)})
            except Exception:
                self.response(500, {"error": "Unexpected server error. Your saved records remain available."})
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Run the local SAST review workbench")
    parser.add_argument("--port", type=int, default=8021)
    parser.add_argument("--data-dir", default=".workbench")
    parser.add_argument("--upstream", help="Local Sebastian/SAST checkout (read-only integration)")
    parser.add_argument("--upstream-python", default=sys.executable, help="Python executable with the upstream dependencies")
    args = parser.parse_args()
    data_dir = Path(args.data_dir).resolve()
    app = App(data_dir, args.upstream, args.upstream_python)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler(app))
    print(f"Blackboard Workbench: http://127.0.0.1:{server.server_port}\nSaved data: {data_dir}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if app.jobs.active:
            app.jobs.cancel(app.jobs.active)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
