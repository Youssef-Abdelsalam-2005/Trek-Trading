from fastapi import FastAPI

from trek.routers.experiments import router as experiments_router

app = FastAPI(title="Trek Trading API")
app.include_router(experiments_router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
