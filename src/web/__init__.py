"""Dashboard web local del Personal Tracker."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from flask import Flask, jsonify, render_template
from sqlalchemy.orm import Session, sessionmaker


def create_app(
    session_factory: sessionmaker[Session], today: Callable[[], date] = date.today
) -> Flask:
    app = Flask(__name__)
    app.config["SESSION_FACTORY"] = session_factory
    app.config["TODAY"] = today

    @app.get("/")
    def index() -> str:
        return render_template("page.html", title="Resumen", active="index")

    @app.get("/finanzas")
    def finances() -> str:
        return render_template("page.html", title="Finanzas", active="finances")

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
