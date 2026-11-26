from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, X
from ttkbootstrap.widgets.scrolled import ScrolledFrame

from normastore.application.contracts import CatalogFilters, PageRequest, SortSpec
from normastore.domain.enums import ItemType, LineAction, ReservationState
from normastore.ui.formatting import RESERVATION_LABELS, format_datetime, vnd


class ReservationsPageMixin:
    def reservations_page(self, page) -> None:
        self._heading(page, "Đặt trước", "Theo thứ tự đặt • Giữ 24 giờ khi có hàng")
        search_row = ttk.Frame(page)
        search_row.pack(fill=X, pady=(0, 6))
        search = tk.StringVar()
        ttk.Label(search_row, text="Tìm tên khách hoặc phim:").pack(side=LEFT)
        ttk.Entry(search_row, textvariable=search, width=34).pack(side=LEFT, padx=6)
        tree = self._create_treeview(
            page, columns=("customer", "item", "state", "hold"), show="headings", selectmode="extended"
        )
        for column, title in [
            ("customer", "Khách"),
            ("item", "Phim / tập"),
            ("state", "Trạng thái"),
            ("hold", "Giữ đến"),
        ]:
            tree.heading(column, text=title)
        tree.pack(fill=BOTH, expand=True)
        bottom = ttk.Frame(page)
        bottom.pack(fill=X, pady=6)
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "created", "descending": True}
        reservations = {}
        cancellable_states = (ReservationState.WAITING, ReservationState.HELD)

        def selected_reservations():
            return [reservations[row] for row in tree.selection() if row in reservations]

        def can_cancel(selected):
            return bool(selected) and all(reservation.state in cancellable_states for reservation in selected)

        def update_cancel_button(_event=None):
            enabled = can_cancel(selected_reservations())
            cancel_button.configure(state="normal" if enabled else "disabled")

        def cancel(selected):
            if not can_cancel(selected):
                return
            if len(selected) == 1:
                reservation = selected[0]
                prompt = f"Hủy lượt đặt trước “{reservation.item_title}” của {reservation.customer_name}?"
            else:
                prompt = f"Hủy {len(selected)} lượt đặt trước đã chọn?"
            if not messagebox.askyesno("Hủy đặt trước", prompt, parent=self):
                return
            try:
                self.store.cancel_reservations(
                    [reservation.reservation_id for reservation in selected], self.account.employee_id,
                )
            except Exception as exc:
                messagebox.showerror("Hủy đặt trước", str(exc), parent=self)
                return
            refresh()

        def open_show(show_id):
            catalog_page = self.pages.get("Phim & tập")
            if catalog_page is None:
                catalog_page = ttk.Frame(self.content)
                self.pages["Phim & tập"] = catalog_page
                self.catalog_page(catalog_page)
            previous_grab = self.grab_current()
            if previous_grab:
                previous_grab.grab_release()
            show_dialog = catalog_page.open_show_details(show_id)
            if show_dialog and previous_grab:
                def restore_grab(event):
                    if event.widget is show_dialog and previous_grab.winfo_exists():
                        previous_grab.grab_set()
                show_dialog.bind("<Destroy>", restore_grab, add="+")

        def context_menu(event):
            item = tree.identify_row(event.y)
            if item not in reservations:
                return
            if item not in tree.selection():
                tree.selection_set(item)
            selected = selected_reservations()
            reservation = reservations[item]
            menu = tk.Menu(tree, tearoff=False)
            menu.add_command(label="Xem chi tiết phim / tập", command=lambda: self._open_catalog_details(reservation.item_id))
            if reservation.show_id:
                menu.add_command(label="Xem chi tiết bộ phim", command=lambda: open_show(reservation.show_id))
            menu.add_separator()
            menu.add_command(
                label="Hủy đặt trước", command=lambda: cancel(selected),
                state="normal" if can_cancel(selected) else "disabled",
            )
            menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", context_menu)

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
            picker_area = ttk.Frame(frame)
            picker_area.pack(fill=BOTH, expand=True)
            picker = self._create_treeview(
                picker_area, columns=("type", "stock"), show="tree headings", selectmode="extended"
            )
            picker.heading("#0", text="Phim / tập")
            picker.heading("type", text="Loại")
            picker.heading("stock", text="Sẵn thuê / mua")
            picker.pack(fill=BOTH, expand=True)
            card_area = ScrolledFrame(picker_area, autohide=False)
            selected_item_ids: set[int] = set()
            picker_rows = {}
            item_page = tk.IntVar(value=1)
            item_sort: dict[str, object] = {"field": "#0", "descending": False}

            def load_customers():
                if not dialog.winfo_exists():
                    return
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
                if not dialog.winfo_exists():
                    return
                picker.delete(*picker.get_children())
                picker_rows.clear()
                for child in card_area.winfo_children():
                    child.destroy()
                field = {"#0": "title", "stock": "rentable_copies"}.get(
                    str(item_sort["field"]), str(item_sort["field"])
                )
                result = self.store.query_catalog(CatalogFilters(text=search_var.get(), item_rentable_or_sellable=True), PageRequest(item_page.get(), 48), SortSpec(field, bool(item_sort['descending'])))
                item_pager(result)
                for index, item in enumerate(result.items):
                    picker_rows[str(item.item_id)] = item
                    picker.insert(
                        "",
                        END,
                        iid=str(item.item_id),
                        text=item.title,
                        values=("Phim lẻ" if item.item_type == ItemType.MOVIE else "Tập phim", f"{item.rentable_copies} / {item.sellable_copies}"),
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
                            text=f"{'Phim lẻ' if item.item_type == ItemType.MOVIE else 'Tập phim'} • Điểm {item.vote_average or '—'}",
                            bootstyle="secondary",
                        ).pack(anchor="w")
                        ttk.Label(
                            card,
                            text=f"Giá gốc thuê {vnd(item.rental_price)} • mua {vnd(item.sale_price)}\nSẵn thuê: {item.rentable_copies} • mua: {item.sellable_copies}",
                            wraplength=210,
                        ).pack(anchor="w", pady=(4, 0))
                        ttk.Label(
                            card, text=(item.overview or "Chưa có tóm tắt.")[:130], wraplength=220
                        ).pack(anchor="w", pady=(4, 0))
                        def card_menu(event, item=item):
                            menu = tk.Menu(event.widget, tearoff=False)
                            menu.add_command(label="Xem chi tiết phim / tập", command=lambda: self._open_catalog_details(item.item_id, dialog))
                            if item.show_id:
                                menu.add_command(label="Xem chi tiết bộ phim", command=lambda: open_show(item.show_id))
                            menu.tk_popup(event.x_root, event.y_root)
                        for widget in (card, *card.winfo_children()):
                            widget.bind("<Button-3>", card_menu)
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
            def picker_menu(event):
                row = picker.identify_row(event.y)
                item = picker_rows.get(row)
                if not item:
                    return
                picker.selection_set(row)
                menu = tk.Menu(picker, tearoff=False)
                menu.add_command(label="Xem chi tiết phim / tập", command=lambda: self._open_catalog_details(item.item_id, dialog))
                if item.show_id:
                    menu.add_command(label="Xem chi tiết bộ phim", command=lambda: open_show(item.show_id))
                menu.tk_popup(event.x_root, event.y_root)
            picker.bind("<Button-3>", picker_menu)
            self._install_sortable_headings(
                picker,
                {"#0": "Phim / tập", "type": "Loại", "stock": "Sẵn thuê / mua"},
                item_sort,
                lambda: (item_page.set(1), load_items()),
            )
            customer_debounce: dict[str, str] = {}
            item_debounce: dict[str, str] = {}
            customer_search_var.trace_add(
                "write", lambda *_: self._debounce(customer_debounce, load_customers)
            )
            search_var.trace_add(
                "write",
                lambda *_: self._debounce(item_debounce, lambda: (item_page.set(1), load_items())),
            )
            view_mode.trace_add("write", lambda *_: load_items())
            load_customers()
            load_items()

        def refresh():
            self.store.expire_reservation_holds()
            tree.delete(*tree.get_children())
            reservations.clear()
            result = self.store.query_reservations(
                PageRequest(page_number.get(), 50),
                SortSpec(str(sort_state["field"]), bool(sort_state["descending"])),
                text=search.get(),
            )
            pager(result)
            for reservation in result.items:
                row_id = tree.insert(
                    "",
                    END,
                    values=(
                        reservation.customer_name,
                        reservation.item_title,
                        ({LineAction.RENT: "Đã thuê", LineAction.BUY: "Đã mua"}.get(
                            reservation.fulfilled_action, RESERVATION_LABELS[reservation.state])),
                        format_datetime(reservation.hold_until),
                    ),
                )
                reservations[row_id] = reservation
            update_cancel_button()

        ttk.Button(bottom, text="Tạo đặt trước", command=create, bootstyle="primary").pack(
            side=LEFT
        )
        cancel_button = ttk.Button(
            bottom, text="Hủy đặt trước", command=lambda: cancel(selected_reservations()),
            bootstyle="danger", state="disabled",
        )
        cancel_button.pack(side=LEFT, padx=(6, 0))
        tree.bind("<<TreeviewSelect>>", update_cancel_button)
        ttk.Label(
            bottom,
            text="Giữ Ctrl hoặc Shift để chọn nhiều lượt.",
            bootstyle="secondary",
        ).pack(side=LEFT, padx=10)
        pager = self._create_pager(page, page_number, refresh)
        search_timer: dict[str, str] = {}
        search.trace_add("write", lambda *_: self._debounce(search_timer, lambda: (page_number.set(1), refresh())))
        self._install_sortable_headings(
            tree,
            {"customer": "Khách", "item": "Phim / tập", "state": "Trạng thái", "hold": "Giữ đến"},
            sort_state,
            lambda: (page_number.set(1), refresh()),
        )
        page.refresh = refresh
