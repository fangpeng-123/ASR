from fastapi import FastAPI

from api.config import load_config
from api.routes import health


def create_app() -> FastAPI:
    app = FastAPI(title="DashScope ASR")
    app.state.config = load_config()
    app.include_router(health.router)
    # asr 路由在 Task 6 注册
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    cfg = app.state.config
    uvicorn.run(app, host=cfg.host, port=cfg.port)
