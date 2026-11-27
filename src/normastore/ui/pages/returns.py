from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X
from ttkbootstrap.widgets.scrolled import ScrolledFrame

from normastore.application.contracts import PageRequest, PaymentInput, RentalReturnInput, SortSpec
from normastore.domain.enums import (
    CopyCondition,
    CopyStatus,
    PaymentMethod,
    ReturnOutcome,
)
from normastore.domain.policies import damage_fee, late_fee
from normastore.ui.formatting import RETURN_LABELS, vnd
from normastore.ui.pages.inventory import CONDITION_LABELS, STATUS_LABELS


def _return_vnd(amount: Decimal) -> str:
    if amount == amount.to_integral_value():
        return vnd(amount)
    return f"{amount:,.2f} đ".translate(str.maketrans(",.", ".,"))


class ReturnsPageMixin:
    def returns_page(self, page) -> None:
        self._heading(page, "Đĩa đã được thuê", "Chọn dòng thuê để trả từng phần")
        search_row = ttk.Frame(page)
        search_row.pack(fill=X, pady=(0, 6))
        ttk.Label(search_row, text="Tên khách hàng:").pack(side=LEFT)
        customer_search = tk.StringVar()
        ttk.Entry(search_row, textvariable=customer_search, width=30).pack(side=LEFT, padx=6)
        tree = self._create_treeview(
            page, columns=("customer", "due", "status", "location"), show="tree headings", selectmode="extended"
        )
        tree.heading("#0", text="Phim / bản đĩa")
        tree.heading("customer", text="Khách")
        tree.heading("due", text="Hạn trả")
        tree.heading("status", text="Trạng thái")
        tree.heading("location", text="Dãy / Kệ / Ngăn")
        tree.column("#0", anchor="w")
        tree.pack(fill=BOTH, expand=True)
        footer = ttk.Frame(page)
        footer.pack(fill=X, pady=7)
        rows = {}
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "due", "descending": False}

        def refresh():
            tree.delete(*tree.get_children())
            rows.clear()
            result = self.store.query_active_rentals(PageRequest(page_number.get(), 50), SortSpec(str(sort_state['field']), bool(sort_state['descending'])), customer_search.get())
            pager_update(result)
            for rental in result.items:
                rows[str(rental.term_id)] = rental
                status = "Quá hạn" if rental.due_date < date.today() else "Đang thuê"
                tree.insert(
                    "",
                    END,
                    iid=str(rental.term_id),
                    text=f"{rental.title} — {rental.barcode}",
                    values=(rental.customer_name, rental.due_date, status, " / ".join(value or "—" for value in (rental.aisle, rental.rack, rental.compartment))),
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
            dialog = self._dialog("Trả đĩa", 900, 640)
            footer_dialog = ttk.Frame(dialog, padding=10)
            footer_dialog.pack(side="bottom", fill=X)
            body = ScrolledFrame(dialog, padding=10, autohide=True)
            body.pack(fill=BOTH, expand=True)
            returned_on = date.today()
            unpaid_orders = {
                rental.order_code: rental.order_balance_due
                for rental in selected if rental.order_balance_due > 0
            }
            if unpaid_orders:
                ttk.Label(body, text="Còn thiếu lúc lập phiếu").pack(anchor="w", pady=(0, 4))
                for code, unpaid in unpaid_orders.items():
                    ttk.Label(body, text=f"{code}: {_return_vnd(unpaid)}").pack(anchor="w")
            inputs = []
            damage_outcomes = (ReturnOutcome.LIGHT_DAMAGE, ReturnOutcome.HEAVY_DAMAGE)
            allowed_statuses = (CopyStatus.AVAILABLE, CopyStatus.INSPECTION, CopyStatus.REPAIR, CopyStatus.RETIRED)
            for rental in selected:
                box = ttk.Labelframe(body, text=f"{rental.title} — {rental.barcode}", padding=8)
                box.pack(fill=X, pady=4)
                result = tk.StringVar(value="Bình thường")
                condition = tk.StringVar(value=CONDITION_LABELS[rental.condition])
                percent = tk.StringVar(value=str(rental.condition_percent))
                status = tk.StringVar(value=STATUS_LABELS[CopyStatus.AVAILABLE])
                note = tk.StringVar()
                controls = ttk.Frame(box)
                controls.pack(fill=X)
                for label, variable, choices in (("Kết quả", result, tuple(RETURN_LABELS)),
                        ("Hiện trạng", condition, tuple(CONDITION_LABELS.values())),
                        ("Trạng thái kho", status, tuple(STATUS_LABELS[x] for x in allowed_statuses))):
                    ttk.Label(controls, text=label).pack(side=LEFT, padx=(4, 2))
                    widget = ttk.Combobox(controls, textvariable=variable, values=choices, state="readonly", width=15)
                    widget.pack(side=LEFT, padx=2, fill=X, expand=True)
                    if variable is status:
                        status_control = widget
                details = ttk.Frame(box)
                details.pack(fill=X, pady=(5, 0))
                ttk.Label(details, text="Tình trạng %").pack(side=LEFT)
                ttk.Entry(details, textvariable=percent, width=8).pack(side=LEFT, padx=5)
                ttk.Label(details, text="Ghi chú").pack(side=LEFT)
                ttk.Entry(details, textvariable=note).pack(side=LEFT, fill=X, expand=True, padx=5)
                damage_text = tk.StringVar()
                damage_row = ttk.Frame(box)
                ttk.Label(damage_row, text="Tiền phạt hư đĩa (đ):").pack(side=LEFT)
                ttk.Entry(damage_row, textvariable=damage_text, width=16).pack(side=LEFT, padx=5)
                ttk.Label(damage_row, text="Để trống để dùng mức gợi ý.").pack(side=LEFT)
                fee_text = tk.StringVar()
                fee_label = ttk.Label(box, textvariable=fee_text)
                fee_label.pack(anchor="w", pady=(5, 0))
                def outcome_changed(*_args, result=result, condition=condition, percent=percent,
                                    status=status, status_control=status_control, rental=rental,
                                    damage_row=damage_row, damage_text=damage_text, fee_label=fee_label):
                    value = RETURN_LABELS[result.get()]
                    if value == ReturnOutcome.LOST:
                        status_control.configure(values=(STATUS_LABELS[CopyStatus.LOST],))
                        status.set(STATUS_LABELS[CopyStatus.LOST])
                    else:
                        status_control.configure(values=tuple(STATUS_LABELS[x] for x in allowed_statuses))
                        status.set(STATUS_LABELS[CopyStatus.REPAIR if value != ReturnOutcome.NORMAL else CopyStatus.AVAILABLE])
                    damaged = value in damage_outcomes
                    condition.set(CONDITION_LABELS[CopyCondition.DAMAGED if damaged else rental.condition])
                    percent.set("0" if damaged else str(rental.condition_percent))
                    if damaged:
                        damage_row.pack(before=fee_label, fill=X, pady=(5, 0))
                    else:
                        damage_row.pack_forget()
                    damage_text.set("")
                result.trace_add("write", outcome_changed)
                inputs.append((rental, result, condition, percent, status, note, damage_text, fee_text))

            summary = tk.StringVar()
            ttk.Label(body, textvariable=summary, justify=LEFT).pack(anchor="w", pady=8)
            payment_text = tk.StringVar(value="0")
            payment_row = ttk.Frame(body)
            payment_row.pack(fill=X, pady=4)
            ttk.Label(payment_row, text="Thu thêm sau cấn cọc:").pack(side=LEFT)
            ttk.Entry(payment_row, textvariable=payment_text, width=18).pack(side=LEFT, padx=5)
            remaining = tk.StringVar()
            ttk.Label(body, textvariable=remaining).pack(anchor="w")
            zero = Decimal("0")
            amount_due = None

            def entered_damage(variable):
                entered = variable.get().strip()
                return Decimal(entered) if entered else None

            def update_remaining(*_args):
                if amount_due is None:
                    remaining.set("")
                    return
                try:
                    paid = Decimal(payment_text.get().strip())
                    if not paid.is_finite() or not 0 <= paid <= amount_due:
                        raise ValueError
                except (InvalidOperation, ValueError):
                    remaining.set("Nhập số tiền nhận từ 0 đến số cần thu thêm.")
                    return
                remaining.set(f"Còn thiếu tiền phạt: {_return_vnd(amount_due - paid)}")

            def update_totals(*_args):
                nonlocal amount_due
                charges = total_deposit = zero
                invalid_damage = False
                for rental, result, _, _, _, _, damage_text, label in inputs:
                    days = max(0, (returned_on - rental.due_date).days)
                    late = late_fee(rental.due_date, returned_on, rental.late_daily_rate)
                    deposit = rental.deposit_paid
                    try:
                        damage = damage_fee(
                            rental.replacement_value, RETURN_LABELS[result.get()], entered_damage(damage_text)
                        )
                    except (InvalidOperation, ValueError):
                        label.set("Tiền phạt hư đĩa phải là số nguyên không âm và dưới 1.000 tỷ đồng.")
                        invalid_damage = True
                        continue
                    charges += late + damage
                    total_deposit += deposit
                    label.set(f"Trễ {days} ngày • Phạt trễ: {_return_vnd(late)} • "
                              f"Phạt hư/mất: {_return_vnd(damage)} • Cọc: {_return_vnd(deposit)}")
                if invalid_damage:
                    amount_due = None
                    summary.set("Hãy sửa số tiền phạt hư đĩa.")
                    payment_text.set("")
                    return
                amount_due = max(charges - total_deposit, zero)
                summary.set(f"Cọc đã thu: {_return_vnd(total_deposit)}\nTổng tiền phạt: {_return_vnd(charges)}\n"
                            f"Cọc cấn phạt: {_return_vnd(min(total_deposit, charges))}\n"
                            f"Hoàn khách: {_return_vnd(max(total_deposit - charges, zero))}\n"
                            f"Cần thu thêm: {_return_vnd(amount_due)}")
                payment_text.set(format(amount_due, "f"))

            for _, _, _, _, _, _, damage_text, _ in inputs:
                damage_text.trace_add("write", update_totals)
            payment_text.trace_add("write", update_remaining)
            update_totals()

            def confirm():
                try:
                    if amount_due is None:
                        raise ValueError("Hãy sửa số tiền phạt hư đĩa.")
                    entries = [
                        RentalReturnInput(
                            rental.term_id, RETURN_LABELS[result.get()], note.get(),
                            next(key for key, label in CONDITION_LABELS.items() if label == condition.get()),
                            Decimal(percent.get().replace(",", ".")),
                            next(key for key, label in STATUS_LABELS.items() if label == status.get()),
                            damage_charge=entered_damage(damage_text),
                        )
                        for rental, result, condition, percent, status, note, damage_text, _ in inputs
                    ]
                    try:
                        amount = Decimal(payment_text.get().strip())
                    except InvalidOperation as exc:
                        raise ValueError("Khoản thu thêm không hợp lệ.") from exc
                    if not amount.is_finite() or not zero <= amount <= amount_due:
                        raise ValueError("Nhập số tiền nhận từ 0 đến số cần thu thêm.")
                    method = self._choose_payment_method("Trả đĩa", dialog) if amount else PaymentMethod.CASH
                    if method is None:
                        return
                    balance = self.store.return_rentals(
                        self.account.employee_id, selected[0].customer_id, entries,
                        PaymentInput(method, amount), today=returned_on,
                    )
                    messagebox.showinfo(
                        "Trả đĩa",
                        f"Hoàn khách: {_return_vnd(max(-balance, zero))}\n"
                        f"Đã thu thêm: {_return_vnd(amount)}\n"
                        f"Còn thiếu tiền phạt: {_return_vnd(max(balance - amount, zero))}",
                        parent=self,
                    )
                    dialog.destroy()
                    refresh()
                except Exception as exc:
                    messagebox.showerror("Trả đĩa", str(exc), parent=dialog)
            ttk.Button(footer_dialog, text="Trả đĩa", command=confirm, bootstyle="success").pack(side=RIGHT)

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
            dialog = self._dialog("Gia hạn thuê", 490, 360)
            form = ttk.Frame(dialog, padding=16)
            form.pack(fill=BOTH, expand=True)
            ttk.Label(form, text=f"{rental.title} — {rental.barcode}").pack(anchor="w")
            ttk.Label(form, text=f"Hạn hiện tại: {rental.due_date:%d/%m/%Y}").pack(anchor="w", pady=4)
            late = max(0, (date.today() - rental.due_date).days) * rental.late_daily_rate
            ttk.Label(form, text=f"Phạt quá hạn: {vnd(late)}").pack(anchor="w")
            ttk.Label(form, text="Ngày trả mới:").pack(anchor="w", pady=(8, 0))
            due = tb.DateEntry(form, dateformat="%d/%m/%Y", startdate=max(date.today(), rental.due_date) + timedelta(days=3))
            due.pack(fill=X)
            ttk.Label(form, text="Phí gia hạn thỏa thuận:").pack(anchor="w", pady=(8, 0))
            fee = tk.StringVar()
            ttk.Entry(form, textvariable=fee).pack(fill=X)
            def confirm_extension():
                try:
                    new_due = datetime.strptime(due.entry.get().strip(), "%d/%m/%Y").date()
                    amount = Decimal(fee.get().strip().replace(",", ""))
                    method = self._choose_payment_method("Gia hạn", dialog) if amount + late else PaymentMethod.CASH
                    if method is None:
                        return
                    if not messagebox.askyesno("Gia hạn", f"Phí gia hạn: {vnd(amount)}\nPhạt quá hạn: {vnd(late)}\nTổng thu: {vnd(amount + late)}", parent=dialog):
                        return
                    self.store.extend_rental(rental.term_id, self.account.employee_id, new_due, amount, method)
                    dialog.destroy()
                    messagebox.showinfo("Gia hạn", "Đã ghi nhận gia hạn.", parent=self)
                    refresh()
                except Exception as exc:
                    messagebox.showerror("Gia hạn", str(exc), parent=dialog)
            ttk.Button(form, text="Xác nhận gia hạn", command=confirm_extension, bootstyle="primary").pack(anchor="e", pady=12)

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
                order = self.store.rental_to_sale(rental.term_id, self.account.employee_id, PaymentInput(method, Decimal(amount)))
                receipt = self.store.order_receipt(order.id)
                excess = -sum((payment.amount for payment in receipt.payments if payment.category == "DEPOSIT_REFUND"), Decimal("0"))
                details = f"Đã tạo phiếu bán {order.code}.\nCọc đã cấn: {vnd(receipt.applied_deposit)}.\nCòn thiếu: {vnd(receipt.balance_due)}."
                if excess:
                    details += f"\nCần hoàn phần cọc vượt giá bán: {vnd(excess)}."
                messagebox.showinfo(
                    "Chuyển thành mua", details, parent=self
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
                ("barcode", "Mã vạch"),
                ("sold", "Ngày bán"),
                ("expires", "Hạn trả"),
            ]:
                sale_tree.heading(key, text=title)
            sale_tree.pack(fill=BOTH, expand=True)
            sales = {}

            def load_sales():
                sale_tree.delete(*sale_tree.get_children())
                sales.clear()
                for sale in self.store.returnable_sales():
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
                    refund = self.store.return_sale(int(selection[0]), self.account.employee_id, condition=condition, deduction=deduction, note=note)
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

        ttk.Button(footer, text="Gia hạn…", command=extend, bootstyle="secondary").pack(
            side=LEFT, padx=(8, 0)
        )
        ttk.Button(
            footer, text="Chuyển thành mua", command=convert_to_sale, bootstyle="warning"
        ).pack(side=LEFT, padx=6)
        ttk.Button(
            footer, text="Trả hàng bán", command=open_sale_returns, bootstyle="secondary"
        ).pack(side=LEFT)
        ttk.Button(footer, text="Trả đĩa", command=submit, bootstyle="success").pack(
            side=RIGHT
        )
        pager_update = self._create_pager(page, page_number, refresh)
        search_timer = {}
        customer_search.trace_add("write", lambda *_: (page_number.set(1), self._debounce(search_timer, refresh)))
        self._install_sortable_headings(
            tree,
            {"#0": "Phim / bản đĩa", "customer": "Khách", "due": "Hạn trả", "status": "Trạng thái"},
            sort_state,
            lambda: (page_number.set(1), refresh()),
        )
        page.refresh = refresh
