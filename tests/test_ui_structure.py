import importlib.util
from pathlib import Path

import ttkbootstrap as tb

from normastore.ui.app import NormaStoreApp
from normastore.ui.pages import (
    AuditPageMixin,
    CatalogPageMixin,
    CheckoutPageMixin,
    CustomersPageMixin,
    DashboardPageMixin,
    InventoryPageMixin,
    NotificationsPageMixin,
    OrdersPageMixin,
    PromotionsPageMixin,
    ReservationsPageMixin,
    ReturnsPageMixin,
    SettingsPageMixin,
    ShiftsPageMixin,
    StatisticsPageMixin,
)


def test_public_app_entrypoint_has_all_page_builders():
    for name in (
        "dashboard_page",
        "catalog_page",
        "checkout_page",
        "orders_page",
        "returns_page",
        "reservations_page",
        "inventory_page",
        "customers_page",
        "promotions_page",
        "shifts_page",
        "notifications_page",
        "statistics_page",
        "audit_page",
        "settings_page",
    ):
        assert callable(getattr(NormaStoreApp, name))


def test_page_mixins_are_statically_importable():
    assert all(
        isinstance(cls.__name__, str)
        for cls in (
            AuditPageMixin,
            CatalogPageMixin,
            CheckoutPageMixin,
            CustomersPageMixin,
            DashboardPageMixin,
            InventoryPageMixin,
            NotificationsPageMixin,
            OrdersPageMixin,
            PromotionsPageMixin,
            ReservationsPageMixin,
            ReturnsPageMixin,
            SettingsPageMixin,
            ShiftsPageMixin,
            StatisticsPageMixin,
        )
    )


def test_ui_has_no_legacy_compatibility_layer_or_direct_page_treeviews():
    ui_root = Path(__file__).resolve().parents[1] / "src" / "normastore" / "ui"

    assert importlib.util.find_spec("normastore.ui.legacy_app") is None
    assert tb.Window in NormaStoreApp.__mro__
    for path in ui_root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "legacy_app" not in source
        assert "LegacyNormaStoreApp" not in source
    for path in (ui_root / "pages").glob("*.py"):
        assert "ttk.Treeview(" not in path.read_text(encoding="utf-8")
