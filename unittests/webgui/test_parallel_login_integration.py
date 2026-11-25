"""Live check: a further sap_login of the same user leaves the first session alive (#104).

The further login is a fresh logon in its own browser context. With the same user and client, SAP may show its
"already logged on" page (depending on the system's multiple-logon settings), and the login must continue without
ending the other logons. Creates, changes or deletes no SAP data.
"""

import pytest
from mcp import ClientSession

from sapwebguimcp.models import LoginResult, SessionStatus
from sapwebguimcp.models.sap_results import SessionCloseResult, SessionListResult

from .conftest import call_tool_typed


@pytest.mark.anyio
async def test_second_login_of_the_same_user_keeps_the_first_session_alive(sap_mcp_client: ClientSession) -> None:
    first = await call_tool_typed(sap_mcp_client, "sap_login", {}, LoginResult)
    assert first.success, f"First login failed: {first.error}"
    assert first.session_id

    second = await call_tool_typed(sap_mcp_client, "sap_login", {}, LoginResult)
    try:
        assert second.success, f"Second login failed: {second.error}"
        assert second.session_id
        assert second.session_id != first.session_id

        for session_id in (first.session_id, second.session_id):
            status = await call_tool_typed(sap_mcp_client, "sap_session_status", {"session": session_id}, SessionStatus)
            assert status.status == "active", f"session {session_id} is not active: {status}"

        listed = await call_tool_typed(sap_mcp_client, "sap_session_list", {}, SessionListResult)
        listed_ids = {session.session_id for session in listed.sessions}
        assert {first.session_id, second.session_id} <= listed_ids, f"sessions listed: {sorted(listed_ids)}"
    finally:
        if second.success and second.session_id:
            closed = await call_tool_typed(
                sap_mcp_client, "sap_session_close", {"session_id": second.session_id}, SessionCloseResult
            )
            assert closed.success, f"Closing the second session failed: {closed.error}"

    status = await call_tool_typed(sap_mcp_client, "sap_session_status", {"session": first.session_id}, SessionStatus)
    assert status.status == "active", f"first session is not active after closing the second: {status}"
