class PromotionsPageMixin:
    def promotions_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.promotions_page(self, page)
