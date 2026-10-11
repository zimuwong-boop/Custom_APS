import json
import logging
import time
import uuid

logger = logging.getLogger("aps.requests")


class RequestLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = str(uuid.uuid4())
        started = time.perf_counter()
        response = self.get_response(request)
        response["X-Request-ID"] = request.request_id
        if request.path.startswith("/api/"):
            logger.info(
                json.dumps(
                    {
                        "request_id": request.request_id,
                        "method": request.method,
                        "path": request.path,
                        "status": response.status_code,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                    },
                    ensure_ascii=False,
                )
            )
        return response
