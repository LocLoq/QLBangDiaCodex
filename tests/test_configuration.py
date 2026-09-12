from pathlib import Path


def test_env_example_does_not_contain_api_secrets():
    entries = {}
    for line in (Path(__file__).parents[1] / ".env.example").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            entries[key.strip()] = value.strip()

    assert entries["NORMASTORE_TMDB_API_KEY"] == ""
    assert entries["NORMASTORE_GEMINI_API_KEY"] == ""
