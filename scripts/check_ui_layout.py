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

from normastore.bootstrap import bootstrap  # noqa: E402
from normastore.config import Settings  # noqa: E402
from normastore.ui.app import NormaStoreApp  # noqa: E402


PAGES = (
    ("Tổng quan", "dashboard_page"),
    ("Lập phiếu", "checkout_page"),
    ("Phiếu đã lập", "orders_page"),
    ("Trả đĩa & phạt", "returns_page"),
    ("Đặt trước", "reservations_page"),
    ("Phim & tập", "catalog_page"),
    ("Kho đĩa", "inventory_page"),
    ("Khách hàng & Premium", "customers_page"),
    ("Combo / Voucher", "promotions_page"),
    ("Nhân viên & ca", "shifts_page"),
    ("Thông báo", "notifications_page"),
    ("Thống kê", "statistics_page"),
    ("Nhật ký hành động", "audit_page"),
    ("Cài đặt & About", "settings_page"),
)


def _visible_overflow(root: tk.Misc, container: tk.Misc) -> list[str]:
    root.update_idletasks()
    left, top = container.winfo_rootx(), container.winfo_rooty()
    right, bottom = left + container.winfo_width(), top + container.winfo_height()
    problems: list[str] = []

    def visit(widget: tk.Misc) -> None:
        for child in widget.winfo_children():
            if child.winfo_ismapped():
                x, y = child.winfo_rootx(), child.winfo_rooty()
                x2, y2 = x + child.winfo_width(), y + child.winfo_height()
                if x < left - 2 or x2 > right + 2 or y < top - 2 or y2 > bottom + 2:
                    problems.append(
                        f"{child.winfo_class()} {child.winfo_name()}: "
                        f"({x - left},{y - top},{child.winfo_width()}x{child.winfo_height()})"
                    )
                visit(child)

    visit(container)
    return problems


def main() -> int:
    settings = Settings()
    factory = bootstrap(settings)

    def automatic_login(self) -> None:
        self.account = self.call(lambda service: service.authenticate("admin", "admin123"), True)
        if not self.account:
            raise RuntimeError("Không đăng nhập được tài khoản admin để smoke-test UI.")
        self._build_shell()

    NormaStoreApp._login = automatic_login
    app = NormaStoreApp(factory, settings)
    failures: list[str] = []
    try:
        app.state("normal")
        app.geometry("1366x768+0+0")
        app.update()
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
