import os

import click

from lockr.lockr.core import LockRConfig, LockR


@click.option("--dry-run", is_flag=True, show_default=True, default=False, help="Dry run of lockr to test it works.")
@click.option('--config-file', default=os.getcwd() + '/lockr.ini',
              help="Path to config file, defaults to current folder 'lockr.ini'")
@click.command(hidden=False)
def run(dry_run, config_file):
    """ Run LockR based on the config file to enable Redis locking pattern. """
    try:
        lockr = LockR(lockr_config=LockRConfig.from_config_file(config_file), dry_run=dry_run)
        print("Starting lockr to put an exclusive lock on the requested process, during its execution lifetime")
        lockr.run()
    except Exception as err:
        print("Encountered error while applying lockr exclusive lock:", str(err))
        raise err
