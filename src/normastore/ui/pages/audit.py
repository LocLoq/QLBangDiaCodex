class AuditPageMixin:
    def audit_page(self, page) -> None:
        from normastore.ui.legacy_app import LegacyNormaStoreApp
        return LegacyNormaStoreApp.audit_page(self, page)
