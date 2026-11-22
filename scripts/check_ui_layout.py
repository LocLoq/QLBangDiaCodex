# ruff: noqa: E402, I001
r"""Manual UI smoke test for all main pages at the supported minimum viewport.

Run while Laragon/MySQL is available:
    C:\laragon\bin\python\python-3.13\python.exe scripts\check_ui_layout.py
"""

from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from normastore.bootstrap import bootstrap, build_application  # noqa: E402
from normastore.config import Settings  # noqa: E402
from normastore.ui.app import NormaStoreApp  # noqa: E402
from ttkbootstrap.widgets.scrolled import ScrolledFrame  # noqa: E402


PAGES = (
    ("Tổng quan", "dashboard_page"),
    ("Tạo phiếu", "checkout_page"),
    ("Phiếu đã lập", "orders_page"),
    ("Trả đĩa & phạt", "returns_page"),
    ("Đặt trước", "reservations_page"),
    ("Phim & tập", "catalog_page"),
    ("Kho đĩa", "inventory_page"),
    ("Khách hàng & Premium", "customers_page"),
    ("Combo / Voucher", "promotions_page"),
    ("Nhân viên", "employees_page"),
    ("Thông báo", "notifications_page"),
    ("Thống kê", "statistics_page"),
    ("Nhật ký hành động", "audit_page"),
    ("Cài đặt & Giới thiệu", "settings_page"),
)


def _visible_overflow(root: tk.Misc, container: tk.Misc) -> list[str]:
    root.update_idletasks()
    left, top = container.winfo_rootx(), container.winfo_rooty()
    right, bottom = left + container.winfo_width(), top + container.winfo_height()
    problems: list[str] = []

    def visit(widget: tk.Misc, vertically_scrollable: bool = False) -> None:
        for child in widget.winfo_children():
            if child.winfo_ismapped():
                scrollable = vertically_scrollable or isinstance(child, ScrolledFrame)
                x, y = child.winfo_rootx(), child.winfo_rooty()
                x2, y2 = x + child.winfo_width(), y + child.winfo_height()
                if x < left - 2 or x2 > right + 2 or (
                    not scrollable and (y < top - 2 or y2 > bottom + 2)
                ):
                    problems.append(
                        f"{child.winfo_class()} {child.winfo_name()}: "
                        f"({x - left},{y - top},{child.winfo_width()}x{child.winfo_height()})"
                    )
                visit(child, scrollable)

    visit(container)
    return problems


def _treeview_alignment(container: tk.Misc) -> list[str]:
    problems: list[str] = []

    def visit(widget: tk.Misc) -> None:
        for child in widget.winfo_children():
            if not child.winfo_ismapped():
                continue
            if child.winfo_class() == "Treeview":
                for column in ("#0", *child["columns"]):
                    if str(child.heading(column, "anchor")) != "center":
                        problems.append(f"{child.winfo_name()}/{column}: heading anchor")
            visit(child)

    visit(container)
    return problems


def _check_scrolling(root: tk.Misc, container: tk.Misc) -> list[str]:
    problems: list[str] = []

    def visit(widget: tk.Misc) -> None:
        for child in widget.winfo_children():
            if not child.winfo_ismapped():
                continue
            if isinstance(child, ScrolledFrame) and child.winfo_height() > child.container.winfo_height():
                child.yview("moveto", 0)
                root.update_idletasks()
                top = child.winfo_rooty()
                child.yview("moveto", 1)
                root.update_idletasks()
                if child.winfo_rooty() >= top or child.vscroll.get()[1] < 0.999:
                    problems.append(f"{child.winfo_name()}: nội dung không cuộn được đến cuối")
                child.yview("moveto", 0)
                root.update_idletasks()
            visit(child)

    visit(container)
    return problems


def _check_advanced_filters(root: tk.Misc, container: tk.Misc) -> list[str]:
    buttons = []

    def visit(widget: tk.Misc) -> None:
        for child in widget.winfo_children():
            if not child.winfo_ismapped():
                continue
            if child.winfo_class() == "TButton" and "nâng cao" in str(child.cget("text")):
                buttons.append(child)
            visit(child)

    visit(container)
    problems = []
    for button in buttons:
        button.invoke()
        root.update_idletasks()
        problems.extend(_visible_overflow(root, container))
        button.invoke()
        root.update_idletasks()
    return problems


def main() -> int:
    settings = Settings()
    factory = bootstrap(settings)
    service, poster_cache = build_application(factory, settings)

    def automatic_login(self) -> None:
        self.account = self.store.authenticate('admin', 'admin123')
        if not self.account:
            raise RuntimeError("Không đăng nhập được tài khoản admin để smoke-test UI.")
        self._build_shell()

    NormaStoreApp._login = automatic_login
    app = NormaStoreApp(service, settings, poster_cache)
    failures: list[str] = []
    try:
        app.state("normal")
        app.geometry("1366x768+0+0")
        app.update()
        content_geometry = (app.content.winfo_rootx(), app.content.winfo_width())
        app._open_drawer(temporary=True)
        app.update()
        if not app.drawer.winfo_ismapped():
            failures.append("drawer không mở")
        if content_geometry != (app.content.winfo_rootx(), app.content.winfo_width()):
            failures.append("drawer làm thay đổi hình học nội dung")
        app._close_drawer()
        for font_scale in ("Vừa", "Lớn"):
            app.font_scale.set(font_scale)
            app._set_font_scale()
            for page_name, method_name in PAGES:
                try:
                    app.show_page(page_name, getattr(app, method_name))
                    deadline = time.monotonic() + 0.8
                    while time.monotonic() < deadline:
                        app.update()
                        time.sleep(0.02)
                    overflow = _visible_overflow(app, app.content)
                    if overflow:
                        failures.append(f"{font_scale}/{page_name}: " + " | ".join(overflow[:8]))
                    alignment = _treeview_alignment(app.content)
                    if alignment:
                        failures.append(f"{font_scale}/{page_name}: " + " | ".join(alignment[:8]))
                    scrolling = _check_scrolling(app, app.content)
                    if scrolling:
                        failures.append(f"{font_scale}/{page_name}: " + " | ".join(scrolling[:8]))
                    advanced = _check_advanced_filters(app, app.content)
                    if advanced:
                        failures.append(f"{font_scale}/{page_name}/lọc nâng cao: " + " | ".join(advanced[:8]))
                except Exception as exc:  # smoke runner must continue through all pages
                    failures.append(f"{font_scale}/{page_name}: {type(exc).__name__}: {exc}")
        app.dark_mode.set(True)
        app._set_appearance()
        app.update()
    finally:
        app._close()

    if failures:
        print("UI_SMOKE_FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("UI_SMOKE_OK: 14 pages, medium/large font, dark mode, 1366x768")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
