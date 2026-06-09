"""Entry point del Personal Tracker Bot."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy.orm import sessionmaker
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.ai.audio_converter import AudioConverter
from src.ai.parser import create_groq_parser
from src.ai.whisper_client import create_groq_whisper
from src.bot.commands import BotCommands
from src.bot.handlers import BotHandlers
from src.bot.maintenance import BotMaintenance
from src.config import Settings, get_settings
from src.db.session import create_sqlite_engine


def register_handlers(
    application: Application[Any, Any, Any, Any, Any, Any],
    handlers: BotHandlers,
    commands: BotCommands,
    maintenance: BotMaintenance,
) -> None:
    """Registra los flujos interactivos implementados."""

    async def edit_value_router(update: Any, context: Any) -> None:
        if await maintenance.handle_edit_value(update, context):
            raise ApplicationHandlerStop

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value_router), group=-1
    )
    for name, callback in (
        ("start", commands.start),
        ("help", commands.help),
        ("hoy", commands.today),
        ("balance", commands.balance),
        ("gastos", commands.gastos),
        ("ingresos", commands.ingresos),
        ("ultimos", commands.ultimos),
        ("gym", commands.gym),
        ("sesiones", commands.sessions),
        ("peso", commands.weight),
        ("salud", commands.health),
        ("editar", maintenance.edit),
        ("borrar", maintenance.delete),
    ):
        application.add_handler(CommandHandler(name, callback))
    application.add_handler(CallbackQueryHandler(maintenance.handle_callback, pattern=r"^m:"))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handlers.handle_audio))
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
        whisper=create_groq_whisper(settings),
        audio_converter=AudioConverter(),
        session_factory=sessions,
        now=lambda: datetime.now(timezone).replace(tzinfo=None),
    )
    commands = BotCommands(
        allowed_chat_id=settings.allowed_chat_id,
        session_factory=sessions,
        today=lambda: datetime.now(timezone).date(),
    )
    maintenance = BotMaintenance(
        allowed_chat_id=settings.allowed_chat_id,
        session_factory=sessions,
    )
    application = (
        Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()
    )
    register_handlers(application, handlers, commands, maintenance)
    return application


def main() -> None:
    """Inicia long polling sin descartar mensajes acumulados."""

    build_application(get_settings()).run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
