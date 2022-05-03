"""Module: network

This module provides networking utilities

"""
import logging
import socket

from .logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.network'


def get_ip_list_for_hostname_list(hostname_list):
    """Returns a list of IP addresses objects for a list of hostnames and a list of hostnames that failed

    Note, its possible for a hostname to return an IP and also end up on the failed list if more than one
    entries is returned, and one of the entries is not a valid IP address

    :param hostname_list: (list) of (str) hostnames to query
    :return: (tuple) list of IP addresses, and list of failed hostnames
    """
    log = logging.getLogger(mod_logger + '.get_ip_list_for_hostname_list')
    failed_hostname_list = []
    ip_address_list = []
    for hostname in hostname_list:
        hostname_ip_list = []
        try:
            _, _, hostname_ips = socket.gethostbyname_ex(hostname)
        except (socket.gaierror, socket.error, socket.herror) as exc:
            log.warning('Problem retrieving IP address for hostname: {r}\n{e}'.format(r=hostname, e=str(exc)))
            failed_hostname_list.append(hostname)
            continue
        if len(hostname_ips) < 1:
            log.warning('IP addresses returned for hostname: {h}'.format(h=hostname))
            failed_hostname_list.append(hostname)
            continue
        for hostname_ip in hostname_ips:
            if validate_ip_address(hostname_ip):
                log.info('Found IP address for hostname {h}: {i}'.format(h=hostname, i=hostname_ip))
                hostname_ip_list.append(hostname_ip)
            else:
                log.warning('Invalid IP address returned for hostname {h}: {i}'.format(h=hostname, i=hostname_ip))
                failed_hostname_list.append(hostname)
        ip_address_list.append({
            'hostname': hostname,
            'ip_addresses': hostname_ip_list
        })
    return ip_address_list, failed_hostname_list


def validate_ip_address(ip_address):
    """Validate the ip_address

    :param ip_address: (str) IP address
    :return: (bool) True if the ip_address is valid
    """
    # Validate the IP address
    log = logging.getLogger(mod_logger + '.validate_ip_address')
    if not isinstance(ip_address, str):
        log.warning('ip_address argument is not a string')
        return False

    # Ensure there are 3 dots
    num_dots = 0
    for c in ip_address:
        if c == '.':
            num_dots += 1
    if num_dots != 3:
        log.info('Not a valid IP address: {i}'.format(i=ip_address))
        return False

    # Use the socket module to test
    try:
        socket.inet_aton(ip_address)
    except socket.error as e:
        log.info('Not a valid IP address: {i}\n{e}'.format(i=ip_address, e=e))
        return False
    else:
        log.debug('Validated IP address: %s', ip_address)
        return True
