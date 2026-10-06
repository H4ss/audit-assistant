# Configuration de test locale uniquement : base jetable démarrée par la CI.
TEST_DB_USER = "shop_test"
TEST_DB_PASSWORD = "shop_test_pw"


def test_config_loaded():
    assert TEST_DB_USER
