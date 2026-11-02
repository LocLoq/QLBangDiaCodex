from __future__ import annotations

import tkinter as tk
from datetime import date
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X

from normastore.application.services import (
    PageRequest,
    PaymentInput,
    SortSpec,
)
from normastore.domain.enums import (
    CopyCondition,
    PaymentMethod,
    ReturnOutcome,
)
from normastore.ui.formatting import vnd


class ReturnsPageMixin:
    def returns_page(self, page) -> None:
        self._heading(page, "Trả đĩa & phạt", "Chọn dòng thuê để trả từng phần")
        tree = self._create_treeview(
            page, columns=("customer", "due", "status"), show="tree headings", selectmode="extended"
        )
        tree.heading("#0", text="Phim / bản đĩa")
        tree.heading("customer", text="Khách")
        tree.heading("due", text="Hạn trả")
        tree.heading("status", text="Trạng thái")
        tree.pack(fill=BOTH, expand=True)
        outcome = tk.StringVar(value="NORMAL")
        footer = ttk.Frame(page)
        footer.pack(fill=X, pady=7)
        ttk.Combobox(
            footer,
            textvariable=outcome,
            values=[x.value for x in ReturnOutcome],
            width=18,
            state="readonly",
        ).pack(side=LEFT)
        note = ttk.Entry(footer, width=45)
        note.pack(side=LEFT, padx=6)
        rows = {}
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "due", "descending": False}

        def refresh():
            tree.delete(*tree.get_children())
            rows.clear()
            result = self.call(
                lambda s: s.query_active_rentals(
                    PageRequest(page_number.get(), 50),
                    SortSpec(str(sort_state["field"]), bool(sort_state["descending"])),
                )
            )
            pager_update(result)
            for rental in result.items:
                rows[str(rental.term_id)] = rental
                status = "Quá hạn" if rental.due_date < date.today() else "Đang thuê"
                tree.insert(
                    "",
                    END,
                    iid=str(rental.term_id),
                    text=f"{rental.title} — {rental.barcode}",
                    values=(rental.customer_name, rental.due_date, status),
                )

        def submit():
            selection = tree.selection()
            if not selection:
                return
            selected = [rows[item] for item in selection]
            customer_ids = {rental.customer_id for rental in selected}
            if len(customer_ids) != 1:
                return messagebox.showerror(
                    "Trả đĩa", "Mỗi phiếu trả chỉ áp dụng cho một khách hàng.", parent=self
                )
            try:
                paid = simpledialog.askstring(
                    "Trả đĩa",
                    "Thu thêm sau cấn cọc (nhập 0 nếu khách còn nợ):",
                    initialvalue="0",
                    parent=self,
                )
                if paid is None:
                    return
                method = (
                    self._choose_payment_method("Trả đĩa", self)
                    if Decimal(paid)
                    else PaymentMethod.CASH
                )
                if method is None:
                    return
                balance = self.call(
                    lambda s: s.return_rentals(
                        self.account.employee_id,
                        selected[0].customer_id,
                        [
                            (rental.term_id, ReturnOutcome(outcome.get()), note.get())
                            for rental in selected
                        ],
                        PaymentInput(method, Decimal(paid)),
                    ),
                    True,
                )
                messagebox.showinfo(
                    "Trả đĩa", f"Số dư sau khi cấn cọc: {vnd(balance)}", parent=self
                )
                refresh()
            except Exception as exc:
                messagebox.showerror("Trả đĩa", str(exc), parent=self)

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
                messagebox.showinfo(
                    "Gia hạn", "Đã gia hạn thêm 3 ngày và ghi nhận phí thuê.", parent=self
                )
                refresh()
            except Exception as exc:
                messagebox.showerror("Gia hạn", str(exc), parent=self)

        def convert_to_sale():
            rental = selected_one()
            if not rental:
                return
            amount = simpledialog.askstring(
                "Chuyển thành mua", "Số tiền khách thanh toán thêm:", initialvalue="0", parent=self
            )
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
                messagebox.showinfo(
                    "Chuyển thành mua", f"Đã tạo phiếu bán {order.code} và cấn cọc.", parent=self
                )
                refresh()
            except Exception as exc:
                messagebox.showerror("Chuyển thành mua", str(exc), parent=self)

        def open_sale_returns():
            dialog = tb.Toplevel(self)
            dialog.title("Trả hàng bán trong 7 ngày")
            dialog.geometry("760x360")
            dialog.transient(self)
            frame = ttk.Frame(dialog, padding=12)
            frame.pack(fill=BOTH, expand=True)
            sale_tree = self._create_treeview(
                frame, columns=("customer", "title", "barcode", "sold", "expires"), show="headings"
            )
            for key, title in [
                ("customer", "Khách hàng"),
                ("title", "Phim/tập"),
                ("barcode", "Barcode"),
                ("sold", "Ngày bán"),
                ("expires", "Hạn trả"),
            ]:
                sale_tree.heading(key, text=title)
            sale_tree.pack(fill=BOTH, expand=True)
            sales = {}

            def load_sales():
                sale_tree.delete(*sale_tree.get_children())
                sales.clear()
                for sale in self.call(lambda s: s.returnable_sales()):
                    sales[str(sale.line_id)] = sale
                    sale_tree.insert(
                        "",
                        END,
                        iid=str(sale.line_id),
                        values=(
                            sale.customer_name,
                            sale.title,
                            sale.barcode,
                            sale.sold_on,
                            sale.expires_on,
                        ),
                    )

            def return_selected_sale():
                selection = sale_tree.selection()
                if len(selection) != 1:
                    return messagebox.showinfo(
                        "Trả hàng bán", "Hãy chọn một dòng bán.", parent=dialog
                    )
                damaged = messagebox.askyesno(
                    "Trả hàng bán", "Đĩa hoàn có hư hỏng không?", parent=dialog
                )
                condition = CopyCondition.DAMAGED if damaged else CopyCondition.GOOD
                deduction = Decimal("0")
                note = ""
                if damaged:
                    if not self._can_manage():
                        return messagebox.showerror(
                            "Trả hàng bán",
                            "Chỉ Quản lý mới được quyết định hàng hoàn hỏng.",
                            parent=dialog,
                        )
                    entered = simpledialog.askstring(
                        "Khấu trừ", "Số tiền khấu trừ (VND):", initialvalue="0", parent=dialog
                    )
                    if entered is None:
                        return
                    try:
                        deduction = Decimal(entered.replace(".", "").replace(",", "").strip())
                    except Exception:
                        return messagebox.showerror(
                            "Trả hàng bán", "Mức khấu trừ không hợp lệ.", parent=dialog
                        )
                    note = (
                        simpledialog.askstring("Ghi chú", "Lý do hư hỏng/khấu trừ:", parent=dialog)
                        or ""
                    )
                try:
                    refund = self.call(
                        lambda s: s.return_sale(
                            int(selection[0]),
                            self.account.employee_id,
                            condition=condition,
                            deduction=deduction,
                            note=note,
                        ),
                        True,
                    )
                    messagebox.showinfo(
                        "Trả hàng bán",
                        f"Đã hoàn {vnd(refund)}. Đĩa chuyển sang chờ kiểm tra.",
                        parent=dialog,
                    )
                    load_sales()
                except Exception as exc:
                    messagebox.showerror("Trả hàng bán", str(exc), parent=dialog)

            actions = ttk.Frame(frame)
            actions.pack(fill=X, pady=(8, 0))
            ttk.Button(
                actions, text="Xác nhận hoàn", command=return_selected_sale, bootstyle="warning"
            ).pack(side=RIGHT)
            load_sales()

        ttk.Button(footer, text="Gia hạn 3 ngày", command=extend, bootstyle="secondary").pack(
            side=LEFT, padx=(8, 0)
        )
        ttk.Button(
            footer, text="Chuyển thành mua", command=convert_to_sale, bootstyle="warning"
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            footer, text="Trả hàng bán", command=open_sale_returns, bootstyle="secondary"
        ).pack(side=LEFT)
        ttk.Button(footer, text="Xác nhận trả", command=submit, bootstyle="success").pack(
            side=RIGHT
        )
        pager_update = self._create_pager(page, page_number, refresh)
        self._install_sortable_headings(
            tree,
            {"#0": "Phim / bản đĩa", "customer": "Khách", "due": "Hạn trả", "status": "Trạng thái"},
            sort_state,
            lambda: (page_number.set(1), refresh()),
        )
        page.refresh = refresh
