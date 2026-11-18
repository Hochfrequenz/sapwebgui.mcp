"""Guard against ``extra`` keys that collide with ``logging.LogRecord`` attributes.

``logging`` raises ``KeyError("Attempt to overwrite ... in LogRecord")`` when an ``extra`` dict
contains a reserved key such as ``message`` or ``name``. That happens only when the record is
actually emitted, so the bug hides at INFO level and surfaces in error paths or with DEBUG
logging enabled.

Only literal ``extra={...}`` and ``extra=dict(...)`` arguments are checked; an ``extra`` passed as
a variable or built by another call is not.
"""
