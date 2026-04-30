from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="TradingAgents UI API")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "tradingagents-ui"}

    return app
