"""Module: azcomputeutil

This module provides utilities for interacting with the Azure
Compute API.

"""
import logging
import os

from azure.identity import AzureAuthorityHosts, AzureCliCredential, DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.resource import SubscriptionClient

from .exceptions import AzAPIError
from .logify import Logify


__author__ = 'Joe Yennaco'

# Set up logger name for this module
mod_logger = Logify.get_name() + '.azcomputeutil'


class AzureEnvironment:
    """
    Singleton class representing the Azure environment configuration.
    Only one instance may ever exist.
    """
    _instance = None
    _initialized = False

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(AzureEnvironment, cls).__new__(cls)
        return cls._instance

    def __init__(self, authority_host=None, management_endpoint=None):
        # Prevent re-initialization when __init__ is called again on the singleton
        if AzureEnvironment._initialized:
            print('Loaded: ' + self.__repr__())
            return

        self.cls_logger = mod_logger + '.AzureEnvironment'
        self.authority_host = authority_host
        self.management_endpoint = management_endpoint
        self.__initialize__()

        AzureEnvironment._initialized = True

    def __repr__(self):
        return (
            f"AzureEnvironment(authority_host={self.authority_host!r}, "
            f"management_endpoint={self.management_endpoint!r})"
        )
    
    def __initialize__(self):
        """Given the azure cloud/environment, return the auth authority and management endpoint

        :return: (tuple) AzureAuthorityHost, string endpoint URL
        :raises: OSError
        """
        log = logging.getLogger(self.cls_logger + '.__initialize__')

        if self.authority_host and self.management_endpoint:
            log.info('AzureEnvironment already initialized with authority_host and management_endpoint.')
            return

        # Info for configuring Azure Environment based on the AZURE_AUTHORITY_HOST
        # environment variable.  Only contains supported regions.
        az_authority_host_endpoint_map = {
            AzureAuthorityHosts.AZURE_PUBLIC_CLOUD: 'https://management.azure.com/',
            AzureAuthorityHosts.AZURE_GOVERNMENT: 'https://management.usgovcloudapi.net'
        }

        # Map the AZURE_ENVIRONMENT to AZURE_AUTHORITY_HOST endpoint
        # AZURE_PUBLIC_CLOUD, AZURE_CHINA_CLOUD, AZURE_US_GOVERNMENT
        az_environment_authority_host_map = {
            'AZURE_PUBLIC_CLOUD': AzureAuthorityHosts.AZURE_PUBLIC_CLOUD,
            'AZURE_US_GOVERNMENT': AzureAuthorityHosts.AZURE_GOVERNMENT,
            'AzurePublic': AzureAuthorityHosts.AZURE_PUBLIC_CLOUD,
            'AzureUSGovernment': AzureAuthorityHosts.AZURE_GOVERNMENT
        }

        # Check for the AZURE_AUTHORITY_HOST and AZURE_ENVIRONMENT environment variables
        az_auth_host = os.environ.get('AZURE_AUTHORITY_HOST')
        az_environment = os.environ.get('AZURE_ENVIRONMENT')

        if az_auth_host:
            if az_auth_host not in az_authority_host_endpoint_map.keys():
                msg = 'Invalid AZURE_AUTHORITY_HOST environment variable, must be '
                msg += 'one of: [{v}]'.format(v=','.join(az_authority_host_endpoint_map.keys()))
                raise OSError(msg)
            if AzureAuthorityHosts.AZURE_PUBLIC_CLOUD in az_auth_host:
                az_auth_host = AzureAuthorityHosts.AZURE_PUBLIC_CLOUD
            elif AzureAuthorityHosts.AZURE_GOVERNMENT in az_auth_host:
                az_auth_host = AzureAuthorityHosts.AZURE_GOVERNMENT
            log.info('Loaded AZURE_AUTHORITY_HOST: [{e}]'.format(e=az_auth_host))
        elif az_environment:
            # AZURE_AUTHORITY_HOST is not set, check for the AZURE_ENVIRONMENT environment variable
            if az_environment not in az_environment_authority_host_map.keys():
                msg = 'Invalid AZURE_ENVIRONMENT environment variable, must be '
                msg += 'one of: [{v}]'.format(v=','.join(az_environment_authority_host_map.keys()))
                raise OSError(msg)
            log.info('Loaded AZURE_ENVIRONMENT: [{e}]'.format(e=az_environment))
            az_auth_host = az_environment_authority_host_map[az_environment]
            log.info('Using AZURE_AUTHORITY_HOST: [{e}]'.format(e=az_auth_host))
        else:
            # Ask the user
            az_env_options = {
                '1': AzureAuthorityHosts.AZURE_PUBLIC_CLOUD,
                '2': AzureAuthorityHosts.AZURE_GOVERNMENT
            }

            print('Select the Azure Environment:')
            print('\t1) Azure Public Cloud')
            print('\t2) Azure US Government')

            while True:
                selection = input('Enter selection [1-2]: ')
                if selection in az_env_options.keys():
                    az_auth_host = az_env_options[selection]
                    log.info('User selected Azure environment: [{e}]'.format(e=az_auth_host))
                    break
                else:
                    print('Invalid selection, please try again.')
        
        # Get the endpoint for the authority host
        endpoint = az_authority_host_endpoint_map[az_auth_host]
        log.info('Loaded auth host [{h}] and endpoint [{e}]'.format(h=az_auth_host, e=endpoint))
        
        # Return the environment based on the configured environment vars
        self.authority_host = az_auth_host
        self.management_endpoint = endpoint
    
    def get_scopes(self):
        """Get the scopes for the Azure environment

        :return: (list) of scopes
        :raises: OSError
        """
        log = logging.getLogger(self.cls_logger + '.get_scopes')

        # The scope is the management endpoint with '/.default' appended
        scope = self.management_endpoint.rstrip('/') + '/.default'
        log.info('Using scope: [{s}]'.format(s=scope))
        return [scope]
    
    def get_subscription_from_env(self):
        """Get subscription ID from environment variable

        :return: (str) subscription ID
        :raises: OSError
        """
        log = logging.getLogger(self.cls_logger + '.get_subscription_from_env')

        # Get the Azure subscription ID if set
        subscription_id = os.environ.get("AZURE_SUBSCRIPTION_ID")

        # Ensure the subscription ID was provided
        if subscription_id:
            log.info('Loaded AZURE_SUBSCRIPTION_ID: [{s}]'.format(s=subscription_id))
        else:
            log.info('AZURE_SUBSCRIPTION_ID environment variable is not set.')
        return subscription_id


def connect():
    """Connect to the Azure compute API using default credentials scheme

    :return: (ComputeManagementClient) Azure compute client
    :raises: OSError
    """
    log = logging.getLogger(mod_logger + '.connect')

    # Get the Azure environment
    az_env = AzureEnvironment()

    # Get the Azure subscription ID if set
    subscription_id = az_env.get_subscription_from_env()

    # Ensure the subscription ID was provided
    if not subscription_id:
        raise OSError('AZURE_SUBSCRIPTION_ID environment variable is required but not set')
    log.info('Loaded AZURE_SUBSCRIPTION_ID: [{s}]'.format(s=subscription_id))

    # Use DefaultAzureCredential to authenticate
    credential = DefaultAzureCredential(authority=az_env.authority_host)

    # Initialize the Compute Management client
    log.info('Connecting to Azure Compute API AZ auth host [{h}] at endpoint [{e}] and subscription ID [{s}]...'.format(
        h=az_env.authority_host, e=az_env.management_endpoint, s=subscription_id))
    compute_client = ComputeManagementClient(
        credential, 
        subscription_id,
        base_url=az_env.management_endpoint,
        credential_scopes=az_env.get_scopes(),
    )
    return compute_client


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
    """Get subscription locations

    :return: (list) of location strings
    """
    log = logging.getLogger(mod_logger + '.get_subscription_locations')

    log.info('Getting subscription available locations...')

    # Get the Azure environment
    az_env = AzureEnvironment()

    # Get the Azure subscription ID if set
    subscription_id = az_env.get_subscription_from_env()

    # Ensure the subscription ID was provided
    if not subscription_id:
        raise OSError('AZURE_SUBSCRIPTION_ID environment variable is required but not set')
    log.info('Loaded AZURE_SUBSCRIPTION_ID: [{s}]'.format(s=subscription_id))

    # Use DefaultAzureCredential to authenticate
    credential = DefaultAzureCredential(authority=az_env.authority_host)
    
    # Initialize the subscription client
    subscription_client = SubscriptionClient(
        credential,
        base_url=az_env.management_endpoint,
        credential_scopes=az_env.get_scopes(),
    )

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
