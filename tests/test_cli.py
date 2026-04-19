import pytest
from typer.testing import CliRunner
from lokiwiki.cli import app
import tempfile
from pathlib import Path

runner = CliRunner()


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def vault(tmp_path):
    """Create a real initialized vault and return its path."""
    vault_path = tmp_path / "test-vault"
    result = runner.invoke(app, ["init", str(vault_path)])
    assert result.exit_code == 0
    return vault_path


# ─── init ─────────────────────────────────────────────────────────────────────

def test_init_creates_vault(tmp_path):
    vault_path = tmp_path / "fresh-vault"
    result = runner.invoke(app, ["init", str(vault_path)])
    assert result.exit_code == 0
    assert "✅ Vault created" in result.stdout


def test_init_creates_expected_folders(tmp_path):
    vault_path = tmp_path / "fresh-vault"
    runner.invoke(app, ["init", str(vault_path)])
    assert (vault_path / "raw").is_dir()
    assert (vault_path / "wiki").is_dir()
    assert (vault_path / "config").is_dir()
    assert (vault_path / "toBeProcessed").is_dir()


def test_init_creates_expected_files(tmp_path):
    vault_path = tmp_path / "fresh-vault"
    runner.invoke(app, ["init", str(vault_path)])
    assert (vault_path / "index.md").exists()
    assert (vault_path / "log.md").exists()
    assert (vault_path / "config" / "agents.md").exists()


def test_init_existing_vault(tmp_path):
    vault_path = tmp_path / "existing-vault"
    runner.invoke(app, ["init", str(vault_path)])
    result = runner.invoke(app, ["init", str(vault_path)])
    assert result.exit_code == 0
    assert "already exists" in result.stdout
    assert "Set as default vault" in result.stdout


def test_init_git_outcome(tmp_path):
    vault_path = tmp_path / "git-vault"
    result = runner.invoke(app, ["init", str(vault_path)])
    git_mentioned = any(phrase in result.stdout for phrase in [
        "Git repository", "Git init failed", "Git command not found"
    ])
    assert git_mentioned


# ─── config ───────────────────────────────────────────────────────────────────

def test_config_set_and_read(tmp_path):
    vault_path = tmp_path / "config-vault"
    runner.invoke(app, ["init", str(vault_path)])
    result = runner.invoke(app, ["config"])
    assert result.exit_code == 0
    assert str(vault_path) in result.stdout.replace("\n", "")


def test_config_set_vault_option(tmp_path):
    vault_path = tmp_path / "another-vault"
    vault_path.mkdir(parents=True)
    result = runner.invoke(app, ["config", "--set-vault", str(vault_path)])
    assert result.exit_code == 0
    assert "Default vault set" in result.stdout

# ─── lint ─────────────────────────────────────────────────────────────────────

def test_lint_clean_vault(vault):
    result = runner.invoke(app, ["lint", "--vault", str(vault)])
    assert result.exit_code == 0
    assert "No broken wikilinks" in result.stdout
    assert "No orphan pages" in result.stdout


def test_lint_detects_missing_from_index(vault):
    # Write a wiki page that isn't listed in index.md
    wiki_page = vault / "wiki" / "Concepts" / "Orphan_Topic.md"
    wiki_page.parent.mkdir(parents=True, exist_ok=True)
    wiki_page.write_text("""---
title: "Orphan Topic"
tags: [concept]
created: "2026-01-01"
updated: "2026-01-01"
sources: []
related: []
---

Some content.
""", encoding="utf-8")

    result = runner.invoke(app, ["lint", "--vault", str(vault)], input="n\n")
    assert result.exit_code == 0
    assert "Missing from index" in result.stdout


def test_lint_detects_broken_wikilinks(vault):
    wiki_page = vault / "wiki" / "Concepts" / "Topic.md"
    wiki_page.parent.mkdir(parents=True, exist_ok=True)
    wiki_page.write_text("""---
title: "Topic"
tags: [concept]
created: "2026-01-01"
updated: "2026-01-01"
sources: []
related: []
---

See also [[NonExistentPage]].
""", encoding="utf-8")

    result = runner.invoke(app, ["lint", "--vault", str(vault)], input="n\n")
    assert result.exit_code == 0
    assert "Broken wikilinks" in result.stdout


def test_lint_detects_frontmatter_issues(vault):
    wiki_page = vault / "wiki" / "Concepts" / "BadFrontmatter.md"
    wiki_page.parent.mkdir(parents=True, exist_ok=True)
    wiki_page.write_text("No frontmatter here, just raw text.\n", encoding="utf-8")

    result = runner.invoke(app, ["lint", "--vault", str(vault)], input="n\n")
    assert result.exit_code == 0
    assert "Frontmatter issues" in result.stdout


# ─── backup ───────────────────────────────────────────────────────────────────

def test_backup_without_git(tmp_path):
    vault_path = tmp_path / "no-git-vault"
    vault_path.mkdir()
    result = runner.invoke(app, ["backup", "--vault", str(vault_path)])
    assert result.exit_code == 0
    assert "Git not initialized" in result.stdout


def test_backup_with_git(vault):
    # Only run if git was actually initialized
    if not (vault / ".git").exists():
        pytest.skip("Git not available in this environment")
    result = runner.invoke(app, ["backup", "--vault", str(vault), "--message", "test backup"])
    assert result.exit_code == 0
    assert any(phrase in result.stdout for phrase in ["Backup created", "No changes to backup"])


# ─── no vault fallback ────────────────────────────────────────────────────────

def test_command_fails_gracefully_without_vault(monkeypatch, tmp_path):
    """Commands should exit cleanly when no vault is configured."""
    fake_config = tmp_path / "nonexistent_config.json"
    monkeypatch.setattr("lokiwiki.cli.GLOBAL_CONFIG_FILE", fake_config)
    result = runner.invoke(app, ["lint"])
    assert result.exit_code != 0 or "No vault" in result.stdout