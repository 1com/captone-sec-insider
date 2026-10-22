"""Small helpers shared by the MVP pipeline and renderer."""

import contextlib
import math


def json_safe(obj):
    """Replace NaN/inf (invalid in JSON) with None, recursively; turn numpy scalars into Python."""
    if isinstance(obj, dict):
        return {k: json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_safe(v) for v in obj]
    if hasattr(obj, "item") and not isinstance(obj, (str, bytes)):
        with contextlib.suppress(ValueError, AttributeError):
            obj = obj.item()
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def text_or_empty(value) -> str:
    return value if isinstance(value, str) else ""
