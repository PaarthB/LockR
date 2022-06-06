"""
Unit tests for LockRConfig, testing:
    - Correct file parsing / valid configuration
    - Invalid file path
    - Invalid file configuration specified
"""
import logging
import os
import shlex
import socket
import time
from os.path import dirname

import pytest
from fakeredis import FakeStrictRedis
from mock import patch, MagicMock
from redis import StrictRedis, RedisCluster
from redis.cluster import ClusterNode

from lockr.constants import LUA_EXTEND_SCRIPT
from lockr.core import LockRConfig, LockR


class TestLockRConfig:

    def test_invalid_config_file_path(self, caplog):
        """ Tests the use case of passing invalid file path """
        with caplog.at_level(logging.INFO):
            with pytest.raises(FileNotFoundError) as file_not_found:
                invalid_file_path = dirname(dirname(os.path.abspath(__file__))) + '/config_files/invalid-file.ini'
                LockRConfig.from_config_file(
                    config_file_path=invalid_file_path,
                )
        assert file_not_found.value.__str__() == f'File path {invalid_file_path} not found.'
        assert f"Invalid lockr config path specified: {invalid_file_path} - " \
               f"by default lockr.ini should be in the current directory" in caplog.text

    @patch('os.getpid', MagicMock(return_value=1))
    def test_lockr_config_valid_single_host(self, caplog, monkeypatch):
        """ Tests the happy path of passing correct config file (single node) """
        # Setup
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
        )
        assert shlex.split(lockr_config.command)[0] == "echo 'test lockr'"
        assert lockr_config.host == "redis-host"
        assert lockr_config.port == 1111
        assert lockr_config.use_shell is False
        assert lockr_config.name == "test-lockr"
        assert lockr_config.timeout == 1  # 1s
        assert lockr_config.sleep == 1 / 3  # sleep time should always be
        assert lockr_config.redis_cls.__name__ == StrictRedis.__name__
        assert lockr_config.value == f'prefix-testing-{socket.getfqdn()}-1'  # uses prefix from env variable if set
        assert lockr_config.db == 1
        assert lockr_config.password is None
        assert lockr_config.process is None
        assert lockr_config.cluster_nodes is None

    @patch('os.getpid', MagicMock(return_value=1))
    def test_lockr_config_valid_cluster_mode(self, caplog, monkeypatch):
        """ Tests the happy path of passing correct config file (cluster mode) """
        # Setup
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')

        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr-1.ini',
        )
        assert shlex.split(lockr_config.command)[0] == "echo 'test lockr'"
        assert lockr_config.host == ''
        assert lockr_config.port == 1111
        assert lockr_config.use_shell is False
        assert lockr_config.name == "test-lockr"
        assert lockr_config.timeout == 1  # 1s
        assert lockr_config.sleep == 1 / 3  # sleep time should always be
        assert lockr_config.redis_cls.__name__ == RedisCluster.__name__
        assert lockr_config.value == f'test-prefix-{socket.getfqdn()}-1'  # doesn't use environment variable if not set
        assert lockr_config.db == 1
        assert lockr_config.password is None
        assert lockr_config.process is None
        for node in lockr_config.cluster_nodes:
            assert isinstance(node, ClusterNode)
            assert node.host == 'redis-host'
            assert node.port == 1111

    def test_lockr_config_invalid__no_redis_section(self, caplog):
        """ Tests the file validation failure for no redis section specified """
        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as sys_exit:
                LockRConfig.from_config_file(
                    config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr-2.ini',
                )
            assert sys_exit.value.code == os.EX_CONFIG
        assert "Invalid lockr config file. Require both the sections [redis] and [lockr] to be defined" in caplog.text

    def test_lockr_config_invalid__no_command(self, caplog):
        """ Tests the file validation failure for no command specified """
        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as sys_exit:
                LockRConfig.from_config_file(
                    config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr-3.ini',
                )
            assert sys_exit.value.code == os.EX_CONFIG
        assert "[lockr] section does not have 'command' defined" in caplog.text

    def test_lockr_config_invalid__no_lockr_section(self, caplog):
        """ Tests the file validation failure for no lockr section specified """
        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as sys_exit:
                LockRConfig.from_config_file(
                    config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr-4.ini',
                )
            assert sys_exit.value.code == os.EX_CONFIG
        assert "Invalid lockr config file. Require both the sections [redis] and [lockr] to be defined" in caplog.text

    def test_lockr_config_invalid__no_redis_host_or_cluster_nodes(self, caplog):
        """ Tests the file validation failure for no redis host or cluster nodes specified """
        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as sys_exit:
                LockRConfig.from_config_file(
                    config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr-5.ini',
                )
            assert sys_exit.value.code == os.EX_CONFIG
        assert "[redis] section of config file must specify either 'host' or 'cluster_nodes' section. " \
               "Didn't find either." in caplog.text

    def test_lockr_config_invalid__both_redis_host_and_cluster_nodes(self, caplog):
        """ Tests the file validation failure for BOTH redis host or cluster nodes specified """
        with caplog.at_level(logging.INFO):
            with pytest.raises(SystemExit) as sys_exit:
                LockRConfig.from_config_file(
                    config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr-6.ini',
                )
            assert sys_exit.value.code == os.EX_CONFIG
        assert "[redis] section of config file must specify one of 'host' or 'cluster_nodes', not both." in caplog.text


class TestLockR:
    def test_cleanup_terminates_the_process(self, caplog):
        with caplog.at_level(logging.INFO):
            #  ==== Test single redis host ====
            lockr_config = LockRConfig.from_config_file(
                config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
                redis_testing=True
            )
            lockr_config.command = "sleep 999999999"  # long-running command
            lockr_instance = LockR(lockr_config=lockr_config)
            lockr_instance.process = lockr_instance.start(lockr_config.command)
            assert lockr_instance.process.poll() is None  # process is up
            pid = lockr_instance.process.pid
            lockr_instance.cleanup()
        assert lockr_instance.process is None  # process has been terminated
        assert f"Sending TERM to process with PID: {pid}" in caplog.text
        assert "Process has been terminated" in caplog.text

    def test_owner(self):
        #  ==== Test single redis host ====
        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
            redis_testing=True
        )
        lockr_instance = LockR(lockr_config=lockr_config)
        assert lockr_instance.owner() is None  # no owner exists without setting it
        lockr_instance.redis.set(lockr_config.name, "NEW_LOCK_OWNER")  # Take up the lock by a new owner
        assert lockr_instance.owner().decode('utf-8', 'ignore') == "NEW_LOCK_OWNER"  # Compare owner is correct

    def test_not_dry_run(self, monkeypatch, caplog):
        with caplog.at_level(logging.INFO):
            #  ==== Test single redis host ====
            lockr_config = LockRConfig.from_config_file(
                config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
                redis_testing=True
            )
            lockr_instance = LockR(lockr_config=lockr_config)

            # Ensure FakeStrictRedis is being used for testing
            assert isinstance(lockr_instance.redis, FakeStrictRedis) is True
            assert lockr_instance.dry_run is False
            assert lockr_instance.lockname == lockr_config.name
            assert lockr_instance._lock.lua_extend.script == LUA_EXTEND_SCRIPT # assert LUA extend script is overwritten
            assert "LockR will connect to single Redis instance" in caplog.text

            #  ==== Test redis cluster ====
            monkeypatch.setenv('REDIS_HOST', 'redis-host')
            monkeypatch.setenv('REDIS_PORT', '1111')

            lockr_config = LockRConfig.from_config_file(
                config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr-1.ini',
                redis_testing=True
            )
            LockR(lockr_config=lockr_config)
            assert "LockR will connect to a Redis Cluster." in caplog.text

            #  ==== Test UNIX domain type redis server ====
            monkeypatch.setenv('REDIS_HOST', '/var/run/redis/redis-server.sock')
            lockr_config = LockRConfig.from_config_file(
                config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr-7.ini',
                redis_testing=True
            )
            LockR(lockr_config=lockr_config)
            assert "LockR will connect to single Redis instance via Unix domain socket." in caplog.text
