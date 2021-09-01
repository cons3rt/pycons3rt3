#!/usr/bin/python

"""Module: deployment

This module provides a set of useful utilities for accessing CONS3RT
deployment related info. It is intended to be imported and used in
other python-based CONS3RT assets.

Classes:
    Deployment: Provides utility for accessing information in the
        deployment.properties file, including validation, getting
        specific properties, and getting the scenario role name.

    DeploymentError: Custom exception for raised when there is a
        problem obtaining the deployment properties file.
"""
import argparse
import datetime
import logging
import os
import platform
import re
import yaml


from .bash import get_ip_addresses, ip_addr
from .bash import update_hosts_file as update_hosts_file_linux
from .exceptions import DeploymentError, CommandError, SshConfigError
from .logify import Logify
from .osutil import get_os
from .ssh import generate_ssh_rsa_key, ssh_copy_id, wait_for_host_key, unrestrict_host_key_checking
from .windows import update_hosts_file as update_hosts_file_windows


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.deployment'


class Deployment(object):
    """Utility for storing and access info from deployment.properties

    This class provides a set of useful utilities for accessing CONS3RT
    deployment related deployment information, such as deployment
    properties, deployment home, asset directory, the and the CONS3RT
    role name. If a Deployment object cannot be instantiated, a
    DeploymentError is raised. Sample usage is shown below in the main
    module method.

    Args: None

    Attributes:
        properties (dict): Key value pair for each deployment
            property.
        properties_file (str): Full system path to the deployment
            properties file.
        deployment_home (str): Deployment home system path
        cons3rt_role_name (str): Role name of this system in the
            context of the CONS3RT scenario
        asset_dir (dir): Asset directory system path
    """
    def __init__(self):
        self.cls_logger = mod_logger + '.Deployment'
        self.properties = {}
        self.properties_sh = {}
        self.properties_ps1 = {}
        self.properties_file = ''
        self.properties_file_sh = ''
        self.properties_file_ps1 = ''
        self.deployment_home = ''
        self.cons3rt_role_name = ''
        self.asset_dir = ''
        self.scenario_role_names = []
        self.scenario_master = ''
        self.scenario_network_info = []
        self.deployment_id = None
        self.deployment_name = ''
        self.deployment_run_id = None
        self.deployment_run_name = ''
        self.virtualization_realm_type = ''

        # Determine cons3rt agent directories
        if get_os() == 'Linux':
            self.cons3rt_agent_home = os.path.join(os.path.sep, 'opt', 'cons3rt-agent')
        elif get_os() == 'Windows':
            self.cons3rt_agent_home = os.path.join('C:', os.path.sep, 'cons3rt-agent')
        else:
            self.cons3rt_agent_home = None
        if self.cons3rt_agent_home:
            self.cons3rt_agent_log_dir = os.path.join(self.cons3rt_agent_home, 'log')
            self.cons3rt_agent_run_dir = os.path.join(self.cons3rt_agent_home, 'run')
        else:
            self.cons3rt_agent_log_dir = None
            self.cons3rt_agent_run_dir = None

        # Set deployment home and read deployment properties
        try:
            self.get_deployment_home()
            self.read_deployment_properties()
        except DeploymentError:
            raise
        self.set_cons3rt_role_name()
        self.set_asset_dir()
        self.set_scenario_role_names()
        self.set_scenario_network_info()
        self.set_deployment_name()
        self.set_deployment_id()
        self.set_deployment_run_name()
        self.set_deployment_run_id()
        self.set_virtualization_realm_type()

    def get_deployment_home(self):
        """Sets self.deployment_home

        This method finds and sets deployment home, primarily based on
        the DEPLOYMENT_HOME environment variable. If not set, this
        method will attempt to determine deployment home.

        :return: None
        :raises: DeploymentError
        """
        log = logging.getLogger(self.cls_logger + '.get_deployment_home')
        try:
            self.deployment_home = os.environ['DEPLOYMENT_HOME']
        except KeyError:
            log.warning('DEPLOYMENT_HOME environment variable is not set, attempting to set it...')
        else:
            log.info('Found DEPLOYMENT_HOME environment variable set to: {d}'.format(d=self.deployment_home))
            return

        if self.cons3rt_agent_run_dir is None:
            msg = 'This is not Windows nor Linux, cannot determine DEPLOYMENT_HOME'
            raise DeploymentError(msg)

        # Ensure the run directory can be found
        if not os.path.isdir(self.cons3rt_agent_run_dir):
            msg = 'Could not find the cons3rt run directory, DEPLOYMENT_HOME cannot be set'
            raise DeploymentError(msg)

        run_dir_contents = os.listdir(self.cons3rt_agent_run_dir)
        results = []
        for item in run_dir_contents:
            if 'Deployment' in item:
                results.append(item)
        if len(results) != 1:
            msg = 'Could not find deployment home in the cons3rt run directory, deployment home cannot be set'
            raise DeploymentError(msg)

        # Ensure the Deployment Home is a directory
        candidate_deployment_home = os.path.join(self.cons3rt_agent_run_dir, results[0])
        if not os.path.isdir(candidate_deployment_home):
            msg = 'The candidate deployment home is not a valid directory: {d}'.format(d=candidate_deployment_home)
            raise DeploymentError(msg)

        # Ensure the deployment properties file can be found
        self.deployment_home = candidate_deployment_home
        os.environ['DEPLOYMENT_HOME'] = self.deployment_home
        log.info('Set DEPLOYMENT_HOME in the environment to: {d}'.format(d=self.deployment_home))

    def read_deployment_properties_java(self):
        """Reads the deployment properties file

        This method reads the java deployment properties file into the
        "properties" dictionary object.

        :return: None
        :raises: DeploymentError
        """
        log = logging.getLogger(self.cls_logger + '.read_deployment_properties_java')

        # Ensure deployment properties file exists
        self.properties_file = os.path.join(self.deployment_home, 'deployment.properties')
        if not os.path.isfile(self.properties_file):
            msg = 'Deployment properties file not found: {f}'.format(f=self.properties_file)
            raise DeploymentError(msg)
        log.info('Found deployment properties file: {f}'.format(f=self.properties_file))

        log.info('Reading deployment properties...')
        with open(self.properties_file, 'r') as f:
            for line in f:
                log.debug('Processing deployment properties file line: {a}'.format(a=line))
                if not isinstance(line, str):
                    log.debug('Skipping line that is not a string: {a}'.format(a=line))
                    continue
                elif line.startswith('#'):
                    log.debug('Skipping line that is a comment: {a}'.format(a=line))
                    continue
                elif '=' in line:
                    split_line = line.strip().split('=', 1)
                    if len(split_line) == 2:
                        prop_name = split_line[0].strip()
                        prop_value = split_line[1].strip()
                        if prop_name is None or not prop_name or prop_value is None or not prop_value:
                            log.debug('Property name <{n}> or value <v> is none or blank, not including it'.format(
                                n=prop_name, v=prop_value))
                        else:
                            log.debug('Adding property {n} with value {v}...'.format(n=prop_name, v=prop_value))
                            unescaped_prop_value = prop_value.replace('\\', '')
                            self.properties[prop_name] = unescaped_prop_value
                    else:
                        log.debug('Skipping line that did not split into 2 part on an equal sign...')
        log.info('Successfully read in deployment properties')

    def read_deployment_properties_sh(self):
        """Reads the deployment properties shell file

        This method reads the shell deployment properties file into the
        "properties_sh" dictionary object.

        :return: None
        :raises: DeploymentError
        """
        log = logging.getLogger(self.cls_logger + '.read_deployment_properties_sh')

        # Ensure deployment properties file exists
        self.properties_file_sh = os.path.join(self.deployment_home, 'deployment-properties.sh')
        if not os.path.isfile(self.properties_file_sh):
            msg = 'Deployment properties file not found: {f}'.format(f=self.properties_file_sh)
            raise DeploymentError(msg)
        log.info('Found deployment properties file: {f}'.format(f=self.properties_file_sh))

        log.info('Reading deployment properties shell file...')
        with open(self.properties_file_sh, 'r') as f:
            for line in f:
                log.debug('Processing deployment properties file line: {a}'.format(a=line))
                if not isinstance(line, str):
                    log.debug('Skipping line that is not a string: {a}'.format(a=line))
                    continue
                elif line.startswith('#'):
                    log.debug('Skipping line that is a comment: {a}'.format(a=line))
                    continue
                elif '=' in line:
                    split_line = line.strip().split('=', 1)
                    if len(split_line) == 2:
                        prop_name = split_line[0].strip()
                        prop_value = split_line[1].strip()
                        if prop_name is None or not prop_name or prop_value is None or not prop_value:
                            log.debug('Property name <{n}> or value <v> is none or blank, not including it'.format(
                                n=prop_name, v=prop_value))
                        else:
                            log.debug('Adding property {n} with value {v}...'.format(n=prop_name, v=prop_value))
                            stripped_prop_value = prop_value.lstrip('\'').rstrip('\'')
                            self.properties_sh[prop_name] = stripped_prop_value
                    else:
                        log.debug('Skipping line that did not split into 2 part on an equal sign...')
        log.info('Successfully read in deployment properties shell file')

    def read_deployment_properties_ps1(self):
        """Reads the deployment properties powershell file

        This method reads the powershell deployment properties file into the
        "properties_ps1" dictionary object.

        :return: None
        :raises: DeploymentError
        """
        log = logging.getLogger(self.cls_logger + '.read_deployment_properties_ps1')

        # Ensure deployment properties file exists
        self.properties_file_ps1 = os.path.join(self.deployment_home, 'deployment-properties.ps1')
        if not os.path.isfile(self.properties_file_ps1):
            msg = 'Deployment properties file not found: {f}'.format(f=self.properties_file_ps1)
            raise DeploymentError(msg)
        log.info('Found deployment properties file: {f}'.format(f=self.properties_file_ps1))

        log.info('Reading deployment properties shell file...')
        with open(self.properties_file_ps1, 'r') as f:
            for line in f:
                log.debug('Processing deployment properties file line: {a}'.format(a=line))
                if not isinstance(line, str):
                    log.debug('Skipping line that is not a string: {a}'.format(a=line))
                    continue
                elif line.startswith('#'):
                    log.debug('Skipping line that is a comment: {a}'.format(a=line))
                    continue
                elif '=' in line:
                    split_line = line.strip().split('=', 1)
                    if len(split_line) == 2:
                        prop_name = split_line[0].strip()
                        prop_value = split_line[1].strip()
                        if prop_name is None or not prop_name or prop_value is None or not prop_value:
                            log.debug('Property name <{n}> or value <v> is none or blank, not including it'.format(
                                n=prop_name, v=prop_value))
                        else:
                            log.debug('Adding property {n} with value {v}...'.format(n=prop_name, v=prop_value))
                            stripped_prop_name = prop_name.lstrip('$')
                            stripped_prop_value = prop_value.lstrip('\'').rstrip('\'')
                            self.properties_ps1[stripped_prop_name] = stripped_prop_value
                    else:
                        log.debug('Skipping line that did not split into 2 part on an equal sign...')
        log.info('Successfully read in deployment properties powershell file')

    def read_deployment_properties(self):
        self.read_deployment_properties_java()
        self.read_deployment_properties_sh()
        self.read_deployment_properties_ps1()

    def output_props_yaml(self, yaml_file_path):
        """Outputs the deployment properties in yaml file format to the specified file path

        :param yaml_file_path: (str) yaml file path
        :return: None
        :raises: DeploymentError
        """
        try:
            with open(yaml_file_path, 'w') as f:
                yaml.dump(self.properties_sh, f, sort_keys=True)
        except Exception as exc:
            raise DeploymentError('Problem creating file: {f}'.format(f=yaml_file_path)) from exc

    def get_property(self, regex):
        """Gets the name of a specific property

        This public method is passed a regular expression and
        returns the matching property name. If either the property
        is not found or if the passed string matches more than one
        property, this function will return None.

        :param regex: Regular expression to search on
        :return: (str) Property name matching the passed regex or None.
        """
        log = logging.getLogger(self.cls_logger + '.get_property')

        if not isinstance(regex, str):
            log.error('regex arg is not a string found type: {t}'.format(t=regex.__class__.__name__))
            return None

        log.debug('Looking up property based on regex: {r}'.format(r=regex))
        prop_list_matched = []
        for prop_name in self.properties.keys():
            match = re.search(regex, prop_name)
            if match:
                prop_list_matched.append(prop_name)
        if len(prop_list_matched) == 1:
            log.debug('Found matching property: {p}'.format(p=prop_list_matched[0]))
            return prop_list_matched[0]
        elif len(prop_list_matched) > 1:
            log.debug('Passed regex {r} matched more than 1 property, checking for an exact match...'.format(r=regex))
            for matched_prop in prop_list_matched:
                if matched_prop == regex:
                    log.debug('Found an exact match: {p}'.format(p=matched_prop))
                    return matched_prop
            log.debug('Exact match not found for regex {r}, returning None'.format(r=regex))
            return None
        else:
            log.debug('Passed regex did not match any deployment properties: {r}'.format(r=regex))
            return None

    def get_matching_property_names(self, regex):
        """Returns a list of property names matching the provided
        regular expression

        :param regex: Regular expression to search on
        :return: (list) of property names matching the regex
        """
        log = logging.getLogger(self.cls_logger + '.get_matching_property_names')
        prop_list_matched = []
        if not isinstance(regex, str):
            log.warning('regex arg is not a string, found type: {t}'.format(t=regex.__class__.__name__))
            return prop_list_matched
        log.debug('Finding properties matching regex: {r}'.format(r=regex))
        for prop_name in self.properties.keys():
            match = re.search(regex, prop_name)
            if match:
                prop_list_matched.append(prop_name)
        return prop_list_matched

    def get_value(self, property_name):
        """Returns the value associated to the passed property

        This public method is passed a specific property as a string
        and returns the value of that property. If the property is not
        found, None will be returned.

        :param property_name (str) The name of the property
        :return: (str) value for the passed property, or None.
        """
        log = logging.getLogger(self.cls_logger + '.get_value')
        if not isinstance(property_name, str):
            log.error('property_name arg is not a string, found type: {t}'.format(t=property_name.__class__.__name__))
            return None
        # Ensure a property with that name exists
        prop = self.get_property(property_name)
        if not prop:
            log.debug('Property name not found matching: {n}'.format(n=property_name))
            return None
        value = self.properties[prop]
        log.debug('Found value for property {n}: {v}'.format(n=property_name, v=value))
        return value

    def set_cons3rt_role_name(self):
        """Set the cons3rt_role_name member for this system

        :return: None
        :raises: DeploymentError
        """
        log = logging.getLogger(self.cls_logger + '.set_cons3rt_role_name')
        try:
            self.cons3rt_role_name = os.environ['CONS3RT_ROLE_NAME']
        except KeyError:
            log.warning('CONS3RT_ROLE_NAME is not set, attempting to determine it from deployment properties...')

            if platform.system() == 'Linux':
                log.info('Attempting to determine CONS3RT_ROLE_NAME on Linux...')
                try:
                    self.determine_cons3rt_role_name_linux()
                except DeploymentError:
                    raise
            else:
                log.warning('Unable to determine CONS3RT_ROLE_NAME on this System')

        else:
            log.info('Found environment variable CONS3RT_ROLE_NAME: {r}'.format(r=self.cons3rt_role_name))
            return

    def determine_cons3rt_role_name_linux(self):
        """Determines the CONS3RT_ROLE_NAME for this Linux system, and
        Set the cons3rt_role_name member for this system

        This method determines the CONS3RT_ROLE_NAME for this system
        in the deployment by first checking for the environment
        variable, if not set, determining the value from the
        deployment properties.

        :return: None
        :raises: DeploymentError
        """
        log = logging.getLogger(self.cls_logger + '.determine_cons3rt_role_name_linux')

        # Determine IP addresses for this system
        log.info('Determining the IPv4 addresses for this system...')
        try:
            ip_addresses = get_ip_addresses()
        except CommandError as exc:
            msg = 'Unable to get the IP address of this system, thus cannot determine the CONS3RT_ROLE_NAME'
            raise DeploymentError(msg) from exc
        else:
            log.info('Found IP addresses: {a}'.format(a=ip_addresses))

        # Get IP addresses on this host
        try:
            ip_addresses = ip_addr()
        except CommandError as exc:
            raise DeploymentError(
                'Unable to determine IP addresses on this host to determine CONS3RT_ROLE_NAME') from exc

        for device_name, ip_address in ip_addresses.items():
            pattern = '^cons3rt\.fap\.deployment\.machine.*0.internalIp=' + ip_address + '$'
            try:
                f = open(self.properties_file)
            except IOError as exc:
                msg = 'Could not open file {f}'.format(f=self.properties_file)
                raise DeploymentError(msg) from exc
            prop_list_matched = []
            log.debug('Searching for deployment properties matching pattern: {p}'.format(p=pattern))
            for line in f:
                log.debug('Processing deployment properties file line: {a}'.format(a=line))
                if line.startswith('#'):
                    continue
                elif '=' in line:
                    match = re.search(pattern, line)
                    if match:
                        log.debug('Found matching prop: {a}'.format(a=line))
                        prop_list_matched.append(line)
            log.debug('Number of matching properties found: {n}'.format(n=len(prop_list_matched)))
            if len(prop_list_matched) == 1:
                prop_parts = prop_list_matched[0].split('.')
                if len(prop_parts) > 5:
                    self.cons3rt_role_name = prop_parts[4]
                    log.info('Found CONS3RT_ROLE_NAME from deployment properties: {c}'.format(c=self.cons3rt_role_name))
                    log.info('Adding CONS3RT_ROLE_NAME to the current environment...')
                    os.environ['CONS3RT_ROLE_NAME'] = self.cons3rt_role_name
                    return
                else:
                    log.error('Property found was not formatted as expected: %s',
                              prop_parts)
            else:
                log.error('Did not find a unique matching deployment property')
        msg = 'Could not determine CONS3RT_ROLE_NAME from deployment properties'
        raise DeploymentError(msg)

    def set_asset_dir(self):
        """Returns the ASSET_DIR environment variable

        This method gets the ASSET_DIR environment variable for the
        current asset install. It returns either the string value if
        set or None if it is not set.

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.get_asset_dir')
        try:
            self.asset_dir = os.environ['ASSET_DIR']
        except KeyError:
            log.warning('Environment variable ASSET_DIR is not set!')
        else:
            log.info('Found environment variable ASSET_DIR: {a}'.format(a=self.asset_dir))

    def set_scenario_role_names(self):
        """Populates the list of scenario role names in this deployment and
        populates the scenario_master with the master role

        Gets a list of deployment properties containing "isMaster" because
        there is exactly one per scenario host, containing the role name

        :return:
        """
        log = logging.getLogger(self.cls_logger + '.set_scenario_role_names')
        is_master_props = self.get_matching_property_names('isMaster')
        for is_master_prop in is_master_props:
            role_name = is_master_prop.split('.')[-1]
            log.info('Adding scenario host: {n}'.format(n=role_name))
            self.scenario_role_names.append(role_name)

            # Determine if this is the scenario master
            is_master = self.get_value(is_master_prop).lower().strip()
            if is_master == 'true':
                log.info('Found master scenario host: {r}'.format(r=role_name))
                self.scenario_master = role_name

    def set_scenario_network_info(self):
        """Populates a list of network info for each scenario host from
        deployment properties

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_scenario_network_info')

        for scenario_host in self.scenario_role_names:
            scenario_host_network_info = {'scenario_role_name': scenario_host}
            log.debug('Looking up network info from deployment properties for scenario host: {s}'.format(
                s=scenario_host))
            network_name_props = self.get_matching_property_names(
                'cons3rt.fap.deployment.machine.*{r}.*networkName'.format(r=scenario_host)
            )
            log.debug('Found {n} network name props'.format(n=str(len(network_name_props))))

            network_info_list = []
            for network_name_prop in network_name_props:
                network_info = {}
                network_name = self.get_value(network_name_prop)
                if not network_name:
                    log.debug('Network name not found for prop: {n}'.format(n=network_name_prop))
                    continue
                log.debug('Adding info for network name: {n}'.format(n=network_name))
                network_info['network_name'] = network_name
                interface_name_prop = 'cons3rt.fap.deployment.machine.{r}.{n}.interfaceName'.format(
                    r=scenario_host, n=network_name)
                interface_name = self.get_value(interface_name_prop)
                if interface_name:
                    network_info['interface_name'] = interface_name
                external_ip_prop = 'cons3rt.fap.deployment.machine.{r}.{n}.boundaryIp'.format(
                    r=scenario_host, n=network_name)
                external_ip = self.get_value(external_ip_prop)
                if external_ip:
                    network_info['external_ip'] = external_ip
                internal_ip_prop = 'cons3rt.fap.deployment.machine.{r}.{n}.internalIp'.format(
                    r=scenario_host, n=network_name)
                internal_ip = self.get_value(internal_ip_prop)
                if internal_ip:
                    network_info['internal_ip'] = internal_ip
                is_cons3rt_connection_prop = 'cons3rt.fap.deployment.machine.{r}.{n}.isCons3rtConnection'.format(
                    r=scenario_host, n=network_name)
                is_cons3rt_connection = self.get_value(is_cons3rt_connection_prop)
                if is_cons3rt_connection:
                    if is_cons3rt_connection.lower().strip() == 'true':
                        network_info['is_cons3rt_connection'] = True
                    else:
                        network_info['is_cons3rt_connection'] = False
                mac_address_prop = 'cons3rt.fap.deployment.machine.{r}.{n}.mac'.format(r=scenario_host, n=network_name)
                mac_address = self.get_value(mac_address_prop)
                if mac_address:
                    # Trim the escape characters from the mac address
                    mac_address = mac_address.replace('\\', '')
                    network_info['mac_address'] = mac_address
                log.debug('Found network info: {n}'.format(n=str(network_info)))
                network_info_list.append(network_info)
            scenario_host_network_info['network_info'] = network_info_list
            self.scenario_network_info.append(scenario_host_network_info)

    def get_network_info(self):
        """Returns the network info for THIS host

        :return: (list) of network data
        """
        for network_info in self.scenario_network_info:
            if network_info['scenario_role_name'] == self.cons3rt_role_name:
                return network_info['network_info']

    def set_deployment_name(self):
        """Sets the deployment name from deployment properties

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_deployment_name')
        self.deployment_name = self.get_value('cons3rt.deployment.name')
        log.info('Found deployment name: {n}'.format(n=self.deployment_name))

    def set_deployment_id(self):
        """Sets the deployment ID from deployment properties

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_deployment_id')
        deployment_id_val = self.get_value('cons3rt.deployment.id')
        if not deployment_id_val:
            log.debug('Deployment ID not found in deployment properties')
            return
        try:
            deployment_id = int(deployment_id_val)
        except ValueError:
            log.debug('Deployment ID found was unable to convert to an int: {d}'.format(d=deployment_id_val))
            return
        self.deployment_id = deployment_id
        log.info('Found deployment ID: {i}'.format(i=str(self.deployment_id)))

    def set_deployment_run_name(self):
        """Sets the deployment run name from deployment properties

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_deployment_run_name')
        self.deployment_run_name = self.get_value('cons3rt.deploymentRun.name')
        log.info('Found deployment run name: {n}'.format(n=self.deployment_run_name))

    def set_deployment_run_id(self):
        """Sets the deployment run ID from deployment properties

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_deployment_run_id')
        deployment_run_id_val = self.get_value('cons3rt.deploymentRun.id')
        if not deployment_run_id_val:
            log.debug('Deployment run ID not found in deployment properties')
            return
        try:
            deployment_run_id = int(deployment_run_id_val)
        except ValueError:
            log.debug('Deployment run ID found was unable to convert to an int: {d}'.format(d=deployment_run_id_val))
            return
        self.deployment_run_id = deployment_run_id
        log.info('Found deployment run ID: {i}'.format(i=str(self.deployment_run_id)))

    def set_virtualization_realm_type(self):
        """Sets the virtualization realm type from deployment properties

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_virtualization_realm_type')
        self.virtualization_realm_type = self.get_value('cons3rt.deploymentRun.virtRealm.type')
        log.info('Found virtualization realm type : {t}'.format(t=self.virtualization_realm_type))

    def is_aws(self):
        """Determine if this deployment is in AWS

        :return: (bool) True if AWS, False otherwise
        """
        return self.virtualization_realm_type.lower() == 'amazon'

    def is_azure(self):
        """Determine if this deployment is in Azure

        :return: (bool) True if Azure, False otherwise
        """
        return self.virtualization_realm_type.lower() == 'azure'

    def is_openstack(self):
        """Determine if this deployment is in AWS

        :return: (bool) True if Openstack, False otherwise
        """
        return self.virtualization_realm_type.lower() == 'ppenstack'

    def is_vcloud(self):
        """Determine if this deployment is in vCloud

        :return: (bool) True if vCloud, False otherwise
        """
        return self.virtualization_realm_type.lower() == 'vcloud'

    def update_hosts_file(self, ip, entry):
        """Updated the hosts file depending on the OS

        :param ip: (str) IP address to update
        :param entry: (str) entry to associate to the IP address
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.update_hosts_file')

        if get_os() in ['Linux', 'Darwin']:
            update_hosts_file_linux(ip=ip, entry=entry)
        elif get_os() == 'Windows':
            update_hosts_file_windows(ip=ip, entry=entry)
        else:
            log.warning('OS detected was not Windows nor Linux')

    def set_scenario_hosts_file(self, network_name='user-net', domain_name=None):
        """Adds hosts file entries for each system in the scenario
        for the specified network_name provided

        :param network_name: (str) Name of the network to add to the hosts file
        :param domain_name: (str) Domain name to include in the hosts file entries if provided
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_scenario_hosts_file')

        log.info('Scanning scenario hosts to make entries in the hosts file for network: {n}'.format(n=network_name))
        for scenario_host in self.scenario_network_info:
            if domain_name:
                host_file_entry = '{r}.{d} {r}'.format(r=scenario_host['scenario_role_name'], d=domain_name)
            else:
                host_file_entry = scenario_host['scenario_role_name']
            for host_network_info in scenario_host['network_info']:
                if host_network_info['network_name'] == network_name:
                    self.update_hosts_file(ip=host_network_info['internal_ip'], entry=host_file_entry)

    def set_hosts_file_entry_for_role(self, role_name, network_name='user-net', fqdn=None, domain_name=None):
        """Adds an entry to the hosts file for a scenario host given
        the role name and network name

        :param role_name: (str) role name of the host to add
        :param network_name: (str) Name of the network to add to the hosts file
        :param fqdn: (str) Fully qualified domain name to use in the hosts file entry (trumps domain name)
        :param domain_name: (str) Domain name to include in the hosts file entries if provided
        :return:
        """
        log = logging.getLogger(self.cls_logger + '.set_hosts_file_entry_for_role')

        # Determine the host file entry portion
        if fqdn:
            host_file_entry = fqdn
        else:
            if domain_name:
                host_file_entry = '{r}.{d} {r}'.format(r=role_name, d=domain_name)
            else:
                host_file_entry = role_name
        log.info('Using hosts file entry: {e}'.format(e=host_file_entry))
        log.info('Scanning scenario hosts for role name [{r}] and network: {n}'.format(r=role_name, n=network_name))
        for scenario_host in self.scenario_network_info:
            if scenario_host['scenario_role_name'] == role_name:
                for host_network_info in scenario_host['network_info']:
                    if host_network_info['network_name'] == network_name:
                        self.update_hosts_file(ip=host_network_info['internal_ip'], entry=host_file_entry)

    def get_ip_on_network(self, network_name):
        """Given a network name, returns the IP address

        :param network_name: (str) Name of the network to search for
        :return: (str) IP address on the specified network or None
        """
        return self.get_scenario_host_ip_on_network(
            scenario_role_name=self.cons3rt_role_name,
            network_name=network_name
        )

    def get_external_ip_on_network(self, network_name):
        """Given a network name, returns the external IP address

        :param network_name: (str) Name of the network to search for
        :return: (str) external IP address on the specified network or None
        """
        return self.get_scenario_host_external_ip_on_network(
            scenario_role_name=self.cons3rt_role_name,
            network_name=network_name
        )

    def get_scenario_host_ip_on_network(self, scenario_role_name, network_name):
        """Given a network name, returns the IP address

        :param network_name: (str) Name of the network to search for
        :param scenario_role_name: (str) role name to return the IP address for
        :return: (str) IP address on the specified network or None
        """
        log = logging.getLogger(self.cls_logger + '.get_scenario_host_ip_on_network')

        # Determine the network info for this host based on role name
        cons3rt_network_info = None
        for scenario_host in self.scenario_network_info:
            if scenario_host['scenario_role_name'] == scenario_role_name:
                cons3rt_network_info = scenario_host['network_info']
        if not cons3rt_network_info:
            log.warning('Unable to find network info for this host')
            return

        # Attempt to find a matching IP for network name
        internal_ip = None
        for cons3rt_network in cons3rt_network_info:
            if cons3rt_network['network_name'] == network_name:
                internal_ip = cons3rt_network['internal_ip']
        if not internal_ip:
            log.warning('Unable to find an internal IP for network: {n}'.format(n=network_name))
            return
        log.debug('Found IP address [{i}] for network name: {n}'.format(i=internal_ip, n=network_name))
        return internal_ip

    def get_scenario_host_external_ip_on_network(self, scenario_role_name, network_name):
        """Given a network name, returns the external IP address

        :param network_name: (str) Name of the network to search for
        :param scenario_role_name: (str) role name to return the IP address for
        :return: (str) IP address on the specified network or None
        """
        log = logging.getLogger(self.cls_logger + '.get_scenario_host_external_ip_on_network')

        # Determine the network info for this host based on role name
        cons3rt_network_info = None
        for scenario_host in self.scenario_network_info:
            if scenario_host['scenario_role_name'] == scenario_role_name:
                cons3rt_network_info = scenario_host['network_info']
        if not cons3rt_network_info:
            log.warning('Unable to find network info for this host')
            return

        # Attempt to find a matching external IP for network name
        external_ip = None
        for cons3rt_network in cons3rt_network_info:
            if cons3rt_network['network_name'] == network_name:
                if 'external_ip' in cons3rt_network.keys():
                    external_ip = cons3rt_network['external_ip']
        if not external_ip:
            log.warning('Unable to find an external IP for network: {n}'.format(n=network_name))
            return

        internal_ip = self.get_scenario_host_ip_on_network(scenario_role_name, network_name)
        if internal_ip == external_ip:
            log.warning('External IP found matches the Internal IP, not returning...')
            return

        log.debug('Found external IP address [{i}] for network name: {n}'.format(i=external_ip, n=network_name))
        return external_ip

    def get_device_for_network_linux(self, network_name):
        """Given a cons3rt network name, return the network interface name
        on this Linux system

        :param network_name: (str) Name of the network to search for
        :return: (str) name of the network interface device or None
        """
        log = logging.getLogger(self.cls_logger + '.get_device_for_network_linux')

        if get_os() not in ['Linux']:
            log.warning('Non-linux OS detected, returning...')
            return

        # Get the IP address for the network name according to cons3rt
        ip_address = self.get_ip_on_network(network_name=network_name)
        if not ip_address:
            log.warning('IP address not found for network with name: {n}'.format(n=network_name))
            return

        # Get the system device names and ip addresses
        sys_info = ip_addr()

        # Check for a matching IP address
        device_name = None
        for device_name, sys_ip_address in sys_info.iteritems():
            if sys_ip_address == ip_address:
                log.debug('Found matching system IP [{i}] for device: {d}'.format(i=ip_address, d=device_name))

        if not device_name:
            log.warning('Network device not found with IP address {i} in system network data: {d}'.format(
                i=ip_address, d=str(sys_info)))
            return
        log.debug('Found device name [{d}] with IP address [{i}] for network: {n}'.format(
            d=device_name, i=ip_address, n=network_name))
        return device_name

    def allow_host_ssh_on_network(self, network_name):
        """Adds unrestricted host key checking on a specific network by IP address

        :param network_name: (str) name of the network to unrestrict
        :return: None
        :raises: DeploymentError
        """
        log = logging.getLogger(self.cls_logger + '.allow_host_ssh_on_network')
        ip = None
        for network in self.get_network_info():
            if network['network_name'] == network_name:
                ip = network['internal_ip']
        if not ip:
            raise DeploymentError('IP address not found on network: {n}'.format(n=network_name))
        pattern = '.'.join(ip.split('.')[0:3]) + '.*'
        log.info('Adding unrestricted host key access for network {n}: {p}'.format(n=network_name, p=pattern))
        try:
            unrestrict_host_key_checking(pattern)
        except SshConfigError as exc:
            raise DeploymentError('Problem adding unrestricted host key checking for: {p}'.format(
                p=pattern)) from exc

    def generate_scenario_ssh_keys(self, key_name=None, username=None, port=22):
        """Use this method to generate SSH RSA keys on this host and distribute the keys to
        other hosts in the scenario.

        NOTE: This depends on the other hosts allowing passwordless SSH access

        :return: None
        :raises: DeploymentError
        """
        log = logging.getLogger(self.cls_logger + '.generate_scenario_ssh_keys')

        # Determine key_name
        if not key_name:
            key_name = 'dr{d}_{t}_id_rsa'.format(
                d=str(self.deployment_run_id),
                t=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            )

        # Generate SSH keys
        log.info('Generating SSH key with name: {n}'.format(n=key_name))
        try:
            key_path, pub_key_path = generate_ssh_rsa_key(key_name=key_name)
        except CommandError as exc:
            raise DeploymentError('Problem generating SSH RSA keys') from exc

        if len(self.scenario_role_names) < 1:
            log.warning('No scenario role names found to distribute keys to')
            return

        if not self.cons3rt_role_name:
            log.warning('cons3rt role name for this host not found, cannot distribute the SSH key')
            return

        # Determine the list of remote hosts
        remote_hosts = []
        for host in self.scenario_role_names:
            if host != self.cons3rt_role_name:
                remote_hosts.append(host)

        # Distribute the key to remote hosts
        for host in remote_hosts:
            log.info('Distributing SSH key to host: {h}'.format(h=host))
            try:
                wait_for_host_key(host=host)
                ssh_copy_id(pub_key_path=pub_key_path, remote_username=username, host=host, port=str(port))
            except CommandError as exc:
                raise DeploymentError('Problem copying SSH key to host: {h}'.format(h=host)) from exc


def main():
    """Sample usage for this python module

    This main method simply illustrates sample usage for this python
    module.

    :return: None
    """
    parser = argparse.ArgumentParser(description='cons3rt deployment CLI')
    parser.add_argument('command', help='Command for the deployment CLI')
    parser.add_argument('--network', help='Name of the network')
    parser.add_argument('--name', help='Name of a deployment property to get')
    args = parser.parse_args()

    valid_commands = ['ip', 'device', 'prop']
    valid_commands_str = ','.join(valid_commands)

    # Get the command
    command = args.command.strip().lower()

    # Ensure the command is valid
    if command not in valid_commands:
        print('Invalid command found [{c}]\n'.format(c=command) + valid_commands_str)
        return 1

    if command == 'ip':
        if not args.network:
            print('Missed arg: --network, for the name of the network')
    elif command == 'device':
        if not args.network:
            print('Missed arg: --network, for the name of the network')
            return 1
        d = Deployment()
        print(d.get_device_for_network_linux(network_name=args.network))
    elif command == 'prop':
        if not args.name:
            print('Missed arg: --name, for the name of the property to retrieve')
            return 1
        d = Deployment()
        print(d.get_value(property_name=args.name))


if __name__ == '__main__':
    main()
