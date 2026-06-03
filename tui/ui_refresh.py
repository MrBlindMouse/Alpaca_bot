"""Skip Static/Label updates when rendered content is unchanged."""

from __future__ import annotations

from typing import Optional, Union

from textual.widgets import Label, Static

TextWidget = Union[Static, Label]


def update_text_if_changed(
    widget: TextWidget,
    content: str,
    last: Optional[str],
) -> str:
    """Update widget only when content differs. Returns the current content."""
    if content == last:
        return last or content
    widget.update(content)
    return content
