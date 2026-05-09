from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="FastAPI Hello World Server", version="1.0.0")


@app.get("/")
async def read_root():
    """Endpoint di benvenuto."""
    return JSONResponse({"message": "Hello World!"})


@app.get("/health")
async def health_check():
    """Endpoint di verifica della salute del server."""
    return JSONResponse({"status": "healthy"})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)

