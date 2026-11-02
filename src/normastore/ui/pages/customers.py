from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X


class CustomersPageMixin:
    def customers_page(self, page) -> None:
        bar = self._heading(
            page, "Khách hàng & Premium", "Điểm uy tín ảnh hưởng cọc và hạn mức thuê"
        )
        search = tk.StringVar()
        ttk.Entry(bar, textvariable=search, width=35).pack(side=RIGHT)
        ttk.Label(bar, text="Tìm tên / SĐT:").pack(side=RIGHT, padx=(0, 4))
        tree = self._create_treeview(
            page, columns=("phone", "email", "trust", "premium"), show="tree headings"
        )
        tree.heading("#0", text="Khách hàng")
        tree.heading("phone", text="Số điện thoại")
        tree.heading("email", text="Email")
        tree.heading("trust", text="Uy tín")
        tree.heading("premium", text="Premium")
        tree.pack(fill=BOTH, expand=True)
        bottom = ttk.Frame(page)
        bottom.pack(fill=X, pady=6)
        rows = {}

        def refresh():
            tree.delete(*tree.get_children())
            rows.clear()
            for customer in self.store.list_customers(search.get()):
                rows[str(customer.id)] = customer
                premium = self.store.premium_active(customer.id)
                tree.insert(
                    "",
                    END,
                    iid=str(customer.id),
                    text=customer.full_name,
                    values=(
                        customer.phone,
                        customer.email or "—",
                        customer.reputation_score,
                        "Đang hiệu lực" if premium else "Thường",
                    ),
                )

        def add_customer():
            self._quick_customer(None)

        def premium():
            ids = tree.selection()
            if not ids:
                return
            days = simpledialog.askinteger(
                "Premium", "Kỳ hạn 30, 90 hoặc 365 ngày:", initialvalue=30, parent=self
            )
            if days:
                method = self._choose_payment_method("Premium", self)
                if method is None:
                    return
                try:
                    self.store.activate_premium(int(ids[0]), days, self.account.employee_id, method)
                    refresh()
                except Exception as exc:
                    messagebox.showerror("Premium", str(exc), parent=self)

        def adjust_reputation():
            ids = tree.selection()
            if len(ids) != 1:
                return messagebox.showinfo("Uy tín", "Hãy chọn một khách hàng.", parent=self)
            delta = simpledialog.askinteger(
                "Uy tín", "Điều chỉnh điểm (ví dụ 5 hoặc -10):", parent=self
            )
            reason = (
                simpledialog.askstring("Uy tín", "Lý do bắt buộc:", parent=self) if delta else None
            )
            if not reason:
                return
            try:
                self.store.adjust_reputation(int(ids[0]), delta, reason, self.account.employee_id)
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
                text = (
                    "\n".join(f"• {item.title} — {item.reason} ({item.source})" for item in results)
                    or "Chưa có phim phù hợp còn hàng."
                )
                messagebox.showinfo("Đề cử cho khách hàng", text, parent=self)

            def failed(_exc):
                button.configure(state="normal", text="Đề cử phim")
                messagebox.showerror("Đề cử", "Không thể tạo đề cử lúc này.", parent=self)

            self._run_async(lambda: self.store.customer_recommendations(int(ids[0])), done, failed)

        ttk.Button(bottom, text="Thêm khách", command=add_customer).pack(side=LEFT)
        ttk.Button(bottom, text="Kích hoạt Premium", command=premium, bootstyle="warning").pack(
            side=LEFT, padx=5
        )
        ttk.Button(
            bottom,
            text="Điều chỉnh uy tín",
            command=adjust_reputation,
            bootstyle="secondary",
            state="normal" if self._can_manage() else "disabled",
        ).pack(side=LEFT, padx=5)
        button = ttk.Button(bottom, text="Đề cử phim", command=recommend, bootstyle="primary")
        button.pack(side=LEFT, padx=5)
        search.trace_add("write", lambda *_: self.after(250, refresh))
        page.refresh = refresh
