from __future__ import annotations

import tkinter as tk
from datetime import datetime
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X, Y
from ttkbootstrap.widgets.scrolled import ScrolledFrame

from normastore.application.contracts import CatalogFilters, PagedResult, PageRequest, SortSpec
from normastore.domain.enums import (
    ItemType,
    LineAction,
)
from normastore.ui.formatting import catalog_tooltip_text, vnd
from normastore.ui.tooltips import Tooltip, TreeviewTooltip
from normastore.ui.pages.inventory import CONDITION_LABELS, STATUS_LABELS

CATALOG_PRICE_MODES = {"Giá gốc": "DIRECT", "Theo tình trạng đĩa": "CONDITION", "Theo % giá gốc": "PERCENT"}
ITEM_TYPE_LABELS = {"Tất cả": "", "Phim lẻ": "MOVIE", "Tập phim": "EPISODE"}


class CatalogPageMixin:
    def catalog_page(self, page) -> None:
        bar = self._heading(page, "Phim & tập", "Nhấp đôi để xem phim bộ hoặc sửa phim lẻ")
        query, type_filter = tk.StringVar(), tk.StringVar(value="Tất cả")
        only_rent, only_sell = tk.BooleanVar(), tk.BooleanVar()
        view_mode = tk.StringVar(value="Danh sách")
        page_number = tk.IntVar(value=1)
        ttk.Button(bar, text="Tìm theo mô tả", command=lambda: search_description()).pack(
            side=RIGHT, padx=4
        )
        ttk.Combobox(
            bar, textvariable=view_mode, values=("Danh sách", "Thẻ"), width=12, state="readonly"
        ).pack(side=RIGHT, padx=4)
        filters = ttk.Labelframe(page, text="Tìm kiếm và bộ lọc", padding=(10, 7))
        filters.pack(fill=X, pady=(0, 8))
        basic = ttk.Frame(filters)
        basic.pack(fill=X)
        ttk.Label(basic, text="Từ khóa:").pack(side=LEFT)
        ttk.Entry(basic, textvariable=query, width=30).pack(side=LEFT, padx=(4, 10))
        ttk.Label(basic, text="Loại:").pack(side=LEFT)
        ttk.Combobox(
            basic,
            textvariable=type_filter,
            values=tuple(ITEM_TYPE_LABELS),
            width=11,
            state="readonly",
        ).pack(side=LEFT, padx=4)
        ttk.Checkbutton(basic, text="Còn thuê", variable=only_rent).pack(side=LEFT, padx=6)
        ttk.Checkbutton(basic, text="Còn mua", variable=only_sell).pack(side=LEFT, padx=6)
        advanced_visible = tk.BooleanVar(value=False)
        advanced = ttk.Frame(filters)
        genre_filter, year_from, year_to, rating_min = (
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
        )
        media_filter, condition_filter, status_filter = (
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
        )
        rental_min, rental_max, sale_min, sale_max = (
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
            tk.StringVar(),
        )
        show_filter, season_filter = tk.StringVar(), tk.StringVar()
        genres = {"Tất cả thể loại": None}
        genres.update({genre.name: genre.id for genre in self.store.list_genres()})
        shows = {"Tất cả bộ": None}
        shows.update({show.title: show.show_id for show in self.store.list_shows()})

        def toggle_advanced():
            if advanced_visible.get():
                advanced.pack_forget()
                advanced_visible.set(False)
                advanced_button.configure(text="Bộ lọc nâng cao ▾")
            else:
                advanced.pack(fill=X, pady=(7, 0))
                advanced_visible.set(True)
                advanced_button.configure(text="Thu gọn ▴")

        advanced_button = ttk.Button(
            basic, text="Bộ lọc nâng cao ▾", command=toggle_advanced, bootstyle="secondary"
        )
        advanced_button.pack(side=RIGHT)
        ttk.Button(
            basic, text="Xóa bộ lọc", command=lambda: clear_filters(), bootstyle="secondary"
        ).pack(side=RIGHT, padx=5)
        for index, (label, variable, values, width) in enumerate((
            ("Thể loại", genre_filter, tuple(genres), 16),
            ("Từ năm", year_from, (), 7),
            ("Đến năm", year_to, (), 7),
            ("Điểm ≥", rating_min, (), 7),
            ("Định dạng", media_filter, ("", "VHS", "VCD", "DVD", "Blu-ray"), 10),
            ("Tình trạng", condition_filter, ("", *CONDITION_LABELS.values()), 11),
            ("Kho", status_filter, ("", *STATUS_LABELS.values()), 16),
            ("Bộ", show_filter, tuple(shows), 18),
            ("Mùa", season_filter, (), 6),
            ("Giá gốc thuê từ", rental_min, (), 10),
            ("đến", rental_max, (), 10),
            ("Giá gốc mua từ", sale_min, (), 10),
            ("đến", sale_max, (), 10),
        )):
            row = index // 4
            ttk.Label(advanced, text=label).grid(row=row, column=(index % 4) * 2, sticky="w", padx=(0, 3), pady=3)
            widget = (
                ttk.Combobox(
                    advanced, textvariable=variable, values=values, width=width, state="readonly"
                )
                if values
                else ttk.Entry(advanced, textvariable=variable, width=width)
            )
            widget.grid(row=row, column=(index % 4) * 2 + 1, sticky="ew", padx=(0, 8), pady=3)
            if variable is show_filter:
                show_filter_control = widget
            if variable is genre_filter:
                genre_filter_control = widget
            advanced.columnconfigure((index % 4) * 2 + 1, weight=1)
        pane = ttk.Panedwindow(page, orient="horizontal")
        pane.pack(fill=BOTH, expand=True)
        left, right = ttk.Frame(pane, padding=5), ttk.Frame(pane, padding=12)
        pane.add(left, weight=3)
        pane.add(right, weight=2)
        tree = self._create_treeview(
            left,
            columns=("type", "rating", "rent", "sale", "rentable_copies", "sellable_copies"),
            show="tree headings",
            selectmode="extended",
        )
        tree.column("#0", width=235)
        tree.column("type", width=75)
        tree.column("rating", width=65)
        tree.column("rent", width=90)
        tree.column("sale", width=90)
        tree.column("rentable_copies", width=78)
        tree.column("sellable_copies", width=78)
        tree.pack(fill=BOTH, expand=True)
        card_area = ttk.Frame(left)
        card_canvas = tk.Canvas(card_area, highlightthickness=0)
        self._theme_canvases.append(card_canvas)
        card_canvas.configure(background=self.style.lookup("TFrame", "background"))
        card_scroll = ttk.Scrollbar(card_area, orient="vertical", command=card_canvas.yview)
        card_canvas.configure(yscrollcommand=card_scroll.set)
        card_canvas.pack(side=LEFT, fill=BOTH, expand=True)
        card_scroll.pack(side=RIGHT, fill=Y)
        card_container = ttk.Frame(card_canvas, padding=4)
        card_window = card_canvas.create_window((0, 0), window=card_container, anchor="nw")
        card_container.bind(
            "<Configure>",
            lambda _event: card_canvas.configure(scrollregion=card_canvas.bbox("all")),
        )
        card_canvas.bind(
            "<Configure>", lambda event: card_canvas.itemconfigure(card_window, width=event.width)
        )
        actions = ttk.Frame(left)
        actions.pack(fill=X, pady=5)
        management_state = "normal" if self._can_manage() else "disabled"
        add_button = ttk.Menubutton(actions, text="Thêm mới", state=management_state)
        add_menu = tk.Menu(add_button, tearoff=False)
        add_menu.add_command(label="Phim lẻ", command=lambda: edit(create=True))
        add_menu.add_command(label="Bộ phim", command=lambda: add_show())
        add_menu.add_command(label="Tập phim", command=lambda: bulk_episodes())
        add_menu.add_command(label="Đĩa", command=lambda: add_copy())
        add_button.configure(menu=add_menu)
        add_button.pack(side=LEFT, padx=3)
        ttk.Button(actions, text="Xem bộ phim", command=lambda: show_details()).pack(
            side=LEFT, padx=3
        )
        ttk.Button(
            actions, text="Sửa giá chọn", command=lambda: bulk_prices(), state=management_state
        ).pack(side=LEFT, padx=3)
        ttk.Button(
            actions, text="Lưu trữ chọn", command=lambda: archive(), state=management_state
        ).pack(side=LEFT, padx=3)
        pager_update = self._create_pager(left, page_number, lambda: refresh())
        detail = tk.StringVar(value="Chọn một phim/tập để xem thông tin.")
        ttk.Label(right, text="Chi tiết", font=("Segoe UI", 14, "bold"), bootstyle="primary").pack(
            anchor="w"
        )
        ttk.Label(right, textvariable=detail, justify=LEFT, wraplength=350).pack(
            anchor="nw", fill=X, pady=10
        )
        episode_box = ttk.Labelframe(right, text="Phim bộ", padding=8)
        episode_box.pack(fill=X, pady=6)
        ttk.Label(
            episode_box,
            text="Mở bộ phim để xem các mùa, hoặc thêm tập và đĩa từ menu Thêm mới.",
            wraplength=330,
        ).pack(anchor="w")
        rows = {}
        sort_state: dict[str, object] = {"field": "#0", "descending": False}

        def search_description():
            description = simpledialog.askstring(
                "Tìm phim theo mô tả",
                "Ví dụ: phim gia đình vui nhộn, hoạt hình, thập niên 1990:",
                parent=self,
            )
            if not description:
                return
            dialog = self._dialog("Kết quả tìm theo mô tả", 800, 500, modal=False)
            ttk.Label(dialog, text="Đang tìm bằng Gemini…", bootstyle="secondary").pack(
                anchor="w", padx=12, pady=10
            )

            def show_results(response):
                for child in dialog.winfo_children():
                    child.destroy()
                if response.warning:
                    ttk.Label(
                        dialog, text=response.warning, bootstyle="warning", wraplength=720
                    ).pack(anchor="w", padx=12, pady=(10, 4))
                result_tree = self._create_treeview(
                    dialog, columns=("overview", "source", "score"), show="tree headings"
                )
                result_tree.heading("#0", text="Phim / tập")
                result_tree.heading("overview", text="Tóm tắt")
                result_tree.heading("source", text="Nguồn")
                result_tree.heading("score", text="Điểm")
                result_tree.column("overview", width=480)
                result_tree.pack(fill=BOTH, expand=True, padx=12, pady=8)
                result_page = tk.IntVar(value=1)

                def load_results():
                    result_tree.delete(*result_tree.get_children())
                    size = 50
                    total_pages = max(1, (len(response.items) + size - 1) // size)
                    result_page.set(min(result_page.get(), total_pages))
                    start = (result_page.get() - 1) * size
                    for result in response.items[start : start + size]:
                        score = f"{result.score:.3f}" if result.score is not None else "—"
                        result_tree.insert(
                            "",
                            END,
                            iid=str(result.item_id),
                            text=result.title,
                            values=(result.overview[:180], result.source, score),
                        )
                    result_pager(
                        PagedResult(
                            tuple(), result_page.get(), size, len(response.items), total_pages
                        )
                    )

                result_pager = self._create_pager(dialog, result_page, load_results)
                load_results()
                if not response.items:
                    ttk.Label(dialog, text="Không có kết quả phù hợp trong kho nội bộ.").pack(
                        pady=8
                    )

            self._run_async(lambda: self.store.search_by_description_response(description), show_results)

        def decimal_value(value: str) -> Decimal | None:
            try:
                return Decimal(value.replace(".", "").replace(",", ".")) if value.strip() else None
            except Exception:
                return None

        def integer_value(value: str) -> int | None:
            try:
                return int(value) if value.strip() else None
            except ValueError:
                return None

        def catalog_filters() -> CatalogFilters:
            return CatalogFilters(
                text=query.get(),
                item_type=ITEM_TYPE_LABELS.get(type_filter.get(), ""),
                genre_id=genres.get(genre_filter.get()),
                year_from=integer_value(year_from.get()),
                year_to=integer_value(year_to.get()),
                rating_min=decimal_value(rating_min.get()),
                media_format=media_filter.get(),
                condition=next((key for key, label in CONDITION_LABELS.items() if label == condition_filter.get()), None),
                copy_status=next((key for key, label in STATUS_LABELS.items() if label == status_filter.get()), None),
                rental_price_min=decimal_value(rental_min.get()),
                rental_price_max=decimal_value(rental_max.get()),
                sale_price_min=decimal_value(sale_min.get()),
                sale_price_max=decimal_value(sale_max.get()),
                show_id=shows.get(show_filter.get()),
                season_number=integer_value(season_filter.get()),
                require_rentable=only_rent.get(),
                require_sellable=only_sell.get(),
            )

        refresh_generation = {"value": 0}

        def refresh():
            genres.clear()
            genres.update({"Tất cả thể loại": None})
            genres.update({genre.name: genre.id for genre in self.store.list_genres()})
            genre_filter_control.configure(values=tuple(genres))
            Tooltip.hide_active()
            tree.delete(*tree.get_children())
            rows.clear()
            for child in card_container.winfo_children():
                child.destroy()
            sort_field = {"#0": "title", "rent": "rental_price", "sale": "sale_price"}.get(
                str(sort_state["field"]), str(sort_state["field"])
            )
            sort = SortSpec(sort_field, bool(sort_state["descending"]))
            filters = catalog_filters()
            request = PageRequest(page_number.get(), 48)
            refresh_generation["value"] += 1
            generation = refresh_generation["value"]

            def render(result):
                if generation != refresh_generation["value"] or not page.winfo_exists():
                    return
                pager_update(result)
                for index, item in enumerate(result.items):
                    rows[str(item.item_id)] = item
                    tree.insert(
                        "",
                        END,
                        iid=str(item.item_id),
                        text=item.title,
                        values=(
                            "Phim lẻ" if item.item_type == ItemType.MOVIE else "Tập phim",
                            item.vote_average or "—",
                            vnd(item.rental_price),
                            vnd(item.sale_price),
                            item.rentable_copies,
                            item.sellable_copies,
                        ),
                    )
                    if view_mode.get() == "Thẻ":
                        card = ttk.Labelframe(
                            card_container, text=item.title, padding=7, style="Norma.Card.TLabelframe"
                        )
                        card.grid(row=index // 3, column=index % 3, sticky="nsew", padx=4, pady=4)
                        poster = ttk.Label(
                            card,
                            text="Đang tải\nposter",
                            width=10,
                            anchor="center",
                            justify="center",
                            style="Norma.CardMuted.TLabel",
                        )
                        poster.pack(side=LEFT, padx=(0, 8))
                        self._load_poster_thumbnail(item.poster_path, poster)
                        content = ttk.Frame(card, style="Norma.Card.TFrame")
                        content.pack(side=LEFT, fill=BOTH, expand=True)
                        ttk.Label(
                            content,
                            text=f"{'Phim lẻ' if item.item_type == ItemType.MOVIE else 'Tập phim'} • Điểm {item.vote_average or '—'}",
                            style="Norma.CardMuted.TLabel",
                        ).pack(anchor="w")
                        ttk.Label(
                            content,
                            text=f"Giá gốc: thuê {vnd(item.rental_price)} • mua {vnd(item.sale_price)}",
                            wraplength=150,
                            style="Norma.Card.TLabel",
                        ).pack(anchor="w", pady=(4, 0))
                        ttk.Label(
                            content,
                            text=f"Sẵn thuê: {item.rentable_copies} • Sẵn mua: {item.sellable_copies}",
                            style="Norma.Card.TLabel",
                        ).pack(anchor="w", pady=(2, 0))

                        def choose(item_id=item.item_id):
                            tree.selection_set(str(item_id))
                            tree.focus(str(item_id))
                            show_detail()

                        card.bind("<Button-1>", lambda _event, action=choose: action())
                        poster.bind("<Button-1>", lambda _event, action=choose: action())
                        content.bind("<Button-1>", lambda _event, action=choose: action())
                        for widget in (card, poster, content):
                            widget.bind("<Double-1>", lambda _event, item_id=item.item_id: open_item(item_id))
                        if self._can_manage():
                            menu_button = ttk.Menubutton(card, text="Thao tác")
                            menu = tk.Menu(menu_button, tearoff=False)
                            menu.add_command(label="Sửa", command=lambda item_id=item.item_id: select_and_run(item_id, edit))
                            menu.add_command(label="Thêm đĩa", command=lambda item_id=item.item_id: select_and_run(item_id, add_copy))
                            if item.show_id:
                                menu.add_command(label="Thêm tập", command=lambda show_id=item.show_id: bulk_episodes(show_id))
                            menu.add_command(label="Lưu trữ", command=lambda item_id=item.item_id: select_and_run(item_id, archive))
                            menu_button.configure(menu=menu)
                            menu_button.pack(side=RIGHT, anchor="s")
                        Tooltip(card, lambda current=item: catalog_tooltip_text(current))
                for column in range(3):
                    card_container.columnconfigure(column, weight=1)
                if view_mode.get() == "Thẻ":
                    tree.pack_forget()
                    card_area.pack(fill=BOTH, expand=True)
                else:
                    card_area.pack_forget()
                    tree.pack(fill=BOTH, expand=True)

            self._run_async(lambda: self.store.query_catalog(filters, request, sort), render)

        def selected():
            ids = tree.selection()
            row = rows.get(ids[0]) if ids else None
            return self.store.catalog_item(row.item_id) if row else None

        def select_and_run(item_id, action):
            tree.selection_set(str(item_id))
            tree.focus(str(item_id))
            action()

        def open_item(item_id):
            row = rows.get(str(item_id))
            if row is None:
                return
            if row.show_id:
                show_details(row.show_id)
            else:
                select_and_run(item_id, edit)

        def show_detail(_event=None):
            item = selected()
            if item:
                genres, reviews = self.store.catalog_metadata(item.id)
                genres_text = ", ".join(genres) or "Chưa có"
                reviews_text = (
                    "\n".join(
                        f"• {review.author} ({review.rating or '—'}): {review.content[:180]}"
                        for review in reviews
                    )
                    or "Chưa có đánh giá TMDB."
                )
                detail.set(
                    f"{item.title}\n\n{item.overview or 'Chưa có tóm tắt.'}\n\n"
                    f"Thể loại: {genres_text}\nĐiểm: {item.vote_average or '—'}\n"
                    f"Giá gốc thuê: {vnd(item.rental_price)} • mua: {vnd(item.sale_price)}\n"
                    f"Giá thực tế tùy theo bản đĩa.\n"
                    f"Cọc tính theo tỷ lệ giá bán của đĩa.\n\nĐánh giá TMDB:\n{reviews_text}"
                )

        def edit(_event=None, *, create=False):
            item = None if create else selected()
            dialog = self._dialog("Sửa phim/tập" if item else "Thêm phim/tập", 620, 680)
            footer = ttk.Frame(dialog, padding=(14, 0, 14, 14))
            footer.pack(fill=X, side="bottom")
            form = ScrolledFrame(dialog, padding=18, autohide=False)
            form.pack(fill=BOTH, expand=True)
            values = {
                "title": tk.StringVar(value=item.title if item else ""),
                "item_type": tk.StringVar(value="Tập phim" if item and item.item_type == ItemType.EPISODE else "Phim lẻ"),
                "overview": tk.StringVar(value=item.overview or "" if item else ""),
                "rental_price": tk.StringVar(value=str(item.rental_price) if item else "25000"),
                "sale_price": tk.StringVar(value=str(item.sale_price) if item else "200000"),
                "genres": tk.StringVar(value=", ".join(self.store.catalog_metadata(item.id)[0]) if item else ""),
            }
            for label, key in [
                ("Tên", "title"),
                ("Loại", "item_type"),
                ("Tóm tắt", "overview"),
                ("Thể loại (phân cách bằng dấu phẩy)", "genres"),
                ("Giá thuê", "rental_price"),
                ("Giá bán", "sale_price"),
            ]:
                ttk.Label(form, text=label).pack(anchor="w")
                widget = (
                    ttk.Combobox(
                        form,
                        textvariable=values[key],
                        values=(values["item_type"].get(),),
                        state="readonly",
                    )
                    if key == "item_type"
                    else ttk.Entry(form, textvariable=values[key], width=52)
                )
                widget.pack(fill=X, pady=(0, 7))

            poster_value = self._poster_editor(form, item.poster_path if item else None)

            ttk.Label(form, text="Ngày phát hành (để trống nếu chưa biết)").pack(anchor="w")
            release = tb.DateEntry(form, dateformat="%d/%m/%Y", popup_title="Chọn ngày phát hành")
            release.pack(fill=X, pady=(0, 7))
            release.entry.delete(0, "end")
            if item and item.release_date:
                release.entry.insert(0, item.release_date.strftime("%d/%m/%Y"))

            pricing = {}
            for label, prefix in (("thuê", "rental"), ("bán", "sale")):
                pricing[prefix + "_mode"] = tk.StringVar(value=next(name for name, code in CATALOG_PRICE_MODES.items() if code == (getattr(item, prefix + "_price_mode") if item else "DIRECT")))
                pricing[prefix + "_percent"] = tk.StringVar(value=str(getattr(item, prefix + "_price_percent") if item else 100))
                row = ttk.Frame(form)
                row.pack(fill=X, pady=3)
                ttk.Label(row, text=f"Cách tính giá {label}").pack(side=LEFT)
                ttk.Combobox(row, textvariable=pricing[prefix + "_mode"], values=tuple(CATALOG_PRICE_MODES), state="readonly", width=20).pack(side=LEFT, padx=5)
                ttk.Label(row, text="Tỷ lệ %").pack(side=LEFT)
                ttk.Entry(row, textvariable=pricing[prefix + "_percent"], width=8).pack(side=LEFT, padx=5)

            def save():
                try:
                    data = {"id": item.id} if item else {}
                    data.update(
                        title=values["title"].get(),
                        item_type=ITEM_TYPE_LABELS[values["item_type"].get()],
                        overview=values["overview"].get(),
                        genre_names=[name.strip() for name in values["genres"].get().split(",") if name.strip()],
                        rental_price=Decimal(values["rental_price"].get()),
                        sale_price=Decimal(values["sale_price"].get()),
                        release_date=datetime.strptime(release.entry.get().strip(), "%d/%m/%Y").date() if release.entry.get().strip() else None,
                        rental_price_mode=CATALOG_PRICE_MODES[pricing["rental_mode"].get()],
                        sale_price_mode=CATALOG_PRICE_MODES[pricing["sale_mode"].get()],
                        rental_price_percent=Decimal(pricing["rental_percent"].get()),
                        sale_price_percent=Decimal(pricing["sale_percent"].get()),
                        poster_path=poster_value(),
                    )
                    if item is None:
                        data["replacement_value"] = Decimal(values["sale_price"].get())
                    self.store.save_catalog_item(self.account.employee_id, **data)
                    dialog.destroy()
                    refresh()
                except Exception as exc:
                    messagebox.showerror("Lỗi", str(exc), parent=dialog)

            ttk.Button(footer, text="Lưu", command=save, bootstyle="primary").pack(
                fill=X, pady=(8, 0)
            )

        def add_copy():
            item = selected()
            if not item:
                return messagebox.showinfo("Kho", "Hãy chọn phim/tập trước.", parent=self)
            dialog = self._dialog("Thêm đĩa", 460, 300)
            form = ttk.Frame(dialog, padding=14)
            form.pack(fill=BOTH, expand=True)
            barcode, media = tk.StringVar(), tk.StringVar(value="DVD")
            can_rent, can_sell = (
                tk.BooleanVar(value=item.can_rent),
                tk.BooleanVar(value=item.can_sell),
            )
            location = tuple(tk.StringVar() for _ in range(3))
            ttk.Label(form, text="Mã vạch").pack(anchor="w")
            ttk.Entry(form, textvariable=barcode).pack(fill=X, pady=(2, 8))
            ttk.Label(form, text="Định dạng").pack(anchor="w")
            ttk.Combobox(
                form, textvariable=media, values=("VHS", "VCD", "DVD", "Blu-ray"), state="readonly"
            ).pack(fill=X, pady=(2, 8))
            ttk.Checkbutton(form, text="Cho thuê", variable=can_rent).pack(anchor="w")
            ttk.Checkbutton(form, text="Cho bán", variable=can_sell).pack(anchor="w")
            location_row = ttk.Frame(form)
            location_row.pack(fill=X, pady=5)
            for label, variable in zip(("Dãy", "Kệ", "Ngăn"), location):
                ttk.Label(location_row, text=label).pack(side=LEFT)
                ttk.Entry(location_row, textvariable=variable, width=10).pack(side=LEFT, padx=3)
            footer = ttk.Frame(dialog, padding=(14, 0, 14, 14))
            footer.pack(fill=X)

            def save():
                try:
                    self.store.add_copy(item.id, barcode.get(), media.get(), self.account.employee_id, can_rent.get(), can_sell.get(), *(v.get() for v in location))
                    dialog.destroy()
                    refresh()
                except Exception as exc:
                    messagebox.showerror("Thêm đĩa", str(exc), parent=dialog)

            ttk.Button(footer, text="Lưu", command=save, bootstyle="primary").pack(side=RIGHT)
            ttk.Button(footer, text="Hủy", command=dialog.destroy, bootstyle="secondary").pack(
                side=RIGHT, padx=6
            )

        def add_show():
            title = simpledialog.askstring("Thêm bộ phim", "Tên bộ phim:", parent=self)
            if not title:
                return
            overview = (
                simpledialog.askstring("Thêm bộ phim", "Tóm tắt (không bắt buộc):", parent=self)
                or ""
            )
            try:
                created = self.store.create_show(title, overview, self.account.employee_id)
                shows[title] = created.id
                show_filter_control.configure(values=tuple(shows))
                messagebox.showinfo(
                    "Phim bộ", "Đã tạo bộ phim. Bây giờ có thể thêm tập hàng loạt.", parent=self
                )
            except Exception as exc:
                messagebox.showerror("Phim bộ", str(exc), parent=self)

        def show_details(initial_show_id=None):
            shows = self.store.list_shows()
            if not shows:
                return messagebox.showinfo("Bộ phim", "Chưa có bộ phim nào.", parent=self)
            dialog = tb.Toplevel(self)
            dialog.title("Chi tiết bộ phim")
            dialog.geometry("1000x620")
            dialog.transient(self)
            pane = ttk.PanedWindow(dialog, orient="horizontal")
            pane.pack(fill=BOTH, expand=True, padx=12, pady=12)
            show_frame, detail_frame = ttk.Frame(pane, padding=4), ttk.Frame(pane, padding=4)
            pane.add(show_frame, weight=1)
            pane.add(detail_frame, weight=3)
            show_tree = self._create_treeview(
                show_frame, columns=("rating", "seasons"), show="tree headings"
            )
            show_tree.heading("#0", text="Bộ phim")
            show_tree.heading("rating", text="Điểm")
            show_tree.heading("seasons", text="Mùa")
            show_tree.column("#0", width=160, minwidth=100)
            show_tree.column("rating", width=55, minwidth=45)
            show_tree.column("seasons", width=55, minwidth=45)
            show_scroll = ttk.Scrollbar(show_frame, orient="vertical", command=show_tree.yview)
            show_tree.configure(yscrollcommand=show_scroll.set)
            show_scroll.pack(side=RIGHT, fill=Y)
            show_tree.pack(fill=BOTH, expand=True)
            by_id = {str(show.show_id): show for show in shows}
            for show in shows:
                show_tree.insert(
                    "",
                    END,
                    iid=str(show.show_id),
                    text=show.title,
                    values=(show.vote_average or "—", show.season_count),
                )
            detail = tk.StringVar(value="Chọn một bộ phim để xem thông tin và các tập.")
            ttk.Label(detail_frame, textvariable=detail, justify=LEFT, wraplength=610).pack(
                anchor="w", fill=X, pady=(0, 8)
            )
            season_var = tk.StringVar(value="Tất cả mùa")
            season_combo = ttk.Combobox(
                detail_frame, textvariable=season_var, state="readonly", width=18
            )
            season_combo.pack(anchor="w", pady=(0, 8))
            episode_actions = ttk.Frame(detail_frame)
            episode_actions.pack(side="bottom", fill=X, pady=(8, 0))
            def edit_show_poster():
                selected_show = show_tree.selection()
                if not selected_show:
                    return messagebox.showinfo("Ảnh bìa", "Hãy chọn bộ phim.", parent=dialog)
                show = by_id[selected_show[0]]
                editor = self._dialog("Ảnh bìa bộ phim", 560, 280)
                form = ttk.Frame(editor, padding=12)
                form.pack(fill=BOTH, expand=True)
                poster = self._poster_editor(form, show.poster_path)
                def save_poster():
                    try:
                        self.store.set_show_poster(show.show_id, poster(), self.account.employee_id)
                        editor.destroy()
                        dialog.destroy()
                        refresh()
                    except Exception as exc:
                        messagebox.showerror("Ảnh bìa", str(exc), parent=editor)
                ttk.Button(form, text="Lưu", command=save_poster, bootstyle="primary").pack(anchor="e", pady=6)
            ttk.Button(episode_actions, text="Ảnh bìa bộ phim", command=edit_show_poster,
                       state="normal" if self._can_manage() else "disabled").pack(side=RIGHT)
            episode_holder = ttk.Frame(detail_frame)
            episode_holder.pack(fill=BOTH, expand=True)
            episodes = self._create_treeview(
                episode_holder,
                columns=("season", "episode", "rating", "available", "sellable"),
                show="tree headings",
            )
            episodes.heading("#0", text="Tập phim")
            episodes.heading("season", text="Mùa")
            episodes.heading("episode", text="Tập")
            episodes.heading("rating", text="Điểm")
            episodes.heading("available", text="Sẵn thuê")
            episodes.heading("sellable", text="Sẵn mua")
            episodes.column("#0", width=300, minwidth=150)
            for column in ("season", "episode", "rating", "available", "sellable"):
                episodes.column(column, width=75, minwidth=55)
            ttk.Button(episode_actions, text="Thuê tập", command=lambda: send_to_checkout(LineAction.RENT), bootstyle="primary").pack(side=LEFT, padx=(0, 5))
            ttk.Button(episode_actions, text="Mua tập", command=lambda: send_to_checkout(LineAction.BUY), bootstyle="success").pack(side=LEFT)
            episode_vertical = ttk.Scrollbar(episode_holder, orient="vertical", command=episodes.yview)
            episode_horizontal = ttk.Scrollbar(episode_holder, orient="horizontal", command=episodes.xview)
            episodes.configure(yscrollcommand=episode_vertical.set, xscrollcommand=episode_horizontal.set)
            episode_vertical.pack(side=RIGHT, fill=Y)
            episode_horizontal.pack(side="bottom", fill=X)
            episodes.pack(fill=BOTH, expand=True)
            current_show_id: int | None = None

            def refresh_episodes(*_args):
                if current_show_id is None:
                    return
                selected_season = season_var.get()
                season_number = (
                    int(selected_season.removeprefix("Mùa "))
                    if selected_season.startswith("Mùa ")
                    else None
                )
                rows = self.store.list_show_episodes(current_show_id, season_number)
                episodes.delete(*episodes.get_children())
                for episode in rows:
                    episodes.insert(
                        "",
                        END,
                        iid=str(episode.item_id),
                        text=episode.title,
                        values=(
                            episode.season_number,
                            episode.episode_number,
                            episode.vote_average or "—",
                            episode.rentable_copies,
                            episode.sellable_copies,
                        ),
                    )

            def select_show(_event=None):
                nonlocal current_show_id
                selection = show_tree.selection()
                if not selection:
                    return
                current_show_id = int(selection[0])
                show = by_id[selection[0]]
                all_episodes = self.store.list_show_episodes(current_show_id)
                seasons = [
                    f"Mùa {number}"
                    for number in sorted({entry.season_number for entry in all_episodes})
                ]
                season_combo["values"] = ["Tất cả mùa", *seasons]
                season_var.set("Tất cả mùa")
                detail.set(
                    f"{show.title}\n\n{show.overview or 'Chưa có tóm tắt.'}\n\nĐiểm TMDB: {show.vote_average or '—'} • {show.season_count} mùa • {len(all_episodes)} tập"
                )
                refresh_episodes()

            show_tree.bind("<<TreeviewSelect>>", select_show)
            season_var.trace_add("write", refresh_episodes)

            def send_to_checkout(action):
                selection = episodes.selection()
                if not selection:
                    return messagebox.showinfo("Phim bộ", "Hãy chọn một tập phim.", parent=dialog)
                item_id = int(selection[0])
                dialog.destroy()
                self.show_page("Tạo phiếu", self.checkout_page)
                self.pages["Tạo phiếu"].add_catalog_item(item_id, action)

            initial = str(initial_show_id) if str(initial_show_id) in by_id else str(shows[0].show_id)
            show_tree.selection_set(initial)
            select_show()
            return dialog

        page.open_show_details = show_details

        def bulk_episodes(initial_show_id=None):
            shows = {
                f"{show.show_id} — {show.title}": show
                for show in self.store.list_shows()
            }
            if not shows:
                messagebox.showinfo("Tập phim", "Hãy thêm bộ phim trước.", parent=self)
                add_show()
                shows = {f"{show.show_id} — {show.title}": show for show in self.store.list_shows()}
                if not shows:
                    return
            dialog = tb.Toplevel(self)
            dialog.title("Thêm tập phim hàng loạt")
            dialog.transient(self)
            dialog.grab_set()
            form = ttk.Frame(dialog, padding=16)
            form.pack(fill=BOTH, expand=True)
            initial = next((name for name, show in shows.items() if show.show_id == initial_show_id), next(iter(shows)))
            show_var = tk.StringVar(value=initial)
            season_var, first_var, last_var, title_var = (
                tk.StringVar(value="1"),
                tk.StringVar(value="1"),
                tk.StringVar(value="10"),
                tk.StringVar(value="Tập {number}"),
            )
            for label, variable in [
                ("Bộ phim", show_var),
                ("Mùa", season_var),
                ("Tập đầu", first_var),
                ("Tập cuối", last_var),
                ("Mẫu tên", title_var),
            ]:
                ttk.Label(form, text=label).pack(anchor="w")
                widget = (
                    ttk.Combobox(
                        form, textvariable=variable, values=list(shows), state="readonly", width=52
                    )
                    if variable is show_var
                    else ttk.Entry(form, textvariable=variable, width=54)
                )
                widget.pack(fill=X, pady=(0, 7))

            def save_bulk():
                try:
                    show = shows[show_var.get()]
                    count = self.store.add_episodes_bulk(show.show_id, int(season_var.get()), int(first_var.get()), int(last_var.get()), title_var.get(), self.account.employee_id)
                    dialog.destroy()
                    refresh()
                    messagebox.showinfo("Tập phim", f"Đã thêm {len(count)} tập phim.", parent=self)
                except Exception as exc:
                    messagebox.showerror("Tập phim", str(exc), parent=dialog)

            ttk.Button(form, text="Thêm tập", command=save_bulk, bootstyle="primary").pack(
                fill=X, pady=(8, 0)
            )

        def archive():
            ids = [int(i) for i in tree.selection()]
            if ids and messagebox.askyesno("Lưu trữ", f"Lưu trữ {len(ids)} item đã chọn?"):
                self.store.archive_items(ids, self.account.employee_id)
                refresh()

        def bulk_prices():
            ids = [int(item_id) for item_id in tree.selection()]
            if not ids:
                return messagebox.showinfo(
                    "Sửa hàng loạt", "Hãy chọn các item cần cập nhật.", parent=self
                )
            rental = simpledialog.askstring(
                "Sửa hàng loạt", "Giá thuê mới (để trống để giữ nguyên):", parent=self
            )
            sale = simpledialog.askstring(
                "Sửa hàng loạt", "Giá bán mới (để trống để giữ nguyên):", parent=self
            )
            try:
                count = self.store.bulk_update_catalog_prices(ids, self.account.employee_id, Decimal(rental) if rental else None, Decimal(sale) if sale else None)
                messagebox.showinfo("Sửa hàng loạt", f"Đã cập nhật {count} item.", parent=self)
                refresh()
            except Exception as exc:
                messagebox.showerror("Sửa hàng loạt", str(exc), parent=self)

        def clear_filters():
            for variable in (
                query,
                type_filter,
                genre_filter,
                year_from,
                year_to,
                rating_min,
                media_filter,
                condition_filter,
                status_filter,
                rental_min,
                rental_max,
                sale_min,
                sale_max,
                show_filter,
                season_filter,
            ):
                variable.set("")
            type_filter.set("Tất cả")
            only_rent.set(False)
            only_sell.set(False)
            page_number.set(1)
            refresh()

        self._install_sortable_headings(
            tree,
            {
                "#0": "Tên phim / tập",
                "type": "Loại",
                "rating": "Điểm",
                "rent": "Giá gốc thuê",
                "sale": "Giá gốc mua",
                "rentable_copies": "Sẵn thuê",
                "sellable_copies": "Sẵn mua",
            },
            sort_state,
            lambda: (page_number.set(1), refresh()),
        )
        tree.bind("<<TreeviewSelect>>", show_detail)
        tree.bind("<Double-1>", lambda _event: open_item(tree.selection()[0]) if tree.selection() else None)
        if self._can_manage():
            def open_actions(event):
                item_id = tree.identify_row(event.y)
                if not item_id or item_id not in rows:
                    return
                tree.selection_set(item_id)
                tree.focus(item_id)
                menu = tk.Menu(tree, tearoff=False)
                menu.add_command(label="Sửa", command=edit)
                menu.add_command(label="Thêm đĩa", command=add_copy)
                if rows[item_id].show_id:
                    menu.add_command(label="Thêm tập", command=lambda: bulk_episodes(rows[item_id].show_id))
                    menu.add_command(label="Xem bộ phim", command=lambda: show_details(rows[item_id].show_id))
                menu.add_command(label="Lưu trữ", command=archive)
                menu.tk_popup(event.x_root, event.y_root)
            tree.bind("<Button-3>", open_actions)
        TreeviewTooltip(
            tree, lambda item_id: catalog_tooltip_text(rows[item_id]) if item_id in rows else ""
        )

        filter_timer = {}

        def reset_page(*_args):
            refresh_generation["value"] += 1
            page_number.set(1)
            self._debounce(filter_timer, refresh)

        for variable in (
            query,
            type_filter,
            only_rent,
            only_sell,
            genre_filter,
            year_from,
            year_to,
            rating_min,
            media_filter,
            condition_filter,
            status_filter,
            rental_min,
            rental_max,
            sale_min,
            sale_max,
            show_filter,
            season_filter,
            view_mode,
        ):
            variable.trace_add("write", reset_page)
        page.refresh = refresh
