import hashlib
import hmac

from app.integrations.github.signature import is_valid_signature

SECRET = "test-secret"
BODY = b'{"zen": "hello"}'


def sign(body: bytes, secret: str = SECRET) -> str:
  """Build the header exactly the way GitHub does."""
  digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
  return "sha256=" + digest


def test_valid_signature_is_accepted():
  assert is_valid_signature(BODY, sign(BODY), SECRET) is True


def test_missing_signature_is_rejected():
  assert is_valid_signature(BODY, None, SECRET) is False


def test_signature_without_sha256_prefix_is_rejected():
  header_without_prefix = sign(BODY).removeprefix("sha256=")
  assert is_valid_signature(BODY, header_without_prefix, SECRET) is False


def test_signature_made_with_wrong_secret_is_rejected():
  assert is_valid_signature(BODY, sign(BODY, secret="wrong-secret"), SECRET) is False


def test_tampered_body_is_rejected():
  header = sign(BODY)
  tampered_body = b'{"zen": "hacked"}'
  assert is_valid_signature(tampered_body, header, SECRET) is False
