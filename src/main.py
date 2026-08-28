"""Entry point del Personal Tracker Bot."""

from __future__ import annotations

from datetime import datetime, time
from typing import Any
from zoneinfo import ZoneInfo

from loguru import logger
from sqlalchemy.orm import sessionmaker
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from src.ai.parser import create_groq_canonicalizer
from src.bot.backup_commands import BotBackup
from src.bot.checkin import CheckinFlow
from src.bot.commands import BotCommands
from src.bot.gym_handlers import GymBotHandlers
from src.bot.maintenance import BotMaintenance
from src.config import Settings, get_settings
from src.db.session import create_sqlite_engine
from src.logging_setup import configure_logging


def register_handlers(
    application: Application[Any, Any, Any, Any, Any, Any],
    gym: GymBotHandlers,
    checkin: CheckinFlow,
    commands: BotCommands,
    maintenance: BotMaintenance,
    backup: BotBackup,
) -> None:
    """Registra los flujos del bot en orden de prioridad."""

    async def priority_router(update: Any, context: Any) -> None:
        if await checkin.handle_free_text(update, context):
            raise ApplicationHandlerStop
        if await maintenance.handle_edit_value(update, context):
            raise ApplicationHandlerStop

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, priority_router), group=-1
    )
    for name, callback in (
        ("start", commands.start),
        ("help", commands.help),
        ("hoy", commands.today),
        ("gym", commands.gym),
        ("sesiones", commands.sessions),
        ("estado", gym.estado),
        ("cancelar", gym.cancelar),
        ("editar", maintenance.edit),
        ("borrar", maintenance.delete),
        ("backup", backup.backup),
        ("export", backup.export),
    ):
        application.add_handler(CommandHandler(name, callback))
    application.add_handler(CallbackQueryHandler(maintenance.handle_callback, pattern=r"^m:"))
    application.add_handler(CallbackQueryHandler(checkin.handle_callback, pattern=r"^k:"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, gym.handle_text))


def build_application(settings: Settings) -> Application[Any, Any, Any, Any, Any, Any]:
    """Construye la aplicación de Telegram con sus dependencias."""

    engine = create_sqlite_engine(settings.db_path)
    sessions = sessionmaker(engine, expire_on_commit=False)
    timezone = ZoneInfo(settings.timezone)
    gym = GymBotHandlers(
        allowed_chat_id=settings.allowed_chat_id,
        session_factory=sessions,
        canonicalizer=create_groq_canonicalizer(settings),
        now=lambda: datetime.now(timezone).replace(tzinfo=None),
    )
    checkin = CheckinFlow(
        allowed_chat_id=settings.allowed_chat_id,
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
    backup = BotBackup(
        allowed_chat_id=settings.allowed_chat_id,
        db_path=settings.db_path,
        backup_dir=settings.backup_dir,
        retention_days=settings.backup_retention_days,
        now=lambda: datetime.now(timezone).replace(tzinfo=None),
    )
    application = (
        Application.builder().token(settings.telegram_bot_token.get_secret_value()).build()
    )
    register_handlers(application, gym, checkin, commands, maintenance, backup)
    application.add_error_handler(_log_unhandled_error)
    application.job_queue.run_daily(
        backup.scheduled_backup,
        time=time(hour=settings.backup_daily_hour, tzinfo=timezone),
    )
    application.job_queue.run_daily(checkin.send_prompt, time=time(hour=22, tzinfo=timezone))
    application.job_queue.run_daily(checkin.send_reminder, time=time(hour=23, tzinfo=timezone))
    application.job_queue.run_repeating(gym.close_stale_sessions, interval=600, first=30)
    return application


async def _log_unhandled_error(_: object, context: Any) -> None:
    """Deja los errores no manejados en el log rotado en vez de stderr suelto."""

    logger.opt(exception=context.error).error("Error no manejado procesando un update")


def main() -> None:
    """Inicia long polling sin descartar mensajes acumulados."""

    settings = get_settings()
    configure_logging(settings)
    if settings.allowed_chat_id is None:
        logger.warning(
            "ALLOWED_CHAT_ID no está configurado: mandale un mensaje al bot, copiá el "
            "chat_id que aparece en este log a tu .env y reiniciá."
        )
    build_application(settings).run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
