#!/usr/bin/env python3

"""Module: ssh

This module provides utilities for performing typical SSH actions like
generating SSH keys

"""
import logging
import os
import shutil
import time
from datetime import datetime

from .bash import mkdir_p, manage_service, run_command, run_remote_command
from .exceptions import CommandError, SshConfigError
from .logify import Logify

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
    log = logging.getLogger(mod_logger + '.add_host_key_to_known_hosts')
    if not key_contents and not key_file:
        raise SshConfigError('key_file or key_contents required')

    # Read the known_hosts contents
    known_hosts_file = os.path.join(os.path.expanduser('~'), '.ssh', 'known_hosts')
    known_hosts_file_contents = ''
    if os.path.isfile(known_hosts_file):
        with open(known_hosts_file, 'r') as f:
            known_hosts_file_contents = f.read()
    if not key_contents:
        key_contents = ''
    if key_file:
        if not os.path.isfile(key_file):
            raise SshConfigError('key_file not found: {f}'.format(f=key_file))
        with open(key_file, 'r') as f:
            key_file_contents = f.read()
            key_contents += os.linesep + key_file_contents + os.linesep
    key_contents = os.linesep.join([s for s in key_contents.splitlines() if s])
    if key_contents == '':
        log.info('No keys found in input, exiting without adding to known_hosts')
        return
    key_content_lines = key_contents.split(os.linesep)
    log.info('Checking {n} provided keys to see if they are not already in the known_hosts file'.format(
        n=str(len(key_content_lines))))
    keys_to_add = []
    for key_content_line in key_content_lines:
        if 'no route' in key_content_line.lower():
            raise SshConfigError('Found a key with "no route" in it: {k}'.format(k=key_content_line))
        elif key_content_line.startswith('#'):
            log.info('Skipping comment line...')
        elif key_content_line in known_hosts_file_contents:
            log.info('Key already exists in known_hosts, skipping...')
        else:
            log.info('Key does not exist in known_hosts, adding...')
            keys_to_add.append(key_content_line)
    if len(keys_to_add) < 1:
        log.info('No new keys to add to known_hosts!')
    keys_to_add_str = os.linesep.join(keys_to_add)
    known_hosts_file_contents += os.linesep + keys_to_add_str + os.linesep
    known_hosts_file_contents = os.linesep.join([s for s in known_hosts_file_contents.splitlines() if s])
    with open(known_hosts_file, 'w') as f:
        f.write(known_hosts_file_contents)
    os.chmod(known_hosts_file, 0o644)
    log.info('keys successfully added to known hosts file')


def add_host_key_to_authorized_keys(key_contents=None, key_file=None):
    """Adds keys to the authorized keys file

    :param key_contents: (str) key contents to add
    :param key_file: (str) path to a file containing 1 or more host keys
    :return: None
    :raises: SshConfigError
    """
    log = logging.getLogger(mod_logger + '.add_host_key_to_authorized_keys')
    if not key_contents and not key_file:
        raise SshConfigError('key_file or key_contents required')

    # Read the authorized keys contents
    authorized_keys_file = os.path.join(os.path.expanduser('~'), '.ssh', 'authorized_keys')
    authorized_keys_file_contents = ''
    if os.path.isfile(authorized_keys_file):
        with open(authorized_keys_file, 'r') as f:
            authorized_keys_file_contents = f.read()

    if not key_contents:
        key_contents = ''
    if key_file:
        if not os.path.isfile(key_file):
            raise SshConfigError('key_file not found: {f}'.format(f=key_file))
        with open(key_file, 'r') as f:
            key_file_contents = f.read()
            key_contents += os.linesep + key_file_contents + os.linesep
    key_contents = os.linesep.join([s for s in key_contents.splitlines() if s])
    if key_contents == '':
        return

    authorized_keys_file_contents += os.linesep + key_contents + os.linesep
    authorized_keys_file_contents = os.linesep.join([s for s in authorized_keys_file_contents.splitlines() if s])
    with open(authorized_keys_file, 'w') as f:
        f.write(authorized_keys_file_contents)
    os.chmod(authorized_keys_file, 0o600)
    log.info('keys successfully added to authorized keys file')


def add_host_to_known_hosts(host):
    """Adds a remote host key to the known_hosts file

    :param host: (str) hostname or IP of the remote host
    :return: None
    :raises: SshConfigError
    """
    log = logging.getLogger(mod_logger + '.add_host_to_known_hosts')
    command = ['ssh-keyscan', '-t', 'rsa', host]
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
    log.info('Successfully added host key for [{h}] to known_hosts'.format(h=host))


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


def update_sshd_config(config_data):
    """Updates the SSHD config file with the provided config data

    :param config_data: (dict) of key value pairs to create the configs
    :return: None
    :raises: SshConfigError
    """
    log = logging.getLogger(mod_logger + '.update_sshd_config')
    sshd_config_file = os.path.join(os.sep, 'etc', 'ssh', 'sshd_config')
    if not os.path.isfile(sshd_config_file):
        raise SshConfigError('sshd config file not found: {f}'.format(f=sshd_config_file))
    log.info('Updating the sshd config file: {f}'.format(f=sshd_config_file))

    # Backup the sshd config
    time_now = datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_file = '{f}.{d}'.format(f=sshd_config_file, d=time_now)
    log.info('Creating backup file: {f}'.format(f=backup_file))
    shutil.copy2(sshd_config_file, backup_file)

    # Read the sshd config
    with open(sshd_config_file, 'r') as f:
        sshd_contents = f.read()
    sshd_lines = sshd_contents.split('\n')
    new_lines = []

    for line in sshd_lines:
        skip = False
        for item, value in config_data.items():
            if line.startswith(item):
                skip = True
                log.info('Removing line: {t}'.format(t=line))
        if not skip:
            new_lines.append(line)

    for item, value in config_data.items():
        new_line = '{k} {v}\n'.format(k=item, v=value)
        log.info('Adding line: {t}'.format(t=new_line))
        new_lines.append(new_line)

    # Build output
    new_sshd_contents = ''
    for line in new_lines:
        new_sshd_contents += line + '\n'

    # Write the output file
    with open(sshd_config_file, 'w') as f:
        f.write(new_sshd_contents)

    # Restart the sshd service
    log.info('Restarting the sshd service...')
    try:
        manage_service(service_name='sshd', service_action='restart', systemd=True)
    except OSError as exc:
        raise SshConfigError('Problem restarting the sshd service') from exc
