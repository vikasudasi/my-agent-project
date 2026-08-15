"""
FastAPI Dashboard for AI Task Management System.

Human-readable web UI that reads from the same SQLite database
as the MCP server. Shows projects, task trees, progress, and docs.
"""

import os
import secrets
import sys
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt
from fastapi import FastAPI, Request, Form, HTTPException, Response, Query, Header
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from db import (
    get_connection,
    init_db,
    list_projects_with_progress,
    get_project,
    get_project_progress,
    get_task,
    get_task_tree,
    get_task_subtree,
    update_task,
    update_project,
    get_project_doc,
    upsert_project_doc,
    get_task_doc,
    upsert_task_doc,
    get_project_doc_meta,
    get_task_doc_meta,
    build_project_docs_hub,
    create_project,
    create_task,
    add_comment,
    list_comments,
    list_agents,
    list_user_agents,
    get_agent,
    reissue_agent_key,
    log_audit,
    get_audit_log_by_agent_paginated,
    get_project_audit_log_paginated,
    get_recent_activity,
    get_task_creator,
    archive_project,
)
from dashboard.markdown_util import render_markdown

app = FastAPI(title="AI Task Manager Dashboard")

dashboard_dir = os.path.dirname(os.path.abspath(__file__))
template_dir = os.path.join(dashboard_dir, "templates")
static_dir = os.path.join(dashboard_dir, "static")
templates = Jinja2Templates(directory=template_dir)
templates.env.filters["markdown"] = render_markdown

app.mount("/static", StaticFiles(directory=static_dir), name="static")

# ---------------------------------------------------------------------------
# Session auth (in-memory), backed by real users in the database
# ---------------------------------------------------------------------------

_sessions: dict[str, dict] = {}

_AUDIT_PAGE_SIZE = 50


def _authenticate_user(email: str, password: str) -> Optional[dict]:
    """Look up a user by email and verify their bcrypt password.

    Returns a public user dict (id, username, email, role, created_at) on
    success, or None on failure.
    """
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not row:
        return None
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8"))
    except (ValueError, TypeError):
        return None
    if not ok:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "role": row["role"],
        "created_at": row["created_at"],
    }


def _verify_user_password(user: dict, password: str) -> bool:
    """Verify ``password`` against the stored bcrypt hash for ``user``."""
    with get_connection() as conn:
        row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user["id"],)).fetchone()
    if not row:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8"))
    except (ValueError, TypeError):
        return False


def _set_user_password(user_id: str, password: str) -> None:
    """Replace a user's password with a fresh bcrypt hash."""
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    with get_connection() as conn:
        conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))


def _create_session(user: dict) -> str:
    token = secrets.token_hex(32)
    _sessions[token] = user
    return token


def _get_session_user(request: Request) -> Optional[dict]:
    token = request.cookies.get("session")
    if token and token in _sessions:
        return _sessions[token]
    return None


def _require_user(request: Request) -> dict:
    user = _get_session_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def _status_color(status: str) -> str:
    colors = {
        "pending": "#6b7280",
        "in_progress": "#3b82f6",
        "completed": "#22c55e",
        "blocked": "#ef4444",
        "failed": "#f97316",
        "cancelled": "#9ca3af",
        "active": "#3b82f6",
        "archived": "#6b7280",
        "completed_project": "#22c55e",
    }
    return colors.get(status, "#6b7280")


def _dashboard_actor(user: dict) -> tuple[str, str, str]:
    """Return (agent_name, master_name, user_id) for audit attribution."""
    return user["username"], user["username"], user["id"]


def _format_audit_detail(entry: dict) -> str:
    if entry.get("field") and entry.get("old_value") is not None:
        return f"{entry['field']}: {entry['old_value']} → {entry['new_value']}"
    if entry.get("field"):
        return entry["field"]
    return ""


def _read_flash(request: Request) -> tuple[str, str]:
    message = request.cookies.get("tm_flash", "")
    flash_type = request.cookies.get("tm_flash_type", "success")
    return message, flash_type


def _flash_redirect(url: str, message: str, flash_type: str = "success") -> RedirectResponse:
    redirect = RedirectResponse(url, status_code=303)
    redirect.set_cookie("tm_flash", message, max_age=30, httponly=False, samesite="lax")
    redirect.set_cookie("tm_flash_type", flash_type, max_age=30, httponly=False, samesite="lax")
    return redirect


def _template_context(request: Request, **kwargs) -> dict:
    flash_message, flash_type = _read_flash(request)
    ctx = {
        "status_color": _status_color,
        "format_audit_detail": _format_audit_detail,
        "flash_message": flash_message,
        "flash_type": flash_type,
        "current_user": _get_session_user(request),
    }
    ctx.update(kwargs)
    return ctx


def _clear_flash_response(response: Response) -> None:
    response.delete_cookie("tm_flash")
    response.delete_cookie("tm_flash_type")


def _pagination_page(page: int) -> int:
    return max(1, page)


def _pagination_offset(page: int, limit: int) -> int:
    return (page - 1) * limit


# ---------------------------------------------------------------------------
# Auth middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    exact_paths = {"/", "/login", "/logout"}
    prefix_paths = {"/static/"}
    path = request.url.path
    if path in exact_paths or any(path.startswith(p) for p in prefix_paths):
        return await call_next(request)

    user = _get_session_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return await call_next(request)


@app.middleware("http")
async def flash_middleware(request: Request, call_next):
    response = await call_next(request)
    if request.cookies.get("tm_flash"):
        _clear_flash_response(response)
    return response


# ---------------------------------------------------------------------------
# Login / Logout
# ---------------------------------------------------------------------------

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if _get_session_user(request):
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"error": error, "current_user": None},
    )


@app.post("/login")
async def login(request: Request,
                email: str = Form(...), password: str = Form(...)):
    user = _authenticate_user(email.strip(), password)
    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid email or password", "current_user": None},
        )
    token = _create_session(user)
    redirect = RedirectResponse(url="/dashboard", status_code=303)
    redirect.set_cookie(key="session", value=token, httponly=True, max_age=86400 * 7)
    return redirect


@app.get("/logout")
async def logout(request: Request):
    token = request.cookies.get("session")
    if token:
        _sessions.pop(token, None)
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("session")
    return response


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    """Public landing page — always rendered, no auth required."""
    user = _get_session_user(request)
    return templates.TemplateResponse(
        request,
        "landing.html",
        {"user": user},
    )


@app.get("/dashboard", response_class=HTMLResponse)
async def home(
    request: Request,
    q: str = Query(""),
    show: str = Query("active"),
):
    user = _require_user(request)
    status_filter = show if show in ("active", "archived", "all") else "active"
    status = None if status_filter == "all" else status_filter
    projects = list_projects_with_progress(
        status=status, q=q.strip() or None, user_id=user["id"]
    )

    return templates.TemplateResponse(
        request,
        "index.html",
        _template_context(
            request,
            projects=projects,
            agents=list_user_agents(user["id"]),
            recent_activity=get_recent_activity(limit=25),
            search_q=q,
            show_filter=status_filter,
        ),
    )


@app.post("/projects/create")
async def project_create(request: Request, name: str = Form(...), description: str = Form("")):
    user = _require_user(request)
    result = create_project(name, description, user_id=user["id"])
    agent, master, uid = _dashboard_actor(user)
    log_audit(agent, master, "project", result["id"], "created", user_id=uid)
    return _flash_redirect("/dashboard", f"Project \"{name}\" created.")


@app.post("/projects/{project_id}/archive")
async def project_archive(request: Request, project_id: str):
    user = _require_user(request)
    old = get_project(project_id, user_id=user["id"])
    archive_project(project_id, user_id=user["id"])
    if old:
        agent, master, uid = _dashboard_actor(user)
        log_audit(agent, master, "project", project_id, "updated", "status", old["status"], "archived", user_id=uid)
    return _flash_redirect("/dashboard", "Project archived.")


@app.post("/projects/{project_id}/restore")
async def project_restore(request: Request, project_id: str):
    user = _require_user(request)
    old = get_project(project_id, user_id=user["id"])
    update_project(project_id, status="active", user_id=user["id"])
    if old:
        agent, master, uid = _dashboard_actor(user)
        log_audit(agent, master, "project", project_id, "updated", "status", old["status"], "active", user_id=uid)
    return _flash_redirect(f"/projects/{project_id}", "Project restored.")


@app.get("/projects/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    user = _require_user(request)
    project = get_project_progress(project_id, user_id=user["id"])
    if not project:
        raise HTTPException(404, "Project not found")

    task_tree = get_task_subtree(project_id, user_id=user["id"])
    doc_spec = get_project_doc(project_id, doc_type="spec", user_id=user["id"])
    doc_progress = get_project_doc(project_id, doc_type="progress", user_id=user["id"])
    doc_closure = get_project_doc(project_id, doc_type="closure", user_id=user["id"])
    comments = list_comments("project", project_id, user_id=user["id"])

    return templates.TemplateResponse(
        request,
        "project.html",
        _template_context(
            request,
            project=project,
            task_tree=task_tree,
            doc_spec=doc_spec,
            doc_progress=doc_progress,
            doc_closure=doc_closure,
            comments=comments,
            statuses=["pending", "in_progress", "completed", "blocked", "failed", "cancelled"],
        ),
    )


@app.post("/projects/{project_id}/tasks/create")
async def task_create_route(
    request: Request,
    project_id: str,
    title: str = Form(...),
    description: str = Form(""),
    parent_id: str = Form(""),
):
    user = _require_user(request)
    result = create_task(
        project_id,
        title,
        description,
        parent_id=parent_id if parent_id else None,
        user_id=user["id"],
    )
    if result:
        agent, master, uid = _dashboard_actor(user)
        log_audit(agent, master, "task", result["id"], "created", user_id=uid)
    if parent_id:
        return _flash_redirect(f"/tasks/{parent_id}", f"Subtask \"{title}\" created.")
    return _flash_redirect(f"/projects/{project_id}", f"Task \"{title}\" created.")


@app.post("/tasks/{task_id}/update")
async def task_update_route(
    request: Request,
    task_id: str,
    status: str = Form(...),
    hx_request: Optional[str] = Header(None, alias="HX-Request"),
):
    user = _require_user(request)
    old = get_task(task_id, user_id=user["id"])
    result = update_task(task_id, status=status, user_id=user["id"])
    if old and result and old["status"] != status:
        agent, master, uid = _dashboard_actor(user)
        log_audit(agent, master, "task", task_id, "updated", "status", old["status"], status, user_id=uid)

    task = result or get_task(task_id, user_id=user["id"])
    if not task:
        return _flash_redirect("/dashboard", "Task not found.", "error")

    if hx_request:
        response = HTMLResponse("")
        response.headers["HX-Trigger"] = (
            '{"showToast": {"message": "Status updated to ' + status.replace("_", " ") + '", "type": "success"}}'
        )
        return response

    referer = request.headers.get("referer", "")
    if f"/tasks/{task_id}" in referer:
        return _flash_redirect(f"/tasks/{task_id}", f"Status updated to {status.replace('_', ' ')}.")
    return _flash_redirect(f"/projects/{task['project_id']}", f"Status updated to {status.replace('_', ' ')}.")


@app.get("/tasks/{task_id}", response_class=HTMLResponse)
async def task_detail(request: Request, task_id: str):
    user = _require_user(request)
    task = get_task(task_id, user_id=user["id"])
    if not task:
        raise HTTPException(404, "Task not found")

    project = get_project_progress(task["project_id"], user_id=user["id"])
    full_tree = get_task_subtree(task["project_id"], user_id=user["id"])
    task_tree = get_task_tree(task_id, user_id=user["id"])
    subtasks = task_tree["children"] if task_tree else []
    doc_spec = get_task_doc(task_id, doc_type="spec", user_id=user["id"])
    doc_progress = get_task_doc(task_id, doc_type="progress", user_id=user["id"])
    doc_closure = get_task_doc(task_id, doc_type="closure", user_id=user["id"])
    comments = list_comments("task", task_id, user_id=user["id"])

    breadcrumb = []
    current = task
    while current and current.get("parent_id"):
        parent = get_task(current["parent_id"], user_id=user["id"])
        if parent:
            breadcrumb.insert(0, parent)
            current = parent
        else:
            break

    return templates.TemplateResponse(
        request,
        "task_detail.html",
        _template_context(
            request,
            task=task,
            project=project,
            full_tree=full_tree,
            subtasks=subtasks,
            doc_spec=doc_spec,
            doc_progress=doc_progress,
            doc_closure=doc_closure,
            comments=comments,
            breadcrumb=breadcrumb,
            created_by=get_task_creator(task_id),
            statuses=["pending", "in_progress", "completed", "blocked", "failed", "cancelled"],
        ),
    )


@app.post("/comments/{entity_type}/{entity_id}")
async def comment_add_route(
    request: Request,
    entity_type: str,
    entity_id: str,
    content: str = Form(...),
    author: str = Form(""),
    hx_request: Optional[str] = Header(None, alias="HX-Request"),
):
    user = _require_user(request)
    comment = add_comment(entity_type, entity_id, content, author=author, user_id=user["id"])
    agent, master, uid = _dashboard_actor(user)
    log_audit(agent, master, entity_type, entity_id, "comment_added", user_id=uid)

    if hx_request and comment:
        return templates.TemplateResponse(
            request,
            "includes/comment_item.html",
            {"c": comment},
        )

    if entity_type == "project":
        return _flash_redirect(f"/projects/{entity_id}", "Comment added.")
    return _flash_redirect(f"/tasks/{entity_id}", "Comment added.")


@app.get("/tasks/{task_id}/doc", response_class=HTMLResponse)
async def task_doc_page(
    request: Request,
    task_id: str,
    type: str = Query("spec"),
    mode: str = Query("view"),
):
    user = _require_user(request)
    doc_type = type
    task = get_task(task_id, user_id=user["id"])
    if not task:
        raise HTTPException(404, "Task not found")
    doc_meta = get_task_doc_meta(task_id, doc_type=doc_type, user_id=user["id"])
    doc = doc_meta["content"] if doc_meta else ""
    comments = list_comments("task", task_id, user_id=user["id"])
    return templates.TemplateResponse(
        request,
        "doc.html",
        _template_context(
            request,
            entity_type="task",
            entity_id=task_id,
            title=task["title"],
            project_id=task["project_id"],
            content=doc,
            doc_meta=doc_meta,
            doc_type=doc_type,
            mode=mode if mode == "edit" else "view",
            comments=comments,
        ),
    )


@app.post("/tasks/{task_id}/doc")
async def task_doc_update(
    request: Request,
    task_id: str,
    content: str = Form(...),
    doc_type: str = Form("spec"),
):
    user = _require_user(request)
    task = get_task(task_id, user_id=user["id"])
    if not task:
        raise HTTPException(404, "Task not found")
    upsert_task_doc(task_id, content, doc_type=doc_type, user_id=user["id"])
    agent, master, uid = _dashboard_actor(user)
    log_audit(agent, master, "task", task_id, "updated", f"doc_{doc_type}", user_id=uid)
    return _flash_redirect(
        f"/tasks/{task_id}/doc?type={doc_type}",
        f"{doc_type.capitalize()} document saved.",
    )


@app.get("/projects/{project_id}/doc", response_class=HTMLResponse)
async def project_doc_page(
    request: Request,
    project_id: str,
    type: str = Query("spec"),
    mode: str = Query("view"),
):
    user = _require_user(request)
    doc_type = type
    project = get_project(project_id, user_id=user["id"])
    if not project:
        raise HTTPException(404, "Project not found")
    doc_meta = get_project_doc_meta(project_id, doc_type=doc_type, user_id=user["id"])
    doc = doc_meta["content"] if doc_meta else ""
    comments = list_comments("project", project_id, user_id=user["id"])
    return templates.TemplateResponse(
        request,
        "doc.html",
        _template_context(
            request,
            entity_type="project",
            entity_id=project_id,
            title=project["name"],
            project_id=project_id,
            content=doc,
            doc_meta=doc_meta,
            doc_type=doc_type,
            mode=mode if mode == "edit" else "view",
            comments=comments,
        ),
    )


@app.post("/projects/{project_id}/doc")
async def project_doc_update(
    request: Request,
    project_id: str,
    content: str = Form(...),
    doc_type: str = Form("spec"),
):
    user = _require_user(request)
    project = get_project(project_id, user_id=user["id"])
    if not project:
        raise HTTPException(404, "Project not found")
    upsert_project_doc(project_id, content, doc_type=doc_type, user_id=user["id"])
    agent, master, uid = _dashboard_actor(user)
    log_audit(agent, master, "project", project_id, "updated", f"doc_{doc_type}", user_id=uid)
    return _flash_redirect(
        f"/projects/{project_id}/doc?type={doc_type}",
        f"{doc_type.capitalize()} document saved.",
    )


@app.get("/projects/{project_id}/docs", response_class=HTMLResponse)
async def project_docs_hub(
    request: Request,
    project_id: str,
    type: str = Query("spec"),
):
    user = _require_user(request)
    doc_type = type if type in ("spec", "progress", "closure") else "spec"
    project = get_project(project_id, user_id=user["id"])
    if not project:
        raise HTTPException(404, "Project not found")
    hub = build_project_docs_hub(project_id, doc_type=doc_type, user_id=user["id"])
    return templates.TemplateResponse(
        request,
        "project_docs_hub.html",
        _template_context(
            request,
            project=project,
            hub=hub,
            doc_type=doc_type,
        ),
    )


@app.get("/projects/{project_id}/audit", response_class=HTMLResponse)
async def project_audit_page(
    request: Request,
    project_id: str,
    page: int = Query(1),
):
    user = _require_user(request)
    project = get_project(project_id, user_id=user["id"])
    if not project:
        raise HTTPException(404, "Project not found")
    page = _pagination_page(page)
    audit_data = get_project_audit_log_paginated(
        project_id,
        limit=_AUDIT_PAGE_SIZE,
        offset=_pagination_offset(page, _AUDIT_PAGE_SIZE),
    )
    return templates.TemplateResponse(
        request,
        "project_audit.html",
        _template_context(
            request,
            project=project,
            audit=audit_data["entries"],
            pagination=audit_data,
        ),
    )


@app.get("/admin/agents", response_class=HTMLResponse)
async def admin_agents(request: Request):
    _require_user(request)
    return templates.TemplateResponse(
        request,
        "admin_agents.html",
        _template_context(request, agents=list_agents()),
    )


@app.get("/admin/agents/{agent_id}", response_class=HTMLResponse)
async def admin_agent_detail(
    request: Request,
    agent_id: str,
    page: int = Query(1),
):
    _require_user(request)
    agent = get_agent(agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    page = _pagination_page(page)
    audit_data = get_audit_log_by_agent_paginated(
        agent["name"],
        limit=_AUDIT_PAGE_SIZE,
        offset=_pagination_offset(page, _AUDIT_PAGE_SIZE),
    )
    return templates.TemplateResponse(
        request,
        "admin_agent_detail.html",
        _template_context(
            request,
            agent=agent,
            audit=audit_data["entries"],
            pagination=audit_data,
            new_key=None,
            back_url="/dashboard",
            back_label="Dashboard",
        ),
    )


@app.post("/admin/agents/{agent_id}/reissue")
async def admin_agent_reissue(request: Request, agent_id: str):
    user = _require_user(request)
    result = reissue_agent_key(agent_id, user_id=user["id"])
    if not result:
        raise HTTPException(404, "Agent not found")
    agent, master, uid = _dashboard_actor(user)
    log_audit(agent, master, "agent", agent_id, "key_reissued", user_id=uid)
    audit_data = get_audit_log_by_agent_paginated(result["name"], limit=_AUDIT_PAGE_SIZE, offset=0)
    return templates.TemplateResponse(
        request,
        "admin_agent_detail.html",
        _template_context(
            request,
            agent=result,
            new_key=result["api_key"],
            audit=audit_data["entries"],
            pagination=audit_data,
            back_url="/dashboard",
            back_label="Dashboard",
        ),
    )


@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, message: str = "", error: str = ""):
    _require_user(request)
    return templates.TemplateResponse(
        request,
        "admin_settings.html",
        _template_context(request, message=message, error=error),
    )


@app.post("/admin/settings/password")
async def admin_change_password(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    user = _require_user(request)
    if not _verify_user_password(user, current_password):
        return templates.TemplateResponse(
            request,
            "admin_settings.html",
            _template_context(request, error="Current password is incorrect"),
        )
    if new_password != confirm_password:
        return templates.TemplateResponse(
            request,
            "admin_settings.html",
            _template_context(request, error="New passwords do not match"),
        )
    if len(new_password) < 4:
        return templates.TemplateResponse(
            request,
            "admin_settings.html",
            _template_context(request, error="New password must be at least 4 characters"),
        )
    _set_user_password(user["id"], new_password)
    return templates.TemplateResponse(
        request,
        "admin_settings.html",
        _template_context(request, message="Password changed successfully"),
    )


if __name__ == "__main__":
    init_db()
    uvicorn.run(app, host="0.0.0.0", port=8000)
