from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, X

from normastore.application.contracts import CatalogFilters, PageRequest, SortSpec
from normastore.ui.formatting import vnd


class ReservationsPageMixin:
    def reservations_page(self, page) -> None:
        self._heading(page, "Đặt trước", "FIFO theo Movie / Episode • Giữ 24 giờ khi có hàng")
        tree = self._create_treeview(
            page, columns=("customer", "item", "state", "hold"), show="headings"
        )
        for column, title in [
            ("customer", "Khách"),
            ("item", "Item"),
            ("state", "Trạng thái"),
            ("hold", "Giữ đến"),
        ]:
            tree.heading(column, text=title)
        tree.pack(fill=BOTH, expand=True)
        bottom = ttk.Frame(page)
        bottom.pack(fill=X, pady=6)
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "created", "descending": True}

        def create():
            dialog = self._dialog("Tạo đặt trước", 1020, 680)
            frame = ttk.Frame(dialog, padding=12)
            frame.pack(fill=BOTH, expand=True)
            customers = {}
            customer_var = tk.StringVar()
            customer_search_var = tk.StringVar()
            customer_combo = ttk.Combobox(
                frame, textvariable=customer_var, state="readonly", width=55
            )
            ttk.Label(frame, text="Tìm khách hàng (tên hoặc số điện thoại):").pack(anchor="w")
            ttk.Entry(frame, textvariable=customer_search_var).pack(fill=X, pady=(0, 4))
            ttk.Label(frame, text="Chọn khách hàng:").pack(anchor="w")
            customer_combo.pack(fill=X, pady=(0, 8))
            search_var = tk.StringVar()
            ttk.Entry(frame, textvariable=search_var).pack(fill=X, pady=(0, 6))
            view_mode = tk.StringVar(value="Danh sách")
            ttk.Combobox(
                frame,
                textvariable=view_mode,
                values=("Danh sách", "Thẻ"),
                state="readonly",
                width=14,
            ).pack(anchor="e", pady=(0, 5))
            picker = self._create_treeview(
                frame, columns=("type", "stock"), show="tree headings", selectmode="extended"
            )
            picker.heading("#0", text="Phim / tập")
            picker.heading("type", text="Loại")
            picker.heading("stock", text="Có sẵn")
            picker.pack(fill=BOTH, expand=True)
            card_area = ttk.Frame(frame)
            selected_item_ids: set[int] = set()
            item_page = tk.IntVar(value=1)
            item_sort: dict[str, object] = {"field": "#0", "descending": False}

            def load_customers():
                previous = customer_var.get()
                values = []
                customers.clear()
                for customer in self.store.list_customers(customer_search_var.get()):
                    key = f"{customer.id} — {customer.full_name} ({customer.phone})"
                    customers[key] = customer
                    values.append(key)
                customer_combo["values"] = values
                customer_var.set(
                    previous if previous in customers else (values[0] if values else "")
                )

            def load_items():
                picker.delete(*picker.get_children())
                for child in card_area.winfo_children():
                    child.destroy()
                field = {"#0": "title", "stock": "rentable_copies"}.get(
                    str(item_sort["field"]), str(item_sort["field"])
                )
                result = self.store.query_catalog(CatalogFilters(text=search_var.get(), item_rentable=True), PageRequest(item_page.get(), 48), SortSpec(field, bool(item_sort['descending'])))
                item_pager(result)
                for index, item in enumerate(result.items):
                    picker.insert(
                        "",
                        END,
                        iid=str(item.item_id),
                        text=item.title,
                        values=(item.item_type.value, item.rentable_copies),
                    )
                    if view_mode.get() == "Thẻ":
                        card = ttk.Labelframe(card_area, text=item.title, padding=8)
                        card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=4, pady=4)
                        selected = tk.BooleanVar(value=item.item_id in selected_item_ids)

                        def toggle(item_id=item.item_id, variable=selected):
                            if variable.get():
                                selected_item_ids.add(item_id)
                            else:
                                selected_item_ids.discard(item_id)

                        ttk.Checkbutton(
                            card, text="Chọn đặt trước", variable=selected, command=toggle
                        ).pack(anchor="w")
                        ttk.Label(
                            card,
                            text=f"{item.item_type.value} • Rating {item.vote_average or '—'}",
                            bootstyle="secondary",
                        ).pack(anchor="w")
                        ttk.Label(
                            card,
                            text=f"Thuê {vnd(item.rental_price)} • Sẵn thuê: {item.rentable_copies}",
                            wraplength=210,
                        ).pack(anchor="w", pady=(4, 0))
                        ttk.Label(
                            card, text=(item.overview or "Chưa có tóm tắt.")[:130], wraplength=220
                        ).pack(anchor="w", pady=(4, 0))
                for column in range(3):
                    card_area.columnconfigure(column, weight=1)
                if view_mode.get() == "Thẻ":
                    picker.pack_forget()
                    card_area.pack(fill=BOTH, expand=True)
                else:
                    card_area.pack_forget()
                    picker.pack(fill=BOTH, expand=True)

            def save():
                customer = customers.get(customer_var.get())
                ids = list(selected_item_ids | {int(item_id) for item_id in picker.selection()})
                if not customer or not ids:
                    return messagebox.showinfo(
                        "Đặt trước", "Hãy chọn khách hàng và ít nhất một phim/tập.", parent=dialog
                    )
                try:
                    self.store.reserve(customer.id, ids, self.account.employee_id)
                    dialog.destroy()
                    refresh()
                except Exception as exc:
                    messagebox.showerror("Đặt trước", str(exc), parent=self)

            ttk.Button(frame, text="Xác nhận đặt trước", command=save, bootstyle="primary").pack(
                anchor="e", pady=(8, 0)
            )
            item_pager = self._create_pager(frame, item_page, load_items)
            self._install_sortable_headings(
                picker,
                {"#0": "Phim / tập", "type": "Loại", "stock": "Có sẵn"},
                item_sort,
                lambda: (item_page.set(1), load_items()),
            )
            debounce_state: dict[str, str] = {}
            customer_search_var.trace_add(
                "write", lambda *_: self._debounce(debounce_state, load_customers)
            )
            search_var.trace_add(
                "write",
                lambda *_: self._debounce(debounce_state, lambda: (item_page.set(1), load_items())),
            )
            view_mode.trace_add("write", lambda *_: load_items())
            load_customers()
            load_items()

        def refresh():
            self.store.expire_reservation_holds()
            tree.delete(*tree.get_children())
            result = self.store.query_reservations(PageRequest(page_number.get(), 50), SortSpec(str(sort_state['field']), bool(sort_state['descending'])))
            pager(result)
            for reservation in result.items:
                tree.insert(
                    "",
                    END,
                    values=(
                        reservation.customer_name,
                        reservation.item_title,
                        reservation.state,
                        reservation.hold_until or "—",
                    ),
                )

        ttk.Button(bottom, text="Tạo đặt trước", command=create, bootstyle="primary").pack(
            side=LEFT
        )
        ttk.Label(
            bottom,
            text="Chọn trực tiếp khách hàng và Movie/Episode trong cửa sổ đặt trước.",
            bootstyle="secondary",
        ).pack(side=LEFT, padx=10)
        pager = self._create_pager(page, page_number, refresh)
        self._install_sortable_headings(
            tree,
            {"customer": "Khách", "item": "Item", "state": "Trạng thái", "hold": "Giữ đến"},
            sort_state,
            lambda: (page_number.set(1), refresh()),
        )
        page.refresh = refresh
