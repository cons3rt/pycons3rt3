#!/usr/bin/env python3

"""Module: ssh

This module provides utilities for performing typical actions on
Linux machines

"""
import logging
import os

from .logify import Logify
from .bash import mkdir_p, run_command
from .exceptions import CommandError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.ssh'


def generate_ssh_rsa_key(key_name, dest_directory=None, passphrase='', comment=''):
    """Generates an RSA keypair

    :param key_name: (str) key file name
    :param dest_directory: (str) path to the directory to output the key files
    :param passphrase: (str) passphrase for the RSA key (default: None)
    :param comment: (str) RSA key comment (default: None)
    :return: None
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.generate_ssh_rsa_key')
    if not dest_directory:
        dest_directory = os.path.expanduser('~'), '.ssh'
    if not os.path.exists(dest_directory):
        mkdir_p(dest_directory)
    key_path = os.path.join(dest_directory, key_name)
    command = ['ssh-keygen', '-t', 'rsa', '-b', '4096', '-N', '"{p}"'.format(p=passphrase),
               '-C', comment, '-f', key_path]
    try:
        result = run_command(command)
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if result['code'] != 0:
        raise CommandError('Command exited with code {a}: {c}'.format(
            a=str(result['code']), c=' '.join(command)))
    log.info('Generated RSA keypair: {f}'.format(f=key_path))


def ssh_copy_id(key_path, remote_username, host, port=22):
    """Copies SSH keys to a remote host

    NOTE: Assumes SSH can be access password-less on the remote
    machine

    :param key_path: (str) path to the SSH key file to copy
    :param remote_username: (str) username on the remote machine
    :param host: (str) hostname or IP address to copy the file to
    :return: None
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.ssh_copy_id')
    if not os.path.isfile(key_path):
        raise CommandError('key file not found: {f}'.format(f=key_path))
    command = ['ssh-copy-id', '-i', key_path, '-p', str(port), '{u}@{h}'.format(u=remote_username, h=host)]
    try:
        result = run_command(command, timeout_sec=60)
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if result['code'] != 0:
        raise CommandError('Command exited with code {a}: {c}'.format(
            a=str(result['code']), c=' '.join(command)))
