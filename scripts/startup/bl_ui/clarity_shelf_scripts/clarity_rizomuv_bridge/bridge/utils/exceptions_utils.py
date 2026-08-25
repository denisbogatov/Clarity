"""Utility functions for handling exceptions."""

import logging
import traceback
from typing import Callable, Literal, Optional

from bpy.types import Operator

logger = logging.getLogger(__name__)


def cancel_with_logged_exception(
    op: Operator, exception: Exception, fn: Optional[Callable] = None
) -> set[Literal["CANCELLED"]]:
    """Cancel the current operator with an exception and log it.

    Args:
        op: The failing operator.
        exception: The exception to log.
        fn: A function to call after logging the exception.

    Returns:
        The operator cancelled set literal.

    """
    op.report({"ERROR"}, str(exception))
    logger.error(traceback.format_exc())

    if fn:
        fn()

    return {"CANCELLED"}
