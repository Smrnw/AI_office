"""Регрессии по итогам аудита безопасности."""
import pytest

from pixel_office import gitrepo, workspace
from pixel_office.checks.browser import _private_target

from conftest import HEADERS


@pytest.mark.parametrize("name", ["p/.git/hooks/pre-commit", "p/.GIT/config", "p/.git./hooks/x", ".git"])
def test_git_folder_is_closed(office, name):
    workspace.write_text("p/index.html", "x")
    gitrepo.commit_now("p", "init", "Coder_1")
    with pytest.raises(workspace.WorkspaceError):
        workspace.safe_path(name)
    r = office.post("/api/file", json={"filename": name, "content": "echo pwned"}, headers=HEADERS)
    assert r.status_code == 400


def test_git_hooks_never_run(office, tmp_path):
    workspace.write_text("h/index.html", "1")
    gitrepo.commit_now("h", "init", "Coder_1")
    marker = tmp_path / "hook-ran"
    hook = workspace.safe_path("h").joinpath(".git", "hooks", "pre-commit")
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text(f"#!/bin/sh\necho x > '{marker.as_posix()}'\n")
    hook.chmod(0o755)
    workspace.write_text("h/index.html", "2")
    assert gitrepo.commit_now("h", "second", "Coder_1")
    assert not marker.exists()


def test_check_browser_cannot_reach_local_network():
    own = "127.0.0.1:5555"
    assert not _private_target("http://127.0.0.1:5555/index.html", own)          # сам сервер проверки
    assert not _private_target("https://fonts.googleapis.com/css", own)
    assert not _private_target("data:image/png;base64,AAA", own)
    for url in ("http://127.0.0.1:8080/api/state", "http://192.168.1.1/", "http://10.0.0.5:9000/",
                "http://localhost:8080/", "http://router.lan/", "http://[::1]:8080/", "http://169.254.169.254/latest"):
        assert _private_target(url, own), url


def test_no_cleartext_smtp_login():
    from pixel_office import notify
    with pytest.raises(RuntimeError, match="открытым текстом"):
        notify._send_email_sync({"security": "none", "username": "me", "host": "127.0.0.1", "port": 1,
                                 "password": "x", "sender": "", "to": "a@b"}, "s", "t")
