"""Tiny structured-ish logger (stdlib only) shared across the relayer."""
from __future__ import annotations

import logging
import os
import sys

_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


def get_logger(name: str = "relayer") -> logging.Logger:
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s | %(message)s", "%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, _LEVEL, logging.INFO))
    logger.propagate = False
    return logger
