from __future__ import annotations

import tkinter as tk
from datetime import datetime
from decimal import Decimal
from tkinter import messagebox, ttk

import ttkbootstrap as tb

from normastore.application.contracts import PageRequest
from normastore.domain.enums import LineAction

from ttkbootstrap.constants import BOTH, END, LEFT, X

from normastore.ui.formatting import vnd


class DashboardPageMixin:
    def dashboard_page(self, page) -> None:
        self._heading(page, "Tổng quan", "Tình hình cửa hàng hôm nay")
        cards = ttk.Frame(page)
        cards.pack(fill=X)
        fields = [
            ("available", "Có sẵn", "success"),
            ("rented", "Đang thuê", "primary"),
            ("overdue", "Quá hạn", "danger"),
            ("reservations", "Đặt trước", "warning"),
        ]
        labels = {}
        for key, title, style in fields:
            card = ttk.Labelframe(cards, text=title, padding=15, bootstyle=style)
            card.pack(side=LEFT, fill=X, expand=True, padx=4)
            labels[key] = ttk.Label(card, text="—", font=("Segoe UI", 20, "bold"))
            labels[key].pack()
        revenue = ttk.Label(page, text="", font=("Segoe UI", 13, "bold"), bootstyle="primary")
        revenue.pack(anchor="w", padx=5, pady=16)
        quick = ttk.Labelframe(page, text="Thao tác nhanh", padding=12)
        quick.pack(fill=X, padx=4)
        ttk.Button(
            quick,
            text="Tạo phiếu",
            command=lambda: self.show_page("Tạo phiếu", self.checkout_page),
            bootstyle="primary",
        ).pack(side=LEFT, padx=4)
        ttk.Button(
            quick,
            text="Nhập phim/tập",
            command=lambda: self.show_page("Phim & tập", self.catalog_page),
        ).pack(side=LEFT, padx=4)
        def add_copy():
            self.show_page("Kho đĩa", self.inventory_page)
            self.pages["Kho đĩa"].add_copy()

        def add_copies_csv():
            self.show_page("Kho đĩa", self.inventory_page)
            self.pages["Kho đĩa"].import_copies_csv()

        import_button = ttk.Menubutton(quick, text="Nhập đĩa",
                                       state="normal" if self._can_manage() else "disabled")
        import_menu = tk.Menu(import_button, tearoff=False)
        import_menu.add_command(label="Nhập thủ công", command=add_copy)
        import_menu.add_command(label="Nhập từ CSV", command=add_copies_csv)
        import_button.configure(menu=import_menu)
        import_button.pack(side=LEFT, padx=4)
        tabs = ttk.Notebook(page)
        tabs.pack(fill=BOTH, expand=True, padx=4, pady=(14, 0))
        trees = {}
        page_numbers = {key: tk.IntVar(value=1) for key in ("stock", "upcoming")}
        pagers = {}
        for key, title, columns in (
            ("stock", "Sắp hết / hết", (("rent", "Sẵn thuê"), ("sell", "Sẵn bán"))),
            ("hot", "Phim hot", (("count", "Lượt thuê (30 ngày)"),)),
            ("sales", "Bán chạy", (("count", "Lượt mua (30 ngày)"),)),
            ("discovery", "Khám phá", (("count", "Lượt trong 30 ngày"), ("discount", "Ưu đãi"))),
            ("random", "Ngẫu nhiên", (("reason", "Đề xuất"),)),
            ("upcoming", "Sắp ra", (("release", "Ngày phát hành"),)),
            ("recommendations", "Đề cử", (("reason", "Lý do"),)),
        ):
            frame = ttk.Frame(tabs, padding=8)
            tabs.add(frame, text=title)
            tree = self._create_treeview(
                frame, columns=tuple(column for column, _ in columns), show="tree headings",
                selectmode="extended",
            )
            tree.heading("#0", text="Phim / tập")
            for column, label in columns:
                tree.heading(column, text=label)
            tree.pack(fill=BOTH, expand=True)
            trees[key] = tree
            if key in page_numbers:
                pagers[key] = self._create_pager(frame, page_numbers[key], lambda current=key: reload_tab(current))
        upcoming = trees["upcoming"]

        def open_stock(_event=None):
            selection = trees["stock"].selection()
            if not selection:
                return
            try:
                item = self.store.catalog_item(int(selection[0]))
                self.show_page("Kho đĩa", self.inventory_page)
                self.pages["Kho đĩa"].show_item(item.id, item.title, item.show_id)
            except Exception as exc:
                messagebox.showerror("Kho đĩa", str(exc), parent=self)

        trees["stock"].bind("<Double-1>", open_stock)
        ttk.Button(trees["stock"].master, text="Xem trong kho", command=open_stock).pack(anchor="e", pady=5)

        def reserve_upcoming():
            selected = upcoming.selection()
            if not selected:
                return messagebox.showinfo("Đặt trước", "Hãy chọn phim sắp phát hành.", parent=self)
            dialog = self._dialog("Đặt trước phim sắp ra", 520, 280)
            choices = {}
            search = tk.StringVar()
            ttk.Label(dialog, text="Tìm khách theo tên hoặc số điện thoại", padding=(10, 8, 10, 0)).pack(anchor="w")
            ttk.Entry(dialog, textvariable=search).pack(fill=X, padx=10)
            ttk.Label(dialog, text="Chọn khách hàng", padding=10).pack(anchor="w")
            picker = ttk.Combobox(dialog, state="readonly")
            picker.pack(fill=X, padx=10)

            def load_customers():
                if not dialog.winfo_exists():
                    return
                previous = picker.get()
                choices.clear()
                choices.update({f"{c.id} — {c.full_name} ({c.phone})": c.id for c in self.store.list_customers(search.get())})
                picker.configure(values=list(choices))
                picker.set(previous if previous in choices else next(iter(choices), ""))

            search_timer = {}
            search.trace_add("write", lambda *_: self._debounce(search_timer, load_customers))
            load_customers()

            def confirm():
                if picker.get() not in choices:
                    return messagebox.showinfo("Đặt trước", "Hãy chọn khách hàng.", parent=dialog)
                try:
                    self.store.reserve(choices[picker.get()], [int(selected[0])], self.account.employee_id)
                    dialog.destroy()
                    messagebox.showinfo("Đặt trước", "Đã ghi nhận đặt trước; thanh toán khi nhận đĩa.", parent=self)
                except Exception as exc:
                    messagebox.showerror("Đặt trước", str(exc), parent=dialog)

            ttk.Button(dialog, text="Xác nhận", command=confirm, bootstyle="primary").pack(pady=12)

        ttk.Button(upcoming.master, text="Đặt trước", command=reserve_upcoming).pack(anchor="e", pady=5)
        loaded = set()
        generation = {"value": 0}
        keys = ("stock", "hot", "sales", "discovery", "random", "upcoming", "recommendations")
        tab_generations = {key: 0 for key in keys}
        discovery_rows = {}

        def create_order(key):
            selection = trees[key].selection()
            if not selection:
                return messagebox.showinfo("Tạo phiếu", "Hãy chọn phim hoặc tập phim.", parent=self)
            self.show_page("Tạo phiếu", self.checkout_page)
            checkout_page = self.pages["Tạo phiếu"]
            if key == "upcoming":
                checkout_page.open_reservations([int(target) for target in selection])
                return
            action = LineAction.BUY if key == "sales" else LineAction.RENT
            for index, target in enumerate(selection):
                if target.startswith("show:"):
                    dialog = checkout_page.select_season(int(target[5:]), action)
                    if dialog is not None and index < len(selection) - 1:
                        self.wait_window(dialog)
                else:
                    checkout_page.add_catalog_item(int(target), action)

        for key in ("hot", "sales", "discovery", "random", "upcoming", "recommendations"):
            trees[key].bind("<Double-1>", lambda _event, current=key: create_order(current))
            ttk.Button(trees[key].master, text="Tạo phiếu", command=lambda current=key: create_order(current)).pack(anchor="e", pady=3)
            ttk.Label(trees[key].master, text="Giữ Ctrl hoặc Shift để chọn nhiều phim.",
                      bootstyle="secondary").pack(anchor="w")

        def load_tab(_event=None):
            index = tabs.index(tabs.select())
            key = keys[index]
            if key in loaded:
                return
            loaded.add(key)
            token = generation["value"]
            tab_generations[key] += 1
            tab_token = tab_generations[key]
            request = PageRequest(page_numbers[key].get(), 50) if key in page_numbers else None
            work = {
                "stock": lambda: self.store.query_dashboard_low_stock(request),
                "hot": lambda: self.store.dashboard_popular_targets(LineAction.RENT),
                "sales": lambda: self.store.dashboard_popular_targets(LineAction.BUY),
                "discovery": self.store.dashboard_discovery,
                "random": self.store.dashboard_random,
                "upcoming": lambda: self.store.query_dashboard_upcoming(request),
                "recommendations": self.store.today_recommendations,
            }[key]

            def done(result):
                if token != generation["value"] or tab_token != tab_generations[key] or not page.winfo_exists():
                    return
                if key in pagers:
                    pagers[key](result)
                    rows = result.items
                else:
                    rows = result
                tree = trees[key]
                tree.delete(*tree.get_children())
                if key == "discovery":
                    discovery_rows.clear()
                for row in rows:
                    if key == "stock":
                        item_id, title, rent, sell = row
                        tree.insert("", END, iid=str(item_id), text=title, values=(rent, sell))
                    elif key == "upcoming":
                        item_id, title, release = row
                        tree.insert("", END, iid=str(item_id), text=title, values=(release.strftime("%d/%m/%Y"),))
                    elif key == "recommendations":
                        tree.insert("", END, iid=str(row.item_id), text=row.title, values=(row.reason,))
                    elif key == "discovery":
                        item_id, title, count, active, percent, starts, ends = row
                        discovery_rows[str(item_id)] = row
                        summary = f"{percent}% ({starts or 'không giới hạn'} – {ends or 'không giới hạn'})" if active else "Chưa bật"
                        tree.insert("", END, iid=str(item_id), text=title, values=(count, summary))
                    elif key == "random":
                        item_id, title = row
                        tree.insert("", END, iid=str(item_id), text=title, values=("Phim còn đĩa",))
                    else:
                        show_id, item_id, title, count = row
                        target = f"show:{show_id}" if show_id else str(item_id)
                        tree.insert("", END, iid=target, text=title, values=(count,))

            def failed(exc):
                if token != generation["value"] or tab_token != tab_generations[key] or not page.winfo_exists():
                    return
                loaded.discard(key)
                messagebox.showerror("Tổng quan", str(exc), parent=self)

            self._run_async(work, done, failed)

        def reload_tab(key):
            loaded.discard(key)
            if keys[tabs.index(tabs.select())] == key:
                load_tab()

        tabs.bind("<<NotebookTabChanged>>", load_tab)

        def edit_discovery():
            selected = trees["discovery"].selection()
            if not selected or selected[0] not in discovery_rows:
                return messagebox.showinfo("Khám phá", "Hãy chọn phim cần điều chỉnh.", parent=self)
            item_id, title, _count, active, percent, starts, ends = discovery_rows[selected[0]]
            dialog = self._dialog("Ưu đãi khám phá", 500, 360)
            frame = ttk.Frame(dialog, padding=12)
            frame.pack(fill=BOTH, expand=True)
            ttk.Label(frame, text=title, wraplength=450).pack(anchor="w")
            enabled = tk.BooleanVar(value=active)
            amount = tk.StringVar(value=str(percent if percent else 10))
            ttk.Checkbutton(frame, text="Bật ưu đãi", variable=enabled).pack(anchor="w", pady=5)
            ttk.Label(frame, text="Giảm (%)").pack(anchor="w")
            ttk.Entry(frame, textvariable=amount).pack(fill=X)
            date_entries = []
            for label, value in (("Bắt đầu (có thể để trống)", starts), ("Kết thúc (có thể để trống)", ends)):
                ttk.Label(frame, text=label).pack(anchor="w", pady=(5, 0))
                entry = tb.DateEntry(frame, dateformat="%d/%m/%Y", popup_title=label)
                entry.entry.delete(0, END)
                if value:
                    entry.entry.insert(0, value.strftime("%d/%m/%Y"))
                entry.pack(fill=X)
                date_entries.append(entry)

            def close():
                nonlocal enabled, amount
                dialog.destroy()
                enabled = amount = None

            dialog.protocol("WM_DELETE_WINDOW", close)

            def save():
                try:
                    dates = [datetime.strptime(entry.entry.get().strip(), "%d/%m/%Y").date() if entry.entry.get().strip() else None for entry in date_entries]
                    self.store.set_discovery_discount(item_id, Decimal(amount.get().replace(",", ".")), enabled.get(), dates[0], dates[1], self.account.employee_id)
                    close()
                    loaded.discard("discovery")
                    load_tab()
                except Exception as exc:
                    messagebox.showerror("Khám phá", str(exc), parent=dialog)

            ttk.Button(frame, text="Lưu ưu đãi", command=save, bootstyle="primary").pack(anchor="e", pady=8)

        ttk.Button(trees["discovery"].master, text="Thiết lập ưu đãi", command=edit_discovery,
                   state="normal" if self._can_manage() else "disabled").pack(anchor="e", pady=5)
        ttk.Button(trees["random"].master, text="Đề cử lại",
                   command=lambda: (loaded.discard("random"), load_tab())).pack(anchor="e", pady=5)

        def refresh():
            generation["value"] += 1
            loaded.clear()
            token = generation["value"]

            def done(stats):
                if token != generation["value"] or not page.winfo_exists():
                    return
                for key in labels:
                    labels[key].configure(text=str(stats[key]))
                revenue.configure(text=f"Dòng tiền thuần hôm nay (gồm cọc): {vnd(stats['cash_flow'])}")

            self._run_async(self.store.dashboard, done)
            load_tab()
            self._refresh_status()

        page.refresh = refresh
