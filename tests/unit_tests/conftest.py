import logging

import pytest

@pytest.fixture(scope='session')
def test_logger():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s LockR: %(message)s', datefmt='%Y-%m-%d %H:%M:%S %Z')
    logger = logging.getLogger()
    return logger

