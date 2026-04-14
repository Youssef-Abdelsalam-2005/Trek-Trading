from fastapi import FastAPI

from trek.routers.trades import router as trades_router

app = FastAPI(title="Trek Trading API")
app.include_router(trades_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
