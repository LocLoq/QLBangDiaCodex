from decimal import Decimal
import os
import subprocess
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from normastore.application._operations import _StoreOperations
from normastore.config import Settings
from normastore.infrastructure.database import setup


def test_migration_command_uses_application_database_configuration(monkeypatch):
    from normastore import migrate

    configured_url = "mysql+pymysql://root:@127.0.0.1:3306/normastore_example"
    monkeypatch.setenv("NORMASTORE_DATABASE_URL", configured_url)
    called = []
    monkeypatch.setattr(migrate, "migrate_database", lambda settings: called.append(settings.database_url))
    migrate.main()
    assert called == [configured_url]


def test_migration_preserves_url_escaping_when_passing_alembic_config(monkeypatch):
    configured_url = "mysql+pymysql://user:p%40ss@127.0.0.1:3306/normastore_example"
    monkeypatch.setattr(setup, "ensure_database", lambda _settings: None)
    monkeypatch.setattr(setup, "_backup_legacy_schema", lambda _settings: None)
    called = []
    monkeypatch.setattr(setup.command, "upgrade", lambda config, _revision: called.append(config.get_main_option("sqlalchemy.url")))
    setup.migrate_database(Settings(database_url=configured_url))
    assert called == [configured_url]


@pytest.mark.parametrize("direct_alembic", [False, True])
def test_upgrade_legacy_database_keeps_transaction_history_and_backup(tmp_path, monkeypatch, direct_alembic):
    name = f"normastore_legacy_{uuid4().hex[:10]}"
    port = os.getenv("NORMASTORE_TEST_MYSQL_PORT", "3306")
    url = f"mysql+pymysql://root:@127.0.0.1:{port}/{name}?charset=utf8mb4"
    admin = create_engine(f"mysql+pymysql://root:@127.0.0.1:{port}/mysql", isolation_level="AUTOCOMMIT")
    engine = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        command.upgrade(config, "20260907_04")
        engine = create_engine(url)
        statements = (
            "INSERT INTO customers (id,full_name,phone,reputation_score,email_opt_in,sms_opt_in,created_at,updated_at) VALUES (1,'Legacy customer','0999000000',90,1,1,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            "INSERT INTO employees (id,full_name,active,created_at,updated_at) VALUES (1,'Legacy employee',1,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            "INSERT INTO shifts (id,employee_id,opened_at,opening_cash,created_at,updated_at) VALUES (1,1,UTC_TIMESTAMP(),1000,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            "INSERT INTO reputation_events (id,customer_id,delta,reason,created_at,updated_at) VALUES (1,1,-1,'Legacy event',UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            "INSERT INTO catalog_items (id,item_type,title,rental_price,sale_price,deposit_amount,replacement_value,can_rent,can_sell,archived,created_at,updated_at) VALUES (1,'MOVIE','Legacy film',20000,100000,75000,120000,1,1,0,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            "INSERT INTO physical_copies (id,item_id,barcode,media_format,`condition`,status,can_rent,can_sell,sale_price_override,deposit_override,created_at,updated_at) VALUES (1,1,'LEGACY-001','DVD','GOOD','SOLD',1,1,100000,75000,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            "INSERT INTO orders (id,code,customer_id,employee_id,shift_id,status,gross_total,discount_total,deposit_total,created_at,updated_at) VALUES (1,'LEGACY-RENT',1,1,1,'CONFIRMED',20000,0,75000,UTC_TIMESTAMP(),UTC_TIMESTAMP()),(2,'LEGACY-SALE',1,1,1,'CONFIRMED',100000,75000,0,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
            "INSERT INTO order_lines (id,order_id,copy_id,action,title_snapshot,unit_price,discount_amount,deposit_amount,source_rental_line_id) VALUES (1,1,1,'RENT','Legacy film',20000,0,75000,NULL),(2,2,1,'BUY','Legacy film',100000,75000,0,1)",
            "INSERT INTO rental_terms (id,line_id,due_date,state,late_daily_rate,issued_condition) VALUES (1,1,CURDATE(),'PURCHASED',5000,'GOOD')",
            "INSERT INTO payment_transactions (id,order_id,customer_id,employee_id,method,category,amount,created_at,updated_at) VALUES (1,1,1,1,'CASH','CHECKOUT',95000,UTC_TIMESTAMP(),UTC_TIMESTAMP()),(2,2,1,1,'CASH','RENTAL_TO_SALE',25000,UTC_TIMESTAMP(),UTC_TIMESTAMP())",
        )
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
            orders_before = connection.execute(text("SELECT id,code,customer_id,employee_id,gross_total,discount_total,deposit_total FROM orders ORDER BY id")).all()
            payments_before = connection.execute(text("SELECT id,order_id,category,amount FROM payment_transactions ORDER BY id")).all()
            lines_before = connection.execute(text("SELECT id,order_id,copy_id,unit_price,discount_amount,deposit_amount,source_rental_line_id FROM order_lines ORDER BY id")).all()
        monkeypatch.setattr(setup, "user_data_dir", lambda _name: str(tmp_path))
        if direct_alembic:
            with monkeypatch.context() as failure:
                def fail_backup(*_args, **_kwargs):
                    raise subprocess.CalledProcessError(1, "mysqldump")
                failure.setattr(setup.subprocess, "run", fail_backup)
                with pytest.raises(subprocess.CalledProcessError):
                    command.upgrade(config, "head")
            with engine.connect() as connection:
                assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "20260907_04"
            assert not list((tmp_path / "backups").glob("*.partial"))
            command.upgrade(config, "head")
        else:
            setup.migrate_database(Settings(database_url=url))
        backups = list((tmp_path / "backups").glob("*.sql"))
        assert len(backups) == 1
        backup = backups[0].read_bytes()
        assert b"CREATE TABLE `shifts`" in backup and b"LEGACY-SALE" in backup
        with engine.connect() as connection:
            assert connection.execute(text("SELECT id,code,customer_id,employee_id,gross_total,discount_total,deposit_total FROM orders ORDER BY id")).all() == orders_before
            assert connection.execute(text("SELECT id,order_id,category,amount FROM payment_transactions ORDER BY id")).all() == payments_before
            assert connection.execute(text("SELECT id,order_id,copy_id,unit_price,discount_amount,deposit_amount,source_rental_line_id FROM order_lines ORDER BY id")).all() == lines_before
            assert connection.execute(text("SELECT barcode_snapshot FROM order_lines ORDER BY id")).scalars().all() == ["LEGACY-001", "LEGACY-001"]
            assert connection.execute(text("SELECT sale_price_override FROM physical_copies WHERE id=1")).scalar_one() == Decimal("100000")
        with Session(engine) as session:
            service = _StoreOperations(session)
            receipt = service.order_receipt(2)
            assert receipt.applied_deposit == Decimal("75000")
            assert receipt.discount_total == 0 and receipt.total_due == receipt.checkout_paid == Decimal("25000")
            assert service.operational_report().sale_revenue == Decimal("100000")
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
        admin.dispose()
