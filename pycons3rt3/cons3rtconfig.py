#!/usr/bin/env python
"""
Sets up the config.json file
"""

import os
import json
import logging
import shutil

from .bash import mkdir_p
from .exceptions import Cons3rtConfigError
from .logify import Logify
from .osutil import get_pycons3rt_conf_dir

# Set up logger name for this module
mod_logger = Logify.get_name() + '.cons3rtconfig'

# List of site URLs
site_urls = {
    'arcusgov': 'https://app.arcus-cloud.io/rest/api/',
    'arcusmil': 'https://app.arcus.mil/rest/api/',
    'ci': 'https://api.ci.cons3rt.io/rest/api/',
    'ci2': 'https://api.ci2.cons3rt.io/rest/api/',
    'cons3rt.com': 'https://api.cons3rt.com/rest/api/',
    'dev': 'https://api.dev.cons3rt.io/rest/api/',
    'dev2': 'https://api.dev2.cons3rt.io/rest/api/',
    'int': 'https://api.int.cons3rt.io/rest/api/',
    'open': 'https://api.open.cons3rt.io/rest/api/',
    'qa': 'https://api.qa.cons3rt.io/rest/api/',
    'qa2': 'https://api.qa2.cons3rt.io/rest/api/',
    'qa3': 'https://api.qa3.cons3rt.io/rest/api/'
}

# The default site selection
default_api_url = site_urls['arcusgov']

# List of sites that require certificate-based auth
cert_auth_sites = [
    site_urls['arcusgov'],
    site_urls['arcusmil'],
    site_urls['qa2']
]

# String representation of the list of sites
site_url_list_str = ', '.join(site_urls.keys())

# cons3rtapi config directory
cons3rtapi_config_dir = get_pycons3rt_conf_dir()

# cons3rtapi config file
cons3rtapi_config_file = os.path.join(cons3rtapi_config_dir, 'config.json')


def write_config(config_data):
    """Outputs the cons3rt config to the cons3rt config dir

    :param config_data: (dict)
    :return: None
    """
    if not os.path.isdir(cons3rtapi_config_dir):
        os.makedirs(cons3rtapi_config_dir)
        print('Created your cons3rt config directory: {d}'.format(d=cons3rtapi_config_dir))

    json.dump(config_data, open(cons3rtapi_config_file, 'w'), sort_keys=True, indent=2, separators=(',', ': '))


def manual_config():
    """Manually configures your CONS3RT API

    :return: None
    """
    print('Welcome to CONS3RT!\nLet\'s set up your CONS3RT API...')

    cons3rt_config = {}

    # Get the API URL
    site_selection_input = input('Enter the CONS3RT site ({v}) (default: arcusgov): '.format(v=site_url_list_str))

    if site_selection_input:
        site_selection = site_selection_input.strip()

        if site_selection not in site_urls.keys():
            print('ERROR: Invalid site selection [{s}], valid sites are: {v}'.format(
                s=site_selection, v=site_url_list_str))
            return 1

        cons3rt_config['api_url'] = site_urls[site_selection]
    else:
        cons3rt_config['api_url'] = default_api_url

    # Get cert or username
    if cons3rt_config['api_url'] in cert_auth_sites:
        cert_path_input = input('Enter full path to your client certificate file (pem format): ')

        if not cert_path_input:
            print('ERROR: Client certificate required in PEM format to access API: [{u}]'.format(
                u=cons3rt_config['api_url']))
            return 1

        cons3rt_config['cert'] = cert_path_input.strip()

        if not os.path.isfile(cons3rt_config['cert']):
            print('ERROR: Your client certificate was not found: {c}'.format(c=cons3rt_config['cert']))
            return 1
    else:
        username_input = input('CONS3RT username: ')

        if not username_input:
            print('ERROR: CONS3RT username is required.  You can find username on your account page.')
            return 1

        cons3rt_config['name'] = username_input.strip()

    # Collect root CA cert bundle path if needed
    root_ca_certs_input = input('If a root CA certificate if needed, enter full path to the file in pem format '
                                '(press enter to skip: ')
    if root_ca_certs_input:
        if not os.path.isfile(root_ca_certs_input):
            print('ERROR: Your root CA certificate bundle was not found: {c}'.format(c=root_ca_certs_input))
            return 1
        else:
            cons3rt_config['root_ca_bundle'] = root_ca_certs_input

    # Get the Project
    project_input = input('Enter your CONS3RT project name: ')

    if not project_input:
        print('ERROR: CONS3RT project name is required.  You can find this on your "My Project" page.')
        return 1

    project_name = project_input.strip()
    cons3rt_config['projects'] = [
        {
            'name': project_name
        }
    ]

    # Get the API key
    print('++++++++++++++++++++++++')
    print('You can generate a ReST API key for your project from your account/security page.')
    print('Note: The ReST API key must be associated to your project: [{p}]'.format(p=project_name))
    print('++++++++++++++++++++++++')
    rest_key_input = input('Enter your project ReST API key: ')

    if not rest_key_input:
        print('ERROR: ReST API key is required.  You can find this on your account/security page.')
        return 1

    cons3rt_config['projects'][0]['rest_key'] = rest_key_input.strip()
    write_config(config_data=cons3rt_config)
    print('Congrats! Your CONS3RT API configuration is complete!')
    return 0


def asset_config(config_file_path, cert_file_path=None):
    """Configure pycons3rt3 using a config file and optional cert from the
    ASSET_DIR/media directory

    :param: cert_file_path (str) name of the certificate pem file in the media directory
    :param: config_file_path (str) name of the config file
    :return: None
    """
    log = logging.getLogger(mod_logger + '.asset_config')

    # Create the config directory
    log.info('Creating directory: {d}'.format(d=cons3rtapi_config_dir))
    mkdir_p(cons3rtapi_config_dir)

    # Ensure the config file exists
    if not os.path.isfile(config_file_path):
        raise Cons3rtConfigError('Config file not found: {f}'.format(f=config_file_path))

    # Remove existing config file if it exists
    config_file_dest = os.path.join(cons3rtapi_config_dir, 'config.json')
    if os.path.isfile(config_file_dest):
        log.info('Removing existing config file: {f}'.format(f=config_file_dest))
        os.remove(config_file_dest)

    # Copy files to the config dir
    log.info('Copying config file to directory: {d}'.format(d=cons3rtapi_config_dir))
    shutil.copy2(config_file_path, config_file_dest)

    # Stage the cert if provided
    if cert_file_path:
        log.info('Attempting to stage certificate file: {f}'.format(f=cert_file_path))

        # Ensure the cert file exists
        if not os.path.isfile(cert_file_path):
            raise Cons3rtConfigError('Certificate file not found: {f}'.format(f=cert_file_path))

        # Copy cert file to the config dir
        log.info('Copying certificate file to directory: {d}'.format(d=cons3rtapi_config_dir))
        shutil.copy2(cert_file_path, cons3rtapi_config_dir)
    else:
        log.info('No cert_file_path arg provided, no cert file will be copied.')


def set_config(config_data):
    """Sets the config file data with the data provided after validation

    :param config_data: (dict) configuration data
    :return: None
    :raises Cons3rtConfigError
    """
    log = logging.getLogger(mod_logger + '.set_config')

    cons3rt_config = {}

    # Validate data provided
    if 'api_url' in config_data:
        cons3rt_config['api_url'] = config_data['api_url']
    else:
        raise Cons3rtConfigError('api_url is required')

    if 'cert' in config_data:
        cons3rt_config['cert'] = config_data['cert']
    elif 'name' in config_data:
        cons3rt_config['name'] = config_data['name']
    else:
        raise Cons3rtConfigError('Either name or cert is required config data')

    if 'projects' in config_data:
        cons3rt_config['projects'] = []
        for project in config_data['projects']:
            add_project = {}
            if 'name' in project:
                add_project['name'] = project['name']
            else:
                raise Cons3rtConfigError('project data missing a name')
            if 'rest_key' in project:
                add_project['rest_key'] = project['rest_key']
            else:
                raise Cons3rtConfigError('project data missing a rest_key')
            cons3rt_config['projects'].append(add_project)
    else:
        raise Cons3rtConfigError('projects is required in config data')
    write_config(cons3rt_config)
    log.info('Updated config data here: {f}'.format(f=cons3rtapi_config_file))
