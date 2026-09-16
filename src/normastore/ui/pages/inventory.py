class InventoryPageMixin:
    def inventory_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.inventory_page(self, page)
