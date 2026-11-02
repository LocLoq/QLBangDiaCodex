from normastore.config import Settings


def main() -> None:
    from normastore.bootstrap import bootstrap, build_application
    from normastore.ui.app import NormaStoreApp

    settings = Settings()
    factory = bootstrap(settings)
    service, poster_cache = build_application(factory, settings)
    app = NormaStoreApp(service, settings, poster_cache)
    app.mainloop()


if __name__ == "__main__":
    main()
