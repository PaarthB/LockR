import logging
import os
from os.path import dirname

import pytest
from click.testing import CliRunner
from src.cli.main import cli_run


class TestCliRunner:
    def test_dry_run(self, caplog):
        runner = CliRunner()
        with caplog.at_level(logging.INFO):
            result = runner.invoke(cli_run, ["run", "--dry-run", "--config-file", dirname(os.path.abspath(__file__)) + "/config_files/lockr.ini"])
            assert "Valid configuration found. Dry run verification successful" in caplog.text
            assert result.exit_code == os.EX_OK

    def test_invalid_config_file_path(self, caplog):
        runner = CliRunner()
        with caplog.at_level(logging.INFO):
            with pytest.raises(FileNotFoundError) as e:
                invalid_path = dirname(os.path.abspath(__file__)) + "/invalid_path/lockr.ini"
                runner.invoke(cli_run, ["run", "--dry-run", "--config-file", invalid_path], catch_exceptions=False)
                assert "Invalid lockr config path specified" in caplog.text
            assert f"File path {invalid_path} not found" in str(e.value)
