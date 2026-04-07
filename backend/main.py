from fastapi import FastAPI

app = FastAPI(title="Health Monitor API")


@app.get("/health")
def health_check() -> dict:
    return {"status": "ok"}