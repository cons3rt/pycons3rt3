#!/usr/bin/env python3

"""cons3rt -- entry point for CLI

Usage: %s [options]

Options:
setup -- configures

"""

import sys
import argparse

from .cons3rtconfig import manual_config
from .cons3rtcli import CloudspaceCli, ProjectCli, CloudCli, TeamCli

# Commands for setting up the cons3rtapi configuration
setup_command_options = [
    'setup',
    'config',
    'configure'
]

# List of valid CLI commands
valid_commands = setup_command_options + [
    'cloudspace',
    'project',
    'cloud',
    'team'
]

# String representation of valid commands
valid_commands_str = 'Valid commands: {c}'.format(c=', '.join(valid_commands))


def cloudspace_cli(args):
    c = CloudspaceCli(args)
    if c.process_args():
        return 0
    return 1


def project_cli(args):
    c = ProjectCli(args)
    if c.process_args():
        return 0
    return 1


def cloud_cli(args):
    c = CloudCli(args)
    if c.process_args():
        return 0
    return 1


def team_cli(args):
    c = TeamCli(args)
    if c.process_args():
        return 0
    return 1


def main():
    parser = argparse.ArgumentParser(description='CONS3RT command line interface (CLI)')
    parser.add_argument('command', help='Command for the cons3rt CLI')
    parser.add_argument('--delete', help='Delete action relative to the command provided', action='store_true')
    parser.add_argument('--delete_inactive_runs', help='Delete inactive runs from a cloudspace', action='store_true')
    parser.add_argument('--release_active_runs', help='Release active runs from a cloudspace', action='store_true')
    parser.add_argument('--list_active_runs', help='List active runs in a cloudspace', action='store_true')
    parser.add_argument('--list', help='List action for the provided command', action='store_true')
    parser.add_argument('--my', help='Modifier for list action for only my things', action='store_true')
    parser.add_argument('--all', help='All action relative to the command provided', action='store_true')
    parser.add_argument('--id', help='ID relative to the command provided', required=False)
    parser.add_argument('--ids', help='List of IDs relative to the command provided', required=False)
    args = parser.parse_args()

    # Get the command
    command = args.command.strip()

    if command not in valid_commands:
        print('Invalid command found [{c}]\n'.format(c=command) + valid_commands_str)

    if args.command in setup_command_options:
        manual_config()
    elif args.command == 'cloudspace':
        return cloudspace_cli(args)
    elif args.command == 'project':
        return project_cli(args)
    elif args.command == 'cloud':
        return cloud_cli(args)
    elif args.command == 'team':
        return team_cli(args)
    else:
        print('Command is not yet supported: {c}'.format(c=args.command))
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
