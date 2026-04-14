from fastapi import FastAPI

from trek.routers.backtests import router as backtests_router

app = FastAPI(title="Trek Trading API")
app.include_router(backtests_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
