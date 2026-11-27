from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable
from unicodedata import combining, normalize

import ttkbootstrap as tb
from ttkbootstrap.constants import LEFT, RIGHT, X

from normastore.application.contracts import CustomerView, ShowSummary
from normastore.domain.enums import PaymentMethod


class CommonWidgetsMixin:
    def _searchable_show_picker(
        self, parent, shows: list[ShowSummary], selected: tk.StringVar,
        initial_show_id: int | None = None,
    ) -> dict[str, int]:
        def search_key(value: str) -> str:
            value = value.casefold().replace("đ", "d")
            return "".join(char for char in normalize("NFD", value) if not combining(char))

        show_ids = {f"{show.title} (#{show.show_id})": show.show_id for show in shows}
        titles = {label: search_key(show.title) for label, show in zip(show_ids, shows)}
        search = tk.StringVar()
        ttk.Label(parent, text="Tìm phim bộ:").pack(anchor="w")
        ttk.Entry(parent, textvariable=search).pack(fill=X, pady=(0, 4))
        caption = ttk.Label(parent, text="Bộ phim")
        caption.pack(anchor="w")
        combo = ttk.Combobox(parent, textvariable=selected, values=tuple(show_ids), state="readonly")
        combo.pack(fill=X)
        selected.set(next((label for label, key in show_ids.items() if key == initial_show_id), ""))

        def filter_shows(*_args):
            term = search_key(search.get().strip())
            matches = tuple(label for label, title in titles.items() if term in title)
            combo.configure(values=matches, state="readonly" if matches else "disabled")
            caption.configure(text="Bộ phim" if matches else "Không tìm thấy phim bộ.")
            if selected.get() not in matches:
                replacement = matches[0] if len(matches) == 1 else ""
                if selected.get() != replacement:
                    selected.set(replacement)

        search.trace_add("write", filter_shows)
        return show_ids

    def _open_catalog_details(self, item_id: int, parent=None) -> None:
        from normastore.ui.formatting import vnd

        item = self.store.catalog_item(item_id)
        genres, reviews = self.store.catalog_metadata(item_id)
        dialog = self._dialog("Chi tiết phim / tập", 650, 520)
        if parent is not None:
            dialog.transient(parent)
            def close_details():
                dialog.destroy()
                if parent.winfo_exists():
                    parent.grab_set()
            dialog.protocol("WM_DELETE_WINDOW", close_details)
        frame = ttk.Frame(dialog, padding=14)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text=item.title, font=self._font("section"), wraplength=590).pack(anchor="w")
        poster = ttk.Label(frame)
        poster.pack(anchor="w", pady=5)
        poster_path = item.poster_path
        if not poster_path and item.show_id:
            poster_path = next((show.poster_path for show in self.store.list_shows() if show.show_id == item.show_id), None)
        self._load_poster_thumbnail(poster_path, poster)
        text = (f"{item.overview or 'Chưa có tóm tắt.'}\n\n"
                f"Thể loại: {', '.join(genres) or 'Chưa có'}\n"
                f"Điểm: {item.vote_average or '—'}\n"
                f"Giá thuê: {vnd(item.rental_price)} • Giá mua: {vnd(item.sale_price)}\n\n"
                + "\n".join(f"• {review.author}: {review.content[:180]}" for review in reviews))
        ttk.Label(frame, text=text, justify="left", wraplength=590).pack(anchor="w", fill="x")

    def _create_treeview(self, parent, **kwargs) -> ttk.Treeview:
        """Create a table whose headings and values use the app-wide alignment."""
        tree = ttk.Treeview(parent, **kwargs)
        for column in ("#0", *tree["columns"]):
            tree.column(column, anchor=tk.CENTER)
            tree.heading(column, anchor=tk.CENTER)
        return tree

    def _debounce(self, holder: dict[str, str], callback: Callable, delay: int = 250) -> None:
        previous = holder.get("after")
        if previous:
            self.after_cancel(previous)
        holder["after"] = self.after(delay, callback)

    def _dialog(self, title: str, width: int, height: int, *, modal: bool = True):
        dialog = tb.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        width, height = min(width, int(screen_width * 0.92)), min(height, int(screen_height * 0.86))
        dialog.geometry(f"{width}x{height}")
        dialog.minsize(min(width, 560), min(height, 360))
        dialog.resizable(True, True)
        dialog.update_idletasks()
        dialog.geometry(
            f"+{max(0, (screen_width - width) // 2)}+{max(0, (screen_height - height) // 2)}"
        )
        if modal:
            dialog.grab_set()
        return dialog

    def _heading(self, parent, title: str, subtitle: str = ""):
        bar = ttk.Frame(parent)
        bar.pack(fill=X, pady=(0, 8))
        heading = ttk.Frame(bar)
        heading.pack(side=LEFT, anchor="w")
        ttk.Label(heading, text=title, style="Norma.Title.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(heading, text=subtitle, bootstyle="secondary").pack(anchor="w", pady=(2, 0))
        ttk.Separator(parent).pack(fill=X, pady=(0, 8))
        return bar

    def _install_sortable_headings(
        self, tree, titles: dict[str, str], state: dict[str, object], reload_page
    ) -> Callable[[], None]:
        def draw() -> None:
            for column, title in titles.items():
                marker = ""
                if state["field"] == column:
                    marker = " ▼" if state["descending"] else " ▲"
                tree.heading(column, text=title + marker, command=lambda key=column: change(key))

        def change(column: str) -> None:
            if state["field"] == column:
                state["descending"] = not state["descending"]
            else:
                state["field"] = column
                state["descending"] = False
            draw()
            reload_page()

        draw()
        return draw

    def _create_pager(self, parent, page_number: tk.IntVar, refresh) -> Callable:
        bar = ttk.Frame(parent)
        bar.pack(fill=X, pady=(6, 0))
        first = ttk.Button(bar, text="« Đầu", bootstyle="secondary")
        previous = ttk.Button(bar, text="‹ Trước", bootstyle="secondary")
        label = ttk.Label(bar, text="Trang 1/1 • 0 kết quả", bootstyle="secondary")
        next_button = ttk.Button(bar, text="Sau ›", bootstyle="secondary")
        last = ttk.Button(bar, text="Cuối »", bootstyle="secondary")
        first.pack(side=LEFT, padx=(0, 3))
        previous.pack(side=LEFT, padx=3)
        label.pack(side=LEFT, padx=8)
        last.pack(side=RIGHT)
        next_button.pack(side=RIGHT, padx=3)
        total_pages = 1

        def move(target: int) -> None:
            page_number.set(max(1, min(total_pages, target)))
            refresh()

        first.configure(command=lambda: move(1))
        previous.configure(command=lambda: move(page_number.get() - 1))
        next_button.configure(command=lambda: move(page_number.get() + 1))
        last.configure(command=lambda: move(total_pages))

        def update(result) -> None:
            nonlocal total_pages
            total_pages = result.total_pages
            page_number.set(result.page)
            label.configure(
                text=f"Trang {result.page}/{result.total_pages} • {result.total_items:,} kết quả".replace(
                    ",", "."
                )
            )
            first.configure(state="normal" if result.page > 1 else "disabled")
            previous.configure(state="normal" if result.page > 1 else "disabled")
            next_button.configure(
                state="normal" if result.page < result.total_pages else "disabled"
            )
            last.configure(state="normal" if result.page < result.total_pages else "disabled")

        return update

    def _choose_payment_method(self, title: str, parent=None) -> PaymentMethod | None:
        dialog = self._dialog(title, 420, 190)
        options = {"Tiền mặt": PaymentMethod.CASH, "Chuyển khoản": PaymentMethod.BANK_TRANSFER, "Ví điện tử": PaymentMethod.E_WALLET}
        value = tk.StringVar(value="Tiền mặt")
        selected = []
        ttk.Label(dialog, text="Phương thức thanh toán", padding=12).pack(anchor="w")
        ttk.Combobox(dialog, textvariable=value, values=tuple(options), state="readonly").pack(fill=X, padx=12)

        def confirm():
            selected.append(options[value.get()])
            dialog.destroy()

        ttk.Button(dialog, text="Xác nhận", command=confirm, bootstyle="primary").pack(pady=12)
        self.wait_window(dialog)
        return selected[0] if selected else None

    def _quick_customer(self, combo, *, customer: CustomerView | None = None, on_saved=None) -> None:
        dialog = self._dialog("Sửa khách hàng" if customer else "Thêm khách hàng", 540, 440)
        form = ttk.Frame(dialog, padding=14)
        form.pack(fill="both", expand=True)
        values = {}
        for label, key in (("Họ tên", "full_name"), ("Số điện thoại", "phone"), ("Email", "email"), ("Địa chỉ", "address")):
            values[key] = tk.StringVar(value=getattr(customer, key, None) or "")
            ttk.Label(form, text=label).pack(anchor="w")
            ttk.Entry(form, textvariable=values[key]).pack(fill=X, pady=(0, 7))
        email_opt_in = tk.BooleanVar(value=customer.email_opt_in if customer else True)
        sms_opt_in = tk.BooleanVar(value=customer.sms_opt_in if customer else True)
        ttk.Checkbutton(form, text="Đồng ý nhận email", variable=email_opt_in).pack(anchor="w")
        ttk.Checkbutton(form, text="Đồng ý nhận SMS", variable=sms_opt_in).pack(anchor="w")

        def save():
            details = {key: variable.get() for key, variable in values.items()}
            details["email_opt_in"] = email_opt_in.get()
            details["sms_opt_in"] = sms_opt_in.get()
            try:
                if customer is None:
                    actor_id = self.account.employee_id if self.account else None
                    saved = self.store.add_customer(actor_id=actor_id, **details)
                else:
                    saved = self.store.update_customer(customer.id, actor_id=self.account.employee_id, **details)
            except Exception as exc:
                messagebox.showerror("Khách hàng", str(exc), parent=dialog)
                return
            dialog.destroy()
            if on_saved is not None:
                on_saved(saved)
                return
            page = self.pages.get(self._active_page)
            refresh = getattr(page, "refresh", None) if page else None
            if refresh:
                refresh()
            if combo is not None:
                match = next((value for value in combo.cget("values") if str(value).startswith(f"{saved.id} — ")), None)
                if match:
                    combo.set(match)

        ttk.Button(form, text="Lưu khách hàng", command=save, bootstyle="primary").pack(anchor="e", pady=10)
