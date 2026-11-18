import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class GlobalResponseMiddleware(BaseHTTPMiddleware):
    """Wrap all JSON responses in {success, message, data, error} structure."""

    SKIP_PATHS = {"/docs", "/redoc", "/openapi.json", "/favicon.ico"}

    async def dispatch(self, request: Request, call_next):
        # Skip CORS preflight and non-API paths
        if request.method == "OPTIONS" or any(request.url.path.startswith(p) for p in self.SKIP_PATHS):
            return await call_next(request)

        response = await call_next(request)

        if response.headers.get("content-type", "").startswith("application/json"):
            body = b""
            async for chunk in response.body_iterator:
                body += chunk if isinstance(chunk, bytes) else chunk.encode()

            try:
                original = json.loads(body)
            except json.JSONDecodeError:
                return response

            # Already wrapped — skip
            if isinstance(original, dict) and "success" in original and "message" in original:
                wrapped = original
            else:
                is_success = 200 <= response.status_code < 400
                wrapped = {
                    "success": is_success,
                    "message": "ok" if is_success else "error",
                    "data": original if is_success else None,
                    "error": original if not is_success else None,
                }

            wrapped_body = json.dumps(wrapped, default=str).encode()
            headers = dict(response.headers)
            headers["content-length"] = str(len(wrapped_body))
            return Response(
                content=wrapped_body,
                status_code=response.status_code,
                headers=headers,
                media_type="application/json",
            )

        return response
