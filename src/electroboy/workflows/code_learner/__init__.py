"""Code Learner workflow package."""

from __future__ import annotations


def workflow():
    """Load the Code Learner workflow factory without eager imports."""

    from .plugin import workflow as _workflow

    return _workflow()
