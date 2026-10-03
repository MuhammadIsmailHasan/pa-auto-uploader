from flask import Flask, flash, jsonify, redirect, request, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.exceptions import RequestEntityTooLarge

from .config import Config
from .logging_config import configure_logging

db = SQLAlchemy()


def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)

    configure_logging(app)
    db.init_app(app)

    from .routes.dashboard import dashboard_bp
    from .routes.documents import documents_bp
    from .routes.settings import settings_bp
    from .routes.upload import upload_bp
    from .routes.registration_docs import registration_docs_bp
    from .cli import register_cli

    app.register_blueprint(dashboard_bp)
    app.register_blueprint(documents_bp, url_prefix="/documents")
    app.register_blueprint(settings_bp, url_prefix="/settings")
    app.register_blueprint(upload_bp, url_prefix="/upload")
    app.register_blueprint(registration_docs_bp)
    register_cli(app)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_request_entity_too_large(error):
        message = (
            "Upload folder melebihi batas request aplikasi. "
            "Kurangi jumlah file dalam satu folder atau bagi menjadi beberapa folder."
        )
        app.logger.warning("Request ditolak karena melewati batas upload/form: %s", error)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return jsonify({"ok": False, "message": message}), 413
        flash(message, "danger")
        return redirect(url_for("dashboard.index"))

    return app
