class OrdersPageMixin:
    def orders_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.orders_page(self, page)
