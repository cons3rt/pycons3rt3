#!/usr/bin/env python3

"""Module: ansiblevault

This module provides utilities for performing encryption and decryption
with ansible-vault

"""
import logging
import os

from .logify import Logify
from .bash import run_command
from .exceptions import CommandError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.ansiblevault'


def ansible_vault_decrypt_file(encrypted_file, decrypted_file, password_file):
    """Decrypts a file using ansible-vault and a password file

    :param encrypted_file: (str) path to encrypted file
    :param decrypted_file: (str) path to decrypted file
    :param password_file: (str) path to the password file for decryption
    :return: True (if successful)
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.ansible_vault_decrypt_file')
    if not os.path.isfile(password_file):
        raise CommandError('Password file not found: {f}'.format(f=password_file))
    if not os.path.isfile(encrypted_file):
        raise CommandError('Encrypted file not found: {f}'.format(f=encrypted_file))

    command = ['ansible-vault', 'decrypt', encrypted_file, '--output', decrypted_file, '--vault-password-file',
               password_file]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem decrypting file {f} with password file: {p}'.format(
            f=decrypted_file, p=password_file)) from exc
    if result['code'] != 0:
        raise CommandError('ansible-vault exited with code: {c}'.format(c=str(result['code'])))
    log.info('Created decrypted file: {d}'.format(d=decrypted_file))
    return True


def ansible_vault_encrypt_file(decrypted_file, password_file, encrypted_file=None):
    """Encrypts a file using ansible-vault and a password file

    :param decrypted_file: (str) path to decrypted file
    :param password_file: (str) path to the password file for decryption
    :param encrypted_file: (str) path to encrypted file, will append .enc if not provided
    :return: True (if successful)
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.ansible_vault_encrypt_file')
    if not os.path.isfile(password_file):
        raise CommandError('Password file not found: {f}'.format(f=password_file))
    if not os.path.isfile(decrypted_file):
        raise CommandError('Decrypted file not found: {f}'.format(f=decrypted_file))
    if not encrypted_file:
        encrypted_file = decrypted_file + '.enc'

    command = ['ansible-vault', 'encrypt', encrypted_file, '--output', decrypted_file, '--vault-password-file',
               password_file]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem encrypting file {f} with password file: {p}'.format(
            f=decrypted_file, p=password_file)) from exc
    if result['code'] != 0:
        raise CommandError('ansible-vault exited with code: {c}'.format(c=str(result['code'])))
    log.info('Created encrypted file: {d}'.format(d=encrypted_file))
    return True
