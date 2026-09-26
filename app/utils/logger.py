import logging


def get_logger(name: str) -> logging.Logger:
    """Return a module-level logger.  Call as: logger = get_logger(__name__)"""
    return logging.getLogger(name)
