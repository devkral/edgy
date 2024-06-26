import pytest

import edgy
from edgy.testclient import DatabaseTestClient as Database
from tests.settings import DATABASE_URL

database = Database(url=DATABASE_URL)
models = edgy.Registry(database=database)

pytestmark = pytest.mark.anyio


class User(edgy.Model):
    id = edgy.IntegerField(primary_key=True)
    name = edgy.CharField(max_length=100)
    language = edgy.CharField(max_length=200, null=True)

    class Meta:
        registry = models


class Product(edgy.Model):
    id = edgy.IntegerField(primary_key=True)
    name = edgy.CharField(max_length=100)
    rating = edgy.IntegerField(minimum=1, maximum=5)
    in_stock = edgy.BooleanField(default=False)

    class Meta:
        registry = models
        name = "products"


@pytest.fixture(autouse=True, scope="function")
async def create_test_database():
    await models.create_all()
    yield
    await models.drop_all()


@pytest.fixture(autouse=True)
async def rollback_connections():
    with database.force_rollback():
        async with database:
            yield


async def test_model_lookup():
    Test = edgy.run_sync(User.query.create(name="Test", language="English"))
    tshirt = edgy.run_sync(Product.query.create(name="T-Shirt", rating=5))

    assert edgy.run_sync(User.query.lookup(term="").first()) == Test
    assert edgy.run_sync(User.query.lookup(term="Test").first()) == Test
    assert edgy.run_sync(Product.query.lookup(term="shirt").first()) == tshirt
