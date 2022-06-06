"""`
    Integration tests for LockR testing end to end integration with Redis, and all the expected code paths
`"""
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
        """
        Aims to test the happy path, when lock is acquired as expected and no exceptions are encountered
        """
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
        assert lockr_thread.is_alive() is True  # The original thread should never stop, if no exception encountered
        assert lockr_instance.owner().decode('utf-8', 'ignore') == lockr_config.value  # Ensure a lock value is created

    @patch('os.getpid', MagicMock(return_value=1))
    def test_lockr_run_process_exits_unexpectedly(self, caplog, monkeypatch):
        """
        Aims to test when lock is acquired but when process unexpectedly exits, it is released, as we don't need
        the lock anymore
        """
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
            redis_testing=True
        )
        lockr_config.command = "echo 'test lockr'"  # short-lived command
        lockr_config.timeout = 10  # create a long TTL, to ensure its really reset (lock expires in 10s if not released)
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
        assert lockr_thread.is_alive() is False  # thread exits as expected
        assert lockr_instance.owner() is None  # The prior lock was released

    def test_lock_extend_fails_and_reacquire_fails_due_to_preowned_lock(self, monkeypatch, caplog):
        """
        Aims to test when lock extension can fail, after acquiring once due to redis server reset or large GC pause
        (for example), and is taken by another LockR server/instance previously waiting on lock to become available
        In this case LockR tries to reacquire the lock, but since its taken now, it fails and exits
        """
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
            redis_testing=True
        )
        lockr_config.command = "sleep 999999999"  # long-running command, to allow lock extension
        # Set sleep > timeout/ttl period such that lock can be released/acquired easily by  someone else whilst process
        # is waiting for the next extension
        lockr_config.sleep = 2
        lockr_instance = LockR(lockr_config=lockr_config)

        spy2(lockr_instance.start)  # watch executions of process start (command to be executed)
        spy2(lockr_instance.cleanup)  # watch executions of cleanup method
        spy2(lockr_instance._lock.acquire)  # watch executions of acquire method
        spy2(lockr_instance._lock.release)  # Watch executions of lock release
        spy2(lockr_instance._lock.extend)  # watch executions of lock extend method

        # Ensure FakeStrictRedis is being used for testing
        assert isinstance(lockr_instance.redis, FakeStrictRedis) is True
        with caplog.at_level(logging.INFO):
            lockr_thread = Thread(target=lockr_instance.run, daemon=True)
            lockr_thread.start()  # Start the lockr instance in separate thread to make this a non-blocking operation
            time.sleep(1)  # Sleep few seconds to give chance for thread to run and acquire the lock
            # Ensure lock is taken by a different node
            lockr_instance.redis.set(lockr_config.name, "NEW_LOCK_OWNER")  # Take up the lock by a new owner
            # Sleep a few more seconds, for LockR to finish its sleep period, and fail subsequent lock extension
            time.sleep(2)
            assert f"Waiting on lock, currently held by None" in caplog.text  # Initially lock is available
            assert f"Lock '{lockr_config.name}' acquired" in caplog.text  # Assert lock was acquired
            assert "Started process with PID" in caplog.text  # Assert the process was started
            assert "Lock refresh failed, trying to re-acquire" in caplog.text
            assert f"Unable to refresh lock, its owned by b'NEW_LOCK_OWNER' now" in caplog.text
            verify(lockr_instance, times=1).start("sleep 999999999")  # Assert command was called
            verify(lockr_instance, times=1).cleanup(...)  # Assert cleanup was called after lock re-acquisition failure
            # Assert initial acquire is called only once
            verify(lockr_instance._lock, times=1).acquire(token=lockr_config.value, blocking=True)
            # Assert lock extend is called twice (one in first iteration, and second after sleep of 5s)
            verify(lockr_instance._lock, times=2).extend(lockr_config.timeout)
            # Assert lock is not released if process stays up
            verify(lockr_instance._lock, times=0).release(...)
        assert lockr_thread.is_alive() is False  # thread exits as expected

    def test_lock_extend_fails_and_reacquire_fails(self, monkeypatch, caplog):
        """
        Aims to test when lock extension can fail, after acquiring once (eg: due to redis connectivity problems)
        (for example), and is not acquired by anyone else yet
        In this case LockR tries to reacquire the lock, but due to connectivity failures, it fails and exits
        """
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
        assert lockr_thread.is_alive() is False  # thread exits as expected

    def test_lock_extend_fails_but_reacquires(self, monkeypatch, caplog):
        """
        Aims to test when lock extension can fail, after acquiring once due to redis server reset or large GC pause
        (for example)
        In this case LockR tries to reacquire the lock if its not taken by anyone yet
        """
        monkeypatch.setenv('REDIS_HOST', 'redis-host')
        monkeypatch.setenv('REDIS_PORT', '1111')
        monkeypatch.setenv('TEST_PREFIX', 'prefix-testing')
        lockr_config = LockRConfig.from_config_file(
            config_file_path=dirname(dirname(os.path.abspath(__file__))) + '/config_files/lockr.ini',
            redis_testing=True
        )
        # Choose a very small TTL, such that lock expires after acquisition and fails to extend
        # each iteration for lock extension in LockR is followed by a sleep amount, which is not overridden
        # (defaults to 1/3rd of timeout). The timeout in file is 1000ms, so sleep is 1000/3 = 0.33s. This is more than
        # the lock TTL of 1ms (millisecond) which is overridden by the file specified (which is 1s). This higher sleep
        # but lower TTL, ensures lock expires after acquiring. This tries to emulate case of GC pause or server reset,
        # such that long GC pauses or redis server reset can cause redis lock to expire / be removed.
        # If a large value is chosen like 1s, then this test fails, as the lock extend won't fail due to expiration
        lockr_config.timeout = 0.001  # 1 millisecond (smallest value that can be set for redis key or lock TTL)

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

            owner = None
            # ensure owner is being eventually set as it keeps expiring very quickly
            # This while loop eventually always exits, showing the owner is set
            while not owner:
                owner = lockr_instance.owner()
                if owner is not None:
                    break
            assert owner is not None
            assert owner.decode('utf-8', 'ignore') == lockr_config.value
            assert "Lock refresh failed, trying to re-acquire" in caplog.text
            assert "Lock refresh failed, but successfully re-acquired unclaimed lock" in caplog.text
            assert lockr_thread.is_alive() is True  # thread stays up, as lock is eventually acquired
