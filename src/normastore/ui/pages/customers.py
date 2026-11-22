from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X

from normastore.application.contracts import PageRequest

class CustomersPageMixin:
    def customers_page(self, page) -> None:
        bar = self._heading(
            page, "Khách hàng & Premium", "Quản lý khách hàng và hội viên"
        )
        search = tk.StringVar()
        ttk.Entry(bar, textvariable=search, width=35).pack(side=RIGHT)
        ttk.Label(bar, text="Tìm tên / SĐT:").pack(side=RIGHT, padx=(0, 4))
        tree = self._create_treeview(
            page, columns=("phone", "email", "premium"), show="tree headings"
        )
        tree.heading("#0", text="Khách hàng")
        tree.heading("phone", text="Số điện thoại")
        tree.heading("email", text="Email")
        tree.heading("premium", text="Premium")
        tree.pack(fill=BOTH, expand=True)
        bottom = ttk.Frame(page)
        bottom.pack(fill=X, pady=6)
        rows = {}
        page_number = tk.IntVar(value=1)

        def refresh():
            tree.delete(*tree.get_children())
            rows.clear()
            result = self.store.query_customers_with_premium(search.get(), PageRequest(page_number.get(), 50))
            pager(result)
            for customer, premium in result.items:
                rows[str(customer.id)] = customer
                tree.insert(
                    "",
                    END,
                    iid=str(customer.id),
                    text=customer.full_name,
                    values=(
                        customer.phone,
                        customer.email or "—",
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
        button = ttk.Button(bottom, text="Đề cử phim", command=recommend, bootstyle="primary")
        button.pack(side=LEFT, padx=5)
        pager = self._create_pager(page, page_number, refresh)
        search_timer = {}
        search.trace_add("write", lambda *_: self._debounce(search_timer, lambda: (page_number.set(1), refresh())))
        page.refresh = refresh
