"""The detail of an ST22 dump is completed from the list entry only where it has no value of its own (#96)."""

from sapwebguimcp.models.st22_models import ST22Dump, ST22DumpDetail
from sapwebguimcp.tools.st22_tools import _enrich_detail


def _dump() -> ST22Dump:
    return ST22Dump(
        index=0,
        time="12:00:00",
        program="ZLIST_PROGRAM",
        error_type="LIST_ERROR",
        short_text="from the list",
        user="SOMEONE",
    )


def test_the_short_text_of_the_detail_wins() -> None:
    detail = ST22DumpDetail(short_text="from the dump", raw_text="raw")

    _enrich_detail(detail, _dump())

    assert detail.short_text == "from the dump"


def test_the_list_short_text_is_the_fallback() -> None:
    detail = ST22DumpDetail(short_text="", raw_text="raw")

    _enrich_detail(detail, _dump())

    assert detail.short_text == "from the list"


def test_program_and_error_type_fall_back_to_the_list() -> None:
    detail = ST22DumpDetail(program="", error_type="", raw_text="raw")

    _enrich_detail(detail, _dump())

    assert (detail.program, detail.error_type) == ("ZLIST_PROGRAM", "LIST_ERROR")


def test_program_and_error_type_of_the_detail_win() -> None:
    detail = ST22DumpDetail(program="ZDETAIL_PROGRAM", error_type="DETAIL_ERROR", raw_text="raw")

    _enrich_detail(detail, _dump())

    assert (detail.program, detail.error_type) == ("ZDETAIL_PROGRAM", "DETAIL_ERROR")
