from fastapi import FastAPI
from app.api.routes.github import router as github_router

app = FastAPI(title="CodeEvidence")

app.include_router(github_router)

@app.get("/health")
def health_check():
    return {"status": "ok"}
