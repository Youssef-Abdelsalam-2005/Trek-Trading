from fastapi import FastAPI

from backend.app.routes.risk_config import router as risk_config_router

app = FastAPI(title="Trek Trading API")
app.include_router(risk_config_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
