#!/usr/bin/env python3

"""Module: windows

This module provides utilities for performing typical actions on
Windows machines

"""
import os

from .bash import update_hosts_file_content
from .logify import Logify

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
    # C:\Windows\System32\drivers\etc
    windows_hosts_file = os.path.join('C:', os.sep, 'Windows', 'System32', 'drivers', 'etc', 'hosts')
    update_hosts_file_content(hosts_file_path=windows_hosts_file, ip=ip, entry=entry)
