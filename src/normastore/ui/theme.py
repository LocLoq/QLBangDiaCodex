from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

from normastore.config import Settings


@dataclass(frozen=True)
class ThemePalette:
    background: str
    surface: str
    heading: str
    foreground: str
    muted: str
    accent: str
    border: str
    selection: str
    tooltip_background: str
    tooltip_foreground: str


def theme_palette(dark_mode: bool) -> ThemePalette:
    if dark_mode:
        return ThemePalette(
            background="#2B3E50", surface="#32465A", heading="#354D63",
            foreground="#F8FAFC", muted="#C4CED8", accent="#79B8F3",
            border="#526170", selection="#3F7FBA",
            tooltip_background="#1F2D3A", tooltip_foreground="#F8FAFC",
        )
    return ThemePalette(
        background="#FFFFFF", surface="#F7F9FB", heading="#EDF1F4",
        foreground="#212529", muted="#5F6B73", accent="#2C3E50",
        border="#CED4DA", selection="#6F8588",
        tooltip_background="#2C3E50", tooltip_foreground="#FFFFFF",
    )


def _preferences_path(settings: Settings) -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) / "NormaStore" if local_app_data else settings.cache_dir
    return root / "ui_preferences.json"


def _load_preferences(settings: Settings) -> dict[str, str]:
    preferences = {"theme": "flatly", "font_scale": "Vừa"}
    try:
        saved = json.loads(_preferences_path(settings).read_text(encoding="utf-8"))
        if saved.get("theme") == "darkly":
            preferences["theme"] = "superhero"
        elif saved.get("theme") in ("flatly", "superhero"):
            preferences["theme"] = saved["theme"]
        if saved.get("font_scale") in ("Nhỏ", "Vừa", "Lớn"):
            preferences["font_scale"] = saved["font_scale"]
    except (OSError, ValueError, TypeError):
        pass
    return preferences


class AppearanceMixin:
    """Application-wide ttk, native-widget, and Matplotlib appearance helpers."""

    def _font(self, role: str = "body") -> tuple[str, int, str]:
        base = {"Nhỏ": 10, "Vừa": 11, "Lớn": 12}.get(self.font_scale.get(), 11)
        sizes = {"body": base, "small": base - 1, "section": base + 3, "title": base + 9}
        return ("Segoe UI", sizes[role], "bold" if role in ("section", "title") else "normal")

    def _save_preferences(self) -> None:
        try:
            self._preferences_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._preferences_path.with_suffix(".tmp")
            temporary.write_text(json.dumps({
                "theme": "superhero" if self.dark_mode.get() else "flatly",
                "font_scale": self.font_scale.get(),
            }), encoding="utf-8")
            temporary.replace(self._preferences_path)
        except OSError:
            pass

    def _apply_ui_style(self) -> None:
        palette = theme_palette(self.dark_mode.get())
        self._palette = palette
        base = self._font()[1]
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkCaptionFont", "TkFixedFont"):
            tkfont.nametofont(name).configure(family="Segoe UI", size=base)
        tkfont.nametofont("TkHeadingFont").configure(family="Segoe UI", size=base, weight="bold")
        rowheight = {"Nhỏ": 28, "Vừa": 31, "Lớn": 34}.get(self.font_scale.get(), 31)
        self.style.configure("Treeview", background=palette.surface, fieldbackground=palette.surface,
                             foreground=palette.foreground, bordercolor=palette.border,
                             font=("Segoe UI", base), rowheight=rowheight)
        self.style.configure("TFrame", background=palette.background)
        self.style.configure("TLabel", background=palette.background, foreground=palette.foreground)
        self.style.configure("primary.TLabel", background=palette.background, foreground=palette.accent)
        self.style.configure("secondary.TLabel", background=palette.background, foreground=palette.muted)
        self.style.configure("success.TLabel", background=palette.background, foreground="#55D6A8" if self.dark_mode.get() else "#16876F")
        self.style.configure("warning.TLabel", background=palette.background, foreground="#FFC857" if self.dark_mode.get() else "#A86400")
        self.style.configure("danger.TLabel", background=palette.background, foreground="#FF8A8A" if self.dark_mode.get() else "#B42318")
        self.style.configure("TLabelframe", background=palette.background, bordercolor=palette.border)
        self.style.configure("TLabelframe.Label", background=palette.background, foreground=palette.foreground)
        self.style.configure("primary.TLabelframe.Label", background=palette.background, foreground=palette.accent)
        self.style.configure("secondary.TLabelframe.Label", background=palette.background, foreground=palette.muted)
        self.style.map("Treeview", background=[("selected", palette.selection)], foreground=[("selected", palette.foreground)])
        self.style.configure("Treeview.Heading", background=palette.heading, foreground=palette.foreground,
                             bordercolor=palette.border, font=("Segoe UI", base, "bold"))
        self.style.map("Treeview.Heading", background=[("active", palette.selection)], foreground=[("active", palette.foreground)])
        # ttkbootstrap tries to recreate separator image elements whenever its
        # overridden configure() sees these built-in names.  Calling tkinter's
        # base implementation keeps repeated theme/font refreshes idempotent.
        for style in ("TSeparator", "Horizontal.TSeparator", "Vertical.TSeparator"):
            ttk.Style.configure(self.style, style, background=palette.border)
        self.style.configure("TNotebook", background=palette.background, bordercolor=palette.border)
        self.style.configure("TNotebook.Tab", background=palette.surface, foreground=palette.muted, padding=(10, 6))
        self.style.map("TNotebook.Tab", background=[("selected", palette.heading), ("active", palette.surface)], foreground=[("selected", palette.foreground), ("active", palette.foreground)])
        self.style.configure("Norma.Card.TLabelframe", background=palette.surface, bordercolor=palette.border)
        self.style.configure("Norma.Card.TLabelframe.Label", background=palette.surface, foreground=palette.accent)
        self.style.configure("Norma.Card.TFrame", background=palette.surface)
        self.style.configure("Norma.Card.TLabel", background=palette.surface, foreground=palette.foreground)
        self.style.configure("Norma.CardMuted.TLabel", background=palette.surface, foreground=palette.muted)
        self.style.configure("Norma.Tooltip.TLabel", background=palette.tooltip_background, foreground=palette.tooltip_foreground, bordercolor=palette.border, relief="solid")
        self.style.configure("TCombobox", padding=(6, 4))
        self.style.configure("TButton", padding=(8, 5))
        for canvas in self._theme_canvases:
            if canvas.winfo_exists():
                canvas.configure(background=palette.background)
        for text in self._theme_text_widgets:
            if text.winfo_exists():
                text.configure(background=palette.surface, foreground=palette.foreground, insertbackground=palette.foreground, highlightbackground=palette.border, highlightcolor=palette.accent)
        for menu in self._menus:
            if menu.winfo_exists():
                menu.configure(background=palette.surface, foreground=palette.foreground, activebackground=palette.selection, activeforeground=palette.foreground, selectcolor=palette.accent)
        for figure in self._figures:
            self._style_figure(figure)
            figure.canvas.draw_idle()

    def _style_figure(self, figure) -> None:
        palette = self._palette
        figure.patch.set_facecolor(palette.background)
        for axis in figure.axes:
            axis.set_facecolor(palette.background)
            axis.tick_params(colors=palette.foreground)
            axis.xaxis.label.set_color(palette.foreground)
            axis.yaxis.label.set_color(palette.foreground)
            axis.title.set_color(palette.foreground)
            for spine in axis.spines.values():
                spine.set_color(palette.border)
            axis.grid(axis="y", color=palette.border, alpha=0.55)

    def _set_appearance(self) -> None:
        from normastore.ui.tooltips import Tooltip
        Tooltip.hide_active()
        self.style.theme_use("superhero" if self.dark_mode.get() else "flatly")
        self._apply_ui_style()
        self._save_preferences()

    def _set_font_scale(self, _event=None) -> None:
        self._apply_ui_style()
        self._save_preferences()
