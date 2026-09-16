class CheckoutPageMixin:
    def checkout_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.checkout_page(self, page)
