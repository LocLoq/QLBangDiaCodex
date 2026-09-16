class ReturnsPageMixin:
    def returns_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.returns_page(self, page)
