"""Module: azcomputeutil

This module provides utilities for interacting with the Azure
Compute API.

"""
import logging
import os

from azure.identity import AzureAuthorityHosts, DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.resource import SubscriptionClient

from .exceptions import AzAPIError
from .logify import Logify


__author__ = 'Joe Yennaco'

# Set up logger name for this module
mod_logger = Logify.get_name() + '.azcomputeutil'


def connect():
    """Connect to the Azure compute API using default credentials scheme

    :return: (ComputeManagementClient) Azure compute client
    :raises: OSError
    """
    log = logging.getLogger(mod_logger + '.connect')

    # Get the Azure environment
    az_auth_host, az_management_endpoint = get_azure_environment()

    # Get the Azure subscription ID if set
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID")

    # Ensure the subscription ID was provided
    if not subscription_id:
        raise OSError('AZURE_SUBSCRIPTION_ID environment variable is required but not set')
    log.info('Loaded AZURE_SUBSCRIPTION_ID: [{s}]'.format(s=subscription_id))

    # Use DefaultAzureCredential to authenticate
    credential = DefaultAzureCredential(authority=az_auth_host)

    # Initialize the Compute Management client
    compute_client = ComputeManagementClient(
        credential, 
        subscription_id,
        base_url=az_management_endpoint
    )
    return compute_client


def get_azure_environment():
    """Given the azure cloud/environment, return the auth authority and management endpoint

    :return: (tuple) AzureAuthorityHost, string endpoint URL
    :raises: OSError
    """
    log = logging.getLogger(mod_logger + '.get_azure_environment')

    # Info for configuring Azure Environment based on the AZURE_AUTHORITY_HOST
    # environment variable.  Only cointains supported regions.
    az_authority_host_endpoint_map = {
        AzureAuthorityHosts.AZURE_PUBLIC_CLOUD: 'https://management.azure.com/',
        AzureAuthorityHosts.AZURE_GOVERNMENT: 'https://management.usgovcloudapi.net'
    }

    # Map the AZURE_ENVIRONMENT to AZURE_AUTHORITY_HOST endpoint
    # AZURE_PUBLIC_CLOUD, AZURE_CHINA_CLOUD, AZURE_US_GOVERNMEN
    az_environment_authority_host_map = {
        'AZURE_PUBLIC_CLOUD': AzureAuthorityHosts.AZURE_PUBLIC_CLOUD,
        'AZURE_US_GOVERNMENT': AzureAuthorityHosts.AZURE_GOVERNMENT
    }

    # Check for the AZURE_ENVIRONMENT/AZURE_CLOUD environment variables (these are interchangable)
    az_environment = os.environ.get('AZURE_ENVIRONMENT')
    if not az_environment:
        az_environment = os.environ.get('AZURE_CLOUD')
    if az_environment:
        if az_environment not in az_environment_authority_host_map.keys():
            raise OSError('Invalid AZURE_ENVIRONMENT or AZURE_CLOUD environment variable, must be' \
            'one of: [{v}]'.format(v=','.join(az_environment_authority_host_map.keys())))
        log.info('Loaded AZURE_ENVIRONMENT/AZURE_CLOUD: [{e}]'.format(e=az_environment))

    # Check for the AZURE_AUTHORITY_HOST environment variable
    az_auth_host = os.environ.get('AZURE_AUTHORITY_HOST')
    if az_auth_host:
        if az_environment not in az_environment_authority_host_map.keys():
            raise OSError('Invalid AZURE_ENVIRONMENT or AZURE_CLOUD environment variable, must be' \
            'one of: [{v}]'.format(v=','.join(az_environment_authority_host_map.keys())))
        log.info('Loaded AZURE_AUTHORITY_HOST: [{e}]'.format(e=az_auth_host))
    
    # Return the environment based on the configured environment vars
    if az_auth_host:
        return az_auth_host, az_authority_host_endpoint_map[az_auth_host]
    elif az_environment:
        az_auth_host = az_environment_authority_host_map[az_environment]
        return az_auth_host, az_authority_host_endpoint_map[az_auth_host]
    else:
        raise OSError('One of these environment variables must be set: AZURE_CLOUD, AZURE_ENVIRONMENT, ' \
        'or AZURE_AUTHORITY_HOST')


def get_image_details(compute_client, location, publisher, offer, sku, version):
    """Returns details for an image given the provided params

    :param: (ComputeManagementClient) Azure compute client
    :param: (str) location
    :param: (str) publisher 
    :param: (str) offer
    :param: (str) sku
    :param: (str) version
    :return: Azure image object
    """
    log = logging.getLogger(mod_logger + '.get_image_skus')

    log.info('Querying image for publisher [{p}], offer [{o}], sku [{s}], version [{v}] in location [{r}]...'.format(
        p=publisher, o=offer, s=sku, v=version, r=location))
    
    # Get image version details
    image = compute_client.virtual_machine_images.get(
        location=location,
        publisher_name=publisher,
        offer=offer,
        skus=sku,
        version=version
    )

    # Print the image details
    log.debug('Found image details: [{d}]'.format(d=image.as_dict()))
    return image


def get_image_skus(compute_client, location, publisher, offer):
    """Returns a list of image skus based on the provided params
    
    :param: (ComputeManagementClient) Azure compute client
    :param: (str) location
    :param: (str) publisher 
    :param: (str) offer
    :return: (list) Azure image skus
    """
    log = logging.getLogger(mod_logger + '.get_image_skus')

    log.info('Querying SKUs for publisher [{p}], offer [{o}], in location [{r}]...'.format(
        p=publisher, o=offer, r=location))

    # Query for a list of skus for the publisher/offer
    skus = compute_client.virtual_machine_images.list_skus(
        location=location,
        publisher_name=publisher,
        offer=offer
    )

    # DEBUG print the list of skus
    for sku in skus:
        log.debug('Found image sku: [{s}]'.format(s=sku.name))
    return skus


def get_images(compute_client, location, publisher, offer, sku):
    """Returns a list of images based on the provided params
    
    :param: (ComputeManagementClient) Azure compute client
    :param: (str) location
    :param: (str) publisher 
    :param: (str) offer
    :param: (str) sku
    :return: (list) Azure images
    """
    log = logging.getLogger(mod_logger + '.get_images')

    log.info('Querying images for publisher [{p}], offer [{o}], sku [{s}], in location [{r}]...'.format(
        p=publisher, o=offer, s=sku, r=location))
    
    # Query for a list of skus for the publisher/offer/sku
    images = compute_client.virtual_machine_images.list(
        location, 
        publisher, 
        offer, 
        sku
    )
    return images


def get_subscription_locations():
    """Get subcription locations

    :return: (list) of location strings
    """
    log = logging.getLogger(mod_logger + '.get_subscription_locations')

    # Get the Azure environment
    az_auth_host, _ = get_azure_environment()

    # Get the Azure subscription ID if set
    subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID")

    # Ensure the subscription ID was provided
    if not subscription_id:
        raise OSError('AZURE_SUBSCRIPTION_ID environment variable is required but not set')
    log.info('Loaded AZURE_SUBSCRIPTION_ID: [{s}]'.format(s=subscription_id))

    # Use DefaultAzureCredential to authenticate
    credential = DefaultAzureCredential(authority=az_auth_host)
    
    # Initialize the subscription client
    subscription_client = SubscriptionClient(credential)

    # List all locations for the subscription
    locations = subscription_client.subscriptions.list_locations(subscription_id)

    # Print location names
    location_names = []
    for location in locations:
        log.info('Found location for subscription ID [{s}]: [{r}]'.format(s=subscription_id, r=location.name))
        location_names.append(location.name)
    return location_names


def print_image_sku_list(item_list):
    """Given a list of images or skus, print them in an orderly wau

    :param: (list) of Sku objects
    :return: None
    :raises: None
    """
    item_str = '\t'
    new_line_count = 0
    for sku in item_list:
        new_line_count += 1
        item_str += sku.name
        if new_line_count == 4:
            item_str += '\n\t'
            new_line_count = 0
        else:
            item_str += '\t\t'
    print(item_str)
