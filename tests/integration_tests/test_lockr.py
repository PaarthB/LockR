import logging
import os
import time
from os.path import dirname
from threading import Thread

from fakeredis import FakeStrictRedis
from mock import MagicMock, patch
from mockito import verify, when, spy2, mock
from redis.exceptions import LockNotOwnedError
from redis.lock import Lock

from lockr.core import LockR, LockRConfig


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


