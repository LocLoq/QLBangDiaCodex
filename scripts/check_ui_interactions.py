"""Exercise inventory expansion and series checkout on a disposable MySQL database.

Set NORMASTORE_DATABASE_URL to a fresh database named normastore_ui_smoke_*.
This script creates test records and must not point at an operational database.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import tkinter as tk
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from sqlalchemy.engine import make_url
from ttkbootstrap import DateEntry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from normastore.bootstrap import bootstrap, build_application
from normastore.application.contracts import CheckoutLine
from normastore.config import Settings
from normastore.domain.enums import CopyStatus, LineAction, PaymentMethod
from normastore.ui.app import NormaStoreApp


def widgets(root):
    for child in root.winfo_children():
        yield child
        yield from widgets(child)


def button(root, text):
    return next(w for w in widgets(root) if isinstance(w, ttk.Button) and w.cget("text") == text)


def main():
    url = os.environ.get("NORMASTORE_DATABASE_URL", "")
    if not url or not (make_url(url).database or "").startswith("normastore_ui_smoke_"):
        raise RuntimeError("Cần database thử nghiệm riêng có tên bắt đầu bằng normastore_ui_smoke_.")
    settings = Settings()
    background_variables = []
    original_delete = tk.Variable.__del__

    def record_delete(variable):
        if threading.current_thread() is not threading.main_thread():
            background_variables.append((type(variable).__name__, variable._name))
        original_delete(variable)

    tk.Variable.__del__ = record_delete
    print("BOOTSTRAP", flush=True)
    factory = bootstrap(settings)
    service, poster_cache = build_application(factory, settings)
    account = service.authenticate("admin", "admin123")
    if not account:
        raise RuntimeError("Không đăng nhập được tài khoản thử nghiệm.")
    actor = account.employee_id
    customer = service.add_customer("Khách thử giao diện", "0988999000", "ui@example.test", address="Địa chỉ thử")
    service.create_voucher("UI10", actor, percent_off=Decimal("10"))
    future = service.save_catalog_item(actor, item_type="MOVIE", title="Phim sắp ra thử",
                                       release_date=date.today() + timedelta(days=7))
    show = service.create_show("Bộ phim thử giao diện", actor_id=actor)
    episodes = service.add_episodes_bulk(show.id, 1, 1, 3, actor_id=actor)
    for number, episode in enumerate(episodes, 1):
        service.save_catalog_item(actor, id=episode.id, genre_names=["Thể loại thử"])
        service.add_copy(episode.id, f"UI-EP-{number}-A", actor_id=actor)
    service.add_copy(episodes[1].id, "UI-EP-2-B", actor_id=actor)

    def login(app):
        app.account = account
        app._build_shell()

    NormaStoreApp._login = login
    def unexpected_dialog(title, message, **_kwargs):
        raise RuntimeError(f"{title}: {message}")

    messagebox.showerror = unexpected_dialog
    messagebox.showinfo = unexpected_dialog
    print("OPEN_APP", flush=True)
    app = NormaStoreApp(service, settings, poster_cache)
    callback_errors = []
    app.report_callback_exception = lambda kind, value, _traceback: callback_errors.append((kind.__name__, str(value)))

    def pump(seconds=0.5):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            app.update()
            time.sleep(0.02)

    try:
        app.state("normal")
        app.geometry("1366x768+0+0")
        app.show_page("Kho đĩa", app.inventory_page)
        print("INVENTORY_OPEN", flush=True)
        pump()
        page = app.pages["Kho đĩa"]
        tree = next(w for w in widgets(page) if isinstance(w, ttk.Treeview))
        search = next(w for w in widgets(page) if isinstance(w, ttk.Entry))
        search.insert(0, "UI-EP-2-B")
        pump(0.8)
        root = f"show:{show.id}"
        assert tree.exists(root), "Không tìm thấy bộ phim bằng mã đĩa."
        tree.focus(root)
        tree.event_generate("<<TreeviewOpen>>")
        pump()
        episode_node = f"item:{episodes[1].id}"
        assert tree.exists(episode_node), "Không mở được tập phù hợp."
        tree.focus(episode_node)
        tree.event_generate("<<TreeviewOpen>>")
        pump()
        assert any(tree.item(i, "text") == "UI-EP-2-B" for i in tree.get_children(episode_node))
        print("INVENTORY_SEARCH_AND_DRAWER_OK", flush=True)

        copy_node = next(i for i in tree.get_children(episode_node) if tree.item(i, "text") == "UI-EP-2-B")
        tree.selection_set(copy_node)
        button(page, "Sửa bản đĩa").invoke()
        pump()
        edit_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Sửa bản đĩa")

        def field(label):
            widget = next(w for w in widgets(edit_dialog) if isinstance(w, ttk.Label) and w.cget("text") == label)
            return next(w for w in widget.master.grid_slaves(row=widget.grid_info()["row"], column=1))

        field("Tình trạng").set("Cũ")
        percent = field("Tình trạng (%)")
        percent.delete(0, tk.END)
        percent.insert(0, "60")
        field("Cách tính giá thuê").set("Theo tình trạng")
        field("Cách tính giá bán").set("Theo % giá gốc")
        sale_percent = field("Tỷ lệ giá bán (%)")
        sale_percent.delete(0, tk.END)
        sale_percent.insert(0, "50")
        button(edit_dialog, "Lưu").invoke()
        pump()
        assert not edit_dialog.winfo_exists(), "Không lưu được giá riêng của đĩa."
        choice = next(c for c in service.checkout_copies(episodes[1].id, LineAction.RENT) if c.barcode == "UI-EP-2-B")
        assert choice.unit_price == Decimal("10800")
        sale_choice = next(c for c in service.checkout_copies(episodes[1].id, LineAction.BUY) if c.barcode == "UI-EP-2-B")
        assert sale_choice.unit_price == Decimal("65000")
        print("INVENTORY_CONDITION_AND_PRICE_EDIT_OK", flush=True)

        button(page, "Thêm đĩa").invoke()
        pump()
        add_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Thêm đĩa vào kho")
        item_tree = next(w for w in widgets(add_dialog) if isinstance(w, ttk.Treeview))
        item_tree.selection_set(str(episodes[2].id))
        add_entries = [w for w in widgets(add_dialog) if w.winfo_class() == "TEntry"]
        add_entries[1].insert(0, "UI-EP-3-B")
        button(add_dialog, "Thêm đĩa").invoke()
        pump()
        assert not add_dialog.winfo_exists(), "Không lưu được đĩa mới."
        assert any(copy.barcode == "UI-EP-3-B" for copy in service.query_inventory(text="UI-EP-3-B").items)
        print("INVENTORY_ADD_COPY_OK", flush=True)

        confirmations = []
        messagebox.showinfo = lambda title, message, **_kwargs: confirmations.append((title, message))
        app.show_page("Cài đặt & Giới thiệu", app.settings_page)
        pump()
        settings_page = app.pages["Cài đặt & Giới thiệu"]
        deposit_box = next(w for w in widgets(settings_page) if isinstance(w, ttk.Labelframe) and w.cget("text") == "Tỷ lệ tiền cọc")
        deposit_entry = next(w for w in widgets(deposit_box) if w.winfo_class() == "TEntry")
        deposit_entry.delete(0, tk.END)
        deposit_entry.insert(0, "60")
        button(deposit_box, "Lưu").invoke()
        pump()
        quote = service.quote(customer.id, [CheckoutLine(choice.copy_id, LineAction.RENT, date.today() + timedelta(days=3))])
        assert quote.line_deposits[choice.copy_id] == Decimal("39000")
        print("SETTINGS_DEPOSIT_PERCENT_OK", flush=True)

        app.show_page("Phim & tập", app.catalog_page)
        pump(1.5)
        catalog_page = app.pages["Phim & tập"]
        view_picker = next(w for w in widgets(catalog_page) if isinstance(w, ttk.Combobox) and
                           "Thẻ" in w.cget("values"))
        view_picker.set("Thẻ")
        pump(1.5)
        card = next(w for w in widgets(catalog_page) if isinstance(w, ttk.Labelframe) and w.cget("text") == "Mẫu phim khởi động")
        card_button = next(w for w in widgets(card) if isinstance(w, ttk.Menubutton) and w.cget("text") == "Thao tác")
        menu = app.nametowidget(card_button.cget("menu"))
        menu_labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1)]
        assert {"Sửa", "Thêm đĩa", "Lưu trữ"}.issubset(menu_labels)
        episode_card = next(w for w in widgets(catalog_page) if isinstance(w, ttk.Labelframe) and "Bộ phim thử giao diện" in w.cget("text"))
        episode_button = next(w for w in widgets(episode_card) if isinstance(w, ttk.Menubutton) and w.cget("text") == "Thao tác")
        episode_menu = app.nametowidget(episode_button.cget("menu"))
        assert "Thêm tập" in [episode_menu.entrycget(i, "label") for i in range(episode_menu.index("end") + 1)]
        menu.invoke(menu_labels.index("Sửa"))
        pump()
        movie_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Sửa phim/tập")
        rent_row = next(w for w in widgets(movie_dialog) if isinstance(w, ttk.Frame) and
                        any(isinstance(c, ttk.Label) and c.cget("text") == "Cách tính giá thuê" for c in w.winfo_children()))
        next(w for w in rent_row.winfo_children() if isinstance(w, ttk.Combobox)).set("Theo % giá gốc")
        movie_percent = next(w for w in rent_row.winfo_children() if w.winfo_class() == "TEntry")
        movie_percent.delete(0, tk.END)
        movie_percent.insert(0, "50")
        button(movie_dialog, "Lưu").invoke()
        pump(1.5)
        demo_copy = next(row for row in service.query_inventory(text="DVD-DEMO-001").items if row.barcode == "DVD-DEMO-001")
        demo_item = next(item for item in service.query_catalog().items if item.title == "Mẫu phim khởi động")
        assert next(c for c in service.checkout_copies(demo_item.item_id, LineAction.RENT) if c.copy_id == demo_copy.copy_id).unit_price == Decimal("12500")
        print("CATALOG_CARD_AND_ITEM_PRICE_OK", flush=True)

        app.show_page("Tạo phiếu", app.checkout_page)
        print("CHECKOUT_OPEN", flush=True)
        pump(1.5)
        page = app.pages["Tạo phiếu"]
        customer_picker = next(w for w in widgets(page) if isinstance(w, ttk.Combobox) and
                               any("0988999000" in str(value) for value in w.cget("values")))
        customer_picker.set(next(value for value in customer_picker.cget("values") if "0988999000" in value))
        voucher_picker = next(w for w in widgets(page) if isinstance(w, ttk.Combobox) and
                              any("UI10" in str(value) for value in w.cget("values")))
        voucher = next(value for value in voucher_picker.cget("values") if "UI10" in value)
        assert "Giảm" in voucher and "%" in voucher
        voucher_picker.set(voucher)
        labels = [app.getvar(w.cget("textvariable")) for w in widgets(page) if
                  isinstance(w, ttk.Label) and w.cget("textvariable")]
        assert any("ui@example.test" in str(label) and "Địa chỉ thử" in str(label) for label in labels)
        print("CHECKOUT_CUSTOMER_AND_VOUCHER_OK", flush=True)
        button(page, "Chọn phim bộ").invoke()
        pump()
        dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Chọn tập phim bộ")
        controls = next(w for w in widgets(dialog) if isinstance(w, ttk.Frame) and
                        any(isinstance(c, ttk.Label) and c.cget("text") == "Từ tập" for c in w.winfo_children()))
        entries = [w for w in controls.winfo_children() if w.winfo_class() == "TEntry"]
        entries[0].insert(0, "2")
        entries[1].insert(0, "3")
        button(dialog, "Chọn thuê").invoke()
        pump()
        choices = [w for w in widgets(dialog) if isinstance(w, ttk.Combobox) and
                   any("UI-EP-2-B" in str(value) for value in w.cget("values"))]
        assert len(choices) == 1, "Không có lựa chọn đĩa cho tập 2."
        choices[0].set(next(value for value in choices[0].cget("values") if "UI-EP-2-B" in value))
        button(dialog, "Thêm vào giỏ").invoke()
        pump()
        carts = [w for w in widgets(page) if isinstance(w, ttk.Treeview) and
                 any("UI-EP-2-B" in w.item(i, "text") for i in w.get_children())]
        assert len(carts) == 1
        texts = [carts[0].item(i, "text") for i in carts[0].get_children()]
        assert len(texts) == 2 and any("UI-EP-3-A" in text for text in texts)
        print("SERIES_RANGE_AND_COPY_SELECTION_OK", flush=True)

        button(page, "Chọn phim bộ").invoke()
        pump()
        dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Chọn tập phim bộ")
        button(dialog, "Chọn mua").invoke()
        pump()
        button(dialog, "Thêm vào giỏ").invoke()
        pump()
        texts = [carts[0].item(i, "text") for i in carts[0].get_children()]
        assert len(texts) == 5 and any("UI-EP-3-B" in text for text in texts)
        print("SERIES_FULL_SEASON_PURCHASE_OK", flush=True)

        confirmations.clear()
        messagebox.showinfo = lambda title, message, **_kwargs: confirmations.append((title, message))
        simpledialog.askstring = lambda _title, _prompt, **kwargs: kwargs["initialvalue"]
        app._choose_payment_method = lambda *_args: PaymentMethod.CASH
        button(page, "Hoàn tất").invoke()
        pump()
        assert any(title == "Hoàn tất" for title, _ in confirmations), "Không hoàn tất được phiếu."
        assert not carts[0].get_children(), "Giỏ hàng chưa được xóa sau thanh toán."
        order = service.query_orders().items[0]
        assert order.customer_name == "Khách thử giao diện"
        _, lines = service.order_detail(order.order_id)
        assert len(lines) == 5
        assert sum(line.action == LineAction.RENT for line in lines) == 2
        assert sum(line.action == LineAction.BUY for line in lines) == 3
        receipt = service.order_receipt(order.order_id)
        assert any(discount.source == "VOUCHER" and discount.source_code == "UI10" and discount.amount > 0
                   for discount in receipt.discounts)
        assert receipt.checkout_paid == receipt.total_due and receipt.balance_due == 0
        assert service.query_inventory(text="UI-EP-2-B").items[0].status == CopyStatus.RENTED
        assert service.query_inventory(text="UI-EP-3-B").items[0].status == CopyStatus.SOLD
        print("CHECKOUT_PAYMENT_AND_ORDER_OK", flush=True)

        app.show_page("Trả đĩa & phạt", app.returns_page)
        pump()
        returns_page = app.pages["Trả đĩa & phạt"]
        returns_tree = next(w for w in widgets(returns_page) if isinstance(w, ttk.Treeview))
        rental = next(row for row in service.active_rentals() if row.barcode == "UI-EP-2-B")
        returns_tree.selection_set(str(rental.term_id))
        outcome_picker = next(w for w in widgets(returns_page) if isinstance(w, ttk.Combobox) and
                              "Hư nhẹ" in w.cget("values"))
        outcome_picker.set("Hư nhẹ")
        button(returns_page, "Xác nhận trả").invoke()
        pump()
        assert service.query_inventory(text="UI-EP-2-B").items[0].status == CopyStatus.REPAIR
        button(returns_page, "Trả hàng bán").invoke()
        pump()
        sale_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Trả hàng bán trong 7 ngày")
        sale_tree = next(w for w in widgets(sale_dialog) if isinstance(w, ttk.Treeview))
        sale_line = next(row for row in service.returnable_sales() if row.barcode == "UI-EP-3-B")
        sale_tree.selection_set(str(sale_line.line_id))
        messagebox.askyesno = lambda *_args, **_kwargs: False
        button(sale_dialog, "Xác nhận hoàn").invoke()
        pump()
        assert service.query_inventory(text="UI-EP-3-B").items[0].status == CopyStatus.INSPECTION
        assert not sale_tree.exists(str(sale_line.line_id))
        sale_dialog.destroy()
        print("RENTAL_AND_SALE_RETURN_OK", flush=True)
        app.show_page("Thống kê", app.statistics_page)
        pump(3)
        page = app.pages["Thống kê"]
        analysis = app._figures[-1]
        revenue_axis, damage_axis, genre_axis = analysis.axes
        assert len(revenue_axis.lines) == 2, "Biểu đồ doanh thu thiếu thuê hoặc bán."
        assert damage_axis.patches, "Biểu đồ hỏng hóc thiếu lượt trả thử."
        assert genre_axis.patches, "Biểu đồ thể loại thiếu lượt bán thử."
        action_picker = next(w for w in widgets(page) if isinstance(w, ttk.Combobox) and
                             "Tất cả giao dịch" in w.cget("values"))
        action_picker.set("Mua")
        button(page, "Áp dụng").invoke()
        pump(2)
        assert [line.get_label() for line in revenue_axis.lines] == ["Bán"]
        assert not damage_axis.patches, "Bộ lọc mua vẫn hiển thị hỏng hóc thuê."
        assert genre_axis.patches
        period_picker = next(w for w in widgets(page) if isinstance(w, ttk.Combobox) and
                             "Tùy chọn" in w.cget("values"))
        period_picker.set("Tùy chọn")
        dates = [w for w in widgets(page) if isinstance(w, DateEntry)]
        assert len(dates) == 2
        tomorrow = (date.today() + timedelta(days=1)).strftime("%d/%m/%Y")
        for entry in dates:
            entry.entry.delete(0, tk.END)
            entry.entry.insert(0, tomorrow)
        button(page, "Áp dụng").invoke()
        pump(2)
        assert not revenue_axis.lines and not genre_axis.patches, "Bộ lọc ngày vẫn hiển thị giao dịch hôm nay."
        for entry in dates:
            entry.entry.delete(0, tk.END)
            entry.entry.insert(0, date.today().strftime("%d/%m/%Y"))
        button(page, "Áp dụng").invoke()
        pump(2)
        assert [line.get_label() for line in revenue_axis.lines] == ["Bán"] and genre_axis.patches
        with tempfile.TemporaryDirectory(prefix="normastore-ui-export-") as export_dir:
            csv_path = Path(export_dir) / "report.csv"
            png_path = Path(export_dir) / "report.png"
            filedialog.asksaveasfilename = lambda **kwargs: str(csv_path if kwargs["defaultextension"] == ".csv" else png_path)
            button(page, "Xuất CSV").invoke()
            button(page, "Xuất ảnh").invoke()
            pump()
            csv_text = csv_path.read_text(encoding="utf-8-sig")
            assert "Thể loại bán chạy" in csv_text and "Ngày có lại dự kiến" in csv_text
            assert png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        print("STATISTICS_EXPORT_OK", flush=True)
        print("STATISTICS_CHARTS_AND_FILTER_OK", flush=True)

        app.show_page("Tổng quan", app.dashboard_page)
        pump(1.5)
        page = app.pages["Tổng quan"]
        notebook = next(w for w in widgets(page) if isinstance(w, ttk.Notebook))
        for tab_name in ("Phim hot", "Bán chạy"):
            tab_id = next(tab for tab in notebook.tabs() if notebook.tab(tab, "text") == tab_name)
            notebook.select(tab_id)
            pump(1.5)
            tab = notebook.nametowidget(tab_id)
            chart = next(w for w in widgets(tab) if isinstance(w, ttk.Treeview))
            assert any("Bộ phim thử giao diện" in chart.item(i, "text") for i in chart.get_children()), tab_name
        print("DASHBOARD_POPULAR_TABS_OK", flush=True)

        def select_tab(name):
            tab_id = next(tab for tab in notebook.tabs() if notebook.tab(tab, "text") == name)
            notebook.select(tab_id)
            pump(1.5)
            tab = notebook.nametowidget(tab_id)
            return tab, next(w for w in widgets(tab) if isinstance(w, ttk.Treeview))

        tab, stock = select_tab("Sắp hết / hết")
        assert any("Bộ phim thử giao diện" in stock.item(i, "text") for i in stock.get_children())
        tab, discovery = select_tab("Khám phá")
        assert discovery.get_children(), "Không có phim khám phá."
        discovery.selection_set(discovery.get_children()[0])
        selected_id = int(discovery.selection()[0])
        button(tab, "Thiết lập ưu đãi").invoke()
        pump()
        discount_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Ưu đãi khám phá")
        next(w for w in widgets(discount_dialog) if isinstance(w, ttk.Checkbutton)).invoke()
        button(discount_dialog, "Lưu ưu đãi").invoke()
        pump(1.5)
        assert any(row[0] == selected_id and row[3] and row[4] > 0 for row in service.dashboard_discovery())
        discovery.selection_set(str(selected_id))
        button(tab, "Thiết lập ưu đãi").invoke()
        pump()
        discount_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Ưu đãi khám phá")
        app.tk.call(discount_dialog.protocol("WM_DELETE_WINDOW"))
        pump()
        assert not discount_dialog.winfo_exists(), "Không đóng được hộp thoại ưu đãi."
        tab, random_tree = select_tab("Ngẫu nhiên")
        assert random_tree.get_children(), "Không có phim đề cử ngẫu nhiên."
        button(tab, "Đề cử lại").invoke()
        pump(1.5)
        assert random_tree.get_children()
        tab, upcoming = select_tab("Sắp ra")
        deadline = time.monotonic() + 8
        while not upcoming.exists(str(future.id)) and time.monotonic() < deadline:
            pump(0.2)
        assert upcoming.exists(str(future.id))
        upcoming.selection_set(str(future.id))
        button(tab, "Đặt trước").invoke()
        pump()
        reserve_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Đặt trước phim sắp ra")
        picker = next(w for w in widgets(reserve_dialog) if isinstance(w, ttk.Combobox))
        picker.set(next(value for value in picker.cget("values") if "0988999000" in value))
        button(reserve_dialog, "Xác nhận").invoke()
        pump()
        assert any(row.item_title == "Phim sắp ra thử" and row.customer_name == "Khách thử giao diện"
                   for row in service.list_reservations())
        assert not background_variables, f"Biến giao diện bị giải phóng ở luồng nền: {background_variables}"
        assert not callback_errors, f"Lỗi callback giao diện: {callback_errors}"
        print("DASHBOARD_STOCK_DISCOVERY_RANDOM_PREORDER_OK", flush=True)
    finally:
        app._close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
