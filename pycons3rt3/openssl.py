#!/usr/bin/env python3

"""Module: openssl

This module provides utilities for performing encryption and decryption
with openssl

"""
import logging
import os

from .logify import Logify
from .bash import run_command
from .exceptions import CommandError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.openssl'


def generate_password_file(pwd_bytes=4096, out_file=None):
    """Generates a password file with openssl

    :param pwd_bytes: (int) bytes to generate
    :param out_file: (str) path to output file
    :return: (str) password contents
    """
    log = logging.getLogger(mod_logger + '.generate_password_file')
    command = ['openssl', 'rand', '-base64', str(pwd_bytes)]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem running command: {c}'.format(c=' '.join(command))) from exc
    if result['code'] != 0:
        raise CommandError('openssl exited with code: {c}'.format(c=str(result['code'])))
    password_contents = result['output']
    if out_file:
        try:
            with open(out_file, 'w') as f:
                f.write(password_contents)
        except OSError as exc:
            raise CommandError('Problem writing file: {f}'.format(f=out_file)) from exc
        else:
            log.info('Generated password file: {f}'.format(f=out_file))
    return password_contents


def openssl_decrypt(encrypted_file, decrypted_file, password_file):
    """Decrypts a file using openssl and a password file

    :param encrypted_file: (str) path to encrypted file
    :param decrypted_file: (str) path to decrypted file
    :param password_file: (str) path to the password file for decryption
    :return: True (if successful)
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.openssl_decrypt')
    if not os.path.isfile(password_file):
        raise CommandError('Password file not found: {f}'.format(f=password_file))
    if not os.path.isfile(encrypted_file):
        raise CommandError('Encrypted file not found: {f}'.format(f=encrypted_file))
    command = ['openssl', 'enc', '-d', '-aes-256-cbc', '-a', '-in', encrypted_file, '-out', decrypted_file,
               '-pass', 'file:{p}'.format(p=password_file)]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem decrypting file {f} with password file: {p}'.format(
            f=decrypted_file, p=password_file)) from exc
    if result['code'] != 0:
        raise CommandError('openssl exited with code: {c}'.format(c=str(result['code'])))
    log.info('Created decrypted file: {d}'.format(d=decrypted_file))
    return True


def openssl_smime_decrypt(encrypted_file, decrypted_file, password_file):
    """Decrypts a file using openssl smime and a password file

    # From Otto
    openssl smime -decrypt -md sha512 -binary -in $DIR/cons3rt-otto.enc -inform DER -out $DIR/cons3rt-otto.txt
    -inkey $DIR/`basename $ENC_CRT`.key

    :param encrypted_file: (str) path to encrypted file
    :param decrypted_file: (str) path to decrypted file
    :param password_file: (str) path to the key file for decryption
    :return: True (if successful)
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.openssl_smime_decrypt')
    if not os.path.isfile(password_file):
        raise CommandError('Password file not found: {f}'.format(f=password_file))
    if not os.path.isfile(encrypted_file):
        raise CommandError('Encrypted file not found: {f}'.format(f=encrypted_file))
    command = ['openssl', 'smime', '-decrypt', '-md', 'sha512', '-binary', '-in', encrypted_file, '-inform', 'DER',
               '-out', decrypted_file, '-inkey', password_file]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem decrypting file {f} with password file: {p}'.format(
            f=decrypted_file, p=password_file)) from exc
    if result['code'] != 0:
        raise CommandError('openssl exited with code: {c}'.format(c=str(result['code'])))
    log.info('Created decrypted file: {d}'.format(d=decrypted_file))
    return True


def openssl_encrypt(decrypted_file, password_file, encrypted_file=None):
    """Encrypts a file using openssl and a password file

    :param decrypted_file: (str) path to decrypted file
    :param password_file: (str) path to the password file for decryption
    :param encrypted_file: (str) path to encrypted file, will append .enc if not provided
    :return: True (if successful)
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.openssl_encrypt')
    if not os.path.isfile(password_file):
        raise CommandError('Password file not found: {f}'.format(f=password_file))
    if not os.path.isfile(decrypted_file):
        raise CommandError('Decrypted file not found: {f}'.format(f=decrypted_file))
    if not encrypted_file:
        encrypted_file = decrypted_file + '.enc'
    command = ['openssl', 'enc', '-aes-256-cbc', '-a', '-salt', '-in', decrypted_file,
               '-out', encrypted_file, '-pass', 'file:{p}'.format(p=password_file)]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem encrypting file {f} with password file: {p}'.format(
            f=decrypted_file, p=password_file)) from exc
    if result['code'] != 0:
        raise CommandError('openssl exited with code: {c}'.format(c=str(result['code'])))
    log.info('Created encrypted file: {d}'.format(d=encrypted_file))
    return True


def openssl_smime_encrypt(decrypted_file, password_file, encrypted_file=None):
    """Encrypts a file using openssl and a password file

    # From Otto
    openssl smime -encrypt -md sha512 -binary -aes-256-cbc -in $DIR/cons3rt-otto.txt -out $DIR/cons3rt-otto.enc
    -outform DER $ENC_CRT.pem

    :param decrypted_file: (str) path to decrypted file
    :param password_file: (str) path to the password file for decryption
    :param encrypted_file: (str) path to encrypted file, will append .enc if not provided
    :return: True (if successful)
    :raises: CommandError
    """
    log = logging.getLogger(mod_logger + '.openssl_encrypt')
    if not os.path.isfile(password_file):
        raise CommandError('Password file not found: {f}'.format(f=password_file))
    if not os.path.isfile(decrypted_file):
        raise CommandError('Decrypted file not found: {f}'.format(f=decrypted_file))
    if not encrypted_file:
        encrypted_file = decrypted_file + '.enc'
    command = ['openssl', 'smime', '-encrypt', '-md', 'sha512', '-binary', '-aes-256-cbc', '-in', decrypted_file,
               '-out', encrypted_file, '-outform', 'DER', password_file]
    try:
        result = run_command(command, timeout_sec=10.0)
    except CommandError as exc:
        raise CommandError('Problem encrypting file {f} with password file: {p}'.format(
            f=decrypted_file, p=password_file)) from exc
    if result['code'] != 0:
        raise CommandError('openssl exited with code: {c}'.format(c=str(result['code'])))
    log.info('Created encrypted file: {d}'.format(d=encrypted_file))
    return True
