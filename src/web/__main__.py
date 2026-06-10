"""Entry point del dashboard web local."""

from sqlalchemy.orm import sessionmaker

from src.config import get_settings
from src.db.session import create_sqlite_engine
from src.web import create_app


def main() -> None:
    settings = get_settings()
    engine = create_sqlite_engine(settings.db_path)
    app = create_app(sessionmaker(engine, expire_on_commit=False))
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
