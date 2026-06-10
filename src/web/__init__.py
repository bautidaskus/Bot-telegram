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
        return render_template("page.html", title="Gimnasio", active="gym")

    @app.get("/salud")
    def health() -> str:
        return render_template("page.html", title="Salud", active="health")

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
