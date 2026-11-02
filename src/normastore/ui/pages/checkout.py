from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X, Y

from normastore.application.contracts import CatalogFilters, CheckoutLine, PageRequest, PaymentInput, SortSpec
from normastore.domain.enums import (
    CopyCondition,
    CopyStatus,
    LineAction,
)
from normastore.application.contracts import CustomerView
from normastore.ui.formatting import catalog_tooltip_text, vnd
from normastore.ui.tooltips import Tooltip, TreeviewTooltip


class CheckoutPageMixin:
    def checkout_page(self, page) -> None:
        self._heading(page, "Lập phiếu thuê / mua", "Chọn phim rồi thêm vào giỏ")
        top = ttk.Frame(page)
        top.pack(fill=X, pady=(0, 8))
        customer_var = tk.StringVar()
        customer_search_var = tk.StringVar()
        customer_combo = ttk.Combobox(top, textvariable=customer_var, state="readonly", width=38)
        ttk.Label(top, text="Khách hàng:").pack(side=LEFT)
        ttk.Entry(top, textvariable=customer_search_var, width=18).pack(side=LEFT, padx=(6, 0))
        customer_combo.pack(side=LEFT, padx=6)
        ttk.Button(
            top, text="Thêm khách", command=lambda: self._quick_customer(customer_combo)
        ).pack(side=LEFT)
        ttk.Label(top, text="Hạn trả:").pack(side=LEFT, padx=(18, 3))
        due_var = tk.StringVar(value=(date.today() + timedelta(days=3)).isoformat())
        ttk.Entry(top, textvariable=due_var, width=12).pack(side=LEFT)
        ttk.Label(top, text="Voucher:").pack(side=LEFT, padx=(18, 3))
        voucher_var = tk.StringVar()
        voucher_combo = ttk.Combobox(top, textvariable=voucher_var, width=14)
        voucher_combo.pack(side=LEFT)
        ttk.Label(top, text="Combo:").pack(side=LEFT, padx=(18, 3))
        combo_var = tk.StringVar()
        combo_combo = ttk.Combobox(top, textvariable=combo_var, state="readonly", width=24)
        combo_combo.pack(side=LEFT)
        pane = ttk.Panedwindow(page, orient="horizontal")
        pane.pack(fill=BOTH, expand=True)
        catalog_frame, cart_frame = ttk.Frame(pane, padding=5), ttk.Frame(pane, padding=5)
        pane.add(catalog_frame, weight=3)
        pane.add(cart_frame, weight=2)
        search, picker_type = tk.StringVar(), tk.StringVar()
        picker_rent, picker_sell = tk.BooleanVar(), tk.BooleanVar()
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
            values=("", "MOVIE", "EPISODE"),
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
                picker_advanced.pack(fill=X, pady=(0, 5))
                picker_advanced_open.set(True)
                picker_advanced_button.configure(text="Thu gọn ▴")

        picker_advanced_button = ttk.Button(
            picker_filters,
            text="Lọc nâng cao ▾",
            command=toggle_picker_advanced,
            bootstyle="secondary",
        )
        picker_advanced_button.pack(side=RIGHT, padx=5)
        for label, variable, values, width in (
            ("Thể loại", picker_genre, tuple(picker_genres), 14),
            ("Từ năm", picker_year_from, (), 6),
            ("Đến", picker_year_to, (), 6),
            ("Rating ≥", picker_rating, (), 6),
            ("Định dạng", picker_format, ("", "VHS", "VCD", "DVD", "Blu-ray"), 9),
            ("Tình trạng", picker_condition, ("", *[value.value for value in CopyCondition]), 10),
            ("Bộ", picker_show, tuple(picker_shows), 16),
            ("Mùa", picker_season, (), 5),
            ("Thuê từ", picker_rental_min, (), 8),
            ("đến", picker_rental_max, (), 8),
            ("Mua từ", picker_sale_min, (), 8),
            ("đến", picker_sale_max, (), 8),
        ):
            ttk.Label(picker_advanced, text=label).pack(side=LEFT, padx=(0, 2))
            control = (
                ttk.Combobox(
                    picker_advanced,
                    textvariable=variable,
                    values=values,
                    width=width,
                    state="readonly",
                )
                if values
                else ttk.Entry(picker_advanced, textvariable=variable, width=width)
            )
            control.pack(side=LEFT, padx=(0, 4))
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
            cart_frame, columns=("action", "price", "due"), show="tree headings"
        )
        cart.heading("#0", text="Bản đĩa")
        cart.heading("action", text="Loại")
        cart.heading("price", text="Giá")
        cart.heading("due", text="Hạn trả")
        cart.column("#0", width=180)
        cart.column("action", width=65)
        cart.column("price", width=90)
        cart.column("due", width=90)
        cart.pack(fill=BOTH, expand=True)
        total_var = tk.StringVar(value="Tổng cần thu: 0 đ")
        ttk.Label(
            cart_frame, textvariable=total_var, font=("Segoe UI", 11, "bold"), bootstyle="success"
        ).pack(anchor="e", pady=6)
        buttons = ttk.Frame(cart_frame)
        buttons.pack(fill=X)
        cart_lines: list[CheckoutLine] = []
        catalog_rows = {}
        customers: dict[str, CustomerView] = {}
        combos = {}

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
                key = f"{combo.combo_id} — {combo.name} ({vnd(combo.discount_amount)})"
                combos[key] = combo
                combo_values.append(key)
            combo_combo["values"] = combo_values
            if not combo_var.get():
                combo_var.set(combo_values[0])
            voucher_combo["values"] = [
                "",
                *[
                    voucher.code
                    for voucher in self.store.list_vouchers()
                    if voucher.effective_state == "Đang hiệu lực"
                ],
            ]

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
                item_type=picker_type.get(),
                genre_id=picker_genres.get(picker_genre.get()),
                year_from=picker_year(picker_year_from.get()),
                year_to=picker_year(picker_year_to.get()),
                rating_min=picker_number(picker_rating.get()),
                media_format=picker_format.get(),
                condition=CopyCondition(picker_condition.get()) if picker_condition.get() else None,
                copy_status=CopyStatus.AVAILABLE,
                rental_price_min=picker_number(picker_rental_min.get()),
                rental_price_max=picker_number(picker_rental_max.get()),
                sale_price_min=picker_number(picker_sale_min.get()),
                sale_price_max=picker_number(picker_sale_max.get()),
                show_id=picker_shows.get(picker_show.get()),
                season_number=picker_year(picker_season.get()),
                require_rentable=picker_rent.get(),
                require_sellable=picker_sell.get(),
            )

        def refresh_catalog():
            Tooltip.hide_active()
            catalog.delete(*catalog.get_children())
            catalog_rows.clear()
            for child in picker_container.winfo_children():
                child.destroy()
            field = {"#0": "title", "rent": "rental_price", "buy": "sale_price"}.get(
                str(picker_sort["field"]), str(picker_sort["field"])
            )
            result = self.store.query_catalog(picker_catalog_filters(), PageRequest(picker_page.get(), 48), SortSpec(field, bool(picker_sort['descending'])))
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
                        vnd(item.rental_price),
                        vnd(item.sale_price),
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
                        text=f"{item.item_type.value} • Rating {item.vote_average or '—'}",
                        style="Norma.CardMuted.TLabel",
                    ).pack(anchor="w")
                    ttk.Label(
                        body,
                        text=f"Thuê {vnd(item.rental_price)} • Mua {vnd(item.sale_price)}",
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
                        command=lambda ident=item.item_id: add_for_item(ident, LineAction.RENT),
                        state="normal" if item.rentable_copies else "disabled",
                        bootstyle="primary",
                    ).pack(side=LEFT, pady=(5, 0))
                    ttk.Button(
                        body,
                        text="+ Mua",
                        command=lambda ident=item.item_id: add_for_item(ident, LineAction.BUY),
                        state="normal" if item.sellable_copies else "disabled",
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

        def selected_item_id() -> int | None:
            ids = catalog.selection()
            return int(ids[0]) if ids else None

        def add_for_item(item_id: int | None, action: LineAction):
            if not item_id:
                return messagebox.showinfo(
                    "Phiếu", "Hãy chọn một item còn bản đĩa trống.", parent=self
                )
            try:
                due = date.fromisoformat(due_var.get()) if action == LineAction.RENT else None
            except ValueError:
                return messagebox.showerror(
                    "Phiếu", "Ngày hẹn trả phải theo dạng YYYY-MM-DD.", parent=self
                )
            try:
                used = {line.copy_id for line in cart_lines}
                choice = self.store.choose_checkout_copy(item_id, action, used)
                if not choice:
                    return messagebox.showinfo(
                        "Phiếu", "Không còn bản đĩa phù hợp cho thao tác này.", parent=self
                    )
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
                update_quote()
                refresh_catalog()
            except Exception as exc:
                messagebox.showerror("Phiếu", str(exc), parent=self)

        def add(action: LineAction):
            add_for_item(selected_item_id(), action)

        def update_quote():
            customer = customers.get(customer_var.get())
            if not customer or not cart_lines:
                total_var.set("Tổng cần thu: 0 đ")
                return
            try:
                quote = self.store.quote(customer.id, cart_lines, voucher_var.get() or None, combo_ids())
                total_var.set(f"Tổng cần thu: {vnd(quote.total_due)} (cọc {vnd(quote.deposit)})")
            except Exception as exc:
                total_var.set(f"Kiểm tra: {exc}")

        def remove():
            ids = cart.selection()
            if ids:
                selected_ids = {int(value) for value in ids}
                cart_lines[:] = [line for line in cart_lines if line.copy_id not in selected_ids]
                for value in ids:
                    cart.delete(value)
                update_quote()
                refresh_catalog()

        def checkout():
            customer = customers.get(customer_var.get())
            if not customer:
                return messagebox.showerror("Phiếu", "Hãy chọn khách hàng.", parent=self)
            if not self.current_shift:
                return messagebox.showerror("Phiếu", "Cần mở ca trước khi lập phiếu.", parent=self)
            try:
                quote = self.store.quote(customer.id, cart_lines, voucher_var.get() or None, combo_ids())
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
                order = self.store.checkout(customer.id, self.account.employee_id, self.current_shift.id, cart_lines, [PaymentInput(method, Decimal(received))], voucher_var.get() or None, combo_ids())
                messagebox.showinfo("Hoàn tất", f"Đã tạo phiếu {order.code}.", parent=self)
                cart_lines.clear()
                cart.delete(*cart.get_children())
                refresh_catalog()
                update_quote()
                self._refresh_status()
            except Exception as exc:
                messagebox.showerror("Phiếu", str(exc), parent=self)

        rent_button = ttk.Button(
            buttons, text="+ Thuê", command=lambda: add(LineAction.RENT), bootstyle="primary"
        )
        buy_button = ttk.Button(
            buttons, text="+ Mua", command=lambda: add(LineAction.BUY), bootstyle="success"
        )
        remove_button = ttk.Button(buttons, text="Bỏ dòng", command=remove, bootstyle="secondary")
        rent_button.pack(side=LEFT, padx=2)
        buy_button.pack(side=LEFT, padx=2)
        remove_button.pack(side=LEFT, padx=2)
        ttk.Button(buttons, text="Hoàn tất", command=checkout, bootstyle="warning").pack(
            side=RIGHT, padx=2
        )
        picker_pager = self._create_pager(catalog_frame, picker_page, refresh_catalog)

        def update_action_buttons(_event=None):
            item = catalog_rows.get(catalog.selection()[0]) if catalog.selection() else None
            rent_button.configure(state="normal" if item and item.rentable_copies else "disabled")
            buy_button.configure(state="normal" if item and item.sellable_copies else "disabled")
            remove_button.configure(state="normal" if cart.selection() else "disabled")

        self._install_sortable_headings(
            catalog,
            {
                "#0": "Phim / tập",
                "rentable_copies": "Sẵn thuê",
                "sellable_copies": "Sẵn mua",
                "rent": "Thuê",
                "buy": "Mua",
            },
            picker_sort,
            lambda: (picker_page.set(1), refresh_catalog()),
        )
        catalog.bind("<Double-1>", lambda _e: add(LineAction.RENT))
        catalog.bind("<<TreeviewSelect>>", update_action_buttons)
        cart.bind("<<TreeviewSelect>>", update_action_buttons)
        TreeviewTooltip(
            catalog,
            lambda item_id: (
                catalog_tooltip_text(catalog_rows[item_id]) if item_id in catalog_rows else ""
            ),
        )

        def reset_picker(*_args):
            picker_page.set(1)
            self.after(250, refresh_catalog)

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
        customer_search_var.trace_add("write", lambda *_: self.after(250, refresh_customers))
        customer_var.trace_add("write", lambda *_: update_quote())
        voucher_var.trace_add("write", lambda *_: update_quote())
        combo_var.trace_add("write", lambda *_: update_quote())

        def refresh():
            refresh_customers()
            refresh_catalog()
            update_quote()

        page.refresh = refresh
