from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse, Response

from app.middleware import RequestIdMiddleware
from app.routers import sections as sections_router
from app.routers import shares as shares_router

app = FastAPI(title="BlueKnight MRR Collaboration")

app.add_middleware(RequestIdMiddleware)


@app.exception_handler(HTTPException)
async def _spec_error_handler(request: Request, exc: HTTPException) -> Response:
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail and "message" in detail:
        return JSONResponse(
            status_code=exc.status_code,
            content=detail,
            headers=exc.headers,
        )
    return await http_exception_handler(request, exc)


app.include_router(sections_router.router)
app.include_router(shares_router.router)
