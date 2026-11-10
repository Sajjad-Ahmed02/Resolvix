
from fastapi import FastAPI
from app.core.config import settings

app = FastAPI(
    title=settings.APP_NAME,
    description="AI-powered customer support application",
    version="1.0.0"
)


@app.get("/")
def root():
    return {
        "message": "Welcome to Resolvix API",
        "status": "running"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "application": settings.APP_NAME
    }
