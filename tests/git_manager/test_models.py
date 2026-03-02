"""Tests for git manager models — PRCreateIn and PROut."""

import pytest
from pydantic import ValidationError

from app.apps.git_manager.model.input import PRCreateIn
from app.apps.git_manager.model.output import PROut


# --- PRCreateIn ---


class TestPRCreateIn:
    def test_basic(self):
        data = {
            "owner": "user",
            "repo": "myproject",
            "title": "Add feature",
            "body": "## Changes\n- Added feature",
            "head": "feature/branch",
            "base": "develop",
        }
        model = PRCreateIn.model_validate(data)
        assert model.owner == "user"
        assert model.repo == "myproject"
        assert model.title == "Add feature"
        assert model.body == "## Changes\n- Added feature"
        assert model.head == "feature/branch"
        assert model.base == "develop"

    def test_defaults(self):
        data = {
            "owner": "user",
            "repo": "myproject",
            "title": "Fix bug",
            "head": "fix/bug",
        }
        model = PRCreateIn.model_validate(data)
        assert model.body == ""
        assert model.base == "main"

    def test_missing_owner_raises(self):
        with pytest.raises(ValidationError):
            PRCreateIn.model_validate({
                "repo": "myproject",
                "title": "Fix",
                "head": "fix/bug",
            })

    def test_missing_repo_raises(self):
        with pytest.raises(ValidationError):
            PRCreateIn.model_validate({
                "owner": "user",
                "title": "Fix",
                "head": "fix/bug",
            })

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            PRCreateIn.model_validate({
                "owner": "user",
                "repo": "myproject",
                "head": "fix/bug",
            })

    def test_missing_head_raises(self):
        with pytest.raises(ValidationError):
            PRCreateIn.model_validate({
                "owner": "user",
                "repo": "myproject",
                "title": "Fix",
            })

    def test_empty_owner_raises(self):
        with pytest.raises(ValidationError):
            PRCreateIn.model_validate({
                "owner": "",
                "repo": "myproject",
                "title": "Fix",
                "head": "fix/bug",
            })

    def test_empty_repo_raises(self):
        with pytest.raises(ValidationError):
            PRCreateIn.model_validate({
                "owner": "user",
                "repo": "",
                "title": "Fix",
                "head": "fix/bug",
            })

    def test_empty_title_raises(self):
        with pytest.raises(ValidationError):
            PRCreateIn.model_validate({
                "owner": "user",
                "repo": "myproject",
                "title": "",
                "head": "fix/bug",
            })

    def test_empty_head_raises(self):
        with pytest.raises(ValidationError):
            PRCreateIn.model_validate({
                "owner": "user",
                "repo": "myproject",
                "title": "Fix",
                "head": "",
            })

    def test_title_max_length(self):
        with pytest.raises(ValidationError):
            PRCreateIn.model_validate({
                "owner": "user",
                "repo": "myproject",
                "title": "x" * 256,
                "head": "fix/bug",
            })

    def test_title_at_max_length(self):
        model = PRCreateIn.model_validate({
            "owner": "user",
            "repo": "myproject",
            "title": "x" * 255,
            "head": "fix/bug",
        })
        assert len(model.title) == 255


# --- PROut ---


class TestPROut:
    def test_basic(self):
        data = {
            "number": 42,
            "html_url": "https://github.com/user/repo/pull/42",
            "title": "Add feature",
            "state": "open",
        }
        model = PROut.model_validate(data)
        assert model.number == 42
        assert model.html_url == "https://github.com/user/repo/pull/42"
        assert model.title == "Add feature"
        assert model.state == "open"

    def test_state_defaults_open(self):
        data = {
            "number": 1,
            "html_url": "https://github.com/user/repo/pull/1",
            "title": "Fix",
        }
        model = PROut.model_validate(data)
        assert model.state == "open"

    def test_extra_fields_ignored(self):
        data = {
            "number": 1,
            "html_url": "https://github.com/user/repo/pull/1",
            "title": "Fix",
            "state": "open",
            "user": {"login": "user"},
            "created_at": "2025-01-01T00:00:00Z",
            "merged": False,
            "additions": 10,
            "deletions": 3,
        }
        model = PROut.model_validate(data)
        assert model.number == 1
        assert not hasattr(model, "user")
        assert not hasattr(model, "created_at")
        assert not hasattr(model, "merged")

    def test_missing_number_raises(self):
        with pytest.raises(ValidationError):
            PROut.model_validate({
                "html_url": "https://github.com/user/repo/pull/1",
                "title": "Fix",
            })

    def test_missing_html_url_raises(self):
        with pytest.raises(ValidationError):
            PROut.model_validate({
                "number": 1,
                "title": "Fix",
            })

    def test_missing_title_raises(self):
        with pytest.raises(ValidationError):
            PROut.model_validate({
                "number": 1,
                "html_url": "https://github.com/user/repo/pull/1",
            })
