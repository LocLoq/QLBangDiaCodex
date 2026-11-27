from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, X

from normastore.domain.enums import RoleCode


class EmployeesPageMixin:
    def employees_page(self, page) -> None:
        self._heading(
            page, "Nhân viên", "Quản lý nhân viên và tài khoản"
        )
        info = tk.StringVar()
        ttk.Label(page, textvariable=info, style="Norma.Section.TLabel").pack(anchor="w", pady=(0, 8))
        actions = ttk.Frame(page)
        actions.pack(fill=X)
        employees_tree = self._create_treeview(
            page, columns=("phone", "username", "role", "state"), show="tree headings", height=10
        )
        employees_tree.heading("#0", text="Nhân viên")
        employees_tree.column("#0", anchor="w")
        employees_tree.heading("phone", text="Điện thoại")
        employees_tree.heading("username", text="Tài khoản")
        employees_tree.heading("role", text="Vai trò")
        employees_tree.heading("state", text="Trạng thái")
        employees_tree.pack(fill=BOTH, expand=True, pady=(12, 0))

        def refresh():
            info.set(f"Đang đăng nhập: {self.account.employee_name}")
            self._refresh_status()
            employees_tree.delete(*employees_tree.get_children())
            for employee in self.store.list_employees():
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
            role = None
            if username:
                dialog = self._dialog("Chọn vai trò", 420, 190)
                role_values = {"Nhân viên": RoleCode.STAFF, "Quản lý": RoleCode.MANAGER,
                               "Quản trị viên": RoleCode.ADMIN}
                role_name = tk.StringVar(value="Nhân viên")
                ttk.Label(dialog, text="Vai trò", padding=12).pack(anchor="w")
                ttk.Combobox(dialog, textvariable=role_name, values=tuple(role_values), state="readonly").pack(fill=X, padx=12)
                selected = []
                def confirm():
                    selected.append(role_values[role_name.get()])
                    dialog.destroy()
                ttk.Button(dialog, text="Xác nhận", command=confirm, bootstyle="primary").pack(pady=12)
                self.wait_window(dialog)
                role = selected[0] if selected else None
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
                self.store.create_employee_account(full_name, phone or '', username, role, password, self.account.employee_id)
                refresh()
            except Exception as exc:
                messagebox.showerror("Nhân viên", str(exc), parent=self)

        ttk.Button(
            actions,
            text="Thêm nhân viên",
            command=add_employee,
            bootstyle="primary",
            state="normal" if self._can_manage() else "disabled",
        ).pack(side=LEFT, padx=3)
        page.refresh = refresh
