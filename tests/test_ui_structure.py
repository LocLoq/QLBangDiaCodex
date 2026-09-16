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
        "dashboard_page", "catalog_page", "checkout_page", "orders_page", "returns_page",
        "reservations_page", "inventory_page", "customers_page", "promotions_page",
        "shifts_page", "notifications_page", "statistics_page", "audit_page", "settings_page",
    ):
        assert callable(getattr(NormaStoreApp, name))


def test_page_mixins_are_statically_importable():
    assert all(isinstance(cls.__name__, str) for cls in (
        AuditPageMixin, CatalogPageMixin, CheckoutPageMixin, CustomersPageMixin,
        DashboardPageMixin, InventoryPageMixin, NotificationsPageMixin, OrdersPageMixin,
        PromotionsPageMixin, ReservationsPageMixin, ReturnsPageMixin, SettingsPageMixin,
        ShiftsPageMixin, StatisticsPageMixin,
    ))
