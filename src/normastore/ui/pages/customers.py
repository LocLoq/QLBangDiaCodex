class CustomersPageMixin:
    def customers_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.customers_page(self, page)
