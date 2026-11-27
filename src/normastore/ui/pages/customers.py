from __future__ import annotations

import tkinter as tk
from datetime import datetime
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X

from normastore.application.contracts import PageRequest
from normastore.ui.formatting import RENTAL_LABELS, format_datetime

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
                rows[str(customer.id)] = (customer, premium)
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

        def clicked_customer(event):
            if tree.identify_region(event.x, event.y) not in ("tree", "cell"):
                return
            return rows.get(tree.identify_row(event.y))

        def edit_customer(event):
            clicked = clicked_customer(event)
            if clicked is not None:
                self._quick_customer(None, customer=clicked[0])
                return "break"

        tree.bind("<Double-1>", edit_customer)

        def edit_premium(customer):
            try:
                current = self.store.premium_until(customer.id)
                if current is None:
                    messagebox.showinfo("Premium", "Khách hàng không có Premium đang hiệu lực.", parent=self)
                    return
                entered = simpledialog.askstring(
                    "Chỉnh hạn Premium",
                    f"Ngày hết hạn của {customer.full_name} (ngày/tháng/năm):",
                    initialvalue=f"{current:%d/%m/%Y}", parent=self,
                )
                if entered is None:
                    return
                try:
                    new_end = datetime.strptime(entered.strip(), "%d/%m/%Y").date()
                except ValueError:
                    messagebox.showerror("Premium", "Nhập ngày theo dạng DD/MM/YYYY.", parent=self)
                    return
                self.store.set_premium_end_date(customer.id, new_end, self.account.employee_id)
                refresh()
            except Exception as exc:
                messagebox.showerror("Premium", str(exc), parent=self)

        def cancel_premium(customer):
            if not messagebox.askyesno(
                "Hủy Premium",
                f"Hủy ngay Premium của {customer.full_name}? Thao tác này không hoàn tiền.",
                parent=self,
            ):
                return
            try:
                self.store.cancel_premium(customer.id, self.account.employee_id)
                refresh()
            except Exception as exc:
                messagebox.showerror("Premium", str(exc), parent=self)

        def delete_customer(customer):
            if not messagebox.askyesno(
                "Xóa khách hàng",
                f"Xóa vĩnh viễn hồ sơ của {customer.full_name} ({customer.phone})?",
                parent=self,
            ):
                return
            try:
                self.store.delete_customer(customer.id, self.account.employee_id)
                refresh()
            except Exception as exc:
                messagebox.showerror("Xóa khách hàng", str(exc), parent=self)

        menu = tk.Menu(tree, tearoff=False)

        def context_menu(event):
            clicked = clicked_customer(event)
            if clicked is None:
                return
            customer, active = clicked
            row = str(customer.id)
            tree.selection_set(row)
            tree.focus(row)
            can_manage = self._can_manage()
            premium_state = "normal" if can_manage and active else "disabled"
            menu.delete(0, tk.END)
            menu.add_command(label="Chỉnh hạn Premium", state=premium_state,
                             command=lambda: edit_premium(customer))
            menu.add_command(label="Hủy Premium", state=premium_state,
                             command=lambda: cancel_premium(customer))
            menu.add_separator()
            menu.add_command(label="Xóa khách hàng", state="normal" if can_manage else "disabled",
                             command=lambda: delete_customer(customer))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        tree.bind("<Button-3>", context_menu)

        def premium():
            ids = tree.selection()
            if not ids:
                return
            customer, _active = rows[ids[0]]
            self.show_page("Tạo phiếu", self.checkout_page)
            self.pages["Tạo phiếu"].select_customer(customer)

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

        def rental_history():
            selected = tree.selection()
            if len(selected) != 1:
                return messagebox.showinfo("Lịch sử thuê", "Hãy chọn một khách hàng.", parent=self)
            customer, _active = rows[selected[0]]
            dialog = self._dialog(f"Lịch sử thuê — {customer.full_name}", 1050, 570, modal=False)
            history = self._create_treeview(dialog, columns=("order", "created", "barcode", "due", "returned", "state"), show="tree headings")
            for column, title in (("#0", "Phim / tập"), ("order", "Mã phiếu"), ("created", "Ngày thuê"),
                                  ("barcode", "Mã đĩa"), ("due", "Hạn trả"), ("returned", "Ngày trả"), ("state", "Trạng thái")):
                history.heading(column, text=title)
            history.pack(fill=BOTH, expand=True, padx=10, pady=10)
            history_page = tk.IntVar(value=1)
            order_ids = {}

            def load_history():
                result = self.store.customer_rental_history(customer.id, PageRequest(history_page.get(), 50))
                history.delete(*history.get_children())
                order_ids.clear()
                pager_history(result)
                for entry in result.items:
                    row = history.insert("", END, text=entry.title, values=(entry.order_code, format_datetime(entry.created_at),
                        entry.barcode or "—", entry.due_date or "—", entry.returned_on or "—", RENTAL_LABELS.get(entry.state, "—")))
                    order_ids[row] = entry.order_id

            def open_order(_event=None):
                selection = history.selection()
                if not selection:
                    return
                orders_page = self.pages.get("Hóa đơn đã tạo")
                if orders_page is None:
                    orders_page = ttk.Frame(self.content)
                    self.pages["Hóa đơn đã tạo"] = orders_page
                    self.orders_page(orders_page)
                orders_page.open_order(order_ids[selection[0]])

            history.bind("<Double-1>", open_order)
            ttk.Button(dialog, text="Xem hóa đơn", command=open_order).pack(anchor="e", padx=10, pady=5)
            pager_history = self._create_pager(dialog, history_page, load_history)
            load_history()

        ttk.Button(bottom, text="Thêm khách", command=add_customer).pack(side=LEFT)
        ttk.Button(bottom, text="Lịch sử thuê", command=rental_history).pack(side=LEFT, padx=5)
        ttk.Button(bottom, text="Kích hoạt Premium", command=premium, bootstyle="warning").pack(
            side=LEFT, padx=5
        )
        button = ttk.Button(bottom, text="Đề cử phim", command=recommend, bootstyle="primary")
        button.pack(side=LEFT, padx=5)
        pager = self._create_pager(page, page_number, refresh)
        search_timer = {}
        search.trace_add("write", lambda *_: self._debounce(search_timer, lambda: (page_number.set(1), refresh())))
        page.refresh = refresh
