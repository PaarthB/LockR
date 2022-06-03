import logging
import os
import shlex
import socket
import time
from os.path import dirname
from threading import Thread

import pytest
from fakeredis import FakeStrictRedis
from mock import patch, MagicMock
from mockito import spy2, verify, when
from mockito.mocking import mock
from redis import StrictRedis, RedisCluster
from redis.cluster import ClusterNode
from redis.exceptions import LockNotOwnedError
from redis.lock import Lock

from lockr.core import LockRConfig, LockR


class TestLockR:
    @patch('os.getpid', MagicMock(return_value=1))
    def test_lockr_run(self, caplog, monkeypatch):
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')

        lockr_config = LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr.ini',
                                                    redis_testing=True)
        lockr_config.command = "sleep 99999999999"  # Create a long-running command, which keeps LockR thread alive
        lockr_instance = LockR(lockr_config=lockr_config)

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True

        spy2(lockr_instance.start)

        with caplog.at_level(logging.INFO):
            assert lockr_instance.owner() is None  # No lock exists in redis yet

            lockr_thread = Thread(target=lockr_instance.run, daemon=True)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            time.sleep(1)  # Sleep few seconds to give chance for thread to run
            assert "Waiting on lock, currently held by None" in caplog.text
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            verify(lockr_instance, times=1).start("sleep 99999999999")  # Assert command was called

        assert lockr_instance.owner().decode('utf-8', 'ignore') == lockr_config.value  # Ensure a lock value is created

    @patch('os.getpid', MagicMock(return_value=1))
    def test_lockr_run_process_exits_unexpectedly(self, caplog, monkeypatch):
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr.ini',
                                                    redis_testing=True)
        lockr_config.command = "echo 'test lockr'"  # short-lived command
        lockr_instance = LockR(lockr_config=lockr_config)

        spy2(lockr_instance.start)

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True
        with caplog.at_level(logging.INFO):
            assert lockr_instance.owner() is None  # No lock exists in redis yet
            lockr_thread = Thread(target=lockr_instance.run, daemon=True)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            lockr_thread.join()
            assert "Waiting on lock, currently held by None" in caplog.text
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            verify(lockr_instance, times=1).start("echo 'test lockr'")  # Assert command was called
            assert "Process terminated with exit code 0" in caplog.text  # assert process exited
        assert lockr_instance.owner() is None  # The prior lock was released

    def test_lock_extend_fails_and_fails_reacquire_due_to_preowned_lock(self, monkeypatch, caplog):
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr.ini',
                                                    redis_testing=True)
        lockr_config.command = "sleep infinity"  # long-running command, to allow lock extension
        lockr_instance = LockR(lockr_config=lockr_config)
        mock_lock = mock(Lock)
        spy2(lockr_instance.start)
        spy2(lockr_instance.cleanup)
        when(mock_lock).acquire(...).thenReturn(True)
        when(mock_lock).extend(...).thenRaise(LockNotOwnedError)
        when(mock_lock).release(...)
        lockr_instance._lock = mock_lock
        lockr_instance.redis.set(lockr_config.name, lockr_config.value)  # Ensure lock is taken

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True
        with caplog.at_level(logging.INFO):
            lockr_thread = Thread(target=lockr_instance.run, daemon=True)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            time.sleep(1)
            assert f"Waiting on lock, currently held by {lockr_instance.redis.get(lockr_config.name)}" in caplog.text
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            assert "Lock refresh failed, trying to re-acquire" in caplog.text
            assert f"Unable to refresh lock, its owned by {lockr_instance.redis.get(lockr_config.name)} now" in caplog.text
            verify(lockr_instance, times=1).start("sleep infinity")  # Assert command was called
            verify(lockr_instance, times=1).cleanup(...)  # Assert cleanup was called after lock re-acquisition failure

    def test_lock_extend_fails_and_fails_reacquire(self, monkeypatch, caplog):
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr.ini',
                                                    redis_testing=True)
        lockr_config.command = "sleep infinity"  # long-running command, to allow lock extension
        lockr_instance = LockR(lockr_config=lockr_config)
        mock_lock = mock(Lock)
        spy2(lockr_instance.start)
        spy2(lockr_instance.cleanup)
        when(mock_lock).acquire(token=lockr_config.value, blocking=True).thenReturn(True)
        when(mock_lock).acquire(token=lockr_config.value, blocking=False).thenReturn(False)
        when(mock_lock).extend(...).thenRaise(LockNotOwnedError)
        when(mock_lock).release(...)
        lockr_instance._lock = mock_lock

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True
        with caplog.at_level(logging.INFO):
            assert lockr_instance.owner() is None  # No lock exists in redis yet
            lockr_thread = Thread(target=lockr_instance.run, daemon=True)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            time.sleep(1)
            assert f"Waiting on lock, currently held by None" in caplog.text
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            assert "Lock refresh failed, trying to re-acquire" in caplog.text
            assert f"Lock refresh and subsequent re-acquire failed, giving up (Lock now held by None)" in caplog.text
            verify(lockr_instance, times=1).start("sleep infinity")  # Assert command was called
            verify(lockr_instance, times=1).cleanup(...)  # Assert cleanup was called after lock re-acquisition failure

    def test_lock_extend_fails_but_reacquires(self, monkeypatch, caplog):
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr.ini',
                                                    redis_testing=True)
        lockr_config.command = "sleep infinity"  # long-running command, to allow lock extension
        lockr_instance = LockR(lockr_config=lockr_config)
        mock_lock = mock(Lock)
        spy2(lockr_instance.start)
        when(mock_lock).acquire(...).thenReturn(True)
        when(mock_lock).extend(...).thenRaise(LockNotOwnedError)
        when(mock_lock).release(...)
        lockr_instance._lock = mock_lock

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True
        with caplog.at_level(logging.INFO):
            assert lockr_instance.owner() is None  # No lock exists in redis yet
            lockr_thread = Thread(target=lockr_instance.run, daemon=True)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            time.sleep(1)
            assert "Waiting on lock, currently held by None" in caplog.text
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            verify(lockr_instance, times=1).start("sleep infinity")  # Assert command was called
            assert "Lock refresh failed, trying to re-acquire" in caplog.text
            assert "Lock refresh failed, but successfully re-acquired unclaimed lock" in caplog.text


class TestLockRConfig:

    @patch('os.getpid', MagicMock(return_value=1))
    def test_lockr_config_valid_single_host(self, caplog, monkeypatch):
        # Setup
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(dirname(os.path.abspath(__file__)) + '/config_files/lockr.ini')
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


