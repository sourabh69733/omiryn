from fastapi import FastAPI

app = FastAPI(
    title="Omiryn API",
    version="0.1.0",
    description="AI-assisted matchmaking platform API.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {
        "name": "Omiryn",
        "message": "Less swiping, better understanding, more intentional introductions.",
    }
