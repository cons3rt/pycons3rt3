#!/usr/bin/python

"""Module: aliasip

This module provides utilities for adding IP address aliases on Linux
and configuration the alias in AWS if needed.

"""
import logging
import os

from .aws_metadata import is_aws
from .bash import run_command, service_network_restart, validate_ip_address
from .ec2util import EC2Util
from .exceptions import EC2UtilError, CommandError, NetworkRestartError
from .logify import Logify

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.aliasip'


def alias_ip_address(ip_address, interface, aws=False):
    """Adds an IP alias to a specific interface

    Adds an ip address as an alias to the specified interface on
    Linux systems.

    :param ip_address: (str) IP address to set as an alias
    :param interface: (str) The interface number or full device name, if
        an int is provided assumes the device name is eth<i>
    :param aws (bool) True to perform additional AWS config
    :return: None
    """
    log = logging.getLogger(mod_logger + '.alias_ip_address')

    # Validate args
    if not isinstance(ip_address, str):
        raise TypeError('ip_address argument is not a string')

    # Validate the IP address
    if not validate_ip_address(ip_address):
        raise ValueError('The provided IP address arg is invalid: {i}'.format(i=ip_address))

    # Determine if the interface provided is a full device name
    try:
        int(interface)
    except ValueError:
        if isinstance(interface, str):
            device_name = str(interface)
            log.info('Full device name provided, will attempt to alias: {d}'.format(d=device_name))
        else:
            raise TypeError('Provided interface arg must be an int or str')
    else:
        device_name = 'eth{i}'.format(i=interface)
        log.info('Integer provided as interface, using device name: {d}'.format(d=device_name))

    # Add alias
    command = ['ifconfig', '{d}:0'.format(d=device_name), ip_address, 'up']
    log.info('Running command to bring up the alias: {c}'.format(c=' '.join(command)))
    try:
        result = run_command(command)
    except CommandError as exc:
        log.warning('CommandError: There was a problem running command: {c}\n{e}'.format(
            c=' '.join(command), e=str(exc)))
    else:
        log.info('Command produced output:\n{o}'.format(o=result['output']))
        if int(result['code']) != 0:
            log.warning('ifconfig up command produced exit code: {c} and output:\n{o}'.format(
                c=result['code'], o=result['output']))
        else:
            log.info('ifconfig up exited successfully')

    # Create interface file from the existing file
    base_ifcfg = os.path.abspath(os.path.join(os.sep, 'etc', 'sysconfig', 'network-scripts', 'ifcfg-{d}'.format(
            d=device_name)))
    alias_ifcfg = base_ifcfg + ':0'
    log.info('Creating interface config file: {f}'.format(f=alias_ifcfg))

    # Ensure the base config file exists
    if not os.path.isfile(base_ifcfg):
        raise OSError('Required interface config file not found: {f}'.format(f=base_ifcfg))
    else:
        log.info('Found base interface config file: {f}'.format(f=base_ifcfg))

    # Delete the existing interface file if it exists
    if os.path.isfile(alias_ifcfg):
        log.info('Alias interface configuration file already exists, removing: {f}'.format(f=alias_ifcfg))
        try:
            os.remove(alias_ifcfg)
        except OSError as exc:
            raise OSError('There was a problem removing existing alias config file: {f}'.format(
                f=alias_ifcfg)) from exc
    else:
        log.info('No existing alias interface configuration exists yet: {f}'.format(f=alias_ifcfg))

    # Create the interface file
    log.info('Gathering entries from file: {f}...'.format(f=base_ifcfg))
    ifcfg_entries = {}
    try:
        with open(base_ifcfg, 'r') as f:
            for line in f:
                if '=' in line:
                    parts = line.split('=')
                    if len(parts) == 2:
                        parts[0] = parts[0].strip()
                        parts[1] = parts[1].strip()  # Removed translate(None, '"') from this
                        ifcfg_entries[parts[0]] = parts[1]
    except(IOError, OSError) as exc:
        raise OSError('Unable to read file: {f}'.format(f=base_ifcfg)) from exc

    # Defined the ifcfg file entries for the alias
    ifcfg_entries['IPADDR'] = ip_address
    ifcfg_entries['NETMASK'] = '255.255.255.0'
    ifcfg_entries['DEVICE'] = '{d}:0'.format(d=device_name)
    ifcfg_entries['NAME'] = '{d}:0'.format(d=device_name)

    log.info('Creating file: {f}'.format(f=alias_ifcfg))
    try:
        with open(alias_ifcfg, 'a') as f:
            for var, val in ifcfg_entries.items():
                out_str = str(var) + '="' + str(val) + '"\n'
                log.info('Adding entry to %s: %s', alias_ifcfg, out_str)
                f.write(out_str)
    except(IOError, OSError) as exc:
        raise OSError('Unable to write to file: {f}'.format(f=alias_ifcfg)) from exc

    # Performing additional configuration for AWS
    if aws:
        log.info('Checking if this host is actually on AWS...')
        if is_aws():
            log.info('Performing additional configuration for AWS...')
            try:
                ec2 = EC2Util()
                ec2.add_secondary_ip(ip_address, interface)
            except EC2UtilError as exc:
                raise OSError('Unable to instruct AWS to add a secondary IP address <{ip}> on interface <{d}>'.format(
                    ip=ip_address, d=device_name)) from exc
            else:
                log.info('AWS added the secondary IP address <{ip}> on interface <{d}>'.format(
                    ip=ip_address, d=device_name))
        else:
            log.warning('This system is not on AWS, not performing additional configuration')

    log.info('Restarting networking to ensure the changes take effect...')
    try:
        service_network_restart()
    except CommandError as exc:
        raise NetworkRestartError('There was a problem restarting network services') from exc

    # Verify the alias was created
    log.info('Verifying the alias was successfully created...')
    command = ['/sbin/ifconfig']
    try:
        result = run_command(command)
    except CommandError as exc:
        log.warning('CommandError: Unable to run ifconfig to verify the IP alias was created\n{e}'.format(e=str(exc)))
        return

    # Check for the alias
    if '{d}:0'.format(d=device_name) not in result['output']:
        log.warning('The alias was not created yet, system reboot may be required: {d}:0'.format(d=device_name))
    else:
        log.info('Alias created successfully!')


def set_source_ip_for_interface(source_ip_address, desired_source_ip_address, device_num=0):
    """Configures the source IP address for a Linux interface

    :param source_ip_address: (str) Source IP address to change
    :param desired_source_ip_address: (str) IP address to configure as the source in outgoing packets
    :param device_num: (int) Integer interface device number to configure
    :return: None
    :raises: TypeError, ValueError, OSError
    """
    log = logging.getLogger(mod_logger + '.set_source_ip_for_interface')
    if not isinstance(source_ip_address, str):
        raise TypeError('arg source_ip_address must be a string')
    if not isinstance(desired_source_ip_address, str):
        raise TypeError('arg desired_source_ip_address must be a string')
    if not validate_ip_address(ip_address=source_ip_address):
        raise ValueError(
            'The arg source_ip_address was found to be an invalid IP address.  Please pass a valid IP address')
    if not validate_ip_address(ip_address=desired_source_ip_address):
        raise ValueError(
            'The arg desired_source_ip_address was found to be an invalid IP address.  Please pass a valid IP address')

    # Determine the device name based on the device_num
    log.debug('Attempting to determine the device name based on the device_num arg...')
    try:
        int(device_num)
    except ValueError:
        if isinstance(device_num, str):
            device_name = device_num
            log.info('Provided device_num is not an int, assuming it is the full device name: {d}'.format(
                d=device_name))
        else:
            raise TypeError('device_num arg must be a string or int')
    else:
        device_name = 'eth{n}'.format(n=str(device_num))
        log.info('Provided device_num is an int, assuming device name is: {d}'.format(d=device_name))

    # Build the command
    # iptables -t nat -I POSTROUTING -o eth0 -s ${RA_ORIGINAL_IP} -j SNAT --to-source

    command = ['iptables', '-t', 'nat', '-I', 'POSTROUTING', '-o', device_name, '-s',
               source_ip_address, '-j', 'SNAT', '--to-source', desired_source_ip_address]
    log.info('Running command: {c}'.format(c=command))
    try:
        result = run_command(command, timeout_sec=20)
    except CommandError as exc:
        raise OSError('There was a problem running iptables command: {c}'.format(c=' '.join(command))) from exc

    if int(result['code']) != 0:
        raise OSError('The iptables command produced an error with exit code: {c}, and output:\n{o}'.format(
            c=result['code'], o=result['output']))
    log.info('Successfully configured the source IP for {d} to be: {i}'.format(
        d=device_name, i=desired_source_ip_address))


def main():
    """Sample usage for this python module

    This main method simply illustrates sample usage for this python
    module.

    :return: None
    """
    log = logging.getLogger(mod_logger + '.main')
    log.info('Main!')


if __name__ == '__main__':
    main()
