from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X

from normastore.application.services import (
    PageRequest,
    SortSpec,
    UpdateInventoryCopyRequest,
)
from normastore.domain.enums import (
    CopyCondition,
    CopyStatus,
)


class InventoryPageMixin:
    def inventory_page(self, page) -> None:
        self._heading(page, "Kho đĩa", "Quản lý barcode, tình trạng và trạng thái vật lý")
        filters = ttk.Frame(page)
        filters.pack(fill=X, pady=(0, 6))
        status_filter = tk.StringVar(value="TẤT CẢ")
        ttk.Label(filters, text="Trạng thái:").pack(side=LEFT)
        ttk.Combobox(
            filters,
            textvariable=status_filter,
            values=("TẤT CẢ", *[status.value for status in CopyStatus]),
            state="readonly",
            width=18,
        ).pack(side=LEFT, padx=6)
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "title", "descending": False}
        tree = self._create_treeview(
            page,
            columns=("barcode", "title", "format", "condition", "status", "rent", "sell"),
            show="headings",
        )
        titles = [
            ("barcode", "Barcode"),
            ("title", "Phim/tập"),
            ("format", "Định dạng"),
            ("condition", "Tình trạng"),
            ("status", "Kho"),
            ("rent", "Thuê"),
            ("sell", "Bán"),
        ]
        for key, title in titles:
            tree.heading(key, text=title)
        tree.pack(fill=BOTH, expand=True)

        def refresh():
            tree.delete(*tree.get_children())
            selected_status = (
                None if status_filter.get() == "TẤT CẢ" else CopyStatus(status_filter.get())
            )
            result = self.call(
                lambda s: s.query_inventory(
                    selected_status,
                    PageRequest(page_number.get(), 50),
                    SortSpec(str(sort_state["field"]), bool(sort_state["descending"])),
                )
            )
            pager_update(result)
            for copy in result.items:
                tree.insert(
                    "",
                    END,
                    iid=str(copy.copy_id),
                    values=(
                        copy.barcode,
                        copy.title,
                        copy.media_format,
                        copy.condition.value,
                        copy.status.value,
                        "Có" if copy.can_rent else "Không",
                        "Có" if copy.can_sell else "Không",
                    ),
                )

        def edit_copy(_event=None):
            selected = tree.selection()
            if len(selected) != 1:
                return messagebox.showinfo("Kho đĩa", "Hãy chọn một bản đĩa.", parent=self)
            if not self._can_manage():
                return messagebox.showerror(
                    "Kho đĩa", "Chỉ Quản lý/Quản trị viên được sửa kho.", parent=self
                )
            values = tree.item(selected[0], "values")
            dialog = self._dialog("Sửa bản đĩa", 660, 540)
            body = ttk.Frame(dialog, padding=14)
            body.pack(fill=BOTH, expand=True)
            barcode = tk.StringVar(value=values[0])
            media = tk.StringVar(value=values[2])
            condition = tk.StringVar(value=values[3])
            status = tk.StringVar(value=values[4])
            can_rent = tk.BooleanVar(value=values[5] == "Có")
            can_sell = tk.BooleanVar(value=values[6] == "Có")
            rental_override, sale_override, deposit_override, note = (
                tk.StringVar(),
                tk.StringVar(),
                tk.StringVar(),
                tk.StringVar(),
            )
            fields = [
                ("Barcode", barcode, None),
                ("Định dạng", media, ("VHS", "VCD", "DVD", "Blu-ray")),
                ("Tình trạng", condition, tuple(value.value for value in CopyCondition)),
                ("Trạng thái", status, ("AVAILABLE", "INSPECTION", "REPAIR", "LOST", "RETIRED")),
                ("Giá thuê override", rental_override, None),
                ("Giá bán override", sale_override, None),
                ("Cọc override", deposit_override, None),
                ("Ghi chú đổi trạng thái", note, None),
            ]
            for row, (label, variable, options) in enumerate(fields):
                ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=4)
                control = (
                    ttk.Combobox(body, textvariable=variable, values=options, state="readonly")
                    if options
                    else ttk.Entry(body, textvariable=variable)
                )
                control.grid(row=row, column=1, sticky="ew", pady=4)
            ttk.Checkbutton(body, text="Cho thuê", variable=can_rent).grid(
                row=len(fields), column=0, sticky="w", pady=6
            )
            ttk.Checkbutton(body, text="Cho bán", variable=can_sell).grid(
                row=len(fields), column=1, sticky="w", pady=6
            )
            body.columnconfigure(1, weight=1)
            footer = ttk.Frame(dialog, padding=(14, 0, 14, 14))
            footer.pack(fill=X)

            def number(variable):
                raw = variable.get().strip().replace(".", "").replace(",", ".")
                return Decimal(raw) if raw else None

            def save():
                try:
                    request = UpdateInventoryCopyRequest(
                        barcode.get(),
                        media.get(),
                        CopyCondition(condition.get()),
                        can_rent.get(),
                        can_sell.get(),
                        CopyStatus(status.get()),
                        number(rental_override),
                        number(sale_override),
                        number(deposit_override),
                        note.get(),
                    )
                    self.call(
                        lambda s: s.update_inventory_copy(
                            int(selected[0]), request, self.account.employee_id
                        ),
                        True,
                    )
                    dialog.destroy()
                    refresh()
                except Exception as exc:
                    messagebox.showerror("Kho đĩa", str(exc), parent=dialog)

            ttk.Button(footer, text="Lưu", command=save, bootstyle="primary").pack(side=RIGHT)
            ttk.Button(footer, text="Hủy", command=dialog.destroy, bootstyle="secondary").pack(
                side=RIGHT, padx=6
            )

        def inspect(target_status: CopyStatus):
            selected = tree.selection()
            if len(selected) != 1:
                return messagebox.showinfo(
                    "Kiểm tra kho", "Hãy chọn một bản đĩa chờ kiểm tra.", parent=self
                )
            note = simpledialog.askstring("Kiểm tra kho", "Ghi chú (không bắt buộc):", parent=self)
            if note is None:
                return
            try:
                self.call(
                    lambda s: s.inspect_copy(
                        int(selected[0]), self.account.employee_id, target_status, note
                    ),
                    True,
                )
                refresh()
            except Exception as exc:
                messagebox.showerror("Kiểm tra kho", str(exc), parent=self)

        ttk.Button(filters, text="Lọc", command=refresh, bootstyle="secondary").pack(side=LEFT)
        ttk.Button(
            filters,
            text="Sửa bản đĩa",
            command=edit_copy,
            bootstyle="primary",
            state="normal" if self._can_manage() else "disabled",
        ).pack(side=RIGHT, padx=6)
        ttk.Button(
            filters,
            text="Duyệt vào kho",
            command=lambda: inspect(CopyStatus.AVAILABLE),
            bootstyle="success",
        ).pack(side=RIGHT)
        ttk.Button(
            filters,
            text="Chuyển sửa chữa",
            command=lambda: inspect(CopyStatus.REPAIR),
            bootstyle="warning",
        ).pack(side=RIGHT, padx=6)
        ttk.Button(
            filters,
            text="Ngưng khai thác",
            command=lambda: inspect(CopyStatus.RETIRED),
            bootstyle="danger",
        ).pack(side=RIGHT)
        pager_update = self._create_pager(page, page_number, refresh)
        self._install_sortable_headings(
            tree, dict(titles), sort_state, lambda: (page_number.set(1), refresh())
        )
        tree.bind("<Double-1>", edit_copy)
        status_filter.trace_add("write", lambda *_: (page_number.set(1), refresh()))
        page.refresh = refresh
