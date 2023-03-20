#!/usr/bin/env python3

"""Module: azure_metadata

This module provides utilities for interacting with the Azure
metadata service.

"""
import json
import logging
import time

import requests

from .logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.azure_metadata'

# Azure Meta Data Service URL
metadata_url = 'http://169.254.169.254/metadata/instance?api-version=2017-08-01&format=json'

# Required Headers
headers = {
    'Metadata': 'true'
}

# Number of seconds to timeout after, Azure should return quickly
query_timeout_sec = 5

# Number of seconds to retry the query
retry_time_sec = 3

# number of re-tries before giving up
max_num_tries = 3

# Character encoding
character_encoding = 'utf-8'


def get_azure_instance_metadata():
    """Retrieves and returns the Azure instance metadata along with a boolean

    :return: (tuple):
        bool -- True if this instance is on Azure, False otherwise
        dict -- Containing Azure instance metadata
    """
    log = logging.getLogger(mod_logger + '.get_azure_instance_metadata')
    log.info('Querying Azure meta data URL to determine if this system is on Azure: {u}'.format(u=metadata_url))

    # Re-try logic for checking the AWS metadata URL
    attempt_num = 1

    while True:
        if attempt_num > max_num_tries:
            log.info('Unable to query the Azure meta data URL, this system appears to be not running on Azure')
            return False, None

        # Query the AWS metadata URL
        try:
            response = requests.get(metadata_url, headers=headers, timeout=query_timeout_sec)
        except(IOError, OSError) as ex:
            log.info('Error querying the Azure meta data URL: {u}\n{e}'.format(u=metadata_url, e=str(ex)))
            attempt_num += 1
            time.sleep(retry_time_sec)
            continue
        except requests.exceptions.ConnectTimeout as ex:
            log.info('Timeout after [{t}] seconds on query the Azure meta data URL: {u}\n{e}'.format(
                t=str(query_timeout_sec), u=metadata_url, e=str(ex)))
            attempt_num += 1
            time.sleep(retry_time_sec)
            continue

        # Check the code
        if response.status_code == 200:
            log.info('AWS metadata service returned code 200, this system is running on Azure')
            decoded_content = response.content.decode(character_encoding)
            try:
                instance_metadata = json.loads(decoded_content)
            except json.JSONDecodeError as exc:
                log.warning('Problem loading response into JSON: {d}\n{e}'.format(d=decoded_content, e=str(exc)))
                continue
            return True, instance_metadata
        else:
            log.warning('Azure metadata service returned error code: {c}'.format(c=str(response.status_code)))
            attempt_num += 1
            time.sleep(retry_time_sec)
            continue


def get_azure_location():
    """Gets the Azure location/region for this system

    :return: (str) Azure location name where this system lives
    """
    log = logging.getLogger(mod_logger + '.get_location')
    log.info('Attempting to determine the Azure VM location from instance metadata...')
    is_azure_vm, instance_metadata = get_azure_instance_metadata()
    if is_azure_vm and instance_metadata:
        if 'compute' in instance_metadata.keys():
            if 'location' in instance_metadata['compute'].keys():
                return instance_metadata['compute']['location']
        log.info('This VM is on Azure, but location data was not found')
    else:
        log.info('This VM is not on Azure')
    return None


def get_azure_region():
    return get_azure_location()


def is_azure():
    """Determines if this system is on Azure

    :return: bool True if this system is running on Azure, False otherwise
    """
    is_azure_vm, _ = get_azure_instance_metadata()
    return is_azure_vm


def get_mac_address_for_ip_address(desired_ip_address):
    """Determines the MAC address for the provided IP address by querying the Azure
    metadata service

    :return: (str) MAC address for the eth0 interface, or None
    """
    log = logging.getLogger(mod_logger + '.get_mac_address_for_ip_address')
    log.info('Attempting to determine the MAC address matching IP: {i}...'.format(i=desired_ip_address))
    is_azure_vm, instance_metadata = get_azure_instance_metadata()
    if is_azure_vm and instance_metadata:
        if 'network' in instance_metadata.keys():
            if 'interface' in instance_metadata['network'].keys():
                if isinstance(instance_metadata['network']['interface'], list):
                    for interface in instance_metadata['network']['interface']:
                        if 'ipv4' in interface.keys():
                            if 'ipAddress' in interface['ipv4'].keys():
                                if isinstance(interface['ipv4']['ipAddress'], list):
                                    for ip_address in interface['ipv4']['ipAddress']:
                                        if 'privateIpAddress' in ip_address.keys():
                                            if ip_address['privateIpAddress'] == desired_ip_address:
                                                if 'macAddress' in interface.keys():
                                                    log.info('MAC address found for IP address [{i}]: {m}'.format(
                                                        i=desired_ip_address, m=interface['macAddress']
                                                    ))
                                                    return interface['macAddress']
        log.info('This VM is on Azure, but the MAC address for IP [{i}] was not found'.format(i=desired_ip_address))
    else:
        log.info('This VM is not on Azure')
    return None


def get_region():
    return get_azure_location()


def get_azure_vm_id():
    """Returns the Azure instance VM ID from metadata

    :return: (str) Azure VM ID, or None
    """
    log = logging.getLogger(mod_logger + '.get_azure_vm_id')
    log.info('Attempting to get the Azure VM ID from instance metadata...')
    is_azure_vm, instance_metadata = get_azure_instance_metadata()
    if is_azure_vm and instance_metadata:
        if 'compute' in instance_metadata.keys():
            if 'vmId' in instance_metadata['compute'].keys():
                log.info('Found Azure VM ID: {i}'.format(i=instance_metadata['compute']['vmId']))
                return instance_metadata['compute']['vmId']
        log.info('This VM is on Azure, but vmId data was not found')
    else:
        log.info('This VM is not on Azure')
    return None


def get_azure_vm_size():
    """Returns the Azure instance VM size from metadata

    :return: (str) Azure VM size, or None
    """
    log = logging.getLogger(mod_logger + '.get_azure_vm_size')
    log.info('Attempting to get the Azure VM size from instance metadata...')
    is_azure_vm, instance_metadata = get_azure_instance_metadata()
    if is_azure_vm and instance_metadata:
        if 'compute' in instance_metadata.keys():
            if 'vmSize' in instance_metadata['compute'].keys():
                log.info('Found Azure VM size: {i}'.format(i=instance_metadata['compute']['vmSize']))
                return instance_metadata['compute']['vmSize']
        log.info('This VM is on Azure, but vmSize data was not found')
    else:
        log.info('This VM is not on Azure')
    return None
