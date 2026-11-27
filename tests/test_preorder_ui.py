from tkinter import ttk, messagebox
from types import SimpleNamespace

import ttkbootstrap as tb
import pytest

from normastore.application._operations import _StoreOperations
from normastore.ui.pages.checkout import CheckoutPageMixin
from normastore.ui.pages.dashboard import DashboardPageMixin
from normastore.ui.pages.inventory import InventoryPageMixin
from normastore.ui.pages.statistics import StatisticsPageMixin
from normastore.ui.pages.reservations import ReservationsPageMixin
from normastore.ui.pages.customers import CustomersPageMixin
from normastore.ui.theme import AppearanceMixin, theme_palette
from normastore.ui.widgets import CommonWidgetsMixin


def widgets(root):
    for child in root.winfo_children():
        yield child
        yield from widgets(child)


def button(root, text):
    return next(widget for widget in widgets(root)
                if isinstance(widget, ttk.Button) and widget.cget("text") == text)


class PageHarness(CheckoutPageMixin, InventoryPageMixin, CommonWidgetsMixin, tb.Window):
    def __init__(self, store, actor):
        super().__init__(themename="flatly")
        self.withdraw()
        self.store = store
        self.account = SimpleNamespace(employee_id=actor)
        self._theme_canvases = []
        self.callback_errors = []
        self.report_callback_exception = lambda _kind, error, _trace: self.callback_errors.append(error)

    def _font(self, _role="body"):
        return ("Segoe UI", 10)

    def _can_manage(self):
        return True

    def _run_async(self, work, done, failed=None):
        done(work())

    def _create_treeview(self, parent, **kwargs):
        tree = super()._create_treeview(parent, **kwargs)
        tree.test_bindings = {}
        original = tree.bind

        def bind(sequence=None, func=None, add=None, **options):
            if sequence is not None and func is not None:
                tree.test_bindings[sequence] = func
            return original(sequence, func, add, **options)

        tree.bind = bind
        return tree


@pytest.fixture(scope="module")
def ui_root():
    app = PageHarness(None, None)
    yield app
    app.destroy()


@pytest.fixture
def ui_app(ui_root):
    ui_root.callback_errors.clear()
    yield ui_root
    for identifier in ui_root.tk.splitlist(ui_root.tk.call("after", "info")):
        ui_root.after_cancel(identifier)
    for child in ui_root.winfo_children():
        child.destroy()


def test_checkout_switches_preorders_preserves_manual_lines_and_honors_removal(session, monkeypatch, ui_app):
    service = _StoreOperations(session)
    actor = service.authenticate("admin", "admin123").employee_id
    customers = [service.add_customer(f"Khách giỏ đặt trước {i}", f"098711113{i}") for i in range(2)]
    copies = []
    for customer in customers:
        item = service.save_catalog_item(actor, item_type="MOVIE", title=customer.full_name)
        service.reserve(customer.id, [item.id], actor)
        copies.append(service.add_copies(item.id, 1, actor_id=actor)[0])
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Đĩa thêm tay trong giỏ")
    manual, = service.add_copies(item.id, 1, actor_id=actor)
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **_: errors.append((title, message)))
    app = ui_app
    app.store, app.account = service, SimpleNamespace(employee_id=actor)
    try:
        page = ttk.Frame(app)
        app.checkout_page(page)
        page.refresh()
        customer_combo = next(widget for widget in widgets(page) if isinstance(widget, ttk.Combobox)
                              and any("Khách giỏ đặt trước" in str(value) for value in widget["values"]))
        cart = next(widget for widget in widgets(page) if isinstance(widget, ttk.Treeview)
                    and "note" in widget["columns"])
        catalog = next(widget for widget in widgets(page) if isinstance(widget, ttk.Treeview)
                       and "rentable_copies" in widget["columns"])

        def choose_customer(customer):
            customer_combo.set(next(value for value in customer_combo["values"]
                                    if value.startswith(f"{customer.id} —")))

        choose_customer(customers[0])
        assert cart.get_children() == (str(copies[0].copy_id),)
        assert cart.set(str(copies[0].copy_id), "note") == "Đặt trước"
        catalog.selection_set(str(item.id))
        catalog.test_bindings["<<TreeviewSelect>>"]()

        def confirm_copy():
            dialog = next(widget for widget in app.winfo_children() if isinstance(widget, tb.Toplevel))
            button(dialog, "Chọn đĩa").invoke()

        app.after(30, confirm_copy)
        button(page, "+ Thuê").invoke()
        assert set(cart.get_children()) == {str(copies[0].copy_id), str(manual.copy_id)}
        choose_customer(customers[1])
        assert set(cart.get_children()) == {str(copies[1].copy_id), str(manual.copy_id)}
        assert cart.set(str(manual.copy_id), "note") == ""
        page.refresh()
        assert len(cart.get_children()) == 2
        cart.selection_set(str(copies[1].copy_id))
        cart.test_bindings["<<TreeviewSelect>>"]()
        button(page, "Xóa dòng").invoke()
        page.refresh()
        assert cart.get_children() == (str(manual.copy_id),)
        choose_customer(customers[0])
        choose_customer(customers[1])
        assert set(cart.get_children()) == {str(copies[1].copy_id), str(manual.copy_id)}
        cart.selection_set(str(manual.copy_id))
        cart.test_bindings["<Delete>"](None)
        assert cart.get_children() == (str(copies[1].copy_id),)
        button(page, "Xóa tất cả").invoke()
        assert not cart.get_children()
        page.refresh()
        assert not cart.get_children()
        assert not errors and not app.callback_errors
    finally:
        page.destroy()


def test_checkout_can_sell_membership_without_discs(session, monkeypatch, ui_app):
    from decimal import Decimal
    from normastore.domain.enums import PaymentMethod
    from normastore.infrastructure.database.models import PremiumMembership
    from sqlalchemy import select
    from tkinter import simpledialog

    service = _StoreOperations(session)
    actor = service.authenticate("admin", "admin123").employee_id
    customer = service.add_customer("Khách mua gói giao diện", "0987111129")
    app = ui_app
    app.store, app.account = service, SimpleNamespace(employee_id=actor)
    monkeypatch.setattr(simpledialog, "askstring", lambda *_args, **_kwargs: "59000")
    monkeypatch.setattr(app, "_choose_payment_method", lambda *_args: PaymentMethod.CASH)
    monkeypatch.setattr(app, "_refresh_status", lambda: None, raising=False)
    monkeypatch.setattr(messagebox, "showinfo", lambda *_args, **_kwargs: None)
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda _title, message, **_kwargs: errors.append(message))
    page = ttk.Frame(app)
    try:
        app.checkout_page(page)
        page.refresh()
        page.select_customer(customer)
        plan = next(widget for widget in widgets(page) if isinstance(widget, ttk.Combobox)
                    and any(str(value).startswith("30 ngày") for value in widget["values"]))
        plan.set(next(value for value in plan["values"] if str(value).startswith("30 ngày")))
        button(page, "Hoàn tất").invoke()
        membership = session.scalar(select(PremiumMembership).where(PremiumMembership.customer_id == customer.id))
        assert membership and membership.price_paid == Decimal("59000")
        assert not errors and not app.callback_errors
    finally:
        page.destroy()


def test_checkout_can_reserve_multiple_upcoming_items(session, monkeypatch, ui_app):
    from sqlalchemy import select
    from normastore.infrastructure.database.models import Reservation

    service = _StoreOperations(session)
    actor = service.authenticate("admin", "admin123").employee_id
    customer = service.add_customer("Khách đặt nhiều phim", "0987111128")
    items = [service.save_catalog_item(actor, item_type="MOVIE", title=f"Phim đặt nhiều {index}")
             for index in range(2)]
    app = ui_app
    app.store, app.account = service, SimpleNamespace(employee_id=actor)
    monkeypatch.setattr(messagebox, "showinfo", lambda *_args, **_kwargs: None)
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda _title, message, **_kwargs: errors.append(message))
    page = ttk.Frame(app)
    try:
        app.checkout_page(page)
        page.refresh()
        page.select_customer(customer)
        page.open_reservations([item.id for item in items])
        button(page, "Đặt trước phim đã chọn").invoke()
        result = session.scalars(select(Reservation).where(Reservation.customer_id == customer.id)).all()
        assert {reservation.item_id for reservation in result} == {item.id for item in items}
        assert not errors and not app.callback_errors
    finally:
        page.destroy()


def test_statistics_tabs_render_inventory_pie(session, monkeypatch, ui_app, tmp_path):
    from dataclasses import replace
    from decimal import Decimal
    from matplotlib.backend_bases import MouseEvent, PickEvent
    from normastore.application.reporting import TopCustomer
    from tkinter import filedialog
    from ttkbootstrap.widgets.scrolled import ScrolledFrame
    service = _StoreOperations(session)
    app = ui_app
    app.store = service
    service.cache_revision = 0
    app._figures = []
    app._palette = theme_palette(False)
    app._style_figure = lambda figure: AppearanceMixin._style_figure(app, figure)
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda _title, message, **_kwargs: errors.append(message))
    page = ttk.Frame(app)
    try:
        StatisticsPageMixin.statistics_page(app, page)
        page.refresh()
        notebooks = [widget for widget in widgets(page) if isinstance(widget, ttk.Notebook)]
        sections = next(widget for widget in notebooks if [widget.tab(tab, "text") for tab in widget.tabs()]
                        == ["Tổng quan", "Tài chính", "Kho"])
        page.pack(fill="both", expand=True)
        app.deiconify()
        sections.select(2)
        app.update()
        stock_tab = app.nametowidget(sections.tabs()[2])
        scroller = next(widget for widget in widgets(stock_tab) if isinstance(widget, ScrolledFrame))
        scroll_calls = []
        monkeypatch.setattr(scroller, "yview_scroll", lambda amount, units: scroll_calls.append((amount, units)))
        chart_widget = app._figures[0].canvas.get_tk_widget()
        chart_widget.event_generate("<MouseWheel>", delta=-120)
        app.update()
        assert scroll_calls == [(1, "units")]
        inventory_axis = app._figures[0].axes[0]
        assert inventory_axis.get_title() == "Trạng thái tồn kho"
        assert inventory_axis.patches or any(text.get_text() == "Kho chưa có đĩa" for text in inventory_axis.texts)
        report = service.operational_report()
        finance_figure = app._figures[4]
        assert [axis.get_title() for axis in finance_figure.axes[:3]] == [
            "Doanh thu phát sinh", "Dòng tiền (gồm cọc)",
            f"Giá trị và giảm giá ({report.average_discount_rate:.2f}%)",
        ]
        assert len(finance_figure.axes[0].patches) == 3
        assert len(finance_figure.axes[1].patches) == 3
        from normastore.ui.formatting import vnd
        assert vnd(report.rental_revenue, exact=True) in [text.get_text() for text in finance_figure.axes[0].texts]
        assert vnd(report.deposits_held, exact=True) in [text.get_text() for text in finance_figure.axes[4].texts]
        top_customer = TopCustomer(987, "Khách kiểm thử", "0901234567", 2, Decimal("150000"))
        sample_report = replace(report, available=0, held=1, rented=0, inspection=0, repair=0, lost=0, retired=0,
                                top_customers=(top_customer,))
        monkeypatch.setattr(service, "operational_report", lambda *_args: sample_report)
        page.refresh()
        figure = app._figures[0]
        customer_tree = next(widget for widget in widgets(page) if isinstance(widget, ttk.Treeview)
                             and "orders" in widget["columns"] and "total" in widget["columns"])
        assert customer_tree.item("987", "text") == "Khách kiểm thử"
        assert customer_tree.set("987", "total") == "150.000 đ"
        from matplotlib.colors import to_rgba
        legend = inventory_axis.get_legend()
        assert legend.get_frame().get_facecolor() == to_rgba(app._palette.surface)
        app._palette = theme_palette(True)
        AppearanceMixin._style_figure(app, figure)
        assert legend.get_frame().get_facecolor() == to_rgba(app._palette.surface)
        assert all(text.get_color() == app._palette.foreground for text in legend.get_texts())
        mouse = MouseEvent("button_press_event", figure.canvas, 0, 0)
        figure.canvas.callbacks.process("pick_event", PickEvent("pick_event", figure.canvas, mouse, inventory_axis.patches[0]))
        assert any(isinstance(widget, tb.Toplevel) and widget.title() == "Kho: Đang giữ"
                   for widget in app.winfo_children())
        for widget in app.winfo_children():
            if isinstance(widget, tb.Toplevel):
                widget.destroy()
        empty_report = replace(report, available=0, held=0, rented=0, inspection=0, repair=0, lost=0, retired=0)
        monkeypatch.setattr(service, "operational_report", lambda *_args: empty_report)
        page.refresh()
        assert not inventory_axis.patches
        assert any(text.get_text() == "Kho chưa có đĩa" for text in inventory_axis.texts)
        empty_finance = replace(empty_report, discounts_by_source=(), net_cash_flow=-1000,
                                top_customers=(top_customer,))
        monkeypatch.setattr(service, "operational_report", lambda *_args: empty_finance)
        page.refresh()
        assert any(text.get_text() == "Không có dữ liệu" for text in finance_figure.axes[3].texts)
        assert finance_figure.axes[1].patches[2].get_width() == -1000
        monkeypatch.setattr(messagebox, "showinfo", lambda *_args, **_kwargs: None)
        for index in range(3):
            sections.select(index)
            output = tmp_path / f"statistics-{index}.png"
            monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **_kwargs: str(output))
            button(page, "Xuất ảnh").invoke()
            assert output.read_bytes().startswith(b"\x89PNG")
        output_csv = tmp_path / "statistics.csv"
        monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **_kwargs: str(output_csv))
        button(page, "Xuất CSV").invoke()
        assert "Đang giữ" in output_csv.read_text(encoding="utf-8-sig")
        assert "Khách kiểm thử,0901234567,2,150000" in output_csv.read_text(encoding="utf-8-sig")
        assert not errors and not app.callback_errors
    finally:
        app.withdraw()
        page.destroy()


def test_statistics_table_wheel_stays_single_after_reenter(session, monkeypatch, ui_app):
    from ttkbootstrap.widgets.scrolled import ScrolledFrame

    service = _StoreOperations(session)
    service.cache_revision = 0
    app = ui_app
    app.store = service
    app._figures = []
    app._palette = theme_palette(False)
    app._style_figure = lambda figure: AppearanceMixin._style_figure(app, figure)
    page = ttk.Frame(app)
    try:
        StatisticsPageMixin.statistics_page(app, page)
        page.pack(fill="both", expand=True)
        app.deiconify()
        app.update()
        scroller = next(widget for widget in widgets(page) if isinstance(widget, ScrolledFrame))
        table = next(widget for widget in widgets(page) if isinstance(widget, ttk.Treeview)
                     and str(widget.heading("#0", "text")) == "Khách hàng")
        table_calls, page_calls = [], []
        monkeypatch.setattr(table, "yview_scroll", lambda amount, units: table_calls.append((amount, units)))
        monkeypatch.setattr(scroller, "yview_scroll", lambda amount, units: page_calls.append((amount, units)))
        for _ in range(2):
            scroller._del_scroll_binding(scroller)
            scroller._add_scroll_binding(scroller)
            table.event_generate("<MouseWheel>", delta=-120)
            app.update()
        assert table_calls == [(1, "units"), (1, "units")]
        assert not page_calls and not app.callback_errors
    finally:
        app.withdraw()
        page.destroy()


def test_reservation_cards_filter_and_cancel(session, monkeypatch, ui_app):
    from normastore.domain.enums import ReservationState
    service = _StoreOperations(session)
    actor = service.authenticate("admin", "admin123").employee_id
    customer = service.add_customer("Khách thẻ đặt trước", "0987111127")
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim thẻ đặt trước")
    service.reserve(customer.id, [item.id], actor)
    app = ui_app
    app.store, app.account = service, SimpleNamespace(employee_id=actor)
    monkeypatch.setattr(app, "_load_poster_thumbnail", lambda *_args: None, raising=False)
    monkeypatch.setattr(messagebox, "askyesno", lambda *_args, **_kwargs: True)
    page = ttk.Frame(app)
    try:
        ReservationsPageMixin.reservations_page(app, page)
        page.refresh()
        picker = next(widget for widget in widgets(page) if isinstance(widget, ttk.Combobox)
                      and "Thẻ" in widget["values"])
        picker.set("Thẻ")
        card = next(widget for widget in widgets(page) if isinstance(widget, ttk.Labelframe)
                    and widget.cget("text") == item.title)
        check = next(widget for widget in widgets(card) if isinstance(widget, ttk.Checkbutton))
        check.invoke()
        button(page, "Hủy đặt trước").invoke()
        assert service.list_reservations()[-1].state == ReservationState.CANCELLED
        assert not app.callback_errors
    finally:
        page.destroy()


def test_reservation_ui_can_select_specific_copy(session, monkeypatch, ui_app):
    from normastore.infrastructure.database.models import Reservation
    from sqlalchemy import select

    service = _StoreOperations(session)
    actor = service.authenticate("admin", "admin123").employee_id
    customer = service.add_customer("Khách chọn bản đĩa", "0987111126")
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim chọn bản đĩa")
    created = service.add_copies(item.id, 2, actor_id=actor)
    app = ui_app
    app.store, app.account = service, SimpleNamespace(employee_id=actor)
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda _title, message, **_kwargs: errors.append(message))
    page = ttk.Frame(app)
    try:
        ReservationsPageMixin.reservations_page(app, page)
        page.refresh()
        button(page, "Tạo đặt trước").invoke()
        dialog = next(widget for widget in app.winfo_children() if isinstance(widget, tb.Toplevel)
                      and widget.title() == "Tạo đặt trước")
        customer_picker = next(widget for widget in widgets(dialog) if isinstance(widget, ttk.Combobox)
                               and any(str(value).startswith(f"{customer.id} —") for value in widget["values"]))
        customer_picker.set(next(value for value in customer_picker["values"] if str(value).startswith(f"{customer.id} —")))
        picker = next(widget for widget in widgets(dialog) if isinstance(widget, ttk.Treeview) and "stock" in widget["columns"])
        picker.selection_set(str(item.id))
        button(dialog, "Chọn bản đĩa cho phim đã chọn").invoke()
        copy_dialog = next(widget for widget in app.winfo_children() if isinstance(widget, tb.Toplevel)
                           and widget.title() == "Chọn bản đĩa đặt trước")
        copy_tree = next(widget for widget in widgets(copy_dialog) if isinstance(widget, ttk.Treeview))
        copy_tree.selection_set(str(created[1].copy_id))
        button(copy_dialog, "Chọn đĩa").invoke()
        button(dialog, "Xác nhận đặt trước").invoke()
        reservation = session.scalar(select(Reservation).where(Reservation.customer_id == customer.id))
        assert reservation.allocated_copy_id == created[1].copy_id
        assert not errors and not app.callback_errors
    finally:
        page.destroy()


def test_customer_history_opens_correct_invoice(session, monkeypatch, ui_app):
    from datetime import date, timedelta
    from decimal import Decimal
    from normastore.application.contracts import CheckoutLine, PaymentInput
    from normastore.domain.enums import LineAction, PaymentMethod

    service = _StoreOperations(session)
    actor = service.authenticate("admin", "admin123").employee_id
    customer = service.add_customer("Khách xem lịch sử", "0987111125")
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim lịch sử giao diện")
    copy = service.add_copy(item.id, actor_id=actor)
    order = service.checkout(customer.id, actor, [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
                             [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
    app = ui_app
    app.store, app.account = service, SimpleNamespace(employee_id=actor)
    opened = []
    app.pages = {"Hóa đơn đã tạo": SimpleNamespace(open_order=opened.append)}
    page = ttk.Frame(app)
    try:
        CustomersPageMixin.customers_page(app, page)
        page.refresh()
        tree = next(widget for widget in widgets(page) if isinstance(widget, ttk.Treeview))
        tree.selection_set(str(customer.id))
        button(page, "Lịch sử thuê").invoke()
        dialog = next(widget for widget in app.winfo_children() if isinstance(widget, tb.Toplevel)
                      and widget.title().startswith("Lịch sử thuê"))
        history = next(widget for widget in widgets(dialog) if isinstance(widget, ttk.Treeview))
        history.selection_set(history.get_children()[0])
        button(dialog, "Xem hóa đơn").invoke()
        assert opened == [order.id]
        assert not app.callback_errors
    finally:
        page.destroy()


def test_dashboard_tabs_route_selected_items_to_checkout(monkeypatch, ui_app):
    from datetime import date, timedelta
    from normastore.application.contracts import PagedResult
    from normastore.domain.enums import LineAction

    app = ui_app
    app.calls = []
    app.pages = {"Tạo phiếu": SimpleNamespace(
        add_catalog_item=lambda item, action: app.calls.append(("item", item, action)),
        select_season=lambda show, action: app.calls.append(("show", show, action)),
        open_reservations=lambda items: app.calls.append(("reserve", *items)),
    )}
    monkeypatch.setattr(app, "show_page", lambda name, builder: app.calls.append(("page", name)), raising=False)
    app.store = SimpleNamespace(
        dashboard_popular_targets=lambda action: [(7, None, "Bộ", 2)] if action == LineAction.RENT else [(None, 8, "Phim", 1)],
        dashboard_discovery=lambda: [(9, "Khám phá", 1, False, 0, None, None)],
        dashboard_random=lambda: [(10, "Ngẫu nhiên"), (13, "Phim thứ hai")],
        query_dashboard_upcoming=lambda _request: PagedResult(((11, "Sắp ra", date.today() + timedelta(days=1)),
                                                               (14, "Sắp phát hành", date.today() + timedelta(days=1))), 1, 50, 2, 1),
        today_recommendations=lambda: [SimpleNamespace(item_id=12, title="Đề cử", reason="Phù hợp")],
    )
    page = ttk.Frame(app)
    try:
        DashboardPageMixin.dashboard_page(app, page)
        notebook = next(widget for widget in widgets(page) if isinstance(widget, ttk.Notebook))
        expected = [("show", 7, LineAction.RENT), ("item", 8, LineAction.BUY),
                    ("item", 9, LineAction.RENT), ("item", 10, LineAction.RENT),
                    ("reserve", 11), ("item", 12, LineAction.RENT)]
        for index, target in enumerate(expected, 1):
            notebook.select(index)
            notebook.event_generate("<<NotebookTabChanged>>")
            app.update()
            tab = app.nametowidget(notebook.tabs()[index])
            tree = next(widget for widget in widgets(tab) if isinstance(widget, ttk.Treeview))
            assert str(tree.cget("selectmode")) == "extended"
            tree.selection_set(tree.get_children()[0])
            button(tab, "Tạo phiếu").invoke()
            assert app.calls[-1] == target
            if index == 4:
                app.calls.clear()
                tree.selection_set(tree.get_children())
                button(tab, "Tạo phiếu").invoke()
                assert app.calls == [("page", "Tạo phiếu"), ("item", 10, LineAction.RENT),
                                     ("item", 13, LineAction.RENT)]
            if index == 5:
                tree.selection_set(tree.get_children())
                button(tab, "Tạo phiếu").invoke()
                assert app.calls[-1] == ("reserve", 11, 14)
        assert not app.callback_errors
    finally:
        page.destroy()


def test_checkout_search_shows_held_disc_only_for_its_customer(session, monkeypatch, ui_app):
    service = _StoreOperations(session)
    actor = service.authenticate("admin", "admin123").employee_id
    owner = service.add_customer("Khách tìm đĩa đang giữ", "0987111140")
    other = service.add_customer("Khách không giữ đĩa", "0987111141")
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim đang giữ cần tìm")
    service.reserve(owner.id, [item.id], actor)
    copy, = service.add_copies(item.id, 1, actor_id=actor)
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **_: errors.append((title, message)))
    app = ui_app
    app.store, app.account = service, SimpleNamespace(employee_id=actor)
    monkeypatch.setattr(app, "_debounce", lambda _holder, callback: callback())
    page = ttk.Frame(app)
    try:
        app.checkout_page(page)
        page.refresh()
        customer_combo = next(widget for widget in widgets(page) if isinstance(widget, ttk.Combobox)
                              and any(owner.full_name in str(value) for value in widget["values"]))
        catalog = next(widget for widget in widgets(page) if isinstance(widget, ttk.Treeview)
                       and "rentable_copies" in widget["columns"])
        cart = next(widget for widget in widgets(page) if isinstance(widget, ttk.Treeview)
                    and "note" in widget["columns"])
        search = next(widget for widget in widgets(page) if isinstance(widget, ttk.Entry)
                      and not isinstance(widget, ttk.Combobox)
                      and isinstance(widget.master, ttk.Labelframe)
                      and widget.master.cget("text") == "Tìm phim / tập")
        customer_combo.set(next(value for value in customer_combo["values"]
                                if value.startswith(f"{owner.id} —")))
        search.insert(0, item.title)
        assert catalog.get_children() == (str(item.id),)
        assert cart.get_children() == (str(copy.copy_id),)
        assert cart.set(str(copy.copy_id), "note") == "Đặt trước"
        # Changing customers must refresh the same search, without extra typing.
        customer_combo.set(next(value for value in customer_combo["values"]
                                if value.startswith(f"{other.id} —")))
        assert catalog.get_children() == ()
        assert cart.get_children() == ()
        customer_combo.set(next(value for value in customer_combo["values"]
                                if value.startswith(f"{owner.id} —")))
        assert catalog.get_children() == (str(item.id),)
        assert cart.get_children() == (str(copy.copy_id),)
        assert not errors and not app.callback_errors
    finally:
        page.destroy()


@pytest.mark.parametrize("context", ["movie", "show", "season"])
def test_inventory_context_menu_imports_quantity_with_generated_codes(session, monkeypatch, ui_app, context):
    service = _StoreOperations(session)
    actor = service.authenticate("admin", "admin123").employee_id
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim nhập từ chuột phải")
    if context != "movie":
        show = service.create_show("Phim bộ nhập từ chuột phải", actor_id=actor)
        episodes = service.add_episodes_bulk(show.id, 1, 1, 2, actor_id=actor)
        other_season = service.add_episodes_bulk(show.id, 2, 1, 1, actor_id=actor)
        item = episodes[0]
        for episode in [episodes[1], *other_season]:
            service.add_copies(episode.id, 1, actor_id=actor)
    service.add_copies(item.id, 1, actor_id=actor)
    errors, menus = [], []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **_: errors.append((title, message)))
    monkeypatch.setattr(messagebox, "showinfo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tkinter.Menu.tk_popup", lambda menu, *_args: menus.append(menu))
    app = ui_app
    app.store, app.account = service, SimpleNamespace(employee_id=actor)
    try:
        page = ttk.Frame(app)
        app.inventory_page(page)
        page.refresh()
        tree = next(widget for widget in widgets(page) if isinstance(widget, ttk.Treeview))
        target = f"item:{item.id}" if context == "movie" else f"show:{show.id}"
        if context == "season":
            tree.focus(target)
            tree.test_bindings["<<TreeviewOpen>>"]()
            target = next(child for child in tree.get_children(target) if tree.item(child, "text") == "Mùa 1")
        monkeypatch.setattr(tree, "identify_row", lambda _y: target)
        tree.test_bindings["<Button-3>"](SimpleNamespace(y=0, x_root=0, y_root=0))
        assert menus[-1].entrycget(0, "label") == "Thêm đĩa"
        menus[-1].invoke(0)
        dialog = next(widget for widget in app.winfo_children() if isinstance(widget, tb.Toplevel))
        picker = next(widget for widget in widgets(dialog) if isinstance(widget, ttk.Treeview))
        if context == "movie":
            assert picker.selection() == (str(item.id),)
        else:
            expected = episodes if context == "season" else [*episodes, *other_season]
            assert set(picker.get_children()) == {str(episode.id) for episode in expected}
            picker.selection_set(str(item.id))
        quantity = next(widget for widget in widgets(dialog) if isinstance(widget, ttk.Spinbox))
        assert quantity.get() == "1"
        quantity.set("3")
        button(dialog, "Thêm đĩa").invoke()
        copies = service.query_inventory(item_id=item.id).items
        assert len(copies) == 4
        assert len({copy.barcode for copy in copies}) == 4
        assert all(copy.barcode.startswith("DIA-") for copy in copies)
        assert not errors and not app.callback_errors
    finally:
        page.destroy()


def test_inventory_bulk_edit_selected_copies(session, monkeypatch, ui_app):
    service = _StoreOperations(session)
    actor = service.authenticate("admin", "admin123").employee_id
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim sửa nhiều đĩa giao diện")
    created = service.add_copies(item.id, 2, actor_id=actor)
    errors = []
    menus = []
    monkeypatch.setattr(messagebox, "showerror", lambda _title, message, **_kwargs: errors.append(message))
    monkeypatch.setattr(messagebox, "showinfo", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("tkinter.Menu.tk_popup", lambda menu, *_args: menus.append(menu))
    app = ui_app
    app.store, app.account = service, SimpleNamespace(employee_id=actor)
    page = ttk.Frame(app)
    try:
        app.inventory_page(page)
        page.refresh()
        tree = next(widget for widget in widgets(page) if isinstance(widget, ttk.Treeview))
        tree.focus(f"item:{item.id}")
        tree.test_bindings["<<TreeviewOpen>>"]()
        tree.selection_set([str(copy.copy_id) for copy in created])
        monkeypatch.setattr(tree, "identify_row", lambda _y: str(created[1].copy_id))
        tree.test_bindings["<Button-3>"](SimpleNamespace(y=0, x_root=0, y_root=0))
        assert len(tree.selection()) == 2
        menus[-1].invoke(0)
        dialog = next(widget for widget in app.winfo_children() if isinstance(widget, tb.Toplevel))
        checkbox = next(widget for widget in widgets(dialog)
                        if isinstance(widget, ttk.Checkbutton) and widget.cget("text") == "Kệ")
        checkbox.invoke()
        row = checkbox.grid_info()["row"]
        entry = next(widget for widget in widgets(dialog) if isinstance(widget, ttk.Entry)
                     and not isinstance(widget, ttk.Combobox) and widget.grid_info().get("row") == row)
        entry.insert(0, "K1")
        button(dialog, "Lưu").invoke()
        assert {copy.rack for copy in service.query_inventory(item_id=item.id).items} == {"K1"}
        assert not errors and not app.callback_errors
    finally:
        page.destroy()
