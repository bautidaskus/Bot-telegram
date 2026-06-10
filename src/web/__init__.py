"""Dashboard web local del Personal Tracker."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta

from flask import Flask, jsonify, render_template, request
from sqlalchemy.orm import Session, sessionmaker

from src.web.queries import DashboardQueries, month_bounds


def create_app(
    session_factory: sessionmaker[Session], today: Callable[[], date] = date.today
) -> Flask:
    app = Flask(__name__)
    app.config["SESSION_FACTORY"] = session_factory
    app.config["TODAY"] = today
    app.jinja_env.filters["number"] = format_number

    @app.get("/")
    def index() -> str:
        current_day = today()
        month_start, next_month = month_bounds(current_day)
        with session_factory() as session:
            queries = DashboardQueries(session)
            return render_template(
                "index.html",
                active="index",
                month=current_day.strftime("%Y-%m"),
                finances=queries.month_summary(current_day),
                latest_weight=queries.latest_weight(),
                health=queries.health_averages(current_day),
                gym=queries.gym_summary(month_start, next_month - timedelta(days=1), limit=3),
                activity=queries.recent_activity(),
            )

    @app.get("/finanzas")
    def finances() -> str:
        selected_month = parse_month(request.args.get("month"), today())
        requested_currency = request.args.get("currency", "").upper()
        with session_factory() as session:
            queries = DashboardQueries(session)
            available = [item["currency"] for item in queries.month_summary(selected_month)]
            selected_currency = select_currency(requested_currency, available)
            data = queries.finance_month(selected_month, selected_currency)
        currencies = data["available_currencies"] or [selected_currency]
        return render_template(
            "finances.html",
            active="finances",
            month=selected_month.strftime("%Y-%m"),
            currency=selected_currency,
            currencies=currencies,
            data=data,
        )

    @app.get("/gym")
    def gym() -> str:
        requested_exercise = request.args.get("exercise", "")
        with session_factory() as session:
            queries = DashboardQueries(session)
            exercises = queries.exercises()
            selected_exercise = (
                requested_exercise
                if requested_exercise in exercises
                else exercises[0]
                if exercises
                else None
            )
            progression = (
                queries.exercise_progression(selected_exercise) if selected_exercise else []
            )
            sessions = queries.gym_summary(date(1970, 1, 1), today(), limit=10)["sessions"]
        return render_template(
            "gym.html",
            active="gym",
            exercises=exercises,
            exercise=selected_exercise,
            progression=progression,
            sessions=sessions,
        )

    @app.get("/salud")
    def health() -> str:
        days = parse_days(request.args.get("days"))
        current_day = today()
        start = current_day - timedelta(days=days - 1)
        with session_factory() as session:
            history = DashboardQueries(session).health_history(start, current_day)
        return render_template(
            "health.html", active="health", days=days, periods=(30, 90, 365), history=history
        )

    @app.get("/healthz")
    def healthz():  # type: ignore[no-untyped-def]
        return jsonify(status="ok")

    @app.errorhandler(404)
    def not_found(_: object) -> tuple[str, int]:
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_error(_: object) -> tuple[str, int]:
        return render_template("errors/500.html"), 500

    return app


def parse_month(raw: str | None, fallback: date) -> date:
    if raw:
        try:
            return date.fromisoformat(f"{raw}-01").replace(day=1)
        except ValueError:
            pass
    return fallback.replace(day=1)


def select_currency(requested: str, available: list[str]) -> str:
    if requested in available:
        return requested
    if "ARS" in available:
        return "ARS"
    return available[0] if available else "ARS"


def format_number(value: float | int | None) -> str:
    if value is None:
        return "—"
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "_").replace(".", ",").replace("_", ".")


def parse_days(raw: str | None) -> int:
    try:
        value = int(raw or "")
    except ValueError:
        return 30
    return value if value in {30, 90, 365} else 30
