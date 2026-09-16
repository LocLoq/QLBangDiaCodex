class SettingsPageMixin:
    def settings_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.settings_page(self, page)
