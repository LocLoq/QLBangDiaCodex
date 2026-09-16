from __future__ import annotations

import csv
import json
import os
import tkinter as tk
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
from typing import Callable

import keyring
import ttkbootstrap as tb
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from PIL import Image, ImageTk
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X, Y

from normastore.application.services import (
    AuditQuery,
    CatalogFilters,
    CheckoutLine,
    MockSeedRequest,
    PagedResult,
    PageRequest,
    PaymentInput,
    SortSpec,
    StoreService,
    UpdateInventoryCopyRequest,
    run_mock_seed,
)
from normastore.config import Settings
from normastore.domain.enums import (
    CopyCondition,
    CopyStatus,
    LineAction,
    PaymentMethod,
    ReturnOutcome,
    RoleCode,
)
from normastore.infrastructure.database import Customer, Shift, UserAccount
from normastore.infrastructure.external import MockSmsSender, PosterCache, SmtpSender
from normastore.infrastructure.pdf_receipts import PdfReceiptExporter
from normastore.jobs import process_notification_outbox


def vnd(amount: Decimal | int | float | None) -> str:
    return f"{Decimal(amount or 0):,.0f} đ".replace(",", ".")


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


def tooltip_position(
    pointer_x: int, pointer_y: int, tooltip_width: int, tooltip_height: int,
    bounds_x: int, bounds_y: int, bounds_width: int, bounds_height: int, offset: int = 16,
) -> tuple[int, int]:
    """Place a tooltip beside the cursor without letting it leave the virtual desktop."""
    right, bottom = bounds_x + bounds_width, bounds_y + bounds_height
    x, y = pointer_x + offset, pointer_y + offset
    if x + tooltip_width > right:
        x = pointer_x - tooltip_width - offset
    if y + tooltip_height > bottom:
        y = pointer_y - tooltip_height - offset
    return (
        max(bounds_x, min(x, right - tooltip_width)),
        max(bounds_y, min(y, bottom - tooltip_height)),
    )


def catalog_tooltip_text(item) -> str:
    return (
        f"{item.release_date or '—'} • Rating {item.vote_average or '—'}\n"
        f"{item.overview or 'Chưa có tóm tắt.'}\n"
        f"Sẵn thuê: {item.rentable_copies} • Sẵn mua: {item.sellable_copies}\n"
        f"Thuê: {vnd(item.rental_price)} • Mua: {vnd(item.sale_price)}"
    )


def _preferences_path(settings: Settings) -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    return (Path(local_app_data) / "NormaStore" if local_app_data else settings.cache_dir) / "ui_preferences.json"


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


class Tooltip:
    """A single, non-focus popup for a composite widget and all of its children."""

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
        self.pointer_x = event.x_root
        self.pointer_y = event.y_root

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
        ttk.Label(
            self.tip, text=value, justify=LEFT, padding=8, wraplength=320,
            style="Norma.Tooltip.TLabel",
        ).pack()
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
        x, y = tooltip_position(
            self.pointer_x, self.pointer_y, self.tip.winfo_reqwidth(), self.tip.winfo_reqheight(),
            self.widget.winfo_vrootx(), self.widget.winfo_vrooty(),
            self.widget.winfo_vrootwidth(), self.widget.winfo_vrootheight(),
        )
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
        self.text_for_row = text_for_row
        self.hovered_row: str | None = None
        self.widget = tree
        self.text = ""
        self.tip = None
        self.after_id = None
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
            return
        if row != self.hovered_row:
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


class LegacyNormaStoreApp(tb.Window):
    def __init__(self, factory, settings: Settings) -> None:
        preferences = _load_preferences(settings)
        super().__init__(themename=preferences["theme"])
        self.factory, self.settings = factory, settings
        self._preferences_path = _preferences_path(settings)
        self.dark_mode = tk.BooleanVar(value=preferences["theme"] == "superhero")
        self.font_scale = tk.StringVar(value=preferences["font_scale"])
        self.account: UserAccount | None = None
        self.current_shift: Shift | None = None
        self.executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="normastore")
        self.poster_cache = PosterCache(settings.cache_dir / "posters")
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
        self.style.configure("Treeview", font=("Segoe UI", base), rowheight=rowheight)
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
        self.style.configure("Treeview", background=palette.surface, fieldbackground=palette.surface,
                             foreground=palette.foreground, bordercolor=palette.border, font=("Segoe UI", base), rowheight=rowheight)
        self.style.map("Treeview", background=[("selected", palette.selection)], foreground=[("selected", palette.foreground)])
        self.style.configure("Treeview.Heading", background=palette.heading, foreground=palette.foreground,
                             bordercolor=palette.border, font=("Segoe UI", base, "bold"))
        self.style.map("Treeview.Heading", background=[("active", palette.selection)], foreground=[("active", palette.foreground)])
        self.style.configure("TSeparator", background=palette.border)
        self.style.configure("Horizontal.TSeparator", background=palette.border)
        self.style.configure("Vertical.TSeparator", background=palette.border)
        self.style.configure("TNotebook", background=palette.background, bordercolor=palette.border)
        self.style.configure("TNotebook.Tab", background=palette.surface, foreground=palette.muted, padding=(10, 6))
        self.style.map("TNotebook.Tab", background=[("selected", palette.heading), ("active", palette.surface)],
                       foreground=[("selected", palette.foreground), ("active", palette.foreground)])
        self.style.configure("Norma.Card.TLabelframe", background=palette.surface, bordercolor=palette.border)
        self.style.configure("Norma.Card.TLabelframe.Label", background=palette.surface, foreground=palette.accent)
        self.style.configure("Norma.Card.TFrame", background=palette.surface)
        self.style.configure("Norma.Card.TLabel", background=palette.surface, foreground=palette.foreground)
        self.style.configure("Norma.CardMuted.TLabel", background=palette.surface, foreground=palette.muted)
        self.style.configure("Norma.Tooltip.TLabel", background=palette.tooltip_background,
                             foreground=palette.tooltip_foreground, bordercolor=palette.border, relief="solid")
        self.style.configure("TCombobox", padding=(6, 4))
        self.style.configure("TButton", padding=(8, 5))
        for canvas in self._theme_canvases:
            if canvas.winfo_exists():
                canvas.configure(background=palette.background)
        for text in self._theme_text_widgets:
            if text.winfo_exists():
                text.configure(background=palette.surface, foreground=palette.foreground,
                               insertbackground=palette.foreground, highlightbackground=palette.border,
                               highlightcolor=palette.accent)
        for menu in self._menus:
            if menu.winfo_exists():
                menu.configure(background=palette.surface, foreground=palette.foreground,
                               activebackground=palette.selection, activeforeground=palette.foreground,
                               selectcolor=palette.accent)
        for figure in self._figures:
            self._style_figure(figure)
            figure.canvas.draw_idle()

    def _style_figure(self, figure: Figure) -> None:
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
        Tooltip.hide_active()
        self.style.theme_use("superhero" if self.dark_mode.get() else "flatly")
        self._apply_ui_style()
        self._save_preferences()

    def _set_font_scale(self, _event=None) -> None:
        self._apply_ui_style()
        self._save_preferences()

    def _close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.destroy()

    def _gemini_api_key(self) -> str | None:
        return os.environ.get("NORMASTORE_GEMINI_API_KEY") or self.settings.gemini_api_key or keyring.get_password("normastore", "gemini")

    def service(self, write: bool = False):
        session = self.factory()
        return session, StoreService(
            session,
            self._gemini_api_key(),
            self.settings.gemini_embedding_model,
            self.settings.gemini_embedding_dimensions,
            self.settings.gemini_generation_model,
        ), write

    def call(self, func, write: bool = False):
        session, service, _ = self.service(write)
        try:
            value = func(service)
            if write:
                session.commit()
            return value
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def call_async(self, func, done: Callable | None = None, failed: Callable[[Exception], None] | None = None, write: bool = False) -> None:
        future = self.executor.submit(lambda: self.call(func, write))

        self._poll_future(future, done, failed)

    def _run_async(self, work: Callable, done: Callable | None = None, failed: Callable[[Exception], None] | None = None) -> None:
        self._poll_future(self.executor.submit(work), done, failed)

    def _poll_future(self, future, done: Callable | None, failed: Callable[[Exception], None] | None) -> None:
        def poll():
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

    def _debounce(self, holder: dict[str, str], callback: Callable, delay: int = 250) -> None:
        previous = holder.get("after")
        if previous:
            self.after_cancel(previous)
        holder["after"] = self.after(delay, callback)

    def _dialog(self, title: str, width: int, height: int, *, modal: bool = True):
        dialog = tb.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = min(width, int(screen_width * 0.92)), min(height, int(screen_height * 0.86))
        dialog.geometry(f"{width}x{height}")
        dialog.minsize(min(width, 560), min(height, 360))
        dialog.resizable(True, True)
        dialog.update_idletasks()
        dialog.geometry(f"+{max(0, (screen_width - width) // 2)}+{max(0, (screen_height - height) // 2)}")
        if modal:
            dialog.grab_set()
        return dialog

    def _login(self) -> None:
        login = tb.Toplevel(self)
        login.title("Đăng nhập NormaStore")
        login.resizable(False, False)
        login.transient(self)
        login.grab_set()
        frame = ttk.Frame(login, padding=28)
        frame.pack(fill=BOTH, expand=True)
        ttk.Label(frame, text="NormaStore", font=("Segoe UI", 22, "bold"), bootstyle="primary").pack(anchor="w")
        ttk.Label(frame, text="Quản lý băng đĩa truyền thống", font=("Segoe UI", 10)).pack(anchor="w", pady=(0, 18))
        user_var, pass_var = tk.StringVar(value="admin"), tk.StringVar(value="admin123")
        ttk.Label(frame, text="Tài khoản").pack(anchor="w")
        user_entry = ttk.Entry(frame, textvariable=user_var, width=34)
        user_entry.pack(fill=X, pady=(3, 10))
        ttk.Label(frame, text="Mật khẩu").pack(anchor="w")
        pass_entry = ttk.Entry(frame, textvariable=pass_var, show="•", width=34)
        pass_entry.pack(fill=X, pady=(3, 14))
        ttk.Label(frame, text="Lần đầu: admin / admin123", bootstyle="secondary").pack(anchor="w", pady=(0, 12))

        def submit(_event=None):
            account = self.call(lambda s: s.authenticate(user_var.get(), pass_var.get()), True)
            if not account:
                messagebox.showerror("Đăng nhập", "Tài khoản hoặc mật khẩu không đúng.", parent=login)
                return
            self.account = account
            login.destroy()
            self._build_shell()

        ttk.Button(frame, text="Đăng nhập", command=submit, bootstyle="primary").pack(fill=X)
        pass_entry.bind("<Return>", submit)
        login.protocol("WM_DELETE_WINDOW", self.destroy)
        user_entry.focus_set()

    def _build_shell(self) -> None:
        self._build_menu()
        outer = ttk.Frame(self)
        outer.pack(fill=BOTH, expand=True)
        self.sidebar = ttk.Frame(outer, padding=(12, 14), width=230)
        self.sidebar.pack(side=LEFT, fill=Y)
        self.sidebar.pack_propagate(False)
        ttk.Label(self.sidebar, text="ĐIỀU HƯỚNG", bootstyle="secondary", font=self._font("small")).pack(anchor="w", pady=(0, 8))
        self.pages: dict[str, ttk.Frame] = {}
        entries = [
            ("Tổng quan", self.dashboard_page), ("Lập phiếu", self.checkout_page), ("Phiếu đã lập", self.orders_page), ("Trả đĩa & phạt", self.returns_page),
            ("Đặt trước", self.reservations_page), ("Phim & tập", self.catalog_page), ("Kho đĩa", self.inventory_page),
            ("Khách hàng & Premium", self.customers_page), ("Combo / Voucher", self.promotions_page),
            ("Nhân viên & ca", self.shifts_page), ("Thông báo", self.notifications_page), ("Thống kê", self.statistics_page),
            ("Cài đặt & About", self.settings_page),
        ]
        if self._can_manage():
            entries.insert(-1, ("Nhật ký hành động", self.audit_page))
        for label, builder in entries:
            ttk.Button(self.sidebar, text=label, command=lambda n=label, b=builder: self.show_page(n, b), bootstyle="link").pack(fill=X, pady=1, anchor="w")
        ttk.Separator(self.sidebar).pack(fill=X, pady=(12, 8))
        ttk.Checkbutton(self.sidebar, text="Chế độ tối", variable=self.dark_mode, command=self._set_appearance, bootstyle="round-toggle").pack(anchor="w")
        appearance = ttk.Frame(self.sidebar)
        appearance.pack(fill=X, pady=(8, 0))
        ttk.Label(appearance, text="Cỡ chữ").pack(side=LEFT)
        font_picker = ttk.Combobox(appearance, textvariable=self.font_scale, values=("Nhỏ", "Vừa", "Lớn"), state="readonly", width=9)
        font_picker.pack(side=RIGHT)
        font_picker.bind("<<ComboboxSelected>>", self._set_font_scale)
        ttk.Separator(outer, orient="vertical").pack(side=LEFT, fill=Y)
        self.content = ttk.Frame(outer, padding=(8, 10))
        self.content.pack(side=LEFT, fill=BOTH, expand=True)
        self.status = tk.StringVar()
        ttk.Separator(self, orient="horizontal").pack(fill=X, side="bottom")
        ttk.Label(self, textvariable=self.status, padding=(12, 6), anchor="w", bootstyle="secondary").pack(fill=X, side="bottom")
        self._refresh_status()
        self._apply_ui_style()
        self._schedule_notification_worker()
        self.show_page("Tổng quan", self.dashboard_page)

    def _schedule_notification_worker(self) -> None:
        def work() -> None:
            session = self.factory()
            try:
                email_sender = None
                if self.settings.smtp_host and self.settings.smtp_username and self.settings.smtp_from:
                    password = keyring.get_password("normastore", "smtp")
                    if password:
                        smtp = SmtpSender(
                            self.settings.smtp_host,
                            self.settings.smtp_port,
                            self.settings.smtp_username,
                            password,
                            self.settings.smtp_starttls,
                        )
                        email_sender = lambda recipient, body: smtp.send(
                            self.settings.smtp_from, recipient, "Nhắc hạn trả đĩa NormaStore", body
                        )
                process_notification_outbox(
                    session,
                    send_email=email_sender,
                    send_sms=lambda phone, body: MockSmsSender().send(phone, body),
                )
                session.commit()
            except Exception:
                session.rollback()
            finally:
                session.close()

        self.executor.submit(work)
        self.after(5 * 60 * 1000, self._schedule_notification_worker)

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        file_menu = tk.Menu(menu, tearoff=False)
        file_menu.add_command(label="Đổi giao diện sáng/tối", command=self._toggle_theme)
        file_menu.add_command(label="Đổi mật khẩu", command=self._change_password)
        file_menu.add_separator()
        file_menu.add_command(label="Thoát", command=self._close)
        menu.add_cascade(label="Hệ thống", menu=file_menu)
        help_menu = tk.Menu(menu, tearoff=False)
        help_menu.add_command(label="Giới thiệu", command=lambda: self.show_page("Cài đặt & About", self.settings_page))
        menu.add_cascade(label="Trợ giúp", menu=help_menu)
        self._menus = [menu, file_menu, help_menu]
        self.config(menu=menu)

    def _toggle_theme(self) -> None:
        self.dark_mode.set(not self.dark_mode.get())
        self._set_appearance()

    def _can_manage(self) -> bool:
        return bool(self.account and self.account.role.code in (RoleCode.ADMIN, RoleCode.MANAGER))

    def _change_password(self) -> None:
        if not self.account:
            return
        current = simpledialog.askstring("Đổi mật khẩu", "Mật khẩu hiện tại:", show="•", parent=self)
        new_password = simpledialog.askstring("Đổi mật khẩu", "Mật khẩu mới (ít nhất 8 ký tự):", show="•", parent=self) if current is not None else None
        if new_password is None:
            return
        try:
            self.call(lambda s: s.change_password(self.account.id, current, new_password), True)
            messagebox.showinfo("Đổi mật khẩu", "Đã đổi mật khẩu thành công.", parent=self)
        except Exception as exc:
            messagebox.showerror("Đổi mật khẩu", str(exc), parent=self)

    def _refresh_status(self) -> None:
        if not self.account:
            return
        shift = self.call(lambda s: s.current_shift(self.account.employee_id))
        self.current_shift = shift
        ca = f"Ca #{shift.id} đang mở" if shift else "Chưa mở ca"
        self.status.set(f"{self.account.employee.full_name} • {self.account.role.name} • {ca} • MySQL: kết nối")

    def show_page(self, name: str, builder) -> None:
        Tooltip.hide_active()
        for page in self.pages.values():
            page.pack_forget()
        page = self.pages.get(name)
        if not page:
            page = ttk.Frame(self.content)
            self.pages[name] = page
            builder(page)
        page.pack(fill=BOTH, expand=True)
        refresh = getattr(page, "refresh", None)
        if refresh:
            refresh()

    def _heading(self, parent, title: str, subtitle: str = ""):
        bar = ttk.Frame(parent)
        bar.pack(fill=X, pady=(0, 10))
        ttk.Label(bar, text=title, font=self._font("title"), bootstyle="primary").pack(side=LEFT)
        if subtitle:
            ttk.Label(bar, text=subtitle, bootstyle="secondary").pack(side=LEFT, padx=12, pady=8)
        ttk.Separator(parent).pack(fill=X, pady=(0, 8))
        return bar

    def _install_sortable_headings(self, tree, titles: dict[str, str], state: dict[str, object], reload_page) -> Callable[[], None]:
        def draw() -> None:
            for column, title in titles.items():
                marker = ""
                if state["field"] == column:
                    marker = " ▼" if state["descending"] else " ▲"
                tree.heading(column, text=title + marker, command=lambda key=column: change(key))

        def change(column: str) -> None:
            if state["field"] == column:
                state["descending"] = not state["descending"]
            else:
                state["field"] = column
                state["descending"] = False
            draw()
            reload_page()

        draw()
        return draw

    def _create_pager(self, parent, page_number: tk.IntVar, refresh) -> Callable:
        bar = ttk.Frame(parent)
        bar.pack(fill=X, pady=(6, 0))
        first = ttk.Button(bar, text="« Đầu", bootstyle="secondary")
        previous = ttk.Button(bar, text="‹ Trước", bootstyle="secondary")
        label = ttk.Label(bar, text="Trang 1/1 • 0 kết quả", bootstyle="secondary")
        next_button = ttk.Button(bar, text="Sau ›", bootstyle="secondary")
        last = ttk.Button(bar, text="Cuối »", bootstyle="secondary")
        first.pack(side=LEFT, padx=(0, 3)); previous.pack(side=LEFT, padx=3)
        label.pack(side=LEFT, padx=8)
        last.pack(side=RIGHT); next_button.pack(side=RIGHT, padx=3)
        total_pages = 1

        def move(target: int) -> None:
            page_number.set(max(1, min(total_pages, target)))
            refresh()

        first.configure(command=lambda: move(1))
        previous.configure(command=lambda: move(page_number.get() - 1))
        next_button.configure(command=lambda: move(page_number.get() + 1))
        last.configure(command=lambda: move(total_pages))

        def update(result) -> None:
            nonlocal total_pages
            total_pages = result.total_pages
            page_number.set(result.page)
            label.configure(text=f"Trang {result.page}/{result.total_pages} • {result.total_items:,} kết quả".replace(",", "."))
            first.configure(state="normal" if result.page > 1 else "disabled")
            previous.configure(state="normal" if result.page > 1 else "disabled")
            next_button.configure(state="normal" if result.page < result.total_pages else "disabled")
            last.configure(state="normal" if result.page < result.total_pages else "disabled")

        return update

    def _choose_payment_method(self, title: str, parent=None) -> PaymentMethod | None:
        raw = simpledialog.askstring(
            title,
            "Phương thức: CASH, BANK_TRANSFER hoặc E_WALLET",
            initialvalue=PaymentMethod.CASH.value,
            parent=parent or self,
        )
        if raw is None:
            return None
        try:
            return PaymentMethod(raw.strip().upper())
        except ValueError:
            messagebox.showerror(title, "Phương thức thanh toán không hợp lệ.", parent=parent or self)
            return None

    def _load_poster_thumbnail(self, poster_path: str | None, label: ttk.Label) -> None:
        if not poster_path:
            return
        target = self.poster_cache.path_for(poster_path)
        cache_key = str(target)

        def apply_thumbnail(path) -> None:
            if not label.winfo_exists() or not path:
                return
            try:
                with Image.open(path) as image:
                    image.thumbnail((82, 116))
                    thumbnail = ImageTk.PhotoImage(image.copy())
            except Exception:
                return
            self._poster_images[cache_key] = thumbnail
            label.configure(image=thumbnail, text="")

        if cache_key in self._poster_images:
            label.configure(image=self._poster_images[cache_key], text="")
            return
        if target.exists():
            apply_thumbnail(target)
            return
        if poster_path in self._poster_loading:
            return
        self._poster_loading.add(poster_path)

        def fetch():
            try:
                return self.poster_cache.fetch(poster_path)
            except Exception:
                return None

        future = self.executor.submit(fetch)

        def poll() -> None:
            if not future.done():
                self.after(80, poll)
                return
            self._poster_loading.discard(poster_path)
            apply_thumbnail(future.result())

        self.after(80, poll)

    def dashboard_page(self, page) -> None:
        self._heading(page, "Tổng quan", "Tình hình cửa hàng hôm nay")
        cards = ttk.Frame(page)
        cards.pack(fill=X)
        fields = [("available", "Có sẵn", "success"), ("rented", "Đang thuê", "primary"), ("overdue", "Quá hạn", "danger"), ("reservations", "Đặt trước", "warning")]
        labels = {}
        for key, title, style in fields:
            card = ttk.Labelframe(cards, text=title, padding=15, bootstyle=style)
            card.pack(side=LEFT, fill=X, expand=True, padx=4)
            labels[key] = ttk.Label(card, text="—", font=("Segoe UI", 20, "bold"))
            labels[key].pack()
        revenue = ttk.Label(page, text="", font=("Segoe UI", 13, "bold"), bootstyle="primary")
        revenue.pack(anchor="w", padx=5, pady=16)
        quick = ttk.Labelframe(page, text="Thao tác nhanh", padding=12)
        quick.pack(fill=X, padx=4)
        ttk.Button(quick, text="Mở ca", command=self._open_shift, bootstyle="success").pack(side=LEFT, padx=4)
        ttk.Button(quick, text="Lập phiếu", command=lambda: self.show_page("Lập phiếu", self.checkout_page), bootstyle="primary").pack(side=LEFT, padx=4)
        ttk.Button(quick, text="Nhập phim/tập", command=lambda: self.show_page("Phim & tập", self.catalog_page)).pack(side=LEFT, padx=4)
        recommendation_box = ttk.Labelframe(page, text="Đề cử hôm nay", padding=10)
        recommendation_box.pack(fill=BOTH, expand=True, padx=4, pady=(14, 0))
        recommendation_tree = ttk.Treeview(recommendation_box, columns=("reason",), show="tree headings", height=7)
        recommendation_tree.heading("#0", text="Phim / tập"); recommendation_tree.heading("reason", text="Lý do")
        recommendation_tree.pack(fill=BOTH, expand=True)
        def refresh():
            stats = self.call(lambda s: s.dashboard())
            for key in labels:
                labels[key].configure(text=str(stats[key]))
            revenue.configure(text=f"Dòng tiền thuần (gồm cọc): {vnd(stats['cash_flow'])}")
            recommendation_tree.delete(*recommendation_tree.get_children())
            for recommendation in self.call(lambda s: s.today_recommendations(), True):
                recommendation_tree.insert("", END, iid=str(recommendation.item_id), text=recommendation.title, values=(recommendation.reason,))
            self._refresh_status()
        page.refresh = refresh

    def catalog_page(self, page) -> None:
        bar = self._heading(page, "Phim & tập", "Double-click để sửa • Hover xem thông tin")
        query, type_filter = tk.StringVar(), tk.StringVar()
        only_rent, only_sell = tk.BooleanVar(), tk.BooleanVar()
        view_mode = tk.StringVar(value="Danh sách")
        page_number = tk.IntVar(value=1)
        ttk.Button(bar, text="Tìm theo mô tả", command=lambda: search_description()).pack(side=RIGHT, padx=4)
        ttk.Combobox(bar, textvariable=view_mode, values=("Danh sách", "Thẻ"), width=12, state="readonly").pack(side=RIGHT, padx=4)
        filters = ttk.Labelframe(page, text="Tìm kiếm và bộ lọc", padding=(10, 7))
        filters.pack(fill=X, pady=(0, 8))
        basic = ttk.Frame(filters); basic.pack(fill=X)
        ttk.Label(basic, text="Từ khóa:").pack(side=LEFT)
        ttk.Entry(basic, textvariable=query, width=30).pack(side=LEFT, padx=(4, 10))
        ttk.Label(basic, text="Loại:").pack(side=LEFT)
        ttk.Combobox(basic, textvariable=type_filter, values=("", "MOVIE", "EPISODE"), width=11, state="readonly").pack(side=LEFT, padx=4)
        ttk.Checkbutton(basic, text="Còn thuê", variable=only_rent).pack(side=LEFT, padx=6)
        ttk.Checkbutton(basic, text="Còn mua", variable=only_sell).pack(side=LEFT, padx=6)
        advanced_visible = tk.BooleanVar(value=False)
        advanced = ttk.Frame(filters)
        genre_filter, year_from, year_to, rating_min = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()
        media_filter, condition_filter, status_filter = tk.StringVar(), tk.StringVar(), tk.StringVar()
        rental_min, rental_max, sale_min, sale_max = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()
        show_filter, season_filter = tk.StringVar(), tk.StringVar()
        genres = {"Tất cả thể loại": None}
        genres.update({genre.name: genre.id for genre in self.call(lambda s: s.list_genres())})
        shows = {"Tất cả bộ": None}
        shows.update({show.title: show.show_id for show in self.call(lambda s: s.list_shows())})

        def toggle_advanced():
            if advanced_visible.get():
                advanced.pack_forget(); advanced_visible.set(False); advanced_button.configure(text="Bộ lọc nâng cao ▾")
            else:
                advanced.pack(fill=X, pady=(7, 0)); advanced_visible.set(True); advanced_button.configure(text="Thu gọn ▴")

        advanced_button = ttk.Button(basic, text="Bộ lọc nâng cao ▾", command=toggle_advanced, bootstyle="secondary")
        advanced_button.pack(side=RIGHT)
        ttk.Button(basic, text="Xóa bộ lọc", command=lambda: clear_filters(), bootstyle="secondary").pack(side=RIGHT, padx=5)
        for label, variable, values, width in (
            ("Thể loại", genre_filter, tuple(genres), 16), ("Từ năm", year_from, (), 7), ("Đến năm", year_to, (), 7),
            ("Rating ≥", rating_min, (), 7), ("Định dạng", media_filter, ("", "VHS", "VCD", "DVD", "Blu-ray"), 10),
            ("Tình trạng", condition_filter, ("", *[value.value for value in CopyCondition]), 11),
            ("Kho", status_filter, ("", *[value.value for value in CopyStatus]), 11), ("Bộ", show_filter, tuple(shows), 18), ("Mùa", season_filter, (), 6),
            ("Thuê từ", rental_min, (), 10), ("đến", rental_max, (), 10), ("Mua từ", sale_min, (), 10), ("đến", sale_max, (), 10),
        ):
            ttk.Label(advanced, text=label).pack(side=LEFT, padx=(0, 3))
            widget = ttk.Combobox(advanced, textvariable=variable, values=values, width=width, state="readonly") if values else ttk.Entry(advanced, textvariable=variable, width=width)
            widget.pack(side=LEFT, padx=(0, 6))
        pane = ttk.Panedwindow(page, orient="horizontal")
        pane.pack(fill=BOTH, expand=True)
        left, right = ttk.Frame(pane, padding=5), ttk.Frame(pane, padding=12)
        pane.add(left, weight=3); pane.add(right, weight=2)
        tree = ttk.Treeview(left, columns=("type", "rating", "rent", "sale", "rentable_copies", "sellable_copies"), show="tree headings", selectmode="extended")
        tree.column("#0", width=235); tree.column("type", width=75); tree.column("rating", width=65); tree.column("rent", width=90); tree.column("sale", width=90); tree.column("rentable_copies", width=78); tree.column("sellable_copies", width=78)
        tree.pack(fill=BOTH, expand=True)
        card_area = ttk.Frame(left)
        card_canvas = tk.Canvas(card_area, highlightthickness=0)
        self._theme_canvases.append(card_canvas)
        card_canvas.configure(background=self.style.lookup("TFrame", "background"))
        card_scroll = ttk.Scrollbar(card_area, orient="vertical", command=card_canvas.yview)
        card_canvas.configure(yscrollcommand=card_scroll.set)
        card_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        card_scroll.pack(side=RIGHT, fill=Y)
        card_container = ttk.Frame(card_canvas, padding=4)
        card_window = card_canvas.create_window((0, 0), window=card_container, anchor="nw")
        card_container.bind("<Configure>", lambda _event: card_canvas.configure(scrollregion=card_canvas.bbox("all")))
        card_canvas.bind("<Configure>", lambda event: card_canvas.itemconfigure(card_window, width=event.width))
        actions = ttk.Frame(left); actions.pack(fill=X, pady=5)
        management_state = "normal" if self._can_manage() else "disabled"
        ttk.Button(actions, text="Thêm phim", command=lambda: edit(), state=management_state).pack(side=LEFT, padx=3)
        ttk.Button(actions, text="Thêm bộ", command=lambda: add_show(), state=management_state).pack(side=LEFT, padx=3)
        ttk.Button(actions, text="Xem bộ phim", command=lambda: show_details()).pack(side=LEFT, padx=3)
        ttk.Button(actions, text="Thêm tập hàng loạt", command=lambda: bulk_episodes(), state=management_state).pack(side=LEFT, padx=3)
        ttk.Button(actions, text="Thêm đĩa", command=lambda: add_copy(), state=management_state).pack(side=LEFT, padx=3)
        ttk.Button(actions, text="Sửa giá chọn", command=lambda: bulk_prices(), state=management_state).pack(side=LEFT, padx=3)
        ttk.Button(actions, text="Lưu trữ chọn", command=lambda: archive(), state=management_state).pack(side=LEFT, padx=3)
        pager_update = self._create_pager(left, page_number, lambda: refresh())
        detail = tk.StringVar(value="Chọn một phim/tập để xem thông tin.")
        ttk.Label(right, text="Chi tiết", font=("Segoe UI", 14, "bold"), bootstyle="primary").pack(anchor="w")
        ttk.Label(right, textvariable=detail, justify=LEFT, wraplength=350).pack(anchor="nw", fill=X, pady=10)
        episode_box = ttk.Labelframe(right, text="Phim bộ", padding=8)
        episode_box.pack(fill=X, pady=6)
        ttk.Label(episode_box, text="Episode được quản lý như item riêng. Dùng import TMDB hoặc thêm item EPISODE để thêm hàng loạt.", wraplength=330).pack(anchor="w")
        rows = {}
        sort_state: dict[str, object] = {"field": "#0", "descending": False}
        def search_description():
            description = simpledialog.askstring("Tìm phim theo mô tả", "Ví dụ: phim gia đình vui nhộn, hoạt hình, thập niên 1990:", parent=self)
            if not description:
                return
            dialog = self._dialog("Kết quả tìm theo mô tả", 800, 500, modal=False)
            ttk.Label(dialog, text="Đang tìm bằng Gemini…", bootstyle="secondary").pack(anchor="w", padx=12, pady=10)
            def show_results(response):
                for child in dialog.winfo_children():
                    child.destroy()
                if response.warning:
                    ttk.Label(dialog, text=response.warning, bootstyle="warning", wraplength=720).pack(anchor="w", padx=12, pady=(10, 4))
                result_tree = ttk.Treeview(dialog, columns=("overview", "source", "score"), show="tree headings")
                result_tree.heading("#0", text="Phim / tập"); result_tree.heading("overview", text="Tóm tắt"); result_tree.heading("source", text="Nguồn"); result_tree.heading("score", text="Điểm")
                result_tree.column("overview", width=480); result_tree.pack(fill=BOTH, expand=True, padx=12, pady=8)
                result_page = tk.IntVar(value=1)
                def load_results():
                    result_tree.delete(*result_tree.get_children())
                    size = 50; total_pages = max(1, (len(response.items) + size - 1) // size)
                    result_page.set(min(result_page.get(), total_pages)); start = (result_page.get() - 1) * size
                    for result in response.items[start:start + size]:
                        score = f"{result.score:.3f}" if result.score is not None else "—"
                        result_tree.insert("", END, iid=str(result.item_id), text=result.title, values=(result.overview[:180], result.source, score))
                    result_pager(PagedResult(tuple(), result_page.get(), size, len(response.items), total_pages))
                result_pager = self._create_pager(dialog, result_page, load_results)
                load_results()
                if not response.items:
                    ttk.Label(dialog, text="Không có kết quả phù hợp trong kho nội bộ.").pack(pady=8)
            self.call_async(lambda s: s.search_by_description_response(description), show_results)
        def decimal_value(value: str) -> Decimal | None:
            try:
                return Decimal(value.replace(".", "").replace(",", ".")) if value.strip() else None
            except Exception:
                return None

        def integer_value(value: str) -> int | None:
            try:
                return int(value) if value.strip() else None
            except ValueError:
                return None

        def catalog_filters() -> CatalogFilters:
            return CatalogFilters(
                text=query.get(), item_type=type_filter.get(), genre_id=genres.get(genre_filter.get()),
                year_from=integer_value(year_from.get()), year_to=integer_value(year_to.get()), rating_min=decimal_value(rating_min.get()),
                media_format=media_filter.get(), condition=CopyCondition(condition_filter.get()) if condition_filter.get() else None,
                copy_status=CopyStatus(status_filter.get()) if status_filter.get() else None,
                rental_price_min=decimal_value(rental_min.get()), rental_price_max=decimal_value(rental_max.get()),
                sale_price_min=decimal_value(sale_min.get()), sale_price_max=decimal_value(sale_max.get()),
                show_id=shows.get(show_filter.get()), season_number=integer_value(season_filter.get()),
                require_rentable=only_rent.get(), require_sellable=only_sell.get(),
            )

        def refresh():
            Tooltip.hide_active()
            tree.delete(*tree.get_children()); rows.clear()
            for child in card_container.winfo_children():
                child.destroy()
            sort_field = {"#0": "title", "rent": "rental_price", "sale": "sale_price"}.get(str(sort_state["field"]), str(sort_state["field"]))
            sort = SortSpec(sort_field, bool(sort_state["descending"]))
            result = self.call(lambda s: s.query_catalog(catalog_filters(), PageRequest(page_number.get(), 48), sort))
            pager_update(result)
            for index, item in enumerate(result.items):
                rows[str(item.item_id)] = item
                tree.insert("", END, iid=str(item.item_id), text=item.title, values=(item.item_type.value, item.vote_average or "—", vnd(item.rental_price), vnd(item.sale_price), item.rentable_copies, item.sellable_copies))
                if view_mode.get() == "Thẻ":
                    card = ttk.Labelframe(card_container, text=item.title, padding=7, style="Norma.Card.TLabelframe")
                    card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=4, pady=4)
                    poster = ttk.Label(card, text="Đang tải\nposter", width=10, anchor="center", justify="center", style="Norma.CardMuted.TLabel")
                    poster.pack(side=LEFT, padx=(0, 8))
                    self._load_poster_thumbnail(item.poster_path, poster)
                    content = ttk.Frame(card, style="Norma.Card.TFrame")
                    content.pack(side=LEFT, fill=BOTH, expand=True)
                    ttk.Label(content, text=f"{item.item_type} • Rating {item.vote_average or '—'}", style="Norma.CardMuted.TLabel").pack(anchor="w")
                    ttk.Label(content, text=f"Thuê {vnd(item.rental_price)} • Mua {vnd(item.sale_price)}", wraplength=150, style="Norma.Card.TLabel").pack(anchor="w", pady=(4, 0))
                    ttk.Label(content, text=f"Sẵn thuê: {item.rentable_copies} • Sẵn mua: {item.sellable_copies}", style="Norma.Card.TLabel").pack(anchor="w", pady=(2, 0))

                    def choose(item_id=item.item_id):
                        tree.selection_set(str(item_id))
                        tree.focus(str(item_id))
                        show_detail()

                    card.bind("<Button-1>", lambda _event, action=choose: action())
                    poster.bind("<Button-1>", lambda _event, action=choose: action())
                    content.bind("<Button-1>", lambda _event, action=choose: action())
                    if self._can_manage():
                        ttk.Button(card, text="Sửa", command=lambda item_id=item.item_id: (tree.selection_set(str(item_id)), tree.focus(str(item_id)), edit()), bootstyle="secondary").pack(side=RIGHT, anchor="s")
                    Tooltip(card, lambda current=item: catalog_tooltip_text(current))
            for column in range(3):
                card_container.columnconfigure(column, weight=1)
            if view_mode.get() == "Thẻ":
                tree.pack_forget()
                card_area.pack(fill=BOTH, expand=True)
            else:
                card_area.pack_forget()
                tree.pack(fill=BOTH, expand=True)
        def selected():
            ids = tree.selection()
            row = rows.get(ids[0]) if ids else None
            return self.call(lambda s: s.catalog_item(row.item_id)) if row else None
        def show_detail(_event=None):
            item = selected()
            if item:
                genres, reviews = self.call(lambda s: s.catalog_metadata(item.id))
                genres_text = ", ".join(genres) or "Chưa có"
                reviews_text = "\n".join(
                    f"• {review.author} ({review.rating or '—'}): {review.content[:180]}"
                    for review in reviews
                ) or "Chưa có review TMDB."
                detail.set(
                    f"{item.title}\n\n{item.overview or 'Chưa có tóm tắt.'}\n\n"
                    f"Thể loại: {genres_text}\nRating: {item.vote_average or '—'}\n"
                    f"Thuê: {vnd(item.rental_price)} • Mua: {vnd(item.sale_price)}\n"
                    f"Cọc: {vnd(item.deposit_amount)}\n\nReview TMDB:\n{reviews_text}"
                )
        def edit(_event=None):
            item = selected()
            dialog = tb.Toplevel(self); dialog.title("Sửa phim/tập" if item else "Thêm phim/tập"); dialog.transient(self); dialog.grab_set()
            form = ttk.Frame(dialog, padding=18); form.pack(fill=BOTH, expand=True)
            values = {
                "title": tk.StringVar(value=item.title if item else ""), "item_type": tk.StringVar(value=str(item.item_type) if item else "MOVIE"),
                "overview": tk.StringVar(value=item.overview or "" if item else ""), "rental_price": tk.StringVar(value=str(item.rental_price) if item else "25000"),
                "sale_price": tk.StringVar(value=str(item.sale_price) if item else "200000"), "deposit_amount": tk.StringVar(value=str(item.deposit_amount) if item else "120000"),
            }
            for label, key in [("Tên", "title"), ("Loại", "item_type"), ("Tóm tắt", "overview"), ("Giá thuê", "rental_price"), ("Giá bán", "sale_price"), ("Tiền cọc", "deposit_amount")]:
                ttk.Label(form, text=label).pack(anchor="w")
                widget = ttk.Combobox(form, textvariable=values[key], values=["MOVIE", "EPISODE"], state="readonly") if key == "item_type" else ttk.Entry(form, textvariable=values[key], width=52)
                widget.pack(fill=X, pady=(0, 7))
            def save():
                try:
                    data = {"id": item.id} if item else {}
                    data.update(title=values["title"].get(), item_type=values["item_type"].get(), overview=values["overview"].get(), rental_price=Decimal(values["rental_price"].get()), sale_price=Decimal(values["sale_price"].get()), deposit_amount=Decimal(values["deposit_amount"].get()), replacement_value=Decimal(values["sale_price"].get()))
                    self.call(lambda s: s.save_catalog_item(self.account.employee_id, **data), True); dialog.destroy(); refresh()
                except Exception as exc: messagebox.showerror("Lỗi", str(exc), parent=dialog)
            ttk.Button(form, text="Lưu", command=save, bootstyle="primary").pack(fill=X, pady=(8, 0))
        def add_copy():
            item = selected()
            if not item: return messagebox.showinfo("Kho", "Hãy chọn phim/tập trước.", parent=self)
            dialog = self._dialog("Thêm đĩa", 460, 300)
            form = ttk.Frame(dialog, padding=14); form.pack(fill=BOTH, expand=True)
            barcode, media = tk.StringVar(), tk.StringVar(value="DVD")
            can_rent, can_sell = tk.BooleanVar(value=item.can_rent), tk.BooleanVar(value=item.can_sell)
            ttk.Label(form, text="Barcode").pack(anchor="w")
            ttk.Entry(form, textvariable=barcode).pack(fill=X, pady=(2, 8))
            ttk.Label(form, text="Định dạng").pack(anchor="w")
            ttk.Combobox(form, textvariable=media, values=("VHS", "VCD", "DVD", "Blu-ray"), state="readonly").pack(fill=X, pady=(2, 8))
            ttk.Checkbutton(form, text="Cho thuê", variable=can_rent).pack(anchor="w")
            ttk.Checkbutton(form, text="Cho bán", variable=can_sell).pack(anchor="w")
            footer = ttk.Frame(dialog, padding=(14, 0, 14, 14)); footer.pack(fill=X)
            def save():
                try:
                    self.call(lambda s: s.add_copy(item.id, barcode.get(), media.get(), self.account.employee_id, can_rent.get(), can_sell.get()), True)
                    dialog.destroy(); refresh()
                except Exception as exc:
                    messagebox.showerror("Thêm đĩa", str(exc), parent=dialog)
            ttk.Button(footer, text="Lưu", command=save, bootstyle="primary").pack(side=RIGHT)
            ttk.Button(footer, text="Hủy", command=dialog.destroy, bootstyle="secondary").pack(side=RIGHT, padx=6)
        def add_show():
            title = simpledialog.askstring("Thêm bộ phim", "Tên bộ phim:", parent=self)
            if not title:
                return
            overview = simpledialog.askstring("Thêm bộ phim", "Tóm tắt (không bắt buộc):", parent=self) or ""
            try:
                self.call(lambda s: s.create_show(title, overview, self.account.employee_id), True)
                messagebox.showinfo("Phim bộ", "Đã tạo bộ phim. Bây giờ có thể thêm tập hàng loạt.", parent=self)
            except Exception as exc:
                messagebox.showerror("Phim bộ", str(exc), parent=self)
        def show_details():
            shows = self.call(lambda s: s.list_shows())
            if not shows:
                return messagebox.showinfo("Bộ phim", "Chưa có bộ phim nào.", parent=self)
            dialog = tb.Toplevel(self)
            dialog.title("Chi tiết bộ phim")
            dialog.geometry("1000x620")
            dialog.transient(self)
            pane = ttk.PanedWindow(dialog, orient="horizontal")
            pane.pack(fill=BOTH, expand=True, padx=12, pady=12)
            show_frame, detail_frame = ttk.Frame(pane, padding=4), ttk.Frame(pane, padding=4)
            pane.add(show_frame, weight=1)
            pane.add(detail_frame, weight=3)
            show_tree = ttk.Treeview(show_frame, columns=("rating", "seasons"), show="tree headings")
            show_tree.heading("#0", text="Bộ phim")
            show_tree.heading("rating", text="Rating")
            show_tree.heading("seasons", text="Mùa")
            show_tree.column("#0", width=250)
            show_tree.pack(fill=BOTH, expand=True)
            by_id = {str(show.show_id): show for show in shows}
            for show in shows:
                show_tree.insert("", END, iid=str(show.show_id), text=show.title, values=(show.vote_average or "—", show.season_count))
            detail = tk.StringVar(value="Chọn một bộ phim để xem thông tin và các tập.")
            ttk.Label(detail_frame, textvariable=detail, justify=LEFT, wraplength=610).pack(anchor="w", fill=X, pady=(0, 8))
            season_var = tk.StringVar(value="Tất cả mùa")
            season_combo = ttk.Combobox(detail_frame, textvariable=season_var, state="readonly", width=18)
            season_combo.pack(anchor="w", pady=(0, 8))
            episodes = ttk.Treeview(detail_frame, columns=("season", "episode", "rating", "available"), show="tree headings")
            episodes.heading("#0", text="Tập phim")
            episodes.heading("season", text="Mùa")
            episodes.heading("episode", text="Tập")
            episodes.heading("rating", text="Rating")
            episodes.heading("available", text="Sẵn thuê")
            episodes.column("#0", width=390)
            episodes.pack(fill=BOTH, expand=True)
            current_show_id: int | None = None

            def refresh_episodes(*_args):
                if current_show_id is None:
                    return
                selected_season = season_var.get()
                season_number = int(selected_season.removeprefix("Mùa ")) if selected_season.startswith("Mùa ") else None
                rows = self.call(lambda s: s.list_show_episodes(current_show_id, season_number))
                episodes.delete(*episodes.get_children())
                for episode in rows:
                    episodes.insert("", END, iid=str(episode.item_id), text=episode.title, values=(episode.season_number, episode.episode_number, episode.vote_average or "—", episode.rentable_copies))

            def select_show(_event=None):
                nonlocal current_show_id
                selection = show_tree.selection()
                if not selection:
                    return
                current_show_id = int(selection[0])
                show = by_id[selection[0]]
                all_episodes = self.call(lambda s: s.list_show_episodes(current_show_id))
                seasons = [f"Mùa {number}" for number in sorted({entry.season_number for entry in all_episodes})]
                season_combo["values"] = ["Tất cả mùa", *seasons]
                season_var.set("Tất cả mùa")
                detail.set(f"{show.title}\n\n{show.overview or 'Chưa có tóm tắt.'}\n\nRating TMDB: {show.vote_average or '—'} • {show.season_count} mùa • {len(all_episodes)} tập")
                refresh_episodes()

            show_tree.bind("<<TreeviewSelect>>", select_show)
            season_var.trace_add("write", refresh_episodes)
            show_tree.selection_set(str(shows[0].show_id))
            select_show()
        def bulk_episodes():
            shows = {f"{show.show_id} — {show.title}": show for show in self.call(lambda s: s.list_shows())}
            if not shows:
                return messagebox.showinfo("Tập phim", "Hãy thêm bộ phim trước.", parent=self)
            dialog = tb.Toplevel(self); dialog.title("Thêm tập phim hàng loạt"); dialog.transient(self); dialog.grab_set()
            form = ttk.Frame(dialog, padding=16); form.pack(fill=BOTH, expand=True)
            show_var = tk.StringVar(value=next(iter(shows)))
            season_var, first_var, last_var, title_var = tk.StringVar(value="1"), tk.StringVar(value="1"), tk.StringVar(value="10"), tk.StringVar(value="Tập {number}")
            for label, variable in [("Bộ phim", show_var), ("Mùa", season_var), ("Tập đầu", first_var), ("Tập cuối", last_var), ("Mẫu tên", title_var)]:
                ttk.Label(form, text=label).pack(anchor="w")
                widget = ttk.Combobox(form, textvariable=variable, values=list(shows), state="readonly", width=52) if variable is show_var else ttk.Entry(form, textvariable=variable, width=54)
                widget.pack(fill=X, pady=(0, 7))
            def save_bulk():
                try:
                    show = shows[show_var.get()]
                    count = self.call(lambda s: s.add_episodes_bulk(show.show_id, int(season_var.get()), int(first_var.get()), int(last_var.get()), title_var.get(), self.account.employee_id), True)
                    dialog.destroy(); refresh()
                    messagebox.showinfo("Tập phim", f"Đã thêm {len(count)} tập phim.", parent=self)
                except Exception as exc:
                    messagebox.showerror("Tập phim", str(exc), parent=dialog)
            ttk.Button(form, text="Thêm tập", command=save_bulk, bootstyle="primary").pack(fill=X, pady=(8, 0))
        def archive():
            ids = [int(i) for i in tree.selection()]
            if ids and messagebox.askyesno("Lưu trữ", f"Lưu trữ {len(ids)} item đã chọn?"):
                self.call(lambda s: s.archive_items(ids, self.account.employee_id), True); refresh()
        def bulk_prices():
            ids = [int(item_id) for item_id in tree.selection()]
            if not ids:
                return messagebox.showinfo("Sửa hàng loạt", "Hãy chọn các item cần cập nhật.", parent=self)
            rental = simpledialog.askstring("Sửa hàng loạt", "Giá thuê mới (để trống để giữ nguyên):", parent=self)
            sale = simpledialog.askstring("Sửa hàng loạt", "Giá bán mới (để trống để giữ nguyên):", parent=self)
            deposit = simpledialog.askstring("Sửa hàng loạt", "Tiền cọc mới (để trống để giữ nguyên):", parent=self)
            try:
                count = self.call(lambda s: s.bulk_update_catalog_prices(ids, self.account.employee_id, Decimal(rental) if rental else None, Decimal(sale) if sale else None, Decimal(deposit) if deposit else None), True)
                messagebox.showinfo("Sửa hàng loạt", f"Đã cập nhật {count} item.", parent=self)
                refresh()
            except Exception as exc:
                messagebox.showerror("Sửa hàng loạt", str(exc), parent=self)
        def clear_filters():
            for variable in (query, type_filter, genre_filter, year_from, year_to, rating_min, media_filter, condition_filter, status_filter, rental_min, rental_max, sale_min, sale_max, show_filter, season_filter):
                variable.set("")
            only_rent.set(False); only_sell.set(False)
            page_number.set(1); refresh()

        self._install_sortable_headings(
            tree,
            {"#0": "Tên phim / tập", "type": "Loại", "rating": "Rating", "rent": "Thuê", "sale": "Mua", "rentable_copies": "Sẵn thuê", "sellable_copies": "Sẵn mua"},
            sort_state,
            lambda: (page_number.set(1), refresh()),
        )
        tree.bind("<<TreeviewSelect>>", show_detail); tree.bind("<Double-1>", edit)
        TreeviewTooltip(tree, lambda item_id: catalog_tooltip_text(rows[item_id]) if item_id in rows else "")
        def reset_page(*_args):
            page_number.set(1); self.after(250, refresh)
        for variable in (query, type_filter, only_rent, only_sell, genre_filter, year_from, year_to, rating_min, media_filter, condition_filter, status_filter, rental_min, rental_max, sale_min, sale_max, show_filter, season_filter, view_mode):
            variable.trace_add("write", reset_page)
        page.refresh = refresh

    def checkout_page(self, page) -> None:
        self._heading(page, "Lập phiếu thuê / mua", "Chọn phim rồi thêm vào giỏ")
        top = ttk.Frame(page); top.pack(fill=X, pady=(0, 8))
        customer_var = tk.StringVar(); customer_search_var = tk.StringVar()
        customer_combo = ttk.Combobox(top, textvariable=customer_var, state="readonly", width=38)
        ttk.Label(top, text="Khách hàng:").pack(side=LEFT)
        ttk.Entry(top, textvariable=customer_search_var, width=18).pack(side=LEFT, padx=(6, 0))
        customer_combo.pack(side=LEFT, padx=6)
        ttk.Button(top, text="Thêm khách", command=lambda: self._quick_customer(customer_combo)).pack(side=LEFT)
        ttk.Label(top, text="Hạn trả:").pack(side=LEFT, padx=(18, 3))
        due_var = tk.StringVar(value=(date.today() + timedelta(days=3)).isoformat())
        ttk.Entry(top, textvariable=due_var, width=12).pack(side=LEFT)
        ttk.Label(top, text="Voucher:").pack(side=LEFT, padx=(18, 3))
        voucher_var = tk.StringVar()
        voucher_combo = ttk.Combobox(top, textvariable=voucher_var, width=14)
        voucher_combo.pack(side=LEFT)
        ttk.Label(top, text="Combo:").pack(side=LEFT, padx=(18, 3))
        combo_var = tk.StringVar()
        combo_combo = ttk.Combobox(top, textvariable=combo_var, state="readonly", width=24)
        combo_combo.pack(side=LEFT)
        pane = ttk.Panedwindow(page, orient="horizontal"); pane.pack(fill=BOTH, expand=True)
        catalog_frame, cart_frame = ttk.Frame(pane, padding=5), ttk.Frame(pane, padding=5)
        pane.add(catalog_frame, weight=3); pane.add(cart_frame, weight=2)
        search, picker_type = tk.StringVar(), tk.StringVar()
        picker_rent, picker_sell = tk.BooleanVar(), tk.BooleanVar()
        picker_view, picker_page = tk.StringVar(value="Danh sách"), tk.IntVar(value=1)
        picker_filters = ttk.Labelframe(catalog_frame, text="Tìm phim / tập", padding=(8, 5))
        picker_filters.pack(fill=X, pady=(0, 5))
        ttk.Label(picker_filters, text="Từ khóa:").pack(side=LEFT)
        ttk.Entry(picker_filters, textvariable=search, width=25).pack(side=LEFT, padx=4, fill=X, expand=True)
        ttk.Label(picker_filters, text="Loại:").pack(side=LEFT)
        ttk.Combobox(picker_filters, textvariable=picker_type, values=("", "MOVIE", "EPISODE"), width=11, state="readonly").pack(side=LEFT, padx=4)
        ttk.Checkbutton(picker_filters, text="Còn thuê", variable=picker_rent).pack(side=LEFT, padx=4)
        ttk.Checkbutton(picker_filters, text="Còn mua", variable=picker_sell).pack(side=LEFT, padx=4)
        ttk.Combobox(picker_filters, textvariable=picker_view, values=("Danh sách", "Thẻ"), width=12, state="readonly").pack(side=RIGHT)
        picker_advanced_open = tk.BooleanVar(value=False)
        picker_advanced = ttk.Frame(catalog_frame)
        picker_genre, picker_year_from, picker_year_to, picker_rating = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()
        picker_format, picker_condition, picker_rental_min, picker_rental_max = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()
        picker_sale_min, picker_sale_max, picker_show, picker_season = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()
        picker_genres = {"Tất cả thể loại": None}
        picker_genres.update({genre.name: genre.id for genre in self.call(lambda s: s.list_genres())})
        picker_shows = {"Tất cả bộ": None}
        picker_shows.update({show.title: show.show_id for show in self.call(lambda s: s.list_shows())})
        def toggle_picker_advanced():
            if picker_advanced_open.get():
                picker_advanced.pack_forget(); picker_advanced_open.set(False); picker_advanced_button.configure(text="Lọc nâng cao ▾")
            else:
                picker_advanced.pack(fill=X, pady=(0, 5)); picker_advanced_open.set(True); picker_advanced_button.configure(text="Thu gọn ▴")
        picker_advanced_button = ttk.Button(picker_filters, text="Lọc nâng cao ▾", command=toggle_picker_advanced, bootstyle="secondary")
        picker_advanced_button.pack(side=RIGHT, padx=5)
        for label, variable, values, width in (
            ("Thể loại", picker_genre, tuple(picker_genres), 14), ("Từ năm", picker_year_from, (), 6), ("Đến", picker_year_to, (), 6),
            ("Rating ≥", picker_rating, (), 6), ("Định dạng", picker_format, ("", "VHS", "VCD", "DVD", "Blu-ray"), 9),
            ("Tình trạng", picker_condition, ("", *[value.value for value in CopyCondition]), 10), ("Bộ", picker_show, tuple(picker_shows), 16),
            ("Mùa", picker_season, (), 5), ("Thuê từ", picker_rental_min, (), 8), ("đến", picker_rental_max, (), 8),
            ("Mua từ", picker_sale_min, (), 8), ("đến", picker_sale_max, (), 8),
        ):
            ttk.Label(picker_advanced, text=label).pack(side=LEFT, padx=(0, 2))
            control = ttk.Combobox(picker_advanced, textvariable=variable, values=values, width=width, state="readonly") if values else ttk.Entry(picker_advanced, textvariable=variable, width=width)
            control.pack(side=LEFT, padx=(0, 4))
        catalog = ttk.Treeview(catalog_frame, columns=("rentable_copies", "sellable_copies", "rent", "buy"), show="tree headings")
        catalog.column("#0", width=260); catalog.column("rentable_copies", width=78); catalog.column("sellable_copies", width=78); catalog.column("rent", width=88); catalog.column("buy", width=88)
        catalog.pack(fill=BOTH, expand=True)
        picker_cards = ttk.Frame(catalog_frame)
        picker_canvas = tk.Canvas(picker_cards, highlightthickness=0)
        self._theme_canvases.append(picker_canvas)
        picker_canvas.configure(background=self.style.lookup("TFrame", "background"))
        picker_scroll = ttk.Scrollbar(picker_cards, orient="vertical", command=picker_canvas.yview)
        picker_canvas.configure(yscrollcommand=picker_scroll.set)
        picker_canvas.pack(side=LEFT, fill=BOTH, expand=True); picker_scroll.pack(side=RIGHT, fill=Y)
        picker_container = ttk.Frame(picker_canvas, padding=4)
        picker_window = picker_canvas.create_window((0, 0), window=picker_container, anchor="nw")
        picker_container.bind("<Configure>", lambda _event: picker_canvas.configure(scrollregion=picker_canvas.bbox("all")))
        picker_canvas.bind("<Configure>", lambda event: picker_canvas.itemconfigure(picker_window, width=event.width))
        ttk.Label(cart_frame, text="Giỏ phiếu", font=("Segoe UI", 14, "bold"), bootstyle="primary").pack(anchor="w")
        cart = ttk.Treeview(cart_frame, columns=("action", "price", "due"), show="tree headings")
        cart.heading("#0", text="Bản đĩa"); cart.heading("action", text="Loại"); cart.heading("price", text="Giá"); cart.heading("due", text="Hạn trả")
        cart.column("#0", width=180); cart.column("action", width=65); cart.column("price", width=90); cart.column("due", width=90)
        cart.pack(fill=BOTH, expand=True)
        total_var = tk.StringVar(value="Tổng cần thu: 0 đ")
        ttk.Label(cart_frame, textvariable=total_var, font=("Segoe UI", 11, "bold"), bootstyle="success").pack(anchor="e", pady=6)
        buttons = ttk.Frame(cart_frame); buttons.pack(fill=X)
        cart_lines: list[CheckoutLine] = []
        catalog_rows = {}
        customers: dict[str, Customer] = {}
        combos = {}
        def refresh_customers(*_args):
            selected = customer_var.get()
            customers.clear()
            values = []
            for customer in self.call(lambda s: s.list_customers(customer_search_var.get())):
                key = f"{customer.id} — {customer.full_name} ({customer.phone})"; customers[key] = customer; values.append(key)
            customer_combo["values"] = values
            if selected not in customers:
                customer_var.set(values[0] if not selected and values else "")
            combos.clear()
            combo_values = ["Không dùng combo"]
            for combo in self.call(lambda s: s.list_combos()):
                key = f"{combo.combo_id} — {combo.name} ({vnd(combo.discount_amount)})"
                combos[key] = combo
                combo_values.append(key)
            combo_combo["values"] = combo_values
            if not combo_var.get(): combo_var.set(combo_values[0])
            voucher_combo["values"] = ["", *[
                voucher.code for voucher in self.call(lambda s: s.list_vouchers())
                if voucher.effective_state == "Đang hiệu lực"
            ]]
        def combo_ids():
            combo = combos.get(combo_var.get())
            return [combo.combo_id] if combo else None
        picker_sort: dict[str, object] = {"field": "#0", "descending": False}
        def picker_number(value: str) -> Decimal | None:
            try:
                return Decimal(value.replace(".", "").replace(",", ".")) if value.strip() else None
            except Exception:
                return None
        def picker_year(value: str) -> int | None:
            try:
                return int(value) if value.strip() else None
            except ValueError:
                return None
        def picker_catalog_filters() -> CatalogFilters:
            return CatalogFilters(
                text=search.get(), item_type=picker_type.get(), genre_id=picker_genres.get(picker_genre.get()),
                year_from=picker_year(picker_year_from.get()), year_to=picker_year(picker_year_to.get()), rating_min=picker_number(picker_rating.get()),
                media_format=picker_format.get(), condition=CopyCondition(picker_condition.get()) if picker_condition.get() else None,
                copy_status=CopyStatus.AVAILABLE, rental_price_min=picker_number(picker_rental_min.get()), rental_price_max=picker_number(picker_rental_max.get()),
                sale_price_min=picker_number(picker_sale_min.get()), sale_price_max=picker_number(picker_sale_max.get()),
                show_id=picker_shows.get(picker_show.get()), season_number=picker_year(picker_season.get()),
                require_rentable=picker_rent.get(), require_sellable=picker_sell.get(),
            )
        def refresh_catalog():
            Tooltip.hide_active()
            catalog.delete(*catalog.get_children()); catalog_rows.clear()
            for child in picker_container.winfo_children(): child.destroy()
            field = {"#0": "title", "rent": "rental_price", "buy": "sale_price"}.get(str(picker_sort["field"]), str(picker_sort["field"]))
            result = self.call(lambda s: s.query_catalog(
                picker_catalog_filters(),
                PageRequest(picker_page.get(), 48), SortSpec(field, bool(picker_sort["descending"])),
            ))
            picker_pager(result)
            for index, item in enumerate(result.items):
                catalog_rows[str(item.item_id)] = item
                catalog.insert("", END, iid=str(item.item_id), text=item.title, values=(item.rentable_copies, item.sellable_copies, vnd(item.rental_price), vnd(item.sale_price)))
                if picker_view.get() == "Thẻ":
                    card = ttk.Labelframe(picker_container, text=item.title, padding=7, style="Norma.Card.TLabelframe")
                    card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=4, pady=4)
                    poster = ttk.Label(card, text="Đang tải\nposter", width=10, anchor="center", justify="center", style="Norma.CardMuted.TLabel")
                    poster.pack(side=LEFT, padx=(0, 7)); self._load_poster_thumbnail(item.poster_path, poster)
                    body = ttk.Frame(card, style="Norma.Card.TFrame"); body.pack(side=LEFT, fill=BOTH, expand=True)
                    ttk.Label(body, text=f"{item.item_type.value} • Rating {item.vote_average or '—'}", style="Norma.CardMuted.TLabel").pack(anchor="w")
                    ttk.Label(body, text=f"Thuê {vnd(item.rental_price)} • Mua {vnd(item.sale_price)}", style="Norma.Card.TLabel").pack(anchor="w")
                    ttk.Label(body, text=f"Sẵn thuê: {item.rentable_copies} • Sẵn mua: {item.sellable_copies}", style="Norma.Card.TLabel").pack(anchor="w")
                    ttk.Button(body, text="+ Thuê", command=lambda ident=item.item_id: add_for_item(ident, LineAction.RENT), state="normal" if item.rentable_copies else "disabled", bootstyle="primary").pack(side=LEFT, pady=(5, 0))
                    ttk.Button(body, text="+ Mua", command=lambda ident=item.item_id: add_for_item(ident, LineAction.BUY), state="normal" if item.sellable_copies else "disabled", bootstyle="success").pack(side=LEFT, padx=4, pady=(5, 0))
                    Tooltip(card, lambda current=item: catalog_tooltip_text(current))
            for column in range(2): picker_container.columnconfigure(column, weight=1)
            if picker_view.get() == "Thẻ":
                catalog.pack_forget(); picker_cards.pack(fill=BOTH, expand=True)
            else:
                picker_cards.pack_forget(); catalog.pack(fill=BOTH, expand=True)
            update_action_buttons()
        def selected_item_id() -> int | None:
            ids = catalog.selection()
            return int(ids[0]) if ids else None
        def add_for_item(item_id: int | None, action: LineAction):
            if not item_id:
                return messagebox.showinfo("Phiếu", "Hãy chọn một item còn bản đĩa trống.", parent=self)
            try: due = date.fromisoformat(due_var.get()) if action == LineAction.RENT else None
            except ValueError: return messagebox.showerror("Phiếu", "Ngày hẹn trả phải theo dạng YYYY-MM-DD.", parent=self)
            try:
                used = {line.copy_id for line in cart_lines}
                choice = self.call(lambda s: s.choose_checkout_copy(item_id, action, used))
                if not choice:
                    return messagebox.showinfo("Phiếu", "Không còn bản đĩa phù hợp cho thao tác này.", parent=self)
                cart_lines.append(CheckoutLine(choice.copy_id, action, due))
                cart.insert("", END, iid=str(choice.copy_id), text=f"{choice.barcode} — {choice.title}", values=("Thuê" if action == LineAction.RENT else "Mua", vnd(choice.unit_price), due or "—"))
                update_quote(); refresh_catalog()
            except Exception as exc:
                messagebox.showerror("Phiếu", str(exc), parent=self)
        def add(action: LineAction):
            add_for_item(selected_item_id(), action)
        def update_quote():
            customer = customers.get(customer_var.get())
            if not customer or not cart_lines: total_var.set("Tổng cần thu: 0 đ"); return
            try:
                quote = self.call(lambda s: s.quote(customer.id, cart_lines, voucher_var.get() or None, combo_ids()))
                total_var.set(f"Tổng cần thu: {vnd(quote.total_due)} (cọc {vnd(quote.deposit)})")
            except Exception as exc: total_var.set(f"Kiểm tra: {exc}")
        def remove():
            ids = cart.selection()
            if ids:
                selected_ids = {int(value) for value in ids}
                cart_lines[:] = [line for line in cart_lines if line.copy_id not in selected_ids]
                for value in ids: cart.delete(value)
                update_quote(); refresh_catalog()
        def checkout():
            customer = customers.get(customer_var.get())
            if not customer: return messagebox.showerror("Phiếu", "Hãy chọn khách hàng.", parent=self)
            if not self.current_shift: return messagebox.showerror("Phiếu", "Cần mở ca trước khi lập phiếu.", parent=self)
            try:
                quote = self.call(lambda s: s.quote(customer.id, cart_lines, voucher_var.get() or None, combo_ids()))
                received = simpledialog.askstring("Thanh toán", f"Số tiền nhận (mặc định {quote.total_due:,.0f}):", initialvalue=str(quote.total_due), parent=self)
                if received is None: return
                method = self._choose_payment_method("Thanh toán", self)
                if method is None: return
                order = self.call(lambda s: s.checkout(customer.id, self.account.employee_id, self.current_shift.id, cart_lines, [PaymentInput(method, Decimal(received))], voucher_var.get() or None, combo_ids()), True)
                messagebox.showinfo("Hoàn tất", f"Đã tạo phiếu {order.code}.", parent=self)
                cart_lines.clear(); cart.delete(*cart.get_children()); refresh_catalog(); update_quote(); self._refresh_status()
            except Exception as exc: messagebox.showerror("Phiếu", str(exc), parent=self)
        rent_button = ttk.Button(buttons, text="+ Thuê", command=lambda: add(LineAction.RENT), bootstyle="primary")
        buy_button = ttk.Button(buttons, text="+ Mua", command=lambda: add(LineAction.BUY), bootstyle="success")
        remove_button = ttk.Button(buttons, text="Bỏ dòng", command=remove, bootstyle="secondary")
        rent_button.pack(side=LEFT, padx=2); buy_button.pack(side=LEFT, padx=2); remove_button.pack(side=LEFT, padx=2)
        ttk.Button(buttons, text="Hoàn tất", command=checkout, bootstyle="warning").pack(side=RIGHT, padx=2)
        picker_pager = self._create_pager(catalog_frame, picker_page, refresh_catalog)
        def update_action_buttons(_event=None):
            item = catalog_rows.get(catalog.selection()[0]) if catalog.selection() else None
            rent_button.configure(state="normal" if item and item.rentable_copies else "disabled")
            buy_button.configure(state="normal" if item and item.sellable_copies else "disabled")
            remove_button.configure(state="normal" if cart.selection() else "disabled")
        self._install_sortable_headings(
            catalog,
            {"#0": "Phim / tập", "rentable_copies": "Sẵn thuê", "sellable_copies": "Sẵn mua", "rent": "Thuê", "buy": "Mua"},
            picker_sort,
            lambda: (picker_page.set(1), refresh_catalog()),
        )
        catalog.bind("<Double-1>", lambda _e: add(LineAction.RENT))
        catalog.bind("<<TreeviewSelect>>", update_action_buttons)
        cart.bind("<<TreeviewSelect>>", update_action_buttons)
        TreeviewTooltip(catalog, lambda item_id: catalog_tooltip_text(catalog_rows[item_id]) if item_id in catalog_rows else "")
        def reset_picker(*_args):
            picker_page.set(1); self.after(250, refresh_catalog)
        for variable in (search, picker_type, picker_rent, picker_sell, picker_view, picker_genre, picker_year_from, picker_year_to, picker_rating, picker_format, picker_condition, picker_rental_min, picker_rental_max, picker_sale_min, picker_sale_max, picker_show, picker_season): variable.trace_add("write", reset_picker)
        customer_search_var.trace_add("write", lambda *_: self.after(250, refresh_customers))
        customer_var.trace_add("write", lambda *_: update_quote())
        voucher_var.trace_add("write", lambda *_: update_quote())
        combo_var.trace_add("write", lambda *_: update_quote())
        def refresh(): refresh_customers(); refresh_catalog(); update_quote()
        page.refresh = refresh

    def _quick_customer(self, combo) -> None:
        name = simpledialog.askstring("Khách hàng", "Tên khách:", parent=self)
        phone = simpledialog.askstring("Khách hàng", "Số điện thoại:", parent=self) if name else None
        if name and phone:
            try:
                self.call(lambda s: s.add_customer(name, phone), True)
                refresh = getattr(self.pages.get("Lập phiếu"), "refresh", None)
                if refresh: refresh()
            except Exception as exc: messagebox.showerror("Khách hàng", str(exc), parent=self)

    def orders_page(self, page) -> None:
        bar = self._heading(page, "Phiếu đã lập", "Double-click để xem chi tiết phim/tập trong phiếu")
        search = tk.StringVar()
        ttk.Entry(bar, textvariable=search, width=35).pack(side=RIGHT)
        tree = ttk.Treeview(page, columns=("customer", "employee", "created", "status", "total"), show="tree headings")
        tree.heading("#0", text="Mã phiếu"); tree.heading("customer", text="Khách hàng"); tree.heading("employee", text="Nhân viên"); tree.heading("created", text="Lập lúc"); tree.heading("status", text="Trạng thái"); tree.heading("total", text="Cần thu")
        tree.column("total", anchor="e", width=115)
        tree.pack(fill=BOTH, expand=True)
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "created", "descending": True}
        rows = {}
        pdf_layout = tk.StringVar(value="A4")

        def export_pdf(order_id: int, code: str, parent=None) -> None:
            layout = pdf_layout.get()
            suffix = "A4" if layout == "A4" else "80mm"
            path = filedialog.asksaveasfilename(
                parent=parent or self,
                title="Xuất phiếu PDF",
                defaultextension=".pdf",
                filetypes=[("PDF", "*.pdf")],
                initialfile=f"NormaStore_{code}_{suffix}.pdf",
            )
            if not path:
                return
            export_button.configure(state="disabled", text="Đang xuất PDF…")

            def work():
                receipt = self.call(lambda s: s.order_receipt(order_id))
                PdfReceiptExporter().export(receipt, Path(path), layout)
                self.call(lambda s: s.record_order_pdf_export(order_id, self.account.employee_id, layout, Path(path).name), True)
                return Path(path)

            def done(saved_path: Path):
                export_button.configure(state="normal", text="Xuất PDF")
                messagebox.showinfo("Xuất PDF", f"Đã tạo phiếu PDF:\n{saved_path}", parent=parent or self)

            def failed(exc):
                export_button.configure(state="normal", text="Xuất PDF")
                messagebox.showerror("Xuất PDF", str(exc), parent=parent or self)

            self._run_async(work, done, failed)

        ttk.Combobox(bar, textvariable=pdf_layout, values=("A4", "80mm"), width=8, state="readonly").pack(side=RIGHT, padx=(6, 0))
        export_button = ttk.Button(bar, text="Xuất PDF", bootstyle="secondary", state="disabled")
        export_button.pack(side=RIGHT)

        def export_selected():
            selected = tree.selection()
            if len(selected) != 1:
                return messagebox.showinfo("Xuất PDF", "Hãy chọn đúng một phiếu.", parent=self)
            order = rows[selected[0]]
            export_pdf(order.order_id, order.code)

        export_button.configure(command=export_selected)
        def refresh():
            tree.delete(*tree.get_children()); rows.clear(); export_button.configure(state="disabled")
            result = self.call(lambda s: s.query_orders(search.get(), PageRequest(page_number.get(), 50), SortSpec(str(sort_state["field"]), bool(sort_state["descending"]))))
            pager_update(result)
            for order in result.items:
                rows[str(order.order_id)] = order
                tree.insert("", END, iid=str(order.order_id), text=order.code, values=(order.customer_name, order.employee_name, order.created_at.strftime("%d/%m/%Y %H:%M"), order.status, vnd(order.total_due)))
        def detail(_event=None):
            selected = tree.selection()
            if len(selected) != 1:
                return
            try:
                order, lines = self.call(lambda s: s.order_detail(int(selected[0])))
            except Exception as exc:
                return messagebox.showerror("Phiếu", str(exc), parent=self)
            dialog = tb.Toplevel(self); dialog.title(f"Phiếu {order.code}"); dialog.geometry("760x410"); dialog.transient(self)
            frame = ttk.Frame(dialog, padding=12); frame.pack(fill=BOTH, expand=True)
            ttk.Label(frame, text=f"{order.customer_name} • {order.created_at:%d/%m/%Y %H:%M} • Tổng cần thu: {vnd(order.total_due)}", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(0, 8))
            lines_tree = ttk.Treeview(frame, columns=("barcode", "action", "price", "deposit", "due", "state"), show="tree headings")
            for key, title in [("barcode", "Barcode"), ("action", "Loại"), ("price", "Giá"), ("deposit", "Cọc"), ("due", "Hạn trả"), ("state", "Tình trạng thuê")]: lines_tree.heading(key, text=title)
            lines_tree.pack(fill=BOTH, expand=True)
            for line in lines:
                lines_tree.insert("", END, text=line.title, values=(line.barcode or "—", "Thuê" if line.action == LineAction.RENT else "Mua", vnd(line.unit_price), vnd(line.deposit), line.due_date or "—", line.rental_state or "—"))
            ttk.Button(frame, text="Xuất PDF", command=lambda: export_pdf(order.order_id, order.code, dialog), bootstyle="secondary").pack(anchor="e", pady=(8, 0))
        tree.bind("<Double-1>", detail)
        tree.bind("<<TreeviewSelect>>", lambda _event: export_button.configure(state="normal" if len(tree.selection()) == 1 else "disabled"), add="+")
        pager_update = self._create_pager(page, page_number, refresh)
        self._install_sortable_headings(tree, {"#0": "Mã phiếu", "customer": "Khách hàng", "employee": "Nhân viên", "created": "Lập lúc", "status": "Trạng thái", "total": "Cần thu"}, sort_state, lambda: (page_number.set(1), refresh()))
        search.trace_add("write", lambda *_: (page_number.set(1), self.after(250, refresh)))
        page.refresh = refresh

    def returns_page(self, page) -> None:
        self._heading(page, "Trả đĩa & phạt", "Chọn dòng thuê để trả từng phần")
        tree = ttk.Treeview(page, columns=("customer", "due", "status"), show="tree headings", selectmode="extended")
        tree.heading("#0", text="Phim / bản đĩa"); tree.heading("customer", text="Khách"); tree.heading("due", text="Hạn trả"); tree.heading("status", text="Trạng thái")
        tree.pack(fill=BOTH, expand=True)
        outcome = tk.StringVar(value="NORMAL")
        footer = ttk.Frame(page); footer.pack(fill=X, pady=7)
        ttk.Combobox(footer, textvariable=outcome, values=[x.value for x in ReturnOutcome], width=18, state="readonly").pack(side=LEFT)
        note = ttk.Entry(footer, width=45); note.pack(side=LEFT, padx=6)
        rows = {}
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "due", "descending": False}
        def refresh():
            tree.delete(*tree.get_children()); rows.clear()
            result = self.call(lambda s: s.query_active_rentals(PageRequest(page_number.get(), 50), SortSpec(str(sort_state["field"]), bool(sort_state["descending"]))))
            pager_update(result)
            for rental in result.items:
                rows[str(rental.term_id)] = rental
                status = "Quá hạn" if rental.due_date < date.today() else "Đang thuê"
                tree.insert("", END, iid=str(rental.term_id), text=f"{rental.title} — {rental.barcode}", values=(rental.customer_name, rental.due_date, status))
        def submit():
            selection = tree.selection()
            if not selection: return
            selected = [rows[item] for item in selection]
            customer_ids = {rental.customer_id for rental in selected}
            if len(customer_ids) != 1:
                return messagebox.showerror("Trả đĩa", "Mỗi phiếu trả chỉ áp dụng cho một khách hàng.", parent=self)
            try:
                paid = simpledialog.askstring("Trả đĩa", "Thu thêm sau cấn cọc (nhập 0 nếu khách còn nợ):", initialvalue="0", parent=self)
                if paid is None:
                    return
                method = self._choose_payment_method("Trả đĩa", self) if Decimal(paid) else PaymentMethod.CASH
                if method is None:
                    return
                balance = self.call(
                    lambda s: s.return_rentals(
                        self.account.employee_id,
                        selected[0].customer_id,
                        [(rental.term_id, ReturnOutcome(outcome.get()), note.get()) for rental in selected],
                        PaymentInput(method, Decimal(paid)),
                    ),
                    True,
                )
                messagebox.showinfo("Trả đĩa", f"Số dư sau khi cấn cọc: {vnd(balance)}", parent=self); refresh()
            except Exception as exc: messagebox.showerror("Trả đĩa", str(exc), parent=self)
        def selected_one():
            selection = tree.selection()
            if len(selection) != 1:
                messagebox.showinfo("Trả đĩa", "Hãy chọn đúng một dòng thuê.", parent=self)
                return None
            return rows[selection[0]]
        def extend():
            rental = selected_one()
            if not rental:
                return
            try:
                self.call(lambda s: s.extend_rental(rental.term_id, self.account.employee_id), True)
                messagebox.showinfo("Gia hạn", "Đã gia hạn thêm 3 ngày và ghi nhận phí thuê.", parent=self)
                refresh()
            except Exception as exc:
                messagebox.showerror("Gia hạn", str(exc), parent=self)
        def convert_to_sale():
            rental = selected_one()
            if not rental:
                return
            amount = simpledialog.askstring("Chuyển thành mua", "Số tiền khách thanh toán thêm:", initialvalue="0", parent=self)
            if amount is None:
                return
            method = self._choose_payment_method("Chuyển thành mua", self)
            if method is None:
                return
            try:
                order = self.call(
                    lambda s: s.rental_to_sale(
                        rental.term_id,
                        self.account.employee_id,
                        PaymentInput(method, Decimal(amount)),
                    ),
                    True,
                )
                messagebox.showinfo("Chuyển thành mua", f"Đã tạo phiếu bán {order.code} và cấn cọc.", parent=self)
                refresh()
            except Exception as exc:
                messagebox.showerror("Chuyển thành mua", str(exc), parent=self)
        def open_sale_returns():
            dialog = tb.Toplevel(self)
            dialog.title("Trả hàng bán trong 7 ngày")
            dialog.geometry("760x360")
            dialog.transient(self)
            frame = ttk.Frame(dialog, padding=12); frame.pack(fill=BOTH, expand=True)
            sale_tree = ttk.Treeview(frame, columns=("customer", "title", "barcode", "sold", "expires"), show="headings")
            for key, title in [("customer", "Khách hàng"), ("title", "Phim/tập"), ("barcode", "Barcode"), ("sold", "Ngày bán"), ("expires", "Hạn trả")]:
                sale_tree.heading(key, text=title)
            sale_tree.pack(fill=BOTH, expand=True)
            sales = {}
            def load_sales():
                sale_tree.delete(*sale_tree.get_children()); sales.clear()
                for sale in self.call(lambda s: s.returnable_sales()):
                    sales[str(sale.line_id)] = sale
                    sale_tree.insert("", END, iid=str(sale.line_id), values=(sale.customer_name, sale.title, sale.barcode, sale.sold_on, sale.expires_on))
            def return_selected_sale():
                selection = sale_tree.selection()
                if len(selection) != 1:
                    return messagebox.showinfo("Trả hàng bán", "Hãy chọn một dòng bán.", parent=dialog)
                damaged = messagebox.askyesno("Trả hàng bán", "Đĩa hoàn có hư hỏng không?", parent=dialog)
                condition = CopyCondition.DAMAGED if damaged else CopyCondition.GOOD
                deduction = Decimal("0")
                note = ""
                if damaged:
                    if not self._can_manage():
                        return messagebox.showerror("Trả hàng bán", "Chỉ Quản lý mới được quyết định hàng hoàn hỏng.", parent=dialog)
                    entered = simpledialog.askstring("Khấu trừ", "Số tiền khấu trừ (VND):", initialvalue="0", parent=dialog)
                    if entered is None:
                        return
                    try:
                        deduction = Decimal(entered.replace(".", "").replace(",", "").strip())
                    except Exception:
                        return messagebox.showerror("Trả hàng bán", "Mức khấu trừ không hợp lệ.", parent=dialog)
                    note = simpledialog.askstring("Ghi chú", "Lý do hư hỏng/khấu trừ:", parent=dialog) or ""
                try:
                    refund = self.call(
                        lambda s: s.return_sale(
                            int(selection[0]), self.account.employee_id, condition=condition,
                            deduction=deduction, note=note,
                        ),
                        True,
                    )
                    messagebox.showinfo("Trả hàng bán", f"Đã hoàn {vnd(refund)}. Đĩa chuyển sang chờ kiểm tra.", parent=dialog)
                    load_sales()
                except Exception as exc:
                    messagebox.showerror("Trả hàng bán", str(exc), parent=dialog)
            actions = ttk.Frame(frame); actions.pack(fill=X, pady=(8, 0))
            ttk.Button(actions, text="Xác nhận hoàn", command=return_selected_sale, bootstyle="warning").pack(side=RIGHT)
            load_sales()
        ttk.Button(footer, text="Gia hạn 3 ngày", command=extend, bootstyle="secondary").pack(side=LEFT, padx=(8, 0))
        ttk.Button(footer, text="Chuyển thành mua", command=convert_to_sale, bootstyle="warning").pack(side=LEFT, padx=6)
        ttk.Button(footer, text="Trả hàng bán", command=open_sale_returns, bootstyle="secondary").pack(side=LEFT)
        ttk.Button(footer, text="Xác nhận trả", command=submit, bootstyle="success").pack(side=RIGHT)
        pager_update = self._create_pager(page, page_number, refresh)
        self._install_sortable_headings(tree, {"#0": "Phim / bản đĩa", "customer": "Khách", "due": "Hạn trả", "status": "Trạng thái"}, sort_state, lambda: (page_number.set(1), refresh()))
        page.refresh = refresh

    def reservations_page(self, page) -> None:
        self._heading(page, "Đặt trước", "FIFO theo Movie / Episode • Giữ 24 giờ khi có hàng")
        tree = ttk.Treeview(page, columns=("customer", "item", "state", "hold"), show="headings")
        for column, title in [("customer", "Khách"), ("item", "Item"), ("state", "Trạng thái"), ("hold", "Giữ đến")]: tree.heading(column, text=title)
        tree.pack(fill=BOTH, expand=True)
        bottom = ttk.Frame(page); bottom.pack(fill=X, pady=6)
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "created", "descending": True}
        def create():
            dialog = self._dialog("Tạo đặt trước", 1020, 680)
            frame = ttk.Frame(dialog, padding=12); frame.pack(fill=BOTH, expand=True)
            customers = {}
            customer_var = tk.StringVar()
            customer_search_var = tk.StringVar()
            customer_combo = ttk.Combobox(frame, textvariable=customer_var, state="readonly", width=55)
            ttk.Label(frame, text="Tìm khách hàng (tên hoặc số điện thoại):").pack(anchor="w")
            ttk.Entry(frame, textvariable=customer_search_var).pack(fill=X, pady=(0, 4))
            ttk.Label(frame, text="Chọn khách hàng:").pack(anchor="w"); customer_combo.pack(fill=X, pady=(0, 8))
            search_var = tk.StringVar()
            ttk.Entry(frame, textvariable=search_var).pack(fill=X, pady=(0, 6))
            view_mode = tk.StringVar(value="Danh sách")
            ttk.Combobox(frame, textvariable=view_mode, values=("Danh sách", "Thẻ"), state="readonly", width=14).pack(anchor="e", pady=(0, 5))
            picker = ttk.Treeview(frame, columns=("type", "stock"), show="tree headings", selectmode="extended")
            picker.heading("#0", text="Phim / tập"); picker.heading("type", text="Loại"); picker.heading("stock", text="Có sẵn")
            picker.pack(fill=BOTH, expand=True)
            card_area = ttk.Frame(frame)
            selected_item_ids: set[int] = set()
            item_page = tk.IntVar(value=1)
            item_sort: dict[str, object] = {"field": "#0", "descending": False}
            def load_customers():
                previous = customer_var.get()
                values = []
                customers.clear()
                for customer in self.call(lambda s: s.list_customers(customer_search_var.get())):
                    key = f"{customer.id} — {customer.full_name} ({customer.phone})"; customers[key] = customer; values.append(key)
                customer_combo["values"] = values
                customer_var.set(previous if previous in customers else (values[0] if values else ""))
            def load_items():
                picker.delete(*picker.get_children())
                for child in card_area.winfo_children():
                    child.destroy()
                field = {"#0": "title", "stock": "rentable_copies"}.get(str(item_sort["field"]), str(item_sort["field"]))
                result = self.call(lambda s: s.query_catalog(CatalogFilters(text=search_var.get(), item_rentable=True), PageRequest(item_page.get(), 48), SortSpec(field, bool(item_sort["descending"]))))
                item_pager(result)
                for index, item in enumerate(result.items):
                    picker.insert("", END, iid=str(item.item_id), text=item.title, values=(item.item_type.value, item.rentable_copies))
                    if view_mode.get() == "Thẻ":
                        card = ttk.Labelframe(card_area, text=item.title, padding=8)
                        card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=4, pady=4)
                        selected = tk.BooleanVar(value=item.item_id in selected_item_ids)
                        def toggle(item_id=item.item_id, variable=selected):
                            if variable.get(): selected_item_ids.add(item_id)
                            else: selected_item_ids.discard(item_id)
                        ttk.Checkbutton(card, text="Chọn đặt trước", variable=selected, command=toggle).pack(anchor="w")
                        ttk.Label(card, text=f"{item.item_type.value} • Rating {item.vote_average or '—'}", bootstyle="secondary").pack(anchor="w")
                        ttk.Label(card, text=f"Thuê {vnd(item.rental_price)} • Sẵn thuê: {item.rentable_copies}", wraplength=210).pack(anchor="w", pady=(4, 0))
                        ttk.Label(card, text=(item.overview or "Chưa có tóm tắt.")[:130], wraplength=220).pack(anchor="w", pady=(4, 0))
                for column in range(3): card_area.columnconfigure(column, weight=1)
                if view_mode.get() == "Thẻ":
                    picker.pack_forget(); card_area.pack(fill=BOTH, expand=True)
                else:
                    card_area.pack_forget(); picker.pack(fill=BOTH, expand=True)
            def save():
                customer = customers.get(customer_var.get())
                ids = list(selected_item_ids | {int(item_id) for item_id in picker.selection()})
                if not customer or not ids:
                    return messagebox.showinfo("Đặt trước", "Hãy chọn khách hàng và ít nhất một phim/tập.", parent=dialog)
                try:
                    self.call(lambda s: s.reserve(customer.id, ids, self.account.employee_id), True); dialog.destroy(); refresh()
                except Exception as exc: messagebox.showerror("Đặt trước", str(exc), parent=self)
            ttk.Button(frame, text="Xác nhận đặt trước", command=save, bootstyle="primary").pack(anchor="e", pady=(8, 0))
            item_pager = self._create_pager(frame, item_page, load_items)
            self._install_sortable_headings(picker, {"#0": "Phim / tập", "type": "Loại", "stock": "Có sẵn"}, item_sort, lambda: (item_page.set(1), load_items()))
            debounce_state: dict[str, str] = {}
            customer_search_var.trace_add("write", lambda *_: self._debounce(debounce_state, load_customers))
            search_var.trace_add("write", lambda *_: self._debounce(debounce_state, lambda: (item_page.set(1), load_items())))
            view_mode.trace_add("write", lambda *_: load_items())
            load_customers(); load_items()
        def refresh():
            self.call(lambda s: s.expire_reservation_holds(), True)
            tree.delete(*tree.get_children())
            result = self.call(lambda s: s.query_reservations(
                PageRequest(page_number.get(), 50), SortSpec(str(sort_state["field"]), bool(sort_state["descending"])),
            ))
            pager(result)
            for reservation in result.items:
                tree.insert("", END, values=(reservation.customer_name, reservation.item_title, reservation.state, reservation.hold_until or "—"))
        ttk.Button(bottom, text="Tạo đặt trước", command=create, bootstyle="primary").pack(side=LEFT)
        ttk.Label(bottom, text="Chọn trực tiếp khách hàng và Movie/Episode trong cửa sổ đặt trước.", bootstyle="secondary").pack(side=LEFT, padx=10)
        pager = self._create_pager(page, page_number, refresh)
        self._install_sortable_headings(tree, {"customer": "Khách", "item": "Item", "state": "Trạng thái", "hold": "Giữ đến"}, sort_state, lambda: (page_number.set(1), refresh()))
        page.refresh = refresh

    def inventory_page(self, page) -> None:
        self._heading(page, "Kho đĩa", "Quản lý barcode, tình trạng và trạng thái vật lý")
        filters = ttk.Frame(page); filters.pack(fill=X, pady=(0, 6))
        status_filter = tk.StringVar(value="TẤT CẢ")
        ttk.Label(filters, text="Trạng thái:").pack(side=LEFT)
        ttk.Combobox(
            filters,
            textvariable=status_filter,
            values=("TẤT CẢ", *[status.value for status in CopyStatus]),
            state="readonly",
            width=18,
        ).pack(side=LEFT, padx=6)
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "title", "descending": False}
        tree = ttk.Treeview(page, columns=("barcode", "title", "format", "condition", "status", "rent", "sell"), show="headings")
        titles = [("barcode", "Barcode"), ("title", "Phim/tập"), ("format", "Định dạng"), ("condition", "Tình trạng"), ("status", "Kho"), ("rent", "Thuê"), ("sell", "Bán")]
        for key, title in titles:
            tree.heading(key, text=title)
        tree.pack(fill=BOTH, expand=True)
        def refresh():
            tree.delete(*tree.get_children())
            selected_status = None if status_filter.get() == "TẤT CẢ" else CopyStatus(status_filter.get())
            result = self.call(lambda s: s.query_inventory(
                selected_status,
                PageRequest(page_number.get(), 50),
                SortSpec(str(sort_state["field"]), bool(sort_state["descending"])),
            ))
            pager_update(result)
            for copy in result.items:
                tree.insert("", END, iid=str(copy.copy_id), values=(
                    copy.barcode, copy.title, copy.media_format, copy.condition.value,
                    copy.status.value, "Có" if copy.can_rent else "Không", "Có" if copy.can_sell else "Không",
                ))
        def edit_copy(_event=None):
            selected = tree.selection()
            if len(selected) != 1:
                return messagebox.showinfo("Kho đĩa", "Hãy chọn một bản đĩa.", parent=self)
            if not self._can_manage():
                return messagebox.showerror("Kho đĩa", "Chỉ Quản lý/Quản trị viên được sửa kho.", parent=self)
            values = tree.item(selected[0], "values")
            dialog = self._dialog("Sửa bản đĩa", 660, 540)
            body = ttk.Frame(dialog, padding=14); body.pack(fill=BOTH, expand=True)
            barcode = tk.StringVar(value=values[0]); media = tk.StringVar(value=values[2])
            condition = tk.StringVar(value=values[3]); status = tk.StringVar(value=values[4])
            can_rent = tk.BooleanVar(value=values[5] == "Có"); can_sell = tk.BooleanVar(value=values[6] == "Có")
            rental_override, sale_override, deposit_override, note = tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()
            fields = [
                ("Barcode", barcode, None), ("Định dạng", media, ("VHS", "VCD", "DVD", "Blu-ray")),
                ("Tình trạng", condition, tuple(value.value for value in CopyCondition)),
                ("Trạng thái", status, ("AVAILABLE", "INSPECTION", "REPAIR", "LOST", "RETIRED")),
                ("Giá thuê override", rental_override, None), ("Giá bán override", sale_override, None),
                ("Cọc override", deposit_override, None), ("Ghi chú đổi trạng thái", note, None),
            ]
            for row, (label, variable, options) in enumerate(fields):
                ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4)
                control = ttk.Combobox(body, textvariable=variable, values=options, state="readonly") if options else ttk.Entry(body, textvariable=variable)
                control.grid(row=row, column=1, sticky="ew", pady=4)
            ttk.Checkbutton(body, text="Cho thuê", variable=can_rent).grid(row=len(fields), column=0, sticky="w", pady=6)
            ttk.Checkbutton(body, text="Cho bán", variable=can_sell).grid(row=len(fields), column=1, sticky="w", pady=6)
            body.columnconfigure(1, weight=1)
            footer = ttk.Frame(dialog, padding=(14, 0, 14, 14)); footer.pack(fill=X)

            def number(variable):
                raw = variable.get().strip().replace(".", "").replace(",", ".")
                return Decimal(raw) if raw else None

            def save():
                try:
                    request = UpdateInventoryCopyRequest(
                        barcode.get(), media.get(), CopyCondition(condition.get()), can_rent.get(), can_sell.get(),
                        CopyStatus(status.get()), number(rental_override), number(sale_override), number(deposit_override), note.get(),
                    )
                    self.call(lambda s: s.update_inventory_copy(int(selected[0]), request, self.account.employee_id), True)
                    dialog.destroy(); refresh()
                except Exception as exc:
                    messagebox.showerror("Kho đĩa", str(exc), parent=dialog)
            ttk.Button(footer, text="Lưu", command=save, bootstyle="primary").pack(side=RIGHT)
            ttk.Button(footer, text="Hủy", command=dialog.destroy, bootstyle="secondary").pack(side=RIGHT, padx=6)

        def inspect(target_status: CopyStatus):
            selected = tree.selection()
            if len(selected) != 1:
                return messagebox.showinfo("Kiểm tra kho", "Hãy chọn một bản đĩa chờ kiểm tra.", parent=self)
            note = simpledialog.askstring("Kiểm tra kho", "Ghi chú (không bắt buộc):", parent=self)
            if note is None:
                return
            try:
                self.call(lambda s: s.inspect_copy(int(selected[0]), self.account.employee_id, target_status, note), True)
                refresh()
            except Exception as exc:
                messagebox.showerror("Kiểm tra kho", str(exc), parent=self)
        ttk.Button(filters, text="Lọc", command=refresh, bootstyle="secondary").pack(side=LEFT)
        ttk.Button(filters, text="Sửa bản đĩa", command=edit_copy, bootstyle="primary", state="normal" if self._can_manage() else "disabled").pack(side=RIGHT, padx=6)
        ttk.Button(filters, text="Duyệt vào kho", command=lambda: inspect(CopyStatus.AVAILABLE), bootstyle="success").pack(side=RIGHT)
        ttk.Button(filters, text="Chuyển sửa chữa", command=lambda: inspect(CopyStatus.REPAIR), bootstyle="warning").pack(side=RIGHT, padx=6)
        ttk.Button(filters, text="Ngưng khai thác", command=lambda: inspect(CopyStatus.RETIRED), bootstyle="danger").pack(side=RIGHT)
        pager_update = self._create_pager(page, page_number, refresh)
        self._install_sortable_headings(tree, dict(titles), sort_state, lambda: (page_number.set(1), refresh()))
        tree.bind("<Double-1>", edit_copy)
        status_filter.trace_add("write", lambda *_: (page_number.set(1), refresh()))
        page.refresh = refresh

    def customers_page(self, page) -> None:
        bar = self._heading(page, "Khách hàng & Premium", "Điểm uy tín ảnh hưởng cọc và hạn mức thuê")
        search = tk.StringVar()
        ttk.Entry(bar, textvariable=search, width=35).pack(side=RIGHT)
        ttk.Label(bar, text="Tìm tên / SĐT:").pack(side=RIGHT, padx=(0, 4))
        tree = ttk.Treeview(page, columns=("phone", "email", "trust", "premium"), show="tree headings")
        tree.heading("#0", text="Khách hàng"); tree.heading("phone", text="Số điện thoại"); tree.heading("email", text="Email"); tree.heading("trust", text="Uy tín"); tree.heading("premium", text="Premium")
        tree.pack(fill=BOTH, expand=True)
        bottom = ttk.Frame(page); bottom.pack(fill=X, pady=6)
        rows = {}
        def refresh():
            tree.delete(*tree.get_children()); rows.clear()
            for customer in self.call(lambda s: s.list_customers(search.get())):
                rows[str(customer.id)] = customer
                premium = self.call(lambda s, ident=customer.id: s.premium_active(ident))
                tree.insert("", END, iid=str(customer.id), text=customer.full_name, values=(customer.phone, customer.email or "—", customer.reputation_score, "Đang hiệu lực" if premium else "Thường"))
        def add_customer(): self._quick_customer(None)
        def premium():
            ids = tree.selection()
            if not ids: return
            days = simpledialog.askinteger("Premium", "Kỳ hạn 30, 90 hoặc 365 ngày:", initialvalue=30, parent=self)
            if days:
                method = self._choose_payment_method("Premium", self)
                if method is None:
                    return
                try: self.call(lambda s: s.activate_premium(int(ids[0]), days, self.account.employee_id, method), True); refresh()
                except Exception as exc: messagebox.showerror("Premium", str(exc), parent=self)
        def adjust_reputation():
            ids = tree.selection()
            if len(ids) != 1:
                return messagebox.showinfo("Uy tín", "Hãy chọn một khách hàng.", parent=self)
            delta = simpledialog.askinteger("Uy tín", "Điều chỉnh điểm (ví dụ 5 hoặc -10):", parent=self)
            reason = simpledialog.askstring("Uy tín", "Lý do bắt buộc:", parent=self) if delta else None
            if not reason:
                return
            try:
                self.call(lambda s: s.adjust_reputation(int(ids[0]), delta, reason, self.account.employee_id), True)
                refresh()
            except Exception as exc:
                messagebox.showerror("Uy tín", str(exc), parent=self)
        def recommend():
            ids = tree.selection()
            if len(ids) != 1:
                return messagebox.showinfo("Đề cử", "Hãy chọn một khách hàng.", parent=self)
            button.configure(state="disabled", text="Đang đề cử…")
            def done(results):
                button.configure(state="normal", text="Đề cử phim")
                text = "\n".join(f"• {item.title} — {item.reason} ({item.source})" for item in results) or "Chưa có phim phù hợp còn hàng."
                messagebox.showinfo("Đề cử cho khách hàng", text, parent=self)
            def failed(_exc):
                button.configure(state="normal", text="Đề cử phim")
                messagebox.showerror("Đề cử", "Không thể tạo đề cử lúc này.", parent=self)
            self.call_async(lambda s: s.customer_recommendations(int(ids[0])), done, failed, True)
        ttk.Button(bottom, text="Thêm khách", command=add_customer).pack(side=LEFT)
        ttk.Button(bottom, text="Kích hoạt Premium", command=premium, bootstyle="warning").pack(side=LEFT, padx=5)
        ttk.Button(bottom, text="Điều chỉnh uy tín", command=adjust_reputation, bootstyle="secondary", state="normal" if self._can_manage() else "disabled").pack(side=LEFT, padx=5)
        button = ttk.Button(bottom, text="Đề cử phim", command=recommend, bootstyle="primary")
        button.pack(side=LEFT, padx=5)
        search.trace_add("write", lambda *_: self.after(250, refresh))
        page.refresh = refresh

    def promotions_page(self, page) -> None:
        self._heading(page, "Combo / Voucher", "Ưu đãi áp theo Combo → Premium → Voucher, trần 50%")
        notebook = ttk.Notebook(page); notebook.pack(fill=BOTH, expand=True)
        combo, voucher = ttk.Frame(notebook, padding=15), ttk.Frame(notebook, padding=15)
        notebook.add(combo, text="Combo"); notebook.add(voucher, text="Voucher")
        ttk.Label(combo, text="Combo cố định giảm giá khi giỏ có đủ toàn bộ item. Nhập ID phim/tập, phân cách bằng dấu phẩy.", justify=LEFT).pack(anchor="nw")
        def create_combo():
            name = simpledialog.askstring("Combo", "Tên combo:", parent=self)
            item_text = simpledialog.askstring("Combo", "ID phim/tập:", parent=self) if name else None
            discount = simpledialog.askstring("Combo", "Số tiền giảm:", parent=self) if item_text else None
            if not discount:
                return
            try:
                ids = [int(value.strip()) for value in item_text.split(",")]
                self.call(lambda s: s.create_fixed_combo(name, ids, Decimal(discount), self.account.employee_id), True)
                messagebox.showinfo("Combo", "Đã tạo combo. Combo sẽ xuất hiện trong màn lập phiếu.", parent=self)
                refresh_promotions()
            except Exception as exc:
                messagebox.showerror("Combo", str(exc), parent=self)
        management_state = "normal" if self._can_manage() else "disabled"
        ttk.Button(combo, text="Tạo combo cố định", command=create_combo, bootstyle="primary", state=management_state).pack(anchor="w", pady=(10, 0))
        def create_episode_combo():
            name = simpledialog.askstring("Combo tập phim", "Tên combo:", parent=self)
            show_id = simpledialog.askinteger("Combo tập phim", "ID bộ phim (Show):", parent=self) if name else None
            count = simpledialog.askinteger("Combo tập phim", "Số tập tối thiểu:", parent=self) if show_id else None
            discount = simpledialog.askstring("Combo tập phim", "Số tiền giảm:", parent=self) if count else None
            if not discount:
                return
            try:
                self.call(lambda s: s.create_show_episode_combo(name, show_id, count, Decimal(discount), self.account.employee_id), True)
                messagebox.showinfo("Combo tập phim", "Đã tạo combo theo số tập cùng bộ.", parent=self)
                refresh_promotions()
            except Exception as exc:
                messagebox.showerror("Combo tập phim", str(exc), parent=self)
        ttk.Button(combo, text="Tạo combo N tập cùng bộ", command=create_episode_combo, bootstyle="secondary", state=management_state).pack(anchor="w", pady=(6, 0))
        combo_tree = ttk.Treeview(combo, columns=("rule", "scope", "required", "discount", "state"), show="tree headings", height=12)
        for key, title in [("#0", "Tên combo"), ("rule", "Quy tắc"), ("scope", "Áp dụng"), ("required", "Số tập"), ("discount", "Giảm"), ("state", "Trạng thái")]:
            combo_tree.heading(key, text=title)
        combo_tree.column("scope", width=250)
        combo_tree.pack(fill=BOTH, expand=True, pady=(10, 0))
        tree = ttk.Treeview(voucher, columns=("description", "starts", "ends", "state"), show="tree headings", height=12)
        for key, title in [("#0", "Mã"), ("description", "Ưu đãi"), ("starts", "Bắt đầu"), ("ends", "Kết thúc"), ("state", "Trạng thái")]:
            tree.heading(key, text=title)
        tree.pack(fill=BOTH, expand=True)

        def refresh_promotions():
            combo_tree.delete(*combo_tree.get_children())
            for item in self.call(lambda s: s.list_combos(include_inactive=True)):
                combo_tree.insert("", END, iid=str(item.combo_id), text=item.name, values=(
                    "Cố định" if item.rule_type == "FIXED" else "Theo bộ", item.scope,
                    item.required_count or "—", vnd(item.discount_amount), "Hoạt động" if item.active else "Đã tắt",
                ))
            tree.delete(*tree.get_children())
            for item in self.call(lambda s: s.list_vouchers()):
                tree.insert("", END, iid=str(item.voucher_id), text=item.code, values=(
                    item.description, item.starts_on or "—", item.ends_on or "—", item.effective_state,
                ))
        def create_voucher():
            code = simpledialog.askstring("Voucher", "Mã voucher:", parent=self)
            if not code:
                return
            value = simpledialog.askstring("Voucher", "Nhập phần trăm (vd 10) hoặc số tiền kèm 'd' (vd 20000d):", parent=self)
            if not value:
                return
            try:
                text = value.strip().lower()
                percent = None if text.endswith("d") else Decimal(text)
                amount = Decimal(text[:-1]) if text.endswith("d") else None
                self.call(lambda s: s.create_voucher(code, percent_off=percent, amount_off=amount, actor_id=self.account.employee_id), True)
                refresh_promotions()
            except Exception as exc:
                messagebox.showerror("Voucher", str(exc), parent=self)
        ttk.Button(voucher, text="Tạo voucher", command=create_voucher, bootstyle="primary", state=management_state).pack(anchor="e", pady=(8, 0))
        ttk.Button(combo, text="Làm mới", command=refresh_promotions, bootstyle="secondary").pack(anchor="e", pady=(6, 0))
        ttk.Button(voucher, text="Làm mới", command=refresh_promotions, bootstyle="secondary").pack(anchor="w", pady=(8, 0))
        page.refresh = refresh_promotions

    def shifts_page(self, page) -> None:
        self._heading(page, "Nhân viên & ca làm", "Mỗi giao dịch được gắn nhân viên và ca thực hiện")
        info = tk.StringVar()
        ttk.Label(page, textvariable=info, font=("Segoe UI", 13)).pack(anchor="w", pady=12)
        actions = ttk.Frame(page); actions.pack(fill=X)
        employees_tree = ttk.Treeview(page, columns=("phone", "username", "role", "state"), show="tree headings", height=10)
        employees_tree.heading("#0", text="Nhân viên"); employees_tree.heading("phone", text="Điện thoại"); employees_tree.heading("username", text="Tài khoản"); employees_tree.heading("role", text="Vai trò"); employees_tree.heading("state", text="Trạng thái")
        employees_tree.pack(fill=BOTH, expand=True, pady=(12, 0))
        def refresh():
            shift = self.call(lambda s: s.current_shift(self.account.employee_id))
            self.current_shift = shift
            info.set(f"{self.account.employee.full_name}: " + (f"đang mở ca #{shift.id} từ {shift.opened_at:%H:%M}" if shift else "chưa mở ca"))
            self._refresh_status()
            employees_tree.delete(*employees_tree.get_children())
            for employee in self.call(lambda s: s.list_employees()):
                employees_tree.insert("", END, iid=str(employee.employee_id), text=employee.full_name, values=(employee.phone or "—", employee.username or "Chưa có", employee.role_name or "—", "Đang làm" if employee.active else "Ngưng"))
        def add_employee():
            full_name = simpledialog.askstring("Nhân viên", "Họ tên:", parent=self)
            phone = simpledialog.askstring("Nhân viên", "Điện thoại:", parent=self) if full_name else None
            username = simpledialog.askstring("Nhân viên", "Tên đăng nhập:", parent=self) if phone is not None else None
            role = simpledialog.askstring("Nhân viên", "Vai trò: ADMIN, MANAGER hoặc STAFF:", initialvalue="STAFF", parent=self) if username else None
            password = simpledialog.askstring("Nhân viên", "Mật khẩu tạm (ít nhất 8 ký tự):", show="•", parent=self) if role else None
            if not password:
                return
            try:
                self.call(lambda s: s.create_employee_account(full_name, phone or "", username, RoleCode(role.upper()), password, self.account.employee_id), True)
                refresh()
            except Exception as exc:
                messagebox.showerror("Nhân viên", str(exc), parent=self)
        ttk.Button(actions, text="Mở ca", command=self._open_shift, bootstyle="success").pack(side=LEFT, padx=3)
        ttk.Button(actions, text="Đóng ca", command=self._close_shift, bootstyle="danger").pack(side=LEFT, padx=3)
        ttk.Button(actions, text="Thêm nhân viên", command=add_employee, bootstyle="primary", state="normal" if self._can_manage() else "disabled").pack(side=LEFT, padx=3)
        page.refresh = refresh

    def _open_shift(self) -> None:
        if not self.account: return
        try:
            amount = simpledialog.askstring("Mở ca", "Tiền đầu ca:", initialvalue="0", parent=self)
            if amount is None: return
            self.call(lambda s: s.open_shift(self.account.employee_id, Decimal(amount)), True)
            self._refresh_status()
            refresh = getattr(self.pages.get("Nhân viên & ca"), "refresh", None)
            if refresh: refresh()
        except Exception as exc: messagebox.showerror("Ca làm", str(exc), parent=self)

    def _close_shift(self) -> None:
        if not self.current_shift: return messagebox.showinfo("Ca làm", "Không có ca đang mở.", parent=self)
        try:
            amount = simpledialog.askstring("Đóng ca", "Tiền cuối ca thực tế:", initialvalue="0", parent=self)
            if amount is None: return
            self.call(lambda s: s.close_shift(self.current_shift.id, Decimal(amount), self.account.employee_id), True); self._refresh_status()
            refresh = getattr(self.pages.get("Nhân viên & ca"), "refresh", None)
            if refresh: refresh()
        except Exception as exc: messagebox.showerror("Ca làm", str(exc), parent=self)

    def notifications_page(self, page) -> None:
        self._heading(page, "Thông báo", "Email SMTP thật • SMS mock • Gửi bù khi mở app")
        ttk.Label(page, text="Worker kiểm tra mỗi 5 phút khi ứng dụng mở. SMS là mock; Email chỉ gửi khi SMTP và Windows Credential Manager được cấu hình.", wraplength=850, justify=LEFT).pack(anchor="w", pady=(0, 10))
        tree = ttk.Treeview(page, columns=("customer", "channel", "event", "scheduled", "status", "attempts", "error"), show="headings")
        for key, title in [("customer", "Khách hàng"), ("channel", "Kênh"), ("event", "Sự kiện"), ("scheduled", "Lịch gửi"), ("status", "Trạng thái"), ("attempts", "Lần thử"), ("error", "Lỗi")]: tree.heading(key, text=title)
        tree.column("error", width=260); tree.pack(fill=BOTH, expand=True)
        def refresh():
            tree.delete(*tree.get_children())
            for notification in self.call(lambda s: s.list_notifications()):
                tree.insert("", END, iid=str(notification.notification_id), values=(notification.customer_name, notification.channel, notification.event, notification.scheduled_for.strftime("%d/%m/%Y %H:%M"), notification.status, notification.attempts, notification.error or "—"))
        ttk.Button(page, text="Làm mới", command=refresh, bootstyle="secondary").pack(anchor="e", pady=(8, 0))
        page.refresh = refresh

    def statistics_page(self, page) -> None:
        heading = self._heading(page, "Thống kê", "Doanh thu phát sinh tách hoàn toàn tiền cọc")
        period_var = tk.StringVar(value="Tháng này")
        start_var = tk.StringVar()
        end_var = tk.StringVar()
        ttk.Label(heading, text="Kỳ:").pack(side=LEFT)
        ttk.Combobox(
            heading,
            textvariable=period_var,
            values=("Tất cả", "Hôm nay", "Tháng này", "Quý này", "Năm nay", "Tùy chọn"),
            state="readonly",
            width=12,
        ).pack(side=LEFT, padx=(4, 8))
        ttk.Entry(heading, textvariable=start_var, width=11).pack(side=LEFT)
        ttk.Label(heading, text="đến").pack(side=LEFT, padx=3)
        ttk.Entry(heading, textvariable=end_var, width=11).pack(side=LEFT)
        stats = tk.StringVar()
        ttk.Label(page, textvariable=stats, font=("Segoe UI", 13), justify=LEFT).pack(anchor="w", pady=15)
        tables = ttk.PanedWindow(page, orient="horizontal")
        tables.pack(fill=BOTH, expand=True)
        top_frame = ttk.Frame(tables, padding=4)
        overdue_frame = ttk.Labelframe(tables, text="Khách hàng quá hạn", padding=8)
        stockout_frame = ttk.Labelframe(tables, text="Hết hàng & ETA", padding=8)
        tables.add(top_frame, weight=1); tables.add(overdue_frame, weight=1); tables.add(stockout_frame, weight=1)
        top_tabs = ttk.Notebook(top_frame)
        top_tabs.pack(fill=BOTH, expand=True)
        rental_tab, sale_tab, combo_tab, voucher_tab = ttk.Frame(top_tabs, padding=6), ttk.Frame(top_tabs, padding=6), ttk.Frame(top_tabs, padding=6), ttk.Frame(top_tabs, padding=6)
        top_tabs.add(rental_tab, text="Top thuê")
        top_tabs.add(sale_tab, text="Top bán")
        top_tabs.add(combo_tab, text="Top combo")
        top_tabs.add(voucher_tab, text="Top voucher")
        top_tree = ttk.Treeview(rental_tab, columns=("count",), show="tree headings", height=11)
        top_tree.heading("#0", text="Phim / tập"); top_tree.heading("count", text="Lượt thuê")
        top_tree.column("count", width=90, anchor="e")
        top_tree.pack(fill=BOTH, expand=True)
        sale_tree = ttk.Treeview(sale_tab, columns=("count",), show="tree headings", height=11)
        sale_tree.heading("#0", text="Phim / tập"); sale_tree.heading("count", text="Lượt bán")
        sale_tree.column("count", width=90, anchor="e")
        sale_tree.pack(fill=BOTH, expand=True)
        combo_tree = ttk.Treeview(combo_tab, columns=("count",), show="tree headings", height=11)
        combo_tree.heading("#0", text="Combo"); combo_tree.heading("count", text="Lượt dùng")
        combo_tree.column("count", width=90, anchor="e")
        combo_tree.pack(fill=BOTH, expand=True)
        voucher_tree = ttk.Treeview(voucher_tab, columns=("count",), show="tree headings", height=11)
        voucher_tree.heading("#0", text="Voucher"); voucher_tree.heading("count", text="Lượt dùng")
        voucher_tree.column("count", width=90, anchor="e")
        voucher_tree.pack(fill=BOTH, expand=True)
        overdue_tree = ttk.Treeview(overdue_frame, columns=("count", "fee"), show="tree headings", height=11)
        overdue_tree.heading("#0", text="Khách hàng"); overdue_tree.heading("count", text="Đĩa quá hạn"); overdue_tree.heading("fee", text="Phạt hiện tại")
        overdue_tree.column("count", width=90, anchor="e"); overdue_tree.column("fee", width=130, anchor="e")
        overdue_tree.pack(fill=BOTH, expand=True)
        stockout_tree = ttk.Treeview(stockout_frame, columns=("eta",), show="tree headings", height=11)
        stockout_tree.heading("#0", text="Phim / tập")
        stockout_tree.heading("eta", text="ETA dự kiến")
        stockout_tree.column("eta", width=110, anchor="e")
        stockout_tree.pack(fill=BOTH, expand=True)
        chart_frame = ttk.Labelframe(page, text="Phân bổ tồn kho", padding=6)
        chart_frame.pack(fill=X, pady=(10, 0))
        figure = Figure(figsize=(7.8, 2.3), dpi=100)
        self._figures.append(figure)
        axis = figure.add_subplot(111)
        self._style_figure(figure)
        chart = FigureCanvasTkAgg(figure, master=chart_frame)
        chart.get_tk_widget().pack(fill=X)
        inventory_statuses = (
            CopyStatus.AVAILABLE,
            CopyStatus.RENTED,
            CopyStatus.INSPECTION,
            CopyStatus.REPAIR,
            CopyStatus.LOST,
            CopyStatus.RETIRED,
        )
        bar_statuses: dict[object, CopyStatus] = {}

        def open_inventory_drilldown(status: CopyStatus):
            dialog = tb.Toplevel(self)
            dialog.title(f"Kho: {status.value}")
            dialog.geometry("760x440")
            dialog.transient(self)
            label = ttk.Label(dialog, text="", font=self._font("section"))
            label.pack(anchor="w", padx=12, pady=(12, 6))
            tree = ttk.Treeview(dialog, columns=("format", "condition", "rent", "buy"), show="tree headings")
            tree.heading("#0", text="Barcode / phim")
            tree.heading("format", text="Định dạng")
            tree.heading("condition", text="Hiện trạng")
            tree.heading("rent", text="Cho thuê")
            tree.heading("buy", text="Cho mua")
            tree.column("#0", width=360)
            tree.pack(fill=BOTH, expand=True, padx=12, pady=(0, 12))
            copy_page = tk.IntVar(value=1)
            copy_sort: dict[str, object] = {"field": "barcode", "descending": False}
            def load_copies():
                tree.delete(*tree.get_children())
                result = self.call(lambda s: s.query_inventory(status, PageRequest(copy_page.get(), 50), SortSpec(str(copy_sort["field"]), bool(copy_sort["descending"]))))
                label.configure(text=f"{result.total_items:,} bản đĩa trạng thái {status.value}".replace(",", "."))
                copy_pager(result)
                for copy in result.items:
                    tree.insert("", END, text=f"{copy.barcode} — {copy.title}", values=(copy.media_format, copy.condition, "Có" if copy.can_rent else "Không", "Có" if copy.can_sell else "Không"))
            copy_pager = self._create_pager(dialog, copy_page, load_copies)
            self._install_sortable_headings(tree, {"#0": "Barcode / phim", "format": "Định dạng", "condition": "Hiện trạng", "rent": "Cho thuê", "buy": "Cho mua"}, copy_sort, lambda: (copy_page.set(1), load_copies()))
            load_copies()

        def chart_click(event):
            status = bar_statuses.get(event.artist)
            if not status:
                return
            open_inventory_drilldown(status)

        figure.canvas.mpl_connect("pick_event", chart_click)

        def report_dates() -> tuple[date | None, date | None]:
            today = date.today()
            period = period_var.get()
            if period == "Tất cả":
                return None, None
            if period == "Hôm nay":
                return today, today
            if period == "Tháng này":
                return today.replace(day=1), today
            if period == "Quý này":
                first_month = (today.month - 1) // 3 * 3 + 1
                return today.replace(month=first_month, day=1), today
            if period == "Năm nay":
                return today.replace(month=1, day=1), today
            try:
                start = date.fromisoformat(start_var.get()) if start_var.get().strip() else None
                end = date.fromisoformat(end_var.get()) if end_var.get().strip() else None
            except ValueError as exc:
                raise ValueError("Ngày lọc phải theo dạng YYYY-MM-DD.") from exc
            if not start and not end:
                raise ValueError("Nhập ít nhất một ngày cho kỳ tùy chọn.")
            return start, end

        def current_report():
            start_on, end_on = report_dates()
            return self.call(lambda s: s.operational_report(start_on, end_on))

        def export_csv():
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Xuất báo cáo NormaStore",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv")],
                initialfile="normastore-report.csv",
            )
            if not path:
                return
            try:
                report = current_report()
                with open(path, "w", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["Chỉ số", "Giá trị"])
                    for label, value in [
                        ("Doanh thu thuê phát sinh", report.rental_revenue), ("Doanh thu bán phát sinh", report.sale_revenue),
                        ("Doanh thu Premium phát sinh", report.premium_revenue),
                        ("Tiền đã thu (gồm cọc)", report.cash_collected), ("Tiền đã hoàn", report.cash_refunded),
                        ("Dòng tiền thuần (gồm cọc)", report.net_cash_flow),
                        ("Doanh thu trước giảm", report.gross_revenue), ("Tổng giảm giá", report.discounts_granted),
                        ("Tỷ lệ giảm giá TB (%)", report.average_discount_rate),
                        ("Premium đang hiệu lực", report.active_premium_memberships),
                        ("Premium hết hạn", report.expired_premium_memberships),
                        ("Email đã gửi", report.email_notifications_sent),
                        ("SMS mock đã gửi", report.sms_notifications_sent),
                        ("Thông báo thất bại", report.notification_failures),
                        ("Phạt đã ghi nhận", report.penalties_assessed), ("Hoàn hàng bán", report.sales_refunded),
                        ("Cọc đang giữ", report.deposits_held), ("Có sẵn", report.available), ("Đang thuê", report.rented),
                        ("Quá hạn", report.overdue_count),
                    ]:
                        writer.writerow([label, value])
                    writer.writerow([]); writer.writerow(["Top thuê", "Lượt"])
                    writer.writerows(report.top_rentals)
                    writer.writerow([]); writer.writerow(["Top bán", "Lượt"])
                    writer.writerows(report.top_sales)
                    writer.writerow([]); writer.writerow(["Top combo thuê", "Lượt"])
                    writer.writerows(report.top_combos)
                    writer.writerow([]); writer.writerow(["Top voucher", "Lượt"])
                    writer.writerows(report.top_vouchers)
                    writer.writerow([]); writer.writerow(["Item hết hàng", "ETA dự kiến"])
                    writer.writerows(
                        (item.title, item.estimated_available_on.isoformat() if item.estimated_available_on else "Chưa xác định")
                        for item in report.out_of_stock
                    )
                    writer.writerow([]); writer.writerow(["Item đặt trước", "Khách đang chờ"])
                    writer.writerows(report.waiting_reservations)
                    writer.writerow([]); writer.writerow(["Khách quá hạn", "Số đĩa", "Phạt hiện tại"])
                    writer.writerows((entry.customer_name, entry.rental_count, entry.overdue_amount) for entry in report.overdue_customers)
                messagebox.showinfo("Thống kê", "Đã xuất CSV thành công.", parent=self)
            except Exception as exc:
                messagebox.showerror("Thống kê", str(exc), parent=self)
        def export_chart():
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Xuất biểu đồ tồn kho",
                defaultextension=".png",
                filetypes=[("PNG", "*.png")],
                initialfile="normastore-inventory.png",
            )
            if not path:
                return
            try:
                figure.savefig(path, dpi=160, bbox_inches="tight")
                messagebox.showinfo("Thống kê", "Đã xuất ảnh biểu đồ.", parent=self)
            except Exception as exc:
                messagebox.showerror("Thống kê", str(exc), parent=self)
        ttk.Button(heading, text="Áp dụng", command=lambda: refresh(), bootstyle="primary").pack(side=RIGHT, padx=5)
        ttk.Button(heading, text="Xuất CSV", command=export_csv, bootstyle="secondary").pack(side=RIGHT)
        ttk.Button(heading, text="Xuất ảnh", command=export_chart, bootstyle="secondary").pack(side=RIGHT, padx=5)
        def refresh():
            try:
                report = current_report()
            except Exception as exc:
                messagebox.showerror("Thống kê", str(exc), parent=self)
                return
            stats.set(
                f"Tài chính\n• Doanh thu thuê phát sinh: {vnd(report.rental_revenue)}  • Doanh thu bán phát sinh: {vnd(report.sale_revenue)}\n"
                f"• Doanh thu Premium phát sinh: {vnd(report.premium_revenue)}\n"
                f"• Tiền đã thu (gồm cọc): {vnd(report.cash_collected)}  • Tiền đã hoàn: {vnd(report.cash_refunded)}  • Dòng tiền thuần: {vnd(report.net_cash_flow)}\n"
                f"• Trước giảm: {vnd(report.gross_revenue)}  • Giảm giá: {vnd(report.discounts_granted)} ({report.average_discount_rate:.2f}%)\n"
                f"• Premium: {report.active_premium_memberships} đang hiệu lực, {report.expired_premium_memberships} hết hạn\n"
                f"• Khách Premium distinct: {report.premium_customer_count}  • Giảm theo nguồn: {', '.join(f'{name} {vnd(amount)}' for name, amount in report.discounts_by_source) or '—'}\n"
                f"• Thông báo: Email {report.email_notifications_sent}, SMS {report.sms_notifications_sent}, lỗi {report.notification_failures}\n"
                f"• Phạt đã ghi nhận: {vnd(report.penalties_assessed)}  • Hoàn hàng bán: {vnd(report.sales_refunded)}\n"
                f"• Cọc đang giữ: {vnd(report.deposits_held)}\n\n"
                f"Kho\n• Có sẵn: {report.available}  • Đang thuê: {report.rented}  • Chờ kiểm tra: {report.inspection}\n"
                f"• Sửa chữa: {report.repair}  • Mất: {report.lost}  • Ngưng khai thác: {report.retired}  • Quá hạn: {report.overdue_count}"
            )
            top_tree.delete(*top_tree.get_children())
            sale_tree.delete(*sale_tree.get_children())
            combo_tree.delete(*combo_tree.get_children())
            voucher_tree.delete(*voucher_tree.get_children())
            overdue_tree.delete(*overdue_tree.get_children())
            stockout_tree.delete(*stockout_tree.get_children())
            for title, count in report.top_rentals:
                top_tree.insert("", END, text=title, values=(count,))
            for title, count in report.top_sales:
                sale_tree.insert("", END, text=title, values=(count,))
            for name, count in report.top_combos:
                combo_tree.insert("", END, text=name, values=(count,))
            for name, count in report.top_vouchers:
                voucher_tree.insert("", END, text=name, values=(count,))
            for customer in report.overdue_customers:
                overdue_tree.insert("", END, text=customer.customer_name, values=(customer.rental_count, vnd(customer.overdue_amount)))
            for item in report.out_of_stock:
                eta = item.estimated_available_on.strftime("%d/%m/%Y") if item.estimated_available_on else "Chưa xác định"
                stockout_tree.insert("", END, text=item.title, values=(eta,))
            axis.clear()
            self._style_figure(figure)
            labels = ["Có sẵn", "Đang thuê", "Kiểm tra", "Sửa chữa", "Mất", "Ngưng"]
            values = [report.available, report.rented, report.inspection, report.repair, report.lost, report.retired]
            bars = axis.bar(labels, values, color=["#2e8b57", "#3b82f6", "#f59e0b", "#ef4444", "#7c3aed", "#6b7280"])
            bar_statuses.clear()
            bar_statuses.update(zip(bars, inventory_statuses))
            for bar in bars:
                bar.set_picker(True)
            axis.set_ylabel("Số bản đĩa")
            axis.set_title("Trạng thái tồn kho")
            figure.tight_layout()
            chart.draw_idle()
        page.refresh = refresh

    def audit_page(self, page) -> None:
        self._heading(page, "Nhật ký hành động", "Thay đổi nghiệp vụ và sự kiện bảo mật")
        filters = ttk.Frame(page); filters.pack(fill=X, pady=(0, 8))
        text, action = tk.StringVar(), tk.StringVar()
        ttk.Label(filters, text="Tìm:").pack(side=LEFT)
        ttk.Entry(filters, textvariable=text, width=32).pack(side=LEFT, padx=(4, 10))
        ttk.Label(filters, text="Hành động:").pack(side=LEFT)
        ttk.Entry(filters, textvariable=action, width=25).pack(side=LEFT, padx=4)
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "created", "descending": True}
        tree = ttk.Treeview(page, columns=("created", "actor", "action", "entity", "entity_id"), show="headings")
        titles = {"created": "Thời gian", "actor": "Nhân viên", "action": "Hành động", "entity": "Đối tượng", "entity_id": "ID"}
        for key, title in titles.items():
            tree.heading(key, text=title)
        tree.pack(fill=BOTH, expand=True)
        rows = {}
        def refresh():
            tree.delete(*tree.get_children()); rows.clear()
            result = self.call(lambda s: s.query_audit_logs(
                AuditQuery(text.get(), action.get()), PageRequest(page_number.get(), 50),
                SortSpec(str(sort_state["field"]), bool(sort_state["descending"])),
            ))
            pager(result)
            for row in result.items:
                rows[str(row.audit_id)] = row
                tree.insert("", END, iid=str(row.audit_id), values=(row.created_at, row.actor_name or "Hệ thống", row.action, row.entity, row.entity_id))
        def detail(_event=None):
            selected = tree.selection()
            if len(selected) != 1:
                return
            row = rows[selected[0]]
            dialog = self._dialog("Chi tiết nhật ký", 720, 480, modal=False)
            body = tk.Text(dialog, wrap="word", padx=12, pady=12)
            self._theme_text_widgets.append(body)
            self._apply_ui_style()
            body.pack(fill=BOTH, expand=True)
            body.insert("1.0", json.dumps(row.detail, ensure_ascii=False, indent=2, default=str) if isinstance(row.detail, (dict, list)) else str(row.detail or "Không có chi tiết"))
            body.configure(state="disabled")
        ttk.Button(filters, text="Lọc", command=lambda: (page_number.set(1), refresh()), bootstyle="secondary").pack(side=LEFT, padx=6)
        pager = self._create_pager(page, page_number, refresh)
        self._install_sortable_headings(tree, titles, sort_state, lambda: (page_number.set(1), refresh()))
        tree.bind("<Double-1>", detail)
        state: dict[str, str] = {}
        text.trace_add("write", lambda *_: self._debounce(state, lambda: (page_number.set(1), refresh())))
        action.trace_add("write", lambda *_: self._debounce(state, lambda: (page_number.set(1), refresh())))
        page.refresh = refresh

    def settings_page(self, page) -> None:
        self._heading(page, "Cài đặt & About", "Kết nối, secret và attribution")
        ttk.Label(page, text=f"Database: {self.settings.database_url}\n\nTMDB/Gemini/SMTP không được hard-code. Đặt biến môi trường NORMASTORE_* hoặc lưu secret bằng Windows Credential Manager.\n\nThis product uses the TMDB API but is not endorsed or certified by TMDB.", justify=LEFT, wraplength=850).pack(anchor="w", pady=12)
        ttk.Label(page, text="Khóa API đã từng gửi qua chat cần được đổi trước khi import dữ liệu thật.", bootstyle="danger").pack(anchor="w")
        gemini_box = ttk.Labelframe(page, text="Gemini", padding=12)
        gemini_box.pack(fill=X, pady=(14, 0))
        source = "biến môi trường" if os.environ.get("NORMASTORE_GEMINI_API_KEY") else ("Windows Credential Manager" if keyring.get_password("normastore", "gemini") else "chưa cấu hình")
        ttk.Label(gemini_box, text=f"Nguồn key hiện tại: {source}. Key không được hiển thị lại.").pack(anchor="w")
        gemini_actions = ttk.Frame(gemini_box); gemini_actions.pack(fill=X, pady=(8, 0))
        def save_gemini():
            value = simpledialog.askstring("Gemini API key", "Nhập Gemini API key để lưu trong Windows Credential Manager:", show="•", parent=self)
            if not value:
                return
            try:
                keyring.set_password("normastore", "gemini", value.strip())
                messagebox.showinfo("Gemini", "Đã lưu key trong Windows Credential Manager.", parent=self)
            except Exception as exc:
                messagebox.showerror("Gemini", str(exc), parent=self)
        def delete_gemini():
            if not messagebox.askyesno("Gemini", "Xóa Gemini key đã lưu trong Credential Manager?", parent=self):
                return
            try:
                keyring.delete_password("normastore", "gemini")
            except keyring.errors.PasswordDeleteError:
                pass
            except Exception as exc:
                return messagebox.showerror("Gemini", str(exc), parent=self)
            messagebox.showinfo("Gemini", "Đã xóa key lưu cục bộ.", parent=self)
        def test_gemini():
            if not self._gemini_api_key():
                return messagebox.showerror("Gemini", "Chưa có Gemini API key.", parent=self)
            test_button.configure(state="disabled", text="Đang kiểm tra…")
            def done(response):
                test_button.configure(state="normal", text="Kiểm tra Gemini")
                messagebox.showinfo("Gemini", "Gemini sẵn sàng." if response.mode == "GEMINI" else (response.warning or "Đang dùng fallback nội bộ."), parent=self)
            def failed(_exc):
                test_button.configure(state="normal", text="Kiểm tra Gemini")
                messagebox.showerror("Gemini", "Không thể kết nối Gemini; ứng dụng vẫn dùng fallback nội bộ.", parent=self)
            self.call_async(lambda s: s.search_by_description_response("phim gia đình"), done, failed)
        ttk.Button(gemini_actions, text="Lưu key", command=save_gemini, bootstyle="secondary").pack(side=LEFT)
        ttk.Button(gemini_actions, text="Xóa key", command=delete_gemini, bootstyle="secondary").pack(side=LEFT, padx=6)
        test_button = ttk.Button(gemini_actions, text="Kiểm tra Gemini", command=test_gemini, bootstyle="primary")
        test_button.pack(side=LEFT)

        if self._can_manage():
            deposit_box = ttk.Labelframe(page, text="Tiền cọc mặc định theo định dạng", padding=12)
            deposit_box.pack(fill=X, pady=(14, 0))
            defaults = self.call(lambda s: s.deposit_defaults())
            values = {name: tk.StringVar(value=str(defaults[name])) for name in ("VHS", "VCD", "DVD", "Blu-ray")}
            for column, name in enumerate(values):
                ttk.Label(deposit_box, text=name).grid(row=0, column=column, padx=5, sticky="w")
                ttk.Entry(deposit_box, textvariable=values[name], width=13).grid(row=1, column=column, padx=5, sticky="ew")
                deposit_box.columnconfigure(column, weight=1)
            deposit_actions = ttk.Frame(deposit_box); deposit_actions.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
            def parsed_defaults():
                return {name: Decimal(variable.get().replace(".", "").replace(",", ".")) for name, variable in values.items()}
            def save_defaults():
                try:
                    self.call(lambda s: s.save_deposit_defaults(parsed_defaults(), self.account.employee_id), True)
                    messagebox.showinfo("Tiền cọc", "Đã lưu mức cọc theo định dạng.", parent=self)
                except Exception as exc:
                    messagebox.showerror("Tiền cọc", str(exc), parent=self)
            def apply_defaults():
                if not messagebox.askyesno("Tiền cọc", "Ghi đè cọc override của toàn bộ đĩa? Phiếu đã lập không thay đổi.", parent=self):
                    return
                try:
                    self.call(lambda s: s.save_deposit_defaults(parsed_defaults(), self.account.employee_id), True)
                    count = self.call(lambda s: s.apply_deposit_defaults_to_inventory(self.account.employee_id), True)
                    messagebox.showinfo("Tiền cọc", f"Đã áp dụng cho {count} bản đĩa.", parent=self)
                except Exception as exc:
                    messagebox.showerror("Tiền cọc", str(exc), parent=self)
            ttk.Button(deposit_actions, text="Lưu mức cọc", command=save_defaults, bootstyle="secondary").pack(side=LEFT)
            ttk.Button(deposit_actions, text="Áp dụng toàn kho", command=apply_defaults, bootstyle="warning").pack(side=LEFT, padx=6)
            mock_box = ttk.Labelframe(page, text="Dữ liệu mock", padding=12)
            mock_box.pack(fill=X, pady=(14, 0))
            ttk.Label(mock_box, text="Tạo tối đa 250 phiếu/ngày, 31 ngày/lần. Ngày đã chạy sẽ tự bỏ qua.", bootstyle="secondary").pack(anchor="w")
            mock_status = tk.StringVar(value="Chưa chạy dữ liệu mock.")
            ttk.Label(mock_box, textvariable=mock_status, bootstyle="secondary").pack(anchor="w", pady=(4, 0))
            def run_mock():
                default_start = (date.today() - timedelta(days=19)).isoformat()
                start_text = simpledialog.askstring("Dữ liệu mock", "Từ ngày (YYYY-MM-DD):", initialvalue=default_start, parent=self)
                end_text = simpledialog.askstring("Dữ liệu mock", "Đến ngày (YYYY-MM-DD):", initialvalue=date.today().isoformat(), parent=self) if start_text else None
                if not end_text:
                    return
                try:
                    start_on, end_on = date.fromisoformat(start_text), date.fromisoformat(end_text)
                except ValueError:
                    return messagebox.showerror("Dữ liệu mock", "Ngày phải theo YYYY-MM-DD.", parent=self)
                if not messagebox.askyesno("Dữ liệu mock", f"Tạo tối đa {(end_on - start_on).days + 1} × 250 phiếu?", parent=self):
                    return
                mock_button.configure(state="disabled", text="Đang tạo mock…")
                mock_status.set("Đang chuẩn bị fixture Combo, Voucher và Premium…")
                def done(result):
                    mock_button.configure(state="normal", text="Cập nhật dữ liệu mock")
                    summary = (f"Đã tạo {result.orders_created} phiếu trên {result.created_days} ngày; bỏ qua {result.skipped_days} ngày.\n"
                        f"Fixture mới: {result.combos_created} Combo, {result.vouchers_created} Voucher, {result.memberships_created} Premium.")
                    if result.failed_on:
                        summary += f"\nDừng tại {result.failed_on}: {result.error}"
                        mock_status.set(f"Ngày {result.failed_on} chưa được ghi, có thể chạy lại.")
                    else:
                        mock_status.set("Hoàn tất; ngày đã tạo sẽ được tự bỏ qua khi chạy lại.")
                    for name in ("Combo / Voucher", "Lập phiếu", "Thống kê"):
                        refresh = getattr(self.pages.get(name), "refresh", None)
                        if refresh:
                            refresh()
                    messagebox.showinfo("Dữ liệu mock", summary, parent=self)
                def failed(exc):
                    mock_button.configure(state="normal", text="Cập nhật dữ liệu mock")
                    mock_status.set("Không thể tạo fixture mock.")
                    messagebox.showerror("Dữ liệu mock", str(exc), parent=self)
                def progress(completed, total):
                    self.after(0, lambda: mock_status.set(f"Đang xử lý ngày {completed}/{total}…"))
                self._run_async(
                    lambda: run_mock_seed(self.factory, MockSeedRequest(start_on, end_on, self.account.employee_id), progress),
                    done,
                    failed,
                )
            mock_button = ttk.Button(mock_box, text="Cập nhật dữ liệu mock", command=run_mock, bootstyle="warning")
            mock_button.pack(anchor="w", pady=(8, 0))
        def test_smtp():
            settings = self.settings
            password = keyring.get_password("normastore", "smtp")
            if not (settings.smtp_host and settings.smtp_username and settings.smtp_from and password):
                return messagebox.showerror("SMTP", "Cần host, username, email gửi và App Password trong Windows Credential Manager.", parent=self)
            def send():
                try:
                    SmtpSender(
                        settings.smtp_host,
                        settings.smtp_port,
                        settings.smtp_username,
                        password,
                        settings.smtp_starttls,
                    ).send(settings.smtp_from, settings.smtp_from, "NormaStore SMTP test", "SMTP NormaStore đã cấu hình thành công.")
                except Exception as exc:
                    error_message = str(exc)
                    self.after(0, lambda: messagebox.showerror("SMTP", error_message, parent=self))
                else:
                    self.after(0, lambda: messagebox.showinfo("SMTP", f"Đã gửi email kiểm tra đến {settings.smtp_from}.", parent=self))
            self.executor.submit(send)
        ttk.Button(page, text="Gửi email kiểm tra", command=test_smtp, bootstyle="secondary").pack(anchor="w", pady=(14, 0))
