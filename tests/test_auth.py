import pytest

from auth import AuthError, AuthManager, hash_password, verify_password
from persistent_storage import PersistentStorage


class Logger:
    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(message)

    warning = error = info


@pytest.fixture
def storage(tmp_path):
    s = PersistentStorage(str(tmp_path / "auth.db"))
    yield s
    s.close()


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


def test_password_hashes():
    stored = hash_password("correct horse")
    assert stored.startswith("scrypt$") and "correct horse" not in stored
    assert verify_password("correct horse", stored) and not verify_password("Correct horse", stored)
    assert hash_password("correct horse") != stored  # random salt
    assert not verify_password("x", "md5$abc") and not verify_password("x", "garbage")


def test_setup_with_the_code_of_the_log(storage, capsys):
    logger = Logger()
    auth = AuthManager(storage, logger, enabled=True)
    assert auth.setup_code and auth.setup_code in capsys.readouterr().out and any(auth.setup_code in m for m in logger.messages)
    with pytest.raises(AuthError, match="invalid_setup_code"):
        auth.setup("WRONG-CODE", "admin", "correct horse")
    with pytest.raises(AuthError, match="password_too_short"):
        auth.setup(auth.setup_code, "admin", "short")
    auth.setup(auth.setup_code.lower(), "admin", "correct horse")
    assert auth.list_users() == ["admin"] and auth.setup_code is None
    with pytest.raises(AuthError, match="already_set_up"):
        auth.setup("ANY-CODE", "other", "correct horse")
    # no setup code once there is an account
    assert AuthManager(storage, Logger(), enabled=True).setup_code is None


def test_sessions(storage):
    clock = Clock()
    auth = AuthManager(storage, Logger(), enabled=True, clock=clock)
    auth.create_user("admin", "correct horse")
    token = auth.make_token("admin")
    assert auth.verify_token(token) == "admin"
    assert auth.verify_token(token[:-2] + "xx") is None                       # tampered signature
    assert auth.verify_token("eyJ1IjoiYWRtaW4ifQ." + token.split(".")[1]) is None  # tampered payload
    clock.now += AuthManager.SESSION_SECONDS + 1
    assert auth.verify_token(token) is None                                   # expired
    remembered = auth.make_token("admin", remember=True)
    clock.now += 20 * 86400
    assert auth.verify_token(remembered) == "admin"
    auth.set_password("admin", "battery staple")
    assert auth.verify_token(remembered) is None                              # password changed
    auth.delete_user("admin")
    assert auth.verify_token(auth.make_token("admin") if auth.list_users() else "") is None


def test_login_throttling(storage):
    clock = Clock()
    auth = AuthManager(storage, Logger(), enabled=True, clock=clock)
    auth.create_user("admin", "correct horse")
    assert auth.login("admin", "correct horse", "10.0.0.2") == "admin"
    for _ in range(AuthManager.MAX_FAILURES):
        with pytest.raises(AuthError, match="invalid_credentials"):
            auth.login("admin", "wrong", "10.0.0.2")
    with pytest.raises(AuthError, match="locked"):
        auth.login("admin", "correct horse", "10.0.0.2")       # locked even with the right password
    assert auth.login("admin", "correct horse", "10.0.0.3") == "admin"  # other client
    clock.now += AuthManager.LOCKOUT_SECONDS + 1
    assert auth.login("admin", "correct horse", "10.0.0.2") == "admin"
    with pytest.raises(AuthError, match="invalid_credentials"):
        auth.login("nobody", "correct horse", "10.0.0.4")


def test_user_names_and_passwords(storage):
    auth = AuthManager(storage, Logger(), enabled=False)
    for name, password in [("bad name", "correct horse"), ("x" * 33, "correct horse"), ("admin", "1234567")]:
        with pytest.raises(AuthError):
            auth.create_user(name, password)
    auth.create_user("admin", "correct horse")
    with pytest.raises(AuthError, match="user_exists"):
        auth.create_user("admin", "correct horse")


def test_default_passwords_and_policy(storage):
    auth = AuthManager(storage, Logger(), enabled=True)
    with pytest.raises(AuthError, match="password_too_weak"):
        auth.create_user("admin", "admin12345")                  # contains the user name
    with pytest.raises(AuthError, match="password_too_weak"):
        auth.create_user("admin", "Password2024")
    # a default password (e.g. of the demo account) does not need to be strong, but must be changed
    auth.create_user("admin", "aq-demo-2024", must_change=True, check_strength=False)
    assert auth.must_change_password("admin")
    session = auth.verify_session(auth.make_token("admin"))
    assert session == {"user": "admin", "must_change_password": True}
    with pytest.raises(AuthError, match="invalid_credentials"):
        auth.change_password("admin", "wrong", "Velvet-Otter-93-Lamp", "10.0.0.2")
    with pytest.raises(AuthError, match="password_unchanged"):
        auth.change_password("admin", "aq-demo-2024", "aq-demo-2024", "10.0.0.2")
    auth.change_password("admin", "aq-demo-2024", "Velvet-Otter-93-Lamp", "10.0.0.2")
    assert not auth.must_change_password("admin")
    # temporary password set by the administrator
    auth.set_password("admin", "Another-Temp-Pass-1", must_change=True)
    assert auth.must_change_password("admin")


def test_users_table_of_a_former_version_is_migrated(tmp_path):
    import sqlite3
    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE "users" ("username" TEXT PRIMARY KEY, "password_hash" TEXT NOT NULL, "created" INTEGER NOT NULL)')
    conn.execute('INSERT INTO "users" VALUES (?, ?, 0)', ("admin", hash_password("correct horse")))
    conn.commit()
    conn.close()
    storage = PersistentStorage(path)
    try:
        auth = AuthManager(storage, Logger(), enabled=True)
        assert auth.login("admin", "correct horse", "x") == "admin" and not auth.must_change_password("admin")
    finally:
        storage.close()
