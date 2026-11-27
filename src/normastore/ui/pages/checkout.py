from __future__ import annotations

import tkinter as tk
from datetime import date, datetime, timedelta
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X, Y
from ttkbootstrap.widgets.scrolled import ScrolledFrame

from normastore.application.contracts import CatalogFilters, CheckoutLine, PageRequest, PaymentInput, SortSpec
from normastore.domain.enums import (
    LineAction,
)
from normastore.application.contracts import CustomerView
from normastore.ui.formatting import catalog_tooltip_text, vnd
from normastore.ui.tooltips import Tooltip, TreeviewTooltip
from normastore.ui.pages.inventory import CONDITION_LABELS


class CheckoutPageMixin:
    def checkout_page(self, page) -> None:
        self._heading(page, "Tạo phiếu thuê / mua", "Chọn phim rồi thêm vào giỏ")
        top = ttk.Frame(page)
        top.pack(fill=X, pady=(0, 8))
        customer_var = tk.StringVar()
        customer_search_var = tk.StringVar()
        customer_combo = ttk.Combobox(top, textvariable=customer_var, state="readonly", width=38)
        ttk.Label(top, text="Khách hàng:").pack(side=LEFT)
        ttk.Entry(top, textvariable=customer_search_var, width=18).pack(side=LEFT, padx=(6, 0))
        customer_combo.pack(side=LEFT, padx=6)
        ttk.Button(
            top, text="Thêm khách", command=lambda: self._quick_customer(customer_combo, on_saved=select_new_customer)
        ).pack(side=LEFT)
        ttk.Label(top, text="Hạn trả:").pack(side=LEFT, padx=(18, 3))
        due_entry = tb.DateEntry(top, dateformat="%d/%m/%Y", startdate=date.today() + timedelta(days=3), popup_title="Chọn hạn trả", width=11)
        due_entry.pack(side=LEFT)
        voucher_var = tk.StringVar()
        combo_var = tk.StringVar()
        premium_var = tk.StringVar(value="Không đăng ký")
        premium_period = tk.StringVar(value="")
        customer_details = tk.StringVar(value="Chọn khách hàng để xem thông tin.")
        ttk.Label(page, textvariable=customer_details, wraplength=1100, justify=LEFT).pack(anchor="w", pady=(0, 6))
        pane = ttk.Panedwindow(page, orient="horizontal")
        pane.pack(fill=BOTH, expand=True)
        catalog_frame = ttk.Frame(pane, padding=5, width=550)
        cart_frame = ttk.Frame(pane, padding=5, width=380)
        catalog_frame.pack_propagate(False)
        cart_frame.pack_propagate(False)
        pane.add(catalog_frame, weight=3)
        pane.add(cart_frame, weight=2)
        search, picker_type = tk.StringVar(), tk.StringVar(value="Tất cả")
        item_types = {"Tất cả": "", "Phim lẻ": "MOVIE", "Tập phim": "EPISODE"}
        picker_rent, picker_sell = tk.BooleanVar(value=True), tk.BooleanVar(value=True)
        picker_view, picker_page = tk.StringVar(value="Danh sách"), tk.IntVar(value=1)
        picker_filters = ttk.Labelframe(catalog_frame, text="Tìm phim / tập", padding=(8, 5))
        picker_filters.pack(fill=X, pady=(0, 5))
        ttk.Label(picker_filters, text="Từ khóa:").pack(side=LEFT)
        ttk.Entry(picker_filters, textvariable=search, width=25).pack(
            side=LEFT, padx=4, fill=X, expand=True
        )
        ttk.Label(picker_filters, text="Loại:").pack(side=LEFT)
        ttk.Combobox(
            picker_filters,
            textvariable=picker_type,
            values=tuple(item_types),
            width=11,
            state="readonly",
        ).pack(side=LEFT, padx=4)
        ttk.Checkbutton(picker_filters, text="Còn thuê", variable=picker_rent).pack(
            side=LEFT, padx=4
        )
        ttk.Checkbutton(picker_filters, text="Còn mua", variable=picker_sell).pack(
            side=LEFT, padx=4
        )
        ttk.Combobox(
            picker_filters,
            textvariable=picker_view,
            values=("Danh sách", "Thẻ"),
            width=12,
            state="readonly",
        ).pack(side=RIGHT)
        picker_advanced_open = tk.BooleanVar(value=False)
        picker_advanced = ttk.Frame(catalog_frame)
        picker_genre, picker_year_from, picker_year_to, picker_rating = (
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
        )
        picker_format, picker_condition, picker_rental_min, picker_rental_max = (
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
        )
        picker_sale_min, picker_sale_max, picker_show, picker_season = (
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
        )
        picker_genres = {"Tất cả thể loại": None}
        picker_genres.update(
            {genre.name: genre.id for genre in self.store.list_genres()}
        )
        picker_shows = {"Tất cả bộ": None}
        picker_shows.update(
            {show.title: show.show_id for show in self.store.list_shows()}
        )

        def toggle_picker_advanced():
            if picker_advanced_open.get():
                picker_advanced.pack_forget()
                picker_advanced_open.set(False)
                picker_advanced_button.configure(text="Lọc nâng cao ▾")
            else:
                picker_advanced.pack(fill=X, pady=(0, 5), before=catalog)
                picker_advanced_open.set(True)
                picker_advanced_button.configure(text="Thu gọn ▴")

        picker_advanced_button = ttk.Button(
            picker_filters,
            text="Lọc nâng cao ▾",
            command=toggle_picker_advanced,
            bootstyle="secondary",
        )
        picker_advanced_button.pack(side=RIGHT, padx=5)
        def clear_picker_filters():
            for variable in (
                search, picker_genre, picker_year_from, picker_year_to, picker_rating,
                picker_format, picker_condition, picker_rental_min, picker_rental_max,
                picker_sale_min, picker_sale_max, picker_show, picker_season,
            ):
                variable.set("")
            picker_type.set("Tất cả")
            picker_rent.set(True)
            picker_sell.set(True)
            picker_show_control.configure(values=tuple(picker_shows))

        ttk.Button(
            picker_filters, text="Xóa bộ lọc", command=clear_picker_filters, bootstyle="secondary"
        ).pack(side=RIGHT, padx=5)
        for index, (label, variable, values, width) in enumerate((
            ("Thể loại", picker_genre, tuple(picker_genres), 14),
            ("Từ năm", picker_year_from, (), 6),
            ("Đến", picker_year_to, (), 6),
            ("Điểm ≥", picker_rating, (), 6),
            ("Định dạng", picker_format, ("", "VHS", "VCD", "DVD", "Blu-ray"), 9),
            ("Tình trạng", picker_condition, ("", *CONDITION_LABELS.values()), 10),
            ("Bộ", picker_show, tuple(picker_shows), 16),
            ("Mùa", picker_season, (), 5),
            ("Giá gốc thuê từ", picker_rental_min, (), 8),
            ("đến", picker_rental_max, (), 8),
            ("Giá gốc mua từ", picker_sale_min, (), 8),
            ("đến", picker_sale_max, (), 8),
        )):
            row = index // 4
            ttk.Label(picker_advanced, text=label).grid(row=row, column=(index % 4) * 2, sticky="w", padx=(0, 2), pady=3)
            control = (
                ttk.Combobox(
                    picker_advanced,
                    textvariable=variable,
                    values=values,
                    width=width,
                    state="normal" if variable is picker_show else "readonly",
                )
                if values
                else ttk.Entry(picker_advanced, textvariable=variable, width=width)
            )
            control.grid(row=row, column=(index % 4) * 2 + 1, sticky="ew", padx=(0, 4), pady=3)
            if variable is picker_genre:
                picker_genre_control = control
            if variable is picker_show:
                picker_show_control = control

                def filter_picker_shows(event):
                    if event.keysym in ("Up", "Down", "Return", "Escape", "Tab"):
                        return
                    term = picker_show.get().strip().casefold()
                    picker_show_control.configure(
                        values=tuple(name for name in picker_shows if term in name.casefold())
                    )

                picker_show_control.bind("<KeyRelease>", filter_picker_shows)
                picker_show_control.bind(
                    "<<ComboboxSelected>>",
                    lambda _event: picker_show_control.configure(values=tuple(picker_shows)),
                )
            picker_advanced.columnconfigure((index % 4) * 2 + 1, weight=1)
        catalog = self._create_treeview(
            catalog_frame,
            columns=("rentable_copies", "sellable_copies", "rent", "buy"),
            show="tree headings",
        )
        catalog.column("#0", width=260)
        catalog.column("rentable_copies", width=78)
        catalog.column("sellable_copies", width=78)
        catalog.column("rent", width=88)
        catalog.column("buy", width=88)
        catalog.pack(fill=BOTH, expand=True)
        picker_cards = ttk.Frame(catalog_frame)
        picker_canvas = tk.Canvas(picker_cards, highlightthickness=0)
        self._theme_canvases.append(picker_canvas)
        picker_canvas.configure(background=self.style.lookup("TFrame", "background"))
        picker_scroll = ttk.Scrollbar(picker_cards, orient="vertical", command=picker_canvas.yview)
        picker_canvas.configure(yscrollcommand=picker_scroll.set)
        picker_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        picker_scroll.pack(side=RIGHT, fill=Y)
        picker_container = ttk.Frame(picker_canvas, padding=4)
        picker_window = picker_canvas.create_window((0, 0), window=picker_container, anchor="nw")
        picker_container.bind(
            "<Configure>",
            lambda _event: picker_canvas.configure(scrollregion=picker_canvas.bbox("all")),
        )
        picker_canvas.bind(
            "<Configure>",
            lambda event: picker_canvas.itemconfigure(picker_window, width=event.width),
        )
        ttk.Label(
            cart_frame, text="Giỏ phiếu", font=("Segoe UI", 14, "bold"), bootstyle="primary"
        ).pack(anchor="w")
        cart = self._create_treeview(
            cart_frame, columns=("action", "price", "due", "note"), show="tree headings"
        )
        cart.heading("#0", text="Bản đĩa")
        cart.heading("action", text="Loại")
        cart.heading("price", text="Giá")
        cart.heading("due", text="Hạn trả")
        cart.heading("note", text="Ghi chú")
        cart.column("note", width=85, minwidth=65)
        cart.column("#0", width=140, minwidth=70)
        cart.column("action", width=65)
        cart.column("price", width=75, minwidth=50)
        cart.column("due", width=75, minwidth=55)
        summary = ttk.Frame(cart_frame, padding=(0, 5))
        summary.columnconfigure(1, weight=1)
        amounts = {name: tk.StringVar(value="0 đ") for name in ("gross", "voucher", "combo", "premium", "discovery", "deposit", "premium_fee")}
        ttk.Label(summary, text="Tổng trước giảm giá:").grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=amounts["gross"]).grid(row=0, column=2, sticky="e")
        ttk.Label(summary, text="Voucher:").grid(row=1, column=0, sticky="w")
        voucher_combo = ttk.Combobox(summary, textvariable=voucher_var, width=14, state="readonly")
        voucher_combo.grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        Tooltip(voucher_combo, lambda: voucher_var.get())
        ttk.Label(summary, textvariable=amounts["voucher"]).grid(row=1, column=2, sticky="e")
        ttk.Label(summary, text="Combo:").grid(row=2, column=0, sticky="w")
        combo_combo = ttk.Combobox(summary, textvariable=combo_var, state="readonly", width=14)
        combo_combo.grid(row=2, column=1, sticky="ew", padx=6, pady=2)
        Tooltip(combo_combo, lambda: combo_var.get())
        ttk.Label(summary, textvariable=amounts["combo"]).grid(row=2, column=2, sticky="e")
        for row, (name, label) in enumerate((("premium", "Premium:"), ("discovery", "Khám phá:"), ("deposit", "Tiền cọc:")), 3):
            ttk.Label(summary, text=label).grid(row=row, column=0, sticky="w")
            ttk.Label(summary, textvariable=amounts[name]).grid(row=row, column=2, sticky="e")
        ttk.Label(summary, text="Gói hội viên:").grid(row=6, column=0, sticky="w")
        premium_combo = ttk.Combobox(summary, textvariable=premium_var, state="readonly", width=18)
        premium_combo.grid(row=6, column=1, sticky="ew", padx=6)
        ttk.Label(summary, textvariable=amounts["premium_fee"]).grid(row=6, column=2, sticky="e")
        ttk.Label(summary, textvariable=premium_period).grid(row=7, column=0, columnspan=3, sticky="w")
        total_var = tk.StringVar(value="Tổng cần thu: 0 đ")
        total_label = ttk.Label(
            cart_frame, textvariable=total_var, font=("Segoe UI", 11, "bold"), bootstyle="success"
        )
        buttons = ttk.Frame(cart_frame)
        buttons.pack(side="bottom", fill=X)
        total_label.pack(side="bottom", anchor="e", pady=6)
        summary.pack(side="bottom", fill=X)
        cart.pack(fill=BOTH, expand=True)
        cart_lines: list[CheckoutLine] = []
        catalog_rows = {}
        customers: dict[str, CustomerView] = {}
        combos = {}
        vouchers = {}
        premium_plans = {}
        preorder_customer = {"id": None}
        auto_copy_ids: set[int] = set()
        skipped_preorder_ids: set[int] = set()

        def sync_preorders():
            customer = customers.get(customer_var.get())
            customer_id = customer.id if customer else None
            changed = customer_id != preorder_customer["id"]
            if changed:
                cart_lines[:] = [line for line in cart_lines if line.copy_id not in auto_copy_ids]
                for copy_id in auto_copy_ids:
                    if cart.exists(str(copy_id)):
                        cart.delete(str(copy_id))
                auto_copy_ids.clear()
                skipped_preorder_ids.clear()
                preorder_customer["id"] = customer_id
                for row in cart.get_children():
                    cart.set(row, "note", "")
            if customer is None:
                return
            try:
                choices = self.store.customer_preorder_copies(customer.id)
                valid_ids = {choice.copy_id for choice in choices}
                stale_ids = auto_copy_ids - valid_ids
                cart_lines[:] = [line for line in cart_lines if line.copy_id not in stale_ids]
                for copy_id in stale_ids:
                    cart.delete(str(copy_id))
                auto_copy_ids.difference_update(stale_ids)
                for row in cart.get_children():
                    cart.set(row, "note", "Đặt trước" if int(row) in valid_ids else "")
                used = {line.copy_id for line in cart_lines}
                pending = [choice for choice in choices if choice.copy_id not in used | skipped_preorder_ids]
                due = (datetime.strptime(due_entry.entry.get().strip(), "%d/%m/%Y").date()
                       if any(choice.action == LineAction.RENT for choice in pending) else None)
                for choice in pending:
                    line_due = due if choice.action == LineAction.RENT else None
                    cart_lines.append(CheckoutLine(choice.copy_id, choice.action, line_due))
                    auto_copy_ids.add(choice.copy_id)
                    cart.insert("", END, iid=str(choice.copy_id), text=f"{choice.barcode} — {choice.title}",
                                values=("Thuê" if choice.action == LineAction.RENT else "Mua",
                                        vnd(choice.unit_price), line_due or "—", "Đặt trước"))
            except Exception as exc:
                messagebox.showerror("Đặt trước", str(exc), parent=self)

        def refresh_customers(*_args):
            selected = customer_var.get()
            customers.clear()
            values = []
            for customer in self.store.list_customers(customer_search_var.get()):
                key = f"{customer.id} — {customer.full_name} ({customer.phone})"
                customers[key] = customer
                values.append(key)
            customer_combo["values"] = values
            if selected not in customers:
                customer_var.set(values[0] if not selected and values else "")
            combos.clear()
            combo_values = ["Không dùng combo"]
            for combo in self.store.list_combos():
                key = f"{combo.name} ({vnd(combo.discount_amount)})"
                if key in combos:
                    key = f"{key} — #{combo.combo_id}"
                combos[key] = combo
                combo_values.append(key)
            combo_combo["values"] = combo_values
            if not combo_var.get():
                combo_var.set(combo_values[0])
            vouchers.clear()
            for voucher in self.store.list_vouchers():
                if voucher.effective_state == "Đang hiệu lực":
                    label = f"{voucher.code} — {voucher.description}"
                    vouchers[label] = voucher.code
            voucher_combo["values"] = ["", *vouchers]
            premium_plans.clear()
            premium_plans.update({f"{plan.days} ngày — {vnd(plan.price)}": plan.days for plan in self.store.premium_plans()})
            premium_combo["values"] = ["Không đăng ký", *premium_plans]
            if premium_var.get() not in premium_combo["values"]:
                premium_var.set("Không đăng ký")

        def select_new_customer(customer):
            customer_search_var.set(customer.phone)
            refresh_customers()
            label = next((key for key, value in customers.items() if value.id == customer.id), None)
            if label:
                customer_var.set(label)

        page.select_customer = select_new_customer

        def voucher_code():
            value = voucher_var.get().strip()
            return vouchers.get(value, value) or None

        def show_customer():
            customer = customers.get(customer_var.get())
            if not customer:
                customer_details.set("Chọn khách hàng để xem thông tin.")
                return
            premium_end = self.store.premium_until(customer.id)
            premium = f"Đến {premium_end:%d/%m/%Y}" if premium_end else "Không"
            customer_details.set(
                f"Mã: {customer.id} • Họ tên: {customer.full_name} • SĐT: {customer.phone} • "
                f"Email: {customer.email or 'Chưa có'} • Địa chỉ: {customer.address or 'Chưa có'} • "
                f"Premium: {premium} • Nhận email: {'Có' if customer.email_opt_in else 'Không'} • "
                f"Nhận SMS: {'Có' if customer.sms_opt_in else 'Không'}"
            )

        def combo_ids():
            combo = combos.get(combo_var.get())
            return [combo.combo_id] if combo else None

        picker_sort: dict[str, object] = {"field": "#0", "descending": False}

        def picker_number(value: str) -> Decimal | None:
            try:
                return Decimal(value.replace(".", "").replace(",", ".")) if value.strip() else None
            except Exception:
                return None

        def picker_year(value: str) -> int | None:
            try:
                return int(value) if value.strip() else None
            except ValueError:
                return None

        def picker_catalog_filters() -> CatalogFilters:
            return CatalogFilters(
                text=search.get(),
                item_type=item_types.get(picker_type.get(), ""),
                genre_id=picker_genres.get(picker_genre.get()),
                year_from=picker_year(picker_year_from.get()),
                year_to=picker_year(picker_year_to.get()),
                rating_min=picker_number(picker_rating.get()),
                media_format=picker_format.get(),
                condition=next((key for key, label in CONDITION_LABELS.items() if label == picker_condition.get()), None),
                rental_price_min=picker_number(picker_rental_min.get()),
                rental_price_max=picker_number(picker_rental_max.get()),
                sale_price_min=picker_number(picker_sale_min.get()),
                sale_price_max=picker_number(picker_sale_max.get()),
                show_id=picker_shows.get(picker_show.get()),
                season_number=picker_year(picker_season.get()),
                require_rentable=picker_rent.get(),
                require_sellable=picker_sell.get(),
            )

        refresh_generation = {"value": 0}

        def refresh_catalog():
            Tooltip.hide_active()
            catalog.delete(*catalog.get_children())
            catalog_rows.clear()
            for child in picker_container.winfo_children():
                child.destroy()
            field = {"#0": "title", "rent": "rental_price", "buy": "sale_price"}.get(
                str(picker_sort["field"]), str(picker_sort["field"])
            )
            filters = picker_catalog_filters()
            customer = customers.get(customer_var.get())
            customer_id = customer.id if customer else None
            request = PageRequest(picker_page.get(), 48)
            sort = SortSpec(field, bool(picker_sort["descending"]))
            refresh_generation["value"] += 1
            generation = refresh_generation["value"]

            def render(result):
                if generation != refresh_generation["value"] or not page.winfo_exists():
                    return
                picker_pager(result)
                for index, item in enumerate(result.items):
                    catalog_rows[str(item.item_id)] = item
                    catalog.insert(
                        "",
                        END,
                        iid=str(item.item_id),
                        text=item.title,
                        values=(
                            item.rentable_copies,
                            item.sellable_copies,
                            ('Từ ' if item.show_id else '') + vnd(item.rental_price),
                            ('Từ ' if item.show_id else '') + vnd(item.sale_price),
                        ),
                    )
                    if picker_view.get() == "Thẻ":
                        card = ttk.Labelframe(
                            picker_container, text=item.title, padding=7, style="Norma.Card.TLabelframe"
                        )
                        card.grid(row=index // 2, column=index % 2, sticky="nsew", padx=4, pady=4)
                        poster = ttk.Label(
                            card,
                            text="Đang tải\nposter",
                            width=10,
                            anchor="center",
                            justify="center",
                            style="Norma.CardMuted.TLabel",
                        )
                        poster.pack(side=LEFT, padx=(0, 7))
                        self._load_poster_thumbnail(item.poster_path, poster)
                        body = ttk.Frame(card, style="Norma.Card.TFrame")
                        body.pack(side=LEFT, fill=BOTH, expand=True)
                        ttk.Label(
                            body,
                            text=f"{'Phim bộ' if item.show_id else 'Phim lẻ'} • Điểm {item.vote_average or '—'}",
                            style="Norma.CardMuted.TLabel",
                        ).pack(anchor="w")
                        if item.show_id:
                            for widget in (card, poster, body):
                                widget.bind("<Double-1>", lambda _event, show_id=item.show_id: select_season(show_id))
                        ttk.Label(
                            body,
                            text=f"Giá gốc: thuê {'từ ' if item.show_id else ''}{vnd(item.rental_price)} • mua {'từ ' if item.show_id else ''}{vnd(item.sale_price)}",
                            style="Norma.Card.TLabel",
                        ).pack(anchor="w")
                        ttk.Label(
                            body,
                            text=f"Sẵn thuê: {item.rentable_copies} • Sẵn mua: {item.sellable_copies}",
                            style="Norma.Card.TLabel",
                        ).pack(anchor="w")
                        ttk.Button(
                            body,
                            text="+ Thuê",
                            command=lambda current=item: select_season(current.show_id, LineAction.RENT) if current.show_id else add_for_item(current.item_id, LineAction.RENT),
                            state="normal",
                            bootstyle="primary",
                        ).pack(side=LEFT, pady=(5, 0))
                        ttk.Button(
                            body,
                            text="+ Mua",
                            command=lambda current=item: select_season(current.show_id, LineAction.BUY) if current.show_id else add_for_item(current.item_id, LineAction.BUY),
                            state="normal",
                            bootstyle="success",
                        ).pack(side=LEFT, padx=4, pady=(5, 0))
                        Tooltip(card, lambda current=item: catalog_tooltip_text(current))
                for column in range(2):
                    picker_container.columnconfigure(column, weight=1)
                if picker_view.get() == "Thẻ":
                    catalog.pack_forget()
                    picker_cards.pack(fill=BOTH, expand=True)
                else:
                    picker_cards.pack_forget()
                    catalog.pack(fill=BOTH, expand=True)
                update_action_buttons()

            self._run_async(lambda: self.store.query_checkout_catalog(filters, request, sort, customer_id), render)

        def selected_item_id() -> int | None:
            ids = catalog.selection()
            return int(ids[0]) if ids else None

        def add_for_item(item_id: int | None, action: LineAction):
            if not item_id:
                return messagebox.showinfo(
                    "Phiếu", "Hãy chọn một phim hoặc tập còn bản đĩa trống.", parent=self
                )
            try:
                due = datetime.strptime(due_entry.entry.get().strip(), "%d/%m/%Y").date() if action == LineAction.RENT else None
            except ValueError:
                return messagebox.showerror(
                    "Phiếu", "Ngày hẹn trả phải theo dạng ngày/tháng/năm.", parent=self
                )
            try:
                used = {line.copy_id for line in cart_lines}
                customer = customers.get(customer_var.get())
                choices = self.store.checkout_copies(item_id, action, used, customer.id if customer else None)
                if not choices:
                    return messagebox.showinfo(
                        "Phiếu", "Không còn bản đĩa phù hợp cho thao tác này.", parent=self
                    )
                dialog = self._dialog("Chọn bản đĩa", 720, 420)
                ttk.Label(dialog, text="Chọn bản đĩa để " + ("thuê" if action == LineAction.RENT else "mua"), padding=10).pack(anchor="w")
                filters = ttk.Frame(dialog, padding=(10, 0))
                filters.pack(fill=X)
                locations = tuple(tk.StringVar() for _ in range(3))
                for label, variable in zip(("Dãy", "Kệ", "Ngăn"), locations):
                    ttk.Label(filters, text=label).pack(side=LEFT)
                    ttk.Entry(filters, textvariable=variable, width=12).pack(side=LEFT, padx=4)
                holder = ttk.Frame(dialog)
                holder.pack(fill=BOTH, expand=True, padx=10)
                copy_tree = self._create_treeview(holder, columns=("barcode", "format", "condition", "percent", "price", "location"), show="headings", selectmode="browse")
                for column, title in (("barcode", "Mã vạch"), ("format", "Định dạng"), ("condition", "Tình trạng"), ("price", "Giá")):
                    copy_tree.heading(column, text=title)
                copy_tree.heading("percent", text="Tình trạng (%)")
                copy_tree.heading("location", text="Dãy / Kệ / Ngăn")
                horizontal = ttk.Scrollbar(holder, orient="horizontal", command=copy_tree.xview)
                horizontal.pack(side="bottom", fill=X)
                vertical = ttk.Scrollbar(holder, orient="vertical", command=copy_tree.yview)
                vertical.pack(side=RIGHT, fill=Y)
                copy_tree.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
                copy_tree.pack(fill=BOTH, expand=True)
                by_id = {str(choice.copy_id): choice for choice in choices}
                def filter_copies(*_args):
                    copy_tree.delete(*copy_tree.get_children())
                    for choice in choices:
                        if any(variable.get().strip().casefold() not in (value or "").casefold()
                               for variable, value in zip(locations, (choice.aisle, choice.rack, choice.compartment))):
                            continue
                        copy_tree.insert("", END, iid=str(choice.copy_id), values=(choice.barcode, choice.media_format, CONDITION_LABELS[choice.condition], f"{choice.condition_percent}%", vnd(choice.unit_price), " / ".join(x or "—" for x in (choice.aisle, choice.rack, choice.compartment))))
                    children = copy_tree.get_children()
                    if children:
                        copy_tree.selection_set(children[0])
                for variable in locations:
                    variable.trace_add("write", filter_copies)
                filter_copies()
                selected = []

                def confirm():
                    ids = copy_tree.selection()
                    if ids:
                        selected.append(by_id[ids[0]])
                        dialog.destroy()

                ttk.Button(dialog, text="Chọn đĩa", command=confirm, bootstyle="primary").pack(pady=10)
                copy_tree.bind("<Double-1>", lambda _event: confirm())
                self.wait_window(dialog)
                if not selected:
                    return
                choice = selected[0]
                cart_lines.append(CheckoutLine(choice.copy_id, action, due))
                cart.insert(
                    "",
                    END,
                    iid=str(choice.copy_id),
                    text=f"{choice.barcode} — {choice.title}",
                    values=(
                        "Thuê" if action == LineAction.RENT else "Mua",
                        vnd(choice.unit_price),
                        due or "—",
                    ),
                )
                sync_preorders()
                update_quote()
                refresh_catalog()
            except Exception as exc:
                messagebox.showerror("Phiếu", str(exc), parent=self)

        def add(action: LineAction):
            item_id = selected_item_id()
            item = catalog_rows.get(str(item_id)) if item_id is not None else None
            if item and item.show_id:
                select_season(item.show_id, action)
            else:
                add_for_item(item_id, action)

        page.add_catalog_item = add_for_item

        def select_season(initial_show_id=None, initial_action=None):
            shows = self.store.list_shows()
            if not shows:
                return messagebox.showinfo("Phim bộ", "Chưa có bộ phim nào.", parent=self)
            dialog = self._dialog("Chọn tập phim bộ", 850, 650)
            frame = ttk.Frame(dialog, padding=12)
            frame.pack(fill=BOTH, expand=True)
            show_var = tk.StringVar()
            season_var = tk.StringVar()
            first_var, last_var = tk.StringVar(), tk.StringVar()
            initial = next((show.show_id for show in shows if show.show_id == initial_show_id), shows[0].show_id)
            show_map = self._searchable_show_picker(frame, shows, show_var, initial)
            controls = ttk.Frame(frame)
            controls.pack(fill=X, pady=8)
            ttk.Label(controls, text="Mùa").pack(side=LEFT)
            season_combo = ttk.Combobox(controls, textvariable=season_var, state="readonly", width=8)
            season_combo.pack(side=LEFT, padx=5)
            ttk.Label(controls, text="Từ tập").pack(side=LEFT, padx=(10, 3))
            ttk.Entry(controls, textvariable=first_var, width=6).pack(side=LEFT)
            ttk.Label(controls, text="đến tập").pack(side=LEFT, padx=3)
            ttk.Entry(controls, textvariable=last_var, width=6).pack(side=LEFT)
            ttk.Label(controls, text="(để trống cả hai để chọn cả mùa)").pack(side=LEFT, padx=8)
            footer = ttk.Frame(frame)
            footer.pack(side="bottom", fill=X, pady=4)
            choices_frame = ScrolledFrame(frame, autohide=True)
            choices_frame.pack(fill=BOTH, expand=True, pady=6)
            selections = []
            current = {"action": None}

            def load_seasons(*_args):
                show_id = show_map.get(show_var.get())
                episodes = self.store.list_show_episodes(show_id) if show_id is not None else ()
                seasons = sorted({episode.season_number for episode in episodes})
                season_combo.configure(values=seasons)
                season_var.set(str(seasons[0]) if seasons else "")
                clear_choices()

            def clear_choices(*_args):
                selections.clear()
                current["action"] = None
                for child in choices_frame.winfo_children():
                    child.destroy()

            def prepare(action):
                clear_choices()
                if not show_var.get() or not season_var.get():
                    return messagebox.showinfo("Phim bộ", "Hãy chọn bộ phim và mùa có tập.", parent=dialog)
                try:
                    start = int(first_var.get()) if first_var.get().strip() else None
                    end = int(last_var.get()) if last_var.get().strip() else None
                    customer = customers.get(customer_var.get())
                    result = self.store.season_checkout_choices(
                        show_map[show_var.get()], int(season_var.get()), action,
                        customer.id if customer else None, {line.copy_id for line in cart_lines},
                        start, end,
                    )
                    by_number = {episode.episode_number: (episode, choices) for episode, choices in result}
                    first = start if start is not None else min(by_number)
                    last = end if end is not None else max(by_number)
                    for number in range(first, last + 1):
                        row = ttk.Frame(choices_frame, padding=4)
                        row.pack(fill=X)
                        if number not in by_number:
                            ttk.Label(row, text=f"Tập {number}: Chưa nhập danh mục", bootstyle="secondary").pack(anchor="w")
                            continue
                        episode, choices = by_number[number]
                        ttk.Label(row, text=f"Tập {episode.episode_number}: {episode.title}", wraplength=650).pack(anchor="w")
                        if not choices:
                            ttk.Label(row, text="Không có đĩa phù hợp", bootstyle="secondary").pack(anchor="w")
                            continue
                        mapping = {f"{choice.barcode} • {choice.media_format} • {CONDITION_LABELS[choice.condition]} {choice.condition_percent}% • {vnd(choice.unit_price)} • {' / '.join(x or '—' for x in (choice.aisle, choice.rack, choice.compartment))}": choice for choice in choices}
                        selected = tk.StringVar(value=next(iter(mapping)))
                        ttk.Combobox(row, textvariable=selected, values=tuple(mapping), state="readonly").pack(fill=X, expand=True)
                        selections.append((episode.item_id, selected, mapping))
                    current["action"] = action
                except (ValueError, TypeError) as exc:
                    messagebox.showerror("Phim bộ", str(exc) or "Mùa và khoảng tập phải là số hợp lệ.", parent=dialog)
                except Exception as exc:
                    messagebox.showerror("Phim bộ", str(exc), parent=dialog)

            def add_selected():
                if not selections or current["action"] is None:
                    return messagebox.showinfo("Phim bộ", "Hãy chọn thuê hoặc mua để kiểm tra các tập.", parent=dialog)
                try:
                    action = current["action"]
                    due = datetime.strptime(due_entry.entry.get().strip(), "%d/%m/%Y").date() if action == LineAction.RENT else None
                    chosen = [mapping[variable.get()] for _, variable, mapping in selections]
                    customer = customers.get(customer_var.get())
                    used = {line.copy_id for line in cart_lines}
                    for choice in chosen:
                        available = self.store.checkout_copies(choice.item_id, action, used, customer.id if customer else None)
                        if not any(row.copy_id == choice.copy_id for row in available):
                            raise ValueError(f"Đĩa {choice.barcode} không còn phù hợp; hãy chọn lại.")
                        used.add(choice.copy_id)
                    for choice in chosen:
                        cart_lines.append(CheckoutLine(choice.copy_id, action, due))
                        cart.insert("", END, iid=str(choice.copy_id), text=f"{choice.barcode} — {choice.title}", values=("Thuê" if action == LineAction.RENT else "Mua", vnd(choice.unit_price), due or "—"))
                    sync_preorders()
                    dialog.destroy()
                    update_quote()
                    refresh_catalog()
                except Exception as exc:
                    messagebox.showerror("Phim bộ", str(exc), parent=dialog)

            ttk.Button(footer, text="Chọn thuê", command=lambda: prepare(LineAction.RENT)).pack(side=LEFT, padx=3)
            ttk.Button(footer, text="Chọn mua", command=lambda: prepare(LineAction.BUY)).pack(side=LEFT, padx=3)
            ttk.Button(footer, text="Thêm vào giỏ", command=add_selected, bootstyle="primary").pack(side=RIGHT)
            show_var.trace_add("write", load_seasons)
            for variable in (season_var, first_var, last_var):
                variable.trace_add("write", clear_choices)
            load_seasons()
            if initial_action and season_var.get():
                prepare(initial_action)
            return dialog

        ttk.Button(picker_filters, text="Chọn phim bộ", command=lambda: select_season()).pack(side=RIGHT, padx=4)

        def update_quote():
            for variable in amounts.values():
                variable.set("0 đ")
            premium_period.set("")
            customer = customers.get(customer_var.get())
            if not customer or (not cart_lines and premium_var.get() not in premium_plans):
                total_var.set("Tổng cần thu: 0 đ")
                return
            try:
                quote = self.store.quote(customer.id, cart_lines, voucher_code(), combo_ids(), premium_plans.get(premium_var.get()))
                amounts["gross"].set(vnd(quote.gross))
                amounts["deposit"].set(vnd(quote.deposit))
                amounts["premium_fee"].set(vnd(quote.premium_fee))
                if quote.premium_starts_on:
                    premium_period.set(f"Hiệu lực {quote.premium_starts_on:%d/%m/%Y} – {quote.premium_ends_on:%d/%m/%Y}")
                for source in ("voucher", "combo", "premium", "discovery"):
                    amounts[source].set(f"- {vnd(quote.discount_sources.get(source.upper(), Decimal('0')))}")
                total_var.set(f"Tổng cần thu: {vnd(quote.total_due)}")
            except Exception as exc:
                total_var.set(f"Kiểm tra: {exc}")

        def reserve_items(item_ids):
            customer = customers.get(customer_var.get())
            if not customer:
                return messagebox.showinfo("Đặt trước", "Hãy chọn khách hàng.", parent=self)
            try:
                self.store.reserve(customer.id, item_ids, self.account.employee_id)
                messagebox.showinfo("Đặt trước", "Đã ghi nhận đặt trước.", parent=self)
                pending_reservation.clear()
                reserve_label.set("")
                reserve_button.configure(state="disabled")
            except Exception as exc:
                messagebox.showerror("Đặt trước", str(exc), parent=self)

        pending_reservation = []
        def open_reservations(item_ids):
            pending_reservation[:] = list(dict.fromkeys(item_ids))
            titles = [self.store.catalog_item(item_id).title for item_id in pending_reservation]
            reserve_label.set("Đặt trước: " + ", ".join(titles))
            reserve_button.configure(state="normal")

        reserve_label = tk.StringVar(value="")
        ttk.Label(cart_frame, textvariable=reserve_label, wraplength=320).pack(side="bottom", anchor="w")
        reserve_button = ttk.Button(cart_frame, text="Đặt trước phim đã chọn",
                                    command=lambda: reserve_items(pending_reservation), state="disabled")
        reserve_button.pack(side="bottom", anchor="w")
        page.open_reservations = open_reservations
        page.open_reservation = lambda item_id: open_reservations([item_id])
        page.select_season = select_season

        def remove(ids=None):
            ids = cart.selection() if ids is None else ids
            if ids:
                selected_ids = {int(value) for value in ids}
                skipped_preorder_ids.update(selected_ids)
                auto_copy_ids.difference_update(selected_ids)
                cart_lines[:] = [line for line in cart_lines if line.copy_id not in selected_ids]
                for value in ids:
                    cart.delete(value)
                update_quote()
                refresh_catalog()

        def clear_cart():
            remove(cart.get_children())

        def checkout():
            customer = customers.get(customer_var.get())
            if not customer:
                return messagebox.showerror("Phiếu", "Hãy chọn khách hàng.", parent=self)
            try:
                quote = self.store.quote(customer.id, cart_lines, voucher_code(), combo_ids(), premium_plans.get(premium_var.get()))
                received = simpledialog.askstring(
                    "Thanh toán",
                    f"Số tiền nhận (mặc định {quote.total_due:,.0f}):",
                    initialvalue=str(quote.total_due),
                    parent=self,
                )
                if received is None:
                    return
                method = self._choose_payment_method("Thanh toán", self)
                if method is None:
                    return
                order = self.store.checkout(customer.id, self.account.employee_id, cart_lines, [PaymentInput(method, Decimal(received))], voucher_code(), combo_ids(), expected_quote=quote, premium_days=premium_plans.get(premium_var.get()))
                messagebox.showinfo("Hoàn tất", f"Đã tạo phiếu {order.code}.", parent=self)
                cart_lines.clear()
                premium_var.set("Không đăng ký")
                auto_copy_ids.clear()
                skipped_preorder_ids.clear()
                cart.delete(*cart.get_children())
                refresh_catalog()
                update_quote()
                self._refresh_status()
            except Exception as exc:
                update_quote()
                messagebox.showerror("Phiếu", str(exc), parent=self)

        rent_button = ttk.Button(
            buttons, text="+ Thuê", command=lambda: add(LineAction.RENT), bootstyle="primary"
        )
        buy_button = ttk.Button(
            buttons, text="+ Mua", command=lambda: add(LineAction.BUY), bootstyle="success"
        )
        remove_button = ttk.Button(buttons, text="Xóa dòng", command=remove, bootstyle="secondary")
        rent_button.pack(side=LEFT, padx=2)
        buy_button.pack(side=LEFT, padx=2)
        remove_button.pack(side=LEFT, padx=2)
        ttk.Button(buttons, text="Xóa tất cả", command=clear_cart, bootstyle="secondary").pack(side=LEFT, padx=2)
        cart.bind("<Delete>", lambda _event: remove())
        ttk.Button(buttons, text="Hoàn tất", command=checkout, bootstyle="warning").pack(
            side=RIGHT, padx=2
        )
        picker_pager = self._create_pager(catalog_frame, picker_page, refresh_catalog)

        def update_action_buttons(_event=None):
            item = catalog_rows.get(catalog.selection()[0]) if catalog.selection() else None
            rent_button.configure(state="normal" if item else "disabled")
            buy_button.configure(state="normal" if item else "disabled")
            remove_button.configure(state="normal" if cart.selection() else "disabled")

        self._install_sortable_headings(
            catalog,
            {
                "#0": "Phim / tập",
                "rentable_copies": "Sẵn thuê",
                "sellable_copies": "Sẵn mua",
                "rent": "Giá gốc thuê",
                "buy": "Giá gốc mua",
            },
            picker_sort,
            lambda: (picker_page.set(1), refresh_catalog()),
        )
        def open_selected(_event=None):
            item_id = selected_item_id()
            item = catalog_rows.get(str(item_id)) if item_id is not None else None
            if item and item.show_id:
                select_season(item.show_id)
            elif item:
                add_for_item(item.item_id, LineAction.RENT)

        catalog.bind("<Double-1>", open_selected)
        catalog.bind("<<TreeviewSelect>>", update_action_buttons)
        cart.bind("<<TreeviewSelect>>", update_action_buttons)
        TreeviewTooltip(
            catalog,
            lambda item_id: (
                catalog_tooltip_text(catalog_rows[item_id]) if item_id in catalog_rows else ""
            ),
        )

        picker_timer = {}
        customer_timer = {}

        def reset_picker(*_args):
            refresh_generation["value"] += 1
            picker_page.set(1)
            self._debounce(picker_timer, refresh_catalog)

        for variable in (
            search,
            picker_type,
            picker_rent,
            picker_sell,
            picker_view,
            picker_genre,
            picker_year_from,
            picker_year_to,
            picker_rating,
            picker_format,
            picker_condition,
            picker_rental_min,
            picker_rental_max,
            picker_sale_min,
            picker_sale_max,
            picker_show,
            picker_season,
        ):
            variable.trace_add("write", reset_picker)
        customer_search_var.trace_add("write", lambda *_: self._debounce(customer_timer, refresh_customers))
        customer_var.trace_add("write", lambda *_: (show_customer(), sync_preorders(), update_quote(), reset_picker()))
        voucher_var.trace_add("write", lambda *_: update_quote())
        combo_var.trace_add("write", lambda *_: update_quote())
        premium_var.trace_add("write", lambda *_: update_quote())

        def refresh():
            picker_genres.clear()
            picker_genres.update({"Tất cả thể loại": None})
            picker_genres.update({genre.name: genre.id for genre in self.store.list_genres()})
            picker_genre_control.configure(values=tuple(picker_genres))
            picker_shows.clear()
            picker_shows.update({"Tất cả bộ": None})
            picker_shows.update({show.title: show.show_id for show in self.store.list_shows()})
            picker_show_control.configure(values=tuple(picker_shows))
            refresh_customers()
            sync_preorders()
            refresh_catalog()
            update_quote()

        page.refresh = refresh
