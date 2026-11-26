from tkinter import ttk, messagebox
from types import SimpleNamespace

import ttkbootstrap as tb
import pytest

from normastore.application._operations import _StoreOperations
from normastore.ui.pages.checkout import CheckoutPageMixin
from normastore.ui.pages.inventory import InventoryPageMixin
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

    def _run_async(self, work, done):
        done(work())

    def _create_treeview(self, parent, **kwargs):
        tree = super()._create_treeview(parent, **kwargs)
        tree.test_bindings = {}
        original = tree.bind

        def bind(sequence, func, **options):
            tree.test_bindings[sequence] = func
            return original(sequence, func, **options)

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
        button(page, "Bỏ dòng").invoke()
        page.refresh()
        assert cart.get_children() == (str(manual.copy_id),)
        choose_customer(customers[0])
        choose_customer(customers[1])
        assert set(cart.get_children()) == {str(copies[1].copy_id), str(manual.copy_id)}
        assert not errors and not app.callback_errors
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
