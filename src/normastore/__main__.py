from normastore.config import Settings


def main() -> None:
    from normastore.bootstrap import bootstrap
    from normastore.ui.app import NormaStoreApp

    settings = Settings()
    factory = bootstrap(settings)
    app = NormaStoreApp(factory, settings)
    app.mainloop()


if __name__ == "__main__":
    main()
