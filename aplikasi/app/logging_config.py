import logging
from logging.handlers import RotatingFileHandler


def configure_logging(app):
    app.config["LOG_DIR"].mkdir(parents=True, exist_ok=True)
    log_file = app.config["LOG_DIR"] / "app.log"

    handler = RotatingFileHandler(log_file, maxBytes=5_000_000, backupCount=10)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    handler.setLevel(logging.INFO)

    app.logger.setLevel(logging.INFO)
    app.logger.addHandler(handler)
