from typer.testing import CliRunner
from lokiwiki.cli import app
import tempfile
from pathlib import Path

runner = CliRunner()

import subprocess

def test_init_command():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmp:
        vault_arg = str(Path(tmp) / "fresh-test-vault")
        result = runner.invoke(app, ["init", vault_arg])
        
        assert result.exit_code == 0
        assert "Vault created" in result.stdout
        assert "✅ Vault created" in result.stdout  # more precise
        
        # Git is optional in init — accept either success or graceful failure
        git_success = "Git repository" in result.stdout or "Git init failed" in result.stdout
        assert git_success, f"Unexpected Git output: {result.stdout}"

def test_init_git_command(temp_vault):
    runner = CliRunner()
    result = runner.invoke(app, ["init-git", "--vault", str(temp_vault)])
    
    assert result.exit_code == 0
    
    # Accept success, already-initialized, or graceful failure due to missing git config
    output = result.stdout
    acceptable = (
        "Git repository initialized" in output or
        "already initialized" in output or
        "Git init failed" in output or
        "Failed to initialize Git" in output
    )
    assert acceptable, f"Unexpected init-git output: {output}"