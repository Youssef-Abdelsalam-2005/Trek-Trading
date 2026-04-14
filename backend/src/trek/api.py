from fastapi import FastAPI

from backend.app.routes.risk_config import router as risk_config_router
from trek.routers.events import router as events_router
from trek.routers.variations import router as variations_router

app = FastAPI(title="Trek Trading API")
app.include_router(variations_router)
app.include_router(events_router)
app.include_router(risk_config_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
