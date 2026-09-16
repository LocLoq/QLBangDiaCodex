class StatisticsPageMixin:
    def statistics_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.statistics_page(self, page)
