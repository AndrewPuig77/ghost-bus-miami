from fastapi import FastAPI

app = FastAPI(title="Ghost Bus Miami API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
