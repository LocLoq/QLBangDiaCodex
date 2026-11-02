from __future__ import annotations

import os
import tkinter as tk
from decimal import Decimal
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

from PIL import Image, ImageDraw, ImageFont, ImageTk
from ttkbootstrap.constants import BOTH, LEFT, RIGHT, X, Y

from normastore.domain.enums import RoleCode
from normastore.ui.tooltips import Tooltip

_RAIL_WIDTH = 56
_DRAWER_WIDTH = 230
_MDL2_FONT = "Segoe MDL2 Assets"
_NAVIGATION_ITEMS = (
    ("Tổng quan", "\ue80f", "dashboard_page", False),
    ("Lập phiếu", "\ue7bf", "checkout_page", False),
    ("Phiếu đã lập", "\ue8fd", "orders_page", False),
    ("Trả đĩa & phạt", "\ue72b", "returns_page", False),
    ("Đặt trước", "\ue787", "reservations_page", False),
    ("Phim & tập", "\ue714", "catalog_page", False),
    ("Kho đĩa", "\ue7b8", "inventory_page", False),
    ("Khách hàng & Premium", "\ue716", "customers_page", False),
    ("Combo / Voucher", "\ue8ec", "promotions_page", False),
    ("Nhân viên & ca", "\ue916", "shifts_page", False),
    ("Thông báo", "\uea8f", "notifications_page", False),
    ("Thống kê", "\ueb05", "statistics_page", False),
    ("Nhật ký hành động", "\ue81c", "audit_page", True),
    ("Cài đặt & About", "\ue713", "settings_page", False),
)


class ShellMixin:
    def _login(self) -> None:
        # Keep the action area outside the expanding form.  At 125–150% DPI a
        # 330px client area is too short and used to clip the submit button.
        login = self._dialog("Đăng nhập NormaStore", 440, 410)
        login.minsize(400, 390)
        login.resizable(False, False)
        frame = ttk.Frame(login, padding=(28, 24, 28, 12))
        frame.pack(fill=BOTH, expand=True)
        ttk.Label(
            frame, text="NormaStore", font=("Segoe UI", 22, "bold"), bootstyle="primary"
        ).pack(anchor="w")
        ttk.Label(frame, text="Quản lý băng đĩa truyền thống", font=("Segoe UI", 10)).pack(
            anchor="w", pady=(0, 18)
        )
        user_var, pass_var = tk.StringVar(value="admin"), tk.StringVar(value="admin123")
        ttk.Label(frame, text="Tài khoản").pack(anchor="w")
        user_entry = ttk.Entry(frame, textvariable=user_var, width=34)
        user_entry.pack(fill=X, pady=(3, 10))
        ttk.Label(frame, text="Mật khẩu").pack(anchor="w")
        pass_entry = ttk.Entry(frame, textvariable=pass_var, show="•", width=34)
        pass_entry.pack(fill=X, pady=(3, 14))
        ttk.Label(frame, text="Lần đầu: admin / admin123", bootstyle="secondary").pack(
            anchor="w", pady=(0, 12)
        )

        def submit(_event=None):
            account = self.store.authenticate(user_var.get(), pass_var.get())
            if not account:
                messagebox.showerror(
                    "Đăng nhập", "Tài khoản hoặc mật khẩu không đúng.", parent=login
                )
                return
            self.account = account
            login.destroy()
            self._build_shell()

        footer = ttk.Frame(login, padding=(28, 0, 28, 24))
        footer.pack(fill=X, side="bottom")
        ttk.Button(footer, text="Đăng nhập", command=submit, bootstyle="primary").pack(fill=X)
        pass_entry.bind("<Return>", submit)
        login.protocol("WM_DELETE_WINDOW", self.destroy)
        user_entry.focus_set()

    def _build_shell(self) -> None:
        self._build_menu()
        outer = ttk.Frame(self)
        outer.pack(fill=BOTH, expand=True)
        self.pages = {}
        self._active_page = ""
        self._drawer_pinned = False
        self._drawer_temporary = False
        self._nav_buttons: dict[str, list[ttk.Button]] = {}
        self._nav_icon_widgets: list[tuple[ttk.Button, str]] = []
        self._navigation_icon_images: dict[str, ImageTk.PhotoImage] = {}

        self.sidebar = ttk.Frame(outer, padding=(6, 10), width=_RAIL_WIDTH)
        self.sidebar.pack(side=LEFT, fill=Y)
        self.sidebar.pack_propagate(False)
        self._add_navigation_button(
            self.sidebar, "\ue700", "Mở điều hướng", icon_only=True, command=self._toggle_drawer
        )
        self._nav_icon_widgets[-1][0].bind(
            "<Enter>", lambda _event: self._open_drawer(temporary=True), add="+"
        )

        self.drawer = ttk.Frame(outer, padding=(12, 14), width=_DRAWER_WIDTH)
        self.drawer.pack_propagate(False)
        self.drawer.bind("<Leave>", self._schedule_drawer_close, add="+")
        drawer_header = ttk.Frame(self.drawer)
        drawer_header.pack(fill=X, pady=(0, 8))
        self._add_navigation_button(
            drawer_header, "\ue700", "Đóng điều hướng", icon_only=True, command=self._toggle_drawer
        )
        drawer_hamburger = self._nav_icon_widgets[-1][0]
        drawer_hamburger.pack_forget()
        drawer_hamburger.pack(side=LEFT)
        ttk.Label(
            drawer_header, text="ĐIỀU HƯỚNG", bootstyle="secondary", font=self._font("small")
        ).pack(side=LEFT, padx=(8, 0))

        for label, glyph, builder_name, restricted in _NAVIGATION_ITEMS:
            if restricted and not self._can_manage():
                continue
            builder = getattr(self, builder_name)
            self._add_navigation_button(
                self.sidebar,
                glyph,
                label,
                icon_only=True,
                command=lambda n=label, b=builder: self._navigate(n, b),
            )
            self._add_navigation_button(
                self.drawer,
                glyph,
                label,
                command=lambda n=label, b=builder: self._navigate(n, b),
            )

        controls = ttk.Frame(self.drawer)
        controls.pack(fill=X, side="bottom", pady=(12, 0))
        ttk.Separator(controls).pack(fill=X, pady=(0, 8))
        ttk.Checkbutton(
            controls,
            text="Chế độ tối",
            variable=self.dark_mode,
            command=self._set_appearance,
            bootstyle="round-toggle",
        ).pack(anchor="w")
        appearance = ttk.Frame(controls)
        appearance.pack(fill=X, pady=(8, 0))
        ttk.Label(appearance, text="Cỡ chữ").pack(side=LEFT)
        picker = ttk.Combobox(
            appearance,
            textvariable=self.font_scale,
            values=("Nhỏ", "Vừa", "Lớn"),
            state="readonly",
            width=9,
        )
        picker.pack(side=RIGHT)
        picker.bind("<<ComboboxSelected>>", self._set_font_scale)
        ttk.Separator(outer, orient="vertical").pack(side=LEFT, fill=Y)
        self.content = ttk.Frame(outer, padding=(8, 10))
        self.content.pack(side=LEFT, fill=BOTH, expand=True)
        self.status = tk.StringVar()
        ttk.Separator(self, orient="horizontal").pack(fill=X, side="bottom")
        ttk.Label(
            self, textvariable=self.status, padding=(12, 6), anchor="w", bootstyle="secondary"
        ).pack(fill=X, side="bottom")
        self._refresh_status()
        self._apply_ui_style()
        self._schedule_notification_worker()
        self.bind("<Escape>", self._close_drawer_from_escape, add="+")
        self.show_page("Tổng quan", self.dashboard_page)

    def _add_navigation_button(
        self, parent, glyph: str, label: str, *, command, icon_only: bool = False
    ) -> None:
        button = ttk.Button(
            parent, text="" if icon_only else label, command=command, bootstyle="link"
        )
        button.configure(compound="left")
        if icon_only:
            button.configure(padding=0)
        button.pack(fill=X, pady=1)
        self._nav_icon_widgets.append((button, glyph))
        if not icon_only:
            self._nav_buttons.setdefault(label, []).append(button)
        else:
            Tooltip(button, label)

    def _navigation_icon(self, glyph: str) -> ImageTk.PhotoImage:
        font_path = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts" / "segmdl2.ttf"
        size = max(18, self._font()[1] + 8)
        image = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        font = ImageFont.truetype(font_path, size)
        left, top, right, bottom = draw.textbbox((0, 0), glyph, font=font)
        draw.text(
            ((size * 2 - (right - left)) / 2 - left, (size * 2 - (bottom - top)) / 2 - top),
            glyph,
            font=font,
            fill=self._palette.foreground,
        )
        return ImageTk.PhotoImage(image)

    def _refresh_navigation_icons(self) -> None:
        if not hasattr(self, "_nav_icon_widgets"):
            return
        images: dict[str, ImageTk.PhotoImage] = {}
        for button, glyph in self._nav_icon_widgets:
            image = images.setdefault(glyph, self._navigation_icon(glyph))
            button.configure(image=image)
        self._navigation_icon_images = images

    def _navigate(self, name: str, builder) -> None:
        self.show_page(name, builder)
        if not self._drawer_pinned:
            self._close_drawer()

    def _open_drawer(self, *, temporary: bool = False) -> None:
        if temporary and not self._drawer_pinned:
            self._drawer_temporary = True
        self.drawer.place(x=0, y=0, width=_DRAWER_WIDTH, relheight=1)
        self.drawer.lift()

    def _close_drawer(self) -> None:
        self.drawer.place_forget()
        self._drawer_temporary = False

    def _toggle_drawer(self) -> None:
        if self.drawer.winfo_ismapped() and self._drawer_pinned:
            self._drawer_pinned = False
            self._close_drawer()
            return
        self._drawer_pinned = True
        self._drawer_temporary = False
        self._open_drawer()

    def _close_drawer_from_escape(self, _event=None) -> None:
        self._drawer_pinned = False
        self._close_drawer()

    def _schedule_drawer_close(self, _event=None) -> None:
        self.after_idle(self._close_temporary_drawer_if_outside)

    def _close_temporary_drawer_if_outside(self) -> None:
        if self._drawer_pinned or not self._drawer_temporary:
            return
        x, y = self.winfo_pointerxy()
        widget = self.winfo_containing(x, y)
        while widget:
            if widget is self.drawer:
                return
            widget = widget.master
        self._close_drawer()

    def _schedule_notification_worker(self) -> None:
        def work() -> None:
            try:
                self.store.process_notifications()
            except Exception:
                pass

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
        help_menu.add_command(
            label="Giới thiệu",
            command=lambda: self.show_page("Cài đặt & About", self.settings_page),
        )
        menu.add_cascade(label="Trợ giúp", menu=help_menu)
        self._menus = [menu, file_menu, help_menu]
        self.config(menu=menu)

    def _toggle_theme(self) -> None:
        self.dark_mode.set(not self.dark_mode.get())
        self._set_appearance()

    def _can_manage(self) -> bool:
        return bool(self.account and self.account.role_code in (RoleCode.ADMIN, RoleCode.MANAGER))

    def _change_password(self) -> None:
        if not self.account:
            return
        current = simpledialog.askstring(
            "Đổi mật khẩu", "Mật khẩu hiện tại:", show="•", parent=self
        )
        new_password = (
            simpledialog.askstring(
                "Đổi mật khẩu", "Mật khẩu mới (ít nhất 8 ký tự):", show="•", parent=self
            )
            if current is not None
            else None
        )
        if new_password is None:
            return
        try:
            self.store.change_password(self.account.id, current, new_password)
            messagebox.showinfo("Đổi mật khẩu", "Đã đổi mật khẩu thành công.", parent=self)
        except Exception as exc:
            messagebox.showerror("Đổi mật khẩu", str(exc), parent=self)

    def _refresh_status(self) -> None:
        if not self.account:
            return
        self.current_shift = self.store.current_shift(self.account.employee_id)
        ca = f"Ca #{self.current_shift.id} đang mở" if self.current_shift else "Chưa mở ca"
        self.status.set(
            f"{self.account.employee_name} • {self.account.role_name} • {ca} • MySQL: kết nối"
        )

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
        self._active_page = name
        for label, buttons in self._nav_buttons.items():
            for button in buttons:
                button.configure(bootstyle="primary" if label == name else "link")

    def _open_shift(self) -> None:
        if not self.account:
            return
        opening_cash = simpledialog.askfloat("Mở ca", "Tiền đầu ca:", minvalue=0, parent=self)
        if opening_cash is None:
            return
        self.current_shift = self.store.open_shift(self.account.employee_id, Decimal(str(opening_cash)))
        self._refresh_status()

    def _close_shift(self) -> None:
        if not self.current_shift or not self.account:
            return
        closing_cash = simpledialog.askfloat("Đóng ca", "Tiền cuối ca:", minvalue=0, parent=self)
        if closing_cash is None:
            return
        self.store.close_shift(self.current_shift.id, Decimal(str(closing_cash)), self.account.employee_id)
        self._refresh_status()
