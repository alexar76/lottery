"""ASGI middleware: /monitor/api/* → /api/*, /monitor/ws → /ws (standalone :9100)."""


def strip_monitor_prefix(path: str) -> str | None:
    if path.startswith("/monitor/api"):
        return path[len("/monitor") :] or "/"
    if path == "/monitor/ws":
        return "/ws"
    if path.startswith("/monitor/ws/"):
        return "/ws" + path[len("/monitor/ws") :]
    return None


class MonitorBasePathMiddleware:
    """Rewrite Vite base-path API/WS calls when nginx is not stripping /monitor/."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] in ("http", "websocket"):
            path = scope.get("path") or ""
            rewritten = strip_monitor_prefix(path)
            if rewritten is not None:
                scope = dict(scope)
                scope["path"] = rewritten
                if scope["type"] == "http":
                    scope["raw_path"] = rewritten.encode("utf-8")
        await self.app(scope, receive, send)
