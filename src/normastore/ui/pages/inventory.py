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
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "title", "descending": False}
        tree_frame = ttk.Frame(page)
        tree_frame.pack(fill=BOTH, expand=True)
        tree = self._create_treeview(
            tree_frame,
            columns=("barcode", "title", "format", "condition", "status", "rent", "sell"),
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
                episodes = self.store.inventory_group_episodes(identifier, *current_filters, item_id=navigation["item_id"])
                tree.delete(*children)
                seasons = {}
                for episode in episodes:
                    season = seasons.get(episode.season_number)
                    if season is None:
                        season = tree.insert(node, END, text=f"Mùa {episode.season_number}")
                        seasons[episode.season_number] = season
                    child = tree.insert(season, END, iid=f"item:{episode.item_id}", text=f"Tập {episode.episode_number}: {episode.title}")
                    nodes[child] = ("item", episode.item_id)
                    add_placeholder(child)
            elif kind in ("item", "more"):
                item_id, copy_page = (identifier, 1) if kind == "item" else identifier
                parent = node if kind == "item" else tree.parent(node)
                status, text, condition, media, rentable, sellable = current_filters
                result = self.store.query_inventory(status, PageRequest(copy_page, 100), SortSpec("barcode"), text, item_id, condition, media, rentable, sellable)
                if kind == "more":
                    tree.delete(node)
                    nodes.pop(node, None)
                else:
                    tree.delete(*children)
                for copy in result.items:
                    iid = str(copy.copy_id)
                    rows[iid] = copy
                    tree.insert(parent, END, iid=iid, text=copy.barcode, values=(copy.barcode, copy.title, copy.media_format, CONDITION_LABELS[copy.condition], STATUS_LABELS[copy.status], "Có" if copy.can_rent else "Không", "Có" if copy.can_sell else "Không"))
                if result.page < result.total_pages:
                    more = tree.insert(parent, END, text="Mở để tải thêm đĩa…")
                    nodes[more] = ("more", (item_id, result.page + 1))
                    add_placeholder(more)

        def refresh():
            tree.delete(*tree.get_children())
            rows.clear()
            nodes.clear()
            result = self.store.inventory_groups(*filters_now(), PageRequest(page_number.get(), 50), bool(sort_state['descending']), item_id=navigation["item_id"])
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
            fields = [
                ("Mã vạch", barcode, None),
                ("Định dạng", media, ("VHS", "VCD", "DVD", "Blu-ray")),
                ("Tình trạng", condition, tuple(CONDITION_LABELS.values())),
                ("Trạng thái", status, (status.get(),) if copy.status in (CopyStatus.RENTED, CopyStatus.HELD, CopyStatus.SOLD) else tuple(STATUS_LABELS[value] for value in (CopyStatus.AVAILABLE, CopyStatus.INSPECTION, CopyStatus.REPAIR, CopyStatus.LOST, CopyStatus.RETIRED))),
                ("Tình trạng (%)", condition_percent, None),
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

        def add_copy():
            dialog = self._dialog("Thêm đĩa vào kho", 720, 530)
            query = tk.StringVar()
            barcode = tk.StringVar()
            media = tk.StringVar(value="DVD")
            rentable = tk.BooleanVar(value=True)
            sellable = tk.BooleanVar(value=True)
            form = ttk.Frame(dialog, padding=12)
            form.pack(fill=BOTH, expand=True)
            ttk.Label(form, text="Tìm phim / tập").pack(anchor="w")
            ttk.Entry(form, textvariable=query).pack(fill=X)
            items = self._create_treeview(form, columns=("title",), show="headings", height=8, selectmode="browse")
            items.heading("title", text="Phim / tập")
            items.pack(fill=BOTH, expand=True, pady=6)
            page_var = tk.IntVar(value=1)

            def load_items():
                if not dialog.winfo_exists():
                    return
                result = self.store.query_catalog(CatalogFilters(text=query.get()), PageRequest(page_var.get(), 50))
                items.delete(*items.get_children())
                for item in result.items:
                    items.insert("", END, iid=str(item.item_id), values=(item.title,))
                update_pager(result)

            update_pager = self._create_pager(form, page_var, load_items)
            timer = {}
            query.trace_add("write", lambda *_: (page_var.set(1), self._debounce(timer, load_items)))
            ttk.Label(form, text="Mã vạch").pack(anchor="w")
            ttk.Entry(form, textvariable=barcode).pack(fill=X)
            controls = ttk.Frame(form)
            controls.pack(fill=X, pady=6)
            ttk.Label(controls, text="Định dạng").pack(side=LEFT)
            ttk.Combobox(controls, textvariable=media, values=("VHS", "VCD", "DVD", "Blu-ray"), state="readonly", width=10).pack(side=LEFT, padx=6)
            ttk.Checkbutton(controls, text="Cho thuê", variable=rentable).pack(side=LEFT, padx=6)
            ttk.Checkbutton(controls, text="Cho bán", variable=sellable).pack(side=LEFT, padx=6)

            def save():
                selection = items.selection()
                if not selection:
                    messagebox.showinfo("Thêm đĩa", "Hãy chọn phim hoặc tập phim.", parent=dialog)
                    return
                try:
                    self.store.add_copy(int(selection[0]), barcode.get(), media.get(), self.account.employee_id, rentable.get(), sellable.get())
                    dialog.destroy()
                    refresh()
                except Exception as exc:
                    messagebox.showerror("Thêm đĩa", str(exc), parent=dialog)

            ttk.Button(form, text="Thêm đĩa", command=save, bootstyle="primary").pack(anchor="e")
            load_items()

        ttk.Button(filters, text="Lọc", command=refresh, bootstyle="secondary").pack(side=LEFT)
        ttk.Button(filters, text="Thêm đĩa", command=add_copy, state="normal" if self._can_manage() else "disabled").pack(side=LEFT, padx=4)
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
        def change_sort():
            sort_state["descending"] = not sort_state["descending"]
            page_number.set(1)
            refresh()
        tree.heading("#0", text="Phim / bộ / mùa / đĩa", command=change_sort)
        tree.bind("<<TreeviewOpen>>", load_node)
        tree.bind("<Double-1>", lambda event: edit_copy(event) if tree.selection() and tree.selection()[0] in rows else None)
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

        page.show_item = show_item
        page.refresh = refresh
