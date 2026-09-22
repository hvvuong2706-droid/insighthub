"""Bound the entire multipart body before parsing, including chunked HTTP requests."""

from fastapi.responses import JSONResponse

from app.core.config import get_settings


class UploadLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        path = scope["path"].rstrip("/")
        # D8: retry re-uploads the original file, so it needs the same bound as /documents.
        is_bounded_route = path == "/documents" or (
            path.startswith("/documents/") and path.endswith("/retry")
        )
        if scope["type"] != "http" or scope["method"] != "POST" or not is_bounded_route:
            return await self.app(scope, receive, send)
        # Allow multipart headers/boundaries in addition to the actual file limit.
        limit = get_settings().max_upload_bytes + 64 * 1024
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
            if length < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({"detail": "Invalid Content-Length"}, 400)(
                scope, receive, send
            )
        if length > limit:
            return await JSONResponse({"detail": "Upload quá lớn."}, 413)(
                scope, receive, send
            )
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            data = message.get("body", b"")
            if len(body) + len(data) > limit:
                return await JSONResponse({"detail": "Upload quá lớn."}, 413)(
                    scope, receive, send
                )
            body.extend(data)
            if not message.get("more_body", False):
                break
        delivered = False

        async def bounded_receive():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        return await self.app(scope, bounded_receive, send)
