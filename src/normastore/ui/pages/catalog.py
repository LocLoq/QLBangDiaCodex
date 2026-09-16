class CatalogPageMixin:
    def catalog_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.catalog_page(self, page)
