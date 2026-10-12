from fastapi import Depends, FastAPI
from prometheus_client import REGISTRY

from app.api.errors import error_responses, register_error_handlers
from app.api.middleware import observe_requests
from app.api.routes.events import router as events_router
from app.api.routes.health import router as health_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.pull_requests import router as pull_requests_router
from app.api.routes.repositories import router as repositories_router
from app.api.routes.webhooks import router as webhooks_router
from app.api.security import enforce_rate_limit
from app.core.config import settings
from app.core.logs import configure_logging
from app.core.metrics import StateCollector
from app.db.redis import get_broker, get_redis
from app.db.session import SessionLocal

configure_logging(settings.log_level)

app = FastAPI(title="CodeEvidence")

register_error_handlers(app)
app.middleware("http")(observe_requests)
REGISTRY.register(StateCollector(SessionLocal, get_redis, get_broker))

# Open: health checks and metrics (for orchestrators and Prometheus), and the webhook
# (authenticated by its HMAC signature instead).
app.include_router(health_router)
app.include_router(webhooks_router)

# The read API: an API key and a rate limit on every endpoint.
protected = {"dependencies": [Depends(enforce_rate_limit)], "responses": error_responses(401, 429)}
app.include_router(repositories_router, **protected)
app.include_router(pull_requests_router, **protected)
app.include_router(events_router, **protected)
app.include_router(jobs_router, **protected)
