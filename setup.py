#!/usr/bin/env python
# -*- encoding: utf-8 -*-
from __future__ import absolute_import
from __future__ import print_function

from setuptools import setup, find_packages

long_description = open('README.rst').read()

setup(
    name='lockr',
    version='0.0.3',
    license='Apache License, Version 2.0',
    description='CLI tool leveraging Redis locking pattern for management of distributed applications in cloud',
    long_description=long_description,
    author='Paarth Bhasin',
    long_description_content_type='text/x-rst',
    url='https://github.com/PaarthB/LockR/',
    packages=find_packages(include=['cli', 'lockr'], exclude=["tests"]),
    include_package_data=True,
    zip_safe=False,
    python_requires='>=3.8.13',
    py_modules=['cli', 'lockr'],
    tests_require=['pytest'],
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
        'redis==4.3.1',
    ],
    entry_points={
        'console_scripts': [
            'lockr=cli.main:main',
        ]
    },
)
