import click

from . import commands


@click.group()
def cli_group():
    pass


cli_group.add_command(commands.run, "run")
