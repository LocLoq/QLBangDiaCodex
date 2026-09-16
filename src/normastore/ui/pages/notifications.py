class NotificationsPageMixin:
    def notifications_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.notifications_page(self, page)
