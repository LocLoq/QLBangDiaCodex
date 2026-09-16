from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

from ttkbootstrap.constants import LEFT

from normastore.ui.theme import theme_palette


def tooltip_position(pointer_x: int, pointer_y: int, tooltip_width: int, tooltip_height: int, bounds_x: int, bounds_y: int, bounds_width: int, bounds_height: int, offset: int = 16) -> tuple[int, int]:
    """Place a tooltip beside the cursor without letting it leave the virtual desktop."""
    right, bottom = bounds_x + bounds_width, bounds_y + bounds_height
    x, y = pointer_x + offset, pointer_y + offset
    if x + tooltip_width > right:
        x = pointer_x - tooltip_width - offset
    if y + tooltip_height > bottom:
        y = pointer_y - tooltip_height - offset
    return max(bounds_x, min(x, right - tooltip_width)), max(bounds_y, min(y, bottom - tooltip_height))


class Tooltip:
    """A single, non-focus popup for a composite widget and all its children."""
    _active: "Tooltip | None" = None

    def __init__(self, widget: tk.Widget, text: Callable[[], str] | str) -> None:
        self.widget, self.text = widget, text
        self.tip: tk.Toplevel | None = None
        self.after_id: str | None = None
        self.pointer_x = self.pointer_y = 0
        self._bind_composite(widget)
        widget.bind("<Unmap>", self.hide, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")

    @classmethod
    def hide_active(cls) -> None:
        if cls._active:
            cls._active.hide()

    def _bind_composite(self, widget: tk.Widget) -> None:
        widget.bind("<Enter>", self._enter, add="+")
        widget.bind("<Motion>", self._motion, add="+")
        widget.bind("<Leave>", self._leave, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")
        widget.bind("<MouseWheel>", self.hide, add="+")
        for child in widget.winfo_children():
            self._bind_composite(child)

    def _remember_pointer(self, event) -> None:
        self.pointer_x, self.pointer_y = event.x_root, event.y_root

    def _enter(self, event) -> None:
        self._remember_pointer(event)
        if self.tip:
            self._move_tip()
        else:
            self._schedule()

    def _motion(self, event) -> None:
        self._remember_pointer(event)
        if self.tip:
            self._move_tip()
        elif not self.after_id:
            self._schedule()

    def _leave(self, _event=None) -> None:
        self.widget.after_idle(self._hide_if_outside)

    def _hide_if_outside(self) -> None:
        if not self._pointer_in_widget_tree():
            self.hide()

    def _pointer_in_widget_tree(self) -> bool:
        try:
            x, y = self.widget.winfo_pointerxy()
            current = self.widget.winfo_containing(x, y)
            while current:
                if current == self.widget:
                    return True
                current = current.master
        except tk.TclError:
            return False
        return False

    def _schedule(self) -> None:
        self._cancel_schedule()
        self.after_id = self.widget.after(500, self.show)

    def _cancel_schedule(self) -> None:
        if self.after_id:
            try:
                self.widget.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None

    def _value(self) -> str:
        return self.text() if callable(self.text) else self.text

    def show(self) -> None:
        self.after_id = None
        if not self._pointer_in_widget_tree():
            return
        value = self._value()
        if not value:
            return
        Tooltip.hide_active()
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_attributes("-topmost", True)
        self.tip.configure(background=theme_palette(self._is_dark()).tooltip_background)
        ttk.Label(self.tip, text=value, justify=LEFT, padding=8, wraplength=320, style="Norma.Tooltip.TLabel").pack()
        Tooltip._active = self
        self.tip.update_idletasks()
        self._move_tip()

    def _is_dark(self) -> bool:
        return ttk.Style(self.widget).theme_use() == "superhero"

    def _move_tip(self) -> None:
        if not self.tip or not self.tip.winfo_exists():
            return
        if not self.pointer_x and not self.pointer_y:
            self.pointer_x, self.pointer_y = self.widget.winfo_pointerxy()
        x, y = tooltip_position(self.pointer_x, self.pointer_y, self.tip.winfo_reqwidth(), self.tip.winfo_reqheight(), self.widget.winfo_vrootx(), self.widget.winfo_vrooty(), self.widget.winfo_vrootwidth(), self.widget.winfo_vrootheight())
        self.tip.wm_geometry(f"+{x}+{y}")

    def _on_destroy(self, event) -> None:
        if event.widget == self.widget:
            self.hide()

    def hide(self, _event=None) -> None:
        self._cancel_schedule()
        if self.tip:
            try:
                if self.tip.winfo_exists():
                    self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None
        if Tooltip._active is self:
            Tooltip._active = None


class TreeviewTooltip(Tooltip):
    """Tooltip whose content follows the Treeview row under the pointer."""
    def __init__(self, tree: ttk.Treeview, text_for_row: Callable[[str], str]) -> None:
        self.text_for_row, self.hovered_row = text_for_row, None
        self.widget, self.text, self.tip, self.after_id = tree, "", None, None
        self.pointer_x = self.pointer_y = 0
        tree.bind("<Motion>", self._tree_motion, add="+")
        tree.bind("<Leave>", self._tree_leave, add="+")
        tree.bind("<ButtonPress>", self.hide, add="+")
        tree.bind("<MouseWheel>", self.hide, add="+")
        tree.bind("<Unmap>", self.hide, add="+")
        tree.bind("<Destroy>", self._on_destroy, add="+")

    def _tree_motion(self, event) -> None:
        row = self.widget.identify_row(event.y)
        self._remember_pointer(event)
        if not row:
            self.hovered_row = None
            self.hide()
        elif row != self.hovered_row:
            self.hide()
            self.hovered_row = row
            self._schedule()
        elif self.tip:
            self._move_tip()
        elif not self.after_id:
            self._schedule()

    def _tree_leave(self, _event=None) -> None:
        self.hovered_row = None
        self.hide()

    def _value(self) -> str:
        return self.text_for_row(self.hovered_row) if self.hovered_row else ""
