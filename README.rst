LockR
========

.. image:: https://raw.githubusercontent.com/PaarthB/LockR/main/assets/lockr-logo-1.png
    :alt: lockr

.. image:: https://img.shields.io/badge/python-3.8-blue.svg
    :alt: python3.8

.. image:: https://img.shields.io/badge/python-3.9-blue.svg
    :alt: python3.9

.. image:: https://img.shields.io/badge/python-3.10-blue.svg
    :alt: python3.10

.. image:: https://raw.githubusercontent.com/dwyl/repo-badges/main/svg/build-passing.svg
    :alt: buildPassing

``LockR`` is an open source CLI tool which solves the problem of concurrency management for distributed applications in cloud, using Redis.

In summary, it provides out of the box ability to use the well known **Redis Locking pattern** or **Redlock Algorithm**

Read more `here <https://redis.io/docs/reference/patterns/distributed-locks/>`_

Why LockR?
----------

- Manage any application in the cloud: 
    *  It is meant to be a very general purpose CLI tool, to provide applications with distributed locking mechanism, to prevent duplicate instances of the application running at the same time
    * Usable for all sorts of applications (Flask app, Spring boot app, Celery workers etc.) if you want to prevent more than one instance of the app running at the same time.
- Extremely fault-tolerant: 
    * `LockR` is designed to be resilient to network errors, application problems and so on. So you only need to worry about your own application.
- Simple to use: 
    * `LockR` is very straightforward to use and maintain
- No 3rd party dependencies: 
    * `LockR` has been built entirely using in-built python libraries, not relying on any 3rd party libraries.


Getting started
----------------


Install with ``pip``

.. code-block:: python

    pip install lockr

You then need a configuration file to tell ``lockr`` what to do. Its usually called ``lockr.ini`` but can be any name also be anywhere,
as long as it is readable and in the right format.

To find usage instructions run:

.. code-block:: console

    lockr --help
    lockr run --help

A general configuration looks as follows:

.. code-block:: python

    # LockR default configuration file
    [lockr]
    # LockR timeout in milliseconds. Higher values mean it will take longer before a
    # downed node is recognized, lower values mean more Redis traffic.
    timeout = 1000
    # defaults to 1000
    
    # Name of the lock. If empty, generated from the command. Defaults to 'lockr'
    lockname = test-lockr
    
    # Command to execute. This is the process you want to start up. MUST BE SPECIFIED
    # Examples are: Flask app, celery worker , anything which you don't want to run on more than one node at a time
    command = "echo 'test lockr'"
    
    
    # Whether or not to run command in shell. Defaults to 'no'
    use_shell = no
    
    # Specify any custom lock prefix for the lock value stored in key 'lockname'
    # Defaults to 'LockR'. Accepts environment variables as well
    lock_prefix = test-prefix
    
    [redis]
    # defaults to localhost. Specify environment variable or pass directly as well. Conflicts with 'cluster_nodes' (only one can be specified).
    host = ${REDIS_HOST}

    # Specify all the cluster nodes each in new line. Conflicts with 'host' (only one can be specified).
    # Currently only works with environment variables
    # The nodes must have cluster mode enabled
    cluster_nodes = ${REDIS_HOST}:${REDIS_HOST}

    # port is optional and defaults to 6379. Specify environment variable or pass directly as well
    port = ${REDIS_HOST}
    
    # In single Redis server mode only, you can SELECT the database. Defaults to 0. Ignored for cluster_nodes
    database = 1

All the default parameters are optional, which take the default value if nothing is specified. It is recommended not to update them,
unless you want to fine tune your `lockr` instance.

Then just run:

.. code-block:: console

    lockr run --dry-run

If your config file is valid, you should see the output:

.. code-block:: console

    Valid configuration found. Dry run verification successful

Once, you've confirmed the file is valid, run:

.. code-block:: console

    lockr run


Development
------------
``LockR`` is available on `GitHub <https://github.com/PaarthB/LockR>`_

Once you have the source you can run the tests with the following commands

.. code-block:: console

    pip install -r requirements.dev.txt
    pytest tests/


