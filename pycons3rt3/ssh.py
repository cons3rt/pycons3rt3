#!/usr/bin/env python3

"""Module: ssh

This module provides utilities for performing typical SSH actions like
generating SSH keys

"""
import logging
import os
import time

from .logify import Logify
from .bash import mkdir_p, run_command, run_remote_command
from .exceptions import CommandError, SshConfigError

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
    :raises: SshConfigError
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
        raise SshConfigError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if result['code'] != 0:
        raise SshConfigError('Command exited with code {a}: {c}'.format(
            a=str(result['code']), c=' '.join(command)))
    log.info('Generated RSA keypair: {f}'.format(f=key_path))
    try:
        os.chmod(key_path, 0o400)
        os.chmod(pub_key_path, 0o644)
    except OSError as exc:
        raise SshConfigError('Problem setting permissions on SSH keys') from exc
    return key_path, pub_key_path


def ssh_copy_id(pub_key_path, host, remote_username=None, port=22):
    """Copies SSH keys to a remote host

    NOTE: Assumes SSH can be access password-less on the remote
    machine

    :param pub_key_path: (str) path to the SSH key file to copy
    :param host: (str) hostname or IP address to copy the file to
    :param remote_username: (str) username on the remote machine
    :return: True if successful
    :raises: SshConfigError
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
        raise SshConfigError('There was a problem running: {c}'.format(c=' '.join(command))) from exc
    if result['code'] != 0:
        raise SshConfigError('Command exited with code {a}: {c}'.format(
            a=str(result['code']), c=' '.join(command)))
    return True


def add_host_key_to_known_hosts(key_contents=None, key_file=None):
    """Adds keys to the known hosts file

    :param key_contents: (str) key contents to add
    :param key_file: (str) path to a file containing 1 or more host keys
    :return: None
    :raises: SshConfigError
    """
    log = logging.getLogger(mod_logger + '.add_known_hosts')
    if not key_contents and not key_file:
        raise SshConfigError('key_file or key_contents required')
    if not key_contents:
        key_contents = ''
    if key_file:
        if not os.path.isfile(key_file):
            raise SshConfigError('key_file not found: {f}'.format(f=key_file))
        with open(key_file, 'r') as f:
            key_file_contents = f.read()
            key_contents += '\n' + key_file_contents
    key_contents = os.linesep.join([s for s in key_contents.splitlines() if s])
    if key_contents == '':
        return
    known_hosts_file = os.path.join(os.path.expanduser('~'), '.ssh', 'known_hosts')
    known_hosts_file_contents = ''
    if os.path.isfile(known_hosts_file):
        with open(known_hosts_file, 'r') as f:
            known_hosts_file_contents = f.read()
    known_hosts_file_contents += key_contents
    known_hosts_file_contents = os.linesep.join([s for s in known_hosts_file_contents.splitlines() if s])
    with open(known_hosts_file, 'w') as f:
        f.write(known_hosts_file_contents)
    os.chmod(known_hosts_file, 0o644)
    log.info('keys successfully added to known hosts file')


def add_host_to_known_hosts(host):
    """Adds a remote host key to the known_hosts file

    :param host: (str) hostname or IP of the remote host
    :return: None
    :raises: SshConfigError
    """
    log = logging.getLogger(mod_logger + '.add_host_to_known_hosts')
    command = ['ssh-keyscan', host]
    try:
        result = run_command(command, timeout_sec=30.0)
    except CommandError as exc:
        raise SshConfigError('Problem scanning host for SSH key: {h}'.format(h=host)) from exc
    if result['code'] != 0:
        raise SshConfigError('ssh-keyscan returned code [{c}] scanning host: {h}'.format(c=str(result['code']), h=host))
    host_key = result['output']
    try:
        add_host_key_to_known_hosts(key_contents=host_key)
    except CommandError as exc:
        raise SshConfigError('Problem adding host key for [{h}] to known_hosts file: {k}'.format(
            h=host, k=host_key)) from exc
    log.info('Successfully added host key for [{h}] to known_hosts: {k}'.format(h=host, k=host_key))


def wait_for_host_key(host, max_wait_time_sec=7200, check_interval_sec=10):
    """Query for available host key until the host is available
    
    :param host: (str) hostname or IP address to query
    :param max_wait_time_sec: (int) max time to wait before raising exception
    :param check_interval_sec: (int) seconds to re-try scanning a host for SSH key
    :return: None
    :raises: SshConfigError
    """
    log = logging.getLogger(mod_logger + '.wait_for_host_key')
    log.info('Querying host for SSH host key availability: {h}'.format(h=host))
    num_checks = max_wait_time_sec // check_interval_sec
    start_time = time.time()
    for _ in range(0, num_checks):
        elapsed_time = round(time.time() - start_time, 1)
        if elapsed_time > max_wait_time_sec:
            raise SshConfigError('Unable to scan SSH key for host {h} after {t} sec'.format(
                h=host, t=str(max_wait_time_sec)))
        try:
            add_host_to_known_hosts(host)
        except SshConfigError as exc:
            log.warning('Failed to query host {h} for SSH key, re-trying in {t} sec\n{e}'.format(
                h=host, t=str(check_interval_sec), e=str(exc)
            ))
            time.sleep(check_interval_sec)
        else:
            log.info('Successful SSH query of host: {h}'.format(h=host))
            return
    raise SshConfigError('Unable to scan SSH key for host {h} after {n} attempts'.format(h=host, n=str(num_checks)))


def unrestrict_host_key_checking(pattern):
    """Add an SSH config that unrestricts host key checking for a pattern

    For example: 192.168.10.*  or  *.example.com

    :param pattern: (str) pattern to add to SSH config
    :return: None
    :raises: SshConfigError
    """
    log = logging.getLogger(mod_logger + '.unrestrict_host_key_checking')
    log.info('Adding an SSH config to unrestrict host key checking for pattern: {p}'.format(p=pattern))
    ssh_config_file = os.path.join(os.path.expanduser('~'), '.ssh', 'config')
    ssh_config_contents = ''
    if os.path.isfile(ssh_config_file):
        with open(ssh_config_file, 'r') as f:
            ssh_config_contents = f.read()
    ssh_config_entry = '\nHost {p}\n\tStrictHostKeyChecking no\n'
    ssh_config_contents += ssh_config_entry
    with open(ssh_config_file, 'w') as f:
        f.write(ssh_config_contents)
    os.chmod(ssh_config_file, 0o600)
