from fastapi import FastAPI

from api.config import load_config
from api.routes import asr as asr_route
from api.routes import health


def create_app() -> FastAPI:
    app = FastAPI(title="DashScope ASR")
    app.state.config = load_config()
    app.include_router(health.router)
    app.include_router(asr_route.router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    cfg = app.state.config
    uvicorn.run(app, host=cfg.host, port=cfg.port)
