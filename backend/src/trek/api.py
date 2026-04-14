from fastapi import FastAPI

app = FastAPI(title="Trek Trading API")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
