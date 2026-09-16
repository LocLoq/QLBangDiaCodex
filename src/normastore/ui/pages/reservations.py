class ReservationsPageMixin:
    def reservations_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.reservations_page(self, page)
