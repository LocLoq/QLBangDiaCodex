from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Callable

import ttkbootstrap as tb
from ttkbootstrap.constants import LEFT, RIGHT, X

from normastore.domain.enums import PaymentMethod


class CommonWidgetsMixin:
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
        bar.pack(fill=X, pady=(0, 10))
        ttk.Label(bar, text=title, font=self._font("title"), bootstyle="primary").pack(side=LEFT)
        if subtitle:
            ttk.Label(bar, text=subtitle, bootstyle="secondary").pack(side=LEFT, padx=12, pady=8)
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
        raw = simpledialog.askstring(
            title,
            "Phương thức: CASH, BANK_TRANSFER hoặc E_WALLET",
            initialvalue=PaymentMethod.CASH.value,
            parent=parent or self,
        )
        if raw is None:
            return None
        try:
            return PaymentMethod(raw.strip().upper())
        except ValueError:
            messagebox.showerror(
                title, "Phương thức thanh toán không hợp lệ.", parent=parent or self
            )
            return None

    def _quick_customer(self, combo) -> None:
        name = simpledialog.askstring("Khách hàng mới", "Họ tên:", parent=self)
        phone = simpledialog.askstring("Khách hàng mới", "Số điện thoại:", parent=self)
        if name and phone:
            self.store.add_customer(name, phone)
            refresh = getattr(self.pages.get("Lập phiếu"), "refresh", None)
            if refresh:
                refresh()
