from datetime import datetime, timezone

from app.db.models import Repository


def make_repository(number: int) -> Repository:
  now = datetime.now(timezone.utc)
  return Repository(
    github_repo_id=1000 + number,
    owner="octo",
    full_name=f"octo/repo{number}",
    default_branch="main",
    html_url=f"https://github.com/octo/repo{number}",
    is_private=False,
    created_at=now,
    updated_at=now,
    ingested_at=now,
    last_synced_at=now,
  )


def test_list_is_empty_when_no_repositories(client):
  response = client.get("/repositories")

  assert response.status_code == 200
  assert response.json() == {"items": [], "next_cursor": None}


def test_list_returns_repositories_in_id_order(client, db_session):
  db_session.add_all([make_repository(1), make_repository(2), make_repository(3)])
  db_session.commit()

  response = client.get("/repositories")

  names = [item["full_name"] for item in response.json()["items"]]
  assert names == ["octo/repo1", "octo/repo2", "octo/repo3"]


def test_list_respects_limit(client, db_session):
  db_session.add_all([make_repository(1), make_repository(2), make_repository(3)])
  db_session.commit()

  response = client.get("/repositories?limit=2")

  assert len(response.json()["items"]) == 2


def test_list_rejects_bad_limit(client):
  assert client.get("/repositories?limit=0").status_code == 422
  assert client.get("/repositories?limit=101").status_code == 422


def test_get_one_repository(client, db_session):
  repository = make_repository(1)
  db_session.add(repository)
  db_session.commit()

  response = client.get(f"/repositories/{repository.id}")

  body = response.json()
  assert response.status_code == 200
  assert body["full_name"] == "octo/repo1"
  assert "github_repo_id" not in body


def test_get_missing_repository_is_404(client):
  response = client.get("/repositories/999")

  assert response.status_code == 404

def test_list_pages_through_everything_without_repeats(client, db_session):
  db_session.add_all([make_repository(n) for n in range(1, 6)])
  db_session.commit()

  seen = []
  cursor = None
  for _ in range(10):
    url = "/repositories?limit=2"
    if cursor:
      url += f"&cursor={cursor}"
    body = client.get(url).json()
    seen += [item["full_name"] for item in body["items"]]
    cursor = body["next_cursor"]
    if cursor is None:
      break

  assert seen == [f"octo/repo{n}" for n in range(1, 6)]


def test_next_cursor_is_none_when_everything_fits(client, db_session):
  db_session.add_all([make_repository(1), make_repository(2)])
  db_session.commit()

  body = client.get("/repositories?limit=2").json()

  assert len(body["items"]) == 2
  assert body["next_cursor"] is None


def test_list_rejects_invalid_cursor(client):
  assert client.get("/repositories?cursor=not-a-cursor").status_code == 400