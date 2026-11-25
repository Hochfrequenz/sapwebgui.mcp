"""Readers for the text boxes and check boxes of an ARIA snapshot, shared by the builder parsers (SE24, SE37).

A screen field shows up as ``- textbox "<label>" [flags]: <value>`` (the whole line single-quoted by the YAML
dump when the label or value needs it), a check box as ``- checkbox "<label>" [checked] [flags]``.
"""

import re

from sapwebguimcp.lang.text import Text

__all__ = ["checkbox_checked", "textbox_value", "unescape_yaml_name"]

_TEXTBOX_LINE = re.compile(
    r"""^\s*- '?textbox "(?P<label>(?:[^"\\]|\\.)*)"(?: \[[^\]]*\])*(?::[ ]?(?P<value>.*)|'?)\s*$"""
)
_CHECKBOX_LINE = re.compile(r"""^\s*- '?checkbox "(?P<label>(?:[^"\\]|\\.)*)"(?P<flags>(?: \[[^\]]*\])*)""")


def unescape_yaml_name(raw: str, quoted_line: bool) -> str:
    """Undo the YAML escaping of an accessible name (``\\"`` and, in single-quoted lines, ``''``)."""
    name = raw.replace('\\"', '"')
    return name.replace("''", "'") if quoted_line else name


def textbox_value(snapshot: str, label: Text) -> str | None:
    """Value of the first text box whose label is one of ``label``; None when there is no such text box."""
    for line in snapshot.splitlines():
        match = _TEXTBOX_LINE.match(line)
        if match is None:
            continue
        quoted_line = line.lstrip().startswith("- '")
        if not label.equals(unescape_yaml_name(match.group("label"), quoted_line)):
            continue
        value = (match.group("value") or "").rstrip()
        if quoted_line:
            # a single-quoted YAML line: drop the closing quote and undo the doubling of apostrophes
            value = value.removesuffix("'").replace("''", "'")
        value = value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1].replace('\\"', '"')
        return value
    return None


def checkbox_checked(snapshot: str, label: Text) -> bool:
    """Whether the first check box whose label is one of ``label`` is checked (``[checked]`` among its flags)."""
    for line in snapshot.splitlines():
        match = _CHECKBOX_LINE.match(line)
        if match is None:
            continue
        if label.equals(unescape_yaml_name(match.group("label"), line.lstrip().startswith("- '"))):
            return "[checked]" in match.group("flags")
    return False
