from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import (BaseHTTPMiddleware,
                                       RequestResponseEndpoint)

from .api import router as api_router
from .api.response.response import error, ok, unexpect_error
from .db.mongo import mongo_error_requests
from .logger import log

app = FastAPI()
app.include_router(api_router)


@app.get("/")
async def root():
    return ok()


# Middleware to cache request body
class CacheRequestBodyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        # Read and cache the body
        body = await request.body()
        # Store the body in the request state for later use
        request.state.cached_body = body

        # Reconstruct the receive channel to allow body to be read again
        async def receive():
            return {"type": "http.request", "body": body}

        response = await call_next(request)
        return response


app.add_middleware(CacheRequestBodyMiddleware)


# Custom global error handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Handle all uncaught exceptions globally.
    """
    # handle HTTPException
    if isinstance(exc, HTTPException):
        log.error(f"HTTPException: {exc.detail}")
        # return JSONResponse(status_code=exc.status_code, content=exc.detail)
        return error(exc.detail)

    log.error(f"Unhandled exception: {exc}")

    body = request.state.cached_body if hasattr(request.state, "cached_body") else None
    body_content = body.decode("utf-8") if body else None
    error_doc = {
        "error": str(exc),
        "request": {
            "method": request.method,
            "url": str(request.url),
            "headers": dict(request.headers),
            "body": body_content,
        },
    }
    mongo_error_requests.insert_one(error_doc)
    return JSONResponse(status_code=500, content=unexpect_error())
