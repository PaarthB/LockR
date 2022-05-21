"""
#### LockR is a reliable cli tool, providing easy access to redis locking pattern, usable by all applications ####

- LockR provides management of distributed applications which have a strict requirement of not running more than one
  instance at a time.

- LockR ensures that a given process / application in a distributed architecture does not run on more than one node
  at the same time

- This is done by using an expiring lock in Redis, which is refreshed continuously every few seconds
  (defined in the config).

- If the application faces bottlenecks causing slowed processing (e.g. high CPU usage), or dies off,
  the lock will expire soon and another instance of the application should be able to acquire the lock.

- LockR is based around the redis locking pattern described here:https://redis.io/docs/reference/patterns/distributed-locks/
"""

import atexit
import logging
import os
import shlex
import signal
import subprocess
import sys
import time
from configparser import ConfigParser
from functools import reduce
from typing import Union, Type, List

import redis
from redis import StrictRedis, RedisCluster
from redis.cluster import ClusterNode

from redis.exceptions import LockNotOwnedError
from redis.lock import Lock

from lockr.constants import LUA_EXTEND_SCRIPT

logging.basicConfig(level=logging.INFO, format='%(asctime)s LockR: %(message)s', datefmt='%Y-%m-%d %H:%M:%S %Z')
logger = logging.getLogger()


class LockRConfig:
    """
    Defines the state of LockR, used later for executing the Redis Locking pattern or Redlock Algorithm
    """
    lock_value_prefix: str = "LockR"
    lock_name: str = "lockr"
    redis_db: int = 0

    def __init__(self, command: str, lockname: str, lock_prefix: str, redis_cls: Type[Union[StrictRedis, RedisCluster]],
                 redis_port: int = 6379, redis_db: int = 0, cluster_nodes: List[str] = None, host: str = '',
                 config_path: str = 'lockr.ini', timeout: int = 1000, redis_password: str = None,
                 use_shell: bool = False):
        self.command: str = command
        self.use_shell: bool = use_shell
        self.timeout: float = float(timeout / 1000)  # convert to seconds
        # sleep < timeout, specifically 1/3rd, to ensure we refresh 3 times within each extension period
        # (lock extends by timeout amount 3 times within a single period itself)
        self.sleep: float = float(timeout / (1000.0 * 3))
        self.process = None

        # Set the value contained within the lock. Use special prefix if given, else use default one and os PID
        self.value: str = "%s-%d" % (lock_prefix, os.getpid())
        self.port: int = redis_port
        self.db: int = redis_db
        self.host: str = host
        self.cluster_nodes: List[str] = cluster_nodes
        self.name: str = lockname
        self.config: str = config_path
        self.password: str = redis_password
        self.redis_cls: Type[Union[StrictRedis, RedisCluster]] = redis_cls

    @staticmethod
    def from_config_file(config_file_path: str = 'lockr.ini'):
        redis_host = ''
        redis_nodes = None
        config = ConfigParser(os.environ)
        if not os.path.exists(config_file_path):
            logger.error(
                "Invalid lockr config path specified: %s - by default lockr.ini should be in the current directory",
                config_file_path)
            raise FileNotFoundError(f"File path {config_file_path} not found.")
        config.read(config_file_path)
        if not config.has_section('lockr') or not config.has_section('redis'):
            logger.error("Invalid lockr config file. Require both the sections [redis] and [lockr] to be defined")
            sys.exit(os.EX_CONFIG)
        if not config.has_option('lockr', 'command'):
            logger.error("[lockr] section does not have 'command' defined")
            sys.exit(os.EX_CONFIG)
        if config.has_option('redis', 'host') and config.has_option('redis', 'cluster_nodes'):
            logger.error("[redis] section of config file must specify one of 'host' or 'cluster_nodes', not both.")
            sys.exit(os.EX_CONFIG)

        if not config.has_option('redis', 'host') and not config.has_option('redis', 'cluster_nodes'):
            logger.error(
                "[redis] section of config file must specify either 'host' or 'cluster_nodes' section. "
                "Didn't find either.")
            sys.exit(os.EX_CONFIG)

        # Single redis instance
        if config.has_option('redis', 'host'):
            # Single Redis mode
            host = os.path.expandvars(config.get('redis', 'host'))
            redis_host = host if host != config.get('redis', 'host') else os.getenv(host, 'localhost')
            redis_cls = StrictRedis

        # Redis Cluster mode
        else:
            redis_nodes = [
                ClusterNode(host=os.path.expandvars(node.split(':')[0]), port=int(os.path.expandvars(node.split(':')[1])))
                for node in config.get('redis', 'cluster_nodes').split('\n')
            ]
            redis_cls = RedisCluster

        lockr_kwargs = dict(
            host=redis_host, cluster_nodes=redis_nodes,
            timeout=config.getint('lockr', 'timeout', fallback=1000),
            use_shell=config.getboolean('lockr', 'use_shell', fallback=False),
        )

        # Update the redis instance class to be used
        lockr_kwargs.update(dict(redis_cls=redis_cls))

        # Update the lockname
        lockr_kwargs.update(dict(lockname=config.get('lockr', 'lockname', fallback=LockRConfig.lock_name)))

        # Update the lock value prefix
        lockr_kwargs.update(
            dict(lock_prefix=config.get('lockr', 'lock_prefix', fallback=LockRConfig.lock_value_prefix)))

        if config.has_option('redis', 'port'):
            port = os.path.expandvars(config.get('redis', 'port'))
            lockr_kwargs.update(
                dict(redis_port=int(port if port != config.get('redis', 'port') else os.getenv(port, '6379'))))
        if config.has_option('redis', 'database'):
            lockr_kwargs.update(dict(redis_db=config.getint('redis', 'database', fallback=LockRConfig.redis_db)))
        if config.has_option('redis', 'password'):
            lockr_kwargs.update(dict(redis_password=config.get('redis', 'password')))

        return LockRConfig(config.get('lockr', 'command'), **lockr_kwargs)


class LockR:
    """ LockR is responsible for ensuring exclusive task / application execution.  """

    def __init__(self, lockr_config: LockRConfig, dry_run: bool = False):
        """ Build the setup from the provided config """
        self.config: LockRConfig = lockr_config
        self.dry_run: bool = dry_run
        self.process = None  # Defines the eventual process that will be run by LockR

        redis_kwargs = dict(password=self.config.password)
        if self.config.db and not self.config.cluster_nodes:
            redis_kwargs.update(dict(db=self.config.db))
        if self.config.cluster_nodes:  # Redis Cluster mode
            redis_kwargs.update(dict(startup_nodes=self.config.cluster_nodes))
            logger.info("LockR will connect to a Redis Cluster.")
        elif "/" in self.config.host:  # Redis via unix-socket connection implementation
            redis_kwargs.update(dict(unix_socket_path=self.config.host))
            logger.info("LockR will connect to single Redis instance via Unix domain socket.")
        else:  # Redis via HTTP connection
            redis_kwargs.update(dict(host=self.config.host, port=self.config.port))
            logger.info("LockR will connect to single Redis instance")
        self.redis: Type[Union[StrictRedis, RedisCluster]] = self.config.redis_cls(**redis_kwargs)

        if dry_run:
            logger.info(" --- Valid configuration found. Dry run verification successful ---")
            sys.exit(0)
        try:
            redis_info = self.redis.info()
        except redis.exceptions.ConnectionError as e:
            logger.exception("Couldn't connect to Redis: %s", str(e))
            sys.exit(os.EX_NOHOST)

        # Verify redis version is recent enough. 'redis_version' is absent for Redis Cluster, as redis_info is a dict of
        # cluster nodes - it is not required for redis clusters.
        if 'redis_version' in redis_info and reduce(lambda l, r: l * 1000 + r,
                                                    map(int, redis_info['redis_version'].split('.'))) < 2006012:
            logger.error("Redis version is too old. You got %s, minimum requirement is %s", redis_info['redis_version'],
                         '2.6.12')
            sys.exit(os.EX_PROTOCOL)

        self.lockname: str = self.config.name or "lockr:%s" % self.config.command
        #
        self._lock: Lock = self.redis.lock(name=self.lockname, timeout=self.config.timeout, sleep=self.config.sleep)

        # overwrite redis-py's extend script used for extending the TTL value of a redis key
        # This will add additional timeout instead of extend to a new timeout (which is actually set during acquisition)
        self._lock.lua_extend = self.redis.register_script(LUA_EXTEND_SCRIPT)

        # The exception handling functions, to handle if anything goes during the lifetine of the execution of LockR
        atexit.register(self.crash)
        atexit.register(self.handle_signal, signal.SIGTERM)
        atexit.register(self.handle_signal, signal.SIGINT)
        atexit.register(self.handle_signal, signal.SIGHUP)

    def run(self):
        """ 
        Start the process if it's not being run by someone else, else keep waiting until the lock is released 
        This means process execution is also paused until the lock can be acquired
        """
        logger.info("Waiting on lock, currently held by %s", self.owner())
        try:
            # continues to wait until the lock is available (expired or released)
            if self._lock.acquire(token=self.config.value, blocking=True):
                logger.info("Lock '%s' acquired", self.lockname)

                # We got the lock, so we make sure the process is running and keep refreshing the lock -
                # if we ever stop for any reason, for example because our host died, the lock will soon expire.
                while True:
                    if self.process is None:  # Process not started yet
                        self.process = self.start(self.config.command if not self.dry_run else "print 1")
                        logger.info("Started process with PID %d", self.process.pid)
                    process_status = self.process.poll()
                    try:
                        if process_status is not None:
                            # Process died, due to some issue or normal exit procedure
                            logger.error("Process terminated with exit code %d", process_status)
                            self._lock.release()  # release the lock since we no longer need it
                            sys.exit(1)
                        # increase TTL / refresh the lock by the config 'timeout' amount and sleep
                        self._lock.extend(self.config.timeout)
                    except LockNotOwnedError as e:
                        if process_status is not None:  # No need to re-acquire since process has been removed
                            sys.exit(1)
                        logger.warning("Lock refresh failed, trying to re-acquire. Error: %s", str(e))
                        owner = self.owner()
                        if owner is None:
                            if self._lock.acquire(token=self.config.value, blocking=False):
                                logger.warning("Lock refresh failed, but successfully re-acquired unclaimed lock")
                            else:
                                logger.error(
                                    "Lock refresh and subsequent re-acquire failed, giving up (Lock now held by %s)",
                                    self.owner())
                                self.cleanup()
                                sys.exit(os.EX_UNAVAILABLE)
                        else:
                            logger.error("Unable to refresh lock, its owned by %s now", self.owner())
                            self.cleanup()
                            sys.exit(os.EX_UNAVAILABLE)
                    time.sleep(self.config.sleep)
        except (RuntimeError, Exception) as e:
            logger.exception("An exception occurred while trying to acquire/refresh the lock. Error: %s", str(e))
            self.cleanup()
            sys.exit(os.EX_UNAVAILABLE)

    def start(self, command):
        """ Start a process defined by the command parameter """
        if self.config.use_shell:
            args = command
        else:
            args = shlex.split(command)
        return subprocess.Popen(args, shell=self.config.use_shell)

    def cleanup(self):
        """ Ensure process is terminated/killed """
        if self.process is None:  # No process was running
            return
        if self.process.poll() is None:
            logger.info("Sending TERM to process with PID: %d", self.process.pid)
            self.process.terminate()

            # Wait for 1s before killing it
            start = time.perf_counter()
            while time.perf_counter() - start < 1.0:
                time.sleep(0.05)
                if self.process.poll() is not None:
                    break
            else:
                logger.info("Sending KILL signal to process with PID: %d", self.process.pid)
                self.process.kill()
        assert self.process.poll() is not None

    def handle_signal(self, sig):
        """ Handles signals, surprisingly """
        if sig in [signal.SIGINT]:
            logger.warning("Ctrl-C pressed, shutting down...")
        if sig in [signal.SIGTERM]:
            logger.warning("SIGTERM received, shutting down...")
        self.cleanup()
        sys.exit(-sig)

    def crash(self):
        """
        For handling unexpected exits, like:
           - Redis connectivity failure
           - Memory failure, OOMEs etc.
        """
        self.cleanup()

    def owner(self):
        """ Returns the owner (value) of the lock if there is an owner, or 'None' if the key doesn't exist """
        return self.redis.get(self.lockname)
