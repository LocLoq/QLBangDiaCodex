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

from PIL import Image
from matplotlib.backend_bases import MouseEvent
from sqlalchemy.engine import make_url
from ttkbootstrap import DateEntry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from normastore.bootstrap import bootstrap, build_application
from normastore.application.contracts import CheckoutLine, PaymentInput
from normastore.config import Settings
from normastore.domain.enums import CopyStatus, LineAction, PaymentMethod
from normastore.ui.app import NormaStoreApp
from normastore.ui.formatting import vnd
import normastore.ui.media as ui_media
from check_ui_layout import _visible_overflow


def widgets(root):
    for child in root.winfo_children():
        yield child
        yield from widgets(child)


def button(root, text):
    return next(w for w in widgets(root) if isinstance(w, ttk.Button) and w.cget("text") == text)


def fill_entry(root, label_text, value):
    label = next(w for w in widgets(root) if isinstance(w, ttk.Label) and w.cget("text") == label_text)
    siblings = label.master.winfo_children()
    entry = siblings[siblings.index(label) + 1]
    entry.delete(0, tk.END)
    entry.insert(0, value)


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
    show_title = "Bộ phim thử giao diện"
    show = service.create_show(show_title, actor_id=actor)
    poster_path = "/normastore-ui-smoke-poster.jpg"
    Image.new("RGB", (160, 220), "#28577C").save(poster_cache.path_for(poster_path))
    service.set_show_poster(show.id, poster_path, actor)
    service.create_show("ZZ Phim bộ ngoài kết quả thử", actor_id=actor)
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
        scaling = os.environ.get("NORMASTORE_UI_SCALING")
        if scaling:
            app.tk.call("tk", "scaling", float(scaling))
        font_scale = os.environ.get("NORMASTORE_UI_FONT")
        if font_scale:
            app.font_scale.set(font_scale)
        if scaling or font_scale:
            app._apply_ui_style()
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
        tree.item(root, open=True)
        tree.item(tree.parent(episode_node), open=True)
        tree.item(episode_node, open=True)
        pump()
        tree.selection_set(copy_node)
        x, y, _width, height = tree.bbox(copy_node)
        original_popup = tk.Menu.tk_popup
        tk.Menu.tk_popup = lambda menu, *_args: menu.invoke("Sửa bản đĩa đã chọn")
        try:
            tree.event_generate("<Button-3>", x=x + 4, y=y + height // 2)
        finally:
            tk.Menu.tk_popup = original_popup
        pump()
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

        confirmations = []
        messagebox.showinfo = lambda title, message, **_kwargs: confirmations.append((title, message))
        existing_barcodes = {copy.barcode for copy in service.checkout_copies(episodes[2].id, LineAction.BUY)}
        button(page, "Thêm đĩa").invoke()
        pump()
        add_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Thêm đĩa vào kho")
        item_tree = next(w for w in widgets(add_dialog) if isinstance(w, ttk.Treeview))
        item_tree.selection_set(str(episodes[2].id))
        button(add_dialog, "Thêm đĩa").invoke()
        pump()
        assert not add_dialog.winfo_exists(), "Không lưu được đĩa mới."
        current_barcodes = {copy.barcode for copy in service.checkout_copies(episodes[2].id, LineAction.BUY)}
        added_barcode, = current_barcodes - existing_barcodes
        assert added_barcode.startswith("DIA-")
        assert any(title == "Nhập kho" and added_barcode in text for title, text in confirmations)
        print("INVENTORY_ADD_COPY_OK", flush=True)

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
        with tempfile.TemporaryDirectory(prefix="normastore-cover-") as image_dir:
            cover = Path(image_dir) / "cover.png"
            Image.new("RGB", (50, 75), "blue").save(cover)
            filedialog.askopenfilename = lambda **_kwargs: str(cover)
            original_data_dir = ui_media.user_data_dir
            ui_media.user_data_dir = lambda _name: image_dir
            button(movie_dialog, "Chọn ảnh cục bộ").invoke()
            cover_box = next(w for w in widgets(movie_dialog) if isinstance(w, ttk.Labelframe) and w.cget("text") == "Ảnh bìa")
            assert next(w for w in cover_box.winfo_children() if isinstance(w, ttk.Entry)).get() == str(cover)
            try:
                button(movie_dialog, "Lưu").invoke()
                assert not movie_dialog.winfo_exists(), f"Không lưu được ảnh: {callback_errors}"
                demo_item = next(item for item in service.query_catalog().items if item.title == "Mẫu phim khởi động")
                saved_cover = service.catalog_item(demo_item.item_id).poster_path
                assert Path(saved_cover).is_file()
                editor = app._dialog("Kiểm tra ảnh bìa", 500, 260)
                holder = ttk.Frame(editor)
                holder.pack(fill="both", expand=True)
                prepare = app._poster_editor(holder, saved_cover)
                poster_entry = next(w for w in widgets(holder) if isinstance(w, ttk.Entry))
                original_fetch = app.poster_cache.fetch
                app.poster_cache.fetch = lambda _url: cover
                poster_entry.delete(0, tk.END)
                poster_entry.insert(0, "https://example.test/cover.png")
                assert prepare() == "https://example.test/cover.png"
                service.save_catalog_item(actor, id=demo_item.item_id, poster_path=prepare())
                assert service.catalog_item(demo_item.item_id).poster_path == "https://example.test/cover.png"
                def failed_fetch(_url):
                    raise OSError("không tải được")
                app.poster_cache.fetch = failed_fetch
                poster_entry.delete(0, tk.END)
                poster_entry.insert(0, "https://example.test/broken.png")
                try:
                    prepare()
                    raise AssertionError("Liên kết ảnh lỗi không bị từ chối")
                except ValueError:
                    assert service.catalog_item(demo_item.item_id).poster_path == "https://example.test/cover.png"
                finally:
                    service.save_catalog_item(actor, id=demo_item.item_id, poster_path=saved_cover)
                    app.poster_cache.fetch = original_fetch
                    editor.destroy()
            finally:
                ui_media.user_data_dir = original_data_dir
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
        assert not _visible_overflow(app, dialog), "Cửa sổ chọn tập bị tràn nội dung."
        show_picker = next(w for w in widgets(dialog) if isinstance(w, ttk.Combobox))
        assert len(show_picker.cget("values")) >= 2
        fill_entry(dialog, "Tìm phim bộ:", "khong co phim bo nay")
        assert not show_picker.get() and not show_picker.cget("values")
        fill_entry(dialog, "Tìm phim bộ:", "bo phim thu giao dien")
        assert len(show_picker.cget("values")) == 1 and show_title in show_picker.get()
        controls = next(w for w in widgets(dialog) if isinstance(w, ttk.Frame) and
                        any(isinstance(c, ttk.Label) and c.cget("text") == "Từ tập" for c in w.winfo_children()))
        entries = [w for w in controls.winfo_children() if w.winfo_class() == "TEntry"]
        entries[0].insert(0, "2")
        entries[1].insert(0, "4")
        button(dialog, "Chọn thuê").invoke()
        pump()
        assert any(isinstance(w, ttk.Label) and "Tập 4: Chưa nhập" in str(w.cget("text")) for w in widgets(dialog))
        choices = [w for w in widgets(dialog) if isinstance(w, ttk.Combobox) and
                   any("UI-EP-2-B" in str(value) for value in w.cget("values"))]
        assert len(choices) == 1, "Không có lựa chọn đĩa cho tập 2."
        choices[0].set(next(value for value in choices[0].cget("values") if "UI-EP-2-B" in value))
        episode_three_picker = next(w for w in widgets(dialog) if isinstance(w, ttk.Combobox)
                                    and any("UI-EP-3-A" in str(value) for value in w.cget("values")))
        episode_three_picker.set(next(value for value in episode_three_picker.cget("values")
                                      if "UI-EP-3-A" in value))
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
        assert len(texts) == 5 and any(added_barcode in text for text in texts)
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
        assert service.query_inventory(text=added_barcode).items[0].status == CopyStatus.SOLD
        print("CHECKOUT_PAYMENT_AND_ORDER_OK", flush=True)

        app.show_page("Đĩa đã được thuê", app.returns_page)
        pump()
        returns_page = app.pages["Đĩa đã được thuê"]
        returns_tree = next(w for w in widgets(returns_page) if isinstance(w, ttk.Treeview))
        rental = next(row for row in service.active_rentals() if row.barcode == "UI-EP-2-B")
        returns_tree.selection_set(str(rental.term_id))
        button(returns_page, "Trả đĩa").invoke()
        pump()
        return_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Trả đĩa")
        assert not _visible_overflow(app, return_dialog), "Cửa sổ trả đĩa bị tràn nội dung."
        outcome_picker = next(w for w in widgets(return_dialog) if isinstance(w, ttk.Combobox) and
                              "Hư nhẹ" in w.cget("values"))
        outcome_picker.set("Hư nhẹ")
        condition_picker = next(w for w in widgets(return_dialog) if isinstance(w, ttk.Combobox) and "Cũ" in w.cget("values"))
        condition_picker.set("Cũ")
        percent_label = next(w for w in widgets(return_dialog) if isinstance(w, ttk.Label) and w.cget("text") == "Tình trạng %")
        percent_entry = next(w for w in percent_label.master.winfo_children() if isinstance(w, ttk.Entry))
        percent_entry.delete(0, tk.END)
        percent_entry.insert(0, "55")
        button(return_dialog, "Trả đĩa").invoke()
        pump()
        returned_copy = service.query_inventory(text="UI-EP-2-B").items[0]
        assert returned_copy.status == CopyStatus.REPAIR and returned_copy.condition_percent == Decimal("55")
        other_rental = next(row for row in service.active_rentals() if row.barcode == "UI-EP-3-A")
        returns_tree.selection_set(str(other_rental.term_id))
        button(returns_page, "Gia hạn…").invoke()
        pump()
        extension_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Gia hạn thuê")
        assert not _visible_overflow(app, extension_dialog), "Cửa sổ gia hạn bị tràn nội dung."
        fee_label = next(w for w in widgets(extension_dialog) if isinstance(w, ttk.Label) and w.cget("text") == "Phí gia hạn thỏa thuận:")
        fee_entry = next(w for w in fee_label.master.winfo_children() if isinstance(w, ttk.Entry))
        fee_entry.insert(0, "17000")
        messagebox.askyesno = lambda *_args, **_kwargs: True
        button(extension_dialog, "Xác nhận gia hạn").invoke()
        pump()
        assert next(row for row in service.active_rentals() if row.term_id == other_rental.term_id).due_date == other_rental.due_date + timedelta(days=3)
        button(returns_page, "Trả hàng bán").invoke()
        pump()
        sale_dialog = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Trả hàng bán trong 7 ngày")
        sale_tree = next(w for w in widgets(sale_dialog) if isinstance(w, ttk.Treeview))
        sale_line = next(row for row in service.returnable_sales() if row.barcode == added_barcode)
        sale_tree.selection_set(str(sale_line.line_id))
        messagebox.askyesno = lambda *_args, **_kwargs: False
        button(sale_dialog, "Xác nhận hoàn").invoke()
        pump()
        assert service.query_inventory(text=added_barcode).items[0].status == CopyStatus.INSPECTION
        assert not sale_tree.exists(str(sale_line.line_id))
        sale_dialog.destroy()
        print("RENTAL_AND_SALE_RETURN_OK", flush=True)

        partial_copies = [
            service.add_copy(episodes[1].id, f"UI-PARTIAL-RETURN-{number}", actor_id=actor)
            for number in (1, 2)
        ]
        partial_lines = [CheckoutLine(copy.id, LineAction.RENT, date.today()) for copy in partial_copies]
        partial_order = service.checkout(
            customer.id, actor, partial_lines, [PaymentInput(PaymentMethod.CASH, Decimal("10000"))],
        )
        partial_receipt = service.order_receipt(partial_order.id)
        partial_rentals = [row for row in service.active_rentals() if row.order_code == partial_order.code]
        returns_page.refresh()
        returns_tree.selection_set(tuple(str(row.term_id) for row in partial_rentals))
        button(returns_page, "Trả đĩa").invoke()
        pump()
        partial_dialog = next(w for w in app.winfo_children()
                              if isinstance(w, tk.Toplevel) and w.title() == "Trả đĩa")
        unpaid_label = f"{partial_order.code}: {vnd(partial_receipt.balance_due)}"
        assert sum(isinstance(w, ttk.Label) and w.cget("text") == unpaid_label
                   for w in widgets(partial_dialog)) == 1
        assert any(isinstance(w, ttk.Label) and "Cọc đã thu: 10.000 đ" in w.cget("text")
                   for w in widgets(partial_dialog))
        assert partial_receipt.balance_due == partial_rentals[0].order_balance_due > 0
        outcome = next(w for w in widgets(partial_dialog) if isinstance(w, ttk.Combobox)
                       and "Hư nhẹ" in w.cget("values"))
        outcome.set("Hư nhẹ")

        def return_field(text):
            label = next(w for w in widgets(partial_dialog)
                         if isinstance(w, ttk.Label) and w.cget("text") == text)
            return next(w for w in label.master.winfo_children() if isinstance(w, ttk.Entry))

        damage_entry = return_field("Tiền phạt hư đĩa (đ):")
        damage_entry.insert(0, "20000")
        received_entry = return_field("Thu thêm sau cấn cọc:")
        assert Decimal(received_entry.get()) == Decimal("10000")
        received_entry.delete(0, tk.END)
        received_entry.insert(0, "4000")
        assert any(isinstance(w, ttk.Label) and w.cget("text") == "Còn thiếu tiền phạt: 6.000 đ"
                   for w in widgets(partial_dialog))
        button(partial_dialog, "Trả đĩa").invoke()
        assert not partial_dialog.winfo_exists()
        assert ("Trả đĩa", "Hoàn khách: 0 đ\nĐã thu thêm: 4.000 đ\nCòn thiếu tiền phạt: 6.000 đ") in confirmations
        print("PARTIAL_RENTAL_RETURN_OK", flush=True)

        app.show_page("Thống kê", app.statistics_page)
        pump(3)
        page = app.pages["Thống kê"]
        inventory_figure, analysis, revenue_figure, damage_figure, finance_figure = app._figures[-5:]
        revenue_axis = revenue_figure.axes[0]
        damage_axis = damage_figure.axes[0]
        genre_axis = analysis.axes[0]
        sections = next(w for w in widgets(page) if isinstance(w, ttk.Notebook)
                        and [w.tab(tab, "text") for tab in w.tabs()] == ["Tổng quan", "Tài chính", "Kho"])
        sections.select(1)
        pump(0.5)
        assert len(revenue_axis.lines) == 2, "Biểu đồ doanh thu thiếu thuê hoặc bán."
        assert damage_axis.patches, "Biểu đồ hỏng hóc thiếu lượt trả thử."
        assert genre_axis.patches, "Biểu đồ thể loại thiếu lượt bán thử."

        def hover_revenue():
            line = revenue_axis.lines[0]
            day = line.get_xdata()[-1]
            low, high = revenue_axis.get_ylim()
            x, y = revenue_axis.transData.transform((line.get_xdata(orig=False)[-1], (low + high) / 2))
            event = MouseEvent("motion_notify_event", revenue_figure.canvas, x, y)
            revenue_figure.canvas.callbacks.process(event.name, event)
            return day, next(text for text in revenue_axis.texts if text.get_visible())

        hovered_date, tooltip = hover_revenue()
        report = service.chart_report(hovered_date, hovered_date)
        expected = {action: amount for _, action, amount in report.revenue}
        assert tooltip.get_text() == (
            f"{hovered_date:%d/%m/%Y}\nThuê: {vnd(expected.get(LineAction.RENT, 0), exact=True)}"
            f"\nBán: {vnd(expected.get(LineAction.BUY, 0), exact=True)}"
        )
        outside = MouseEvent("motion_notify_event", revenue_figure.canvas, 0, 0)
        revenue_figure.canvas.callbacks.process(outside.name, outside)
        assert not tooltip.get_visible()
        action_picker = next(w for w in widgets(page) if isinstance(w, ttk.Combobox) and
                             "Tất cả giao dịch" in w.cget("values"))
        action_picker.set("Mua")
        button(page, "Áp dụng").invoke()
        pump(2)
        assert [line.get_label() for line in revenue_axis.lines] == ["Bán"]
        _, tooltip = hover_revenue()
        assert "Bán:" in tooltip.get_text() and "Thuê:" not in tooltip.get_text()
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
        assert tooltip not in revenue_axis.texts
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
        print("REVENUE_HOVER_TOOLTIP_OK", flush=True)

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
        selected_show = next(row for row in chart.get_children() if chart.item(row, "text") == show_title)
        chart.selection_set(selected_show)
        pump(1)
        poster = next(w for w in widgets(page) if isinstance(w, ttk.Label) and w.cget("style") == "Norma.Poster.TLabel")
        assert poster.cget("image"), "Kệ phim chưa hiển thị poster của phim đã chọn."
        chart.selection_remove(selected_show)
        pump()
        assert not poster.cget("image") and poster.cget("text") == "Chọn phim để xem"
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
        service.add_copy(episodes[0].id, "UI-CANCEL-PREORDER", actor_id=actor)
        service.reserve(customer.id, [episodes[0].id], actor)
        waiting_customer = service.add_customer("Khách chờ hủy cùng", "0988999011")
        service.reserve(waiting_customer.id, [episodes[0].id], actor)
        app.show_page("Đặt trước", app.reservations_page)
        pump()
        reservations_page = app.pages["Đặt trước"]
        reservation_tree = next(w for w in widgets(reservations_page) if isinstance(w, ttk.Treeview))
        search_entry = next(w for w in widgets(reservations_page) if isinstance(w, ttk.Entry)
                            and not isinstance(w, ttk.Combobox))
        search_entry.insert(0, "Khách chờ hủy")
        pump()
        assert [reservation_tree.set(row, "customer") for row in reservation_tree.get_children()] == [waiting_customer.full_name]
        search_entry.delete(0, tk.END)
        search_entry.insert(0, show_title)
        next(w for w in widgets(reservations_page) if isinstance(w, ttk.Radiobutton)
             and w.cget("text") == "Phim").invoke()
        pump()
        assert len(reservation_tree.get_children()) == 2
        search_entry.delete(0, tk.END)
        pump()
        assert len(reservation_tree.get_children()) > 2
        print("RESERVATION_SEARCH_OK", flush=True)
        reserved_episode = next(row for row in service.list_reservations() if row.item_id == episodes[0].id)
        episode_rows = {
            reservation_tree.set(i, "customer"): i for i in reservation_tree.get_children()
            if reservation_tree.set(i, "item") == reserved_episode.item_title
        }
        reservation_row = episode_rows[customer.full_name]
        waiting_row = episode_rows[waiting_customer.full_name]
        reservation_tree.see(reservation_row)
        pump()
        x, y, _width, height = reservation_tree.bbox(reservation_row)
        labels = []
        original_popup = tk.Menu.tk_popup
        def invoke_detail(menu, *_args):
            labels.extend(menu.entrycget(i, "label") for i in range(menu.index("end") + 1)
                          if menu.type(i) == "command")
            menu.invoke("Xem chi tiết phim / tập")
        tk.Menu.tk_popup = invoke_detail
        try:
            reservation_tree.event_generate("<Button-3>", x=x + 4, y=y + height // 2)
        finally:
            tk.Menu.tk_popup = original_popup
        pump()
        assert "Xem chi tiết bộ phim" in labels
        assert "Hủy đặt trước" in labels
        details = next(w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and w.title() == "Chi tiết phim / tập")
        details.destroy()
        print("DASHBOARD_STOCK_DISCOVERY_RANDOM_PREORDER_OK", flush=True)
        cancel_button = button(app.pages["Đặt trước"], "Hủy đặt trước")
        reservation_tree.selection_set(reservation_row, waiting_row)
        pump()
        assert not cancel_button.instate(["disabled"])
        messagebox.askyesno = lambda *_args, **_kwargs: False
        cancel_button.invoke()
        assert reservation_tree.item(reservation_row, "values")[2] == "Đang giữ"
        assert reservation_tree.item(waiting_row, "values")[2] == "Đang chờ"
        messagebox.askyesno = lambda *_args, **_kwargs: True
        tk.Menu.tk_popup = lambda menu, *_args: menu.invoke("Hủy đặt trước")
        try:
            reservation_tree.event_generate("<Button-3>", x=x + 4, y=y + height // 2)
        finally:
            tk.Menu.tk_popup = original_popup
        status_filter = next(w for w in widgets(reservations_page) if isinstance(w, ttk.Combobox)
                             and "Đã hủy" in w.cget("values"))
        status_filter.set("Đã hủy")
        pump()
        cancelled_rows = [i for i in reservation_tree.get_children()
                          if reservation_tree.set(i, "item") == reserved_episode.item_title]
        assert len(cancelled_rows) == 2
        assert all(reservation_tree.item(row, "values")[2:] == ("Đã hủy", "—") for row in cancelled_rows)
        reservation_tree.selection_set(cancelled_rows)
        pump()
        assert cancel_button.instate(["disabled"])
        assert not service.customer_preorder_copies(customer.id)
        print("RESERVATION_CANCEL_OK", flush=True)

        app.show_page("Khách hàng & Premium", app.customers_page)
        pump()
        customers_page = app.pages["Khách hàng & Premium"]
        customers_tree = next(w for w in widgets(customers_page) if isinstance(w, ttk.Treeview))
        customer_row = str(customer.id)
        customers_tree.see(customer_row)
        pump()
        x, y, _width, height = customers_tree.bbox(customer_row, "phone")
        for at in (1000, 1100):
            customers_tree.event_generate("<ButtonPress-1>", x=x + 4, y=y + height // 2, time=at)
            customers_tree.event_generate("<ButtonRelease-1>", x=x + 4, y=y + height // 2, time=at + 10)
        edit_dialog = next(w for w in app.winfo_children()
                           if isinstance(w, tk.Toplevel) and w.title() == "Sửa khách hàng")
        name, phone, email, address = [w for w in widgets(edit_dialog) if isinstance(w, ttk.Entry)]
        assert (name.get(), phone.get(), email.get(), address.get()) == (
            customer.full_name, customer.phone, customer.email, customer.address,
        )
        name.delete(0, tk.END)
        name.insert(0, "Khách đã sửa qua bảng")
        button(edit_dialog, "Lưu khách hàng").invoke()
        assert not edit_dialog.winfo_exists()
        assert customers_tree.item(customer_row, "text") == "Khách đã sửa qua bảng"
        assert service.list_customers(customer.phone)[0].id == customer.id
        print("CUSTOMER_DOUBLE_CLICK_EDIT_OK", flush=True)

        def invoke_customer_action(customer_id, label):
            row = str(customer_id)
            customers_tree.see(row)
            app.update_idletasks()
            x, y, _width, height = customers_tree.bbox(row, "phone")
            original_popup = tk.Menu.tk_popup
            tk.Menu.tk_popup = lambda menu, *_args: menu.invoke(label)
            try:
                customers_tree.event_generate("<Button-3>", x=x + 4, y=y + height // 2)
            finally:
                tk.Menu.tk_popup = original_popup

        service.activate_premium(customer.id, 30, actor)
        customers_page.refresh()
        new_end = date.today() + timedelta(days=12)
        simpledialog.askstring = lambda *_args, **_kwargs: f"{new_end:%d/%m/%Y}"
        invoke_customer_action(customer.id, "Chỉnh hạn Premium")
        assert service.premium_until(customer.id) == new_end
        messagebox.askyesno = lambda *_args, **_kwargs: True
        invoke_customer_action(customer.id, "Hủy Premium")
        assert not service.premium_active(customer.id)
        assert customers_tree.set(customer_row, "premium") == "Thường"
        unused = service.add_customer("Khách chưa có lịch sử", "0988999001")
        customers_page.refresh()
        messagebox.askyesno = lambda *_args, **_kwargs: False
        invoke_customer_action(unused.id, "Xóa khách hàng")
        assert customers_tree.exists(str(unused.id))
        messagebox.askyesno = lambda *_args, **_kwargs: True
        invoke_customer_action(unused.id, "Xóa khách hàng")
        assert not customers_tree.exists(str(unused.id))
        assert service.list_customers(unused.phone) == []
        print("CUSTOMER_CONTEXT_ACTIONS_OK", flush=True)

        app.show_page("Combo / Voucher", app.promotions_page)
        promotions = app.pages["Combo / Voucher"]
        button(promotions, "Tạo combo cố định").invoke()
        fixed_dialog = next(w for w in app.winfo_children()
                            if isinstance(w, tk.Toplevel) and w.title() == "Tạo combo cố định")
        pump()
        assert not _visible_overflow(app, fixed_dialog), "Cửa sổ tạo combo cố định bị tràn nội dung."
        results, chosen = [w for w in widgets(fixed_dialog) if isinstance(w, ttk.Treeview)]
        fill_entry(fixed_dialog, "Tìm phim hoặc tập:", "Phim sắp ra thử")
        button(fixed_dialog, "Tìm").invoke()
        assert results.get_children() == (str(future.id),)
        results.selection_set(str(future.id))
        button(fixed_dialog, "Thêm vào combo").invoke()
        fill_entry(fixed_dialog, "Tìm phim hoặc tập:", show_title)
        button(fixed_dialog, "Tìm").invoke()
        assert results.set(str(episodes[0].id), "detail") == f"{show_title} • Mùa 1, tập 1"
        results.selection_set(str(episodes[0].id))
        button(fixed_dialog, "Thêm vào combo").invoke()
        assert chosen.get_children() == (str(future.id), str(episodes[0].id))
        fill_entry(fixed_dialog, "Tên combo:", "Combo cố định thử giao diện")
        fill_entry(fixed_dialog, "Số tiền giảm (đ):", "10000")
        button(fixed_dialog, "Lưu combo").invoke()
        assert not fixed_dialog.winfo_exists()
        assert any(row.name == "Combo cố định thử giao diện" and row.rule_type == "FIXED"
                   for row in service.list_combos())

        button(promotions, "Tạo combo N tập cùng bộ").invoke()
        episode_dialog = next(w for w in app.winfo_children()
                              if isinstance(w, tk.Toplevel) and w.title() == "Tạo combo N tập cùng bộ")
        fill_entry(episode_dialog, "Tên combo:", "Combo phim bộ thử giao diện")
        fill_entry(episode_dialog, "Số tiền giảm (đ):", "15000")
        fill_entry(episode_dialog, "Tìm phim bộ:", "bo phim thu giao dien")
        button(episode_dialog, "Lưu combo").invoke()
        assert not episode_dialog.winfo_exists()
        episode_combo = next(row for row in service.list_combos() if row.name == "Combo phim bộ thử giao diện")
        assert (episode_combo.scope, episode_combo.required_count) == (show_title, 2)
        print("COMBO_SEARCH_AND_SELECTION_OK", flush=True)

        assert not background_variables, f"Biến giao diện bị giải phóng ở luồng nền: {background_variables}"
        assert not callback_errors, f"Lỗi callback giao diện: {callback_errors}"
    finally:
        app._close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
