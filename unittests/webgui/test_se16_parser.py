"""Unit tests for SE16 (Data Browser) parser."""

from pathlib import Path

import pytest

from sapwebguimcp.backend.webgui.parsers.se16_parser import (
    parse_se16_columns,
    parse_se16_hit_count,
    parse_se16_rows,
    parse_se16_snapshot,
)
from sapwebguimcp.lang.schema import LanguagePack

# Test data directory
TESTDATA_DIR = Path(__file__).parent / "testdata" / "se16_exploration"


class TestParseHitCount:
    """Tests for parse_se16_hit_count function."""

    def test_parse_simple_number(self, lang_de: LanguagePack) -> None:
        """Test parsing a simple number like '500'."""
        snapshot = 'textbox "Number of Hits": "500"'
        assert parse_se16_hit_count(snapshot, lang_de) == 500

    def test_parse_german_locale_thousands(self, lang_de: LanguagePack) -> None:
        """Test parsing German locale with dot as thousands separator."""
        snapshot = 'textbox "Number of Hits": "5.000"'
        assert parse_se16_hit_count(snapshot, lang_de) == 5000

    def test_parse_large_number(self, lang_de: LanguagePack) -> None:
        """Test parsing larger numbers with German locale."""
        snapshot = 'textbox "Number of Hits": "50.000"'
        assert parse_se16_hit_count(snapshot, lang_de) == 50000

    def test_no_hit_count_field(self, lang_de: LanguagePack) -> None:
        """Test returns 0 when field is not found."""
        snapshot = "some other content without hit count"
        assert parse_se16_hit_count(snapshot, lang_de) == 0

    def test_parse_from_real_snapshot(self, lang_de: LanguagePack) -> None:
        """Test parsing hit count from real SE16N snapshot."""
        snapshot_file = TESTDATA_DIR / "se16n_5000_debug.yaml"
        if snapshot_file.exists():
            snapshot = snapshot_file.read_text(encoding="utf-8")
            assert parse_se16_hit_count(snapshot, lang_de) == 5000


class TestParseColumns:
    """Tests for parse_se16_columns function."""

    def test_parse_columns_from_header_row(self, lang_de: LanguagePack) -> None:
        """Test extracting column names from header row."""
        snapshot = """
      - row "Column for row selection Transaction Code Program":
        - columnheader "Column for row selection": To select all
        - columnheader "Transaction Code"
        - columnheader "Program"
        """
        columns = parse_se16_columns(snapshot, lang_de)
        assert columns == ["Transaction Code", "Program"]

    def test_skips_selection_column(self, lang_de: LanguagePack) -> None:
        """Test that the row selection column is skipped."""
        snapshot = """
      - row "Column for row selection Field1 Field2":
        - columnheader "Column for row selection": helper text
        - columnheader "Field1"
        - columnheader "Field2"
        """
        columns = parse_se16_columns(snapshot, lang_de)
        assert "Column for row selection" not in columns
        assert columns == ["Field1", "Field2"]

    def test_parse_from_real_snapshot(self, lang_de: LanguagePack) -> None:
        """Test parsing columns from real SE16N snapshot."""
        snapshot_file = TESTDATA_DIR / "se16n_5000_debug.yaml"
        if snapshot_file.exists():
            snapshot = snapshot_file.read_text(encoding="utf-8")
            columns = parse_se16_columns(snapshot, lang_de)
            # TSTC table has these columns
            assert "Transaction Code" in columns
            assert "Program" in columns
            assert "Number" in columns
            assert len(columns) == 7


class TestParseRows:
    """Tests for parse_se16_rows function."""

    def test_parse_simple_row(self, lang_de: LanguagePack) -> None:
        """Test parsing a simple data row."""
        snapshot = """
      - row "Column for row selection Code Name":
        - columnheader "Column for row selection"
        - columnheader "Code"
        - columnheader "Name"
      - row "To select a row, press the space bar. ABC Test":
        - gridcell "To select a row, press the space bar."
        - gridcell "ABC":
          - textbox
        - gridcell "Test":
          - textbox
    - rowgroup
        """
        rows = parse_se16_rows(snapshot, lang_de)
        assert len(rows) == 1
        assert rows[0]["Code"] == "ABC"
        assert rows[0]["Name"] == "Test"

    def test_parse_numeric_values_coerced(self, lang_de: LanguagePack) -> None:
        """Test that numeric values are coerced to int/float."""
        snapshot = """
      - row "Column for row selection ID Value":
        - columnheader "Column for row selection"
        - columnheader "ID"
        - columnheader "Value"
      - row "To select a row, press the space bar. 123 45.67":
        - gridcell "To select a row, press the space bar."
        - gridcell "123":
          - textbox
        - gridcell "45.67":
          - textbox
    - rowgroup
        """
        rows = parse_se16_rows(snapshot, lang_de)
        assert len(rows) == 1
        assert rows[0]["ID"] == 123
        assert isinstance(rows[0]["ID"], int)
        assert rows[0]["Value"] == 45.67
        assert isinstance(rows[0]["Value"], float)

    def test_parse_empty_cells(self, lang_de: LanguagePack) -> None:
        """Test handling of empty cells."""
        snapshot = """
      - row "Column for row selection A B C":
        - columnheader "Column for row selection"
        - columnheader "A"
        - columnheader "B"
        - columnheader "C"
      - row "To select a row, press the space bar. Val1 Val3":
        - gridcell "To select a row, press the space bar."
        - gridcell "Val1":
          - textbox
        - gridcell:
          - textbox
        - gridcell "Val3":
          - textbox
    - rowgroup
        """
        rows = parse_se16_rows(snapshot, lang_de)
        assert len(rows) == 1
        assert rows[0]["A"] == "Val1"
        assert rows[0]["B"] == ""
        assert rows[0]["C"] == "Val3"

    def test_parse_quoted_row_with_colons(self, lang_de: LanguagePack) -> None:
        """Test parsing rows that are YAML-quoted due to colons in values."""
        snapshot = """
      - row "Column for row selection Code Text":
        - columnheader "Column for row selection"
        - columnheader "Code"
        - columnheader "Text"
      - 'row "To select a row, press the space bar. ABC Activity: Test"':
        - gridcell "To select a row, press the space bar."
        - gridcell "ABC":
          - textbox
        - 'gridcell "Activity: Test"':
          - textbox
    - rowgroup
        """
        rows = parse_se16_rows(snapshot, lang_de)
        assert len(rows) == 1
        assert rows[0]["Code"] == "ABC"
        assert rows[0]["Text"] == "Activity: Test"

    def test_parse_from_quoted_row_snapshot(self, lang_de: LanguagePack) -> None:
        """Test parsing from snapshot with YAML-quoted rows (has colons)."""
        snapshot_file = TESTDATA_DIR / "se16n_norows_page69.yaml"
        if snapshot_file.exists():
            snapshot = snapshot_file.read_text(encoding="utf-8")
            rows = parse_se16_rows(snapshot, lang_de)
            # This snapshot has rows with colons in transaction text
            assert len(rows) > 0
            # First row should have a transaction code starting with /ISDFPS/
            first_row = rows[0]
            assert "Transaction Code" in first_row
            assert first_row["Transaction Code"].startswith("/ISDFPS/")


class TestParseSe16Snapshot:
    """Tests for the main parse_se16_snapshot function."""

    def test_parse_complete_snapshot(self, lang_de: LanguagePack) -> None:
        """Test parsing a complete SE16N result snapshot."""
        snapshot_file = TESTDATA_DIR / "se16n_5000_debug.yaml"
        if snapshot_file.exists():
            snapshot = snapshot_file.read_text(encoding="utf-8")
            result = parse_se16_snapshot(snapshot, lang_de)

            assert len(result.columns) == 7
            assert "Transaction Code" in result.columns
            # Should have ~13 rows visible in first page
            assert len(result.rows) >= 10

    def test_parse_t000_small_table(self, lang_de: LanguagePack) -> None:
        """Test parsing T000 results (small table with 6 rows)."""
        import json

        snapshot_file = TESTDATA_DIR / "se16n_t000_results.yaml"
        if snapshot_file.exists():
            content = snapshot_file.read_text(encoding="utf-8")
            # Handle JSON-wrapped snapshot
            if content.startswith("{"):
                data = json.loads(content)
                snapshot = data.get("snapshot", content)
            else:
                snapshot = content

            result = parse_se16_snapshot(snapshot, lang_de)

            # T000 has columns like Client, Name, City, etc.
            assert len(result.columns) > 0
            assert "Client" in result.columns
            # T000 typically has 6 rows
            assert len(result.rows) == 6


class TestTypeCoercion:
    """Tests for value type coercion."""

    def test_integer_coercion(self, lang_de: LanguagePack) -> None:
        """Test that integer strings become int."""
        snapshot = """
      - row "Column for row selection Val":
        - columnheader "Column for row selection"
        - columnheader "Val"
      - row "To select a row, press the space bar. 42":
        - gridcell "To select a row, press the space bar."
        - gridcell "42":
          - textbox
    - rowgroup
        """
        rows = parse_se16_rows(snapshot, lang_de)
        assert rows[0]["Val"] == 42
        assert isinstance(rows[0]["Val"], int)

    def test_negative_integer(self, lang_de: LanguagePack) -> None:
        """Test negative integer coercion."""
        snapshot = """
      - row "Column for row selection Val":
        - columnheader "Column for row selection"
        - columnheader "Val"
      - row "To select a row, press the space bar. -123":
        - gridcell "To select a row, press the space bar."
        - gridcell "-123":
          - textbox
    - rowgroup
        """
        rows = parse_se16_rows(snapshot, lang_de)
        assert rows[0]["Val"] == -123

    def test_float_coercion(self, lang_de: LanguagePack) -> None:
        """Test that decimal strings become float."""
        snapshot = """
      - row "Column for row selection Val":
        - columnheader "Column for row selection"
        - columnheader "Val"
      - row "To select a row, press the space bar. 3.14":
        - gridcell "To select a row, press the space bar."
        - gridcell "3.14":
          - textbox
    - rowgroup
        """
        rows = parse_se16_rows(snapshot, lang_de)
        assert rows[0]["Val"] == 3.14
        assert isinstance(rows[0]["Val"], float)

    def test_string_preserved(self, lang_de: LanguagePack) -> None:
        """Test that non-numeric strings stay as strings."""
        snapshot = """
      - row "Column for row selection Val":
        - columnheader "Column for row selection"
        - columnheader "Val"
      - row "To select a row, press the space bar. ABC123":
        - gridcell "To select a row, press the space bar."
        - gridcell "ABC123":
          - textbox
    - rowgroup
        """
        rows = parse_se16_rows(snapshot, lang_de)
        assert rows[0]["Val"] == "ABC123"
        assert isinstance(rows[0]["Val"], str)

    def test_date_string_not_parsed(self, lang_de: LanguagePack) -> None:
        """Test that date strings remain as strings (no date parsing)."""
        snapshot = """
      - row "Column for row selection Val":
        - columnheader "Column for row selection"
        - columnheader "Val"
      - row "To select a row, press the space bar. 2024-01-15":
        - gridcell "To select a row, press the space bar."
        - gridcell "2024-01-15":
          - textbox
    - rowgroup
        """
        rows = parse_se16_rows(snapshot, lang_de)
        assert rows[0]["Val"] == "2024-01-15"
        assert isinstance(rows[0]["Val"], str)


class TestLargeSnapshotParsing:
    """Tests for parsing large snapshots (5000+ rows simulation)."""

    def test_parse_multiple_pages_combined(self, lang_de: LanguagePack) -> None:
        """Test parsing when multiple page snapshots are combined."""
        # This simulates what the tool does when collecting rows
        snapshot_files = [
            TESTDATA_DIR / "se16n_pagination_initial.yaml",
            TESTDATA_DIR / "se16n_norows_page69.yaml",
        ]

        all_rows: list[dict] = []
        columns: list[str] | None = None

        for snapshot_file in snapshot_files:
            if snapshot_file.exists():
                # Handle JSON-wrapped snapshots
                content = snapshot_file.read_text(encoding="utf-8")
                if content.startswith("{"):
                    import json

                    data = json.loads(content)
                    snapshot = data.get("snapshot", content)
                else:
                    snapshot = content

                if columns is None:
                    columns = parse_se16_columns(snapshot, lang_de)

                rows = parse_se16_rows(snapshot, lang_de, columns)
                all_rows.extend(rows)

        if columns:
            assert len(columns) > 0
            assert len(all_rows) > 0
            # Both snapshots should have parsed successfully
            # Each page has ~13 rows
            assert len(all_rows) >= 20


class TestRepeatedColumnTitlesAndCodes:
    """Repeated titles keep every value; codes with leading zeros stay strings (#78)."""

    _SNAPSHOT = """
    - grid:
      - rowgroup:
        - row "Column for row selection Partner Name 1 Name 1 Name 1":
          - columnheader "Column for row selection"
          - columnheader "Partner"
          - columnheader "Name 1"
          - columnheader "Name 1"
          - columnheader "Name 1"
      - rowgroup:
        - row "To select a row, press the space bar. 0000000123 A B C":
          - gridcell "To select a row, press the space bar."
          - gridcell "0000000123":
            - textbox
          - gridcell "A":
            - textbox
          - gridcell "B":
            - textbox
          - gridcell "C":
            - textbox
    - rowgroup
    """

    def test_repeated_titles_are_made_unique(self, lang_de: LanguagePack) -> None:
        columns = parse_se16_columns(self._SNAPSHOT, lang_de)
        assert columns == ["Partner", "Name 1", "Name 1 (2)", "Name 1 (3)"]

    def test_no_value_is_lost_for_repeated_titles(self, lang_de: LanguagePack) -> None:
        columns = parse_se16_columns(self._SNAPSHOT, lang_de)
        (row,) = parse_se16_rows(self._SNAPSHOT, lang_de, columns)
        assert [row[c] for c in columns[1:]] == ["A", "B", "C"]

    def test_leading_zero_code_stays_a_string(self, lang_de: LanguagePack) -> None:
        (row,) = parse_se16_rows(self._SNAPSHOT, lang_de)
        assert row["Partner"] == "0000000123"


class TestResultGridSnapshots:
    """Result grids captured from a live SE16N (German UI, sanitized), #78."""

    _DIR = Path(__file__).parent / "testdata" / "se16_result_grids"

    @staticmethod
    def _read(name: str) -> str:
        return (TestResultGridSnapshots._DIR / name).read_text(encoding="utf-8")

    def test_every_row_of_a_grid_with_a_repeating_first_column_is_parsed(self, lang_de: LanguagePack) -> None:
        """T002 (max_hits 5): the first column has the same value in all rows, only the text differs."""
        result = parse_se16_snapshot(self._read("t002_result_de.aria.txt"), lang_de)
        assert parse_se16_hit_count(self._read("t002_result_de.aria.txt"), lang_de) == 5
        assert result.columns == ["Sprache", "Spezifika", "Üb.grad", "SprCode", "Bezeichnung"]
        assert [row["Bezeichnung"] for row in result.rows] == [
            "Chinesisch",
            "Koreanisch",
            "Rumänisch",
            "Serbisch",
            "Thailändisch",
        ]

    def test_rows_without_an_accessible_name_are_parsed(self, lang_de: LanguagePack) -> None:
        """BUT000: a row with 114 cells has no name in the ARIA tree (``- row:``), so no row was found."""
        snapshot = self._read("but000_result_de.aria.txt")
        columns = parse_se16_columns(snapshot, lang_de)
        assert len(columns) == 114
        (row,) = parse_se16_rows(snapshot, lang_de, columns)
        assert row["GPartner"] == 4711
        assert row["Grp."] == "0001"
        assert row["Nachname"] == "Mustermann"

    def test_empty_cells_stay_empty(self, lang_de: LanguagePack) -> None:
        """An empty cell is ``- gridcell:`` and must not become its column title."""
        snapshot = self._read("but000_result_de.aria.txt")
        (row,) = parse_se16_rows(snapshot, lang_de)
        assert row["Art"] == ""
        assert row["Externe Nr"] == ""

    def test_rows_can_be_keyed_by_technical_names(self, lang_de: LanguagePack) -> None:
        snapshot = self._read("but000_result_de.aria.txt")
        names = self._read("but000_technical_names.txt").split()
        assert len(names) == len(parse_se16_columns(snapshot, lang_de))
        (row,) = parse_se16_rows(snapshot, lang_de, names)
        assert row["PARTNER"] == 4711
        assert row["BU_GROUP"] == "0001"
        assert row["NAME_LAST"] == "Mustermann"
        assert row["NAME_FIRST"] == "Max"
        assert row["BPKIND"] == ""


class TestUnnamedRows:
    """Rows without an accessible name (``- row:``) of the result grid, and only of it (#78)."""

    _GRID = """
  - textbox "Number of Hits": "2"
    - grid:
      - row:
        - columnheader "Column for row selection"
        - columnheader "Partner"
        - columnheader "Name"
      - row:
        - gridcell "To select a row, press the space bar."
        - gridcell "4711":
          - textbox "Partner"
        - gridcell "Max":
          - textbox "Name"
      - row:
        - gridcell "To select a row, press the space bar."
        - gridcell "4712":
          - textbox "Partner"
        - gridcell:
          - textbox
    - rowgroup
"""
    _OTHER_GRID = """
    - grid:
      - row:
        - gridcell "Other"
        - gridcell "NOISE"
        - gridcell "NOISE2"
"""

    def test_unnamed_data_rows_are_parsed(self, lang_en: LanguagePack) -> None:
        rows = parse_se16_rows(self._GRID, lang_en)
        assert rows == [{"Partner": 4711, "Name": "Max"}, {"Partner": 4712, "Name": ""}]

    def test_unnamed_rows_of_a_later_grid_are_ignored(self, lang_en: LanguagePack) -> None:
        rows = parse_se16_rows(self._GRID + self._OTHER_GRID, lang_en)
        assert [r["Partner"] for r in rows] == [4711, 4712]

    def test_unnamed_rows_of_an_earlier_grid_are_ignored(self, lang_en: LanguagePack) -> None:
        rows = parse_se16_rows(self._OTHER_GRID + self._GRID, lang_en)
        assert [r["Partner"] for r in rows] == [4711, 4712]


class TestRowKey:
    """Duplicate detection must not collide when values only differ in where they are split (#78)."""

    def test_split_values_do_not_collide(self) -> None:
        from sapwebguimcp.tools.se16_tools import _row_key

        assert _row_key({"a": "AB", "b": "C"}) != _row_key({"a": "A", "b": "BC"})
        assert _row_key({"a": "AB", "b": "C"}) == _row_key({"a": "AB", "b": "C"})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
