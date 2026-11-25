"""Unit tests for the shared ARIA field readers (text boxes and check boxes of a screen snapshot)."""

from sapwebguimcp.backend.webgui.parsers.aria_fields import checkbox_checked, textbox_value, unescape_yaml_name
from sapwebguimcp.lang.text import Text


class TestTextboxValue:
    def test_single_quoted_line_with_escapes(self) -> None:
        snapshot = """- 'textbox "It''s \\"x\\"" [disabled]: v'"""
        assert textbox_value(snapshot, Text(('It\'s "x"',))) == "v"

    def test_single_quoted_line_unescapes_apostrophes_in_the_value(self) -> None:
        snapshot = """- 'textbox "Beschreibung": Kunde''s Kennzeichen'"""
        assert textbox_value(snapshot, Text(("Beschreibung",))) == "Kunde's Kennzeichen"

    def test_unquoted_line_keeps_a_trailing_apostrophe(self) -> None:
        assert textbox_value("""- textbox "Beschreibung": Kunden'""", Text(("Beschreibung",))) == "Kunden'"

    def test_single_quoted_line_with_apostrophes_in_label_and_value(self) -> None:
        snapshot = """- 'textbox "Kunde''s Feld" [disabled]: Kunde''s Kennzeichen'"""
        assert textbox_value(snapshot, Text(("Kunde's Feld",))) == "Kunde's Kennzeichen"

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
