from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, X
from ttkbootstrap.widgets.scrolled import ScrolledFrame

from normastore.application.contracts import CatalogFilters, PageRequest, SortSpec
from normastore.domain.enums import CopyStatus, ItemType, LineAction, ReservationState
from normastore.ui.formatting import RESERVATION_LABELS, format_datetime, vnd


class ReservationsPageMixin:
    def reservations_page(self, page) -> None:
        self._heading(page, "Đặt trước", "Theo thứ tự đặt • Giữ 24 giờ khi có hàng")
        search_row = ttk.Frame(page)
        search_row.pack(fill=X, pady=(0, 6))
        search = tk.StringVar()
        search_field = tk.StringVar(value="name")
        for label, value in (("Tên khách", "name"), ("SĐT", "phone"), ("Phim", "movie")):
            ttk.Radiobutton(search_row, text=label, variable=search_field, value=value).pack(side=LEFT, padx=2)
        ttk.Entry(search_row, textvariable=search, width=34).pack(side=LEFT, padx=6)
        states = {"Đang chờ hoặc đang giữ": (ReservationState.WAITING, ReservationState.HELD),
                  "Tất cả": None, "Đang chờ": ReservationState.WAITING,
                  "Đang giữ": ReservationState.HELD, "Đã thuê": ReservationState.FULFILLED,
                  "Đã mua": ReservationState.FULFILLED,
                  "Hết hạn": ReservationState.EXPIRED, "Đã hủy": ReservationState.CANCELLED}
        state_filter = tk.StringVar(value="Đang chờ hoặc đang giữ")
        ttk.Label(search_row, text="Trạng thái").pack(side=LEFT, padx=(10, 3))
        ttk.Combobox(search_row, textvariable=state_filter, values=tuple(states),
                     state="readonly", width=23).pack(side=LEFT)
        list_mode = tk.StringVar(value="Danh sách")
        ttk.Combobox(search_row, textvariable=list_mode, values=("Danh sách", "Thẻ"),
                     state="readonly", width=10).pack(side=LEFT, padx=5)
        list_area = ttk.Frame(page)
        list_area.pack(fill=BOTH, expand=True)
        tree = self._create_treeview(
            list_area, columns=("customer", "item", "state", "hold"), show="headings", selectmode="extended"
        )
        for column, title in [
            ("customer", "Khách"),
            ("item", "Phim / tập"),
            ("state", "Trạng thái"),
            ("hold", "Giữ đến"),
        ]:
            tree.heading(column, text=title)
        tree.pack(fill=BOTH, expand=True)
        cards = ScrolledFrame(list_area, autohide=False)
        bottom = ttk.Frame(page)
        bottom.pack(fill=X, pady=6)
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "created", "descending": True}
        reservations = {}
        card_selection: set[int] = set()
        cancellable_states = (ReservationState.WAITING, ReservationState.HELD)

        def selected_reservations():
            if list_mode.get() == "Thẻ":
                return [reservation for reservation in reservations.values()
                        if reservation.reservation_id in card_selection]
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
            selected_copies: dict[int, int] = {}
            selected_copy_labels: dict[int, str] = {}
            selected_copy_text = tk.StringVar(value="Chưa chọn đĩa cụ thể.")
            ttk.Label(frame, textvariable=selected_copy_text, wraplength=950).pack(anchor="w")
            picker_rows = {}
            item_page = tk.IntVar(value=1)
            item_sort: dict[str, object] = {"field": "#0", "descending": False}

            def choose_copy():
                selected = list(picker.selection()) if view_mode.get() == "Danh sách" else [str(i) for i in selected_item_ids]
                if len(selected) != 1:
                    return messagebox.showinfo("Chọn đĩa", "Hãy chọn đúng một phim hoặc tập.", parent=dialog)
                item_id = int(selected[0])
                item = self.store.catalog_item(item_id)
                from datetime import date
                if item.release_date and item.release_date > date.today():
                    return messagebox.showinfo("Chọn đĩa", "Phim chưa phát hành. Hãy đặt trước theo phim.", parent=dialog)
                previous_grab = self.grab_current()
                copy_dialog = self._dialog("Chọn bản đĩa đặt trước", 720, 450)
                if previous_grab:
                    def restore_grab(event):
                        if event.widget is copy_dialog and previous_grab.winfo_exists():
                            previous_grab.grab_set()
                    copy_dialog.bind("<Destroy>", restore_grab, add="+")
                copy_tree = self._create_treeview(copy_dialog, columns=("format", "condition", "location"), show="tree headings")
                for column, title in (("#0", "Mã đĩa"), ("format", "Định dạng"), ("condition", "Tình trạng"), ("location", "Vị trí")):
                    copy_tree.heading(column, text=title)
                copy_tree.pack(fill=BOTH, expand=True, padx=10, pady=10)
                copy_page = tk.IntVar(value=1)

                def load_copies():
                    copy_tree.delete(*copy_tree.get_children())
                    result = self.store.query_inventory(CopyStatus.AVAILABLE, PageRequest(copy_page.get(), 50), SortSpec("barcode"), item_id=item_id)
                    pager(result)
                    for copy in result.items:
                        if (item.can_rent and copy.can_rent) or (item.can_sell and copy.can_sell):
                            copy_tree.insert("", END, iid=str(copy.copy_id), text=copy.barcode,
                                             values=(copy.media_format, copy.condition.value, " / ".join(x or "—" for x in (copy.aisle, copy.rack, copy.compartment))))

                def confirm_copy():
                    selection = copy_tree.selection()
                    if not selection:
                        return messagebox.showinfo("Chọn đĩa", "Hãy chọn một bản đĩa.", parent=copy_dialog)
                    selected_item_ids.add(item_id)
                    selected_copies[item_id] = int(selection[0])
                    selected_copy_labels[item_id] = f"{item.title}: {copy_tree.item(selection[0], 'text')}"
                    selected_copy_text.set("Đã chọn đĩa: " + "; ".join(selected_copy_labels.values()))
                    copy_dialog.destroy()

                def clear_copy():
                    selected_copies.pop(item_id, None)
                    selected_copy_labels.pop(item_id, None)
                    selected_copy_text.set("Đã chọn đĩa: " + "; ".join(selected_copy_labels.values())
                                           if selected_copy_labels else "Chưa chọn đĩa cụ thể.")
                    copy_dialog.destroy()

                pager = self._create_pager(copy_dialog, copy_page, load_copies)
                ttk.Button(copy_dialog, text="Chọn đĩa", command=confirm_copy).pack(side=LEFT, padx=10, pady=8)
                ttk.Button(copy_dialog, text="Đặt theo phim", command=clear_copy).pack(side=LEFT, padx=5)
                load_copies()

            ttk.Button(frame, text="Chọn bản đĩa cho phim đã chọn", command=choose_copy).pack(anchor="w", pady=4)

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
                    self.store.reserve(customer.id, ids, self.account.employee_id,
                                       copy_ids={item_id: selected_copies[item_id] for item_id in ids if item_id in selected_copies})
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
            card_selection.clear()
            for child in cards.winfo_children():
                child.destroy()
            result = self.store.query_reservations(
                PageRequest(page_number.get(), 50),
                SortSpec(str(sort_state["field"]), bool(sort_state["descending"])),
                text=search.get(), state=states[state_filter.get()], search_field=search_field.get(),
                fulfilled_action={"Đã thuê": LineAction.RENT, "Đã mua": LineAction.BUY}.get(state_filter.get()),
            )
            pager(result)
            for index, reservation in enumerate(result.items):
                label = {LineAction.RENT: "Đã thuê", LineAction.BUY: "Đã mua"}.get(
                    reservation.fulfilled_action, RESERVATION_LABELS[reservation.state])
                row_id = tree.insert(
                    "",
                    END,
                    values=(
                        reservation.customer_name,
                        reservation.item_title,
                        label,
                        format_datetime(reservation.hold_until),
                    ),
                )
                reservations[row_id] = reservation
                if list_mode.get() == "Thẻ":
                    card = ttk.Labelframe(cards, text=reservation.item_title, padding=8)
                    card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=4, pady=4)
                    poster = ttk.Label(card, text="Đang tải poster", width=10, anchor="center")
                    poster.pack(side=LEFT, padx=(0, 8))
                    self._load_poster_thumbnail(reservation.poster_path, poster)
                    content = ttk.Frame(card)
                    content.pack(side=LEFT, fill=BOTH, expand=True)
                    ttk.Label(content, text=f"Khách: {reservation.customer_name}\n{label}\nĐĩa: {reservation.barcode or '—'}\nGiữ đến: {format_datetime(reservation.hold_until)}", justify=LEFT, wraplength=220).pack(anchor="w")
                    chosen = tk.BooleanVar(value=False)
                    def toggle(current=reservation.reservation_id, variable=chosen):
                        if variable.get():
                            card_selection.add(current)
                        else:
                            card_selection.discard(current)
                        update_cancel_button()
                    ttk.Checkbutton(content, text="Chọn", variable=chosen, command=toggle).pack(anchor="w")
                    ttk.Button(content, text="Chi tiết phim", command=lambda item_id=reservation.item_id: self._open_catalog_details(item_id)).pack(anchor="w")
            if list_mode.get() == "Thẻ":
                tree.pack_forget()
                cards.pack(fill=BOTH, expand=True)
            else:
                cards.pack_forget()
                tree.pack(fill=BOTH, expand=True)
            for column in range(3):
                cards.columnconfigure(column, weight=1)
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
        state_filter.trace_add("write", lambda *_: (page_number.set(1), refresh()))
        search_field.trace_add("write", lambda *_: (page_number.set(1), refresh()))
        list_mode.trace_add("write", lambda *_: refresh())
        self._install_sortable_headings(
            tree,
            {"customer": "Khách", "item": "Phim / tập", "state": "Trạng thái", "hold": "Giữ đến"},
            sort_state,
            lambda: (page_number.set(1), refresh()),
        )
        page.refresh = refresh
