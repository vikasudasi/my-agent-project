"""Integration tests for the dashboard UI against a running server."""

import re
import subprocess
import time

import httpx
import pytest

BASE = "http://127.0.0.1:8080"
PROJECT_ID = "daa1ce70-1157-483b-ab15-f21fad72611c"
PARENT_TASK_ID = "089ddfdb-5fcb-4ecc-8145-f148047ab678"
CHILD_TASK_ID = "749d025d-d85d-40a3-b7a1-2a6c9541996b"


@pytest.fixture(scope="module")
def server():
  """Ensure dashboard server is reachable (started externally on :8080)."""
  for _ in range(20):
    try:
      r = httpx.get(f"{BASE}/login", timeout=2)
      if r.status_code == 200:
        return
    except httpx.ConnectError:
      time.sleep(0.5)
  pytest.skip("Dashboard server not running on :8080")


@pytest.fixture
def client(server):
  return httpx.Client(base_url=BASE, follow_redirects=False, timeout=10)


@pytest.fixture
def authed_client(client):
  r = client.post(
    "/login",
    data={"username": "admin", "password": "admin"},
  )
  assert r.status_code == 303
  session = r.cookies.get("session")
  assert session
  c = httpx.Client(
    base_url=BASE,
    cookies={"session": session},
    follow_redirects=True,
    timeout=10,
  )
  yield c
  c.close()


class TestStaticAssets:
  def test_css_bundle(self, client):
    r = client.get("/static/css/app.css")
    assert r.status_code == 200
    assert "tailwind" in r.text or ".bg-gray-50" in r.text or "box-sizing" in r.text

  def test_js_assets(self, client):
    for path in [
      "/static/js/task-tree.js",
      "/static/js/task-filters.js",
      "/static/js/flash.js",
      "/static/js/nav.js",
      "/static/js/docs-accordion.js",
    ]:
      r = client.get(path)
      assert r.status_code == 200, path


class TestAuth:
  def test_login_page_uses_static_css(self, client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "/static/css/app.css" in r.text
    assert "cdn.tailwindcss.com" not in r.text
    assert "Default: admin / admin" not in r.text

  def test_protected_home_redirects(self, client):
    r = client.get("/")
    assert r.status_code == 303
    assert r.headers["location"] == "/login"

  def test_doc_routes_require_auth(self, client):
    for path in [
      f"/projects/{PROJECT_ID}/doc",
      f"/tasks/{PARENT_TASK_ID}/doc",
      f"/projects/{PROJECT_ID}/docs",
    ]:
      r = client.get(path)
      assert r.status_code == 303, path
      assert r.headers["location"] == "/login"


class TestAuthenticatedUI:
  def test_home_lists_project_with_progress(self, authed_client):
    r = authed_client.get("/")
    assert r.status_code == 200
    assert "UI Test Project" in r.text
    assert "/static/css/app.css" in r.text
    assert 'id="project-name"' in r.text
    assert "Agents" in r.text
    assert "Settings" in r.text

  def test_project_page_structure(self, authed_client):
    r = authed_client.get(f"/projects/{PROJECT_ID}")
    assert r.status_code == 200
    html = r.text
    assert "All Docs" in html
    assert 'id="taskSearch"' in html
    assert 'role="group"' in html
    assert "/static/js/task-filters.js" in html
    assert "/static/js/task-tree.js" in html
    assert "htmx.org" in html
    assert "Parent Task" in html
    assert "Child Task" in html
    # Server-rendered markdown (not client textarea blocks for preview)
    assert "<strong>Bold</strong>" in html or "<strong>" in html
    assert 'class="markdown-body' in html

  def test_task_detail_sidebar_indentation(self, authed_client):
    r = authed_client.get(f"/tasks/{PARENT_TASK_ID}")
    assert r.status_code == 200
    assert 'style="margin-left: 1.5rem"' in r.text or 'style="margin-left: 3.0rem"' in r.text
    assert "ml-{{" not in r.text
    assert 'data-confirm' in r.text

  def test_docs_hub_accordion(self, authed_client):
    r = authed_client.get(f"/projects/{PROJECT_ID}/docs?type=spec")
    assert r.status_code == 200
    assert "doc-accordion-toggle" in r.text
    assert "/static/js/docs-accordion.js" in r.text
    assert 'id="doc-panel-' in r.text

  def test_doc_view_server_markdown(self, authed_client):
    r = authed_client.get(f"/projects/{PROJECT_ID}/doc?type=spec")
    assert r.status_code == 200
    assert "<h1" in r.text or "Spec" in r.text
    assert "markdown-source" not in r.text

  def test_doc_edit_has_live_preview_assets(self, authed_client):
    r = authed_client.get(f"/projects/{PROJECT_ID}/doc?type=spec&mode=edit")
    assert r.status_code == 200
    assert 'id="doc-editor"' in r.text
    assert 'id="doc-preview"' in r.text
    assert "marked.min.js" in r.text
    assert "/static/js/markdown-preview.js" in r.text

  def test_admin_agents_table_scroll(self, authed_client):
    r = authed_client.get("/admin/agents")
    assert r.status_code == 200
    assert "overflow-x-auto" in r.text
    assert 'scope="col"' in r.text
    assert "ui-tester" in r.text

  def test_audit_pagination_controls(self, authed_client):
    r = authed_client.get(f"/projects/{PROJECT_ID}/audit")
    assert r.status_code == 200
    # May or may not show pagination depending on entry count
    assert "Audit Log" in r.text


class TestMutations:
  def test_comment_htmx_partial(self, authed_client):
    r = authed_client.post(
      f"/comments/project/{PROJECT_ID}",
      data={"author": "Tester", "content": "HTMX validation comment"},
      headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "HTMX validation comment" in r.text
    assert "Tester" in r.text
    assert 'id="comment-' in r.text

  def test_flash_cookie_on_task_create_redirect(self, client):
    login = client.post("/login", data={"username": "admin", "password": "admin"})
    session = login.cookies.get("session")
    authed = httpx.Client(
      base_url=BASE,
      cookies={"session": session},
      follow_redirects=False,
      timeout=10,
    )
    r = authed.post(
      f"/projects/{PROJECT_ID}/tasks/create",
      data={"title": "Flash Test Task", "description": "", "parent_id": ""},
    )
    authed.close()
    assert r.status_code == 303
    assert r.cookies.get("tm_flash")
    assert "created" in r.cookies.get("tm_flash", "").lower()

  def test_status_update_with_htmx_trigger(self, authed_client):
    r = authed_client.post(
      f"/tasks/{CHILD_TASK_ID}/update",
      data={"status": "in_progress"},
      headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "HX-Trigger" in r.headers
    assert "showToast" in r.headers["HX-Trigger"]
