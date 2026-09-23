from fastapi import FastAPI

app = FastAPI(title="CodeEvidence")

@app.get("/health")
def health_check():
    return {"status": "ok"}