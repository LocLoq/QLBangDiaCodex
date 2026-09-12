import pytest

from normastore.bootstrap import bootstrap
from normastore.config import Settings


@pytest.fixture
def session():
    factory = bootstrap(
        Settings(database_url="mysql+pymysql://root:@127.0.0.1:3306/normastore_test?charset=utf8mb4")
    )
    instance = factory()
    try:
        yield instance
    finally:
        instance.rollback()
        instance.close()
