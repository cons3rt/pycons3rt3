#!/usr/bin/env python3

"""Module: windows

This module provides utilities for performing typical actions on
Windows machines

"""
import logging
import os
import fileinput
import re
import sys

from .logify import Logify
from .exceptions import Pycons3rtWindowsCommandError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.windows'


def update_hosts_file(ip, entry):
    """Updates the hosts file for the specified ip

    This method updates the hosts file for the specified IP
    address with the specified entry.

    :param ip: (str) IP address to be added or updated
    :param entry: (str) Hosts file entry to be added
    :return: None
    :raises CommandError
    """
    log = logging.getLogger(mod_logger + '.update_hosts_file')

    # Validate args
    if not isinstance(ip, str):
        msg = 'ip argument must be a string'
        raise Pycons3rtWindowsCommandError(msg)
    if not isinstance(entry, str):
        msg = 'entry argument must be a string'
        raise Pycons3rtWindowsCommandError(msg)

    # Ensure the file_path file exists
    # C:\Windows\System32\drivers\etc
    hosts_file = os.path.join('C:', os.sep, 'Windows', 'System32', 'drivers', 'etc', 'hosts')
    if not os.path.isfile(hosts_file):
        msg = 'File not found: {f}'.format(f=hosts_file)
        raise Pycons3rtWindowsCommandError(msg)

    # Updating /etc/hosts file
    log.info('Updating hosts file: {f} with IP {i} and entry: {e}'.format(f=hosts_file, i=ip, e=entry))
    full_entry = ip + ' ' + entry.strip() + '\n'
    updated = False
    for line in fileinput.input(hosts_file, inplace=True):
        if re.search(ip, line):
            if line.split()[0] == ip:
                log.info('Found IP {i} in line: {li}, updating...'.format(i=ip, li=line))
                log.info('Replacing with new line: {n}'.format(n=full_entry))
                sys.stdout.write(full_entry)
                updated = True
            else:
                log.debug('Found ip {i} in line {li} but not an exact match, adding line back to hosts file {f}...'.
                          format(i=ip, li=line, f=hosts_file))
                sys.stdout.write(line)
        else:
            log.debug('IP address {i} not found in line, adding line back to hosts file {f}: {li}'.format(
                i=ip, li=line, f=hosts_file))
            sys.stdout.write(line)

    # Append the entry if the hosts file was not updated
    if updated is False:
        with open(hosts_file, 'a') as f:
            log.info('Appending hosts file entry to {f}: {e}'.format(f=hosts_file, e=full_entry))
            f.write(full_entry)
