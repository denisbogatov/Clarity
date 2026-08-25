"""Utility function for reporrting operator errors and optionally logging exceptions."""

import logging
import sys


class ShortNameFormatter(logging.Formatter):
    """Formatter that shows only the final component of the logger name."""

    def format(self, record):
        record.name = record.name.split(".")[-1]
        return super().format(record)


def logging_toggle(enabled: bool, logger: logging.Logger):
    """Toggle logging stout output on or off.

    Args:
        enabled: Whether to enable logging.

    """
    root_logger = logging.getLogger()

    if enabled:
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
                root_logger.removeHandler(handler)

        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)
        formatter = ShortNameFormatter("%(name)s - %(levelname)s - %(message)s")
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        root_logger.setLevel(logging.DEBUG)
        logger.info("Logging enabled")
    else:
        for handler in root_logger.handlers[:]:
            if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
                root_logger.removeHandler(handler)
        logger.info("Logging disabled")
