from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

import keyring
from ttkbootstrap.constants import BOTH, LEFT, RIGHT, X, Y

from normastore.domain.enums import RoleCode
from normastore.infrastructure.external import MockSmsSender, SmtpSender
from normastore.jobs import process_notification_outbox
from normastore.ui.tooltips import Tooltip


class ShellMixin:
    def _login(self) -> None:
        # Keep the action area outside the expanding form.  At 125–150% DPI a
        # 330px client area is too short and used to clip the submit button.
        login = self._dialog("Đăng nhập NormaStore", 440, 410)
        login.minsize(400, 390)
        login.resizable(False, False)
        frame = ttk.Frame(login, padding=(28, 24, 28, 12))
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
        self.sidebar = ttk.Frame(outer, padding=(12, 14), width=230)
        self.sidebar.pack(side=LEFT, fill=Y)
        self.sidebar.pack_propagate(False)
        ttk.Label(self.sidebar, text="ĐIỀU HƯỚNG", bootstyle="secondary", font=self._font("small")).pack(anchor="w", pady=(0, 8))
        self.pages = {}
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
        picker = ttk.Combobox(appearance, textvariable=self.font_scale, values=("Nhỏ", "Vừa", "Lớn"), state="readonly", width=9)
        picker.pack(side=RIGHT)
        picker.bind("<<ComboboxSelected>>", self._set_font_scale)
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
                        smtp = SmtpSender(self.settings.smtp_host, self.settings.smtp_port, self.settings.smtp_username, password, self.settings.smtp_starttls)
                        email_sender = lambda recipient, body: smtp.send(self.settings.smtp_from, recipient, "Nhắc hạn trả đĩa NormaStore", body)
                process_notification_outbox(session, send_email=email_sender, send_sms=lambda phone, body: MockSmsSender().send(phone, body))
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
        file_menu.add_separator(); file_menu.add_command(label="Thoát", command=self._close)
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
        self.current_shift = self.call(lambda s: s.current_shift(self.account.employee_id))
        ca = f"Ca #{self.current_shift.id} đang mở" if self.current_shift else "Chưa mở ca"
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

    def _open_shift(self) -> None:
        if not self.account:
            return
        opening_cash = simpledialog.askfloat("Mở ca", "Tiền đầu ca:", minvalue=0, parent=self)
        if opening_cash is None:
            return
        self.current_shift = self.call(lambda s: s.open_shift(self.account.employee_id, Decimal(str(opening_cash)), self.account.id), True)
        self._refresh_status()

    def _close_shift(self) -> None:
        if not self.current_shift or not self.account:
            return
        closing_cash = simpledialog.askfloat("Đóng ca", "Tiền cuối ca:", minvalue=0, parent=self)
        if closing_cash is None:
            return
        self.call(lambda s: s.close_shift(self.current_shift.id, Decimal(str(closing_cash)), self.account.id), True)
        self._refresh_status()
