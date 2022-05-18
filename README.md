-------
# LockR 

![Dynamic Soaking Workflow](assets/lockr-logo-1.png)

[![Python 3.8](https://img.shields.io/badge/python-3.8-blue.svg)](https://www.python.org/downloads/release/python-380/)
[![Python 3.9](https://img.shields.io/badge/python-3.9-blue.svg)](https://www.python.org/downloads/release/python-390/)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/release/python-3100/)
![example workflow](https://raw.githubusercontent.com/dwyl/repo-badges/main/svg/build-passing.svg)

```LockR``` is an open source CLI tool which solves the problem of concurrency management for distributed applications in cloud.

In summary, it provides out of the box ability to use the well known <u><b>*"Redis Locking pattern"*</b></u>. 
Read more [here](https://redis.com/ebook/part-2-core-concepts/chapter-6-application-components-in-redis/6-2-distributed-locking/#:~:text=With%20distributed%20locking%2C%20we%20have,machines%20can%20acquire%20and%20release.)

# Why LockR?
* **Manage any application in the cloud**: 
It is meant to be very general purpose CLI tool, to provide applications with distributed locking, to prevent duplicate instances of the application running at the same time:
    * Usable for all sorts of applications (Flask app, Spring boot app, Celery workers etc.) if you want to prevent more than one instance of the app running at the same time.
* **Extremely fault-tolerant**: `LockR` is designed to be resilient to network errors, application problems and so on. 
So you only need to worry about your own application.
* **Simple to use**: `LockR` is very straightforward to use and maintain
* **No 3rd party dependencies**: `LockR` has been built entirely using in-built python libraries, not relying on any 3rd party libraries. 


## Getting started
To use `LockR`, install it from PyPi as follows:
<br/>
> pip install lockr 

You then need a configuration file to tell `lockr` what to do. Its usually called `lockr.ini` but can be any name also be anywhere, 
as long as it is readable and in the right format.

A general configuration looks as follows:
```
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
# Defaults to 'LockR'
lock_prefix = test-prefix

[redis]
# defaults to localhost. Specify environment variable or pass directly as well
host = ${REDIS_HOST}

# port is optional and defaults to 6379. Specify environment variable or pass directly as well
port = ${REDIS_PORT}

# In single Redis server mode only, you can SELECT the database.
database = 1
```

All the default parameters are option, which take the default value if nothing is specified. It is recommended not to update them,
unless you want to fine tune your `lockr` instance.

Then just run:
> lockr run --dry-run

If your config file is valid, you should see the output:
> Valid configuration found. Dry run verification successful

Once, you've confirmed the file is valid, run:
> lockr run

## Prerequisites

