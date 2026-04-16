from typer.testing import CliRunner
from lokiwiki.cli import app
import tempfile
from pathlib import Path

runner = CliRunner()

def test_init_command():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        vault_arg = str(Path(tmp) / "fresh-test-vault")   # always a brand-new path

        result = runner.invoke(app, ["init", vault_arg])

        assert result.exit_code == 0
        assert "Vault created" in result.stdout
        assert "Git repository" in result.stdout          # optional but nice

def test_init_git_command(temp_vault):
    result = runner.invoke(app, ["init-git", "--vault", str(temp_vault)])
    assert result.exit_code == 0
    assert "Git repository initialized" in result.stdout or "already initialized" in result.stdout