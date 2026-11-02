"""Statically imported page mixins for PyInstaller collection."""

from normastore.ui.pages.audit import AuditPageMixin
from normastore.ui.pages.catalog import CatalogPageMixin
from normastore.ui.pages.checkout import CheckoutPageMixin
from normastore.ui.pages.customers import CustomersPageMixin
from normastore.ui.pages.dashboard import DashboardPageMixin
from normastore.ui.pages.inventory import InventoryPageMixin
from normastore.ui.pages.notifications import NotificationsPageMixin
from normastore.ui.pages.orders import OrdersPageMixin
from normastore.ui.pages.promotions import PromotionsPageMixin
from normastore.ui.pages.reservations import ReservationsPageMixin
from normastore.ui.pages.returns import ReturnsPageMixin
from normastore.ui.pages.settings import SettingsPageMixin
from normastore.ui.pages.shifts import ShiftsPageMixin
from normastore.ui.pages.statistics import StatisticsPageMixin

__all__ = [
    "AuditPageMixin",
    "CatalogPageMixin",
    "CheckoutPageMixin",
    "CustomersPageMixin",
    "DashboardPageMixin",
    "InventoryPageMixin",
    "NotificationsPageMixin",
    "OrdersPageMixin",
    "PromotionsPageMixin",
    "ReservationsPageMixin",
    "ReturnsPageMixin",
    "SettingsPageMixin",
    "ShiftsPageMixin",
    "StatisticsPageMixin",
]
