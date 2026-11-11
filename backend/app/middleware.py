from collections import deque

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_REQUEST_BODY_BYTES = 16_384


class RequestSizeLimitMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        max_body_bytes: int = MAX_REQUEST_BODY_BYTES,
    ) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", ()))
        content_length = headers.get(b"content-length")
        if content_length:
            try:
                declared_length = int(content_length)
            except ValueError:
                await JSONResponse(
                    {"detail": "Invalid Content-Length header."},
                    status_code=400,
                )(scope, receive, send)
                return
            if declared_length < 0:
                await JSONResponse(
                    {"detail": "Invalid Content-Length header."},
                    status_code=400,
                )(scope, receive, send)
                return
            if declared_length > self.max_body_bytes:
                await JSONResponse(
                    {"detail": "Request body is too large."},
                    status_code=413,
                )(scope, receive, send)
                return

        body_messages = deque()
        body_size = 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body_size += len(message.get("body", b""))
            if body_size > self.max_body_bytes:
                await JSONResponse(
                    {"detail": "Request body is too large."},
                    status_code=413,
                )(scope, receive, send)
                return
            body_messages.append(message)
            if not message.get("more_body", False):
                break

        async def replay_body() -> Message:
            if body_messages:
                return body_messages.popleft()
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_body, send)
