import argparse
import uvicorn
from app.config import settings


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reload", action="store_true")
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--port", type=int, default=settings.port)
    args = parser.parse_args()

    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="debug" if settings.debug else "info",
    )


if __name__ == "__main__":
    main()
