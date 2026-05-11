from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import logging
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan del server"""
    google_api_key = os.environ.get("GOOGLE_API_KEY", "NOT SET")
    groq_api_key = os.environ.get("GROQ_API_KEY", "NOT SET")
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY", "NOT SET")
    llm_provider = os.environ.get("LLM_PROVIDER", "google")

    logger.info(f"=== API Keys ===")
    logger.info(f"GOOGLE_API_KEY: {google_api_key}")
    logger.info(f"GROQ_API_KEY: {groq_api_key}")
    logger.info(f"OPENROUTER_API_KEY: {openrouter_api_key}")
    logger.info(f"LLM_PROVIDER: {llm_provider}")
    yield


app = FastAPI(
    title="Hello World Server",
    version="1.0.0",
    description="Simple Hello World with FastAPI",
    lifespan=lifespan
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

