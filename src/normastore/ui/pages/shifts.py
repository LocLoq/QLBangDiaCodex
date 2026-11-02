from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, X

from normastore.domain.enums import RoleCode


class ShiftsPageMixin:
    def shifts_page(self, page) -> None:
        self._heading(
            page, "Nhân viên & ca làm", "Mỗi giao dịch được gắn nhân viên và ca thực hiện"
        )
        info = tk.StringVar()
        ttk.Label(page, textvariable=info, font=("Segoe UI", 13)).pack(anchor="w", pady=12)
        actions = ttk.Frame(page)
        actions.pack(fill=X)
        employees_tree = self._create_treeview(
            page, columns=("phone", "username", "role", "state"), show="tree headings", height=10
        )
        employees_tree.heading("#0", text="Nhân viên")
        employees_tree.heading("phone", text="Điện thoại")
        employees_tree.heading("username", text="Tài khoản")
        employees_tree.heading("role", text="Vai trò")
        employees_tree.heading("state", text="Trạng thái")
        employees_tree.pack(fill=BOTH, expand=True, pady=(12, 0))

        def refresh():
            shift = self.call(lambda s: s.current_shift(self.account.employee_id))
            self.current_shift = shift
            info.set(
                f"{self.account.employee.full_name}: "
                + (f"đang mở ca #{shift.id} từ {shift.opened_at:%H:%M}" if shift else "chưa mở ca")
            )
            self._refresh_status()
            employees_tree.delete(*employees_tree.get_children())
            for employee in self.call(lambda s: s.list_employees()):
                employees_tree.insert(
                    "",
                    END,
                    iid=str(employee.employee_id),
                    text=employee.full_name,
                    values=(
                        employee.phone or "—",
                        employee.username or "Chưa có",
                        employee.role_name or "—",
                        "Đang làm" if employee.active else "Ngưng",
                    ),
                )

        def add_employee():
            full_name = simpledialog.askstring("Nhân viên", "Họ tên:", parent=self)
            phone = (
                simpledialog.askstring("Nhân viên", "Điện thoại:", parent=self)
                if full_name
                else None
            )
            username = (
                simpledialog.askstring("Nhân viên", "Tên đăng nhập:", parent=self)
                if phone is not None
                else None
            )
            role = (
                simpledialog.askstring(
                    "Nhân viên",
                    "Vai trò: ADMIN, MANAGER hoặc STAFF:",
                    initialvalue="STAFF",
                    parent=self,
                )
                if username
                else None
            )
            password = (
                simpledialog.askstring(
                    "Nhân viên", "Mật khẩu tạm (ít nhất 8 ký tự):", show="•", parent=self
                )
                if role
                else None
            )
            if not password:
                return
            try:
                self.call(
                    lambda s: s.create_employee_account(
                        full_name,
                        phone or "",
                        username,
                        RoleCode(role.upper()),
                        password,
                        self.account.employee_id,
                    ),
                    True,
                )
                refresh()
            except Exception as exc:
                messagebox.showerror("Nhân viên", str(exc), parent=self)

        ttk.Button(actions, text="Mở ca", command=self._open_shift, bootstyle="success").pack(
            side=LEFT, padx=3
        )
        ttk.Button(actions, text="Đóng ca", command=self._close_shift, bootstyle="danger").pack(
            side=LEFT, padx=3
        )
        ttk.Button(
            actions,
            text="Thêm nhân viên",
            command=add_employee,
            bootstyle="primary",
            state="normal" if self._can_manage() else "disabled",
        ).pack(side=LEFT, padx=3)
        page.refresh = refresh
