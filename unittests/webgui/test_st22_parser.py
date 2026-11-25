"""
Unit tests for ST22 (Short Dump Analysis) parser.

Tests parsing of YAML accessibility snapshots from ST22 screens.
"""

import json
from pathlib import Path

import pytest

from sapwebguimcp import lang
from sapwebguimcp.backend.webgui.parsers.st22_parser import (
    _MAX_RAW_TEXT_LENGTH,
    is_no_dumps_message,
    parse_st22_dump_detail,
    parse_st22_dump_list,
    parse_st22_initial_screen,
)
from sapwebguimcp.models.st22_models import ST22Dump, ST22DumpDetail

T = lang.view_for("DE")  # German first, English after: the snapshots of both languages are parsed


SNAPSHOTS_DIR = Path(__file__).parent / "testdata" / "st22_exploration"


def _load_snapshot(name: str) -> str:
    """Load a YAML snapshot file."""
    filepath = SNAPSHOTS_DIR / f"{name}_de.yaml"
    if not filepath.exists():
        pytest.skip(f"Snapshot {filepath} not available - run exploration tests first")
    return filepath.read_text(encoding="utf-8")


class TestParseInitialScreen:
    """Tests for parsing ST22 initial screen."""

    def test_parse_initial_screen_counts(self) -> None:
        """Initial screen snapshot should extract today/yesterday counts."""
        snapshot = _load_snapshot("st22_initial")
        counts = parse_st22_initial_screen(snapshot, T)

        assert "today" in counts
        assert "yesterday" in counts
        assert counts["today"] >= 0
        assert counts["yesterday"] >= 0

    def test_parse_initial_screen_with_dumps(self) -> None:
        """Initial screen shows '1 Laufzeitfehler' for both days."""
        snapshot = _load_snapshot("st22_initial")
        counts = parse_st22_initial_screen(snapshot, T)

        # Our captured snapshot has "1 Laufzeitfehler" for both
        assert counts["today"] == 1
        assert counts["yesterday"] == 1

    def test_parse_initial_screen_synthetic(self) -> None:
        """Synthetic snapshot with known counts."""
        snapshot = """- group "Standard":
  - heading "Standard" [level=3]
  - button "Heute"
  - button "5 Laufzeitfehler"
  - button "Gestern"
  - button "12 Laufzeitfehler"
"""
        counts = parse_st22_initial_screen(snapshot, T)
        assert counts["today"] == 5
        assert counts["yesterday"] == 12

    def test_parse_initial_screen_en(self) -> None:
        """Synthetic EN snapshot."""
        snapshot = """- group "Standard":
  - heading "Standard" [level=3]
  - button "Today"
  - button "3 Runtime Errors"
  - button "Yesterday"
  - button "0 Runtime Errors"
"""
        counts = parse_st22_initial_screen(snapshot, T)
        assert counts["today"] == 3
        assert counts["yesterday"] == 0

    def test_parse_initial_screen_empty(self) -> None:
        """Snapshot without count buttons returns 0."""
        snapshot = "- heading 'Something else'"
        counts = parse_st22_initial_screen(snapshot, T)
        assert counts["today"] == 0
        assert counts["yesterday"] == 0


class TestIsNoDumpsMessage:
    """Tests for no-dumps detection."""

    def test_no_dumps_de(self) -> None:
        snapshot = 'note "Warnung Meldungsleiste Es sind keine Kurzdumps - wie selektiert - verfügbar"'
        assert is_no_dumps_message(snapshot, T)

    def test_no_dumps_en(self) -> None:
        snapshot = 'note "Warning No entries found for the selection"'
        assert is_no_dumps_message(snapshot, T)

    def test_no_dumps_from_real_snapshot(self) -> None:
        """Real snapshot with no dumps message."""
        snapshot = _load_snapshot("st22_today_executed")
        assert is_no_dumps_message(snapshot, T)

    def test_has_dumps(self) -> None:
        """Snapshot without no-dumps message."""
        snapshot = '- row "some data row"\n  - cell "10:00:00"\n  - cell "ZPROG"'
        assert not is_no_dumps_message(snapshot, T)


class TestParseDumpList:
    """Tests for parsing ST22 dump list."""

    def test_empty_list_returns_empty(self) -> None:
        """Snapshot with no dump rows should return empty list."""
        snapshot = '- heading "ABAP Runtime Errors":\n  - toolbar:\n    - button "Today"'
        dumps = parse_st22_dump_list(snapshot, T)
        assert dumps == []

    def test_no_dumps_message_returns_empty(self) -> None:
        """Snapshot with 'no dumps' message returns empty list."""
        snapshot = 'note "Es sind keine Kurzdumps - wie selektiert - verfügbar"'
        dumps = parse_st22_dump_list(snapshot, T)
        assert dumps == []

    def test_parse_gridcell_format(self) -> None:
        """Parse dumps from gridcell ALV format."""
        snapshot = """- grid:
  - row:
    - columnheader "Zeit"
    - columnheader "Laufzeitfehler"
    - columnheader "Programm"
    - columnheader "Benutzer"
    - columnheader "Kurztext"
  - row:
    - gridcell "14:32:15"
    - gridcell "RABAX_STATE"
    - gridcell "ZTEST_PROGRAM"
    - gridcell "TESTUSER"
    - gridcell "Test error"
  - row:
    - gridcell "15:00:00"
    - gridcell "MESSAGE_TYPE_X"
    - gridcell "ZPROG2"
    - gridcell "USER2"
    - gridcell "Another error"
"""
        dumps = parse_st22_dump_list(snapshot, T)

        assert len(dumps) == 2
        # Parser returns DOM order (sorting is done in tool layer)
        assert dumps[0].index == 0
        assert dumps[0].time == "14:32:15"
        assert dumps[0].error_type == "RABAX_STATE"
        assert dumps[0].program == "ZTEST_PROGRAM"
        assert dumps[0].user == "TESTUSER"
        assert dumps[0].short_text == "Test error"

        assert dumps[1].index == 1
        assert dumps[1].time == "15:00:00"
        assert dumps[1].error_type == "MESSAGE_TYPE_X"
        assert dumps[1].program == "ZPROG2"

    def test_parse_cell_format(self) -> None:
        """Parse dumps from cell-based row format (fallback)."""
        snapshot = """- row "14:32:15 ZTEST_PROGRAM RABAX_STATE TESTUSER":
    - cell "14:32:15"
    - cell "ZTEST_PROGRAM"
    - cell ""
    - cell "RABAX_STATE"
    - cell "TESTUSER"
"""
        dumps = parse_st22_dump_list(snapshot, T)
        # The cell pattern heuristic should pick this up
        assert len(dumps) >= 1
        if len(dumps) > 0:
            assert dumps[0].time == "14:32:15"

    def test_dump_indexes_sequential(self) -> None:
        """Dump indexes should be sequential starting from 0."""
        snapshot = """- grid:
  - row:
    - columnheader "Zeit"
    - columnheader "Laufzeitfehler"
    - columnheader "Programm"
    - columnheader "Benutzer"
  - row:
    - gridcell "10:00:00"
    - gridcell "ERROR1"
    - gridcell "PROG1"
    - gridcell "USER1"
  - row:
    - gridcell "11:00:00"
    - gridcell "ERROR2"
    - gridcell "PROG2"
    - gridcell "USER2"
  - row:
    - gridcell "12:00:00"
    - gridcell "ERROR3"
    - gridcell "PROG3"
    - gridcell "USER3"
"""
        dumps = parse_st22_dump_list(snapshot, T)
        assert len(dumps) == 3
        for i, dump in enumerate(dumps):
            assert dump.index == i

    def test_dumps_preserve_dom_order(self) -> None:
        """Parser returns dumps in DOM order (sorting is done in tool layer)."""
        snapshot = """- grid:
  - row:
    - columnheader "Zeit"
    - columnheader "Laufzeitfehler"
    - columnheader "Programm"
    - columnheader "Benutzer"
  - row:
    - gridcell "08:15:00"
    - gridcell "EARLY_ERROR"
    - gridcell "ZPROG_EARLY"
    - gridcell "USER1"
  - row:
    - gridcell "16:45:30"
    - gridcell "LATE_ERROR"
    - gridcell "ZPROG_LATE"
    - gridcell "USER2"
  - row:
    - gridcell "12:00:00"
    - gridcell "MID_ERROR"
    - gridcell "ZPROG_MID"
    - gridcell "USER3"
"""
        dumps = parse_st22_dump_list(snapshot, T)
        assert len(dumps) == 3
        # DOM order preserved: 08:15, 16:45, 12:00
        assert dumps[0].time == "08:15:00"
        assert dumps[0].error_type == "EARLY_ERROR"
        assert dumps[0].index == 0
        assert dumps[1].time == "16:45:30"
        assert dumps[1].error_type == "LATE_ERROR"
        assert dumps[1].index == 1
        assert dumps[2].time == "12:00:00"
        assert dumps[2].error_type == "MID_ERROR"
        assert dumps[2].index == 2


class TestParseDumpDetail:
    """Tests for parsing ST22 dump detail text."""

    def test_parse_detail_fallback(self) -> None:
        """Parser should not crash on unexpected format, returning raw_text fallback."""
        snapshot = '- document:\n  - text: "Some random text content here"'
        detail = parse_st22_dump_detail(snapshot, T)

        assert isinstance(detail, ST22DumpDetail)
        assert detail.raw_text  # Should still have raw content
        assert detail.error_type == ""  # Could not extract

    def test_parse_detail_with_sections(self) -> None:
        """Parse detail with known section headers."""
        snapshot = """- document:
  - text: "ABAP Laufzeitfehler"
  - text: "Laufzeitfehler: RABAX_STATE"
  - text: "Was ist geschehen?"
  - text: "An error occurred during ABAP processing."
  - text: "The current program terminated unexpectedly."
  - text: "Was können Sie tun?"
  - text: "Contact your system administrator."
  - text: "Fehleranalyse"
  - text: "Error in line 42 of program ZTEST"
  - text: "Programm: ZTEST_PROGRAM"
  - text: "Zeile im Quelltext: 42"
"""
        detail = parse_st22_dump_detail(snapshot, T)

        assert detail.error_type == "RABAX_STATE"
        assert detail.program == "ZTEST_PROGRAM"
        assert detail.line == 42
        assert "error occurred" in detail.what_happened.lower() or detail.what_happened != ""
        assert detail.raw_text

    def test_parse_detail_en(self) -> None:
        """Parse EN dump detail."""
        snapshot = """- document:
  - text: "ABAP Runtime Errors"
  - text: "Runtime Error: MESSAGE_TYPE_X"
  - text: "What happened?"
  - text: "A RAISE statement in the program ZPROG caused an exception."
  - text: "How to Correct the Error"
  - text: "Check the program logic."
  - text: "Program: ZPROG_MAIN"
  - text: "Source Code Line: 100"
"""
        detail = parse_st22_dump_detail(snapshot, T)

        assert detail.error_type == "MESSAGE_TYPE_X"
        assert detail.program == "ZPROG_MAIN"
        assert detail.line == 100
        assert "RAISE" in detail.what_happened or detail.what_happened != ""

    def test_parse_detail_raw_text_truncated(self) -> None:
        """raw_text should be truncated if content is very large."""
        # Create a large snapshot: 100 text lines of 500 characters each, well above the limit
        large_content = ('- text: "' + "x" * 500 + '"\n') * 100
        detail = parse_st22_dump_detail(large_content, T)

        marker = "\n... [truncated]"
        assert detail.raw_text.endswith("[truncated]")
        assert len(detail.raw_text) == _MAX_RAW_TEXT_LENGTH + len(marker)

    def test_sections_and_call_stack_are_found_behind_the_raw_text_limit(self) -> None:
        """Only raw_text is truncated; the call stack and the sections are read from the whole text."""
        filler = "".join(f'  - text: "{"x" * 100} {i}"\n' for i in range(150))
        snapshot = (
            "- document:\n"
            + filler
            + """  - text: "Was ist geschehen?"
  - text: "Der Abbruch geschah hinter der Grenze."
  - text: "Was können Sie tun?"
  - text: "Programm korrigieren."
  - text: "Active Calls"
  - text: "ZTEST_PROGRAM line 42"
  - text: "SAPMSYST line 100"
  - text: ""
  - text: "End of call stack"
"""
        )
        detail = parse_st22_dump_detail(snapshot, T)

        assert detail.raw_text.endswith("[truncated]")
        assert "Active Calls" not in detail.raw_text  # the heading lies behind the truncation point
        assert detail.what_happened == "Der Abbruch geschah hinter der Grenze."
        assert detail.how_to_correct == "Programm korrigieren."
        assert detail.call_stack == ["ZTEST_PROGRAM line 42", "SAPMSYST line 100"]

    def test_raw_text_keeps_escaped_quotes_of_a_name(self) -> None:
        """A name with escaped quotes (JSON string in the YAML) is decoded, not cut at the first quote."""
        snapshot = '- document:\n  - generic "des Includes \\"ZCL_DEMO\\"."'
        detail = parse_st22_dump_detail(snapshot, T)

        assert 'des Includes "ZCL_DEMO".' in detail.raw_text.split("\n")

    def test_raw_text_keeps_an_unquoted_text_node(self) -> None:
        """An unquoted inline value of a text node is kept."""
        snapshot = """- document:
  - text: Im Quelltext befindet sich die Abbruchstelle in Zeile 36
  - text: des Includes "ZCL_DEMO"."""
        detail = parse_st22_dump_detail(snapshot, T)

        lines = detail.raw_text.split("\n")
        assert "Im Quelltext befindet sich die Abbruchstelle in Zeile 36" in lines
        assert 'des Includes "ZCL_DEMO".' in lines

    def test_raw_text_keeps_a_quoted_text_node(self) -> None:
        """A double-quoted inline value is decoded."""
        snapshot = '- document:\n  - text: "\\"ZCL_DEMO\\""'
        detail = parse_st22_dump_detail(snapshot, T)

        assert '"ZCL_DEMO"' in detail.raw_text.split("\n")

    def test_raw_text_keeps_inline_element_text(self) -> None:
        """The inline text of an element (paragraph, generic with a ref) is kept."""
        snapshot = "- document:\n  - paragraph: Kurztext\n  - generic [ref=e3]: Zeile 36"
        detail = parse_st22_dump_detail(snapshot, T)

        lines = detail.raw_text.split("\n")
        assert "Kurztext" in lines
        assert "Zeile 36" in lines

    def test_raw_text_undoes_a_single_quoted_entry(self) -> None:
        """A whole entry wrapped in single quotes (because its name contains ': ') is unwrapped."""
        snapshot = "- document:\n  - 'generic \"Zugriff über ''NULL'': Objektreferenz\"'"
        detail = parse_st22_dump_detail(snapshot, T)

        assert "Zugriff über 'NULL': Objektreferenz" in detail.raw_text.split("\n")

    def test_a_single_character_text_is_kept(self) -> None:
        """A one-character text (the line number of a label split from its value) is kept, not dropped as noise."""
        snapshot = "\n".join(
            [
                "- text: Information on Where Terminated",
                "- text: Source Code Line:",
                '- text: "5"',  # Playwright quotes a value that is a number
                "- text: Source Code Extract",
            ]
        )
        detail = parse_st22_dump_detail(snapshot, lang.view_for("EN"))

        assert detail.line == 5
        assert "5" in detail.raw_text.split("\n")

    def test_an_icon_glyph_is_not_text(self) -> None:
        """A text of only private-use characters is an icon-font glyph of the Web GUI chrome, not dump text."""
        snapshot = "- text: \n- text: \U000f0001\n- text: Kurztext"
        detail = parse_st22_dump_detail(snapshot, T)

        lines = detail.raw_text.split("\n")
        assert "" not in lines
        assert "\U000f0001" not in lines
        assert "Kurztext" in lines

    def test_parse_detail_call_stack(self) -> None:
        """Extract call stack entries."""
        snapshot = """- document:
  - text: "Active Calls"
  - text: "ZTEST_PROGRAM line 42"
  - text: "SAPMSYST line 100"
  - text: "SAPLZMOD line 200"
  - text: ""
  - text: "End of call stack"
"""
        detail = parse_st22_dump_detail(snapshot, T)
        assert len(detail.call_stack) >= 2


def _snapshot(lines: list[str]) -> str:
    """A Playwright ARIA snapshot of one text node per line (a value that starts with a quote is YAML-quoted)."""
    return "\n".join(f"- text: {json.dumps(line)}" if line.startswith('"') else f"- text: {line}" for line in lines)


_DETAIL_DE_LINES = [
    "Kurztext",
    "Zugriff über 'NULL' Objektreferenz nicht möglich.",
    "Was ist passiert?",
    "Die Laufzeitumgebung hat einen Fehler festgestellt.",
    "Was können Sie tun?",
    "Programm nach der Fehleranalyse korrigieren.",
    "Fehleranalyse",
    "Fehler in Zeile 7 der Methode",
    "Systemumgebung",
    "SAP-Release..... 816",
    "Informationen zur Abbruchstelle",
    "Der Abbruch trat im ABAP-Programm bzw. Include",
    '"ZCL_DEMO======================CP"',
    'auf, und zwar in "ZIF_DEMO~DISPLAY". Das Hauptprogramm war "ZDEMO_MAIN1".',
    "Im Quelltext befindet sich die Abbruchstelle in Zeile 36",
    'des Includes "ZCL_DEMO======================CM00C".',
    "Quelltext",
    'beginnt in Zeile 1 des Includes "ZCL_DEMO======================CM00C".',
    "Quelltextauszug",
    "Zeile 40 >>>>> lv_x = lo_ref->get( ).",
    "Aktive Aufrufe/Ereignisse",
    "4 METHOD ZCL_DEMO======================CP ZCL_DEMO======================CM",
]
_DETAIL_DE = _snapshot(_DETAIL_DE_LINES)

_INCLUDE_CM00C = "ZCL_DEMO======================CM00C"


class TestTerminationPoint:
    """The include and the line of the termination point come from the section on where the program terminated."""

    def test_include_and_line_come_from_the_termination_section(self) -> None:
        detail = parse_st22_dump_detail(_DETAIL_DE, T)

        assert (detail.include, detail.line) == (_INCLUDE_CM00C, 36)

    def test_english_termination_text(self) -> None:
        snapshot = _snapshot(
            [
                "Information on Where Terminated",
                "In the source code you have the termination point in line 36",
                'of the (Include) program "ZCL_X=========CM00C".',
                "Active Calls/Events",
            ]
        )
        detail = parse_st22_dump_detail(snapshot, lang.view_for("EN"))

        assert (detail.include, detail.line) == ("ZCL_X=========CM00C", 36)

    def test_italian_termination_text(self) -> None:
        snapshot = _snapshot(
            [
                "Informazioni punto di interr.",
                (
                    "Nel testo sorgente il punto di interruzione si trova alla riga 36 "
                    'dell\'include "ZCL_X=========CM00C".'
                ),
                "Chiamate/eventi attivi",
            ]
        )
        detail = parse_st22_dump_detail(snapshot, lang.view_for("IT"))

        assert (detail.include, detail.line) == ("ZCL_X=========CM00C", 36)

    def test_italian_pack_names_the_termination_heading(self) -> None:
        assert "Informazioni punto di interr." in lang.pack_for("IT").st22.termination_heading

    def test_a_line_of_another_section_is_not_the_line(self) -> None:
        """Without the termination point text, neither line 7 (error analysis) nor line 40 (source extract) counts."""
        dropped = {
            "Im Quelltext befindet sich die Abbruchstelle in Zeile 36",
            'des Includes "ZCL_DEMO======================CM00C".',
            'beginnt in Zeile 1 des Includes "ZCL_DEMO======================CM00C".',
        }
        snapshot = _snapshot([line for line in _DETAIL_DE_LINES if line not in dropped])
        detail = parse_st22_dump_detail(snapshot, T)

        assert (detail.include, detail.line) == (None, None)

    def test_a_labelled_line_inside_the_termination_section(self) -> None:
        snapshot = _snapshot(
            ["Information on Where Terminated", "Source Code Line: 100", "Source Code Extract", "Line 5 of the extract"]
        )
        detail = parse_st22_dump_detail(snapshot, lang.view_for("EN"))

        assert detail.line == 100
        assert detail.include is None

    def test_the_fallback_inside_the_section_takes_only_the_labelled_line(self) -> None:
        snapshot = _snapshot(["Informationen zur Abbruchstelle", "Der Abbruch trat in Zeile 5 auf", "Quelltextauszug"])
        detail = parse_st22_dump_detail(snapshot, T)

        assert detail.line is None
        assert detail.include is None

    def test_termination_point_beyond_the_raw_text_limit(self) -> None:
        position = _DETAIL_DE_LINES.index("Fehleranalyse") + 1
        notes = [f"Hinweis Nummer {number} mit etwas Text" for number in range(500)]
        snapshot = _snapshot([*_DETAIL_DE_LINES[:position], *notes, *_DETAIL_DE_LINES[position:]])
        detail = parse_st22_dump_detail(snapshot, T)

        assert (detail.include, detail.line) == (_INCLUDE_CM00C, 36)
        assert "[truncated]" in detail.raw_text


class TestShortText:
    """The short text of the detail comes from the dump's own short text section."""

    def test_short_text_comes_from_its_section(self) -> None:
        detail = parse_st22_dump_detail(_DETAIL_DE, T)

        assert detail.short_text == "Zugriff über 'NULL' Objektreferenz nicht möglich."

    def test_short_text_over_two_lines_is_joined_by_a_space(self) -> None:
        snapshot = _snapshot(["Short Text", "first part", "second part", "What happened?", "Something went wrong."])
        detail = parse_st22_dump_detail(snapshot, lang.view_for("EN"))

        assert detail.short_text == "first part second part"

    def test_a_short_text_repeated_on_an_overlapping_page_is_read_once(self) -> None:
        position = _DETAIL_DE_LINES.index("Was ist passiert?")
        snapshot = _snapshot([*_DETAIL_DE_LINES, *_DETAIL_DE_LINES[:position]])
        detail = parse_st22_dump_detail(snapshot, T)

        assert detail.short_text == "Zugriff über 'NULL' Objektreferenz nicht möglich."

    def test_without_a_short_text_section_the_short_text_is_empty(self) -> None:
        snapshot = _snapshot(_DETAIL_DE_LINES[2:])
        detail = parse_st22_dump_detail(snapshot, T)

        assert detail.short_text == ""

    def test_the_short_text_ends_at_the_source_code_heading(self) -> None:
        snapshot = _snapshot(["Kurztext", "Ein Fehler.", "Quelltext des Programms ZDEMO", "Zeile 1"])
        detail = parse_st22_dump_detail(snapshot, T)

        assert detail.short_text == "Ein Fehler."

    def test_a_repeated_short_text_heading_ends_the_first_section(self) -> None:
        snapshot = _snapshot(["Kurztext", "erster Teil", "Kurztext", "zweiter Teil", "Was ist passiert?", "etwas"])
        detail = parse_st22_dump_detail(snapshot, T)

        assert detail.short_text == "erster Teil"
