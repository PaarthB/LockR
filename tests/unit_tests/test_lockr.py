import logging
import os
import shlex
from os.path import dirname

import pytest
from mock import patch, MagicMock
from redis.client import StrictRedis
from redis.cluster import ClusterNode
from src.lockr.core import LockRConfig


class TestLockR:

    @patch('os.getpid', MagicMock(return_value=1))
    def test_lockr_config_valid_single_host(self, caplog, monkeypatch):
        # Setup
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')

        lockr_config = LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr.ini')
        assert shlex.split(lockr_config.command)[0] == "echo 'test lockr'"
        assert lockr_config.host == "redis-host"
        assert lockr_config.port == 1111
        assert lockr_config.use_shell is False
        assert lockr_config.name == "test-lockr"
        assert lockr_config.timeout == 1  # 1s
        assert lockr_config.sleep == 1 / 3  # sleep time should always be
        assert type(lockr_config.redis_cls) == type(StrictRedis)
        assert lockr_config.value == 'test-prefix-1'
        assert lockr_config.db == 1
        assert lockr_config.password is None
        assert lockr_config.process is None
        assert lockr_config.cluster_nodes is None

    @patch('os.getpid', MagicMock(return_value=1))
    def test_lockr_config_valid_cluster_mode(self, caplog, monkeypatch):
        # Setup
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')

        lockr_config = LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr-1.ini')
        assert shlex.split(lockr_config.command)[0] == "echo 'test lockr'"
        assert lockr_config.host == ''
        assert lockr_config.port == 1111
        assert lockr_config.use_shell is False
        assert lockr_config.name == "test-lockr"
        assert lockr_config.timeout == 1  # 1s
        assert lockr_config.sleep == 1 / 3  # sleep time should always be
        assert type(lockr_config.redis_cls) == type(StrictRedis)
        assert lockr_config.value == 'test-prefix-1'
        assert lockr_config.db == 1
        assert lockr_config.password is None
        assert lockr_config.process is None
        for node in lockr_config.cluster_nodes:
            assert isinstance(node, ClusterNode)
            assert node.host == 'redis-host'
            assert node.port == 1111

    def test_lockr_config_invalid__no_redis_section(self, caplog):
        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as sys_exit:
                LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr-2.ini')
                assert sys_exit.value.code == os.EX_CONFIG
                assert "Invalid lockr config file. Require both the sections [redis] and [lockr] to be defined" in caplog.text

    def test_lockr_config_invalid__no_command(self, caplog):
        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as sys_exit:
                LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr-3.ini')
                assert sys_exit.value.code == os.EX_CONFIG
                assert "[lockr] section does not have 'command' defined" in caplog.text

    def test_lockr_config_invalid__no_lockr_section(self, caplog):
        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as sys_exit:
                LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr-4.ini')
                assert sys_exit.value.code == os.EX_CONFIG
                assert "Invalid lockr config file. Require both the sections [redis] and [lockr] to be defined" in caplog.text

    def test_lockr_config_invalid__no_redis_host_or_startup_nodes(self, caplog):
        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as sys_exit:
                LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr-5.ini')
                assert sys_exit.value.code == os.EX_CONFIG
                assert "[redis] section of config file must specify either 'host' or 'startup_nodes' section. " \
                       "Didn't find either." in caplog.text

    def test_lockr_config_invalid__both_redis_host_and_startup_nodes(self, caplog):
        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as sys_exit:
                LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr-6.ini')
                assert sys_exit.value.code == os.EX_CONFIG
                assert "[redis] section of config file must specify either 'host' or 'startup_nodes' section. " \
                       "Didn't find either." in caplog.text
