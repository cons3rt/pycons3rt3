#!/usr/bin/env python3

"""Module: ssh

This module provides utilities for performing typical SSH actions like
generating SSH keys

"""
import logging
import os

from .logify import Logify
from .bash import mkdir_p, run_command, run_remote_command
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
    :return: (tuple) (str) paths to the private and public key files
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.generate_ssh_rsa_key')
    if not dest_directory:
        dest_directory = os.path.join(os.path.expanduser('~'), '.ssh')
    if not os.path.exists(dest_directory):
        mkdir_p(dest_directory)
    key_path = os.path.join(dest_directory, key_name)
    pub_key_path = key_path + '.pub'
    if os.path.isfile(key_path):
        os.remove(key_path)
    if os.path.isfile(pub_key_path):
        os.remove(pub_key_path)
    command = ['ssh-keygen', '-t', 'rsa', '-b', '4096', '-N', '{p}'.format(p=passphrase),
               '-C', '{c}'.format(c=comment), '-f', key_path]
    try:
        result = run_command(command, output=False, timeout_sec=30.0)
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if result['code'] != 0:
        raise CommandError('Command exited with code {a}: {c}'.format(
            a=str(result['code']), c=' '.join(command)))
    log.info('Generated RSA keypair: {f}'.format(f=key_path))
    try:
        os.chmod(key_path, 0o400)
        os.chmod(pub_key_path, 0o644)
    except OSError as exc:
        raise CommandError('Problem setting permissions on SSH keys') from exc
    return key_path, pub_key_path


def ssh_copy_id(pub_key_path, host, remote_username=None, port=22):
    """Copies SSH keys to a remote host

    NOTE: Assumes SSH can be access password-less on the remote
    machine

    :param pub_key_path: (str) path to the SSH key file to copy
    :param host: (str) hostname or IP address to copy the file to
    :param remote_username: (str) username on the remote machine
    :return: True if successful
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.ssh_copy_id')
    if remote_username:
        user_host_str = '{u}@{h}'.format(u=remote_username, h=host)
    else:
        user_host_str = host
    if not os.path.isfile(pub_key_path):
        raise CommandError('Public key file not found: {f}'.format(f=pub_key_path))
    with open(pub_key_path) as f:
        pub_key_contents = f.read()
    command = 'echo "{p}" >> $HOME/.ssh/authorized_keys'.format(p=pub_key_contents)
    log.info('Copying key {k} to host: {h}'.format(k=pub_key_path, h=user_host_str))
    try:
        result = run_remote_command(host=user_host_str, command=command, timeout_sec=30.0)
    except CommandError as exc:
        raise CommandError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if result['code'] != 0:
        raise CommandError('Command exited with code {a}: {c}'.format(
            a=str(result['code']), c=' '.join(command)))
    return True
