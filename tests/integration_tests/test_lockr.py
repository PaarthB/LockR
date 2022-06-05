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

        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
            redis_testing=True
        )
        lockr_config.command = "sleep 999999999"  # Create a long-running command, which keeps LockR thread alive
        lockr_instance = LockR(lockr_config=lockr_config)

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True

        spy2(lockr_instance.start)  # watch executions of process start (command to be executed)
        spy2(lockr_instance._lock.acquire)  # watch executions of lock acquire method
        spy2(lockr_instance._lock.extend)  # watch executions of lock extend method
        spy2(lockr_instance._lock.release)  # Watch executions of lock release

        with caplog.at_level(logging.INFO):
            assert lockr_instance.owner() is None  # No lock exists in redis yet

            lockr_thread = Thread(target=lockr_instance.run, daemon=True)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            time.sleep(1)  # Sleep few seconds to give chance for thread to run
            assert "Waiting on lock, currently held by None" in caplog.text
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            verify(lockr_instance, times=1).start("sleep 999999999")  # Assert command was called
            # Assert initial acquire is called only once
            verify(lockr_instance._lock, times=1).acquire(token=lockr_config.value, blocking=True)
            # Assert lock extend was called
            verify(lockr_instance._lock, atleast=1).extend(lockr_config.timeout)
            verify(lockr_instance._lock, times=0).release(...)  # Assert lock is not released if process stays up

        assert lockr_instance.owner().decode('utf-8', 'ignore') == lockr_config.value  # Ensure a lock value is created

    @patch('os.getpid', MagicMock(return_value=1))
    def test_lockr_run_process_exits_unexpectedly(self, caplog, monkeypatch):
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
            redis_testing=True
        )
        lockr_config.command = "echo 'test lockr'"  # short-lived command
        lockr_instance = LockR(lockr_config=lockr_config)

        spy2(lockr_instance.start)  # watch executions of process start (command to be executed)
        spy2(lockr_instance._lock.release)  # Watch executions of lock release
        spy2(lockr_instance._lock.acquire)  # watch executions of acquire method
        spy2(lockr_instance._lock.extend)  # watch executions of lock extend method

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True
        with caplog.at_level(logging.INFO):
            assert lockr_instance.owner() is None  # No lock exists in redis yet
            lockr_thread = Thread(target=lockr_instance.run)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            lockr_thread.join()  # wait for thread to complete
            assert "Waiting on lock, currently held by None" in caplog.text
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            verify(lockr_instance, times=1).start("echo 'test lockr'")  # Assert command was called
            verify(lockr_instance._lock, times=1).release(...)  # Assert lock was released after process exit
            # Assert initial acquire is called only once
            verify(lockr_instance._lock, times=1).acquire(token=lockr_config.value, blocking=True)
            # Assert lock extend was never called, as we never reach there in case of process exits
            verify(lockr_instance._lock, atmost=1).extend(...)

            assert "Process terminated with exit code 0" in caplog.text  # assert process exited
        assert lockr_instance.owner() is None  # The prior lock was released

    def test_lock_extend_fails_and_reacquire_fails_due_to_preowned_lock(self, monkeypatch, caplog):
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
            redis_testing=True
        )
        lockr_config.command = "sleep 999999999"  # long-running command, to allow lock extension
        lockr_instance = LockR(lockr_config=lockr_config)
        mock_lock = mock(Lock)

        # Setup mocks on the lock, to simulate a lock being taken over during the execution of LockR by another instance
        # This tries to simulate the case of a GC pause (eg), causing lock to expire and taken by someone else,
        # using mocks (since this can't be controlled ourselves)
        when(mock_lock).acquire(...).thenReturn(True)  # Allow acquiring lock first time
        when(mock_lock).extend(...).thenRaise(LockNotOwnedError)
        lockr_instance._lock = mock_lock

        spy2(lockr_instance.start)  # watch executions of process start (command to be executed)
        spy2(lockr_instance.cleanup)  # watch executions of cleanup method

        # Ensure lock is taken by a different node
        lockr_instance.redis.set(lockr_config.name, lockr_config.value)

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True
        with caplog.at_level(logging.INFO):
            lockr_thread = Thread(target=lockr_instance.run, daemon=True)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            time.sleep(1)  # Sleep few seconds to give chance for thread to run
            assert f"Waiting on lock, currently held by {lockr_instance.redis.get(lockr_config.name)}" in caplog.text
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            assert "Lock refresh failed, trying to re-acquire" in caplog.text
            assert f"Unable to refresh lock, its owned by {lockr_instance.redis.get(lockr_config.name)} now" in caplog.text
            verify(lockr_instance, times=1).start("sleep 999999999")  # Assert command was called
            verify(lockr_instance, times=1).cleanup(...)  # Assert cleanup was called after lock re-acquisition failure
            # Assert initial acquire is called only once
            verify(lockr_instance._lock, times=1).acquire(token=lockr_config.value, blocking=True)
            # Assert lock extend is called only once
            verify(lockr_instance._lock, times=1).extend(lockr_config.timeout)
            # Assert lock is not released if process stays up
            verify(lockr_instance._lock, times=0).release(...)

    def test_lock_extend_fails_and_reacquire_fails(self, monkeypatch, caplog):
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
            redis_testing=True
        )
        lockr_config.command = "sleep 999999999"  # long-running command, to allow lock extension
        lockr_instance = LockR(lockr_config=lockr_config)
        mock_lock = mock(Lock)

        # mocking the behaviour for handling the special case when extension and reacquiring have to fail without
        # a pre-owned lock (due to sudden loss of redis connectivity).
        # (Tries to simulate network error, or a connection error, which is why we need to mock this behaviour)
        when(mock_lock).acquire(token=lockr_config.value, blocking=True).thenReturn(True)
        when(mock_lock).acquire(token=lockr_config.value, blocking=False).thenReturn(False)
        when(mock_lock).extend(...).thenRaise(LockNotOwnedError)
        
        lockr_instance._lock = mock_lock

        spy2(lockr_instance.start)  # watch executions of process start (command to be executed)
        spy2(lockr_instance.cleanup)  # watch executions of cleanup method

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True
        with caplog.at_level(logging.INFO):
            assert lockr_instance.owner() is None  # No lock exists in redis yet
            lockr_thread = Thread(target=lockr_instance.run, daemon=True)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            time.sleep(1)  # Sleep few seconds to give chance for thread to run
            assert f"Waiting on lock, currently held by None" in caplog.text
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            assert "Lock refresh failed, trying to re-acquire" in caplog.text
            assert f"Lock refresh and subsequent re-acquire failed, giving up (Lock now held by None)" in caplog.text
            verify(lockr_instance, times=1).start("sleep 999999999")  # Assert command was called
            verify(lockr_instance, times=1).cleanup(...)  # Assert cleanup was called after lock re-acquisition failure
            # Assert initial acquire is called only once
            verify(lockr_instance._lock, times=1).acquire(token=lockr_config.value, blocking=True)
            verify(lockr_instance._lock, times=0).release(...)  # Assert lock is not released if process stays up
            # Assert lock extend was called
            verify(lockr_instance._lock, times=1).extend(lockr_config.timeout)
            # Assert subsequent acquire was called (due to extension failure)
            verify(lockr_instance._lock, times=1).acquire(token=lockr_config.value, blocking=False)

    def test_lock_extend_fails_but_reacquires(self, monkeypatch, caplog):
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
            redis_testing=True
        )
        lockr_config.timeout = 0.1  # Choose a very small TTL, such that lock expires after acquisition & can't extend
        lockr_config.command = "sleep 999999999"  # long-running command, to allow lock extension
        lockr_instance = LockR(lockr_config=lockr_config)

        spy2(lockr_instance.start)  # watch executions of process start (command to be executed)
        spy2(lockr_instance._lock.acquire)  # watch executions of acquire method
        spy2(lockr_instance._lock.release)  # Watch executions of lock release
        spy2(lockr_instance._lock.extend)  # watch executions of lock extend method

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True
        with caplog.at_level(logging.INFO):
            assert lockr_instance.owner() is None  # No lock exists in redis yet
            lockr_thread = Thread(target=lockr_instance.run, daemon=True)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            time.sleep(1)  # Sleep few seconds to give chance for thread to run
            assert "Waiting on lock, currently held by None" in caplog.text
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            verify(lockr_instance, times=1).start("sleep 999999999")  # Assert command was called
            # Assert initial acquire is called only once
            verify(lockr_instance._lock, times=1).acquire(token=lockr_config.value, blocking=True)
            verify(lockr_instance._lock, times=0).release(...)  # Assert lock is not released if process stays up
            # Assert subsequent acquire was called atleast once (can be more due to lock expiring multiple times)
            verify(lockr_instance._lock, atleast=1).acquire(token=lockr_config.value, blocking=False)
            # Assert lock extend is called atleast once (can be more due to multiple iterations that might have passed)
            verify(lockr_instance._lock, atleast=1).extend(lockr_config.timeout)

            assert "Lock refresh failed, trying to re-acquire" in caplog.text
            assert "Lock refresh failed, but successfully re-acquired unclaimed lock" in caplog.text
