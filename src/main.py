from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(
    title="Hello World Server",
    version="1.0.0",
    description="Simple Hello World with FastAPI"
)

# Abilita CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    uvicorn.run(app, host="0.0.0.0", port=8086)

