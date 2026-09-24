import hashlib
import hmac


def is_valid_signature(raw_body: bytes, signature_header: str | None, secret: str) -> bool:
  """Check GitHub's X-Hub-Signature-256 header against our shared secret.

  Returns True/False only. Deciding the HTTP response (401) is the route's job,
  so this function stays reusable and easy to unit test.
  """
  if not signature_header or not signature_header.startswith("sha256="):
    return False

  expected = hmac.new(
    key=secret.encode("utf-8"),
    msg=raw_body,
    digestmod=hashlib.sha256,
  ).hexdigest()

  provided = signature_header.removeprefix("sha256=")

  return hmac.compare_digest(expected, provided)
