"""Unit tests for the shared ARIA field readers (text boxes and check boxes of a screen snapshot)."""

from sapwebguimcp.backend.webgui.parsers.aria_fields import checkbox_checked, textbox_value, unescape_yaml_name
from sapwebguimcp.lang.text import Text


class TestTextboxValue:
    def test_single_quoted_line_with_escapes(self) -> None:
        snapshot = """- 'textbox "It''s \\"x\\"" [disabled]: v'"""
        assert textbox_value(snapshot, Text(('It\'s "x"',))) == "v"

    def test_textbox_without_value_is_empty(self) -> None:
        assert textbox_value('- textbox "Paket"', Text(("Paket",))) == ""

    def test_missing_label_is_none(self) -> None:
        assert textbox_value('- textbox "Paket": ZPKG', Text(("Beschreibung",))) is None

    def test_label_must_match_exactly(self) -> None:
        assert textbox_value('- textbox "Paketname": ZPKG', Text(("Paket",))) is None

    def test_first_match_wins_and_flags_are_skipped(self) -> None:
        snapshot = '- textbox "Paket" [disabled]: ZFIRST\n- textbox "Paket": ZSECOND'
        assert textbox_value(snapshot, Text(("Paket",))) == "ZFIRST"


class TestCheckboxChecked:
    def test_checked_flag(self) -> None:
        assert checkbox_checked('- checkbox "Final" [checked] [disabled]:  Final', Text(("Final",))) is True

    def test_unchecked_checkbox(self) -> None:
        assert checkbox_checked('- checkbox "Final" [disabled]', Text(("Final",))) is False

    def test_value_text_does_not_count(self) -> None:
        assert checkbox_checked('- checkbox "Final" [disabled]: Final [checked]', Text(("Final",))) is False

    def test_missing_checkbox_is_false(self) -> None:
        assert checkbox_checked('- checkbox "Filter" [checked]', Text(("Final",))) is False


class TestUnescapeYamlName:
    def test_double_quote_and_single_quote_escapes(self) -> None:
        assert unescape_yaml_name("a''b \\\"c\\\"", quoted_line=True) == 'a\'b "c"'
        assert unescape_yaml_name("a''b", quoted_line=False) == "a''b"
