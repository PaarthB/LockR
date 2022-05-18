#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from __future__ import absolute_import
from __future__ import print_function

from setuptools import setup, find_packages


setup(
    name='lockr',
    version='1.0.0',
    license='MIT',
    description='CLI tool leveraging Redis locking pattern for management of distributed applications in cloud',
    author='Paarth Bhasin',
    url='https://github.com/PaarthB/LockR/',
    packages=find_packages(exclude=["tests"]),
    include_package_data=True,
    zip_safe=False,
    python_requires='>=3.8.13',
    py_modules=['cli', 'lockr'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'Operating System :: Unix',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3.8',
        'Topic :: Utilities',
    ],
    install_requires=[
        'requests==2.27.1',
        'click==8.1.2',
        'redis<4.0.0,>=3.0.0',
        'redis-py-cluster==2.1.3'
    ],
    entry_points={
        'console_scripts': [
            'lockr = src.cli.main:main',
        ]
    },
)
