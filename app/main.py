from fastapi import FastAPI

from app.middleware import RequestIdMiddleware

app = FastAPI(title="BlueKnight MRR Collaboration")

app.add_middleware(RequestIdMiddleware)
