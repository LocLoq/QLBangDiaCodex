# ruff: noqa: E402, I001
r"""Manual UI smoke test for all main pages at the supported minimum viewport.

Run while Laragon/MySQL is available:
    C:\laragon\bin\python\python-3.13\python.exe scripts\check_ui_layout.py
"""

from __future__ import annotations

import sys
import os
import time
import tkinter as tk
from itertools import product
from tkinter import messagebox, ttk
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
    ("Hóa đơn đã tạo", "orders_page"),
    ("Đĩa đã được thuê", "returns_page"),
    ("Đặt trước", "reservations_page"),
    ("Phim & tập", "catalog_page"),
    ("Kho đĩa", "inventory_page"),
    ("Khách hàng & Premium", "customers_page"),
    ("Combo / Voucher", "promotions_page"),
    ("Thông báo", "notifications_page"),
    ("Thống kê", "statistics_page"),
    ("Lịch sử và hoạt động", "audit_page"),
    ("Cài đặt & Giới thiệu", "settings_page"),
    ("Nhân viên", "employees_page"),
)

SCREENSHOTS = {"dashboard_page", "checkout_page", "inventory_page", "statistics_page"}


def _capture(window: tk.Misc, name: str) -> None:
    folder = os.environ.get("NORMASTORE_UI_SCREENSHOTS")
    if not folder:
        return
    from PIL import ImageGrab

    output = Path(folder)
    output.mkdir(parents=True, exist_ok=True)
    hwnd = int(window.wm_frame(), 0)
    ImageGrab.grab(window=hwnd).save(output / f"{name}.png")


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


def _check_primary_controls(container: tk.Misc, page_name: str) -> list[str]:
    required = {"Tạo phiếu": {"+ Thuê", "+ Mua", "Xóa dòng", "Xóa tất cả", "Hoàn tất"},
                "Kho đĩa": {"Thêm đĩa", "Sửa đã chọn", "Nhập CSV", "Tải mẫu CSV"}}
    missing = required.get(page_name, set()).copy()
    if not missing:
        return []
    problems = []

    def visit(parent: tk.Misc) -> None:
        for child in parent.winfo_children():
            if isinstance(child, ttk.Button) and (text := child.cget("text")) in missing:
                missing.remove(text)
                if not child.winfo_viewable() or child.winfo_width() < child.winfo_reqwidth() - 2:
                    problems.append(f"Nút bị cắt: {text}")
            if isinstance(child, ttk.Treeview) and "note" in child["columns"]:
                if not child.winfo_viewable() or child.winfo_height() < 65:
                    problems.append("Giỏ phiếu không đủ chỗ hiển thị.")
            visit(child)

    visit(container)
    return problems + [f"Thiếu nút: {text}" for text in sorted(missing)]


def _check_login(app: NormaStoreApp) -> None:
    app.update()
    dialog = next(widget for widget in app.winfo_children() if isinstance(widget, tk.Toplevel))
    if not dialog.winfo_viewable() or dialog.grab_current() != dialog:
        raise RuntimeError("Hộp đăng nhập không hiển thị hoặc không nhận thao tác.")
    clipped = _visible_overflow(app, dialog)
    if clipped:
        raise RuntimeError("Hộp đăng nhập bị cắt: " + " | ".join(clipped))
    _capture(dialog, "login")
    user, password = [widget for frame in dialog.winfo_children()
                      for widget in frame.winfo_children() if isinstance(widget, ttk.Entry)]
    user.focus_force()
    user.event_generate("<Tab>")
    app.update()
    if dialog.focus_get() != password:
        raise RuntimeError("Tab không chuyển tới ô mật khẩu.")
    original_password = password.get()
    password.delete(0, tk.END)
    password.insert(0, "invalid-smoke-test-password")
    errors = []
    showerror = messagebox.showerror
    try:
        messagebox.showerror = lambda _title, message, **_kwargs: errors.append(message)
        password.event_generate("<Return>")
        app.update()
    finally:
        messagebox.showerror = showerror
    if not errors or app.account is not None or not dialog.winfo_viewable():
        raise RuntimeError("Mật khẩu sai không được xử lý trong hộp đăng nhập.")
    password.delete(0, tk.END)
    password.insert(0, original_password)
    password.event_generate("<Return>")
    app.update()
    if app.account is None or dialog.winfo_exists() or not app.content.winfo_viewable():
        raise RuntimeError("Đăng nhập đúng chưa mở được cửa sổ chính.")


def main() -> int:
    settings = Settings()
    factory = bootstrap(settings)
    service, poster_cache = build_application(factory, settings)

    app = NormaStoreApp(service, settings, poster_cache)
    failures: list[str] = []
    try:
        scaling = os.environ.get("NORMASTORE_UI_SCALING")
        if scaling:
            app.tk.call("tk", "scaling", float(scaling))
            app._apply_ui_style()
        _check_login(app)
        app.state("normal")
        size = os.environ.get("NORMASTORE_UI_SIZE", "1366x768")
        app.geometry(f"{size}+0+0")
        app.update()
        content_geometry = (app.content.winfo_rootx(), app.content.winfo_width())
        app._open_drawer(temporary=True)
        app.update()
        if not app.drawer.winfo_ismapped():
            failures.append("drawer không mở")
        if content_geometry != (app.content.winfo_rootx(), app.content.winfo_width()):
            failures.append("drawer làm thay đổi hình học nội dung")
        app._close_drawer()
        home = next(button for button, glyph in app._nav_icon_widgets if glyph == "\ue80f")
        if app._hidden_visible or any(button.winfo_ismapped() for button in app._hidden_navigation):
            failures.append("các mục ẩn hiển thị trước khi nhấn Home")
        for _ in range(4):
            home.invoke()
        if app._hidden_visible:
            failures.append("các mục ẩn mở trước lần nhấn Home thứ năm")
        app.show_page("Tạo phiếu", app.checkout_page)
        home.invoke()
        if app._hidden_visible:
            failures.append("chuyển trang không đặt lại chuỗi nhấn Home")
        for _ in range(3):
            home.invoke()
        home.invoke()
        app.update_idletasks()
        if not app._hidden_visible or str(app._help_menu.entrycget("Giới thiệu", "state")) != "normal":
            failures.append("không mở được các mục ẩn sau năm lần nhấn Home")
        for _ in range(5):
            home.invoke()
        app.update_idletasks()
        if app._hidden_visible or str(app._help_menu.entrycget("Giới thiệu", "state")) != "disabled":
            failures.append("không ẩn lại các mục sau năm lần nhấn Home")
        for dark_mode, font_scale in product((False, True), ("Nhỏ", "Vừa", "Lớn")):
            if app.dark_mode.get() != dark_mode:
                app.dark_mode.set(dark_mode)
                app._set_appearance()
            app.font_scale.set(font_scale)
            app._set_font_scale()
            for page_name, method_name in PAGES:
                mode = "dark" if dark_mode else "light"
                label = f"{mode}/{font_scale}/{page_name}"
                try:
                    settle = 0.15 if page_name in app.pages else 0.8
                    app.show_page(page_name, getattr(app, method_name))
                    deadline = time.monotonic() + settle
                    while time.monotonic() < deadline:
                        app.update()
                        time.sleep(0.02)
                    if font_scale == "Vừa" and method_name in SCREENSHOTS:
                        _capture(app, f"{method_name}-{mode}")
                    if controls := _check_primary_controls(app.pages[page_name], page_name):
                        failures.append(f"{label}: " + " | ".join(controls))
                    overflow = _visible_overflow(app, app.content)
                    if overflow:
                        failures.append(f"{label}: " + " | ".join(overflow[:8]))
                    if page_name == "Tạo phiếu":
                        panes = [widget for widget in app.pages[page_name].winfo_children()
                                 if isinstance(widget, ttk.Panedwindow)]
                        for pane in panes:
                            for child in pane.panes():
                                frame = pane.nametowidget(child)
                                clipped = _visible_overflow(app, frame)
                                if clipped:
                                    failures.append(f"{label}/khung: " + " | ".join(clipped[:8]))
                    alignment = _treeview_alignment(app.content)
                    if alignment:
                        failures.append(f"{label}: " + " | ".join(alignment[:8]))
                    scrolling = _check_scrolling(app, app.content)
                    if scrolling:
                        failures.append(f"{label}: " + " | ".join(scrolling[:8]))
                    advanced = _check_advanced_filters(app, app.content)
                    if advanced:
                        failures.append(f"{label}/lọc nâng cao: " + " | ".join(advanced[:8]))
                except Exception as exc:  # smoke runner must continue through all pages
                    failures.append(f"{label}: {type(exc).__name__}: {exc}")
    finally:
        app._close()

    if failures:
        print("UI_SMOKE_FAILED")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"UI_SMOKE_OK: login, {len(PAGES)} pages, all font sizes, dark mode, {size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
