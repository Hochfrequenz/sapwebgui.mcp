"""``sap_get_form_fields`` reports checkboxes and radio buttons with their checked state (issue #101)."""

from typing import Any

import pytest

from sapwebguimcp.backend.webgui.backend import WebGuiBackend
from sapwebguimcp.models.sap_results import FormField, SapFieldType

from .test_status_popup_pack import _on_snapshot


async def _form_fields(backend: WebGuiBackend) -> list[FormField]:
    result = await backend.get_form_fields()
    return list(result.fields)


async def _by_label(snapshot: str) -> dict[str, FormField]:
    fields: list[FormField] = await _on_snapshot(snapshot, _form_fields)
    return {f.label: f for f in fields}


async def _by_id(html: str) -> dict[str, FormField]:
    fields: list[FormField] = await _on_snapshot("", _form_fields, html=html)
    return {f.id: f for f in fields if f.id}


def _selectors(fields: Any) -> list[FormField]:
    return [f for f in fields if f.field_type in (SapFieldType.CHECKBOX, SapFieldType.RADIO)]


@pytest.mark.anyio
async def test_se09_checkboxes_report_their_checked_state() -> None:
    fields = await _by_label("se09_shortcuts_de.html")
    workbench = fields["Workbench-Aufträge"]
    customizing = fields["Customizing-Aufträge"]
    assert workbench.field_type == SapFieldType.CHECKBOX
    assert workbench.checked is True
    assert workbench.id == "M0:46:1::4:1"
    assert customizing.field_type == SapFieldType.CHECKBOX
    assert customizing.checked is False
    assert customizing.id == "M0:46:1::3:1"
    assert fields["Änderbar"].checked is True
    assert fields["Freigegeben"].checked is False
    assert not [label for label in fields if label.startswith("Auswahl:")]


@pytest.mark.anyio
async def test_se11_radio_buttons_report_their_checked_state() -> None:
    fields = await _by_label("se11_initial_de.html")
    assert fields["Datenbanktabelle"].field_type == SapFieldType.RADIO
    assert fields["Datenbanktabelle"].checked is True
    assert fields["View"].field_type == SapFieldType.RADIO
    assert fields["View"].checked is False
    radios = [f for f in fields.values() if f.field_type == SapFieldType.RADIO]
    assert len([f for f in radios if f.checked is True]) == 1


@pytest.mark.anyio
async def test_class_only_controls_without_aria_report_their_state() -> None:
    fields = await _by_id(
        '<body><span id="c1" class="lsCheckBox lsCheckBox--checked" title="Eins">Eins</span>'
        '<span id="r1" class="lsRadioButton lsRadioButton--unchecked" title="Zwei">Zwei</span>'
        '<span id="c2" role="checkbox" title="Drei">Drei</span></body>'
    )
    assert fields["c1"].field_type == SapFieldType.CHECKBOX
    assert fields["c1"].checked is True
    assert fields["r1"].field_type == SapFieldType.RADIO
    assert fields["r1"].checked is False
    assert fields["c2"].field_type == SapFieldType.CHECKBOX
    assert fields["c2"].checked is None


@pytest.mark.anyio
async def test_input_inside_a_role_checkbox_is_reported_once() -> None:
    fields = await _by_id(
        '<body><span id="w" role="checkbox" aria-checked="true" aria-label="Wrapped">Wrapped '
        '<input type="checkbox" id="w-input" checked></span></body>'
    )
    checkboxes = _selectors(fields.values())
    assert [f.id for f in checkboxes] == ["w"]
    assert checkboxes[0].field_type == SapFieldType.CHECKBOX
    assert checkboxes[0].checked is True


@pytest.mark.anyio
async def test_input_inside_a_class_only_checkbox_is_reported_once() -> None:
    """SAP_BASIS 750 markup has the lsCheckBox wrapper without ARIA attributes."""
    fields = await _by_id(
        '<body><span id="k" class="lsCheckBox lsCheckBox--checked">Klasse '
        '<input type="checkbox" id="k-input" checked></span></body>'
    )
    checkboxes = _selectors(fields.values())
    assert [f.id for f in checkboxes] == ["k"]
    assert checkboxes[0].field_type == SapFieldType.CHECKBOX
    assert checkboxes[0].checked is True


@pytest.mark.anyio
async def test_disabled_role_checkbox_is_readonly() -> None:
    fields = await _by_id(
        '<body><div id="d" role="checkbox" aria-label="Gesperrt" aria-checked="false" aria-disabled="true" '
        'style="width:16px;height:16px"></div></body>'
    )
    assert fields["d"].field_type == SapFieldType.CHECKBOX
    assert fields["d"].checked is False
    assert fields["d"].readonly is True


@pytest.mark.anyio
async def test_class_only_disabled_modifier_gives_state_and_readonly() -> None:
    fields = await _by_id(
        '<body><span id="c3" class="lsCheckBox lsCheckBox--checked--disabled">Vier</span>'
        '<span id="r3" class="lsRadioButton lsRadioButton--unchecked--disabled">Fuenf</span></body>'
    )
    assert fields["c3"].field_type == SapFieldType.CHECKBOX
    assert fields["c3"].checked is True
    assert fields["c3"].readonly is True
    assert fields["r3"].field_type == SapFieldType.RADIO
    assert fields["r3"].checked is False
    assert fields["r3"].readonly is True


@pytest.mark.anyio
async def test_unnamed_grid_checkboxes_are_not_reported() -> None:
    """Table/ABAP-list checkboxes carry no name, so ``sap_set_checkbox`` cannot address them."""
    unnamed = await _by_id(
        '<body><span id="g1" role="checkbox" aria-checked="true" aria-disabled="true" '
        'style="display:inline-block;width:16px;height:16px"></span></body>'
    )
    assert "g1" not in unnamed
    for snapshot in ("se11_t000_fields_de.html", "sm37_results_de.html"):
        fields = await _by_label(snapshot)
        for field in _selectors(fields.values()):
            assert field.label, f"{snapshot}: unnamed selector control {field.id!r} was reported"

    # SE11 table-control checkboxes: all 28 checkboxes of this snapshot are unnamed grid cells with ids ending in "_c"
    se11 = await _on_snapshot("se11_t000_fields_de.html", _form_fields)
    se11_ids = [f.id for f in _selectors(se11)]
    assert not [i for i in se11_ids if i.endswith("_c")], f"unnamed grid checkboxes were reported: {se11_ids}"

    # SM37 ABAP-list checkboxes (role=checkbox, aria-disabled, no name) must not show up
    sm37 = await _on_snapshot("sm37_results_de.html", _form_fields)
    sm37_ids = [f.id for f in _selectors(sm37)]
    assert "M0:46:::5:0" not in sm37_ids
    assert "M0:46:::5:14" not in sm37_ids


@pytest.mark.anyio
async def test_text_inputs_keep_checked_none() -> None:
    fields = await _by_label("se09_shortcuts_de.html")
    text_fields = [f for f in fields.values() if f.field_type == SapFieldType.TEXT]
    assert text_fields
    assert all(f.checked is None for f in text_fields)
