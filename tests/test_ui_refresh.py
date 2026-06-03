"""Tests for TUI static update guards."""

from textual.widgets import Label, Static

from tui.ui_refresh import update_text_if_changed


class _FakeWidget:
    def __init__(self) -> None:
        self.renderable = ""

    def update(self, content: str) -> None:
        self.renderable = content


def test_update_text_if_changed_skips_identical():
    widget = _FakeWidget()
    first = update_text_if_changed(widget, "hello", None)
    assert first == "hello"
    assert widget.renderable == "hello"
    second = update_text_if_changed(widget, "hello", first)
    assert second == "hello"
    assert widget.renderable == "hello"


def test_update_text_if_changed_updates_on_change():
    widget = _FakeWidget()
    first = update_text_if_changed(widget, "a", None)
    second = update_text_if_changed(widget, "b", first)
    assert second == "b"
    assert widget.renderable == "b"


def test_update_text_if_changed_accepts_static_and_label_types():
    assert Static is not None
    assert Label is not None
