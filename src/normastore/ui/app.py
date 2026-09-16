"""NormaStore application composition root.

The legacy implementation is kept as a compatibility base during the page-by-page
extraction.  Public callers continue to import ``NormaStoreApp`` from this module.
"""
from __future__ import annotations

from normastore.ui.legacy_app import LegacyNormaStoreApp
from normastore.ui.media import PosterMixin
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
from normastore.ui.shell import ShellMixin
from normastore.ui.theme import AppearanceMixin
from normastore.ui.widgets import CommonWidgetsMixin


class NormaStoreApp(
    AppearanceMixin,
    ShellMixin,
    CommonWidgetsMixin,
    PosterMixin,
    DashboardPageMixin,
    CatalogPageMixin,
    CheckoutPageMixin,
    OrdersPageMixin,
    ReturnsPageMixin,
    ReservationsPageMixin,
    InventoryPageMixin,
    CustomersPageMixin,
    PromotionsPageMixin,
    ShiftsPageMixin,
    NotificationsPageMixin,
    StatisticsPageMixin,
    AuditPageMixin,
    SettingsPageMixin,
    LegacyNormaStoreApp,
):
    """Desktop application public entry point."""
