#!/usr/bin/python

"""Module: pyjavakeys

This module provides utilities for performing Java keystore operations

"""
import logging
import os

from .logify import Logify
from .bash import run_command
from .exceptions import CommandError, AliasExistsError, AliasImportError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.pyjavakeys'


def alias_exists(alias, keystore_path=None, keystore_password='changeit'):
    """Checks if an alias already exists in a keystore

    :param alias:
    :param keystore_path:
    :param keystore_password:
    :return: (bool) True when the alias already exists in the keystore
    :raises: OSError
    """
    log = logging.getLogger(mod_logger + '.alias_exists')
    if not isinstance(alias, str):
        msg = 'alias arg must be a string'
        raise OSError(msg)

    # Ensure JAVA_HOME is set
    log.debug('Determining JAVA_HOME...')
    try:
        java_home = os.environ['JAVA_HOME']
    except KeyError:
        msg = 'JAVA_HOME is required but not set'
        raise OSError(msg)

    # Ensure keytool can be found
    keytool = os.path.join(java_home, 'bin', 'keytool')
    if not os.path.isfile(keytool):
        msg = 'keytool file not found: {f}'.format(f=keytool)
        raise OSError(msg)

    # Find the cacerts file
    if keystore_path is None:
        keystore_path = os.path.join(java_home, 'lib', 'security', 'cacerts')

        # If the JRE cacerts location is not found, look for the JDK cacerts
        if not os.path .isfile(keystore_path):
            keystore_path = os.path.join(java_home, 'jre', 'lib', 'security', 'cacerts')
            if not os.path.isfile(keystore_path):
                msg = 'Unable to file cacerts file'
                raise OSError(msg)

    log.info('Checking keystore {k} for alias: {a}...'.format(k=keystore_path, a=alias))

    # Build the keytool command
    command = [keytool, '-keystore', keystore_path, '-storepass', keystore_password, '-list']

    # Running the keytool list command
    log.debug('Running the keytool list command...')
    try:
        result = run_command(command)
    except CommandError as exc:
        msg = 'There was a problem running keytool on keystore: {k}'.format(k=keystore_path)
        raise OSError(msg) from exc
    if result['code'] != 0:
        msg = 'keytool command exited with a non-zero code: {c}, and produced output: {o}'.format(
            c=result['code'], o=result['output'])
        raise OSError(msg)

    # Check for the alias in the output
    if alias in result['output']:
        log.info('Found alias {a} in keystore: {k}'.format(a=alias, k=keystore_path))
        return True
    else:
        log.info('Alias {a} was not found in keystore: {k}'.format(a=alias, k=keystore_path))
        return False


def add_root_ca(root_ca_path, alias, keystore_path=None, keystore_password='changeit'):
    """Adds a root CA to the specified Java keystore

    :param root_ca_path:
    :param alias:
    :param keystore_path:
    :param keystore_password:
    :return: None
    :raises: OSError, AliasImportError, AliasExistsError
    """
    log = logging.getLogger(mod_logger + '.add_root_ca')

    if not isinstance(root_ca_path, str):
        msg = 'root_ca_path arg must be a string'
        raise OSError(msg)
    if not isinstance(alias, str):
        msg = 'alias arg must be a string'
        raise OSError(msg)
    if not os.path.isfile(root_ca_path):
        msg = 'Root CA cert file not found: {f}'.format(f=root_ca_path)
        raise OSError(msg)

    # Ensure JAVA_HOME is set
    log.debug('Determining JAVA_HOME...')
    try:
        java_home = os.environ['JAVA_HOME']
    except KeyError:
        msg = 'JAVA_HOME is required but not set'
        raise OSError(msg)

    # Ensure keytool can be found
    keytool = os.path.join(java_home, 'bin', 'keytool')
    if not os.path.isfile(keytool):
        msg = 'keytool file not found: {f}'.format(f=keytool)
        raise OSError(msg)

    # Find the cacerts file
    if keystore_path is None:
        keystore_path = os.path.join(java_home, 'lib', 'security', 'cacerts')

        # If the JRE cacerts location is not found, look for the JDK cacerts
        if not os.path .isfile(keystore_path):
            keystore_path = os.path.join(java_home, 'jre', 'lib', 'security', 'cacerts')
            if not os.path.isfile(keystore_path):
                msg = 'Unable to file cacerts file'
                raise OSError(msg)

    log.info('Attempting to import alias [{a}] in keystore [{k}] from root ca file: {f}'.format(
        a=alias, k=keystore_path, f=root_ca_path))

    # Log a warning and return if the alias already exists
    if alias_exists(alias=alias, keystore_path=keystore_path, keystore_password=keystore_password):
        log.warning('Alias {a} already exists in keystore: {k}, not updating'.format(a=alias, k=keystore_path))
        return

    log.info('Updating cacerts file: {f}'.format(f=keystore_path))

    # Build the keytool import command
    command = [keytool, '-import', '-noprompt', '-storepass', keystore_password, '-trustcacerts', '-file',
               root_ca_path, '-alias', alias, '-keystore', keystore_path]

    # Running the keytool import
    log.debug('Running the keytool import...')
    try:
        result = run_command(command)
    except CommandError as exc:
        msg = 'Unable to find the import key: {k}'.format(k=keystore_path)
        raise OSError(msg) from exc
    if result['code'] != 0:

        if alias in result['output'] and 'already exists' in result['output']:
            raise AliasExistsError('Found alias [{a}] already existing in keystore: {k}\n{o}'.format(
                a=alias, k=keystore_path, o=result['output']
            ))

        msg = 'keytool command exited with a non-zero code: {c}, and produced output: {o}'.format(
            c=result['code'], o=result['output'])
        raise AliasImportError(msg)
    else:
        log.info('Successfully imported Root CA {c} with alias: {a}'.format(c=root_ca_path, a=alias))
