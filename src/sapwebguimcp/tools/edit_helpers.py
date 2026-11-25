"""Shared helpers for the SE38/SE24/SE37 source edit tools."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, TypeVar

if TYPE_CHECKING:
    from sapwebguimcp.backend.webgui.backend import WebGuiBackend
    from sapwebguimcp.models import PopupInfo

logger = logging.getLogger(__name__)


class _HasCheckMessages(Protocol):
    """Result models of the edit tools: they all carry ``check_messages``."""

    check_messages: list[str]


R = TypeVar("R", bound=_HasCheckMessages)


async def describe_failed_replace(backend: WebGuiBackend, backup_source: str) -> str:
    """Recover from a failed ``replace_editor_source`` and describe the outcome.

    The write clears the editor before inserting, so a verification failure
    leaves a half-written buffer behind (#859).  Nothing has reached the
    server at this point — the object is only written on save/activate — but
    the editor must not be left holding someone else's half of two sources,
    so the backup is put back before reporting.
    """
    restored = await backend.replace_editor_source(backup_source)
    if not restored:
        logger.warning("edit_restore_failed", extra={"backup_chars": len(backup_source)})
    detail = (
        "The original source was restored into the editor."
        if restored
        else (
            "WARNING: the editor buffer could not be restored and held partial content. "
            "The tool leaves the editor without saving; if check_messages reports that leaving failed, "
            "leave the editor WITHOUT saving."
        )
    )
    return (
        "Failed to replace editor content: the editor buffer does not match new_source. "
        f"Nothing was saved or activated, so the object on the server is unchanged. {detail}"
    )


def _popup_text(popup: PopupInfo) -> str:
    return popup.message or popup.title or "unnamed popup"


async def _close_popup(backend: WebGuiBackend, popup: PopupInfo) -> str | None:
    """Close ``popup`` with its close control; ``None`` when it is gone, else a reason.

    The close control (the window's X) cancels the dialog, so nothing is saved.
    A button such as "Yes" is never pressed, because it could save the buffer.
    """
    if not popup.has_close_button:
        return f"a popup without a close control is open: {_popup_text(popup)}"  # lang-ok: our own message
    closed = await backend.dismiss_popup(use_close_button=True)
    if not closed.popup_closed:
        return f"the popup could not be closed: {_popup_text(popup)}"  # lang-ok: our own message
    return None


async def leave_editor(backend: WebGuiBackend) -> str | None:
    """Leave the editor without saving, so that the object lock is released.

    Ends the transaction with ``/n``.  An open popup is closed with its close
    control first, never with a button that could save.  Returns ``None`` when
    the editor was left, otherwise a one-line reason.  Never raises: the edit
    itself has already happened and must not be reported as failed because of
    the cleanup.
    """
    try:
        popup = await backend.check_popup()
        if popup is not None:
            reason = await _close_popup(backend, popup)
            if reason is not None:
                return reason

        tx = await backend.enter_transaction("/n")
        if not tx.success:
            return f"/n failed: {tx.error}"  # lang-ok: our own message

        after = await backend.check_popup()
        if after is not None:
            await _close_popup(backend, after)
            return f"a popup appeared after leaving: {_popup_text(after)}"  # lang-ok: our own message
        return None
    except Exception as exc:  # cleanup must never turn a finished edit into an exception
        logger.warning("leave_editor_failed", exc_info=True)
        return f"{type(exc).__name__}: {exc}"  # lang-ok: our own message


async def finish_edit(backend: WebGuiBackend, result: R) -> R:
    """Leave the editor and note in ``result.check_messages`` when that did not work."""
    reason = await leave_editor(backend)
    if reason is not None:
        result.check_messages.append(
            f"WARNING: could not leave the editor ({reason}); "  # lang-ok: our own message
            "the object may stay locked until this session starts another transaction."
        )
    return result
