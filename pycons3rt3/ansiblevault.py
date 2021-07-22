#!/usr/bin/env python3

"""Module: ansiblevault

This module provides utilities for performing encryption and decryption
with ansible-vault

"""
import logging
import os
import shutil

from .logify import Logify
from .bash import run_command
from .exceptions import CommandError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.ansiblevault'


def ansible_vault_decrypt_file(encrypted_file, password_file, vault_id=None):
    """Decrypts a file using ansible-vault and a password file, optionally a Vault ID

    :param encrypted_file: (str) path to encrypted file
    :param password_file: (str) path to the Ansible Vault password file
    :param vault_id: (str) Ansible Vault ID to provide along with the password file
    :return: True (if successful)
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.ansible_vault_decrypt_file')
    if not os.path.isfile(password_file):
        raise CommandError('Password file not found: {f}'.format(f=password_file))
    if not os.path.isfile(encrypted_file):
        raise CommandError('Encrypted file not found: {f}'.format(f=encrypted_file))

    # Determine the command based on Vault ID provided or not
    if vault_id:
        log.info('Decrypting file [{f}] with vault ID and password file [{v}@{p}]'.format(
            f=encrypted_file, v=vault_id, p=password_file))
        command = ['ansible-vault', 'decrypt', '--vault-id', '{v}@{p}'.format(v=vault_id, p=password_file)]
    else:
        log.info('Decrypting file [{f}] with password file [{p}]'.format(f=encrypted_file, p=password_file))
        command = ['ansible-vault', 'decrypt', encrypted_file, '--vault-password-file', password_file]

    # Decrypt the file in-place
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem decrypting file {f} with password file: {p}'.format(
            f=encrypted_file, p=password_file)) from exc
    if result['code'] != 0:
        raise CommandError('ansible-vault exited with code: {c}'.format(c=str(result['code'])))
    log.info('Created decrypted file: {d}'.format(d=encrypted_file))
    return True


def ansible_vault_encrypt_file(decrypted_file, password_file, vault_id=None):
    """Encrypts a file using ansible-vault and a password file, optionally a vault ID

    :param decrypted_file: (str) path to decrypted file
    :param password_file: (str) path to the password file for decryption
    :param vault_id: (str) Ansible Vault ID to provide along with the password file
    :return: True (if successful)
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.ansible_vault_encrypt_file')
    if not os.path.isfile(password_file):
        raise CommandError('Password file not found: {f}'.format(f=password_file))
    if not os.path.isfile(decrypted_file):
        raise CommandError('Decrypted file not found: {f}'.format(f=decrypted_file))

    # Determine the command based on Vault ID provided or not
    if vault_id:
        log.info('Encrypting file [{f}] with vault ID and password file [{v}@{p}]'.format(
            f=decrypted_file, v=vault_id, p=password_file))
        command = ['ansible-vault', 'encrypt', '--vault-id', '{v}@{p}'.format(v=vault_id, p=password_file)]
    else:
        log.info('Encrypting file [{f}] with password file [{p}]'.format(f=decrypted_file, p=password_file))
        command = ['ansible-vault', 'encrypt', decrypted_file, '--vault-password-file', password_file]

    # Encrypt the file in-place
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem encrypting file {f} with password file: {p}'.format(
            f=decrypted_file, p=password_file)) from exc
    if result['code'] != 0:
        raise CommandError('ansible-vault exited with code: {c}'.format(c=str(result['code'])))
    log.info('Created encrypted file: {d}'.format(d=decrypted_file))
    return True
