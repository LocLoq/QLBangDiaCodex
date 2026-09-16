class ShiftsPageMixin:
    def shifts_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.shifts_page(self, page)
