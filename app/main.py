from fastapi import FastAPI

app = FastAPI(title="Agent CV")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
