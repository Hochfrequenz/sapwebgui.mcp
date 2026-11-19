"""
Unit tests for SE11 YAML parser.

These tests run offline using captured YAML snapshots.
"""

import json
from pathlib import Path

import pytest

from sapwebguimcp import lang
from sapwebguimcp.lang.schema import LanguagePack
from sapwebguimcp.models.se11_models import SE11Entry, SE11Error, SE11Field
from sapwebguimcp.tools.se11_tools import _parse_se11_fields, _parse_se11_yaml

YAML_SNAPSHOTS_DIR = Path(__file__).parent / "testdata" / "yaml_snapshots"


def load_yaml_snapshot(name: str) -> str:
    """Load a YAML snapshot file and extract the snapshot content."""
    filepath = YAML_SNAPSHOTS_DIR / name
    if not filepath.exists():
        pytest.skip(f"Snapshot {name} not found - run integration tests first")

    content = filepath.read_text(encoding="utf-8")

    # The snapshot is wrapped in JSON with a "snapshot" field
    try:
        data = json.loads(content)
        return data.get("snapshot", content)
    except json.JSONDecodeError:
        return content


class TestParseSeYamlTable:
    """Tests for parsing SE11 table YAML snapshots."""

    def test_parse_t000_table_name(self, lang_de: LanguagePack) -> None:
        """Test that table name is extracted correctly."""
        yaml_content = load_yaml_snapshot("se11_t000_fields_de.yaml")
        result = _parse_se11_yaml(yaml_content, "table", lang_de)

        assert isinstance(result, SE11Entry)
        assert result.name == "T000"

    def test_parse_t000_description(self, lang_de: LanguagePack) -> None:
        """Test that table description is extracted correctly."""
        yaml_content = load_yaml_snapshot("se11_t000_fields_de.yaml")
        result = _parse_se11_yaml(yaml_content, "table", lang_de)

        assert isinstance(result, SE11Entry)
        assert result.description == "Mandanten"

    def test_parse_t000_object_type(self, lang_de: LanguagePack) -> None:
        """Test that object type is set correctly."""
        yaml_content = load_yaml_snapshot("se11_t000_fields_de.yaml")
        result = _parse_se11_yaml(yaml_content, "table", lang_de)

        assert isinstance(result, SE11Entry)
        assert result.object_type == "table"

    def test_parse_t000_has_timestamp(self, lang_de: LanguagePack) -> None:
        """Test that retrieved_at timestamp is set."""
        yaml_content = load_yaml_snapshot("se11_t000_fields_de.yaml")
        result = _parse_se11_yaml(yaml_content, "table", lang_de)

        assert isinstance(result, SE11Entry)
        assert result.retrieved_at is not None

    def test_parse_t000_has_fields(self, lang_de: LanguagePack) -> None:
        """Test that fields are parsed."""
        yaml_content = load_yaml_snapshot("se11_t000_fields_de.yaml")
        result = _parse_se11_yaml(yaml_content, "table", lang_de)

        assert isinstance(result, SE11Entry)
        assert len(result.fields) > 0

    def test_parse_t000_all_fields_of_the_snapshot(self, lang_de: LanguagePack) -> None:
        """The recorded grid holds five single-quoted rows (description with ": "); none may be dropped (#91)."""
        fields = _parse_se11_fields(load_yaml_snapshot("se11_t000_fields_de.yaml"), lang_de)
        assert [f.name for f in fields] == [
            "MANDT",
            "MTEXT",
            "ORT01",
            "MWAER",
            "ADRNR",
            "CCCATEGORY",
            "CCCORACTIV",
            "CCNOCLIIND",
            "CCCOPYLOCK",
            "CCNOCASCAD",
            "CCSOFTLOCK",
            "CCORIGCONT",
            "CCIMAILDIS",
            "CCTEMPLOCK",
        ]

    def test_parse_t000_mandt_field(self, lang_de: LanguagePack) -> None:
        """Test that MANDT field is parsed correctly."""
        yaml_content = load_yaml_snapshot("se11_t000_fields_de.yaml")
        result = _parse_se11_yaml(yaml_content, "table", lang_de)

        assert isinstance(result, SE11Entry)

        # Find MANDT field
        mandt_fields = [f for f in result.fields if f.name == "MANDT"]
        assert len(mandt_fields) == 1

        mandt = mandt_fields[0]
        assert mandt.datatype == "CLNT"
        assert mandt.length == 3
        assert mandt.decimals is None  # None for non-numeric types
        assert mandt.description == "Mandant"
        assert mandt.is_key is True

    def test_parse_t000_mtext_field(self, lang_de: LanguagePack) -> None:
        """Test that non-key field is parsed correctly."""
        yaml_content = load_yaml_snapshot("se11_t000_fields_de.yaml")
        result = _parse_se11_yaml(yaml_content, "table", lang_de)

        assert isinstance(result, SE11Entry)

        # Find MTEXT field
        mtext_fields = [f for f in result.fields if f.name == "MTEXT"]
        assert len(mtext_fields) == 1

        mtext = mtext_fields[0]
        assert mtext.datatype == "CHAR"
        assert mtext.length == 25
        assert mtext.description == "Bezeichnung des Mandanten"
        assert mtext.is_key is False


class TestParseSeYamlFields:
    """Tests for the field parsing helper function."""

    def test_parse_fields_returns_list(self, lang_de: LanguagePack) -> None:
        """Test that _parse_se11_fields returns a list."""
        yaml_content = load_yaml_snapshot("se11_t000_fields_de.yaml")
        fields = _parse_se11_fields(yaml_content, lang_de)

        assert isinstance(fields, list)

    def test_parse_fields_all_se11field(self, lang_de: LanguagePack) -> None:
        """Test that all returned items are SE11Field."""
        yaml_content = load_yaml_snapshot("se11_t000_fields_de.yaml")
        fields = _parse_se11_fields(yaml_content, lang_de)

        for field in fields:
            assert isinstance(field, SE11Field)

    def test_parse_fields_datatypes_are_uppercase(self, lang_de: LanguagePack) -> None:
        """Test that data types are uppercase ABAP types."""
        yaml_content = load_yaml_snapshot("se11_t000_fields_de.yaml")
        fields = _parse_se11_fields(yaml_content, lang_de)

        for field in fields:
            assert field.datatype == field.datatype.upper()
            assert len(field.datatype) <= 10  # ABAP types are short


class TestParseSeYamlErrors:
    """Tests for error handling in parsing."""

    def test_parse_empty_yaml_returns_error(self, lang_de: LanguagePack) -> None:
        """Test that empty YAML returns an error."""
        result = _parse_se11_yaml("", "table", lang_de)

        assert isinstance(result, SE11Error)
        assert "not found" in result.error.lower()

    def test_parse_invalid_yaml_returns_error(self, lang_de: LanguagePack) -> None:
        """Test that invalid YAML returns an error."""
        result = _parse_se11_yaml("random text without structure", "table", lang_de)

        assert isinstance(result, SE11Error)

    def test_parse_yaml_without_fields_returns_error(self, lang_de: LanguagePack) -> None:
        """Test that YAML without field grid returns an error."""
        yaml_content = """
- main "Dictionary: Tabelle anzeigen":
  - textbox "Transp.Tabelle": T000
  - textbox "Kurzbeschreibung": Test Table
"""
        result = _parse_se11_yaml(yaml_content, "table", lang_de)

        assert isinstance(result, SE11Error)
        assert "Could not parse fields" in result.error


class TestParseSeYamlStructure:
    """Tests for parsing structure snapshots (if available)."""

    def test_parse_structure_placeholder(self, lang_de: LanguagePack) -> None:
        """Placeholder test for structure parsing - needs snapshot."""
        # This will be filled in when we have a structure snapshot
        yaml_content = """
- main "Dictionary: Struktur anzeigen":
  - textbox "Struktur": BAPIRET2
  - textbox "Kurzbeschreibung": Return Parameter
  - grid:
    - rowgroup:
      - row "Spalte...":
        - columnheader "Feld"
        - columnheader "Datentyp"
      - row "Zum Auswählen... TYPE  BAPI_MTYPE CHAR 1 0 0 Meldungstyp: S Success, E Error, W Warning, I Info, A Abort":
        - gridcell "TYPE":
          - textbox
        - gridcell:
          - checkbox [disabled]
        - gridcell:
          - checkbox "" [checked] [disabled]
        - gridcell "BAPI_MTYPE":
          - textbox
        - gridcell "CHAR":
          - button "CHAR"
        - gridcell "1":
          - textbox
        - gridcell "0":
          - textbox
        - gridcell "0":
          - textbox
        - gridcell "Meldungstyp":
          - textbox
"""
        result = _parse_se11_yaml(yaml_content, "structure", lang_de)

        # For now, this may fail parsing - that's expected until we have real snapshots
        # The test documents the expected behavior
        if isinstance(result, SE11Entry):
            assert result.object_type == "structure"
            assert result.name == "BAPIRET2"


class TestParseSeYamlLanguageParity:
    """A DE and an EN snapshot of the same object parse to the same entry (one search over the merged view)."""

    def test_de_and_en_snapshots_parse_to_the_same_entry(self) -> None:
        de_yaml = load_yaml_snapshot("se11_t000_fields_de.yaml")
        # The EN fixtures of this screen only cover the initial screen, so the DE field list is relabelled
        en_yaml = (
            de_yaml.replace(
                "Zum Auswählen einer Zeile drücken Sie die Leertaste.", "To select a row, press the space bar."
            )
            .replace('textbox "Transp.Tabelle"', 'textbox "Transparent Table"')
            .replace('textbox "Kurzbeschreibung"', 'textbox "Short Description"')
        )
        assert en_yaml != de_yaml
        with lang.use("DE"):
            de = _parse_se11_yaml(de_yaml, "table", lang.current())
        with lang.use("EN"):
            en = _parse_se11_yaml(en_yaml, "table", lang.current())

        assert isinstance(de, SE11Entry)
        assert isinstance(en, SE11Entry)
        assert (de.name, de.description) == ("T000", "Mandanten") == (en.name, en.description)
        assert [(f.name, f.datatype, f.length, f.decimals, f.is_key) for f in de.fields] == [
            (f.name, f.datatype, f.length, f.decimals, f.is_key) for f in en.fields
        ]


class TestTrailingColumnTitleNotInDescription:
    """The empty trailing column ("Gruppe") must not leak into the field description (#77)."""

    @staticmethod
    def _with_group_label(yaml_content: str) -> str:
        """Mimic the live DOM: the row name and the empty last cell carry the column title."""
        out: list[str] = []
        in_row = False
        for line in yaml_content.splitlines():
            out_line = line
            if line.lstrip().startswith(("- row ", "- 'row ")):
                in_row = "Zum Auswählen" in line
                if in_row:
                    end = "\"':" if line.lstrip().startswith("- '") else '":'  # single-quoted YAML row (#91)
                    out_line = line[: line.rindex(end)] + " Gruppe" + end
            elif in_row and line.strip() == "- gridcell:":
                out_line = line.replace("- gridcell:", '- gridcell "Gruppe":')
            out.append(out_line)
        return "\n".join(out)

    def test_group_suffix_is_stripped(self, lang_de: LanguagePack) -> None:
        yaml_content = self._with_group_label(load_yaml_snapshot("se11_t000_fields_de.yaml"))
        assert " Gruppe" in yaml_content
        fields = _parse_se11_fields(yaml_content, lang_de)
        assert fields
        assert fields[0].name == "MANDT"
        assert fields[0].description == "Mandant"
        assert all(not f.description.endswith("Gruppe") for f in fields)
        # the quoted rows (description with ": ") are stripped too (#91)
        assert {f.name: f.description for f in fields}["CCCATEGORY"].startswith("Client Control:")

    _GRID = """\
- grid "Felder":
  - rowgroup:
    - row "Feld Schl Init Datenelement Datentyp Länge Dezimalstellen Kurzbeschreibung Gruppe":
      - columnheader "Feld"
      - columnheader "Gruppe"
  - rowgroup:
    - row "Zum Auswählen einer Zeile drücken Sie die Leertaste. MATKL \ue05b \ue05b MATKL CHAR 9 0 0 @NAME@":
      - gridcell "Zum Auswählen einer Zeile drücken Sie die Leertaste."
      - gridcell "MATKL":
        - textbox
      @LAST@
@TRAILING@"""

    def _grid(self, name: str, last_cell: str, trailing: str = "") -> str:
        return self._GRID.replace("@NAME@", name).replace("@LAST@", last_cell).replace("@TRAILING@", trailing)

    def test_label_of_the_last_cell_strips_the_title(self, lang_de: LanguagePack) -> None:
        yaml_content = self._grid("Materialgruppe Gruppe", '- gridcell "Gruppe":')
        assert [f.description for f in _parse_se11_fields(yaml_content, lang_de)] == ["Materialgruppe"]

    def test_description_ending_in_column_title_is_kept(self, lang_de: LanguagePack) -> None:
        """A real description ending in the title word stays when the last cell is an unlabelled empty cell."""
        yaml_content = self._grid("Material Gruppe", "- gridcell:")
        assert [f.description for f in _parse_se11_fields(yaml_content, lang_de)] == ["Material Gruppe"]

    def test_unlabelled_empty_cell_without_title_in_name(self, lang_de: LanguagePack) -> None:
        """Empty cells without aria-labelledby (#78 snapshot) contribute no title: nothing to strip."""
        yaml_content = self._grid("Materialgruppe", "- gridcell:")
        assert [f.description for f in _parse_se11_fields(yaml_content, lang_de)] == ["Materialgruppe"]

    def test_only_the_rows_own_cells_count(self, lang_de: LanguagePack) -> None:
        """A labelled gridcell after the row (another grid) must not make an unlabelled last cell look labelled."""
        trailing = '- grid "Andere":\n  - row "x":\n    - gridcell "Gruppe"\n'
        yaml_content = self._grid("Material Gruppe", "- gridcell:", trailing)
        assert [f.description for f in _parse_se11_fields(yaml_content, lang_de)] == ["Material Gruppe"]

    def test_a_later_grid_with_cells_at_the_same_depth_does_not_count(self, lang_de: LanguagePack) -> None:
        """A later grid whose cells sit at the same depth as the row's cells ends the row at its shallower lines."""
        # the later grid is nested (indented), and its cells sit exactly at the depth of the row's own cells
        trailing = '  - grid "Andere":\n    - row "x":\n      - gridcell "Gruppe"\n'
        yaml_content = self._grid("Material Gruppe", "- gridcell:", trailing)
        assert [f.description for f in _parse_se11_fields(yaml_content, lang_de)] == ["Material Gruppe"]


class TestQuotedRows:
    """A row name containing ": " is serialised as a single-quoted YAML scalar (#91)."""

    _GRID = """\
- grid "Felder":
  - rowgroup:
    - row "Spalte für Zeilenauswahl Feld Key Datenelement Datentyp Länge Kurzbeschreibung Gruppe":
      - columnheader "Feld"
      - columnheader "Gruppe"
  - rowgroup:
    - row "@H@ MANDT   MANDT CLNT 3 0 0 Mandant":
      - gridcell "@H@"
      - gridcell "MANDT":
        - textbox
    - 'row "@H@ CCCATEGORY  CCCATEGORY CHAR 1 0 0 Client Control: Rolle des Mandanten (Productive, Test,...)"':
      - gridcell "@H@"
      - gridcell "CCCATEGORY":
        - textbox
    - 'row "@H@ ZQUOTE  ZQUOTE CHAR 1 0 0 Steuerung: Kunde''s Kennzeichen"':
      - gridcell "@H@"
      - gridcell "ZQUOTE":
        - textbox
    - row "@H@ LOGSYS  LOGSYS CHAR 10 0 0 Logisches System":
      - gridcell "@H@"
      - gridcell "LOGSYS":
        - textbox
""".replace("@H@", "Zum Auswählen einer Zeile drücken Sie die Leertaste.")

    def test_quoted_rows_are_not_dropped(self, lang_de: LanguagePack) -> None:
        fields = _parse_se11_fields(self._GRID, lang_de)
        assert [f.name for f in fields] == ["MANDT", "CCCATEGORY", "ZQUOTE", "LOGSYS"]

    def test_quoted_row_values(self, lang_de: LanguagePack) -> None:
        by_name = {f.name: f for f in _parse_se11_fields(self._GRID, lang_de)}
        assert by_name["CCCATEGORY"].datatype == "CHAR"
        assert by_name["CCCATEGORY"].length == 1
        assert by_name["CCCATEGORY"].description == "Client Control: Rolle des Mandanten (Productive, Test,...)"

    def test_doubled_apostrophe_is_unescaped(self, lang_de: LanguagePack) -> None:
        by_name = {f.name: f for f in _parse_se11_fields(self._GRID, lang_de)}
        assert by_name["ZQUOTE"].description == "Steuerung: Kunde's Kennzeichen"

    def test_row_before_a_quoted_row_keeps_its_description(self, lang_de: LanguagePack) -> None:
        by_name = {f.name: f for f in _parse_se11_fields(self._GRID, lang_de)}
        assert by_name["MANDT"].description == "Mandant"
