from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, RIGHT

from normastore.application.services import (
    PageRequest,
    SortSpec,
)
from normastore.domain.enums import (
    LineAction,
)
from normastore.infrastructure.pdf_receipts import PdfReceiptExporter
from normastore.ui.formatting import vnd


class OrdersPageMixin:
    def orders_page(self, page) -> None:
        bar = self._heading(
            page, "Phiếu đã lập", "Double-click để xem chi tiết phim/tập trong phiếu"
        )
        search = tk.StringVar()
        ttk.Entry(bar, textvariable=search, width=35).pack(side=RIGHT)
        tree = self._create_treeview(
            page,
            columns=("customer", "employee", "created", "status", "total"),
            show="tree headings",
        )
        tree.heading("#0", text="Mã phiếu")
        tree.heading("customer", text="Khách hàng")
        tree.heading("employee", text="Nhân viên")
        tree.heading("created", text="Lập lúc")
        tree.heading("status", text="Trạng thái")
        tree.heading("total", text="Cần thu")
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
                self.call(
                    lambda s: s.record_order_pdf_export(
                        order_id, self.account.employee_id, layout, Path(path).name
                    ),
                    True,
                )
                return Path(path)

            def done(saved_path: Path):
                export_button.configure(state="normal", text="Xuất PDF")
                messagebox.showinfo(
                    "Xuất PDF", f"Đã tạo phiếu PDF:\n{saved_path}", parent=parent or self
                )

            def failed(exc):
                export_button.configure(state="normal", text="Xuất PDF")
                messagebox.showerror("Xuất PDF", str(exc), parent=parent or self)

            self._run_async(work, done, failed)

        ttk.Combobox(
            bar, textvariable=pdf_layout, values=("A4", "80mm"), width=8, state="readonly"
        ).pack(side=RIGHT, padx=(6, 0))
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
            tree.delete(*tree.get_children())
            rows.clear()
            export_button.configure(state="disabled")
            result = self.call(
                lambda s: s.query_orders(
                    search.get(),
                    PageRequest(page_number.get(), 50),
                    SortSpec(str(sort_state["field"]), bool(sort_state["descending"])),
                )
            )
            pager_update(result)
            for order in result.items:
                rows[str(order.order_id)] = order
                tree.insert(
                    "",
                    END,
                    iid=str(order.order_id),
                    text=order.code,
                    values=(
                        order.customer_name,
                        order.employee_name,
                        order.created_at.strftime("%d/%m/%Y %H:%M"),
                        order.status,
                        vnd(order.total_due),
                    ),
                )

        def detail(_event=None):
            selected = tree.selection()
            if len(selected) != 1:
                return
            try:
                order, lines = self.call(lambda s: s.order_detail(int(selected[0])))
            except Exception as exc:
                return messagebox.showerror("Phiếu", str(exc), parent=self)
            dialog = tb.Toplevel(self)
            dialog.title(f"Phiếu {order.code}")
            dialog.geometry("760x410")
            dialog.transient(self)
            frame = ttk.Frame(dialog, padding=12)
            frame.pack(fill=BOTH, expand=True)
            ttk.Label(
                frame,
                text=f"{order.customer_name} • {order.created_at:%d/%m/%Y %H:%M} • Tổng cần thu: {vnd(order.total_due)}",
                font=("Segoe UI", 11, "bold"),
            ).pack(anchor="w", pady=(0, 8))
            lines_tree = self._create_treeview(
                frame,
                columns=("barcode", "action", "price", "deposit", "due", "state"),
                show="tree headings",
            )
            for key, title in [
                ("barcode", "Barcode"),
                ("action", "Loại"),
                ("price", "Giá"),
                ("deposit", "Cọc"),
                ("due", "Hạn trả"),
                ("state", "Tình trạng thuê"),
            ]:
                lines_tree.heading(key, text=title)
            lines_tree.pack(fill=BOTH, expand=True)
            for line in lines:
                lines_tree.insert(
                    "",
                    END,
                    text=line.title,
                    values=(
                        line.barcode or "—",
                        "Thuê" if line.action == LineAction.RENT else "Mua",
                        vnd(line.unit_price),
                        vnd(line.deposit),
                        line.due_date or "—",
                        line.rental_state or "—",
                    ),
                )
            ttk.Button(
                frame,
                text="Xuất PDF",
                command=lambda: export_pdf(order.order_id, order.code, dialog),
                bootstyle="secondary",
            ).pack(anchor="e", pady=(8, 0))

        tree.bind("<Double-1>", detail)
        tree.bind(
            "<<TreeviewSelect>>",
            lambda _event: export_button.configure(
                state="normal" if len(tree.selection()) == 1 else "disabled"
            ),
            add="+",
        )
        pager_update = self._create_pager(page, page_number, refresh)
        self._install_sortable_headings(
            tree,
            {
                "#0": "Mã phiếu",
                "customer": "Khách hàng",
                "employee": "Nhân viên",
                "created": "Lập lúc",
                "status": "Trạng thái",
                "total": "Cần thu",
            },
            sort_state,
            lambda: (page_number.set(1), refresh()),
        )
        search.trace_add("write", lambda *_: (page_number.set(1), self.after(250, refresh)))
        page.refresh = refresh
