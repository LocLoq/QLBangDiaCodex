"""NormaStore application composition root."""

from __future__ import annotations

import tkinter as tk
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from tkinter import messagebox

import ttkbootstrap as tb
from matplotlib.figure import Figure
from PIL import ImageTk

from normastore.application.contracts import AccountView, ShiftView
from normastore.config import Settings
from normastore.ui.media import PosterMixin
from normastore.ui.pages import (
    AuditPageMixin,
    CatalogPageMixin,
    CheckoutPageMixin,
    CustomersPageMixin,
    DashboardPageMixin,
    InventoryPageMixin,
    NotificationsPageMixin,
    OrdersPageMixin,
    PromotionsPageMixin,
    ReservationsPageMixin,
    ReturnsPageMixin,
    SettingsPageMixin,
    ShiftsPageMixin,
    StatisticsPageMixin,
)
from normastore.ui.shell import ShellMixin
from normastore.ui.theme import AppearanceMixin, _load_preferences, _preferences_path
from normastore.ui.widgets import CommonWidgetsMixin


class NormaStoreApp(
    AppearanceMixin,
    ShellMixin,
    CommonWidgetsMixin,
    PosterMixin,
    DashboardPageMixin,
    CatalogPageMixin,
    CheckoutPageMixin,
    OrdersPageMixin,
    ReturnsPageMixin,
    ReservationsPageMixin,
    InventoryPageMixin,
    CustomersPageMixin,
    PromotionsPageMixin,
    ShiftsPageMixin,
    NotificationsPageMixin,
    StatisticsPageMixin,
    AuditPageMixin,
    SettingsPageMixin,
    tb.Window,
):
    """Desktop application public entry point."""

    def __init__(self, service, settings: Settings, poster_cache) -> None:
        preferences = _load_preferences(settings)
        super().__init__(themename=preferences["theme"])
        self.store, self.settings = service, settings
        self._preferences_path = _preferences_path(settings)
        self.dark_mode = tk.BooleanVar(value=preferences["theme"] == "superhero")
        self.font_scale = tk.StringVar(value=preferences["font_scale"])
        self.account: AccountView | None = None
        self.current_shift: ShiftView | None = None
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="normastore")
        self.poster_cache = poster_cache
        self._poster_images: OrderedDict[str, ImageTk.PhotoImage] = OrderedDict()
        self._poster_loading: set[str] = set()
        self._theme_canvases: list[tk.Canvas] = []
        self._theme_text_widgets: list[tk.Text] = []
        self._menus: list[tk.Menu] = []
        self._figures: list[Figure] = []
        self._apply_ui_style()
        self.title("NormaStore — Quản lý băng đĩa")
        self.geometry("1366x820")
        self.minsize(1120, 680)
        try:
            self.state("zoomed")
        except tk.TclError:
            pass
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._login()

    def _close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()

    def _run_async(
        self,
        work: Callable,
        done: Callable | None = None,
        failed: Callable[[Exception], None] | None = None,
    ) -> None:
        self._poll_future(self.executor.submit(work), done, failed)

    def _poll_future(
        self, future, done: Callable | None, failed: Callable[[Exception], None] | None
    ) -> None:
        def poll() -> None:
            if not future.done():
                self.after(80, poll)
                return
            try:
                result = future.result()
                if done:
                    done(result)
            except Exception as exc:
                if failed:
                    failed(exc)
                else:
                    messagebox.showerror("NormaStore", str(exc), parent=self)

        self.after(80, poll)
