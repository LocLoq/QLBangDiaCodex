import os
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from normastore.application._operations import _StoreOperations
from normastore.application.contracts import CheckoutLine, PaymentInput, UpdateInventoryCopyRequest
from normastore.bootstrap import bootstrap
from normastore.config import Settings
from normastore.domain.enums import CopyCondition, CopyStatus, LineAction, PaymentMethod
from normastore.infrastructure.database.models import Employee, OrderLine


def test_sale_return_condition_migration_preserves_history():
    name = f"normastore_migration_{uuid4().hex[:10]}"
    port = os.getenv("NORMASTORE_TEST_MYSQL_PORT", "3306")
    url = f"mysql+pymysql://root:@127.0.0.1:{port}/{name}?charset=utf8mb4"
    admin = create_engine(f"mysql+pymysql://root:@127.0.0.1:{port}/mysql", isolation_level="AUTOCOMMIT")
    factory = None
    try:
        with admin.connect() as connection:
            connection.execute(text(f"CREATE DATABASE `{name}` CHARACTER SET utf8mb4"))
        factory = bootstrap(Settings(database_url=url))
        with factory() as session:
            service = _StoreOperations(session)
            actor = session.query(Employee.id).first()[0]
            customer = service.list_customers()[0]
            item = service.save_catalog_item(actor, item_type="MOVIE", title="Migration sale")
            copy = service.add_copy(item.id, "MIGRATION-SALE", actor_id=actor)
            lines = [CheckoutLine(copy.id, LineAction.BUY)]
            quote = service.quote(customer.id, lines)
            order = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
            session.flush()
            line = session.query(OrderLine).filter_by(order_id=order.id, copy_id=copy.id).one()
            refund = service.return_sale(line.id, actor, condition=CopyCondition.DAMAGED)
            service.update_inventory_copy(copy.id, UpdateInventoryCopyRequest(
                "MIGRATION-CHANGED", "DVD", CopyCondition.DAMAGED, True, True, CopyStatus.INSPECTION,
            ), actor)
            session.commit()
            session.execute(text("UPDATE audit_logs SET created_at = DATE_ADD(created_at, INTERVAL 2 SECOND) WHERE action = 'UPDATE_COPY'"))
            session.commit()
        config = Config("alembic.ini")
        config.set_main_option("sqlalchemy.url", url)
        with factory() as session:
            session.execute(text("ALTER TABLE orders DROP COLUMN deposit_applied"))
            session.execute(text("UPDATE alembic_version SET version_num = '20261122_10'"))
            session.commit()
        command.downgrade(config, "20261121_08")
        # MySQL DDL commits independently: simulate an interrupted upgrade after DDL.
        with factory() as session:
            session.execute(text("ALTER TABLE sale_returns ADD COLUMN condition_at_return VARCHAR(20) NULL"))
            session.execute(text("ALTER TABLE order_lines ADD COLUMN barcode_snapshot VARCHAR(80) NULL"))
            session.execute(text("CREATE INDEX ix_audit_entity_history ON audit_logs (action, entity, entity_id, created_at)"))
            session.commit()
        command.upgrade(config, "head")
        with factory() as session:
            rows = session.execute(text("SELECT condition_at_return, refund_amount FROM sale_returns")).all()
            assert rows == [("DAMAGED", refund)]
            assert session.execute(text("SELECT barcode_snapshot FROM order_lines")).scalar_one() == "MIGRATION-SALE"
            session.execute(text("UPDATE sale_returns SET condition_at_return = 'WORN'"))
            session.execute(text("UPDATE order_lines SET barcode_snapshot = 'ALREADY-RECORDED'"))
            session.execute(text("UPDATE alembic_version SET version_num = '20261121_08'"))
            session.commit()
        command.upgrade(config, "head")
        with factory() as session:
            assert session.execute(text("SELECT condition_at_return FROM sale_returns")).scalar_one() == "WORN"
            assert session.execute(text("SELECT barcode_snapshot FROM order_lines")).scalar_one() == "ALREADY-RECORDED"
    finally:
        if factory is not None:
            factory.kw["bind"].dispose()
        with admin.connect() as connection:
            connection.execute(text(f"DROP DATABASE IF EXISTS `{name}`"))
        admin.dispose()
