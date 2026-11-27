from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X
from ttkbootstrap.widgets.scrolled import ScrolledFrame

from normastore.application.contracts import CatalogFilters, PageRequest, SortSpec, UpdateInventoryCopyRequest
from normastore.domain.enums import (
    CopyCondition,
    CopyStatus,
)
from normastore.ui.csv_import import export_template, import_file

STATUS_LABELS = {
    CopyStatus.AVAILABLE: "Có sẵn", CopyStatus.HELD: "Đang giữ",
    CopyStatus.RENTED: "Đang thuê", CopyStatus.INSPECTION: "Chờ kiểm tra",
    CopyStatus.REPAIR: "Đang sửa chữa", CopyStatus.LOST: "Đã mất",
    CopyStatus.SOLD: "Đã bán", CopyStatus.RETIRED: "Ngưng khai thác",
}
CONDITION_LABELS = {
    CopyCondition.NEW: "Mới", CopyCondition.GOOD: "Tốt",
    CopyCondition.WORN: "Cũ", CopyCondition.DAMAGED: "Hỏng",
}
PRICE_MODES = {"Theo phim": None, "Nhập giá riêng": "DIRECT", "Theo tình trạng": "CONDITION", "Theo % giá gốc": "PERCENT"}


class InventoryPageMixin:
    def inventory_page(self, page) -> None:
        self._heading(page, "Kho đĩa", "Quản lý mã vạch, tình trạng và trạng thái vật lý")
        filters = ttk.Frame(page)
        filters.pack(fill=X, pady=(0, 6))
        status_filter = tk.StringVar(value="TẤT CẢ")
        search = tk.StringVar()
        ttk.Label(filters, text="Tìm phim / mã vạch:").pack(side=LEFT)
        ttk.Entry(filters, textvariable=search, width=22).pack(side=LEFT, padx=6)
        ttk.Label(filters, text="Trạng thái:").pack(side=LEFT)
        ttk.Combobox(
            filters,
            textvariable=status_filter,
            values=("TẤT CẢ", *STATUS_LABELS.values()),
            state="readonly",
            width=18,
        ).pack(side=LEFT, padx=6)
        advanced = ttk.Frame(page)
        advanced.pack(fill=X, pady=(0, 6))
        condition_filter = tk.StringVar(value="Tất cả")
        media_filter = tk.StringVar(value="Tất cả")
        rentable_filter, sellable_filter = tk.BooleanVar(), tk.BooleanVar()
        ttk.Label(advanced, text="Tình trạng:").pack(side=LEFT)
        ttk.Combobox(advanced, textvariable=condition_filter, values=("Tất cả", *CONDITION_LABELS.values()), state="readonly", width=14).pack(side=LEFT, padx=5)
        ttk.Label(advanced, text="Định dạng:").pack(side=LEFT)
        ttk.Combobox(advanced, textvariable=media_filter, values=("Tất cả", "VHS", "VCD", "DVD", "Blu-ray"), state="readonly", width=10).pack(side=LEFT, padx=5)
        ttk.Checkbutton(advanced, text="Cho thuê", variable=rentable_filter).pack(side=LEFT, padx=5)
        ttk.Checkbutton(advanced, text="Cho bán", variable=sellable_filter).pack(side=LEFT, padx=5)
        location_filters = tuple(tk.StringVar() for _ in range(3))
        location_bar = ttk.Frame(page)
        location_bar.pack(fill=X, pady=(0, 6))
        for label, variable in zip(("Dãy", "Kệ", "Ngăn"), location_filters):
            ttk.Label(location_bar, text=label).pack(side=LEFT)
            ttk.Entry(location_bar, textvariable=variable, width=16).pack(side=LEFT, padx=5)
        ttk.Label(location_bar, text="Giữ Ctrl hoặc Shift để chọn nhiều bản đĩa.",
                  bootstyle="secondary").pack(side=LEFT, padx=8)
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "title", "descending": False}
        tree_frame = ttk.Frame(page)
        tree_frame.pack(fill=BOTH, expand=True)
        tree = self._create_treeview(
            tree_frame,
            columns=("barcode", "title", "format", "condition", "status", "rent", "sell", "percent", "location"),
            show="tree headings",
        )
        tree.heading("#0", text="Phim / bộ / mùa / đĩa")
        tree.column("#0", width=260, minwidth=180)
        titles = [
            ("barcode", "Mã vạch"),
            ("title", "Phim/tập"),
            ("format", "Định dạng"),
            ("condition", "Tình trạng"),
            ("status", "Kho"),
            ("rent", "Thuê"),
            ("sell", "Bán"),
            ("percent", "Tình trạng %"),
            ("location", "Dãy / Kệ / Ngăn"),
        ]
        for key, title in titles:
            tree.heading(key, text=title)
        vertical = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        horizontal = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        vertical.pack(side=RIGHT, fill="y")
        horizontal.pack(side="bottom", fill=X)
        tree.pack(fill=BOTH, expand=True)
        rows = {}
        nodes = {}
        navigation = {"suppress": False, "item_id": None}

        def filters_now():
            status = next((key for key, label in STATUS_LABELS.items() if label == status_filter.get()), None)
            condition = next((key for key, label in CONDITION_LABELS.items() if label == condition_filter.get()), None)
            return (status, search.get(), condition, "" if media_filter.get() == "Tất cả" else media_filter.get(), rentable_filter.get(), sellable_filter.get())

        def add_placeholder(parent):
            tree.insert(parent, END, text="Đang chờ mở…", tags=("placeholder",))

        def load_node(_event=None):
            node = tree.focus()
            if node not in nodes:
                return
            kind, identifier = nodes[node]
            children = tree.get_children(node)
            if not children or "placeholder" not in tree.item(children[0], "tags"):
                return
            current_filters = filters_now()
            if kind == "show":
                episodes = self.store.inventory_group_episodes(identifier, *current_filters, item_id=navigation["item_id"], location=tuple(v.get() for v in location_filters))
                tree.delete(*children)
                seasons = {}
                for episode in episodes:
                    season = seasons.get(episode.season_number)
                    if season is None:
                        season = tree.insert(node, END, text=f"Mùa {episode.season_number}")
                        seasons[episode.season_number] = season
                        nodes[season] = ("season", (identifier, episode.season_number))
                    child = tree.insert(season, END, iid=f"item:{episode.item_id}", text=f"Tập {episode.episode_number}: {episode.title}")
                    nodes[child] = ("item", episode.item_id)
                    add_placeholder(child)
            elif kind in ("item", "more"):
                item_id, copy_page = (identifier, 1) if kind == "item" else identifier
                parent = node if kind == "item" else tree.parent(node)
                status, text, condition, media, rentable, sellable = current_filters
                result = self.store.query_inventory(status, PageRequest(copy_page, 100), SortSpec("barcode"), text, item_id, condition, media, rentable, sellable, tuple(v.get() for v in location_filters))
                if kind == "more":
                    tree.delete(node)
                    nodes.pop(node, None)
                else:
                    tree.delete(*children)
                for copy in result.items:
                    iid = str(copy.copy_id)
                    rows[iid] = copy
                    tree.insert(parent, END, iid=iid, text=copy.barcode, values=(copy.barcode, copy.title, copy.media_format, CONDITION_LABELS[copy.condition], STATUS_LABELS[copy.status], "Có" if copy.can_rent else "Không", "Có" if copy.can_sell else "Không", f"{copy.condition_percent}%", " / ".join(x or "—" for x in (copy.aisle, copy.rack, copy.compartment))))
                if result.page < result.total_pages:
                    more = tree.insert(parent, END, text="Mở để tải thêm đĩa…")
                    nodes[more] = ("more", (item_id, result.page + 1))
                    add_placeholder(more)

        def refresh():
            tree.delete(*tree.get_children())
            rows.clear()
            nodes.clear()
            result = self.store.inventory_groups(*filters_now(), PageRequest(page_number.get(), 50), bool(sort_state['descending']), item_id=navigation["item_id"], location=tuple(v.get() for v in location_filters))
            pager_update(result)
            for group in result.items:
                kind = "show" if group.is_show else "item"
                node = tree.insert("", END, iid=f"{kind}:{group.group_id}", text=group.title)
                nodes[node] = (kind, group.group_id)
                add_placeholder(node)

        def edit_copy(_event=None):
            selected = tree.selection()
            if len(selected) != 1 or selected[0] not in rows:
                return messagebox.showinfo("Kho đĩa", "Hãy chọn một bản đĩa.", parent=self)
            if not self._can_manage():
                return messagebox.showerror(
                    "Kho đĩa", "Chỉ Quản lý/Quản trị viên được sửa kho.", parent=self
                )
            values = tree.item(selected[0], "values")
            copy = rows[selected[0]]
            dialog = self._dialog("Sửa bản đĩa", 660, 700)
            footer = ttk.Frame(dialog, padding=(14, 0, 14, 14))
            footer.pack(fill=X, side="bottom")
            body = ScrolledFrame(dialog, padding=14, autohide=False)
            body.pack(fill=BOTH, expand=True)
            barcode = tk.StringVar(value=values[0])
            media = tk.StringVar(value=values[2])
            condition = tk.StringVar(value=values[3])
            status = tk.StringVar(value=values[4])
            can_rent = tk.BooleanVar(value=values[5] == "Có")
            can_sell = tk.BooleanVar(value=values[6] == "Có")
            rental_override = tk.StringVar(value=str(copy.rental_price_override) if copy.rental_price_override is not None else "")
            sale_override = tk.StringVar(value=str(copy.sale_price_override) if copy.sale_price_override is not None else "")
            condition_percent = tk.StringVar(value=str(copy.condition_percent))
            rental_mode = tk.StringVar(value=next(label for label, mode in PRICE_MODES.items() if mode == copy.rental_price_mode))
            sale_mode = tk.StringVar(value=next(label for label, mode in PRICE_MODES.items() if mode == copy.sale_price_mode))
            rental_percent = tk.StringVar(value=str(copy.rental_price_percent) if copy.rental_price_percent is not None else "100")
            sale_percent = tk.StringVar(value=str(copy.sale_price_percent) if copy.sale_price_percent is not None else "100")
            note = tk.StringVar()
            aisle, rack, compartment = (tk.StringVar(value=value or "") for value in (copy.aisle, copy.rack, copy.compartment))
            fields = [
                ("Mã vạch", barcode, None),
                ("Định dạng", media, ("VHS", "VCD", "DVD", "Blu-ray")),
                ("Tình trạng", condition, tuple(CONDITION_LABELS.values())),
                ("Trạng thái", status, (status.get(),) if copy.status in (CopyStatus.RENTED, CopyStatus.HELD, CopyStatus.SOLD) else tuple(STATUS_LABELS[value] for value in (CopyStatus.AVAILABLE, CopyStatus.INSPECTION, CopyStatus.REPAIR, CopyStatus.LOST, CopyStatus.RETIRED))),
                ("Tình trạng (%)", condition_percent, None),
                ("Dãy", aisle, None),
                ("Kệ", rack, None),
                ("Ngăn", compartment, None),
                ("Cách tính giá thuê", rental_mode, tuple(PRICE_MODES)),
                ("Giá thuê riêng", rental_override, None),
                ("Tỷ lệ giá thuê (%)", rental_percent, None),
                ("Cách tính giá bán", sale_mode, tuple(PRICE_MODES)),
                ("Giá bán riêng", sale_override, None),
                ("Tỷ lệ giá bán (%)", sale_percent, None),
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
                if variable is barcode:
                    control.configure(state="readonly")
            ttk.Checkbutton(body, text="Cho thuê", variable=can_rent).grid(
                row=len(fields), column=0, sticky="w", pady=6
            )
            ttk.Checkbutton(body, text="Cho bán", variable=can_sell).grid(
                row=len(fields), column=1, sticky="w", pady=6
            )
            body.columnconfigure(1, weight=1)

            def number(variable):
                raw = variable.get().strip().replace(",", ".")
                return Decimal(raw) if raw else None

            def save():
                try:
                    request = UpdateInventoryCopyRequest(
                        barcode.get(),
                        media.get(),
                        next(key for key, label in CONDITION_LABELS.items() if label == condition.get()),
                        can_rent.get(),
                        can_sell.get(),
                        next(key for key, label in STATUS_LABELS.items() if label == status.get()),
                        number(rental_override) if PRICE_MODES[rental_mode.get()] == "DIRECT" else None,
                        number(sale_override) if PRICE_MODES[sale_mode.get()] == "DIRECT" else None,
                        note.get(),
                        number(condition_percent),
                        PRICE_MODES[rental_mode.get()],
                        PRICE_MODES[sale_mode.get()],
                        number(rental_percent) if PRICE_MODES[rental_mode.get()] == "PERCENT" else None,
                        number(sale_percent) if PRICE_MODES[sale_mode.get()] == "PERCENT" else None,
                        aisle.get(), rack.get(), compartment.get(),
                    )
                    self.store.update_inventory_copy(int(selected[0]), request, self.account.employee_id)
                    dialog.destroy()
                    refresh()
                except Exception as exc:
                    messagebox.showerror("Kho đĩa", str(exc), parent=dialog)

            ttk.Button(footer, text="Lưu", command=save, bootstyle="primary").pack(side=RIGHT)
            ttk.Button(footer, text="Hủy", command=dialog.destroy, bootstyle="secondary").pack(
                side=RIGHT, padx=6
            )

        def edit_selected_copies():
            selected = tree.selection()
            if not selected or any(row not in rows for row in selected):
                return messagebox.showinfo("Kho đĩa", "Hãy chỉ chọn các bản đĩa cần sửa.", parent=self)
            if not self._can_manage():
                return messagebox.showerror("Kho đĩa", "Chỉ Quản lý/Quản trị viên được sửa kho.", parent=self)
            if len(selected) == 1:
                return edit_copy()
            dialog = self._dialog("Sửa nhiều bản đĩa", 690, 720)
            footer = ttk.Frame(dialog, padding=(14, 0, 14, 14))
            footer.pack(fill=X, side="bottom")
            body = ScrolledFrame(dialog, padding=14, autohide=False)
            body.pack(fill=BOTH, expand=True)
            ttk.Label(body, text=f"Đã chọn {len(selected)} đĩa. Đánh dấu các trường cần thay đổi.").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 8)
            )
            field_specs = (
                ("media_format", "Định dạng", ("VHS", "VCD", "DVD", "Blu-ray")),
                ("condition", "Tình trạng", tuple(CONDITION_LABELS.values())),
                ("status", "Trạng thái", tuple(STATUS_LABELS[value] for value in
                 (CopyStatus.AVAILABLE, CopyStatus.INSPECTION, CopyStatus.REPAIR, CopyStatus.LOST, CopyStatus.RETIRED))),
                ("can_rent", "Cho thuê", ("Có", "Không")),
                ("can_sell", "Cho bán", ("Có", "Không")),
                ("condition_percent", "Tình trạng (%)", None),
                ("aisle", "Dãy", None), ("rack", "Kệ", None), ("compartment", "Ngăn", None),
                ("rental_price_mode", "Cách tính giá thuê", tuple(PRICE_MODES)),
                ("rental_price_override", "Giá thuê riêng", None),
                ("rental_price_percent", "Tỷ lệ giá thuê (%)", None),
                ("sale_price_mode", "Cách tính giá bán", tuple(PRICE_MODES)),
                ("sale_price_override", "Giá bán riêng", None),
                ("sale_price_percent", "Tỷ lệ giá bán (%)", None),
            )
            fields = {}
            for index, (name, label, choices) in enumerate(field_specs, 1):
                enabled = tk.BooleanVar(value=False)
                value = tk.StringVar(value=choices[0] if choices else "")
                fields[name] = (enabled, value)
                ttk.Checkbutton(body, text=label, variable=enabled).grid(row=index, column=0, sticky="w", pady=3)
                control = (ttk.Combobox(body, textvariable=value, values=choices, state="readonly")
                           if choices else ttk.Entry(body, textvariable=value))
                control.grid(row=index, column=1, sticky="ew", pady=3)
            note = tk.StringVar()
            ttk.Label(body, text="Ghi chú đổi trạng thái").grid(row=len(field_specs) + 1, column=0, sticky="w", pady=4)
            ttk.Entry(body, textvariable=note).grid(row=len(field_specs) + 1, column=1, sticky="ew", pady=4)
            body.columnconfigure(1, weight=1)

            def save():
                try:
                    changes = {}
                    for name, (enabled, value) in fields.items():
                        if not enabled.get():
                            continue
                        raw = value.get().strip()
                        if name == "condition":
                            changes[name] = next(key for key, label in CONDITION_LABELS.items() if label == raw)
                        elif name == "status":
                            changes[name] = next(key for key, label in STATUS_LABELS.items() if label == raw)
                        elif name in ("can_rent", "can_sell"):
                            changes[name] = raw == "Có"
                        elif name in ("rental_price_mode", "sale_price_mode"):
                            changes[name] = PRICE_MODES[raw]
                        elif name in ("condition_percent", "rental_price_override", "sale_price_override",
                                      "rental_price_percent", "sale_price_percent"):
                            changes[name] = Decimal(raw.replace(",", ".")) if raw else None
                        else:
                            changes[name] = raw
                    if note.get().strip():
                        changes["note"] = note.get()
                    for prefix in ("rental", "sale"):
                        mode_key = f"{prefix}_price_mode"
                        if mode_key in changes:
                            if changes[mode_key] != "DIRECT":
                                changes[f"{prefix}_price_override"] = None
                            if changes[mode_key] != "PERCENT":
                                changes[f"{prefix}_price_percent"] = None
                    count = self.store.update_inventory_copies([int(row) for row in selected], changes, self.account.employee_id)
                    dialog.destroy()
                    refresh()
                    messagebox.showinfo("Kho đĩa", f"Đã sửa {count} bản đĩa.", parent=self)
                except Exception as exc:
                    messagebox.showerror("Kho đĩa", str(exc), parent=dialog)

            ttk.Button(footer, text="Lưu", command=save, bootstyle="primary").pack(side=RIGHT)
            ttk.Button(footer, text="Hủy", command=dialog.destroy, bootstyle="secondary").pack(side=RIGHT, padx=6)

        def inspect(target_status: CopyStatus):
            selected = tree.selection()
            if len(selected) != 1 or selected[0] not in rows:
                return messagebox.showinfo(
                    "Kiểm tra kho", "Hãy chọn một bản đĩa chờ kiểm tra.", parent=self
                )
            note = simpledialog.askstring("Kiểm tra kho", "Ghi chú (không bắt buộc):", parent=self)
            if note is None:
                return
            try:
                self.store.inspect_copy(int(selected[0]), self.account.employee_id, target_status, note)
                refresh()
            except Exception as exc:
                messagebox.showerror("Kiểm tra kho", str(exc), parent=self)

        def add_copy(item_id=None, show_id=None, season_number=None):
            if not self._can_manage():
                return messagebox.showerror("Kho đĩa", "Chỉ Quản lý/Quản trị viên được nhập kho.", parent=self)
            dialog = self._dialog("Thêm đĩa vào kho", 720, 590)
            query = tk.StringVar()
            quantity = tk.StringVar(value="1")
            media = tk.StringVar(value="DVD")
            rentable = tk.BooleanVar(value=True)
            sellable = tk.BooleanVar(value=True)
            location = tuple(tk.StringVar() for _ in range(3))
            form = ttk.Frame(dialog, padding=12)
            form.pack(fill=BOTH, expand=True)
            ttk.Label(form, text="Tìm phim / tập").pack(anchor="w")
            ttk.Entry(form, textvariable=query, state="readonly" if item_id else "normal").pack(fill=X)
            items = self._create_treeview(form, columns=("title",), show="headings", height=8, selectmode="browse")
            items.heading("title", text="Phim / tập")
            items.pack(fill=BOTH, expand=True, pady=6)
            page_var = tk.IntVar(value=1)

            def load_items():
                if not dialog.winfo_exists():
                    return
                items.delete(*items.get_children())
                if item_id is not None:
                    item = self.store.catalog_item(item_id)
                    items.insert("", END, iid=str(item.id), values=(item.title,))
                    items.selection_set(str(item.id))
                    rentable.set(item.can_rent)
                    sellable.set(item.can_sell)
                    return
                result = self.store.query_catalog(CatalogFilters(text=query.get(), show_id=show_id,
                                                  season_number=season_number), PageRequest(page_var.get(), 50))
                for item in result.items:
                    items.insert("", END, iid=str(item.item_id), values=(item.title,))
                update_pager(result)

            update_pager = self._create_pager(form, page_var, load_items)
            timer = {}
            query.trace_add("write", lambda *_: (page_var.set(1), self._debounce(timer, load_items)))
            ttk.Label(form, text="Số lượng (mã đĩa được tạo tự động)").pack(anchor="w")
            ttk.Spinbox(form, textvariable=quantity, from_=1, to=1000000).pack(fill=X)
            controls = ttk.Frame(form)
            controls.pack(fill=X, pady=6)
            ttk.Label(controls, text="Định dạng").pack(side=LEFT)
            ttk.Combobox(controls, textvariable=media, values=("VHS", "VCD", "DVD", "Blu-ray"), state="readonly", width=10).pack(side=LEFT, padx=6)
            ttk.Checkbutton(controls, text="Cho thuê", variable=rentable).pack(side=LEFT, padx=6)
            ttk.Checkbutton(controls, text="Cho bán", variable=sellable).pack(side=LEFT, padx=6)
            location_row = ttk.Frame(form)
            location_row.pack(fill=X, pady=4)
            for label, variable in zip(("Dãy", "Kệ", "Ngăn"), location):
                ttk.Label(location_row, text=label).pack(side=LEFT)
                ttk.Entry(location_row, textvariable=variable, width=14).pack(side=LEFT, padx=5)

            def save():
                selection = items.selection()
                if not selection:
                    messagebox.showinfo("Thêm đĩa", "Hãy chọn phim hoặc tập phim.", parent=dialog)
                    return
                try:
                    try:
                        count = int(quantity.get())
                    except ValueError:
                        raise ValueError("Số lượng phải là số nguyên dương.") from None
                    created = self.store.add_copies(int(selection[0]), count, media.get(), self.account.employee_id, rentable.get(), sellable.get(), *(v.get() for v in location))
                    dialog.destroy()
                    refresh()
                    messagebox.showinfo("Nhập kho", f"Đã thêm {len(created)} đĩa.\nMã: {created[0].barcode}"
                                        + (f" … {created[-1].barcode}" if len(created) > 1 else ""), parent=self)
                except Exception as exc:
                    messagebox.showerror("Thêm đĩa", str(exc), parent=dialog)

            ttk.Button(form, text="Thêm đĩa", command=save, bootstyle="primary").pack(anchor="e")
            load_items()

        ttk.Button(filters, text="Lọc", command=refresh, bootstyle="secondary").pack(side=LEFT)
        ttk.Button(filters, text="Thêm đĩa", command=add_copy, state="normal" if self._can_manage() else "disabled").pack(side=LEFT, padx=4)
        ttk.Button(filters, text="Sửa đã chọn", command=edit_selected_copies,
                   state="normal" if self._can_manage() else "disabled").pack(side=LEFT, padx=4)
        ttk.Button(filters, text="Nhập CSV", command=lambda: import_file(self, "copies", refresh),
                   state="normal" if self._can_manage() else "disabled").pack(side=LEFT, padx=4)
        ttk.Button(filters, text="Tải mẫu CSV", command=lambda: export_template(self, "copies")).pack(side=LEFT, padx=4)
        def copy_menu(event):
            item = tree.identify_row(event.y)
            if item in nodes:
                kind, identifier = nodes[item]
                if kind == "more":
                    return
                tree.selection_set(item)
                tree.focus(item)
                menu = tk.Menu(tree, tearoff=False)
                if kind == "item":
                    command = lambda: add_copy(item_id=identifier)
                elif kind == "show":
                    command = lambda: add_copy(show_id=identifier)
                else:
                    command = lambda: add_copy(show_id=identifier[0], season_number=identifier[1])
                menu.add_command(label="Thêm đĩa", command=command,
                                 state="normal" if self._can_manage() else "disabled")
                menu.tk_popup(event.x_root, event.y_root)
                return
            if item not in rows:
                return
            if item not in tree.selection():
                tree.selection_set(item)
            tree.focus(item)
            menu = tk.Menu(tree, tearoff=False)
            menu.add_command(label="Sửa bản đĩa đã chọn", command=edit_selected_copies,
                             state="normal" if self._can_manage() else "disabled")
            menu.add_command(label="Duyệt vào kho", command=lambda: inspect(CopyStatus.AVAILABLE))
            menu.add_command(label="Chuyển sửa chữa", command=lambda: inspect(CopyStatus.REPAIR))
            menu.add_command(label="Ngưng khai thác", command=lambda: inspect(CopyStatus.RETIRED))
            menu.tk_popup(event.x_root, event.y_root)

        tree.bind("<Button-3>", copy_menu)
        pager_update = self._create_pager(page, page_number, refresh)
        def change_sort():
            sort_state["descending"] = not sort_state["descending"]
            page_number.set(1)
            refresh()
        tree.heading("#0", text="Phim / bộ / mùa / đĩa", command=change_sort)
        tree.bind("<<TreeviewOpen>>", load_node)
        tree.bind("<Double-1>", lambda event: edit_selected_copies() if tree.selection() and tree.selection()[0] in rows else None)
        search_timer = {}
        def filter_changed(*_args):
            if not navigation["suppress"]:
                navigation["item_id"] = None
                page_number.set(1)
                refresh()

        def search_changed(*_args):
            if not navigation["suppress"]:
                navigation["item_id"] = None
                page_number.set(1)
                self._debounce(search_timer, refresh)

        for variable in (status_filter, condition_filter, media_filter, rentable_filter, sellable_filter):
            variable.trace_add("write", filter_changed)
        search.trace_add("write", search_changed)
        for variable in location_filters:
            variable.trace_add("write", search_changed)

        def show_item(item_id, title, show_id):
            pending = search_timer.pop("after", None)
            if pending:
                self.after_cancel(pending)
            navigation["suppress"] = True
            navigation["item_id"] = item_id
            try:
                status_filter.set("TẤT CẢ")
                condition_filter.set("Tất cả")
                media_filter.set("Tất cả")
                rentable_filter.set(False)
                sellable_filter.set(False)
                search.set(title)
                for variable in location_filters:
                    variable.set("")
                page_number.set(1)
            finally:
                navigation["suppress"] = False
            refresh()
            parent = f"show:{show_id}" if show_id else f"item:{item_id}"
            if tree.exists(parent):
                tree.focus(parent)
                load_node()
                tree.item(parent, open=True)
                target = f"item:{item_id}"
                if tree.exists(target) and show_id:
                    tree.item(tree.parent(target), open=True)
                    tree.focus(target)
                    load_node()
                    tree.item(target, open=True)
                else:
                    target = parent
                tree.selection_set(target)
                tree.see(target)

        page.add_copy = add_copy
        page.import_copies_csv = lambda: import_file(self, "copies", refresh)
        page.show_item = show_item
        page.refresh = refresh
