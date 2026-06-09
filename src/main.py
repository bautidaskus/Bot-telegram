"""Entry point del Personal Tracker Bot."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import sessionmaker
from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

from src.ai.parser import create_groq_parser
from src.bot.handlers import BotHandlers
from src.config import Settings, get_settings
from src.db.session import create_sqlite_engine


def register_handlers(
    application: Application[Any, Any, Any, Any, Any, Any], handlers: BotHandlers
) -> None:
    """Registra los flujos interactivos implementados."""

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handlers.handle_text))
    application.add_handler(CallbackQueryHandler(handlers.handle_callback))


def build_application(settings: Settings) -> Application[Any, Any, Any, Any, Any, Any]:
    """Construye la aplicación de Telegram con sus dependencias."""

    engine = create_sqlite_engine(settings.db_path)
    sessions = sessionmaker(engine, expire_on_commit=False)
    timezone = ZoneInfo(settings.timezone)
    handlers = BotHandlers(
        allowed_chat_id=settings.allowed_chat_id,
        parser=create_groq_parser(settings),
        session_factory=sessions,
        now=lambda: datetime.now(timezone).replace(tzinfo=None),
    )
    application = (
        Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()
    )
    register_handlers(application, handlers)
    return application


def main() -> None:
    """Inicia long polling sin descartar mensajes acumulados."""

    build_application(get_settings()).run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
