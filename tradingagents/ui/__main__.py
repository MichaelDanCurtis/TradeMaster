import uvicorn


def main() -> None:
    uvicorn.run(
        "tradingagents.ui.api:create_app",
        factory=True,
        host="127.0.0.1",
        port=8787,
        reload=False,
    )


if __name__ == "__main__":
    main()
