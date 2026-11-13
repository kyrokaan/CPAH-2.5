import logging
import logging.config
import os

from . import constants


READ_ONLY = os.environ.get("CPAH_READ_ONLY") == "1"
handlers = {
    "default": {
        "level": "DEBUG",
        "formatter": "default",
        "class": "logging.StreamHandler",
        "stream": "ext://sys.stderr",
    }
}
active_handlers = ["default"]
if not READ_ONLY:
    constants.APPLICATION_DIRECTORY.mkdir(parents=True, exist_ok=True)
    handlers["file"] = {
        "level": "DEBUG",
        "formatter": "default",
        "class": "logging.handlers.RotatingFileHandler",
        "filename": str(constants.LOG_FILE_PATH),
        "encoding": "utf-8",
        "maxBytes": 500_000,
        "backupCount": 1,
    }
    active_handlers.append("file")

logging.config.dictConfig(
    {
        "version": 1,
        "formatters": {
            "default": {"format": "%(asctime)s [%(levelname)s] [CPAH]: %(message)s"}
        },
        "handlers": handlers,
        "loggers": {
            "cpah": {
                "handlers": active_handlers,
                "level": "DEBUG",
                "propagate": False,
            },
        },
    }
)
LOG = logging.getLogger("cpah")
