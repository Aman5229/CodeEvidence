from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.webhooks import router as webhooks_router

app = FastAPI(title="CodeEvidence")

app.include_router(health_router)
app.include_router(webhooks_router)
