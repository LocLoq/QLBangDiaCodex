import os
from datetime import date, timedelta
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from normastore.application._operations import _StoreOperations
from normastore.application.contracts import CheckoutLine
from normastore.bootstrap import bootstrap
from normastore.config import Settings
from normastore.domain.enums import LineAction


def test_preorder_migration_preserves_history_and_resumes_partial_ddl():
    name = f"normastore_preorder_migration_{uuid4().hex[:10]}"
    port = os.getenv("NORMASTORE_TEST_MYSQL_PORT", "3306")
    url = f"mysql+pymysql://root:@127.0.0.1:{port}/{name}?charset=utf8mb4"
    admin = create_engine(f"mysql+pymysql://root:@127.0.0.1:{port}/mysql", isolation_level="AUTOCOMMIT")
    factory = None
    try:
        factory = bootstrap(Settings(database_url=url))
        with factory() as session:
            service = _StoreOperations(session)
            actor = service.authenticate("admin", "admin123").employee_id
            customer = service.list_customers()[0]
            item = service.save_catalog_item(actor, item_type="MOVIE", title="Đặt trước dữ liệu cũ")
            service.reserve(customer.id, [item.id], actor)
            copy, = service.add_copies(item.id, 1, actor_id=actor)
            order = service.checkout(customer.id, actor,
                                     [CheckoutLine(copy.copy_id, LineAction.RENT, date.today() + timedelta(days=3))], [])
            session.commit()
            order_id = order.id
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        command.downgrade(config, "20261122_13")
        with factory() as session:
            before = session.execute(text("SELECT id, state, allocated_copy_id FROM reservations ORDER BY id")).all()
            # Simulate MySQL committing the new columns before a failed FK creation.
            session.execute(text("ALTER TABLE order_lines ADD COLUMN note VARCHAR(255) NULL"))
            session.execute(text("ALTER TABLE reservations ADD COLUMN fulfilled_line_id INTEGER NULL"))
            session.commit()
        command.upgrade(config, "head")
        command.upgrade(config, "head")
        with factory() as session:
            assert session.execute(text("SELECT id, state, allocated_copy_id FROM reservations ORDER BY id")).all() == before
            assert any(key["constrained_columns"] == ["fulfilled_line_id"]
                       for key in inspect(session.connection()).get_foreign_keys("reservations"))
            service = _StoreOperations(session)
            assert service.order_receipt(order_id).lines[0].note is None
            assert service.list_reservations()[0].fulfilled_action is None
    finally:
        if factory is not None:
            factory.kw["bind"].dispose()
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
        admin.dispose()
