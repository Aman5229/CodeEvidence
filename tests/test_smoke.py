from app.main import app_name


def test_app_name():
    assert app_name() == "CodeEvidence"
