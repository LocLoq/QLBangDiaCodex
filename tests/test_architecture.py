import ast
from pathlib import Path

from sqlalchemy.orm import configure_mappers

from normastore.infrastructure.database.models import Base

ROOT = Path(__file__).resolve().parents[1] / "src" / "normastore"


def test_every_table_has_a_separate_model_module():
    configure_mappers()
    mappings = list(Base.registry.mappers)
    assert len(mappings) == len(Base.metadata.tables) == 36
    assert len({mapper.class_.__module__ for mapper in mappings}) == 36


def test_ui_does_not_manage_database_sessions_or_import_orm():
    for path in (ROOT / "ui").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(
                    not alias.name.startswith(("sqlalchemy", "normastore.infrastructure.database"))
                    for alias in node.names
                ), path
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith(
                    ("sqlalchemy", "normastore.infrastructure.database")
                ), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"commit", "rollback"}, path


def test_application_does_not_construct_sqlalchemy_queries():
    for path in [*(ROOT / "application").rglob("*.py"), ROOT / "jobs.py"]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("sqlalchemy") for alias in node.names), path
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("sqlalchemy"), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id != "select", path
