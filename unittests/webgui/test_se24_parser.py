"""
Unit tests for SE24 (Class Builder) parser.

Tests parsing of YAML accessibility snapshots from SE24 screens.
"""

from pathlib import Path

import pytest

from sapwebguimcp.backend.webgui.parsers.se24_parser import (
    SE24TabSnapshots,
    count_se24_grid_rows,
    parse_se24_attributes_snapshot,
    parse_se24_interfaces_table,
    parse_se24_methods_snapshot,
    parse_se24_properties_snapshot,
    parse_se24_snapshot,
)
from sapwebguimcp.lang import LanguagePack
from sapwebguimcp.models import TableData
from sapwebguimcp.models.se24_models import SE24Entry, SE24Error

SNAPSHOTS_DIR = Path(__file__).parent / "testdata" / "se24_exploration"


def _load_snapshot(name: str) -> str:
    """Load a YAML snapshot file."""
    filepath = SNAPSHOTS_DIR / f"{name}_de.yaml"
    if not filepath.exists():
        pytest.skip(f"Snapshot {filepath} not available - run exploration tests first")
    return filepath.read_text(encoding="utf-8")


def _load_table(name: str) -> TableData:
    """Load a captured table read (JSON) of the interfaces grid."""
    filepath = SNAPSHOTS_DIR / f"{name}_de.json"
    if not filepath.exists():
        pytest.skip(f"Table {filepath} not available - run exploration tests first")
    return TableData.model_validate_json(filepath.read_text(encoding="utf-8"))


# =============================================================================
# Method Parsing Tests
# =============================================================================


class TestParseMethodsSnapshot:
    """Tests for parsing SE24 Methods tab snapshots."""

    def test_cl_abap_char_utilities_has_methods(self, lang_de: LanguagePack) -> None:
        """CL_ABAP_CHAR_UTILITIES methods tab should yield methods."""
        snapshot = _load_snapshot("se24_cl_abap_char_utilities_methods")
        methods = parse_se24_methods_snapshot(snapshot, lang_de)

        assert len(methods) >= 3
        names = {m.name for m in methods}
        assert "ENDIAN_TO_NUMBER_FORMAT" in names
        assert "NUMBER_FORMAT_TO_ENDIAN" in names
        assert "GET_SIMPLE_SPACES_FOR_CUR_CP" in names

    def test_cl_abap_char_utilities_methods_are_static(self, lang_de: LanguagePack) -> None:
        """All CL_ABAP_CHAR_UTILITIES methods are static."""
        snapshot = _load_snapshot("se24_cl_abap_char_utilities_methods")
        methods = parse_se24_methods_snapshot(snapshot, lang_de)

        for m in methods:
            assert m.is_static, f"Method {m.name} should be static"

    def test_cl_abap_char_utilities_methods_are_public(self, lang_de: LanguagePack) -> None:
        """All CL_ABAP_CHAR_UTILITIES methods are public."""
        snapshot = _load_snapshot("se24_cl_abap_char_utilities_methods")
        methods = parse_se24_methods_snapshot(snapshot, lang_de)

        for m in methods:
            assert m.visibility == "public", f"Method {m.name} should be public"

    def test_cl_salv_table_has_methods(self, lang_de: LanguagePack) -> None:
        """CL_SALV_TABLE methods tab should yield interface methods."""
        snapshot = _load_snapshot("se24_cl_salv_table_methods")
        methods = parse_se24_methods_snapshot(snapshot, lang_de)

        assert len(methods) >= 10
        names = {m.name for m in methods}
        # These are interface methods with ~ separator
        assert "IF_SALV_GUI_OM_MODEL_INFO~MODEL_TYPE" in names
        assert "IF_SALV_GUI_OM_TABLE_ACTION~DISPLAY" in names
        assert "IF_SALV_GUI_OM_TABLE_ACTION~REFRESH" in names

    def test_cl_salv_table_methods_visibility(self, lang_de: LanguagePack) -> None:
        """CL_SALV_TABLE methods should have correct visibility."""
        snapshot = _load_snapshot("se24_cl_salv_table_methods")
        methods = parse_se24_methods_snapshot(snapshot, lang_de)

        for m in methods:
            assert m.visibility == "public", f"Method {m.name} should be public"

    def test_cl_salv_table_methods_are_instance(self, lang_de: LanguagePack) -> None:
        """CL_SALV_TABLE visible methods are instance methods."""
        snapshot = _load_snapshot("se24_cl_salv_table_methods")
        methods = parse_se24_methods_snapshot(snapshot, lang_de)

        for m in methods:
            assert not m.is_static, f"Method {m.name} should be instance (not static)"

    def test_cl_salv_table_method_descriptions(self, lang_de: LanguagePack) -> None:
        """CL_SALV_TABLE methods should have descriptions."""
        snapshot = _load_snapshot("se24_cl_salv_table_methods")
        methods = parse_se24_methods_snapshot(snapshot, lang_de)

        display_method = next(m for m in methods if m.name == "IF_SALV_GUI_OM_TABLE_ACTION~DISPLAY")
        assert display_method.description == "Output table"

        close_method = next(m for m in methods if m.name == "IF_SALV_GUI_OM_TABLE_ACTION~CLOSE_SCREEN")
        assert close_method.description == "Close Window"

    def test_empty_snapshot_returns_empty(self, lang_de: LanguagePack) -> None:
        """Empty or non-grid snapshot returns no methods."""
        snapshot = '- heading "Something"'
        methods = parse_se24_methods_snapshot(snapshot, lang_de)
        assert methods == []

    def test_synthetic_static_method(self, lang_de: LanguagePack) -> None:
        """Parse a synthetic Static Method row."""
        snapshot = """- grid:
  - rowgroup:
    - row "Methode Art Sichtbarkeit Methodentyp Beschreibung":
      - columnheader "Methode"
      - columnheader "Art"
    - row "MY_METHOD Static Method Public Leer Does something":
      - gridcell "MY_METHOD":
        - textbox
      - gridcell "Static Method":
        - textbox
      - gridcell "Public":
        - textbox
      - gridcell "Leer"
      - gridcell "Does something":
        - textbox
"""
        methods = parse_se24_methods_snapshot(snapshot, lang_de)
        assert len(methods) == 1
        assert methods[0].name == "MY_METHOD"
        assert methods[0].is_static is True
        assert methods[0].visibility == "public"
        assert methods[0].description == "Does something"

    def test_synthetic_interface_method(self, lang_de: LanguagePack) -> None:
        """Parse a synthetic interface method row (with ~)."""
        snapshot = """- grid:
  - rowgroup:
    - row "Methode Art Sichtbarkeit Methodentyp Beschreibung":
      - columnheader "Methode"
    - row "IF_MY_INTERFACE~DO_THING Instance Method Protected Leer Action":
      - gridcell "IF_MY_INTERFACE~DO_THING":
        - textbox
      - gridcell "Instance Method":
        - textbox
      - gridcell "Protected":
        - textbox
      - gridcell "Leer"
      - gridcell "Action":
        - textbox
"""
        methods = parse_se24_methods_snapshot(snapshot, lang_de)
        assert len(methods) == 1
        assert methods[0].name == "IF_MY_INTERFACE~DO_THING"
        assert methods[0].is_static is False
        assert methods[0].visibility == "protected"
        assert methods[0].description == "Action"

    def test_constructor_detection(self, lang_de: LanguagePack) -> None:
        """CONSTRUCTOR should be flagged as constructor."""
        snapshot = """- grid:
  - rowgroup:
    - row "header":
      - columnheader "Methode"
    - row "CONSTRUCTOR Instance Method Public Leer Constructor":
      - gridcell "CONSTRUCTOR":
        - textbox
      - gridcell "Instance Method":
        - textbox
      - gridcell "Public":
        - textbox
      - gridcell "Leer"
      - gridcell "Constructor":
        - textbox
"""
        methods = parse_se24_methods_snapshot(snapshot, lang_de)
        assert len(methods) == 1
        assert methods[0].is_constructor is True

    def test_synthetic_abstract_method(self, lang_de: LanguagePack) -> None:
        """Parse a synthetic Abstract Method row."""
        snapshot = """- grid:
  - rowgroup:
    - row "header":
      - columnheader "Methode"
    - row "MY_METHOD Abstract Method Public Leer Does something":
      - gridcell "MY_METHOD":
        - textbox
      - gridcell "Abstract Method":
        - textbox
      - gridcell "Public":
        - textbox
      - gridcell "Leer"
      - gridcell "Does something":
        - textbox
"""
        methods = parse_se24_methods_snapshot(snapshot, lang_de)
        assert len(methods) == 1
        assert methods[0].name == "MY_METHOD"
        assert methods[0].is_abstract is True
        assert methods[0].is_static is False

    def test_synthetic_abstract_method_german(self, lang_de: LanguagePack) -> None:
        """Parse a synthetic Abstrakte Methode row (German)."""
        snapshot = """- grid:
  - rowgroup:
    - row "header":
      - columnheader "Methode"
    - row "MY_METHOD Abstrakte Methode Public Leer Tut etwas":
      - gridcell "MY_METHOD":
        - textbox
      - gridcell "Abstrakte Methode":
        - textbox
      - gridcell "Public":
        - textbox
      - gridcell "Leer"
      - gridcell "Tut etwas":
        - textbox
"""
        methods = parse_se24_methods_snapshot(snapshot, lang_de)
        assert len(methods) == 1
        assert methods[0].is_abstract is True
        assert methods[0].is_static is False

    def test_method_without_description(self, lang_de: LanguagePack) -> None:
        """Method with empty description gridcell."""
        snapshot = """- grid:
  - rowgroup:
    - row "header":
      - columnheader "Methode"
    - row "MY_METHOD Instance Method Public Leer":
      - gridcell "MY_METHOD":
        - textbox
      - gridcell "Instance Method":
        - textbox
      - gridcell "Public":
        - textbox
      - gridcell "Leer"
      - gridcell:
        - textbox
"""
        methods = parse_se24_methods_snapshot(snapshot, lang_de)
        assert len(methods) == 1
        assert methods[0].description == ""


# =============================================================================
# Attribute Parsing Tests
# =============================================================================


class TestParseAttributesSnapshot:
    """Tests for parsing SE24 Attributes tab snapshots."""

    def test_cl_abap_char_utilities_has_attributes(self, lang_de: LanguagePack) -> None:
        """CL_ABAP_CHAR_UTILITIES attributes tab should yield constants."""
        snapshot = _load_snapshot("se24_cl_abap_char_utilities_attributes")
        attributes = parse_se24_attributes_snapshot(snapshot, lang_de)

        assert len(attributes) >= 10
        names = {a.name for a in attributes}
        assert "HORIZONTAL_TAB" in names
        assert "NEWLINE" in names
        assert "CR_LF" in names
        assert "CHARSIZE" in names
        assert "ENDIAN" in names

    def test_cl_abap_char_utilities_constants(self, lang_de: LanguagePack) -> None:
        """Most CL_ABAP_CHAR_UTILITIES attributes are constants."""
        snapshot = _load_snapshot("se24_cl_abap_char_utilities_attributes")
        attributes = parse_se24_attributes_snapshot(snapshot, lang_de)

        constants = [a for a in attributes if a.is_constant]
        assert len(constants) >= 10

        ht = next(a for a in attributes if a.name == "HORIZONTAL_TAB")
        assert ht.is_constant
        assert ht.is_static
        assert ht.visibility == "public"
        assert ht.type_ref == "ABAP_CHAR1"

    def test_cl_abap_char_utilities_private_attr(self, lang_de: LanguagePack) -> None:
        """SPACE_STR is a private static attribute."""
        snapshot = _load_snapshot("se24_cl_abap_char_utilities_attributes")
        attributes = parse_se24_attributes_snapshot(snapshot, lang_de)

        space_str = next((a for a in attributes if a.name == "SPACE_STR"), None)
        assert space_str is not None
        assert space_str.visibility == "private"
        assert space_str.is_static
        assert not space_str.is_constant
        assert space_str.type_ref == "STRING"

    def test_attribute_type_refs(self, lang_de: LanguagePack) -> None:
        """Attributes should have correct type references."""
        snapshot = _load_snapshot("se24_cl_abap_char_utilities_attributes")
        attributes = parse_se24_attributes_snapshot(snapshot, lang_de)

        charsize = next(a for a in attributes if a.name == "CHARSIZE")
        assert charsize.type_ref == "I"

        bom_little = next(a for a in attributes if a.name == "BYTE_ORDER_MARK_LITTLE")
        assert bom_little.type_ref == "ABAP_BYTE_ORDER_MARK"

    def test_empty_snapshot_returns_empty(self, lang_de: LanguagePack) -> None:
        """Empty or non-grid snapshot returns no attributes."""
        snapshot = '- heading "Something"'
        attributes = parse_se24_attributes_snapshot(snapshot, lang_de)
        assert attributes == []

    def test_synthetic_attribute(self, lang_de: LanguagePack) -> None:
        """Parse a synthetic attribute row."""
        snapshot = """- grid:
  - rowgroup:
    - row "header":
      - columnheader "Attribut"
    - row "MY_ATTR Constant Public Type STRING My description 'hello'":
      - gridcell "MY_ATTR":
        - textbox
      - gridcell "Constant":
        - textbox
      - gridcell "Public":
        - textbox
      - gridcell:
        - checkbox [disabled]
      - gridcell "Type":
        - textbox
      - gridcell "STRING":
        - textbox
      - gridcell:
        - button "Direkte Typeingabe"
      - gridcell "My description":
        - textbox
      - gridcell "'hello'":
        - textbox
"""
        attributes = parse_se24_attributes_snapshot(snapshot, lang_de)
        assert len(attributes) == 1
        assert attributes[0].name == "MY_ATTR"
        assert attributes[0].is_constant is True
        assert attributes[0].is_static is True
        assert attributes[0].visibility == "public"
        assert attributes[0].type_ref == "STRING"
        assert attributes[0].description == "My description"


# =============================================================================
# Full Snapshot Parsing Tests
# =============================================================================


class TestParseFullSnapshot:
    """Tests for parse_se24_snapshot with tab snapshots."""

    def test_cl_salv_table_full_parse(self, lang_de: LanguagePack) -> None:
        """Full parse of CL_SALV_TABLE should return entry with methods."""
        main = _load_snapshot("se24_cl_salv_table_main")
        methods = _load_snapshot("se24_cl_salv_table_methods")

        result = parse_se24_snapshot(
            snapshot=main,
            class_name="CL_SALV_TABLE",
            t=lang_de,
            tab_snapshots=SE24TabSnapshots(methods_tab=methods),
        )

        assert isinstance(result, SE24Entry)
        assert result.class_name == "CL_SALV_TABLE"
        assert len(result.methods) >= 10

    def test_cl_abap_char_utilities_full_parse(self, lang_de: LanguagePack) -> None:
        """Full parse of CL_ABAP_CHAR_UTILITIES should return entry with methods and attributes."""
        main = _load_snapshot("se24_cl_abap_char_utilities_main")
        methods = _load_snapshot("se24_cl_abap_char_utilities_methods")
        attributes = _load_snapshot("se24_cl_abap_char_utilities_attributes")

        result = parse_se24_snapshot(
            snapshot=main,
            class_name="CL_ABAP_CHAR_UTILITIES",
            t=lang_de,
            tab_snapshots=SE24TabSnapshots(methods_tab=methods, attributes_tab=attributes),
        )

        assert isinstance(result, SE24Entry)
        assert result.class_name == "CL_ABAP_CHAR_UTILITIES"
        assert result.object_type == "class"
        assert len(result.methods) >= 3
        assert len(result.attributes) >= 10

    def test_not_found_class(self, lang_de: LanguagePack) -> None:
        """Snapshot with 'not found' should return SE24Error."""
        snapshot = _load_snapshot("se24_not_found")

        result = parse_se24_snapshot(
            snapshot=snapshot,
            class_name="ZZZNOTEXIST_CLASS_99",
            t=lang_de,
        )

        assert isinstance(result, SE24Error)
        assert "not found" in result.error.lower() or "initial screen" in result.error.lower()

    def test_no_tab_snapshots(self, lang_de: LanguagePack) -> None:
        """Without tab snapshots, methods and attributes are empty."""
        main = _load_snapshot("se24_cl_salv_table_main")
        result = parse_se24_snapshot(snapshot=main, class_name="CL_SALV_TABLE", t=lang_de)

        assert isinstance(result, SE24Entry)
        assert result.methods == []
        assert result.attributes == []


_EDIT_DIR = Path(__file__).parent / "testdata" / "se24_edit_exploration"


def _read(directory: Path, name: str) -> str:
    return (directory / name).read_text(encoding="utf-8")


class TestHeadingNameOnRealSnapshots:
    """The name comes from the heading, not from the ``main`` landmark line above it."""

    def test_display_heading_in_german(self, lang_de: LanguagePack) -> None:
        result = parse_se24_snapshot(_read(_EDIT_DIR, "se24_edit_display_main_de.yaml"), "zcl_x", lang_de)
        assert isinstance(result, SE24Entry)
        assert result.class_name == "ZCL_TEST_MCP_EDIT"

    def test_display_heading_in_english(self, lang_en: LanguagePack) -> None:
        result = parse_se24_snapshot(_read(_EDIT_DIR, "se24_edit_display_main_en.yaml"), "zcl_x", lang_en)
        assert isinstance(result, SE24Entry)
        assert result.class_name == "ZCL_TEST_MCP_EDIT"

    def test_interface_heading_in_german(self, lang_de: LanguagePack) -> None:
        result = parse_se24_snapshot(_read(SNAPSHOTS_DIR, "se24_if_serializable_object_main_de.yaml"), "x", lang_de)
        assert isinstance(result, SE24Entry)
        assert result.class_name == "IF_SERIALIZABLE_OBJECT"


# =============================================================================
# Properties tab and interfaces table (#97)
# =============================================================================


class TestParsePropertiesSnapshot:
    """The properties tab carries description, package, superclass, instantiation and the final flag."""

    def test_subclass_final_public(self, lang_de: LanguagePack) -> None:
        p = parse_se24_properties_snapshot(_load_snapshot("se24_cx_sy_zerodivide_properties"), lang_de)
        assert p.superclass == "CX_SY_ARITHMETIC_ERROR"
        assert p.description == "System-Exception für Teilen durch Null."
        assert p.is_final is True
        assert p.is_abstract is False
        assert p.package == "S_ABAP_EXCEPTIONS"

    def test_abstract_root_class_has_no_superclass(self, lang_de: LanguagePack) -> None:
        p = parse_se24_properties_snapshot(_load_snapshot("se24_cx_root_properties"), lang_de)
        assert p.superclass is None
        assert p.is_abstract is True
        assert p.is_final is False
        assert p.description == "Abstrakte Oberklasse aller globalen Exceptions"

    def test_private_final_class(self, lang_de: LanguagePack) -> None:
        p = parse_se24_properties_snapshot(_load_snapshot("se24_cl_salv_table_properties"), lang_de)
        assert (p.package, p.description, p.is_final, p.is_abstract, p.superclass) == (
            "SALV_OM_OBJECTS",
            "Basisklasse für einfache Tabellen",
            True,
            False,
            None,
        )

    def test_interface_has_description_and_package_only(self, lang_de: LanguagePack) -> None:
        p = parse_se24_properties_snapshot(_load_snapshot("se24_if_serializable_object_properties"), lang_de)
        assert (p.description, p.package, p.superclass, p.is_final, p.is_abstract) == (
            "Serialisierbares Objekt",
            "SABP_CORE",
            None,
            False,
            False,
        )

    def test_empty_snapshot_gives_defaults(self, lang_de: LanguagePack) -> None:
        p = parse_se24_properties_snapshot("", lang_de)
        assert (p.description, p.package, p.superclass, p.is_final, p.is_abstract) == ("", "", None, False, False)


class TestParseInterfacesTable:
    """The interfaces grid is read as a table; the column is found by its title, not by its position."""

    def test_cx_root_interfaces(self, lang_de: LanguagePack) -> None:
        table = _load_table("se24_cx_root_interfaces_table")
        assert parse_se24_interfaces_table(table, lang_de) == ["IF_MESSAGE", "IF_SERIALIZABLE_OBJECT"]

    def test_failed_table_gives_no_interfaces(self, lang_de: LanguagePack) -> None:
        assert parse_se24_interfaces_table(TableData.failure("x"), lang_de) == []

    def test_placeholders_and_duplicates_are_dropped(self, lang_de: LanguagePack) -> None:
        cells = ["IF_A", "-", "   ", "/ABC/IF_EXAMPLE", "IF_A"]
        table = TableData(
            headers=["", "Interface", "Beschreibung"],
            rows=[{"row": i, "data": {"Interface": c, "Beschreibung": "d"}} for i, c in enumerate(cells, 1)],
        )
        assert parse_se24_interfaces_table(table, lang_de) == ["IF_A", "/ABC/IF_EXAMPLE"]

    def test_methods_grid_is_not_the_interfaces_grid(self, lang_de: LanguagePack) -> None:
        table = TableData(
            headers=["", "Methode", "Art"],
            rows=[{"row": 1, "data": {"Methode": "DISPLAY", "Art": "Instanzmethode"}}],
        )
        assert parse_se24_interfaces_table(table, lang_de) == []


class TestCountGridRows:
    def test_counts_data_rows_of_the_grid(self) -> None:
        assert count_se24_grid_rows(_load_snapshot("se24_cx_root_interfaces")) == 19

    def test_empty_snapshot_has_no_rows(self) -> None:
        assert count_se24_grid_rows("") == 0


class TestParseSnapshotHeader:
    """``parse_se24_snapshot`` fills the header fields from the properties tab and the interfaces table."""

    def test_header_fields_from_tabs(self, lang_de: LanguagePack) -> None:
        tabs = SE24TabSnapshots(
            properties_tab=_load_snapshot("se24_cx_root_properties"),
            interfaces_table=_load_table("se24_cx_root_interfaces_table"),
        )
        result = parse_se24_snapshot(_load_snapshot("se24_cl_salv_table_main"), "CL_SALV_TABLE", lang_de, tabs)
        assert isinstance(result, SE24Entry)
        assert result.is_abstract is True
        assert result.is_final is False
        assert result.package == "S_ABAP_EXCEPTIONS"
        assert result.description == "Abstrakte Oberklasse aller globalen Exceptions"
        assert result.superclass is None
        assert result.interfaces == ["IF_MESSAGE", "IF_SERIALIZABLE_OBJECT"]

    def test_defaults_without_the_two_tabs(self, lang_de: LanguagePack) -> None:
        result = parse_se24_snapshot(_load_snapshot("se24_cl_salv_table_main"), "CL_SALV_TABLE", lang_de)
        assert isinstance(result, SE24Entry)
        assert (result.description, result.package, result.superclass) == ("", "", None)
        assert (result.is_abstract, result.is_final, result.interfaces) == (False, False, [])
