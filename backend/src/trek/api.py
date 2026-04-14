from fastapi import FastAPI

from trek.routers.events import router as events_router
from trek.routers.variations import router as variations_router

app = FastAPI(title="Trek Trading API")
app.include_router(variations_router)
app.include_router(events_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
