class DashboardPageMixin:
    def dashboard_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.dashboard_page(self, page)
