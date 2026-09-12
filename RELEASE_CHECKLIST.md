# NormaStore release checklist

## Before migration or import

- [x] Replace every TMDB/Gemini key that was previously exposed.
- [ ] Keep `.env.local` local and confirm it is not included in the release folder.
- [ ] Create a database backup:

  ```powershell
  $py = 'C:\laragon\bin\python\python-3.13\python.exe'
  & $py scripts/backup_database.py
  ```

- [ ] Confirm Laragon/MySQL is running and `normastore_db` uses `utf8mb4`.
- [ ] Apply and check migrations:

  ```powershell
  & $py -c "from normastore.bootstrap import migrate_database; from normastore.config import Settings; migrate_database(Settings())"
  & $py -m alembic current
  ```

## Verification

- [ ] Run `& $py -m pytest -q`.
- [ ] Run `& $py -m compileall -q src tests scripts alembic`.
- [ ] Start the app, sign in, open a shift, complete one rent/return and one sale/return.
- [ ] Confirm Statistics can export CSV and PNG, including stockout ETA.
- [ ] Confirm a due reminder is sent only when SMTP is configured; SMS remains `MOCK_SENT`.

## Build and distribution

- [ ] Build the portable Windows application:

  ```powershell
  & .\scripts\build_windows.ps1 -Python $py
  ```

- [ ] Verify `dist\NormaStore\NormaStore.exe`, `_internal\alembic.ini`, and `_internal\alembic_migrations\versions` are present.
- [x] Compile `installer\normastore.iss` with Inno Setup 6.7.3 to create `dist\installer\NormaStore-Setup.exe`.
- [ ] Test the installer on a clean Windows machine that has compatible MySQL/Laragon and its own local `.env.local`.

## TMDB and AI data

- [ ] Import catalog only after a fresh TMDB key is configured:

  ```powershell
  & $py scripts/import_tmdb.py --movies 2000 --shows 100
  & $py scripts/seed_demo.py --orders 25000
  ```

- [ ] Optionally build Gemini cache after import. It only sends catalog title and synopsis:

  ```powershell
  & $py scripts/build_embeddings.py
  ```
