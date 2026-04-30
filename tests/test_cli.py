from __future__ import annotations

import pytest
from click.testing import CliRunner

from model_eval.cli import main


@pytest.mark.unit
class TestCLI:
    def test_group_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--models" in result.output
        assert "sync-aa" in result.output

    def test_no_models_error(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, [])
        assert result.exit_code != 0

    def test_sync_aa_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["sync-aa", "--help"])
        assert result.exit_code == 0
        assert "--api-key" in result.output

    def test_sync_aa_no_key_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("AA_API_KEY", raising=False)
        runner = CliRunner()
        result = runner.invoke(main, ["sync-aa"])
        assert result.exit_code != 0

    def test_fuzzy_flag_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "--fuzzy" in result.output

    def test_check_command_in_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "check" in result.output

    def test_check_command_help(self) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["check", "--help"])
        assert result.exit_code == 0
        assert "--models" in result.output
