"""Module: ec2util

This module provides utilities for interacting with the AWS
EC2 API, including networking and security group
configurations.

"""
import logging
import os
import socket
import time
import traceback

from botocore.client import ClientError
import requests

from .aws_metadata import is_aws, get_instance_id, get_vpc_id_from_mac_address
from .awsutil import get_boto3_client, get_linux_migration_user_data_script_contents, \
    get_linux_nat_config_user_data_script_contents, global_regions, gov_regions, us_regions
from .bash import get_ip_addresses, validate_ip_address
from .cons3rtinfra import Cons3rtInfra
from .exceptions import AWSAPIError, AwsTransitGatewayError, EC2UtilError
from .logify import Logify
from .network import get_ip_list_for_hostname_list
from .osutil import get_os

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.ec2util'


# NAT AMI IDs used for cons3rt NAT VMs
nat_vm_ami = {
    'us-gov-west-1': 'ami-074217ed4c80a6267',
    'us-gov-east-1': 'ami-5623cd27',
    'us-east-1': 'ami-01ef31f9f39c5aaed',
    'us-east-2': 'ami-06064740484d375de',
    'us-west-2': 'ami-0fcc6101b7f2370b9'
}

# Default size of a NAT instance
nat_default_size = 't3.micro'

# Amazon service names when querying IPs
amazon_service_names = ['AMAZON', 'CHIME_VOICECONNECTOR', 'ROUTE53_HEALTHCHECKS', 'S3', 'IVS_REALTIME',
                        'WORKSPACES_GATEWAYS', 'EC2', 'ROUTE53', 'CLOUDFRONT', 'GLOBALACCELERATOR', 'AMAZON_CONNECT',
                        'ROUTE53_HEALTHCHECKS_PUBLISHING', 'CHIME_MEETINGS', 'CLOUDFRONT_ORIGIN_FACING', 'CLOUD9',
                        'CODEBUILD', 'API_GATEWAY', 'ROUTE53_RESOLVER', 'EBS', 'EC2_INSTANCE_CONNECT',
                        'KINESIS_VIDEO_STREAMS', 'AMAZON_APPFLOW', 'MEDIA_PACKAGE_V2', 'DYNAMODB']


class EC2Util(object):
    """Utility for interacting with the AWS API
    """
    def __init__(self, region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None,
                 skip_is_aws=False):
        self.cls_logger = mod_logger + '.EC2Util'
        try:
            self.client = get_ec2_client(region_name=region_name, aws_access_key_id=aws_access_key_id,
                                         aws_secret_access_key=aws_secret_access_key,
                                         aws_session_token=aws_session_token)
        except ClientError as exc:
            msg = 'Unable to create an EC2 client'
            raise EC2UtilError(msg) from exc
        self.region = self.client.meta.region_name
        self.is_aws = False
        self.instance_id = None
        self.vpc_id = None
        if not skip_is_aws:
            if get_os() != 'Darwin':
                self.is_aws = is_aws()
            if self.is_aws:
                self.instance_id = get_instance_id()
            if self.instance_id and self.is_aws:
                self.vpc_id = get_vpc_id_from_mac_address()

    def ensure_exists(self, resource_id, timeout_sec=300):
        """Ensure the provided resource ID exists

        :param resource_id: (str) ID of the resource
        :param timeout_sec: (int) seconds to wait before returning False
        :return: (bool) True when found, False if does not exist in the provided timeout
        :raises: None
        """
        log = logging.getLogger(self.cls_logger + '.ensure_exists')
        check_interval_sec = 2
        num_checks = timeout_sec // check_interval_sec
        start_time = time.time()
        log.info('Waiting a maximum of {t} seconds for resource ID [{i}] become available'.format(
            t=str(timeout_sec), i=resource_id))
        for _ in range(0, num_checks*2):
            time.sleep(check_interval_sec)
            elapsed_time = round(time.time() - start_time, 1)
            if elapsed_time > timeout_sec:
                log.warning('Resource ID {i} has not passed instance status checks after {t} seconds'.format(
                    i=resource_id, t=str(timeout_sec)))
                return False
            try:
                if resource_id.startswith('i-'):
                    get_instance(client=self.client, instance_id=resource_id)
                elif resource_id.startswith('subnet-'):
                    self.client.describe_subnets(SubnetIds=[resource_id])
                elif resource_id.startswith('sg-'):
                    self.client.describe_security_groups(GroupIds=[resource_id])
                elif resource_id.startswith('rtb-'):
                    self.client.describe_route_tables(RouteTableIds=[resource_id])
                elif resource_id.startswith('acl-'):
                    self.client.describe_network_acls(NetworkAclIds=[resource_id])
                elif resource_id.startswith('vpc-'):
                    self.client.describe_vpcs(VpcIds=[resource_id])
                elif resource_id.startswith('igw-'):
                    self.client.describe_internet_gateways(InternetGatewayIds=[resource_id])
                elif resource_id.startswith('eni-'):
                    self.client.describe_network_interfaces(NetworkInterfaceIds=[resource_id])
                elif resource_id.startswith('h-'):
                    self.client.describe_hosts(HostIds=[resource_id])
                elif resource_id.startswith('ami-'):
                    # TODO implement ami existence test
                    return True
                else:
                    log.warning('Resource type not supported for this method: {r}'.format(r=resource_id))
                    return False
            except ClientError as exc:
                log.info('Resource ID not found: {i}\n{e}'.format(i=resource_id, e=str(exc)))
                continue
            else:
                log.info('Found resource ID: {i}'.format(i=resource_id))
                return True
        return False

    def create_tag(self, resource_id, tag_key, tag_value):
        """Adds/updates the tag key with the specified value on the resource ID

        :param resource_id: (str) ID of the resource to tag
        :param tag_key: (str) tag key
        :param tag_value: (str) tag value
        :return: (bool) True if successful, False otherwise
        """
        log = logging.getLogger(self.cls_logger + '.create_tag')
        log.info('Adding tag [{k}={v}] resource ID: {i}'.format(k=tag_key, v=tag_value, i=resource_id))
        try:
            self.client.create_tags(
                DryRun=False,
                Resources=[resource_id],
                Tags=[
                    {
                        'Key': tag_key,
                        'Value': tag_value
                    }
                ]
            )
        except ClientError as exc:
            msg = 'Problem adding tag [{k}={v}] resource ID: {i}\n{e}'.format(
                k=tag_key, v=tag_value, i=resource_id, e=str(exc))
            log.error(msg)
            return False
        return True

    def create_tags(self, resource_id, tags):
        """Adds/updates the provided tags as key/value pairs on the resource ID

        :param resource_id: (str) ID of the resource to tag
        :param tags: (list) of dict key/value tag pairs
        :return: (bool) True if successful, False otherwise
        """
        log = logging.getLogger(self.cls_logger + '.create_tag')
        log.info('Adding tags [{t}] resource ID: {i}'.format(t=str(tags), i=resource_id))
        try:
            self.client.create_tags(
                DryRun=False,
                Resources=[resource_id],
                Tags=tags
            )
        except ClientError as exc:
            msg = 'Problem adding tag [{t}] resource ID: {i}\n{e}'.format(
                t=str(tags), i=resource_id, e=str(exc))
            log.error(msg)
            return False
        return True

    def create_name_tag(self, resource_id, resource_name):
        """Creates the name tag on the specified resource ID

        :param resource_id: (str) ID of the resource to tag
        :param resource_name: (str) desired name tag for the resource
        :return: True if successful, False otherwise
        """
        return self.create_tag(
            resource_id=resource_id,
            tag_key='Name',
            tag_value=resource_name
        )

    def create_cons3rt_enabled_tag(self, resource_id, enabled=True):
        """Creates the name tag on the specified resource ID

        :param resource_id: (str) ID of the resource to tag
        :param enabled: (bool) Set True to enable this resource for CONS3RT, false otherwise
        :return: True if successful, False otherwise
        """
        if enabled:
            enabled_str = 'true'
        else:
            enabled_str = 'false'
        return self.create_tag(
            resource_id=resource_id,
            tag_key='cons3rtenabled',
            tag_value=enabled_str
        )

    def get_vpc_id(self):
        """Gets the VPC ID for this EC2 instance

        :return: String instance ID or None
        """
        log = logging.getLogger(self.cls_logger + '.get_vpc_id')

        # Exit if not running on AWS
        if not self.is_aws:
            log.info('This machine is not running in AWS, exiting...')
            return None

        if not self.instance_id:
            log.warning('Unable to get the Instance ID for this machine')
            return None
        log.info('Found Instance ID: {i}'.format(i=self.instance_id))

        log.info('Querying AWS to get the VPC ID...')
        try:
            instance = get_instance(client=self.client, instance_id=self.instance_id)
        except ClientError as exc:
            log.warning('Unable to query AWS to get info for instance {i}\n{e}'.format(i=self.instance_id, e=str(exc)))
            return None
        if 'VpcId' in instance.keys():
            log.info('Found VPC ID: {v}'.format(v=instance['VpcId']))
            return instance['VpcId']
        log.warning('Unable to get VPC ID from instance: {i}'.format(i=str(instance)))
        return None

    def list_available_regions(self):
        """Returns a list of available regions for this client

        :return: (list) available regions
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.list_available_regions')
        log.info('Getting a list of available regions...')
        try:
            response = self.client.describe_regions()
        except ClientError as exc:
            msg = 'Problem describing all regions available to this client'
            raise EC2UtilError(msg) from exc
        if 'Regions' not in response.keys():
            raise EC2UtilError('Regions not found in response: {r}'.format(r=str(response)))
        return response['Regions']

    def get_rhui_servers(self, all_available=False):
        return self.get_rhui1_servers(all_available=all_available)

    def get_rhui_servers_all_versions(self, all_available=False):
        return self.get_rhui1_servers(all_available=all_available) + \
               self.get_rhui2_servers(all_available=all_available) + \
               self.get_rhui3_servers(all_available=all_available)

    def get_rhui1_servers(self, all_available=False):
        """Returns a list of RHUI1 servers for my region

        :return: (list) of RHUI1 server IP addresses
        """
        log = logging.getLogger(self.cls_logger + '.get_rhui1_servers')
        rhui_regions = []
        if all_available:
            log.info('Getting RHUI1 servers for all available regions...')
            region_list = self.list_available_regions()
            for region in region_list:
                rhui_regions.append(region['RegionName'])
        else:
            log.info('Getting RHUI1 servers for just my current region: {r}'.format(r=self.region))
            rhui_regions = [self.region]
        return get_aws_rhui1_ips(regions=rhui_regions)

    def get_rhui2_servers(self, all_available=False):
        """Returns a list of RHUI2 servers for my region

        :return: (list) of RHUI2 server IP addresses
        """
        log = logging.getLogger(self.cls_logger + '.get_rhui2_servers')
        rhui_regions = []
        if all_available:
            log.info('Getting RHUI2 servers for all available regions...')
            region_list = self.list_available_regions()
            for region in region_list:
                rhui_regions.append(region['RegionName'])
        else:
            log.info('Getting RHUI2 servers for just my current region: {r}'.format(r=self.region))
            rhui_regions = [self.region]
        return get_aws_rhui2_ips(regions=rhui_regions)

    def get_rhui3_servers(self, all_available=False):
        """Returns a list of RHUI3 servers for my region

        :return: (list) of RHUI3 server IP addresses
        """
        log = logging.getLogger(self.cls_logger + '.get_rhui3_servers')
        rhui_regions = []
        if all_available:
            log.info('Getting RHUI3 servers for all available regions...')
            region_list = self.list_available_regions()
            for region in region_list:
                rhui_regions.append(region['RegionName'])
        else:
            log.info('Getting RHUI3 servers for just my current region: {r}'.format(r=self.region))
            rhui_regions = [self.region]
        return get_aws_rhui3_ips(regions=rhui_regions)

    def list_subnets_with_token(self, next_token=None, vpc_id=None):
        """Listing subnets in the VPC with continuation token if provided

        :param vpc_id: (str) VPC ID to filter on if provided
        :param next_token: (str) Next token to provide or None
        :return: (dict) response (see boto3 documentation)
        :raises: EC2UtilError
        """
        filters = []
        if vpc_id:
            filters.append({'Name': 'vpc-id', 'Values': [vpc_id]})
        try:
            response = self.client.describe_subnets(
                DryRun=False,
                Filters=filters
            )
        except ClientError as exc:
            if next_token:
                msg = 'Problem listing subnets with token {t} and filters: {f}'.format(
                    t=next_token, f=str(filters))
            else:
                msg = 'Problem listing subnets in VPC (no token) with filters: {f}'.format(f=str(filters))
            raise EC2UtilError(msg) from exc
        if 'Subnets' not in response.keys():
            raise EC2UtilError('Subnets not found in response: {r}'.format(r=str(response)))
        return response

    def list_subnets(self, vpc_id=None):
        """Returns the list of subnets for the VPC

        :param vpc_id: (str) VPC ID to filter on if provided
        :return: (list) of subnets (see boto3 docs)
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.list_subnets')
        if vpc_id:
            log.info('Listing subnets in VPC ID: {v}'.format(v=vpc_id))
        else:
            log.info('Listing subnets...')
        next_token = None
        next_query = True
        subnets = []
        while next_query:
            response = self.list_subnets_with_token(vpc_id=vpc_id, next_token=next_token)
            if 'NextToken' not in response.keys():
                next_query = False
            else:
                next_token = response['NextToken']
            subnets += response['Subnets']
        return subnets

    def get_subnet(self, subnet_id):
        return self.retrieve_subnet(subnet_id=subnet_id)

    def retrieve_subnet(self, subnet_id):
        """Gets details of the specified subnet ID

        :param subnet_id: (str) subnet ID
        :return: (dict) subnet (see boto3 docs)
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_subnet')
        log.info('Describing subnet: {i}'.format(i=subnet_id))
        try:
            response = self.client.describe_subnets(
                SubnetIds=[subnet_id],
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem describing subnet: {i}'.format(i=subnet_id)
            raise EC2UtilError(msg) from exc
        if 'Subnets' not in response.keys():
            msg = 'Subnets not in response: {r}'.format(r=str(response))
            raise EC2UtilError(msg)
        if len(response['Subnets']) != 1:
            msg = 'Expected 1 subnet in response, found: {n}\n{r}'.format(
                n=str(len(response['Subnets'])), r=str(response))
            raise EC2UtilError(msg)
        return response['Subnets'][0]

    def retrieve_subnet_cidr_block(self, subnet_id):
        """Returns the CIDR block of the specified subnet ID

        :param subnet_id: (str) subnet ID
        :return: (str) CIDR block
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_subnet_cidr_block')
        subnet = self.retrieve_subnet(subnet_id=subnet_id)
        if 'CidrBlock' not in subnet.keys():
            msg = 'CidrBlock not found in subnet: {s}'.format(s=str(subnet))
            raise EC2UtilError(msg)
        cidr = subnet['CidrBlock']
        log.info('Found CIDR for subnet ID [{i}]: {c}'.format(i=subnet_id, c=cidr))
        return cidr

    # Ensure the subnet IDs are in the provided VPC ID
    def verify_subnets_in_vpc(self, vpc_id, subnet_list):
        """Determine if the list of subnets are in the provided VPC ID
        
        :param vpc_id: (str) ID of the VPC
        :param subnet_list: (list) of subnet IDs
        :return: True if all subnets in the provided list are in the VPC ID, False otherwise
        """
        log = logging.getLogger(self.cls_logger + '.verify_subnets_in_vpc')
        log.info('Determining if subnets are in VPC ID [{v}]: {s}'.format(v=vpc_id, s=','.join(subnet_list)))
        try:
            vpc_subnets = self.list_subnets(vpc_id=vpc_id)
        except EC2UtilError as exc:
            msg = 'Problem listing subnets in VPC ID: {i}'.format(i=vpc_id)
            raise EC2UtilError(msg) from exc
        for subnet_id in subnet_list:
            found_in_vpc = False
            for vpc_subnet in vpc_subnets:
                if 'SubnetId' not in vpc_subnet.keys():
                    log.warning('SubnetId not found in subnet data: {s}'.format(s=str(vpc_subnet)))
                    return False
                if 'VpcId' not in vpc_subnet.keys():
                    log.warning('VpcId not found in subnet data: {s}'.format(s=str(vpc_subnet)))
                    return False
                if vpc_subnet['SubnetId'] == subnet_id:
                    if vpc_subnet['VpcId'] != vpc_id:
                        msg = 'Subnet ID [{s}] found in VPC [{f}] not in provided VPC: {v}'.format(
                            s=subnet_id, f=vpc_subnet['VpcId'], v=vpc_id)
                        log.warning(msg)
                        return False
                    else:
                        log.info('Found subnet {s} in provided VPC ID: {v}'.format(
                            s=subnet_id, v=vpc_id))
                        found_in_vpc = True
            if not found_in_vpc:
                log.warning('Subnet {s} not found in VPC ID: {v}'.format(s=subnet_id, v=vpc_id))
                return False
        return True

    def verify_subnets_affinity(self, subnet_id_list, num_availability_zones=2):
        """Ensures that at least 2 availability zones are represented by the provided subnet IDs
        
        :param subnet_id_list: (list) of subnet IDs
        :param num_availability_zones: (int) number of desired availability zones
        :return: True if at least 2 availability zones are represented, False otherwise
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.verify_subnets_in_two_azs')
        log.info('Ensuring that the list of subnets [{s}] are in at least {n} availability zones'.format(
            s=','.join(subnet_id_list), n=str(num_availability_zones)))
        availability_zones = []
        subnets = []
        for subnet_id in subnet_id_list:
            try:
                subnets.append(self.retrieve_subnet(subnet_id=subnet_id))
            except EC2UtilError as exc:
                msg = 'Problem retrieving subnet: {i}'.format(i=subnet_id)
                raise EC2UtilError(msg) from exc
        for subnet in subnets:
            if 'AvailabilityZone' not in subnet.keys():
                msg = 'AvailabilityZone not found in subnet data: {d}'.format(d=str(subnet))
                raise EC2UtilError(msg)
            if subnet['AvailabilityZone'] not in availability_zones:
                availability_zones.append(subnet['AvailabilityZone'])
        if len(availability_zones) < 2:
            log.warning('Subnet IDs must be in at least 2 availability zones, found availability zones: {z}'.format(
                z=','.join(availability_zones)))
            return False
        return True

    def list_vpc_route_tables_with_token(self, next_token=None, vpc_id=None):
        """Listing route tables in the VPC with continuation token if provided

        :param vpc_id: (str) VPC ID to filter on if provided
        :param next_token: (str) Next token to provide or None
        :return: (dict) response (see boto3 documentation)
        :raises: EC2UtilError
        """
        filters = []
        if vpc_id:
            filters.append({'Name': 'vpc-id', 'Values': [vpc_id]})
        try:
            response = self.client.describe_route_tables(
                DryRun=False,
                Filters=filters
            )
        except ClientError as exc:
            if next_token:
                msg = 'Problem listing route tables with token {t} and filters: {f}'.format(
                    t=next_token, f=str(filters))
            else:
                msg = 'Problem listing route tables (no token) with filters: {f}'.format(f=str(filters))
            raise EC2UtilError(msg) from exc
        if 'RouteTables' not in response.keys():
            raise EC2UtilError('RouteTables not found in response: {r}'.format(r=str(response)))
        return response

    def list_vpc_route_tables(self, vpc_id=None):
        """Returns the list of subnets for the VPC

        :param vpc_id: (str) VPC ID to filter on if provided
        :return: (list) of route tables (see boto3 docs)
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.list_vpc_route_tables')
        if vpc_id:
            log.info('Listing route tables in VPC ID: {v}'.format(v=vpc_id))
        else:
            log.info('Listing route tables...')
        next_token = None
        next_query = True
        route_tables = []
        while next_query:
            response = self.list_vpc_route_tables_with_token(vpc_id=vpc_id, next_token=next_token)
            if 'NextToken' not in response.keys():
                next_query = False
            else:
                next_token = response['NextToken']
            route_tables += response['RouteTables']
        return route_tables

    def get_route_table(self, route_table_id):
        """Retrieves the route table

        :param route_table_id: (str) ID of the route table
        :return: (dict) containing route table data (see boto3 docs)
        """
        log = logging.getLogger(self.cls_logger + '.get_route_table')
        log.info('Getting info on route table ID: {i}'.format(i=route_table_id))
        try:
            response = self.client.describe_route_tables(
                DryRun=False,
                RouteTableIds=[route_table_id]
            )
        except ClientError as exc:
            msg = 'Problem getting route table ID: {i}'.format(i=route_table_id)
            raise EC2UtilError(msg) from exc
        if 'RouteTables' not in response.keys():
            raise EC2UtilError('RouteTables not found in response: {r}'.format(r=str(response)))
        if len(response['RouteTables']) != 1:
            raise EC2UtilError('{n} route tables found for ID: {i}'.format(
                n=str(len(response['RouteTables'])), i=route_table_id))
        return response['RouteTables'][0]

    def create_route_to_transit_gateway(self, route_table_id, dest_cidr, transit_gateway):
        """Create an IPv4 route to a transit gateway

        :param dest_cidr: (str) IPv4 CIDR block
        :param route_table_id: (str) ID of the route table to update
        :param transit_gateway: (str) ID of the transit gateway
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_transit_gateway')
        log.info('Route table ID [{r}] creating for destination [{d}] to transit gateway: {i}'.format(
            r=route_table_id, d=dest_cidr, i=transit_gateway))
        return self.client.create_route(
            DestinationCidrBlock=dest_cidr,
            DryRun=False,
            TransitGatewayId=transit_gateway,
            RouteTableId=route_table_id
        )

    def create_route_to_transit_gateway_ipv6(self, route_table_id, dest_cidr_ipv6, transit_gateway):
        """Create an IPv6 route to a transit gateway

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr_ipv6: (str) IPv4 CIDR block
        :param transit_gateway: (str) ID of the transit gateway
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_transit_gateway_ipv6')
        log.info('Route table ID [{r}] creating for destination [{d}] to transit gateway: {i}'.format(
            r=route_table_id, d=dest_cidr_ipv6, i=transit_gateway))
        return self.client.create_route(
            DestinationIpv6CidrBlock=dest_cidr_ipv6,
            DryRun=False,
            TransitGatewayId=transit_gateway,
            RouteTableId=route_table_id
        )

    def create_route_to_egress_internet_gateway(self, route_table_id, dest_cidr, egress_only_internet_gateway):
        """Create an IPv4 route to an egress-only Internet gateway

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr: (str) IPv4 CIDR block
        :param egress_only_internet_gateway: (str) ID of the egress-only Internet gateway
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_transit_gateway_ipv6')
        log.info('Route table ID [{r}] creating for destination [{d}] to egress-only Internet gateway: {i}'.format(
            r=route_table_id, d=dest_cidr, i=egress_only_internet_gateway))
        return self.client.create_route(
            DestinationCidrBlock=dest_cidr,
            DryRun=False,
            EgressOnlyInternetGatewayId=egress_only_internet_gateway,
            RouteTableId=route_table_id
        )

    def create_route_to_egress_internet_gateway_ipv6(self, route_table_id, dest_cidr_ipv6,
                                                     egress_only_internet_gateway):
        """Create an IPv6 route to an egress-only Internet gateway

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr_ipv6: (str) IPv4 CIDR block
        :param egress_only_internet_gateway: (str) ID of the egress-only Internet gateway
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_egress_internet_gateway_ipv6')
        log.info('Route table ID [{r}] creating for destination [{d}] to egress-only Internet gateway: {i}'.format(
            r=route_table_id, d=dest_cidr_ipv6, i=egress_only_internet_gateway))
        return self.client.create_route(
            DestinationIpv6CidrBlock=dest_cidr_ipv6,
            DryRun=False,
            EgressOnlyInternetGatewayId=egress_only_internet_gateway,
            RouteTableId=route_table_id
        )

    def create_route_to_gateway(self, route_table_id, dest_cidr, gateway_id):
        """Create an IPv4 route to an Internet gateway or local

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr: (str) IPv4 CIDR block
        :param gateway_id: (str) ID of Internet Gateway or local
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_gateway')
        log.info('Route table ID [{r}] creating for destination [{d}] to gateway: {i}'.format(
            r=route_table_id, d=dest_cidr, i=gateway_id))
        return self.client.create_route(
            DestinationCidrBlock=dest_cidr,
            DryRun=False,
            GatewayId=gateway_id,
            RouteTableId=route_table_id
        )

    def create_route_to_gateway_ipv6(self, route_table_id, dest_cidr_ipv6, gateway_id):
        """Create an IPv6 route to an Internet gateway or local

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr_ipv6: (str) IPv6 CIDR block
        :param gateway_id: (str) ID of Internet Gateway or local
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_gateway')
        log.info('Route table ID [{r}] creating for destination [{d}] to gateway: {i}'.format(
            r=route_table_id, d=dest_cidr_ipv6, i=gateway_id))
        return self.client.create_route(
            DestinationIpv6CidrBlock=dest_cidr_ipv6,
            DryRun=False,
            GatewayId=gateway_id,
            RouteTableId=route_table_id
        )

    def create_route_to_instance(self, route_table_id, dest_cidr, instance_id):
        """Create an IPv4 route to an EC2 instance

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr: (str) IPv4 CIDR block
        :param instance_id: (str) ID of EC2 instance
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_instance')
        log.info('Route table ID [{r}] creating for destination [{d}] to instance: {i}'.format(
            r=route_table_id, d=dest_cidr, i=instance_id))
        return self.client.create_route(
            DestinationCidrBlock=dest_cidr,
            DryRun=False,
            InstanceId=instance_id,
            RouteTableId=route_table_id
        )

    def create_route_to_instance_ipv6(self, route_table_id, dest_cidr_ipv6, instance_id):
        """Create an IPv6 route to an EC2 instance

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr_ipv6: (str) IPv6 CIDR block
        :param instance_id: (str) ID of EC2 instance
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_instance_ipv6')
        log.info('Route table ID [{r}] creating for destination [{d}] to instance: {i}'.format(
            r=route_table_id, d=dest_cidr_ipv6, i=instance_id))
        return self.client.create_route(
            DestinationIpv6CidrBlock=dest_cidr_ipv6,
            DryRun=False,
            InstanceId=instance_id,
            RouteTableId=route_table_id
        )

    def create_route_to_nat_gateway(self, route_table_id, dest_cidr, nat_gateway):
        """Create an IPv4 route to a NAT gateway

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr: (str) IPv4 CIDR block
        :param nat_gateway: (str) ID of NAT gateway
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_nat_gateway')
        log.info('Route table ID [{r}] creating for destination [{d}] to NAT gateway: {i}'.format(
            r=route_table_id, d=dest_cidr, i=nat_gateway))
        return self.client.create_route(
            DestinationCidrBlock=dest_cidr,
            DryRun=False,
            NatGatewayId=nat_gateway,
            RouteTableId=route_table_id
        )

    def create_route_to_nat_gateway_ipv6(self, route_table_id, dest_cidr_ipv6, nat_gateway):
        """Create an IPv6 route to a NAt gateway

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr_ipv6: (str) IPv6 CIDR block
        :param nat_gateway: (str) ID of NAT gateway
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_nat_gateway')
        log.info('Route table ID [{r}] creating for destination [{d}] to NAT gateway: {i}'.format(
            r=route_table_id, d=dest_cidr_ipv6, i=nat_gateway))
        return self.client.create_route(
            DestinationIpv6CidrBlock=dest_cidr_ipv6,
            DryRun=False,
            NatGatewayId=nat_gateway,
            RouteTableId=route_table_id
        )

    def create_route_to_local_gateway(self, route_table_id, dest_cidr, local_gateway):
        """Create an IPv4 route to a local gateway

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr: (str) IPv4 CIDR block
        :param local_gateway: (str) ID of local gateway
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_local_gateway')
        log.info('Route table ID [{r}] creating for destination [{d}] local gateway: {i}'.format(
            r=route_table_id, d=dest_cidr, i=local_gateway))
        return self.client.create_route(
            DestinationCidrBlock=dest_cidr,
            DryRun=False,
            LocalGatewayId=local_gateway,
            RouteTableId=route_table_id
        )

    def create_route_to_local_gateway_ipv6(self, route_table_id, dest_cidr_ipv6, local_gateway):
        """Create an IPv6 route to a local gateway

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr_ipv6: (str) IPv6 CIDR block
        :param local_gateway: (str) ID of local gateway
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_local_gateway_ipv6')
        log.info('Route table ID [{r}] creating for destination [{d}] local gateway: {i}'.format(
            r=route_table_id, d=dest_cidr_ipv6, i=local_gateway))
        return self.client.create_route(
            DestinationIpv6CidrBlock=dest_cidr_ipv6,
            DryRun=False,
            LocalGatewayId=local_gateway,
            RouteTableId=route_table_id
        )

    def create_route_to_network_interface(self, route_table_id, dest_cidr, network_interface):
        """Create an IPv4 route to a network interface

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr: (str) IPv4 CIDR block
        :param network_interface: (str) ID of network interface
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_network_interface')
        log.info('Route table ID [{r}] creating for destination [{d}] network interface: {i}'.format(
            r=route_table_id, d=dest_cidr, i=network_interface))
        return self.client.create_route(
            DestinationCidrBlock=dest_cidr,
            DryRun=False,
            NetworkInterfaceId=network_interface,
            RouteTableId=route_table_id
        )

    def create_route_to_network_interface_ipv6(self, route_table_id, dest_cidr_ipv6, network_interface):
        """Create an IPv6 route to a network interface

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr_ipv6: (str) IPv6 CIDR block
        :param network_interface: (str) ID of network interface
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_network_interface_ipv6')
        log.info('Route table ID [{r}] creating for destination [{d}] network interface: {i}'.format(
            r=route_table_id, d=dest_cidr_ipv6, i=network_interface))
        return self.client.create_route(
            DestinationIpv6CidrBlock=dest_cidr_ipv6,
            DryRun=False,
            NetworkInterfaceId=network_interface,
            RouteTableId=route_table_id
        )

    def create_route_to_vpc_peering_connection(self, route_table_id, dest_cidr, vpc_peering_connection):
        """Create an IPv4 route to a VPC peering connection

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr: (str) IPv4 CIDR block
        :param vpc_peering_connection: (str) ID of VPC peering connection
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_network_interface')
        log.info('Route table ID [{r}] creating for destination [{d}] network interface: {i}'.format(
            r=route_table_id, d=dest_cidr, i=vpc_peering_connection))
        return self.client.create_route(
            DestinationCidrBlock=dest_cidr,
            DryRun=False,
            VpcPeeringConnectionId=vpc_peering_connection,
            RouteTableId=route_table_id
        )

    def create_route_to_vpc_peering_connection_ipv6(self, route_table_id, dest_cidr_ipv6, vpc_peering_connection):
        """Create an IPv6 route to a VPC peering connection

        :param route_table_id: (str) ID of the route table to update
        :param dest_cidr_ipv6: (str) IPv6 CIDR block
        :param vpc_peering_connection: (str) ID of VPC peering connection
        :return: response (see boto3 documentation)
        """
        log = logging.getLogger(self.cls_logger + '.create_route_to_network_interface')
        log.info('Route table ID [{r}] creating for destination [{d}] network interface: {i}'.format(
            r=route_table_id, d=dest_cidr_ipv6, i=vpc_peering_connection))
        return self.client.create_route(
            DestinationIpv6CidrBlock=dest_cidr_ipv6,
            DryRun=False,
            VpcPeeringConnectionId=vpc_peering_connection,
            RouteTableId=route_table_id
        )

    def create_route(self, route_table_id, dest_cidr, egress_only_internet_gateway=None, gateway_id=None,
                     instance_id=None, nat_gateway=None, transit_gateway=None, local_gateway=None,
                     network_interface=None, vpc_peering_connection=None):
        """Adds the specified rule to the route table

        :param: route_table_id: (str) ID of the route table to update
        :param: dest_cidr: (str) IPv4 CIDR
        :param: egress_only_internet_gateway: (str) ID of the egress only Internet gateway, IPv6 only
        :param: gateway_id (str): ID of Internet Gateway or local
        :param: instance_id (str): ID of the instance (single-nic only)
        :param: nat_gateway (str): ID of the NAT gateway
        :param: transit_gateway (str): ID of the transit gateway
        :param: local_gateway (str): ID of the local gateway
        :param: network_interface (str): ID of the network interface
        :param: vpc_peering_connection (str): ID of the VPC peering connection
        :return: (bool) True if successful, False otherwise
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_route')
        log.info('Creating IPv4 route in route table ID: {i}'.format(i=route_table_id))
        try:
            if egress_only_internet_gateway:
                response = self.create_route_to_egress_internet_gateway(
                    route_table_id=route_table_id,
                    dest_cidr=dest_cidr,
                    egress_only_internet_gateway=egress_only_internet_gateway
                )
            elif gateway_id:
                response = self.create_route_to_gateway(
                    route_table_id=route_table_id,
                    dest_cidr=dest_cidr,
                    gateway_id=gateway_id
                )
            elif instance_id:
                response = self.create_route_to_instance(
                    route_table_id=route_table_id,
                    dest_cidr=dest_cidr,
                    instance_id=instance_id
                )
            elif nat_gateway:
                response = self.create_route_to_nat_gateway(
                    route_table_id=route_table_id,
                    dest_cidr=dest_cidr,
                    nat_gateway=nat_gateway
                )
            elif transit_gateway:
                response = self.create_route_to_transit_gateway(
                    route_table_id=route_table_id,
                    dest_cidr=dest_cidr,
                    transit_gateway=transit_gateway
                )
            elif local_gateway:
                response = self.create_route_to_local_gateway(
                    route_table_id=route_table_id,
                    dest_cidr=dest_cidr,
                    local_gateway=local_gateway
                )
            elif network_interface:
                response = self.create_route_to_network_interface(
                    route_table_id=route_table_id,
                    dest_cidr=dest_cidr,
                    network_interface=network_interface
                )
            elif vpc_peering_connection:
                response = self.create_route_to_vpc_peering_connection(
                    route_table_id=route_table_id,
                    dest_cidr=dest_cidr,
                    vpc_peering_connection=vpc_peering_connection
                )
            else:
                raise EC2UtilError('Invalid args provided')
        except ClientError as exc:
            msg = 'Problem creating IPv4 route in route table: {i}'.format(i=route_table_id)
            raise EC2UtilError(msg) from exc
        if 'Return' not in response.keys():
            raise EC2UtilError('Return not found in response: {r}'.format(r=str(response)))
        if response['Return'] == 'True':
            return True
        else:
            return False

    def create_route_ipv6(self, route_table_id, dest_cidr_ipv6, egress_only_internet_gateway=None, gateway_id=None,
                          instance_id=None, nat_gateway=None, transit_gateway=None, local_gateway=None,
                          network_interface=None, vpc_peering_connection=None):
        """Adds the specified IPv6 rule to the route table

        :param: route_table_id: (str) ID of the route table to update
        :param: dest_cidr_ipv6: (str) IPv6 CIDR
        :param: egress_only_internet_gateway: (str) ID of the egress only Internet gateway, IPv6 only
        :param: gateway_id (str): ID of Internet Gateway or local
        :param: instance_id (str): ID of the instance (single-nic only)
        :param: nat_gateway (str): ID of the NAT gateway
        :param: transit_gateway (str): ID of the transit gateway
        :param: local_gateway (str): ID of the local gateway
        :param: network_interface (str): ID of the network interface
        :param: vpc_peering_connection (str): ID of the VPC peering connection
        :return: (bool) True if successful, False otherwise
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_route')
        log.info('Creating IPv6 route in route table ID: {i}'.format(i=route_table_id))
        try:
            if egress_only_internet_gateway:
                response = self.create_route_to_egress_internet_gateway_ipv6(
                    route_table_id=route_table_id,
                    dest_cidr_ipv6=dest_cidr_ipv6,
                    egress_only_internet_gateway=egress_only_internet_gateway
                )
            elif gateway_id:
                response = self.create_route_to_gateway_ipv6(
                    route_table_id=route_table_id,
                    dest_cidr_ipv6=dest_cidr_ipv6,
                    gateway_id=gateway_id
                )
            elif instance_id:
                response = self.create_route_to_instance_ipv6(
                    route_table_id=route_table_id,
                    dest_cidr_ipv6=dest_cidr_ipv6,
                    instance_id=instance_id
                )
            elif nat_gateway:
                response = self.create_route_to_nat_gateway_ipv6(
                    route_table_id=route_table_id,
                    dest_cidr_ipv6=dest_cidr_ipv6,
                    nat_gateway=nat_gateway
                )
            elif transit_gateway:
                response = self.create_route_to_transit_gateway_ipv6(
                    route_table_id=route_table_id,
                    dest_cidr_ipv6=dest_cidr_ipv6,
                    transit_gateway=transit_gateway
                )
            elif local_gateway:
                response = self.create_route_to_local_gateway_ipv6(
                    route_table_id=route_table_id,
                    dest_cidr_ipv6=dest_cidr_ipv6,
                    local_gateway=local_gateway
                )
            elif network_interface:
                response = self.create_route_to_network_interface_ipv6(
                    route_table_id=route_table_id,
                    dest_cidr_ipv6=dest_cidr_ipv6,
                    network_interface=network_interface
                )
            elif vpc_peering_connection:
                response = self.create_route_to_vpc_peering_connection_ipv6(
                    route_table_id=route_table_id,
                    dest_cidr_ipv6=dest_cidr_ipv6,
                    vpc_peering_connection=vpc_peering_connection
                )
            else:
                raise EC2UtilError('Invalid args provided')
        except ClientError as exc:
            msg = 'Problem creating IPv6 route in route table: {i}'.format(i=route_table_id)
            raise EC2UtilError(msg) from exc
        if 'Return' not in response.keys():
            raise EC2UtilError('Return not found in response: {r}'.format(r=str(response)))
        if response['Return'] == 'True':
            return True
        else:
            return False

    def delete_route_ipv4(self, route_table_id, cidr):
        """Deletes the IPv4 CIDR destination route from the route table

        :param route_table_id: (str) ID of the route table
        :param cidr: (str) CIDR IPv4
        :return: None
        :raises: EC2UtilError
        """
        try:
            self.client.delete_route(
                DestinationCidrBlock=cidr,
                DryRun=False,
                RouteTableId=route_table_id
            )
        except ClientError as exc:
            msg = 'Problem deleting IPv4 CIDR {c} from route table: {i}'.format(c=cidr, i=route_table_id)
            raise EC2UtilError(msg) from exc

    def delete_route_ipv6(self, route_table_id, cidr_ipv6):
        """Deletes the IPv6 CIDR destination route from the route table

        :param route_table_id: (str) ID of the route table
        :param cidr_ipv6: (str) CIDR IPv6
        :return: None
        :raises: EC2UtilError
        """
        try:
            self.client.delete_route(
                DestinationIpv6CidrBlock=cidr_ipv6,
                DryRun=False,
                RouteTableId=route_table_id
            )
        except ClientError as exc:
            msg = 'Problem deleting IPv6 CIDR {c} from route table: {i}'.format(c=cidr_ipv6, i=route_table_id)
            raise EC2UtilError(msg) from exc

    def delete_route(self, route_table_id, route):
        """Deletes the route from the route table

        :param route_table_id: (str) ID of the route table
        :param route: (IpRoute) objects representing a single route
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.delete_route')
        log.info('Deleting route from route table [{i}]: {r}'.format(i=route_table_id, r=str(route)))
        if route.get_cidr_type() == 'DestinationIpv6CidrBlock':
            self.delete_route_ipv6(route_table_id=route_table_id, cidr_ipv6=route.cidr_ipv6)
        elif route.get_cidr_type() == 'DestinationCidrBlock':
            self.delete_route_ipv4(route_table_id=route_table_id, cidr=route.cidr)
        else:
            raise EC2UtilError('Unrecognized CIDR type: {t}'.format(t=route.get_cidr_type()))

    def delete_routes(self, route_table_id, routes):
        """Deletes the list of routes from the route table

        :param route_table_id: (str) ID of the route table
        :param routes: (list) of IpRoute objects
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.delete_routes')
        log.info('Deleting {n} routes from route table ID: {i}'.format(n=str(len(routes)), i=route_table_id))
        for route in routes:
            self.delete_route(route_table_id=route_table_id, route=route)

    def add_route(self, route_table_id, route):
        """Adds the route to the route table

        :param route_table_id: (str) ID of the route table
        :param route: (IpRoute) objects representing a single route
        :return: True if successful, False otherwise
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_route')
        log.info('Adding route type [{t}] to route table [{i}]: {r}'.format(
            i=route_table_id, r=str(route), t=route.get_target_type()))
        response = None
        try:
            if route.get_cidr_type() == 'DestinationCidrBlock':
                if route.get_target_type() == 'EgressOnlyInternetGatewayId':
                    response = self.create_route_to_egress_internet_gateway(
                        route_table_id=route_table_id,
                        dest_cidr=route.cidr,
                        egress_only_internet_gateway=route.target
                    )
                elif route.get_target_type() == 'GatewayId':
                    response = self.create_route_to_gateway(
                        route_table_id=route_table_id,
                        dest_cidr=route.cidr,
                        gateway_id=route.target
                    )
                elif route.get_target_type() == 'InstanceId':
                    response = self.create_route_to_instance(
                        route_table_id=route_table_id,
                        dest_cidr=route.cidr,
                        instance_id=route.target
                    )
                elif route.get_target_type() == 'NatGatewayId':
                    response = self.create_route_to_nat_gateway(
                        route_table_id=route_table_id,
                        dest_cidr=route.cidr,
                        nat_gateway=route.target
                    )
                elif route.get_target_type() == 'TransitGatewayId':
                    response = self.create_route_to_transit_gateway(
                        route_table_id=route_table_id,
                        dest_cidr=route.cidr,
                        transit_gateway=route.target
                    )
                elif route.get_target_type() == 'LocalGatewayId':
                    response = self.create_route_to_local_gateway(
                        route_table_id=route_table_id,
                        dest_cidr=route.cidr,
                        local_gateway=route.target
                    )
                elif route.get_target_type() == 'NetworkInterfaceId':
                    response = self.create_route_to_network_interface(
                        route_table_id=route_table_id,
                        dest_cidr=route.cidr,
                        network_interface=route.target
                    )
                elif route.get_target_type() == 'VpcPeeringConnectionId':
                    response = self.create_route_to_vpc_peering_connection(
                        route_table_id=route_table_id,
                        dest_cidr=route.cidr,
                        vpc_peering_connection=route.target
                    )
            elif route.get_cidr_type() == 'DestinationIpv6CidrBlock':
                if route.get_target_type() == 'EgressOnlyInternetGatewayId':
                    response = self.create_route_to_egress_internet_gateway_ipv6(
                        route_table_id=route_table_id,
                        dest_cidr_ipv6=route.cidr_ipv6,
                        egress_only_internet_gateway=route.target
                    )
                elif route.get_target_type() == 'GatewayId':
                    response = self.create_route_to_gateway_ipv6(
                        route_table_id=route_table_id,
                        dest_cidr_ipv6=route.cidr_ipv6,
                        gateway_id=route.target
                    )
                elif route.get_target_type() == 'InstanceId':
                    response = self.create_route_to_instance_ipv6(
                        route_table_id=route_table_id,
                        dest_cidr_ipv6=route.cidr_ipv6,
                        instance_id=route.target
                    )
                elif route.get_target_type() == 'NatGatewayId':
                    response = self.create_route_to_nat_gateway_ipv6(
                        route_table_id=route_table_id,
                        dest_cidr_ipv6=route.cidr_ipv6,
                        nat_gateway=route.target
                    )
                elif route.get_target_type() == 'TransitGatewayId':
                    response = self.create_route_to_transit_gateway_ipv6(
                        route_table_id=route_table_id,
                        dest_cidr_ipv6=route.cidr_ipv6,
                        transit_gateway=route.target
                    )
                elif route.get_target_type() == 'LocalGatewayId':
                    response = self.create_route_to_local_gateway_ipv6(
                        route_table_id=route_table_id,
                        dest_cidr_ipv6=route.cidr_ipv6,
                        local_gateway=route.target
                    )
                elif route.get_target_type() == 'NetworkInterfaceId':
                    response = self.create_route_to_network_interface_ipv6(
                        route_table_id=route_table_id,
                        dest_cidr_ipv6=route.cidr_ipv6,
                        network_interface=route.target
                    )
                elif route.get_target_type() == 'VpcPeeringConnectionId':
                    response = self.create_route_to_vpc_peering_connection_ipv6(
                        route_table_id=route_table_id,
                        dest_cidr_ipv6=route.cidr_ipv6,
                        vpc_peering_connection=route.target
                    )
        except ClientError as exc:
            msg = 'Problem creating route in route table [{i}]: {r}'.format(i=route_table_id, r=str(route))
            raise EC2UtilError(msg) from exc
        if not response:
            raise EC2UtilError('Response not received for adding route to [{i}]: {r}'.format(
                i=route_table_id, r=str(route)))
        if 'Return' not in response.keys():
            raise EC2UtilError('Return not found in response: {r}'.format(r=str(response)))
        if response['Return'] == 'True':
            return True
        return False

    def add_routes(self, route_table_id, routes):
        """Adds the list of routes to the route table

        :param route_table_id: (str) ID of the route table
        :param routes: (list) of IpRoute objects
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_routes')
        log.info('Adding {n} routes to route table ID: {i}'.format(n=str(len(routes)), i=route_table_id))
        for route in routes:
            self.add_route(route_table_id=route_table_id, route=route)

    def configure_routes(self, route_table_id, desired_routes):
        """Set routes in the route table to match the desired list, deletes ones not on the list

        :param route_table_id: (str) ID of the route table to configure
        :param desired_routes: (list) of IpRoute objects
        :return: True if successful, False otherwise
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.configure_routes')
        if not isinstance(desired_routes, list):
            raise EC2UtilError('routes are expected list, found: {t}'.format(t=desired_routes.__class__.__name__))
        try:
            route_table = self.get_route_table(route_table_id=route_table_id)
        except EC2UtilError as exc:
            msg = 'Problem retrieving route table: {i}'.format(i=route_table_id)
            raise EC2UtilError(msg) from exc

        # Parse permissions into comparable IpPermissions objects
        existing_routes = parse_ip_routes(ip_routes=route_table['Routes'])

        log.info('Existing routes:')
        for existing_route in existing_routes:
            log.info('Existing route: {r}'.format(r=str(existing_route)))
        log.info('Desired routes:')
        for desired_route in desired_routes:
            log.info('Desired route: {r}'.format(r=str(desired_route)))

        # Determine which routes to delete
        delete_routes = []
        for existing_route in existing_routes:
            delete = True
            for desired_route in desired_routes:
                if existing_route == desired_route:
                    delete = False
                    break
            if delete:
                delete_routes.append(existing_route)

        # Determine which routes to add
        add_routes = []
        for desired_route in desired_routes:
            add = True
            for existing_route in existing_routes:
                if desired_route == existing_route:
                    add = False
                    break
            if add:
                add_routes.append(desired_route)

        # Delete routes
        self.delete_routes(route_table_id=route_table_id, routes=delete_routes)

        # Add rules
        self.add_routes(route_table_id=route_table_id, routes=add_routes)
        log.info('Completed configuring rules for route table: {r}'.format(r=route_table_id))
        return True

    def get_eni_id(self, interface=1):
        """Given an interface number, gets the AWS elastic network
        interface associated with the interface.

        :param interface: Integer associated with the interface/device number
        :return: String Elastic Network Interface ID or None if not found
        :raises OSError, AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.get_eni_id')

        # Get the instance-id
        if not self.instance_id:
            msg = 'Instance ID not found for this machine, unable to determine ENI ID'
            raise OSError(msg)
        log.info('Querying instance ID [{i}] to look for ENIs...'.format(i=self.instance_id))
        instance = get_instance(client=self.client, instance_id=self.instance_id)

        # Find the ENI ID
        log.info('Looking for the ENI ID to alias...')
        eni_id = None
        try:
            for network_interface in instance['NetworkInterfaces']:
                if network_interface['Attachment']['DeviceIndex'] == interface:
                    eni_id = network_interface['NetworkInterfaceId']
        except KeyError as exc:
            msg = 'Unable ot find ENI ID instance data: {i}'.format(i=str(instance))
            raise EC2UtilError(msg) from exc
        log.info('Found ENI ID: {e}'.format(e=eni_id))
        return eni_id

    def add_secondary_ip(self, ip_address, interface=1):
        """Adds an IP address as a secondary IP address

        :param ip_address: String IP address to add as a secondary IP
        :param interface: Integer associated to the interface/device number
        :return: None
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_secondary_ip')

        # Get the ENI ID
        eni_id = self.get_eni_id(interface)

        # Verify the ENI ID was found
        if eni_id is None:
            msg = 'Unable to find the corresponding ENI ID for interface: {i}'. \
                format(i=interface)
            log.error(msg)
            raise EC2UtilError(msg)
        else:
            log.info('Found ENI ID: {e}'.format(e=eni_id))

        # Assign the secondary IP address
        log.info('Attempting to assign the secondary IP address...')
        try:
            self.client.assign_private_ip_addresses(
                    NetworkInterfaceId=eni_id,
                    PrivateIpAddresses=[
                        ip_address,
                    ],
                    AllowReassignment=True
            )
        except ClientError as exc:
            msg = 'Unable to assign secondary IP address'
            log.error(msg)
            raise AWSAPIError(msg) from exc
        log.info('Successfully added secondary IP address {s} to ENI ID {e} on interface {i}'.format(
                s=ip_address, e=eni_id, i=interface))

    def associate_elastic_ip(self, allocation_id, interface=1, private_ip=None):
        """Given an elastic IP address and an interface number, associates the
        elastic IP with the interface number on this host.

        :param allocation_id: String ID for the elastic IP
        :param interface: Integer associated to the interface/device number
        :param private_ip: String IP address of the private IP address to
                assign
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.associate_elastic_ip')

        if private_ip is None:
            log.info('No private IP address provided, getting the primary IP'
                     'address on interface {i}...'.format(i=interface))
            private_ip = get_ip_addresses()['eth{i}'.format(i=interface)]

        log.info('Associating Elastic IP {e} on interface {i} on IP {p}'.format(
                e=allocation_id, i=interface, p=private_ip))

        # Get the ENI ID
        log.info('Getting the ENI ID for interface: {i}'.format(i=interface))
        eni_id = self.get_eni_id(interface)

        # Verify the ENI ID was found
        if eni_id is None:
            msg = 'Unable to find the corresponding ENI ID for interface: {i}'. \
                format(i=interface)
            raise EC2UtilError(msg)
        else:
            log.info('Found ENI ID: {e}'.format(e=eni_id))

        # Assign the secondary IP address
        log.info('Attempting to assign the secondary IP address...')
        try:
            response = self.client.associate_address(
                    NetworkInterfaceId=eni_id,
                    AllowReassociation=True,
                    AllocationId=allocation_id,
                    PrivateIpAddress=private_ip
            )
        except ClientError as exc:
            msg = 'Unable to attach elastic IP address {a} to interface {i}'.format(
                    a=allocation_id, i=interface)
            raise EC2UtilError(msg) from exc

        code = response['ResponseMetadata']['HTTPStatusCode']
        if code != 200:
            msg = 'associate_address returned invalid code: {c}'.format(c=code)
            log.error(msg)
            raise EC2UtilError(msg)
        log.info('Successfully associated elastic IP address ID {a} to interface {i} on ENI ID {e}'.format(
                a=allocation_id, i=interface, e=eni_id))

    def associate_elastic_ip_to_instance_id(self, allocation_id, instance_id):
        """Given an elastic IP address and an instance ID, associates the
        elastic IP with the instance

        :param allocation_id: (str) ID for the elastic IP
        :param instance_id: (str) ID of the instance
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.associate_elastic_ip_to_instance_id')

        log.info('Associating Elastic IP {e} to instance: {i}'.format(e=allocation_id, i=instance_id))

        # Assign the secondary IP address
        log.info('Attempting to assign the secondary IP address...')
        try:
            response = self.client.associate_address(
                AllowReassociation=True,
                AllocationId=allocation_id,
                InstanceId=instance_id
            )
        except ClientError as exc:
            msg = 'Unable to attach elastic IP address {a} to instance ID: {i}'.format(a=allocation_id, i=instance_id)
            raise AWSAPIError(msg) from exc

        code = response['ResponseMetadata']['HTTPStatusCode']
        if code != 200:
            msg = 'associate_address returned invalid code: {c}'.format(c=code)
            raise EC2UtilError(msg)
        log.info('Successfully associated elastic IP address ID {a} to instance ID {i}'.format(
            a=allocation_id, i=instance_id))

    def allocate_elastic_ip(self):
        """Allocates an elastic IP address

        :return: Dict with allocation ID and Public IP that were created
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.allocate_elastic_ip')

        # Attempt to allocate a new elastic IP
        log.info('Attempting to allocate an elastic IP...')
        try:
            response = self.client.allocate_address(
                    DryRun=False,
                    Domain='vpc'
            )
        except ClientError as exc:
            msg = 'Unable to allocate a new elastic IP address'
            raise EC2UtilError(msg) from exc

        allocation_id = response['AllocationId']
        public_ip = response['PublicIp']
        log.info('Allocated Elastic IP with ID {a} and Public IP address {p}'.
                 format(a=allocation_id, p=public_ip))

        # Verify the Address was allocated successfully
        log.info('Verifying the elastic IP address was allocated and is available '
                 'for use...')
        ready = False
        verification_timer = [2]*60 + [5]*60 + [10]*18
        num_checks = len(verification_timer)
        for i in range(0, num_checks):
            wait_time = verification_timer[i]
            try:
                self.client.describe_addresses(
                        DryRun=False,
                        AllocationIds=[allocation_id]
                )
            except ClientError as exc:
                log.info('Elastic IP address {p} with Allocation ID {a} is not available for use, trying again in '
                         '{w} sec...\n{e}'.format(p=public_ip, a=allocation_id, w=wait_time, e=str(exc)))
                time.sleep(wait_time)
            else:
                log.info('Elastic IP {p} with Allocation ID {a} is available for use'.format(
                    p=public_ip, a=allocation_id))
                ready = True
                break
        if ready:
            return {'AllocationId': allocation_id, 'PublicIp': public_ip}
        else:
            msg = 'Unable to verify existence of new Elastic IP {p} with Allocation ID: {a}'. \
                format(p=public_ip, a=allocation_id)
            raise EC2UtilError(msg)

    def create_network_interface(self, subnet_id, security_group_list, private_ip_address):
        """Creates a network interface

        :param subnet_id: (str) ID of the subnet
        :param security_group_list: (list) of security group IDs
        :param private_ip_address: (str) IP address to assign to the ENI
        :return: (list)
        :raises: EC2UtilError
        """
        return create_network_interface(
            client=self.client,
            subnet_id=subnet_id,
            security_group_list=security_group_list,
            private_ip_address=private_ip_address
        )

    def attach_new_eni(self, subnet_name, security_group_ids, device_index=2, allocation_id=None, description=''):
        """Creates a new Elastic Network Interface on the Subnet matching the subnet_name, with Security Group
        identified by the security_group_name, then attaches an Elastic IP address if specified in the allocation_id
        parameter, and finally attaches the new ENI to the EC2 instance instance_id at device index device_index.

        :param subnet_name: String name of the subnet
        :param security_group_ids: (list) Security Groups IDs
        :param device_index: Integer device index
        :param allocation_id: String ID of the elastic IP address
        :param description: String description
        :return: None
        :raises: EC2UtilError, AWSAPIError
        """
        log = logging.getLogger(self.cls_logger + '.attach_new_eni')
        log.info('Attempting to attach a new network interface to this instance...')

        # Validate args
        if not isinstance(security_group_ids, list):
            msg = 'security_group_name argument is not a string'
            log.error(msg)
            raise EC2UtilError(msg)
        if not isinstance(subnet_name, str):
            msg = 'subnet_name argument is not a string'
            log.error(msg)
            raise EC2UtilError(msg)
        if allocation_id is not None:
            if not isinstance(allocation_id, str):
                msg = 'allocation_id argument is not a string'
                log.error(msg)
                raise EC2UtilError(msg)
        try:
            device_index = int(device_index)
        except ValueError as exc:
            msg = 'device_index argument is not an int'
            raise EC2UtilError(msg) from exc

        # Get the instance ID and VPC ID for this machine
        if self.instance_id is None or self.vpc_id is None:
            msg = 'Unable to obtain instance ID or VPC ID'
            log.error(msg)
            raise EC2UtilError(msg)

        # Get the subnet ID by name
        log.info('Looking up the subnet ID by name: {n}'.format(n=subnet_name))
        filters = [
            {'Name': 'vpc-id', 'Values': [self.vpc_id]},
            {'Name': 'tag-key', 'Values': ['Name']},
            {'Name': 'tag-value', 'Values': [subnet_name]}]
        try:
            response = self.client.describe_subnets(
                    DryRun=False,
                    Filters=filters
            )
        except ClientError as exc:
            msg = 'Unable to find subnet by name {n} in VPC {v}'.format(n=subnet_name, v=self.vpc_id)
            log.error(msg)
            raise EC2UtilError(msg) from exc

        if len(response['Subnets']) < 1:
            msg = 'No subnets found with name {n} in VPC {v}'.format(n=subnet_name, v=self.vpc_id)
            log.error(msg)
            raise EC2UtilError(msg)
        elif len(response['Subnets']) > 1:
            msg = 'More than 1 subnet found in VPC {v} with name {n}'.format(n=subnet_name, v=self.vpc_id)
            log.error(msg)
            raise EC2UtilError(msg)

        subnet_id = response['Subnets'][0]['SubnetId']
        log.info('Found Subnet ID: {s}'.format(s=subnet_id))

        # Create the ENI
        log.info('Attempting to create the Elastic Network Interface on subnet: {s}, with Security Groups: {g}'.format(
                s=subnet_id, g=security_group_ids))
        try:
            response = self.client.create_network_interface(
                    DryRun=False,
                    SubnetId=subnet_id,
                    Description=description,
                    Groups=security_group_ids)
        except ClientError as exc:
            msg = 'Unable to create a network interface on Subnet {s} using Security Groups {g}'.format(
                    s=subnet_id, g=security_group_ids)
            log.error(msg)
            raise AWSAPIError(msg) from exc

        code = response['ResponseMetadata']['HTTPStatusCode']
        if code != 200:
            msg = 'create_network_interface returned invalid code: {c}'.format(c=code)
            log.error(msg)
            raise AWSAPIError(msg)

        try:
            eni_id = response['NetworkInterface']['NetworkInterfaceId']
        except KeyError as exc:
            msg = 'Unable to parse ENI ID from response: {r}'.format(r=response)
            log.error(msg)
            raise EC2UtilError(msg) from exc
        log.info('Created ENI ID: {eni}'.format(eni=eni_id))

        # Verify the ENI was created successfully
        log.info('Verifying the ENI was created and is available for use...')
        ready = False
        num_checks = 60
        for _ in range(num_checks):
            try:
                self.client.describe_network_interfaces(
                        DryRun=False,
                        NetworkInterfaceIds=[eni_id]
                )
            except ClientError as exc:
                log.info('ENI ID {i} is not available for use, trying again in 1 sec...\n{e}'.format(
                        i=str(eni_id), e=str(exc)))
                time.sleep(2)
            else:
                log.info('ENI ID {eni} is available for use'.format(eni=eni_id))
                ready = True
                break
        if not ready:
            msg = 'Unable to verify existence of new ENI ID: {eni}'.format(eni=eni_id)
            raise EC2UtilError(msg)

        # If an allocation_id is specified, attach the elastic IP to the new ENI
        if allocation_id is not None:
            log.info('Attempting to attach elastic IP {a} to ENI {e}'.format(a=allocation_id, e=eni_id))
            try:
                response = self.client.associate_address(
                        AllocationId=allocation_id,
                        DryRun=False,
                        NetworkInterfaceId=eni_id,
                        AllowReassociation=True)
            except ClientError as exc:
                msg = 'Unable to associate Elastic IP {a} to ENI {eni}'.format(
                        a=allocation_id, eni=eni_id)
                log.error(msg)
                raise AWSAPIError(msg) from exc

            code = response['ResponseMetadata']['HTTPStatusCode']
            if code != 200:
                msg = 'associate_address returned invalid code: {c}'.format(c=code)
                log.error(msg)
                raise AWSAPIError(msg)
            log.info('Successfully attached Elastic IP {a} to ENI ID {eni}'.format(
                    eni=eni_id, a=allocation_id))

        # Attach the ENI to this EC2 instance
        log.info('Attempting to attach ENI ID {eni} to instance ID {i}'.format(
                eni=eni_id, i=self.instance_id))
        try:
            response = self.client.attach_network_interface(
                    DryRun=False,
                    NetworkInterfaceId=eni_id,
                    InstanceId=self.instance_id,
                    DeviceIndex=device_index)
        except ClientError as exc:
            msg = 'Unable to attach ENI ID {eni} to instance {i} at device index {d}'.format(
                    eni=eni_id, i=self.instance_id, d=device_index)
            log.error(msg)
            raise AWSAPIError(msg) from exc

        code = response['ResponseMetadata']['HTTPStatusCode']
        if code != 200:
            msg = 'attach_network_interface returned invalid code: {c}'.format(c=code)
            log.error(msg)
            raise AWSAPIError(msg)
        log.info('Successfully attached ENI ID {eni} to EC2 instance ID {i}'.format(
                eni=eni_id, i=self.instance_id))

    def get_elastic_ips(self, instance_id=None):
        """Returns the elastic IP info for this instance any are
        attached

        :return: (dict) Info about the Elastic IPs
        :raises EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.get_elastic_ips')

        # Ensure instance_id is set
        if not instance_id:
            if self.instance_id:
                instance_id = self.instance_id
            else:
                instance_id = get_instance_id()
        if not instance_id:
            msg = 'Unable to determine instance ID to query for elastic IPs'
            raise EC2UtilError(msg)

        log.info('Querying AWS for info about instance ID {i}...'.format(i=instance_id))
        instance_info = get_instance(client=self.client, instance_id=self.instance_id)

        # Get the list of Public/Elastic IPs for this instance
        public_ips = []
        for network_interface in instance_info['Reservations'][0]['Instances'][0]['NetworkInterfaces']:
            network_interface_id = network_interface['NetworkInterfaceId']
            log.info('Checking ENI: {n}...'.format(n=network_interface_id))
            try:
                public_ips.append(network_interface['Association']['PublicIp'])
            except KeyError:
                log.info('No Public IP found for Network Interface ID: {n}'.format(n=network_interface_id))
            else:
                log.info('Found public IP for Network Interface ID {p}'.format(
                        n=network_interface_id, p=network_interface['Association']['PublicIp']))

        # Return if no Public/Elastic IPs found
        if len(public_ips) == 0:
            log.info('No Elastic IPs found for this instance: {i}'.format(i=instance_id))
            return None
        else:
            log.info('Found Public IPs: {p}'.format(p=public_ips))

        # Get info for each Public/Elastic IP
        try:
            address_info = self.client.describe_addresses(DryRun=False, PublicIps=public_ips)
        except ClientError as exc:
            msg = 'Unable to query AWS to get info for addresses {p}'.format(p=public_ips)
            raise EC2UtilError(msg) from exc
        if not address_info:
            msg = 'No address info return for Public IPs: {p}'.format(p=public_ips)
            raise EC2UtilError(msg)
        return address_info

    def get_elastic_ip_allocation_id(self, elastic_ip_address):
        """Given the elastic IP address, return the allocation ID

        :param elastic_ip_address: (str) IP address
        :return: (str) allocation ID or None
        """
        log = logging.getLogger(self.cls_logger + '.get_elastic_ip_allocation_id')
        log.info('Getting the allocation ID for elastic IP address: [{p}]'.format(p=elastic_ip_address))
        try:
            address_info = self.client.describe_addresses(DryRun=False, PublicIps=[elastic_ip_address])
        except ClientError as exc:
            msg = 'Unable to query AWS to get info for elastic IP address [{p}]'.format(p=elastic_ip_address)
            raise EC2UtilError(msg) from exc
        if not address_info:
            msg = 'No address info return for elastic IP [{p}]'.format(p=elastic_ip_address)
            raise EC2UtilError(msg)
        if 'Addresses' not in address_info.keys():
            raise EC2UtilError('Addresses not found in elastic IP address data: [{d}]'.format(d=str(address_info)))
        for address in address_info['Addresses']:
            if 'PublicIp' not in address.keys():
                continue
            if 'AllocationId' not in address.keys():
                continue
            if address['PublicIp'] == elastic_ip_address:
                log.info('Found allocation ID [{a}] for address [{p}]'.format(
                    a=address['AllocationId'], p=elastic_ip_address))
                return address['AllocationId']
        log.warning('Allocation ID not found for address: [{p}]'.format(p=elastic_ip_address))
        return None

    def disassociate_elastic_ips_from_instance(self, instance_id):
        """For each attached Elastic IP, disassociate it

        :param instance_id: (str) ID of the instance to disassociate the IP(s) from
        :return: None
        :raises AWSAPIError
        """
        log = logging.getLogger(self.cls_logger + '.disassociate_elastic_ips_from_instance')

        try:
            address_info = self.get_elastic_ips(instance_id=instance_id)
        except AWSAPIError as exc:
            msg = 'Unable to determine Elastic IPs on this EC2 instance'
            raise AWSAPIError(msg) from exc

        # Return is no elastic IPs were found
        if not address_info:
            log.info('No elastic IPs found to disassociate')
            return

        # Disassociate each Elastic IP
        for address in address_info['Addresses']:
            if 'AssociationId' not in address.keys():
                continue
            if 'PublicIp' not in address.kesys():
                continue
            association_id = address['AssociationId']
            public_ip = address['PublicIp']
            log.info('Attempting to disassociate address {p} from Association ID: {a}'.format(
                p=public_ip, a=association_id))
            try:
                self.client.disassociate_address(PublicIp=public_ip, AssociationId=association_id)
            except ClientError as exc:
                msg = 'There was a problem disassociating Public IP {p} from Association ID {a}'.format(
                    p=public_ip, a=association_id)
                raise AWSAPIError(msg) from exc
            log.info('Successfully disassociated Public IP: {p}'.format(p=public_ip))

    def disassociate_elastic_ips(self):
        """For each attached Elastic IP, disassociate it

        :return: None
        :raises AWSAPIError
        """
        log = logging.getLogger(self.cls_logger + '.disassociate_elastic_ips')

        try:
            address_info = self.get_elastic_ips()
        except AWSAPIError as exc:
            msg = 'Unable to determine Elastic IPs on this EC2 instance'
            raise AWSAPIError(msg) from exc

        # Return is no elastic IPs were found
        if not address_info:
            log.info('No elastic IPs found to disassociate')
            return

        # Disassociate each Elastic IP
        for address in address_info['Addresses']:
            association_id = address['AssociationId']
            public_ip = address['PublicIp']
            log.info('Attempting to disassociate address {p} from Association ID: {a}'.format(
                    p=public_ip, a=association_id))
            try:
                self.client.disassociate_address(PublicIp=public_ip, AssociationId=association_id)
            except ClientError as exc:
                msg = 'There was a problem disassociating Public IP {p} from Association ID {a}'.format(
                        p=public_ip, a=association_id)
                log.error(msg)
                raise AWSAPIError(msg) from exc
            else:
                log.info('Successfully disassociated Public IP: {p}'.format(p=public_ip))

    def create_security_group(self, name, description='', vpc_id=None):
        """Creates a new Security Group with the specified name,
        description, in the specified vpc_id if provided.  If
        vpc_id is not provided, use self.vpc_id

        :param name: (str) Security Group Name
        :param description: (str) Security Group Description
        :param vpc_id: (str) VPC ID to create the Security Group
        :return: (str) Security Group ID
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_security_group')
        # Validate args
        if not isinstance(name, str):
            msg = 'name argument is not a string'
            raise EC2UtilError(msg)
        if not isinstance(description, str):
            msg = 'description argument is not a string'
            raise EC2UtilError(msg)
        if not vpc_id:
            vpc_id = self.vpc_id
        if not vpc_id:
            raise EC2UtilError('Unable to determine VPC ID to use to create the Security Group')

        # See if a Security Group already exists with the same name
        log.info('Checking for an existing security group with name {n} in VPC: {v}'.format(n=name, v=vpc_id))
        filters = [{
                'Name': 'vpc-id',
                'Values': [vpc_id]
            },
            {
                'Name': 'group-name',
                'Values': [name]
            }]
        try:
            response = self.client.describe_security_groups(DryRun=False, Filters=filters)
        except ClientError as exc:
            msg = 'Unable to query Security Groups to determine if {n} exists in VPC ID {v}'.format(
                n=name, v=vpc_id)
            log.error(msg)
            raise AWSAPIError(msg) from exc
        else:
            log.debug('Found Security Group: {r}'.format(r=response))
            if len(response['SecurityGroups']) == 1:
                log.info('Found an existing security group with name {n} in VPC: {v}'.format(n=name, v=vpc_id))
                try:
                    group_id = response['SecurityGroups'][0]['GroupId']
                except KeyError as exc:
                    msg = 'Unable to determine the Security Group GroupId from response: {r}'.format(
                        r=response)
                    log.error(msg)
                    raise AWSAPIError(msg) from exc
                else:
                    log.info('Found existing Security Group with GroupId: {g}'.format(g=group_id))
                    return group_id
            else:
                log.info('No existing Security Group with name {n} found in VPC: {v}'.format(n=name, v=vpc_id))

        # Create a new Security Group
        log.info('Attempting to create a Security Group with name <{n}>, description <{d}>, in VPC: {v}'.format(
            n=name, d=description, v=vpc_id))
        try:
            response = self.client.create_security_group(
                DryRun=False,
                GroupName=name,
                Description=description,
                VpcId=vpc_id
            )
        except ClientError as exc:
            msg = 'Unable to create Security Group with name [{n}] in VPC: {v}'.format(n=name, v=vpc_id)
            raise EC2UtilError(msg) from exc
        log.info('Successfully created Security Group <{n}> in VPC: {v}'.format(n=name, v=vpc_id))
        if 'GroupId' not in response.keys():
            raise EC2UtilError('GroupId not found in response: {r}'.format(r=str(response)))
        security_group_id = response['GroupId']

        # Ensure the security group ID exists
        if not self.ensure_exists(resource_id=security_group_id):
            raise EC2UtilError('Problem finding security group ID after timeout: {i}'.format(i=security_group_id))

        # Set the name tag
        if not self.create_name_tag(resource_id=security_group_id, resource_name=name):
            raise EC2UtilError('Problem setting name tag for security group ID: {i}'.format(i=security_group_id))
        return security_group_id

    def delete_security_group(self, security_group_id):
        """Deletes the security group

        :param security_group_id: (str) ID of the security group
        :return: (bool) True if successful, false otherwise
        """
        log = logging.getLogger(self.cls_logger + '.delete_security_group')
        log.info('Deleting security group ID: [{g}]'.format(g=security_group_id))
        try:
            response = self.client.delete_security_group(DryRun=False, GroupId=security_group_id)
        except ClientError as exc:
            msg = 'Problem deleting security group ID: [{g}]'.format(g=security_group_id)
            raise EC2UtilError(msg) from exc
        if 'Return' not in response.keys():
            msg = 'Return not found in response: {r}'.format(r=str(response))
            raise EC2UtilError(msg)
        if 'GroupId' not in response.keys():
            msg = 'GroupId not found in response: {r}'.format(r=str(response))
            raise EC2UtilError(msg)
        return response['Return']

    def list_security_groups(self):
        """Lists security groups in the account/region

        :return: (list) Security Group data
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.list_security_groups')

        # Get a list of security groups in the VPC
        log.info('Querying for a list of security groups in this account/region')
        try:
            response = self.client.describe_security_groups(DryRun=False)
        except ClientError as exc:
            msg = 'Problem describing security groups'
            raise EC2UtilError(msg) from exc
        if 'SecurityGroups' not in response.keys():
            msg = 'SecurityGroups not found in response: {r}'.format(r=str(response))
            raise EC2UtilError(msg)
        return response['SecurityGroups']

    def list_security_groups_in_vpc(self, vpc_id=None):
        """Lists security groups in the VPC.  If vpc_id is not provided, use self.vpc_id

        :param vpc_id: (str) VPC ID to list security groups for
        :return: (list) Security Group data
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.list_security_groups_in_vpc')
        if not vpc_id:
            if self.vpc_id:
                vpc_id = self.vpc_id
            else:
                msg = 'vpc_id arg not provided, and self.vpc_id not determined'
                raise EC2UtilError(msg)

        # Create a filter on the VPC ID
        filters = [
            {
                'Name': 'vpc-id',
                'Values': [vpc_id]
            }
        ]

        # Get a list of security groups in the VPC
        log.info('Querying for a list of security groups in VPC ID: {v}'.format(v=vpc_id))
        try:
            response = self.client.describe_security_groups(DryRun=False, Filters=filters)
        except ClientError as exc:
            msg = 'Problem describing security groups in VPC ID: {v}'.format(v=vpc_id)
            raise EC2UtilError(msg) from exc
        if 'SecurityGroups' not in response.keys():
            msg = 'SecurityGroups not found in response: {r}'.format(r=str(response))
            raise EC2UtilError(msg)
        return response['SecurityGroups']

    def add_single_security_group_egress_rule(self, security_group_id, add_rule):
        """Adds a single security group rule

        :param security_group_id: (str) Security Group ID
        :param add_rule: (IpPermission) IpPermissions object to add
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_single_security_group_egress_rule')

        if not isinstance(add_rule, IpPermission):
            raise EC2UtilError('add_rule arg must be type IpPermission, found: {t}'.format(
                t=add_rule.__class__.__name__))

        log.info('Adding egress rule to security group {g}: {r}'.format(g=security_group_id, r=str(add_rule)))
        try:
            self.client.authorize_security_group_egress(
                DryRun=False,
                GroupId=security_group_id,
                IpPermissions=[add_rule.get_json()])
        except ClientError as exc:
            raise EC2UtilError('Unable to add egress rule to security group {g}: {r}\n{e}'.format(
                g=security_group_id, r=str(add_rule), e=str(exc))) from exc

    def add_single_security_group_ingress_rule(self, security_group_id, add_rule):
        """Adds a single security group rule

        :param security_group_id: (str) Security Group ID
        :param add_rule: (IpPermission) IpPermissions object to add
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_single_security_group_ingress_rule')

        if not isinstance(add_rule, IpPermission):
            raise EC2UtilError('add_rule arg must be type IpPermission, found: {t}'.format(
                t=add_rule.__class__.__name__))

        log.info('Adding ingress rule to security group {g}: {r}'.format(g=security_group_id, r=str(add_rule)))
        try:
            self.client.authorize_security_group_ingress(
                DryRun=False,
                GroupId=security_group_id,
                IpPermissions=[add_rule.get_json()])
        except ClientError as exc:
            raise EC2UtilError('Unable to add ingress rule to security group {g}: {r}\n{e}'.format(
                g=security_group_id, r=str(add_rule), e=str(exc))) from exc

    def add_security_group_egress_rules(self, security_group_id, add_rules):
        """Revokes a list of security group rules

        :param security_group_id: (str) Security Group ID
        :param add_rules: (list) List of IpPermission objects to add
        :return: (bool) True if all rules added successfully, False otherwise
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_security_group_egress_rules')

        # Return True if none of the rules fail to add
        success = True

        if not isinstance(add_rules, list):
            raise EC2UtilError('add_rules arg must be type list, found: {t}'.format(
                t=add_rules.__class__.__name__))

        if len(add_rules) < 1:
            log.info('No egress rules provided to add to security group: {g}'.format(g=security_group_id))
            return success

        log.info('Adding {n} egress rules to security group: {g}'.format(n=str(len(add_rules)), g=security_group_id))
        for add_rule in add_rules:
            try:
                self.add_single_security_group_egress_rule(
                    security_group_id=security_group_id,
                    add_rule=add_rule
                )
            except EC2UtilError as exc:
                log.warning('Failed to add egress rule to security group {g}: {r}\n{e}'.format(
                    g=security_group_id, r=str(add_rule), e=str(exc)))
                success = False
        return success

    def add_security_group_ingress_rules(self, security_group_id, add_rules):
        """Revokes a list of security group rules

        :param security_group_id: (str) Security Group ID
        :param add_rules: (list) List of IpPermission objects to add
        :return: (bool) True if all rules added successfully, False otherwise
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_security_group_ingress_rules')
        
        # Return True if none of the rules fail to add
        success = True

        if not isinstance(add_rules, list):
            raise EC2UtilError('add_rules arg must be type list, found: {t}'.format(
                t=add_rules.__class__.__name__))

        if len(add_rules) < 1:
            log.info('No ingress rules provided to add to security group: {g}'.format(g=security_group_id))
            return success

        log.info('Adding {n} ingress rules to security group: {g}'.format(n=str(len(add_rules)), g=security_group_id))
        for add_rule in add_rules:
            try:
                self.add_single_security_group_ingress_rule(
                    security_group_id=security_group_id,
                    add_rule=add_rule
                )
            except EC2UtilError as exc:
                log.warning('Failed to add ingress rule to security group {g}: {r}\n{e}'.format(
                    g=security_group_id, r=str(add_rule), e=str(exc)))
                success = False
        return success

    def revoke_single_security_group_egress_rule(self, security_group_id, revoke_rule):
        """Revokes a single security group rule

        :param security_group_id: (str) Security Group ID
        :param revoke_rule: (IpPermission) IpPermissions object to revoke
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.revoke_single_security_group_egress_rule')

        if not isinstance(revoke_rule, IpPermission):
            raise EC2UtilError('revoke_rule arg must be type IpPermission, found: {t}'.format(
                t=revoke_rule.__class__.__name__))

        log.info('Revoking egress rule from security group {g}: {r}'.format(g=security_group_id, r=str(revoke_rule)))
        try:
            self.client.revoke_security_group_egress(
                DryRun=False,
                GroupId=security_group_id,
                IpPermissions=[revoke_rule.get_json()])
        except ClientError as exc:
            raise EC2UtilError('Unable to revoke egress rule from security group {g}: {r}'.format(
                g=security_group_id, r=str(revoke_rule))) from exc

    def revoke_single_security_group_ingress_rule(self, security_group_id, revoke_rule):
        """Revokes a single security group rule

        :param security_group_id: (str) Security Group ID
        :param revoke_rule: (IpPermission) IpPermissions object to revoke
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.revoke_single_security_group_ingress_rule')

        if not isinstance(revoke_rule, IpPermission):
            raise EC2UtilError('revoke_rule arg must be type IpPermission, found: {t}'.format(
                t=revoke_rule.__class__.__name__))

        log.info('Revoking ingress rule from security group {g}: {r}'.format(g=security_group_id, r=str(revoke_rule)))
        try:
            self.client.revoke_security_group_ingress(
                DryRun=False,
                GroupId=security_group_id,
                IpPermissions=[revoke_rule.get_json()])
        except ClientError as exc:
            raise EC2UtilError('Unable to revoke ingress rule from security group {g}: {r}'.format(
                g=security_group_id, r=str(revoke_rule))) from exc

    def revoke_security_group_egress_rules(self, security_group_id, revoke_rules):
        """Revokes a list of security group rules

        :param security_group_id: (str) Security Group ID
        :param revoke_rules: (list) List of IpPermission objects to revoke
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.revoke_security_group_egress_rules')

        if not isinstance(revoke_rules, list):
            raise EC2UtilError('revoke_rules arg must be type list, found: {t}'.format(
                t=revoke_rules.__class__.__name__))

        if len(revoke_rules) < 1:
            log.info('No egress rules provided to revoke from security group: {g}'.format(g=security_group_id))
            return

        log.info('Revoking {n} egress rules from security group: {g}'.format(
            n=str(len(revoke_rules)), g=security_group_id))
        for revoke_rule in revoke_rules:
            try:
                self.revoke_single_security_group_egress_rule(
                    security_group_id=security_group_id,
                    revoke_rule=revoke_rule
                )
            except EC2UtilError as exc:
                log.warning('Failed to revoke egress rule from security group {g}: {r}\n{e}'.format(
                    g=security_group_id, r=str(revoke_rule), e=str(exc)))

    def revoke_security_group_ingress_rules(self, security_group_id, revoke_rules):
        """Revokes a list of security group rules

        :param security_group_id: (str) Security Group ID
        :param revoke_rules: (list) List of IpPermission objects to revoke
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.revoke_security_group_ingress_rules')

        if not isinstance(revoke_rules, list):
            raise EC2UtilError('revoke_rules arg must be type list, found: {t}'.format(
                t=revoke_rules.__class__.__name__))

        if len(revoke_rules) < 1:
            log.info('No ingress rules provided to revoke from security group: {g}'.format(g=security_group_id))
            return

        log.info('Revoking {n} ingress rules from security group: {g}'.format(
            n=str(len(revoke_rules)), g=security_group_id))
        for revoke_rule in revoke_rules:
            try:
                self.revoke_single_security_group_ingress_rule(
                    security_group_id=security_group_id,
                    revoke_rule=revoke_rule
                )
            except EC2UtilError as exc:
                log.warning('Failed to revoke ingress rule from security group {g}: {r}\n{e}'.format(
                    g=security_group_id, r=str(revoke_rule), e=str(exc)))

    def get_security_group(self, security_group_id):
        """Gets a list of IpPermission objects from the security group's egress rules

        :param security_group_id: (str) Security Group ID
        :return: (dict) security group info
        :raises: AWSAPIError
        """
        log = logging.getLogger(self.cls_logger + '.get_security_group')
        # Validate args
        if not isinstance(security_group_id, str):
            raise EC2UtilError('security_group_id argument is not a string')
        log.info('Getting Security Group ID {g}...'.format(g=security_group_id))
        try:
            security_group_info = self.client.describe_security_groups(DryRun=False, GroupIds=[security_group_id])
        except ClientError as exc:
            msg = 'Unable to query AWS for Security Group ID: {g}'.format(g=security_group_id)
            raise AWSAPIError(msg) from exc
        return security_group_info

    def get_security_group_egress_rules(self, security_group_id):
        """Gets a list of IpPermission objects from the security group's egress rules

        :param security_group_id: (str) Security Group ID
        :return: (list) IpPermission objects
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.configure_security_group_egress')
        log.info('Getting egress rules for security group: {i}'.format(i=security_group_id))
        security_group_info = self.get_security_group(security_group_id=security_group_id)
        try:
            existing_egress_rules = security_group_info['SecurityGroups'][0]['IpPermissionsEgress']
        except KeyError as exc:
            msg = 'Unable to get list of egress rules for Security Group ID: {g}'.format(
                g=security_group_id)
            raise AWSAPIError(msg) from exc

        # Parse permissions into comparable IpPermissions objects
        return parse_ip_permissions(existing_egress_rules)

    def get_security_group_ingress_rules(self, security_group_id):
        """Gets a list of IpPermission objects from the security group's ingess rules

        :param security_group_id: (str) Security Group ID
        :return: (list) IpPermission objects
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.get_security_group_ingress_rules')
        log.info('Getting ingress rules for security group: {i}'.format(i=security_group_id))
        security_group_info = self.get_security_group(security_group_id=security_group_id)
        try:
            existing_ingress_rules = security_group_info['SecurityGroups'][0]['IpPermissions']
        except KeyError as exc:
            msg = 'Unable to get list of ingress rules for Security Group ID: {g}'.format(
                g=security_group_id)
            raise AWSAPIError(msg) from exc

        # Parse permissions into comparable IpPermissions objects
        return parse_ip_permissions(existing_ingress_rules)

    def configure_security_group_egress(self, security_group_id, desired_egress_rules):
        """Configures the security group ID allowing access
        only to the specified CIDR blocks, for the specified
        port number.

        :param security_group_id: (str) Security Group ID
        :param desired_egress_rules: (list) List of IpPermissions as described in AWS boto3 docs
        :return: (bool) True if all rules configured successfully, False otherwise
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.configure_security_group_egress')
        # Validate args
        if not isinstance(security_group_id, str):
            raise EC2UtilError('security_group_id argument is not a string')
        if not isinstance(desired_egress_rules, list):
            raise EC2UtilError('desired_egress_rules argument is not a list')

        # Get the security group egress permissions
        existing_ip_perms = self.get_security_group_egress_rules(security_group_id=security_group_id)

        log.info('Existing egress IP permissions:')
        for existing_ip_perm in existing_ip_perms:
            log.info('Existing egress IP permission: {p}'.format(p=str(existing_ip_perm)))
        log.info('Desired egress IP permissions:')
        for desired_egress_rule in desired_egress_rules:
            log.info('Desired egress IP permission: {p}'.format(p=str(desired_egress_rule)))

        # Determine which rules to revoke
        revoke_ip_perms = []
        for existing_ip_perm in existing_ip_perms:
            revoke = True
            for desired_ip_perm in desired_egress_rules:
                if existing_ip_perm == desired_ip_perm:
                    revoke = False
            if revoke:
                revoke_ip_perms.append(existing_ip_perm)

        # Determine which rules to add
        add_ip_perms = []
        for desired_ip_perm in desired_egress_rules:
            add = True
            for existing_ip_perm in existing_ip_perms:
                if desired_ip_perm == existing_ip_perm:
                    add = False
            if add:
                add_ip_perms.append(desired_ip_perm)

        # Revoke rules
        self.revoke_security_group_egress_rules(security_group_id=security_group_id, revoke_rules=revoke_ip_perms)

        # Add rules
        result = self.add_security_group_egress_rules(security_group_id=security_group_id, add_rules=add_ip_perms)
        log.info('Completed configuring egress rules for security group: {g}'.format(g=security_group_id))
        return result

    def configure_security_group_ingress(self, security_group_id, desired_ingress_rules):
        """Configures the security group ID allowing access
        only to the specified CIDR blocks, for the specified
        port number.

        :param security_group_id: (str) Security Group ID
        :param desired_ingress_rules: (list) List of IpPermissions as described in AWS boto3 docs
        :return: (bool) True if all rules configured successfully, False otherwise
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.configure_security_group_ingress')
        # Validate args
        if not isinstance(security_group_id, str):
            raise EC2UtilError('security_group_id argument is not a string')
        if not isinstance(desired_ingress_rules, list):
            raise EC2UtilError('desired_egress_rules argument is not a list')

        # Get the security group ingress permissions
        existing_ip_perms = self.get_security_group_ingress_rules(security_group_id=security_group_id)

        log.info('Existing ingress IP permissions:')
        for existing_ip_perm in existing_ip_perms:
            log.info('Existing ingress IP permission: {p}'.format(p=str(existing_ip_perm)))
        log.info('Desired ingress IP permissions:')
        for desired_egress_rule in desired_ingress_rules:
            log.info('Desired ingress IP permission: {p}'.format(p=str(desired_egress_rule)))

        # Determine which rules to revoke
        revoke_ip_perms = []
        for existing_ip_perm in existing_ip_perms:
            revoke = True
            for desired_ip_perm in desired_ingress_rules:
                if existing_ip_perm == desired_ip_perm:
                    revoke = False
            if revoke:
                revoke_ip_perms.append(existing_ip_perm)

        # Determine which rules to add
        add_ip_perms = []
        for desired_ip_perm in desired_ingress_rules:
            add = True
            for existing_ip_perm in existing_ip_perms:
                if desired_ip_perm == existing_ip_perm:
                    add = False
            if add:
                add_ip_perms.append(desired_ip_perm)

        # Revoke rules
        self.revoke_security_group_ingress_rules(security_group_id=security_group_id, revoke_rules=revoke_ip_perms)

        # Add rules
        result = self.add_security_group_ingress_rules(security_group_id=security_group_id, add_rules=add_ip_perms)
        log.info('Completed configuring ingress rules for security group: {g}'.format(g=security_group_id))
        return result

    def configure_security_group_ingress_legacy(self, security_group_id, port, desired_cidr_blocks, protocol='tcp'):
        """Configures the security group ID allowing access
        only to the specified CIDR blocks, for the specified
        port number.

        :param security_group_id: (str) Security Group ID
        :param port: (str) Port number
        :param desired_cidr_blocks: (list) List of desired CIDR
               blocks, e.g., 192.168.1.2/32
        :param protocol: (str) protocol tcp | udp | icmp | all
        :return: None
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.configure_security_group_ingress')
        # Validate args
        if not isinstance(security_group_id, str):
            raise EC2UtilError('security_group_id argument is not a string')
        if not isinstance(desired_cidr_blocks, list):
            raise EC2UtilError('desired_cidr_blocks argument is not a list')
        if not isinstance(protocol, str):
            raise EC2UtilError('protocol argument is not a str')
        log.info('Configuring Security Group ID {g} to allow protocol {o} on port {p}: {r}'.format(
            g=security_group_id, p=port, o=protocol, r=desired_cidr_blocks
        ))
        log.debug('Querying AWS for info on Security Group ID: {g}...'.format(g=security_group_id))
        try:
            security_group_info = self.client.describe_security_groups(DryRun=False, GroupIds=[security_group_id])
        except ClientError as exc:
            msg = 'Unable to query AWS for Security Group ID: {g}'.format(g=security_group_id)
            raise AWSAPIError(msg) from exc
        else:
            log.debug('Found Security Group: {g}'.format(g=security_group_info))
        try:
            ingress_rules = security_group_info['SecurityGroups'][0]['IpPermissions']
        except KeyError as exc:
            msg = 'Unable to get list of ingress rules for Security Group ID: {g}'.format(
                g=security_group_id)
            raise AWSAPIError(msg) from exc
        else:
            log.debug('Found ingress rules: {r}'.format(r=ingress_rules))

        # Evaluate each rule against the provided port and IP address list
        log.debug('Setting ingress rules...')
        for ingress_rule in ingress_rules:
            log.debug('Evaluating ingress rule: {r}'.format(r=ingress_rule))
            if ingress_rule['ToPort'] != int(port):
                log.debug('Skipping rule not matching port: {p}'.format(p=port))
                continue
            log.info('Removing existing rules from Security Group {g} for port: {p}...'.format(
                g=security_group_id, p=port))
            try:
                self.client.revoke_security_group_ingress(
                    DryRun=False,
                    GroupId=security_group_id,
                    IpPermissions=[ingress_rule])
            except ClientError as exc:
                msg = 'Unable to remove existing Security Group rules for port {p} from Security Group: ' \
                      '{g}'.format(p=port, g=security_group_id)
                raise AWSAPIError(msg) from exc

        # Build ingress rule based on the provided list of CIDR blocks
        if protocol == 'all':
            desired_ip_permissions = [
                {
                    'IpProtocol': -1,
                    'UserIdGroupPairs': [],
                    'IpRanges': [],
                    'PrefixListIds': []
                }
            ]
        else:
            desired_ip_permissions = [
                {
                    'IpProtocol': protocol,
                    'FromPort': int(port),
                    'ToPort': int(port),
                    'UserIdGroupPairs': [],
                    'IpRanges': [],
                    'PrefixListIds': []
                }
            ]

        # Add IP rules
        for desired_cidr_block in desired_cidr_blocks:
            log.debug('Adding ingress for CIDR block: {b}'.format(b=desired_cidr_block))
            cidr_block_entry = {
                'CidrIp': desired_cidr_block
            }
            desired_ip_permissions[0]['IpRanges'].append(cidr_block_entry)

        # Add the ingress rule
        log.debug('Adding ingress rule: {r}'.format(r=desired_ip_permissions))
        try:
            self.client.authorize_security_group_ingress(
                DryRun=False,
                GroupId=security_group_id,
                IpPermissions=desired_ip_permissions
            )
        except ClientError as exc:
            msg = 'Unable to authorize Security Group ingress rule for Security Group {g}: {r}'.format(
                g=security_group_id, r=desired_ip_permissions)
            raise AWSAPIError(msg) from exc
        else:
            log.info('Successfully added ingress rule for Security Group {g} on port: {p}'.format(
                g=security_group_id, p=port))

    def revoke_security_group_ingress(self, security_group_id, ingress_rules):
        """Revokes all ingress rules for a security group

        :param security_group_id: (str) Security Group ID
        :param ingress_rules: (list) List of IP permissions (see AWS API docs re: IpPermissions)
        :return: None
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.revoke_security_group_ingress')
        log.info('Revoking ingress rules from security group: {g}'.format(g=security_group_id))
        try:
            self.client.revoke_security_group_ingress(
                DryRun=False,
                GroupId=security_group_id,
                IpPermissions=ingress_rules)
        except ClientError as exc:
            msg = 'Unable to remove existing Security Group rules for port from Security Group: {g}'.format(
                g=security_group_id)
            raise AWSAPIError(msg) from exc

    def revoke_security_group_egress(self, security_group_id, egress_rules):
        """Revokes all egress rules for a security group

        :param security_group_id: (str) Security Group ID
        :param egress_rules: (list) List of IP permissions (see AWS API docs re: IpPermissions)
        :return: None
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.revoke_security_group_egress')
        log.info('Revoking egress rules from security group: {g}'.format(g=security_group_id))
        try:
            self.client.revoke_security_group_ingress(
                DryRun=False,
                GroupId=security_group_id,
                IpPermissions=egress_rules)
        except ClientError as exc:
            msg = 'Unable to remove existing Security Group rules for port from Security Group: {g}'.format(
                g=security_group_id)
            raise AWSAPIError(msg) from exc

    def revoke_security_group_rules(self, security_group_id):
        """Revoke all security group ingress and egress rules

        :param security_group_id: (str) ID of the security group
        :return: (tuple) ingress rules, egress rules
        :raises: EC2UtilError
        """
        ingress_rules = self.get_security_group_ingress_rules(security_group_id=security_group_id)
        egress_rules = self.get_security_group_egress_rules(security_group_id=security_group_id)
        self.revoke_security_group_ingress_rules(
            security_group_id=security_group_id,
            revoke_rules=ingress_rules
        )
        self.revoke_security_group_egress_rules(
            security_group_id=security_group_id,
            revoke_rules=egress_rules
        )
        return ingress_rules, egress_rules

    def verify_security_groups_in_vpc(self, security_group_id_list, vpc_id):
        """Determines if the provided list of security groups reside in the VPC
        
        :param security_group_id_list: (list) of security group IDs
        :param vpc_id: (str) ID of the VPC 
        :return: True if all security groups IDs listed live in the provided VPC
        """
        log = logging.getLogger(self.cls_logger + '.verify_security_groups_in_vpc')
        # Ensure the security group ID is in the provided VPC ID
        try:
            vpc_sgs = self.list_security_groups_in_vpc(vpc_id=vpc_id)
        except EC2UtilError as exc:
            msg = 'Problem listing security groups in VPC ID: {i}'.format(i=vpc_id)
            raise EC2UtilError(msg) from exc
        for security_group_id in security_group_id_list:
            found_in_vpc = False
            for vpc_sg in vpc_sgs:
                if 'GroupId' not in vpc_sg.keys():
                    log.warning('GroupId not found in security group data: {s}'.format(s=str(vpc_sg)))
                    return False
                if 'VpcId' not in vpc_sg.keys():
                    log.warning('VpcId not found in subnet data: {s}'.format(s=str(vpc_sg)))
                    return False
                if vpc_sg['GroupId'] == security_group_id:
                    if vpc_sg['VpcId'] != vpc_id:
                        msg = 'Security Group ID [{s}] found in VPC [{f}] not in provided VPC: {v}'.format(
                            s=security_group_id, f=vpc_sg['VpcId'], v=vpc_id)
                        log.warning(msg)
                        return False
                    else:
                        log.info('Found security group {s} in provided VPC ID: {v}'.format(
                            s=security_group_id, v=vpc_id))
                        found_in_vpc = True
            if not found_in_vpc:
                log.warning('Security group {s} not found in VPC ID: {v}'.format(s=security_group_id, v=vpc_id))
                return False
        return True

    def launch_instance(self, ami_id, key_name, subnet_id, security_group_id=None, security_group_list=None,
                        user_data_script_path=None, user_data_script_contents=None, instance_type='c5a.large',
                        root_volume_location='/dev/xvda', root_volume_size_gb=100):
        """Launches an EC2 instance with the specified parameters

        :param ami_id: (str) ID of the AMI to launch from
        :param key_name: (str) Name of the key-pair to use
        :param subnet_id: (str) IF of the VPC subnet to attach the instance to
        :param security_group_id: (str) ID of the security group, of not provided the default will be applied
                appended to security_group_list if provided
        :param security_group_list: (list) of IDs of the security group, if not provided the default will be applied
        :param user_data_script_path: (str) Path to the user-data script to run
        :param user_data_script_contents: (str) contents of the user-data script to run
        :param instance_type: (str) Instance Type (e.g. t2.micro)
        :param root_volume_location: (str) The device name for the root volume
        :param root_volume_size_gb: (int) Size of the root volume in GB
        :return: (dict) Instance info
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.launch_instance')
        log.info('Launching with AMI ID: {a}'.format(a=ami_id))
        log.info('Launching with Key Pair: {k}'.format(k=key_name))

        if security_group_list:
            if not isinstance(security_group_list, list):
                raise EC2UtilError('security_group_list must be a list')

        if security_group_id and security_group_list:
            security_group_list.append(security_group_id)
        elif security_group_id and not security_group_list:
            security_group_list = [security_group_id]
            log.info('Launching with security group list: {s}'.format(s=security_group_list))
        user_data = None
        if user_data_script_path:
            if os.path.isfile(user_data_script_path):
                with open(user_data_script_path, 'r') as f:
                    user_data = f.read()
        elif user_data_script_contents:
            user_data = user_data_script_contents
        monitoring = {'Enabled': False}
        block_device_mappings = [
            {
                'DeviceName': root_volume_location,
                'Ebs': {
                    'VolumeSize': root_volume_size_gb,
                    'DeleteOnTermination': True,
                    'Encrypted': False
                }
            }
        ]
        log.info('Attempting to launch the EC2 instance now...')
        try:
            response = self.client.run_instances(
                DryRun=False,
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                KeyName=key_name,
                SecurityGroupIds=security_group_list,
                UserData=user_data,
                InstanceType=instance_type,
                Monitoring=monitoring,
                SubnetId=subnet_id,
                InstanceInitiatedShutdownBehavior='stop',
                BlockDeviceMappings=block_device_mappings
            )
        except ClientError as exc:
            msg = 'There was a problem launching the EC2 instance\n{e}'.format(e=str(exc))
            raise EC2UtilError(msg) from exc
        instance_id = response['Instances'][0]['InstanceId']
        output = {
            'InstanceId': instance_id,
            'InstanceInfo': response['Instances'][0]
        }
        return output

    def launch_instance_onto_dedicated_host(self, ami_id, host_id, key_name, instance_type, network_interfaces,
                                            os_type, nat=False):
        """Launches an EC2 instance with the specified parameters, onto a dedicated host

        :param ami_id: (str) ID of the AMI to launch from
        :param host_id: (str) ID of the dedicated host
        :param key_name: (str) Name of the key-pair to use
        :param network_interfaces: (list) Network interfaces
        :param instance_type: (str) Instance Type (e.g. t2.micro)
        :param os_type: (str) windows or linux
        :param nat: (bool) Set True when migrating a NAT box
        :return: (dict) Instance info
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.launch_instance_onto_dedicated_host')
        log.info('Launching with AMI ID [{a}] on to host: {h}'.format(a=ami_id, h=host_id))
        log.info('Launching with Key Pair: {k}'.format(k=key_name))

        if network_interfaces:
            if not isinstance(network_interfaces, list):
                raise EC2UtilError('network_interfaces must be a list')

        if not os_type:
            raise EC2UtilError('Required param: os_type, please set to windows or linux')

        if not isinstance(os_type, str):
            raise EC2UtilError('os_type arg must be a string, found: {t}'.format(t=os_type.__class__.__name__))

        if os_type not in ['linux', 'windows']:
            raise EC2UtilError('os_type args must be set to windows or linux, found: {t}'.format(t=os_type))

        # Set monitoring
        monitoring = {'Enabled': False}

        # Configure the placement onto the dedicated host
        placement = {
            'HostId': host_id,
            'Tenancy': 'host'
        }

        # Determine the user data script by os type
        if os_type == 'windows':
            user_data = 'echo "Running Windows instance with pycons3rt3..."'
        elif os_type == 'linux':
            if nat:
                log.info('NAT boxes do not need user-data, using an echo statement...')
                user_data = 'echo "Migrating NAT box onto dedicated host with pycons3rt3..."'
            else:
                user_data = get_linux_migration_user_data_script_contents()
        else:
            user_data = 'echo "Running unknown OS type instance with pycons3rt3..."'

        # Launch the instance onto the dedicated host
        log.info('Attempting to launch the EC2 instance now on to host ID: {h}'.format(h=host_id))
        log.info('Executing with user-data script:\n{s}'.format(s=user_data))
        try:
            response = self.client.run_instances(
                DryRun=False,
                ImageId=ami_id,
                MinCount=1,
                MaxCount=1,
                KeyName=key_name,
                InstanceType=instance_type,
                Monitoring=monitoring,
                InstanceInitiatedShutdownBehavior='stop',
                Placement=placement,
                NetworkInterfaces=network_interfaces,
                UserData=user_data
            )
        except ClientError as exc:
            msg = 'Problem launching the EC2 instance\n{e}'.format(e=str(exc))
            raise EC2UtilError(msg) from exc
        if 'Instances' not in response.keys():
            msg = 'Instances not found in response: {r}'.format(r=str(response))
            raise EC2UtilError(msg)
        if len(response['Instances']) != 1:
            msg = 'Expected 1 instance in the response, found {n}: {r}'.format(
                n=str(len(response['Instances'])), r=str(response['Instances']))
            raise EC2UtilError(msg)
        return response['Instances'][0]

    def wait_for_instance_running(self, instance_id, timeout_sec=900):
        """Waits until the instance ID is in a running state

        :param instance_id: (str) ID of the instance
        :param timeout_sec: (int) Time in seconds before returning False
        :return: (bool) True when the instance reaches the running state, False otherwise
        :raises: EC2UtilError
        """
        return self.wait_for_instance_state(
            instance_id=instance_id,
            target_state='running',
            timeout_sec=timeout_sec
        )

    def wait_for_instance_stopped(self, instance_id, timeout_sec=900):
        """Waits until the instance ID is in a stopped state

        :param instance_id: (str) ID of the instance
        :param timeout_sec: (int) Time in seconds before returning False
        :return: True when the instance reaches the stopped state, False if not available by the provided timeout
        :raises: EC2UtilError
        """
        return self.wait_for_instance_state(
            instance_id=instance_id,
            target_state='stopped',
            timeout_sec=timeout_sec
        )

    def wait_for_instance_terminated(self, instance_id, timeout_sec=900):
        """Waits until the instance ID is in a terminated state

        :param instance_id: (str) ID of the instance
        :param timeout_sec: (int) Time in seconds before returning False
        :return: True when the instance reaches the terminated state, False if not available by the provided timeout
        :raises: EC2UtilError
        """
        return self.wait_for_instance_state(
            instance_id=instance_id,
            target_state='terminated',
            timeout_sec=timeout_sec
        )

    def wait_for_instance_state(self, instance_id, target_state, timeout_sec=900):
        """Waits until the instance ID is in the target state

        :param instance_id: (str) ID of the instance
        :param target_state: (str) 'pending'|'running'|'shutting-down'|'terminated'|'stopping'|'stopped'
        :param timeout_sec: (int) Time in seconds before returning False
        :return: True when the instance reaches the target state, False if not in target state by the provided timeout
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.wait_for_instance_state')
        check_interval_sec = 10
        num_checks = timeout_sec // check_interval_sec
        start_time = time.time()
        log.info('Waiting a maximum of {t} seconds for instance ID [{i}] to reach a target state: {s}'.format(
            t=str(timeout_sec), i=instance_id, s=target_state))
        for _ in range(0, num_checks*2):
            elapsed_time = round(time.time() - start_time, 1)
            if elapsed_time > timeout_sec:
                log.warning('Instance ID {i} not in target state [{s}] after {t} seconds'.format(
                    i=instance_id, t=str(timeout_sec), s=target_state))
                return False
            try:
                response = self.client.describe_instances(DryRun=False, InstanceIds=[instance_id])
            except ClientError as exc:
                log.warning('Problem describing instance ID: {i}\n{e}'.format(i=instance_id, e=str(exc)))
                continue
            if 'Reservations' not in response.keys():
                log.warning('Reservations not found in response: {r}'.format(r=str(response)))
                continue
            if len(response['Reservations']) != 1:
                log.warning('Expected 1 reservation, found in response: {n}'.format(
                    n=str(len(response['Reservations']))))
                continue
            reservation = response['Reservations'][0]
            if 'Instances' not in reservation.keys():
                log.warning('Instances not found in reservation: {r}'.format(r=str(reservation)))
                continue
            if len(reservation['Instances']) != 1:
                log.warning('Expected 1 instance, found in reservation: {n}'.format(
                    n=str(len(reservation['Instances']))))
                continue
            instance = reservation['Instances'][0]
            if 'InstanceId' not in instance.keys():
                log.warning('InstanceId not found in instance data: {i}'.format(i=str(instance)))
                continue
            if 'State' not in instance.keys():
                log.warning('State not found in instance data: {i}'.format(i=str(instance)))
                continue
            if 'Name' not in instance['State'].keys():
                log.warning('Name not found in instance state data: {i}'.format(i=str(instance['State'])))
                continue
            if instance['State']['Name'] == target_state:
                log.info('Instance ID [{i}] state is in the target state [{t}], exiting...'.format(
                    i=instance_id, t=target_state))
                return True
            else:
                log.info('Instance ID [{i}] is in state: {s}'.format(i=instance_id, s=instance['State']['Name']))
            log.info('Waiting {t} seconds to check state of instance ID: {i}'.format(
                t=str(check_interval_sec), i=instance_id))
            time.sleep(check_interval_sec)
        return False

    def wait_for_instance_status_checks(self, instance_id, timeout_sec=900):
        """Waits until the instance ID is in a running state

        :param instance_id: (str) ID of the instance
        :param timeout_sec: (int) Time in seconds before returning False
        :return: True when available, False if not available by the provided timeout
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.wait_for_instance_status_checks')
        check_interval_sec = 10
        num_checks = timeout_sec // check_interval_sec
        start_time = time.time()
        log.info('Waiting a maximum of {t} seconds for instance ID [{i}] to pass its instance status checks'.format(
            t=str(timeout_sec), i=instance_id))
        for _ in range(0, num_checks*2):
            log.info('Waiting {t} seconds to check status of instance ID: {i}'.format(
                t=str(check_interval_sec), i=instance_id))
            time.sleep(check_interval_sec)
            elapsed_time = round(time.time() - start_time, 1)
            if elapsed_time > timeout_sec:
                log.warning('Instance ID {i} has not passed instance status checks after {t} seconds'.format(
                    i=instance_id, t=str(timeout_sec)))
                return False
            try:
                response = self.client.describe_instance_status(
                    DryRun=False, InstanceIds=[instance_id], IncludeAllInstances=True)
            except ClientError as exc:
                log.warning('Problem describing status for instance ID: {i}\n{e}'.format(i=instance_id, e=str(exc)))
                continue
            if 'InstanceStatuses' not in response.keys():
                log.warning('InstanceStatuses not found in response: {r}'.format(r=str(response)))
                continue
            if len(response['InstanceStatuses']) != 1:
                log.warning('Expected 1 instance status, found in response: {n}'.format(
                    n=str(len(response['InstanceStatuses']))))
                continue
            instance_status = response['InstanceStatuses'][0]
            if 'InstanceId' not in instance_status.keys():
                log.warning('InstanceId not found in instance status: {i}'.format(i=str(instance_status)))
                continue
            if instance_status['InstanceId'] != instance_id:
                log.warning('Found instance ID [{i}] does not match the requested instance ID: {r}'.format(
                    i=instance_status['InstanceId'], r=instance_id))
                continue
            if 'InstanceState' not in instance_status.keys():
                log.warning('InstanceState not found in instance status: {i}'.format(i=str(instance_status)))
                continue
            if 'Name' not in instance_status['InstanceState'].keys():
                log.warning('Name not found in instance state data: {i}'.format(
                    i=str(instance_status['InstanceState'])))
                continue
            if instance_status['InstanceState']['Name'] != 'running':
                log.info('Found instance state [{s}] is not running, re-checking...'.format(
                    s=instance_status['InstanceState']['Name']))
                continue
            if 'InstanceStatus' not in instance_status.keys():
                log.warning('InstanceStatus not found in instance status data: {i}'.format(
                    i=str(instance_status)))
                continue
            if 'SystemStatus' not in instance_status.keys():
                log.warning('SystemStatus not found in instance status data: {i}'.format(
                    i=str(instance_status)))
                continue
            if 'Status' not in instance_status['InstanceStatus'].keys():
                log.warning('Status not found in instance status data: {i}'.format(
                    i=str(instance_status['InstanceStatus'])))
                continue
            if 'Status' not in instance_status['SystemStatus'].keys():
                log.warning('Status not found in system status data: {i}'.format(
                    i=str(instance_status['SystemStatus'])))
                continue
            current_instance_status = instance_status['InstanceStatus']['Status']
            current_system_status = instance_status['SystemStatus']['Status']
            log.info('Found current instance status for instance ID [{i}]: {s}'.format(
                i=instance_id, s=current_instance_status))
            log.info('Found current system status for instance ID [{i}]: {s}'.format(
                i=instance_id, s=current_system_status))
            if current_instance_status != 'ok' or current_system_status != 'ok':
                log.info('Instance and system statii are both not [ok], rechecking...')
                continue
            log.info('Both instance and system statii are [ok], exiting...')
            return True
        return False

    def wait_for_instance_availability(self, instance_id):
        """Waits for instance to be running and passed all status checks

        :param instance_id: (str) ID of the instance
        :return: (bool) True when instance is available, False if timeouts are exceeded before availability is
                        reached
        :raises: None
        """
        log = logging.getLogger(self.cls_logger + '.wait_for_instance_availability')
        try:
            if not self.wait_for_instance_running(instance_id=instance_id):
                return False
            if not self.wait_for_instance_status_checks(instance_id=instance_id):
                return False
        except EC2UtilError as exc:
            log.error('Instance ID {i} did not become available in the provided timeouts\n{e}'.format(
                i=instance_id, e=str(exc)))
            traceback.print_exc()
            return False
        return True

    def wait_for_image_available(self, ami_id, timeout_sec=900):
        """Waits until the AMI ID is available

        :param ami_id: (str) ID of the instance
        :param timeout_sec: (int) Time in seconds before returning False
        :return: True when the AMI is available, False if not available by the provided timeout
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.wait_for_image_available')
        check_interval_sec = 10
        num_checks = timeout_sec // check_interval_sec
        start_time = time.time()
        log.info('Waiting a maximum of {t} seconds for image ID [{i}] to become available'.format(
            t=str(timeout_sec), i=ami_id))
        for _ in range(0, num_checks*2):
            log.info('Waiting {t} seconds to check state of AMI ID: {i}'.format(
                t=str(check_interval_sec), i=ami_id))
            time.sleep(check_interval_sec)
            elapsed_time = round(time.time() - start_time, 1)
            if elapsed_time > timeout_sec:
                log.warning('AMI ID {i} not in target state [available] after {t} seconds'.format(
                    i=ami_id, t=str(timeout_sec)))
                return False
            try:
                response = self.get_image(ami_id=ami_id)
            except ClientError as exc:
                log.warning('Problem getting details for AMI ID: {i}\n{e}'.format(i=ami_id, e=str(exc)))
                continue
            if 'State' not in response.keys():
                log.warning('State not found in instance data: {i}'.format(i=str(response)))
                continue
            if response['State'] == 'available':
                log.info('AMI ID [{i}] state is in the target state [available], exiting...'.format(i=ami_id))
                return True
            else:
                log.info('AMI ID [{i}] is in state: {s}'.format(i=ami_id, s=response['State']))
        return False

    def get_host(self, host_id):
        """Gets into for a single host

        :param host_id: (str) ID of the host
        :return: dict containing host data
        :raises: EC2UtilError
        """
        return get_host(client=self.client, host_id=host_id)

    def get_host_capacity_for_instance_type(self, host_id, instance_type):
        """Gets into for a single host

        :param host_id: (str) ID of the host
        :param instance_type: (str) instance type
        :return: dict containing host data
        :raises: EC2UtilError
        """
        return get_host_capacity_for_instance_type(client=self.client, host_id=host_id, instance_type=instance_type)

    def get_instance(self, instance_id):
        """Gets into for a single EC2 instance

        :param instance_id: (str) ID of the instance
        :return: dict containing EC2 instance data
        :raises: EC2UtilError
        """
        return get_instance(client=self.client, instance_id=instance_id)

    def get_ec2_instance(self, instance_id):
        """Gets into for a single EC2 instance

        :param instance_id: (str) ID of the instance
        :return: dict containing EC2 instance data
        :raises: EC2UtilError
        """
        return get_instance(client=self.client, instance_id=instance_id)

    def get_instances(self):
        """Describes the EC2 instances

        :return: dict containing EC2 instance data
        :raises: EC2UtilError
        """
        return list_instances(client=self.client)

    def get_ec2_instances(self):
        """Describes the EC2 instances

        :return: dict containing EC2 instance data
        :raises: EC2UtilError
        """
        return list_instances(client=self.client)

    def stop_instance(self, instance_id):
        """Stops the provided instance

        :return: (tuple) instance ID, current state, and previous state
        :raises: EC2UtilError
        """
        return stop_instance(client=self.client, instance_id=instance_id)

    def terminate_instance(self, instance_id):
        """Terminates the provided instance

        :return: (tuple) instance ID, current state, and previous state
        :raises: EC2UtilError
        """
        return terminate_instance(client=self.client, instance_id=instance_id)

    def create_image(self, instance_id, image_name, image_description='', no_reboot=False):
        """Creates an EC2 image from the provided parameters

        :param instance_id: (str) ID of the instance
        :param image_name: (str) name of the image to create
        :param image_description: (str) description of the image
        :param no_reboot: (bool) Set True to prevent AWS from rebooting the image as part of the creation process
        :return: (str) image ID
        :raises: EC2UtilError
        """
        return create_image(
            client=self.client,
            instance_id=instance_id,
            image_name=image_name,
            image_description=image_description,
            no_reboot=no_reboot
        )

    def get_image(self, ami_id):
        """Return details about the provided AMI ID

        :param ami_id: (str) ID of the AMI
        :return: (dict) data about the AMI
        :raises: EC2UtilError
        """
        return get_image(client=self.client, ami_id=ami_id)

    def list_volumes(self):
        """Describes the EBS volumes

        :return: dict containing EBS volume data
        :raises EC2UtilError
        """
        return list_volumes(client=self.client)

    def list_unattached_volumes(self):
        """Return a list of unattached EBS volumes

        :return: (list) of EC2
        :raises EC2UtilError
        """
        return list_unattached_volumes(client=self.client)

    def delete_volume(self, volume_id):
        """Deletes an EBS volume

        :param volume_id: (str) ID of the EBS volume
        :return: (str) deleted volume ID
        """
        return delete_volume(client=self.client, volume_id=volume_id)

    def delete_snapshot(self, snapshot_id):
        """Deletes an EBS snapshot

        :param snapshot_id: (str) ID of the EBS volume
        :return: (str) deleted snapshot ID
        """
        return delete_snapshot(client=self.client, snapshot_id=snapshot_id)

    def get_ebs_volumes(self):
        """Describes the EBS volumes

        :return: dict containing EBS volume data
        :raises EC2UtilError
        """
        return list_volumes(client=self.client)

    def list_internet_gateways(self):
        """Returns a list of Internet Gateways

        :return: (list) of dict Internet gateways (see boto3 docs for details)
        :raises: EC2UtilError
        """
        return list_internet_gateways(client=self.client)

    def delete_internet_gateway(self, ig_id):
        """Deletes the provided Internet Gateway

        :return: None
        :raises: EC2UtilError
        """
        return delete_internet_gateway(client=self.client, ig_id=ig_id)

    def detach_internet_gateway(self, ig_id, vpc_id):
        """Deletes the provided Internet Gateway

        :return: None
        :raises: EC2UtilError
        """
        return detach_internet_gateway(client=self.client, ig_id=ig_id, vpc_id=vpc_id)

    def delete_subnet(self, subnet_id):
        """Deletes the provided subnet ID

        :return: None
        :raises: EC2UtilError
        """
        return delete_subnet(client=self.client, subnet_id=subnet_id)

    def get_vpcs(self):
        """Describes the VPCs

        :return: dict containing VPC data
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.get_vpcs')
        log.info('Describing VPCs...')
        try:
            response = self.client.describe_vpcs()
        except ClientError as exc:
            msg = 'There was a problem describing VPCs'
            raise EC2UtilError(msg) from exc
        if 'Vpcs' not in response.keys():
            msg = 'Vpcs not found in response: {d}'.format(d=str(response))
            raise EC2UtilError(msg)
        return response['Vpcs']

    def retrieve_vpc(self, vpc_id):
        """Retrieve info on the provided VPC ID

        :param vpc_id: (str) ID of the VPC
        :return: (dict) info on the VPC
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_vpc')
        log.info('Retrieving VPC: {i}'.format(i=vpc_id))
        try:
            response = self.client.describe_vpcs(
                VpcIds=[vpc_id],
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem describing VPC: {i}'.format(i=vpc_id)
            raise EC2UtilError(msg) from exc
        if 'Vpcs' not in response.keys():
            msg = 'Vpcs not in response: {r}'.format(r=str(response))
            raise EC2UtilError(msg)
        if len(response['Vpcs']) != 1:
            msg = 'Expected 1 VPC in response, found: {n}\n{r}'.format(
                n=str(len(response['Subnets'])), r=str(response))
            raise EC2UtilError(msg)
        return response['Vpcs'][0]

    def retrieve_vpc_cidr_blocks(self, vpc_id):
        """Returns a list of associated CIDR blocks for the VPC

        :param vpc_id: (str) ID of the VPC
        :return: (list) of (str) CIDR blocks
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_vpc_cidr_blocks')
        cidr_blocks = []
        vpc = self.retrieve_vpc(vpc_id=vpc_id)
        if 'CidrBlockAssociationSet' not in vpc.keys():
            log.warning('No CIDR blocks found associated to VPC ID: {v}'.format(v=vpc_id))
            return cidr_blocks
        for cidr_block_assoc_set in vpc['CidrBlockAssociationSet']:
            if 'CidrBlock' not in cidr_block_assoc_set.keys():
                continue
            if 'CidrBlockState' not in cidr_block_assoc_set.keys():
                continue
            if 'State' not in cidr_block_assoc_set['CidrBlockState']:
                continue
            if cidr_block_assoc_set['CidrBlockState']['State'] == 'associated':
                cidr_blocks.append(cidr_block_assoc_set['CidrBlock'])
        return cidr_blocks

    def get_vpc_id_by_name(self, vpc_name):
        """Return the VPC ID matching the provided name or None if not found

        :param vpc_name: (str) name of the VPC
        :return: (dict) VPC data if found, or None if not found
        """
        log = logging.getLogger(self.cls_logger + '.get_vpc_id_by_name')
        log.info('Getting a list of VPCS...')
        try:
            vpcs = self.get_vpcs()
        except EC2UtilError as exc:
            raise EC2UtilError('Problem listing VPCs') from exc

        # Ensure VPCs were found
        if len(vpcs) < 1:
            log.info('No VPCs found')
            return None

        # Check eac VPC for matching name
        log.info('Found [{n}] VPCs'.format(n=str(len(vpcs))))
        for vpc in vpcs:
            if 'VpcId' not in vpc.keys():
                continue
            if 'Tags' not in vpc.keys():
                continue
            for tag in vpc['Tags']:
                if tag['Key'] == 'Name' and tag['Value'] == vpc_name:
                    log.info('Found VPC with name [{n}] has ID: {i}'.format(n=vpc_name, i=vpc['VpcId']))
                    return vpc
        log.info('VPC with name {n} not found'.format(n=vpc_name))
        return None

    def create_vpc(self, vpc_name, cidr_block, amazon_ipv6_cidr=False, instance_tenancy='default', dry_run=False):
        """Creates a VPC with the provided name

        :param vpc_name: (str) desired VPC name
        :param cidr_block: (str) desired CIDR block for the VPC
        :param instance_tenancy: (str) default or dedicated
        :param amazon_ipv6_cidr: (bool) Set true to request an Amazon IPv6 CIDR block
        :param dry_run: (bool) Set true to dry run the call
        :return: (dict) VPC data (see boto3 docs)
        """
        log = logging.getLogger(self.cls_logger + '.create_vpc')

        # Check for an existing VPC with the desired name
        try:
            existing_vpc = self.get_vpc_id_by_name(vpc_name=vpc_name)
        except EC2UtilError as exc:
            raise EC2UtilError('Problem checking for existing VPCs') from exc
        if existing_vpc:
            log.info('Found existing VPC named {n} with ID: {i}'.format(n=vpc_name, i=existing_vpc['VpcId']))
            return existing_vpc

        # Create the VPC
        try:
            response = self.client.create_vpc(
                CidrBlock=cidr_block,
                AmazonProvidedIpv6CidrBlock=amazon_ipv6_cidr,
                InstanceTenancy=instance_tenancy,
                DryRun=dry_run
            )
        except ClientError as exc:
            msg = 'There was a problem describing VPCs'
            raise EC2UtilError(msg) from exc

        # Get the new VPC ID
        if 'Vpc' not in response.keys():
            raise EC2UtilError('VPC not created with name: {n}'.format(n=vpc_name))

        if 'VpcId' not in response['Vpc'].keys():
            raise EC2UtilError('VpcId data not found in: {d}'.format(d=str(response['Vpc'])))
        vpc_id = response['Vpc']['VpcId']
        log.info('Created new VPC with ID: {i}'.format(i=vpc_id))

        # Ensure the VPC created exists
        if not self.ensure_exists(resource_id=vpc_id):
            raise EC2UtilError('Created VPC ID not found after timeout: {i}'.format(i=vpc_id))

        # Apply the name tag
        if not self.create_name_tag(resource_id=vpc_id, resource_name=vpc_name):
            raise EC2UtilError('Problem setting name tag for VPC ID: {i}'.format(i=vpc_id))
        log.info('Successfully created VPC name {n} with ID: {n}'.format(n=vpc_name, i=vpc_id))
        return response['Vpc']

    def delete_vpc(self, vpc_id):
        """Deletes the provided VPC ID

        :param vpc_id: (str) ID of the VPC
        :return: None
        :raises EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.delete_vpc')
        log.info('Deleting VPC ID: {i}'.format(i=vpc_id))
        try:
            self.client.delete_vpc(
                VpcId=vpc_id,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem deleting VPC ID: {i}'.format(i=vpc_id)
            raise EC2UtilError(msg) from exc

    def delete_default_vpc(self):
        """Finds and deletes the default VPC if it exists

        :return: (dict) Info about the deleted VPC or None
        :raises: (EC2UtilError)
        """
        log = logging.getLogger(self.cls_logger + '.delete_default_vpc')
        try:
            vpcs = self.get_vpcs()
        except EC2UtilError as exc:
            raise EC2UtilError('Problem listing VPCs') from exc
        log.info('Attempting to find the default VPC if it exists...')

        # Store the default VPC ID when found
        default_vpc_id = None

        # Query and search all the VPCs for the default one
        for vpc in vpcs:
            if 'VpcId' not in vpc.keys():
                log.warning('VpcId not found in data: {d}'.format(d=str(vpc)))
                continue
            if 'IsDefault' not in vpc.keys():
                log.warning('IsDefault not found in data: {d}'.format(d=str(vpc)))
                continue
            if vpc['IsDefault']:
                default_vpc_id = vpc['VpcId']
                break

        # Return none if a default VPC was not found
        if not default_vpc_id:
            log.info('No default VPCs found')
            return

        # Attempt to delete the default VPC
        log.info('Found default VPC ID [{i}], attempting to delete dependencies...'.format(i=default_vpc_id))

        try:
            internet_gateway = self.get_internet_gateway_for_vpc(vpc_id=default_vpc_id)
        except EC2UtilError as exc:
            msg = 'Problem determining the Internet gateway for VPC ID: {i}'.format(i=default_vpc_id)
            raise EC2UtilError(msg) from exc

        # Delete the internet gateway if found
        if internet_gateway:
            log.info('Detach the Internet Gateway [{i}] from VPC: {v}'.format(
                i=internet_gateway['InternetGatewayId'], v=default_vpc_id))
            try:
                self.detach_internet_gateway(ig_id=internet_gateway['InternetGatewayId'], vpc_id=default_vpc_id)
            except EC2UtilError as exc:
                msg = 'Problem detaching Internet Gateway [{i}], unable to delete default VPC'.format(
                    i=internet_gateway['InternetGatewayId'])
                raise EC2UtilError(msg) from exc

            log.info('Deleting the Internet Gateway for VPC ID: {v}'.format(v=default_vpc_id))
            try:
                self.delete_internet_gateway(ig_id=internet_gateway['InternetGatewayId'])
            except EC2UtilError as exc:
                msg = 'Problem deleting Internet Gateway [{i}], unable to delete default VPC'.format(
                    i=internet_gateway['InternetGatewayId'])
                raise EC2UtilError(msg) from exc

        # Get a list of subnets in the VPC
        try:
            subnets = self.list_subnets(vpc_id=default_vpc_id)
        except EC2UtilError as exc:
            msg = 'Problem getting a list of subnet in VPC ID [{i}], unable to delete default VPC'.format(
                i=default_vpc_id)
            raise EC2UtilError(msg) from exc

        # Delete each of the subnets
        log.info('Deleting subnets for VPC ID: {v}'.format(v=default_vpc_id))
        for subnet in subnets:
            try:
                self.delete_subnet(subnet_id=subnet['SubnetId'])
            except EC2UtilError as exc:
                msg = 'Problem deleting subnet ID [{i}], unable to delete default VPC'.format(i=subnet['SubnetId'])
                raise EC2UtilError(msg) from exc

        # Delete the VPC itself after deleting the dependencies
        try:
            self.delete_vpc(vpc_id=default_vpc_id)
        except EC2UtilError as exc:
            msg = 'Problem deleting default VPC: {i}'.format(i=default_vpc_id)
            raise EC2UtilError(msg) from exc

    def get_internet_gateway_for_vpc(self, vpc_id):
        """Returns an Internet gateway if one is attaches to the provided VPC ID

        :param vpc_id: (str) ID of the VPC
        :return: (dict) Internet gateway (see boto3 docs) for the gateway attached to the provided VPC ID, or None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.get_internet_gateway_for_vpc')
        log.info('Attempting to determine if an Internet gateway exists for VPC ID: {i}'.format(i=vpc_id))

        # Check if the VPC already has an internet gateway
        try:
            igs = self.list_internet_gateways()
        except EC2UtilError as exc:
            msg = 'Problem listing internet gateways'
            raise EC2UtilError(msg) from exc

        for ig in igs:
            if 'Attachments' in ig.keys():
                for attachment in ig['Attachments']:
                    if attachment['VpcId'] == vpc_id:
                        log.info('VPC [{v}] has attached Internet gateway [{i}]'.format(
                            v=vpc_id, i=ig['InternetGatewayId']))
                        return ig
        log.info('VPC ID [{v}] does not have an attached Internet gateway'.format(v=vpc_id))
        return None

    def add_vpc_cidr(self, vpc_id, cidr, amazon_ipv6_cidr=False):
        """Adds the provided CIDR block to the VPC

        :param vpc_id: (str) ID of the VPC
        :param cidr: (str) CIDR block to add
        :param amazon_ipv6_cidr: (bool)
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_vpc_cidr')
        log.info('Adding CIDR [{c}] to VPC ID: {i}'.format(c=cidr, i=vpc_id))
        try:
            self.client.associate_vpc_cidr_block(
                AmazonProvidedIpv6CidrBlock=amazon_ipv6_cidr,
                CidrBlock=cidr,
                VpcId=vpc_id
            )
        except ClientError as exc:
            msg = 'There was a problem adding CIDR [{c}] to VPC ID: {i}'.format(c=cidr, i=vpc_id)
            raise EC2UtilError(msg) from exc

    def create_usable_vpc(self, vpc_name, cidr_block):
        """Creates a VPC with a subnet that routes to an Internet Gateway, and default Network ACL and routes

        :param vpc_name: (str) name of the VPC
        :param cidr_block: (str) desired CIDR block
        :return: (tuple) (str) ID of the VPC that was created or configured, (str) ID of the Internet Gateway
        """
        log = logging.getLogger(self.cls_logger + '.create_usable_vpc')

        # Create a VPC
        try:
            vpc = self.create_vpc(vpc_name=vpc_name, cidr_block=cidr_block)
        except EC2UtilError as exc:
            raise EC2UtilError('Problem creating a VPC') from exc
        log.info('Created (or found existing) VPC ID: {i}'.format(i=vpc['VpcId']))

        # Check if the VPC already has an internet gateway
        try:
            ig = self.get_internet_gateway_for_vpc(vpc_id=vpc['VpcId'])
        except EC2UtilError as exc:
            msg = 'Problem determining if VPC ID [{v}] has an Internet gateway'.format(v=vpc['VpcId'])
            raise EC2UtilError(msg) from exc

        # If an existing Internet Gateway was found, return it and the VPC ID
        if ig:
            log.info('Found existing Internet Gateway for VPC ID: {v}'.format(v=vpc['VpcId']))
            return vpc['VpcId'], ig['InternetGatewayId']

        # Create an Internet Gateway
        log.info('Existing attached internet gateway not found for VPC [{v}], creating one...'.format(v=vpc['VpcId']))
        try:
            internet_gateway = self.client.create_internet_gateway(DryRun=False)
        except ClientError as exc:
            raise EC2UtilError('Problem creating Internet Gateway') from exc

        if 'InternetGateway' not in internet_gateway:
            raise EC2UtilError('Internet gateway was not created')

        if 'InternetGatewayId' not in internet_gateway['InternetGateway']:
            raise EC2UtilError('InternetGatewayId not found in data: {d}'.format(d=str(internet_gateway)))

        ig_id = internet_gateway['InternetGateway']['InternetGatewayId']
        log.info('Created Internet gateway: {i}'.format(i=ig_id))

        # Ensure the internet gateway exists
        if not self.ensure_exists(resource_id=ig_id):
            raise EC2UtilError('Created Internet Gateway ID [{i}] not available after a timeout'.format(i=ig_id))

        # Add the name tag
        if not self.create_name_tag(resource_id=ig_id, resource_name=vpc_name + '-ig'):
            raise EC2UtilError('Problem creating name tag for Internet gateway: {i}'.format(i=ig_id))

        # Attach the Internet gateway
        try:
            self.client.attach_internet_gateway(
                DryRun=False,
                InternetGatewayId=ig_id,
                VpcId=vpc['VpcId']
            )
        except ClientError as exc:
            msg = 'Problem attaching Internet gateway {i} to VPC {v}'.format(i=ig_id, v=vpc['VpcId'])
            raise EC2UtilError(msg) from exc
        log.info('Successfully attach Internet gateway {i} to VPC: {v}'.format(i=ig_id, v=vpc['VpcId']))
        return vpc['VpcId'], ig_id

    def enable_vpc_dns(self, vpc_id):
        """Sets the EnableDnsHostnames and EnableDnsSupport values to True for the VPC ID

        modify_vpc_attribute

        :param vpc_id: (str) ID of the VPC
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.enable_vpc_dns')
        log.info('Setting EnableDnsHostnames and EnableDnsSupport to True for VPC ID: {v}'.format(v=vpc_id))
        try:
            self.client.modify_vpc_attribute(
                EnableDnsHostnames={
                    'Value': True
                },
                VpcId=vpc_id
            )
            self.client.modify_vpc_attribute(
                EnableDnsSupport={
                    'Value': True
                },
                VpcId=vpc_id
            )
        except ClientError as exc:
            msg = 'Problem setting EnableDnsHostnames and EnableDnsSupport to True for VPC ID: {v}'.format(v=vpc_id)
            raise EC2UtilError(msg) from exc

    def create_subnet(self, name, vpc_id, cidr, availability_zone=None):
        """Creates a subnet

        :param name: (str) subnet name
        :param vpc_id: (str) VPC ID
        :param cidr: (str) subnet CIDR block
        :param availability_zone: (str) availability zone
        :return: (str) subnet ID
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_subnet')

        # Checking for existing Subnet in VOC
        try:
            existing_vpc_subnets = self.list_subnets(vpc_id=vpc_id)
        except EC2UtilError as exc:
            log.warning('Unable to list existing subnets in VPC [{v}]\n{e}'.format(v=vpc_id, e=str(exc)))
        else:
            for existing_vpc_subnet in existing_vpc_subnets:
                if existing_vpc_subnet['CidrBlock'] == cidr:
                    log.info('Found existing subnet [{s}] for VPC [{v}] with CIDR [{c}]'.format(
                        s=existing_vpc_subnet['SubnetId'], v=vpc_id, c=cidr))
                    return existing_vpc_subnet['SubnetId']

        log.info('Creating subnet in with name [{n}] in VPC ID [{v}] with CIDR: {c}'.format(
            n=name, v=vpc_id, c=cidr))
        try:
            log.info('Requesting subnet in availability zone: {z}'.format(z=availability_zone))
            if availability_zone:
                response = self.client.create_subnet(CidrBlock=cidr, VpcId=vpc_id, DryRun=False,
                                                     AvailabilityZone=availability_zone)
            else:
                response = self.client.create_subnet(CidrBlock=cidr, VpcId=vpc_id, DryRun=False)
        except ClientError as exc:
            msg = 'There was a problem creating subnet with name [{n}] and  CIDR [{c}] in VPC ID: {i}'.format(
                n=name, c=cidr, i=vpc_id)
            raise EC2UtilError(msg) from exc

        # Get the new VPC ID
        if 'Subnet' not in response.keys():
            raise EC2UtilError('Subnet not created with name: {n}'.format(n=name))

        if 'SubnetId' not in response['Subnet'].keys():
            raise EC2UtilError('SubnetId data not found in: {d}'.format(d=str(response['Subnet'])))
        subnet_id = response['Subnet']['SubnetId']

        # Ensure the subnet ID exists
        if not self.ensure_exists(resource_id=subnet_id):
            raise EC2UtilError('Problem finding subnet ID after successful creation: {i}'.format(i=subnet_id))

        # Apply the name tag
        if not self.create_name_tag(resource_id=subnet_id, resource_name=name):
            raise EC2UtilError('Problem adding name tag name of subnet ID: {i}'.format(i=subnet_id))
        log.info('Created new subnet with ID: {i}'.format(i=subnet_id))
        return subnet_id

    def set_subnet_auto_assign_public_ip(self, subnet_id, auto_assign):
        """Sets the auto-assign public attribute of the provided subnet ID to the provided value

        :param subnet_id: (str) ID of the subnet
        :param auto_assign: (bool) True to enable auto-assign public IP, false otherwise
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.set_subnet_auto_assign_public_ip')
        log.info('Setting auto-assign public IP attribute of subnet ID [{s}] to {v}'.format(
            s=subnet_id, v=str(auto_assign)))
        try:
            self.client.modify_subnet_attribute(
                MapPublicIpOnLaunch={
                    'Value': auto_assign,
                },
                SubnetId=subnet_id,
            )
        except ClientError as exc:
            msg = 'Problem setting the auto-assign public IP attribute for subnet ID [{s}] to: {v}'.format(
                s=subnet_id, v=str(auto_assign))
            raise EC2UtilError(msg) from exc

    def create_vpc_route_table(self, name, vpc_id):
        """Creates a route table for a VPC

        :param name: (str) route table name
        :param vpc_id: (str) VPC ID
        :return: (dict) route table data
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_vpc_route_table')
        log.info('Creating route table with name [{n}] in VPC ID: {v}'.format(n=name, v=vpc_id))
        try:
            response = self.client.create_route_table(VpcId=vpc_id, DryRun=False)
        except ClientError as exc:
            msg = 'There was a problem creating route table [{n}] in VPC ID: {i}'.format(n=name, i=vpc_id)
            raise EC2UtilError(msg) from exc

        # Get the new VPC ID
        if 'RouteTable' not in response.keys():
            raise EC2UtilError('Route Table not created with name: {n}'.format(n=name))
        route_table = response['RouteTable']

        if 'RouteTableId' not in route_table.keys():
            raise EC2UtilError('RouteTableId data not found in: {d}'.format(d=str(route_table)))
        route_table_id = route_table['RouteTableId']

        # Ensure the route table ID created exists
        if not self.ensure_exists(resource_id=route_table_id):
            raise EC2UtilError('Created route table ID not found after timeout: {i}'.format(i=route_table_id))

        # Apply the name tag
        if not self.create_name_tag(resource_id=route_table_id, resource_name=name):
            raise EC2UtilError('Problem adding name tag name of route table ID: {i}'.format(i=route_table_id))
        log.info('Created new route table with ID: {i}'.format(i=route_table_id))
        return route_table

    def delete_vpc_route_table(self, route_table_id):
        """Deletes the specified route table ID

        :param route_table_id: (str) route table ID
        :return: (dict) route table data
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.delete_vpc_route_table')

        # Get the route table and ensure it exists
        try:
            route_table = self.get_route_table(route_table_id=route_table_id)
        except EC2UtilError as exc:
            msg = 'Route table ID not found: {i}'.format(i=route_table_id)
            raise EC2UtilError(msg) from exc

        log.info('Deleting route table with ID: {i}'.format(i=route_table_id))
        try:
            self.client.delete_route_table(RouteTableId=route_table_id, DryRun=False)
        except ClientError as exc:
            msg = 'Problem deleting route table: {i}'.format(i=route_table_id)
            raise EC2UtilError(msg) from exc
        return route_table

    def is_vpc_route_table_associated_to_subnet(self, route_table_id, subnet_id):
        """Determines if the route table is assoictaed to the subnet

        :param route_table_id: (str) ID of the route table
        :param subnet_id: (str) ID of the subnet
        :return: (Tuple) (bool) True/False, (dict) Association Data
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.is_vpc_route_table_associated_to_subnet')

        # Ensure the route table ID exists
        try:
            route_table = self.get_route_table(route_table_id=route_table_id)
        except EC2UtilError as exc:
            msg = 'Route table ID not found: {i}'.format(i=route_table_id)
            raise EC2UtilError(msg) from exc

        # Ensure the subnet ID exists
        try:
            self.retrieve_subnet(subnet_id=subnet_id)
        except EC2UtilError as exc:
            msg = 'Subnet ID not found: {i}'.format(i=subnet_id)
            raise EC2UtilError(msg) from exc

        # Return if no associations found
        if 'Associations' not in route_table.keys():
            log.info('Route table has no associations: {i}'.format(i=route_table_id))
            return False, None

        # Get associations for the route table
        log.info('Checking existing associations for route table [{r}]'.format(r=route_table_id))
        for association in route_table['Associations']:
            if 'RouteTableAssociationId' not in association.keys():
                log.warning('RouteTableAssociationId not found in association: {d}'.format(d=str(association)))
                continue
            if 'SubnetId' not in association.keys():
                log.info('SubnetId not found in association: {d}'.format(d=str(association)))
                continue
            if association['SubnetId'] == subnet_id:
                log.info('Subnet ID [{s}] is already associated to route table [{r}] with ID: {i}'.format(
                    s=subnet_id, r=route_table_id, i=association['RouteTableAssociationId']))
                return True, association
        log.info('This route table [{r}] has associations but not to subnet ID [{s}]'.format(
            r=route_table_id, s=subnet_id))
        return False, None

    def associate_route_table(self, route_table_id, subnet_id):
        """Associates the route table with the subnet

        :param route_table_id: (str) ID of the route table
        :param subnet_id: (str) ID of the subnet
        :return: (str) ID of the association
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.associate_route_table')

        # Get associations for the route table
        is_associated, association = self.is_vpc_route_table_associated_to_subnet(
            route_table_id=route_table_id, subnet_id=subnet_id)

        # Is associated, return the association ID
        if is_associated:
            return association['RouteTableAssociationId']

        log.info('Associating route table [{r}] with subnet ID: {s}'.format(r=route_table_id, s=subnet_id))
        try:
            response = self.client.associate_route_table(RouteTableId=route_table_id, SubnetId=subnet_id, DryRun=False)
        except ClientError as exc:
            msg = 'Problem associating route table [{r}] with subnet ID: {s}'.format(r=route_table_id, s=subnet_id)
            raise EC2UtilError(msg) from exc

        # Get the AssociationId
        if 'AssociationId' not in response.keys():
            raise EC2UtilError('AssociationId not found in response: {d}'.format(d=str(response)))
        association_id = response['AssociationId']
        log.info('Associated route table [{r}] to subnet [{s}] with association ID: {a}'.format(
            r=route_table_id, s=subnet_id, a=association_id))
        return association_id

    def disassociate_vpc_route_table(self, route_table_id, subnet_id):
        """Disassociates the VPC route table from the subnet

        :param route_table_id: (str) ID of the route table
        :param subnet_id: (str) ID of the subnet
        :return: (str) ID of the association or None (not associated)
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.disassociate_vpc_route_table')

        # Get associations for the route table
        is_associated, association = self.is_vpc_route_table_associated_to_subnet(
            route_table_id=route_table_id, subnet_id=subnet_id)

        # If it is not associated, return
        if not is_associated:
            log.info('Route table [{r}] is not associated to subnet ID [{s}], nothing to disassociate'.format(
                r=route_table_id, s=subnet_id))
            return None

        # Ensure the RouteTableAssociationId is found
        if 'RouteTableAssociationId' not in association.keys():
            msg = 'RouteTableAssociationId not found in association: {d}'.format(d=str(association))
            raise EC2UtilError(msg)

        # Get the association ID
        association_id = association['RouteTableAssociationId']

        # Disassociate the route table
        log.info('Disassociating route table [{r}] from subnet ID [{s}], with association ID [{i}]'.format(
            r=route_table_id, s=subnet_id, i=association_id))
        try:
            self.client.disassociate_route_table(AssociationId=association_id, DryRun=False)
        except ClientError as exc:
            msg = 'Problem disassociating route table [{r}] from subnet ID [{s}] with association ID [{i}]'.format(
                r=route_table_id, s=subnet_id, i=association_id)
            raise EC2UtilError(msg) from exc
        return association_id

    def create_network_acl(self, name, vpc_id):
        """Creates a network ACL

        :param name: (str) network ACL name
        :param vpc_id: (str) VPC ID
        :return: (str) network ACL ID
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_network_acl')
        log.info('Creating network ACL with name [{n}] in VPC ID: {v}'.format(n=name, v=vpc_id))
        try:
            response = self.client.create_network_acl(VpcId=vpc_id, DryRun=False)
        except ClientError as exc:
            msg = 'There was a problem creating network ACL [{n}] in VPC ID: {i}'.format(n=name, i=vpc_id)
            raise EC2UtilError(msg) from exc

        # Get the new VPC ID
        if 'NetworkAcl' not in response.keys():
            raise EC2UtilError('Network ACL not created with name: {n}'.format(n=name))

        if 'NetworkAclId' not in response['NetworkAcl'].keys():
            raise EC2UtilError('NetworkAclId data not found in: {d}'.format(d=str(response['NetworkAcl'])))
        network_acl_id = response['NetworkAcl']['NetworkAclId']

        # Ensure the network ACL ID exists
        if not self.ensure_exists(resource_id=network_acl_id):
            raise EC2UtilError('Problem finding network ACL ID after successful creation: {i}'.format(i=network_acl_id))

        # Apply the name tag
        if not self.create_name_tag(resource_id=network_acl_id, resource_name=name):
            raise EC2UtilError('Problem adding name tag name of network ACL ID: {i}'.format(i=network_acl_id))

        log.info('Created new network ACL with ID: {i}'.format(i=network_acl_id))
        return network_acl_id

    def delete_network_acl(self, network_acl_id):
        """Deletes a network ACL

        :param network_acl_id: (str) route table name
        :return: (str) Deleted network ACL ID
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.delete_network_acl')
        log.info('Deleting network ACL: {i}'.format(i=network_acl_id))
        try:
            self.client.delete_network_acl(NetworkAclId=network_acl_id, DryRun=False)
        except ClientError as exc:
            msg = 'Problem deleting network ACL: {i}'.format(i=network_acl_id)
            raise EC2UtilError(msg) from exc
        return network_acl_id

    def get_default_network_acl_for_vpc(self, vpc_id):
        """Returns the ID of the default network ACL for the VPC

        :param vpc_id: (str) ID of the VPC
        :return: (dict) network ACL or None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.get_default_network_acl_for_vpc')
        log.info('Getting the default network ACL for VPC ID: [{v}]'.format(v=vpc_id))
        try:
            response = self.client.describe_network_acls(
                Filters=[
                    {
                        'Name': 'vpc-id',
                        'Values': [
                            vpc_id,
                        ]
                    },
                    {
                        'Name': 'default',
                        'Values': [
                            'true',
                        ]
                    },
                ],
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem determining the default network ACL for VPC ID: {v}'.format(v=vpc_id)
            raise EC2UtilError(msg) from exc
        if 'NetworkAcls' not in response.keys():
            log.info('No default network ACLs found for VPC ID: {v}'.format(v=vpc_id))
            return None
        if len(response['NetworkAcls']) == 0:
            log.info('No default network ACLs found for VPC ID: {v}'.format(v=vpc_id))
            return None
        if len(response['NetworkAcls']) != 1:
            msg = 'Expected 1 network default network ACL in response, found: {n}\n{r}'.format(
                n=str(len(response['NetworkAcls'])), r=str(response))
            raise EC2UtilError(msg)
        network_acl = response['NetworkAcls'][0]
        if 'NetworkAclId' not in network_acl.keys():
            raise EC2UtilError('NetworkAclId not found in network ACL data: [{d}]'.format(d=str(network_acl)))
        return network_acl

    def get_network_acl_for_subnet(self, subnet_id):
        """Returns the associated network ACL ID for the specified subnet ID

        :param subnet_id: (str) ID of the subnet
        :return: (tuple) Network ACL ID (str), association ID (str), network ACL data (dict)
        """
        log = logging.getLogger(self.cls_logger + '.get_network_acl_for_subnet')
        log.info('Attempting to determine the associated network ACL for subnet ID: {s}'.format(s=subnet_id))
        try:
            response = self.client.describe_network_acls(
                Filters=[
                    {
                        'Name': 'association.subnet-id',
                        'Values': [
                            subnet_id,
                        ]
                    },
                ],
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem determining the network ACL associated to subnet ID: {s}'.format(s=subnet_id)
            raise EC2UtilError(msg) from exc
        if 'NetworkAcls' not in response.keys():
            log.info('No network ACLs found for subnet ID: {s}'.format(s=subnet_id))
            return None, None
        if len(response['NetworkAcls']) == 0:
            log.info('No network ACLs found for subnet ID: {s}'.format(s=subnet_id))
            return None, None
        if len(response['NetworkAcls']) != 1:
            msg = 'Expected 1 network ACL in response, found: {n}\n{r}'.format(
                n=str(len(response['NetworkAcls'])), r=str(response))
            raise EC2UtilError(msg)
        network_acl = response['NetworkAcls'][0]
        if 'Associations' not in network_acl.keys():
            msg = 'Associations not found in data: {d}'.format(d=str(network_acl))
            raise EC2UtilError(msg)
        network_acl_id = None
        association_id = None
        for association in network_acl['Associations']:
            if association['SubnetId'] == subnet_id:
                network_acl_id = association['NetworkAclId']
                association_id = association['NetworkAclAssociationId']
                break
        if not association_id:
            msg = 'Association ID not found for subnet [{s}] in data: {d}'.format(s=subnet_id, d=str(network_acl))
            raise EC2UtilError(msg)
        if not network_acl_id:
            msg = 'Network ACL ID not found in associations for subnet [{s}] in data: {d}'.format(
                s=subnet_id, d=str(network_acl))
            raise EC2UtilError(msg)
        log.info('Found subnet [{s}] associated to network ACL {n} with association ID: {i}'.format(
            s=subnet_id, n=network_acl_id, i=association_id))
        return network_acl_id, association_id, network_acl

    def associate_network_acl(self, network_acl_id, subnet_id, delete_existing=False):
        """Associates the network ACL to the subnet

        :param network_acl_id: (str) ID of the network ACL
        :param subnet_id: (str) ID of the subnet
        :param delete_existing: (bool) Set True to delete the Network ACL currently associated with the subnet
        :return: (str) ID of the association
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.associate_network_acl')

        # Get the current/default subnet association
        log.info('Getting the current network ACL association for subnet ID: {s}'.format(s=subnet_id))
        try:
            current_network_acl_id, association_id, network_acl = self.get_network_acl_for_subnet(subnet_id=subnet_id)
        except EC2UtilError as exc:
            msg = 'Problem getting the network ACL ID from subnet ID: {i}'.format(i=subnet_id)
            raise EC2UtilError(msg) from exc

        # Log whether a current association exists
        if not current_network_acl_id:
            log.info('Associating network ACL [{n}] with subnet ID [{s}]'.format(n=network_acl_id, s=subnet_id))
        else:
            log.info('Replacing current network ACL [{c}] under association ID [{a}] with network ACL [{n}] in '
                     'subnet ID: {s}'.format(c=current_network_acl_id, a=association_id, n=network_acl_id, s=subnet_id))

        # Replace the network ACL
        try:
            response = self.client.replace_network_acl_association(
                AssociationId=association_id, NetworkAclId=network_acl_id, DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem associating network ACL [{n}] with subnet ID: {s}'.format(n=network_acl_id, s=subnet_id)
            raise EC2UtilError(msg) from exc

        # Get the new association ID
        if 'NewAssociationId' not in response.keys():
            raise EC2UtilError('NewAssociationId not found in response: {d}'.format(d=str(response)))
        new_association_id = response['NewAssociationId']
        log.info('Associated network ACL [{n}] to subnet [{s}] with association ID: {a}'.format(
            n=network_acl_id, s=subnet_id, a=new_association_id))

        # Delete the previously associated network ACL if it is not a default network ACL
        if delete_existing and current_network_acl_id:
            if 'IsDefault' not in network_acl.keys():
                log.warning('IsDefault data not found in network ACL: {d}'.format(d=str(network_acl)))
            else:
                is_default = network_acl['IsDefault']
                if not is_default:
                    log.info('Deleting existing network ACL ID: {i}'.format(i=network_acl_id))
                    self.delete_network_acl(network_acl_id=current_network_acl_id)
                else:
                    log.info('Not deleting the default network ACL: {i}'.format(i=network_acl_id))
        return new_association_id

    def disassociate_network_acl(self, network_acl_id, subnet_id, vpc_id):
        """Disassociates the network ACL from the subnet

        :param network_acl_id: (str) ID of the network ACL
        :param subnet_id: (str) ID of the subnet
        :param vpc_id: (str) ID of the VPC
        :return: (str) ID of the association or None (not associated)
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.disassociate_network_acl')

        # Get the current/default subnet association
        log.info('Getting the current network ACL association for subnet ID: {s}'.format(s=subnet_id))
        try:
            current_network_acl_id, association_id, network_acl = self.get_network_acl_for_subnet(subnet_id=subnet_id)
        except EC2UtilError as exc:
            msg = 'Problem getting the network ACL ID from subnet ID: {i}'.format(i=subnet_id)
            raise EC2UtilError(msg) from exc

        # If it is not associated, return
        if current_network_acl_id != network_acl_id:
            log.info('Network ACL [{n}] is not associated to subnet ID [{s}], nothing to disassociate'.format(
                n=network_acl_id, s=subnet_id))
            return None

        # Find the default VPC network ACL
        try:
            default_network_acl = self.get_default_network_acl_for_vpc(vpc_id=vpc_id)
        except EC2UtilError as exc:
            msg = ('Probelm determining the default network ACL for VPC [{v}], cannot change network ACL association '
                   'for subnet [{s}]').format(v=vpc_id, s=subnet_id)
            raise EC2UtilError(msg) from exc
        default_network_acl_id = default_network_acl['NetworkAclId']

        # Change the network ACL association to the default
        log.info('Replacing association for subnet [{s}] from network ACL [{n}], with default network ACL [{d}]'.format(
            s=subnet_id, n=network_acl_id, d=default_network_acl_id))
        try:
            self.client.replace_network_acl_association(
                AssociationId=association_id, NetworkAclId=default_network_acl_id, DryRun=False)
        except ClientError as exc:
            msg = ('Problem replacing association for subnet [{s}] from network ACL [{n}], with default network '
                   'ACL [{d}]').format(s=subnet_id, n=network_acl_id, d=default_network_acl_id)
            raise EC2UtilError(msg) from exc
        return association_id

    def create_network_acl_rule_ipv4_all(self, network_acl_id, cidr, rule_num, rule_action='allow', egress=False):
        """Creates a rule

        :param network_acl_id: (str) ID of the network ACL
        :param cidr: (str) IPv4 CIDR block
        :param rule_num: (int) ordered rule number
        :param rule_action: (str) allow or deny
        :param egress: (bool) Set True to specify an egress rule, False for ingress
        :return:
        """
        log = logging.getLogger(self.cls_logger + '.create_network_acl_rule_ipv4_all')
        log.info('Creating rule IPv4 rule to {a} all protocols to cidr [{c}] and egress is [{e}]'.format(
            a=rule_action, c=cidr, e=str(egress)))
        try:
            self.client.create_network_acl_entry(
                CidrBlock=cidr,
                DryRun=False,
                Egress=egress,
                NetworkAclId=network_acl_id,
                Protocol='-1',
                RuleAction=rule_action,
                RuleNumber=rule_num
            )
        except ClientError as exc:
            msg = 'Problem creating '
            raise EC2UtilError(msg) from exc

    def create_network_acl_rule_ipv6_all(self, network_acl_id, cidr_ipv6, rule_num, rule_action='allow', egress=False):
        """Creates a rule

        :param network_acl_id: (str) ID of the network ACL
        :param cidr_ipv6: (str) IPv6 CIDR block
        :param rule_num: (int) ordered rule number
        :param rule_action: (str) allow or deny
        :param egress: (bool) Set True to specify an egress rule, False for ingress
        :return:
        """
        log = logging.getLogger(self.cls_logger + '.create_network_acl_rule_ipv6_all')
        log.info('Creating rule IPv6 rule to {a} all protocols to cidr [{c}] and egress is [{e}]'.format(
            a=rule_action, c=cidr_ipv6, e=str(egress)))
        try:
            self.client.create_network_acl_entry(
                Ipv6CidrBlock=cidr_ipv6,
                DryRun=False,
                Egress=egress,
                NetworkAclId=network_acl_id,
                Protocol='-1',
                RuleAction=rule_action,
                RuleNumber=rule_num
            )
        except ClientError as exc:
            msg = 'Problem creating '
            raise EC2UtilError(msg) from exc

    def create_network_acl_rule(self, network_acl_id, rule_num, cidr=None, cidr_ipv6=None, rule_action='allow',
                                protocol='-1', from_port=None, to_port=None, egress=False):
        """Creates a rule in the network ACL

        :param network_acl_id: (str) ID of the network ACL
        :param cidr: (str) IPv4 CIDR block
        :param cidr_ipv6: (str) IPv6 CIDR block
        :param rule_num: (int) ordered rule number
        :param rule_action: (str) allow or deny
        :param protocol: (str) protocol
                A value of "-1" means all protocols. If you specify "-1" or a protocol number other than "6" (TCP),
                "17" (UDP), or "1" (ICMP), traffic on all ports is allowed, regardless of any ports or ICMP types
                or codes that you specify. If you specify protocol "58" (ICMPv6) and specify an IPv4 CIDR block,
                traffic for all ICMP types and codes allowed, regardless of any that you specify. If you specify
                protocol "58" (ICMPv6) and specify an IPv6 CIDR block, you must specify an ICMP type and code.
        :param from_port: (int) starting port of the rule
        :param to_port: (int) ending port of the rule
        :param egress: (bool) Set True to specify an egress rule, False for ingress
        :return: None
        :raises: EC2UtilError
        """
        if rule_action not in ['allow', 'deny']:
            raise EC2UtilError('Invalid rule_action, must be allow or deny, found: {a}'.format(a=rule_action))
        try:
            rule_num = int(rule_num)
        except ValueError:
            raise EC2UtilError('rule_num must be a valid int')
        if cidr:
            if protocol == '-1':
                self.create_network_acl_rule_ipv4_all(
                    network_acl_id=network_acl_id,
                    cidr=cidr,
                    rule_num=rule_num,
                    rule_action=rule_action,
                    egress=egress
                )
        elif cidr_ipv6:
            if protocol == '-1':
                self.create_network_acl_rule_ipv6_all(
                    network_acl_id=network_acl_id,
                    cidr_ipv6=cidr_ipv6,
                    rule_num=rule_num,
                    rule_action=rule_action,
                    egress=egress
                )

    def set_instance_source_dest_check(self, instance_id, source_dest_check):
        """Sets the instance source/destination check, must be False for NAT instances

        :param instance_id: (str) ID of the instance
        :param source_dest_check: (bool) Set True to enable source/dest check, False to disable (for NAT)
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.set_instance_source_dest_check')
        log.info('Setting the source/destination check for instance ID [{i}] to: {v}'.format(
            i=instance_id, v=str(source_dest_check)))
        try:
            self.client.modify_instance_attribute(
                SourceDestCheck={
                    'Value': source_dest_check,
                },
                InstanceId=instance_id
            )
        except ClientError as exc:
            msg = 'Problem setting the source/destination check for instance ID [{i}] to: {v}'.format(
                i=instance_id, v=str(source_dest_check))
            raise EC2UtilError(msg) from exc

    def allocate_networks_for_cons3rt(self, cloudspace_name, cons3rt_infra, vpc_id, nat_key_pair_name,
                                      internet_gateway_id, networks, nat_ami_id,
                                      remote_access_internal_ip_last_octet='253',  remote_access_external_port=9443,
                                      remote_access_internal_port=9443, nat_instance_type='c5a.large',
                                      nat_root_volume_location='/dev/sda1', nat_root_volume_size_gib=100,
                                      fleet_agent_version=None, fleet_token=None):
        """Allocates a list of networks given a specific input format

        :param cloudspace_name: (str) Name of the cloudspace this is creating or allocating into
        :param cons3rt_infra: (Cons3rtInfra) object to represent cons3rt-infrastructure
        :param vpc_id: (str) ID of the VPC to create networks in
        :param nat_key_pair_name: (str) Name of the KeyPair to deplpy NAT instances with
        :param internet_gateway_id: (str) ID of the Internet Gateway for the cloudspace
        :param networks: (list) of (dict) network inputs
        :param nat_ami_id: (str) ID of the AMI to deploy the NAT instance
        :param remote_access_internal_ip_last_octet: (str) last octet of the internal IP of the remote access server
        :param remote_access_external_port: (int) Remote Access external TCP port number
        :param remote_access_internal_port: (int) Remote Access internal TCP port number
        :param nat_instance_type: (str) Instance type for the NAT instance
        :param nat_root_volume_location: (str) root volume location for the NAT instance
        :param nat_root_volume_size_gib: (int) Size of the NAT instance root volume in GiB
        :param fleet_agent_version: (str) Version of the Elastic Fleet Agent installed
        :param fleet_token: (str) Elastic Fleet Token for this NAT / RA box

        Example:

        networks = [
            {
                'name': 'common-net-usgw1-az2',
                'cidr': '10.1.0.0/24',
                'availability_zone': az_2,
                'routable': False,
                'is_nat_subnet': True,
                'is_cons3rt_net': False,
                'elastic_ip_address': '96.127.36.104'  <-- cons3rt-net typically
            },
        ]

        :return: (list) of created Cons3rtNetwork objects
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.allocate_networks_for_cons3rt')
        log.info('Allocation a collection of networks for a CONS3RT cloudspace with VPC ID: [{v}]'.format(v=vpc_id))

        """
        Ordered list of networks to create, the order should be:
          1. common-net / NAT subnet
          2. cons3rt-net
          3. routable additional networks
          4. non-routable additional networks
        """
        ordered_networks = []

        # Network counts
        nat_network_count = 0
        cons3rt_network_count = 0
        additional_network_count = 0

        # Validate the network data
        for network in networks:
            if 'name' not in network.keys():
                raise EC2UtilError('Missing name data for network')
            if 'cidr' not in network.keys():
                raise EC2UtilError('Missing cidr data for network: [{a}]'.format(a=network['name']))
            if 'availability_zone' not in network.keys():
                raise EC2UtilError('Missing availability_zone data for network: [{a}]'.format(a=network['name']))
            if 'routable' not in network.keys():
                raise EC2UtilError('Missing routable data for network: [{a}]'.format(a=network['name']))
            if 'is_nat_subnet' not in network.keys():
                raise EC2UtilError('Missing is_nat_subnet data for network: [{a}]'.format(a=network['name']))
            if 'is_cons3rt_net' not in network.keys():
                raise EC2UtilError('Missing is_cons3rt_net data for network: [{a}]'.format(a=network['name']))
            if network['is_nat_subnet'] and network['is_cons3rt_net']:
                raise EC2UtilError('Network [{a}] cannot be both a NAT network and a cons3rt-net'.format(
                    a=network['name']))

        # Add the NAT network
        for network in networks:
            if network['is_nat_subnet']:
                nat_network_count += 1
                ordered_networks.append(network)

        # Add the cons3rt-net network
        for network in networks:
            if network['is_cons3rt_net']:
                cons3rt_network_count += 1
                ordered_networks.append(network)

        # Add the routable additional-net networks
        for network in networks:
            if not network['is_nat_subnet'] and not network['is_cons3rt_net'] and network['routable']:
                additional_network_count += 1
                ordered_networks.append(network)

        # Add the non-routable additional-net networks
        for network in networks:
            if not network['is_nat_subnet'] and not network['is_cons3rt_net'] and not network['routable']:
                additional_network_count += 1
                ordered_networks.append(network)

        # Validate the network counts
        if nat_network_count != 1:
            raise EC2UtilError('Network list requires exactly 1 NAT network, found: [{c}]'.format(
                c=str(nat_network_count)))
        if cons3rt_network_count != 1:
            raise EC2UtilError('Network list requires exactly 1 cons3rt-net network, found: [{c}]'.format(
                c=str(cons3rt_network_count)))
        if additional_network_count < 1:
            raise EC2UtilError('Network list requires at least 1 additional network, found: [{c}]'.format(
                c=str(additional_network_count)))
        log.info('Allocating a NAT network, a cons3rt-net, and [{c}] additional networks'.format(
            c=str(additional_network_count)))

        # Build the list of ordered networks
        cons3rt_networks = []
        nat_subnet_id = None
        for network in ordered_networks:
            cons3rt_networks.append(
                Cons3rtNetwork(
                    cloudspace_name=cloudspace_name,
                    network_name=network['name'],
                    vpc_id=vpc_id,
                    cidr=network['cidr'],
                    availability_zone=network['availability_zone'],
                    internet_gateway_id=internet_gateway_id,
                    nat_key_pair_name=nat_key_pair_name,
                    routable=network['routable'],
                    is_nat_subnet=network['is_nat_subnet'],
                    is_cons3rt_net=network['is_cons3rt_net'],
                    nat_subnet_id=nat_subnet_id,
                    remote_access_internal_ip_last_octet=remote_access_internal_ip_last_octet,
                    remote_access_internal_port=remote_access_internal_port,
                    remote_access_external_port=remote_access_external_port,
                    elastic_ip_address=network['elastic_ip_address'],
                    nat_instance_ami_id=nat_ami_id,
                    nat_instance_type=nat_instance_type,
                    nat_root_volume_location=nat_root_volume_location,
                    nat_root_volume_size_gib=nat_root_volume_size_gib,
                    cons3rt_infra=cons3rt_infra,
                    fleet_agent_version=fleet_agent_version,
                    fleet_token=fleet_token
                )
            )

        # Create network resources for each network the subnets, route tables, network ACLs, and associate them
        failed_allocation = False
        for cons3rt_network in cons3rt_networks:
            try:
                cons3rt_network.set_nat_subnet_id(nat_subnet_id=nat_subnet_id)
                cons3rt_network.allocate_network(ec2=self)
            except EC2UtilError as exc:
                log.error('Failed to allocate network [{n}]: [{e}]\n{t}'.format(
                    n=cons3rt_network.network_name, e=str(exc), t=traceback.format_exc()))
                failed_allocation = True
                break
            else:
                log.info('Successfully allocated cons3rt network: [{n}]'.format(n=cons3rt_network.network_name))
                if cons3rt_network.is_nat_subnet:
                    nat_subnet_id = cons3rt_network.subnet_id

        # Add additional security group rules across networks
        if not failed_allocation:

            # Get the list of additional network internal security group IDs
            additional_network_security_group_ids = []
            for cons3rt_network in cons3rt_networks:
                if not cons3rt_network.is_nat_subnet and not cons3rt_network.is_cons3rt_net:
                    log.info('Found additional network internal security group ID: [{g}]'.format(
                        g=cons3rt_network.security_group_id))
                    additional_network_security_group_ids.append(cons3rt_network.security_group_id)

            # Add the ingress rules to each internal security group
            for cons3rt_network in cons3rt_networks:
                if not cons3rt_network.add_security_group_ingress_rules_from_group_ids(
                        ec2=self,
                        security_group_ids=additional_network_security_group_ids
                ):
                    log.error('Failed to add security group ingress rules for [{n}]'.format(
                        n=cons3rt_network.security_group_name))
                    failed_allocation = True

        # Roll back the networks if there was an error creating
        if failed_allocation:
            # First revoke security group rules
            log.info('Revoking security group rules...')
            for cons3rt_network in reversed(cons3rt_networks):
                try:
                    cons3rt_network.revoke_security_group_rules(ec2=self)
                except EC2UtilError as exc:
                    log.warning('Failed to revoke secuerity group rules for network [{n}]: [{e}]\n{t}'.format(
                        n=cons3rt_network.network_name, e=str(exc), t=traceback.format_exc()))
                else:
                    log.info('Revoked security group rules for network: [{n}]'.format(n=cons3rt_network.network_name))

            log.info('Waiting 30 seconds, then deallocating networks...')
            time.sleep(30)
            for cons3rt_network in reversed(cons3rt_networks):
                try:
                    cons3rt_network.deallocate_network(ec2=self)
                except EC2UtilError as exc:
                    log.warning('Failed to deallocate network [{n}]: [{e}]\n{t}'.format(
                        n=cons3rt_network.network_name, e=str(exc), t=traceback.format_exc()))
                else:
                    log.info('Deallocation complete for network: [{n}]'.format(n=cons3rt_network.network_name))
            raise EC2UtilError('Allocation failed for cons3rt networks')
        return cons3rt_networks


class Cons3rtNetwork(object):

    def __init__(self, cloudspace_name, network_name, vpc_id, cidr, availability_zone, internet_gateway_id=None,
                 nat_key_pair_name=None,routable=False, is_nat_subnet=False, is_cons3rt_net=False, subnet_id=None,
                 route_table_id=None, network_acl_id=None, security_group_id=None, nat_security_group_id=None,
                 nat_instance_id=None, nat_subnet_id=None, remote_access_internal_ip_last_octet='253',
                 remote_access_external_port=9443, remote_access_internal_port=9443, elastic_ip_address=None,
                 nat_instance_ami_id=None, nat_instance_type='c5a.large', nat_root_volume_location='/dev/sda1',
                 nat_root_volume_size_gib=100, cons3rt_infra=None, fleet_agent_version=None, fleet_token=None):
        self.cls_logger = mod_logger + '.Cons3rtNetwork'
        self.cloudspace_name = cloudspace_name
        self.network_name = network_name
        self.vpc_id = vpc_id
        self.cidr = cidr
        self.availability_zone = availability_zone
        self.internet_gateway_id = internet_gateway_id
        self.nat_key_pair_name = nat_key_pair_name
        self.routable = routable
        self.is_nat_subnet = is_nat_subnet
        self.is_cons3rt_net = is_cons3rt_net
        self.subnet_id = subnet_id
        self.route_table_id = route_table_id
        self.network_acl_id = network_acl_id
        self.security_group_id = security_group_id
        self.nat_security_group_id = nat_security_group_id
        self.nat_instance_id = nat_instance_id
        self.nat_subnet_id = nat_subnet_id
        self.remote_access_internal_ip_last_octet = remote_access_internal_ip_last_octet
        self.remote_access_external_port = remote_access_external_port
        self.remote_access_internal_port = remote_access_internal_port
        self.elastic_ip_address = elastic_ip_address
        self.nat_instance_ami_id = nat_instance_ami_id
        self.nat_instance_type = nat_instance_type
        self.nat_root_volume_location = nat_root_volume_location
        self.nat_root_volume_size_gib = nat_root_volume_size_gib
        self.cons3rt_infra = cons3rt_infra
        self.fleet_agent_version = fleet_agent_version
        self.fleet_token = fleet_token

        # Computed members
        self.cloudspace_name_safe = self.cloudspace_name.replace(' ', '')
        self.route_table_routes = []
        self.security_group_name = None
        self.nat_security_group_name = None
        self.security_group_ingress_rules = []
        self.security_group_egress_rules = []
        self.nat_security_group_ingress_rules = []
        self.nat_security_group_egress_rules = []
        self.region = None
        self.allocation_id = None

    def add_security_group_ingress_rules_from_group_ids(self, ec2, security_group_ids):
        """Add the provided security group IDs as ingress rules on the internal security group
        
        :param ec2: (EC2Util) boto3 client
        :param security_group_ids: (list) Security Group IDs
        :return: (bool) True if successful, False otherwise
        :raise: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_security_group_ingress_rules_from_group_ids')

        if not isinstance(security_group_ids, list):
            raise EC2UtilError('security_group_ids should be list, found: [{t}]'.format(t=type(security_group_ids)))

        log.info('Adding internal security group ingress rules for cloudspace [{c}] network [{n}]'.format(
            c=self.cloudspace_name, n=self.network_name))

        # Return if this is a NAT subnet or cons3rt-net
        if self.is_nat_subnet:
            log.info('This ia NAT subnet [{n}], nothing to do')
            return True
        if self.is_cons3rt_net:
            log.info('This ia cons3rt-net subnet [{n}], nothing to do')
            return True

        # Ensure the security_group_id is set
        if not isinstance(self.security_group_id, str):
            raise EC2UtilError('self.security_group_id should be a str, found: [{t}]'.format(t=type(
                self.security_group_id)))

        # Ensure this network's internal security group ID is included on the list
        validated_my_group_id = False
        for security_group_id in security_group_ids:
            if security_group_id == self.security_group_id:
                validated_my_group_id = True
        if not validated_my_group_id:
            security_group_ids.append(self.security_group_id)

        self.security_group_ingress_rules = get_additional_net_ingress_ip_permissions(
            internal_security_group_ids=security_group_ids
        )

        # Configure the internal security group rules
        log.info('Configuring ingress rules for security group [{i}]'.format(i=self.security_group_id))
        return ec2.configure_security_group_ingress(
                security_group_id=self.security_group_id,
                desired_ingress_rules=self.security_group_ingress_rules
        )

    def allocate_network(self, ec2):
        """Creates the CONS3RT-configurable network in AWS

        :param ec2: (EC2Util) boto3 client
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.allocate_network')

        # Ensure the boto3 client
        if not isinstance(ec2, EC2Util):
            raise EC2UtilError('ec2 arg must be type EC2Util, found: [{t}]'.format(t=type(ec2)))

        # Determine the region
        self.region = self.availability_zone[:len(self.availability_zone)-1]

        # NAT subnet is never considered "routable" -- doesn't need a NAT box
        if self.is_nat_subnet:
            if not self.internet_gateway_id:
                raise EC2UtilError('ig_id for the Internet Gateway must be specified for a NAT subnet')
            self.routable = False
            self.is_cons3rt_net = False

        # Ensure params are available for cons3rt-net
        if self.is_cons3rt_net:
            self.routable = True
            if not self.cons3rt_infra:
                raise EC2UtilError('cons3rt_infra Cons3rtInfra object must be specified for a cons3rt-net network')
            if not isinstance(self.cons3rt_infra, Cons3rtInfra):
                raise EC2UtilError('cons3rt_infra object must be type Cons3rtInfra, found: [{t}]'.format(
                    t=type(self.cons3rt_infra)))
            if not self.remote_access_internal_ip_last_octet:
                raise EC2UtilError('remote_access_internal_ip_last_octet must be specified for a cons3rt-net')
            try:
                int(self.remote_access_external_port)
            except ValueError:
                raise EC2UtilError('remote_access_external_port must be an integer TCP port number for a cons3rt-net')
            try:
                int(self.remote_access_internal_port)
            except ValueError:
                raise EC2UtilError('remote_access_internal_port must be an integer TCP port number for a cons3rt-net')

        # Ensure additional the KeyPair name is provided for a routable network
        if self.routable:
            if not self.nat_key_pair_name:
                raise EC2UtilError('nat_key_pair_name must be specified for a routable network')

        # Ensure the NAT subnet ID is provided for routable networks (that are not the NAT network)
        if not self.is_nat_subnet and self.routable:
            if not self.nat_subnet_id:
                raise EC2UtilError('nat_subnet_id must be specified for a routable network')

        log.info('Attempting to allocate a CONS3RT network with resources named [{n}], in VPC ID [{v}], with CIDR '
                 '[{c}], in availability zone [{z}]'.format(
            n=self.network_name, v=self.vpc_id, c=self.cidr, z=self.availability_zone))

        # Create the resources
        try:
            # Create the subnet
            self.subnet_id = ec2.create_subnet(
                name=self.network_name,
                cidr=self.cidr,
                vpc_id=self.vpc_id,
                availability_zone=self.availability_zone
            )
            ec2.set_subnet_auto_assign_public_ip(subnet_id=self.subnet_id, auto_assign=self.is_nat_subnet)

            # Apply the cons3rtenabled tag except for NAT subnets ONLY
            if not self.is_nat_subnet:
                if not ec2.create_cons3rt_enabled_tag(resource_id=self.subnet_id, enabled=True):
                    raise EC2UtilError('Problem setting cons3rtenabled true on subnet: {i}'.format(i=self.subnet_id))

            # Check for existing route table
            existing_vpc_route_tables = ec2.list_vpc_route_tables(vpc_id=self.vpc_id)
            for existing_vpc_route_table in existing_vpc_route_tables:
                if 'RouteTableId' not in existing_vpc_route_table.keys():
                    log.warning('RouteTableId not found in route table: {d}'.format(d=str(existing_vpc_route_table)))
                    continue
                existing_route_table_id = existing_vpc_route_table['RouteTableId']
                if 'Associations' not in existing_vpc_route_table.keys():
                    log.info('Route table has no associations: {i}'.format(i=existing_route_table_id))
                    continue
                log.info('Checking route table [{r}] for associations to subnet [{s}]'.format(
                    r=existing_route_table_id, s=self.subnet_id))
                for association in existing_vpc_route_table['Associations']:
                    if 'RouteTableAssociationId' not in association.keys():
                        log.warning('RouteTableAssociationId not found in association: {d}'.format(d=str(association)))
                        continue
                    if 'SubnetId' not in association.keys():
                        log.info('SubnetId not found in association: {d}'.format(d=str(association)))
                        continue
                    if association['SubnetId'] == self.subnet_id:
                        log.info('Subnet ID [{s}] is already associated to route table [{r}] with ID: {i}'.format(
                            s=self.subnet_id, r=existing_route_table_id, i=association['RouteTableAssociationId']))
                        self.route_table_id = existing_route_table_id
                        break

            # If an existing route table was found, disassociate and delete it
            if self.route_table_id:
                log.info('Attempting to disassociate and delete the existing route table: {i}'.format(
                    i=self.route_table_id))
                ec2.disassociate_vpc_route_table(route_table_id=self.route_table_id, subnet_id=self.subnet_id)
                ec2.delete_vpc_route_table(route_table_id=self.route_table_id)

            # Create a new route table and associate it
            log.info('Proceeding with route table creation...')
            route_table = ec2.create_vpc_route_table(name=self.network_name + '-rt', vpc_id=self.vpc_id)
            self.route_table_id = route_table['RouteTableId']
            ec2.associate_route_table(route_table_id=self.route_table_id, subnet_id=self.subnet_id)

            # Create and associate the Network ACL
            self.network_acl_id = ec2.create_network_acl(name=self.network_name + '-acl', vpc_id=self.vpc_id)
            ec2.associate_network_acl(network_acl_id=self.network_acl_id, subnet_id=self.subnet_id,
                                      delete_existing=True)
            ec2.create_network_acl_rule(network_acl_id=self.network_acl_id, rule_num=100, cidr='0.0.0.0/0',
                                         rule_action='allow', protocol='-1', egress=False)
            ec2.create_network_acl_rule(network_acl_id=self.network_acl_id, rule_num=100, cidr='0.0.0.0/0',
                                         rule_action='allow', protocol='-1', egress=True)

            # Create the internal Security Group
            if not self.is_nat_subnet:
                self.security_group_name = self.cloudspace_name_safe + '-' + self.network_name + '-sg'
                self.security_group_id = ec2.create_security_group(
                    name=self.security_group_name,
                    vpc_id=self.vpc_id,
                    description='Internal security group for {n}'.format(n=self.network_name)
                )
                if not ec2.ensure_exists(resource_id=self.security_group_id):
                    raise EC2UtilError('Internal Security Group [{n}] not found: [{r}]'.format(
                        n=self.security_group_name, r=self.security_group_id))

            # Create the NAT Security Group if this network is routable
            if self.routable and not self.is_nat_subnet:
                self.nat_security_group_name = self.cloudspace_name_safe + '-' + self.network_name + '-nat-sg'
                self.nat_security_group_id = ec2.create_security_group(
                    name=self.nat_security_group_name,
                    vpc_id=self.vpc_id,
                    description='NAT security group for the {n}'.format(n=self.network_name)
                )
                if not ec2.ensure_exists(resource_id=self.nat_security_group_id):
                    raise EC2UtilError('NAT Security Group [{n}] not found: [{r}]'.format(
                        n=self.nat_security_group_name, r=self.nat_security_group_id))

        except EC2UtilError as exc:
            msg = 'Problem creating network resources for subnet with name [{n}] in VPC ID: {v}'.format(
                n=self.network_name, v=self.vpc_id)
            raise EC2UtilError(msg) from exc

        # Get the CIDR blocks for the VPC
        vpc_cidr_blocks = ec2.retrieve_vpc_cidr_blocks(vpc_id=self.vpc_id)

        # Add a route for each VPC CIDR to the list
        for vpc_cidr in vpc_cidr_blocks:
            self.route_table_routes.append(
                IpRoute(cidr=vpc_cidr, target='local')
            )

        # For a NAT subnet, route Internet traffic to the Internet gateway
        if self.is_nat_subnet:
            self.route_table_routes.append(
                IpRoute(cidr='0.0.0.0/0', target=self.internet_gateway_id)
            )

        # Configure the route table rules for non-route-able networks
        # Since we do not need to wait for the NAT instance ID for a non-route-able network.
        # The NAT subnet requires this before launching the NAT
        if not self.routable:
            ec2.configure_routes(
                route_table_id=self.route_table_id,
                desired_routes=self.route_table_routes
            )

        # Determine the INTERNAL security group rules depending on the type of network
        # There are no security group rules for the NAT subnet
        if not self.is_nat_subnet:

            # Configure cons3rt-net ingress and egress rules, these are known at this time
            if self.is_cons3rt_net:
                self.security_group_ingress_rules += get_cons3rt_net_ingress_ip_permissions(
                    internal_security_group_id=self.security_group_id,
                    nat_security_group_id=self.nat_security_group_id,
                    remote_access_port=self.remote_access_internal_port
                )
                self.security_group_egress_rules += get_cons3rt_net_egress_ip_permissions()

            # Configure additional network ingress and egress rules
            # NOTE - The other additional network security group IDs are not known at this point
            # NOTE - Additional call required to allow all the non-cons3rt networks by ID on the INGRESS
            else:
                # Not configuring ingress rules for additional networks here, not until all SG IDs are known.
                self.security_group_egress_rules += get_additional_net_egress_ip_permissions()

            # Configure the internal security group rules
            log.info('Configuring ingress rules for security group [{n}]'.format(n=self.security_group_name))
            if not ec2.configure_security_group_ingress(
                security_group_id=self.security_group_id,
                desired_ingress_rules=self.security_group_ingress_rules
            ):
                msg = 'Problem configuring ingress rules for security group [{n}]'.format(n=self.security_group_name)
                raise EC2UtilError(msg)

            log.info('Configuring egress rules for security group [{n}]'.format(n=self.security_group_name))
            if not ec2.configure_security_group_egress(
                security_group_id=self.security_group_id,
                desired_egress_rules=self.security_group_egress_rules
            ):
                msg = 'Problem configuring egress rules for security group [{n}]'.format(n=self.security_group_name)
                raise EC2UtilError(msg)

        # Determine the NAT security group rules depending on the type of network
        # There are no security group rules for the NAT subnet
        if not self.is_nat_subnet and self.routable:

            # Configure cons3rt-net NAT ingress and egress rules, these are known at this time
            if self.is_cons3rt_net:
                self.nat_security_group_ingress_rules += get_cons3rt_net_nat_ingress_ip_permissions(
                    cons3rt_infra=self.cons3rt_infra,
                    internal_security_group_id=self.security_group_id,
                    nat_security_group_id=self.nat_security_group_id,
                    external_remote_access_port=self.remote_access_external_port
                )
                self.nat_security_group_egress_rules += get_cons3rt_net_nat_egress_ip_permissions(
                    cons3rt_infra=self.cons3rt_infra,
                    rhui_update_server_ips=ec2.get_rhui_servers(all_available=True),
                    internal_cons3rt_net_security_group_id=self.security_group_id,
                    remote_access_internal_port=self.remote_access_internal_port,
                    nat_cons3rt_net_security_group_id=self.nat_security_group_id
                )

            # Configure additional network ingress and egress rules
            else:
                self.nat_security_group_ingress_rules += get_additional_net_nat_ingress_ip_permissions(
                    internal_security_group_id=self.security_group_id
                )
                self.nat_security_group_egress_rules += get_additional_net_nat_egress_ip_permissions(
                    cons3rt_infra=self.cons3rt_infra
                )

            # Configure the internal security group rules
            log.info('Configuring ingress rules for NAT security group [{n}]'.format(n=self.nat_security_group_name))
            if not ec2.configure_security_group_ingress(
                security_group_id=self.nat_security_group_id,
                desired_ingress_rules=self.nat_security_group_ingress_rules
            ):
                msg = 'Problem configuring ingress rules for NAT security group [{n}]'.format(
                    n=self.nat_security_group_name)
                raise EC2UtilError(msg)

            log.info('Configuring egress rules for NAT security group [{n}]'.format(n=self.nat_security_group_name))
            if not ec2.configure_security_group_egress(
                security_group_id=self.nat_security_group_id,
                desired_egress_rules=self.nat_security_group_egress_rules
            ):
                msg = 'Problem configuring egress rules for NAT security group [{n}]'.format(
                    n=self.nat_security_group_name)
                raise EC2UtilError(msg)

            # Launch the NAT instance
            log.info('Launching a NAT instance for network: [{n}]'.format(n=self.network_name))
            try:
                self.nat_instance_id = self.launch_nat_instance(ec2)
            except EC2UtilError as exc:
                msg = 'Problem launching NAT for subnet with name [{n}] in VPC ID: [{v}]'.format(
                    n=self.network_name, v=self.vpc_id)
                raise EC2UtilError(msg) from exc
            log.info('NAT instance created successfully for network [{n}] with ID: [{i}]'.format(
                n=self.network_name, i=self.nat_instance_id))

        # Append the NAT instance route for routable networks and configure routes
        if self.routable:

            # Ensure the NAT instance was created; otherwise we cannot add the required route to the NAT
            if not self.nat_instance_id:
                raise EC2UtilError(
                    'NAT instance ID is required to configure routes for route-able network: [{n}]'.format(
                        n=self.network_name))

            # Append the route to send all traffic to the NAT
            self.route_table_routes.append(
                IpRoute(cidr='0.0.0.0/0', target=self.nat_instance_id)
            )

            # Configure the route table rules for the routeable network now that we know the NAT instance ID
            ec2.configure_routes(
                route_table_id=self.route_table_id,
                desired_routes=self.route_table_routes
            )

    def deallocate_network(self, ec2):
        """Rolls back a cons3rt network that failed to create, or deallocates an existing network

        :param ec2: (EC2Util) boto3 client
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.deallocate_network')

        # Ensure the boto3 client
        if not isinstance(ec2, EC2Util):
            raise EC2UtilError('ec2 arg must be type EC2Util, found: [{t}]'.format(t=type(ec2)))

        # Disassociate the elastic IP
        if self.allocation_id:
            try:
                ec2.disassociate_elastic_ips_from_instance(instance_id=self.nat_instance_id)
            except AWSAPIError as exc:
                log.warning('Problem disassociating elastic IPs from NAT instance ID [{i}]: [{e}]\n{t}'.format(
                    i=self.nat_instance_id, e=str(exc), t=traceback.format_exc()))
            else:
                log.info('Waiting 5 seconds...')
                time.sleep(5)

        # Terminate the EC2 instance
        if self.nat_instance_id:
            try:
                ec2.terminate_instance(instance_id=self.nat_instance_id)
            except EC2UtilError as exc:
                log.warning('Problem terminating NAT instance ID [{i}]: [{e}]\n{t}'.format(
                    i=self.nat_instance_id, e=str(exc), t=traceback.format_exc()))
            else:
                log.info('Waiting 5 seconds...')
                time.sleep(5)

        # Revoke rules from the NAT security group
        self.revoke_security_group_rules(ec2=ec2)

        # If an existing route table was found, disassociate and delete it
        if self.route_table_id:
            log.info('Attempting to disassociate and delete the route table: [{i}]'.format(i=self.route_table_id))
            try:
                ec2.disassociate_vpc_route_table(route_table_id=self.route_table_id, subnet_id=self.subnet_id)
            except EC2UtilError as exc:
                log.warning('Problem disassociating route table [{r}] from subnet [{s}]: [{e}]\n{t}'.format(
                    r=self.route_table_id, s=self.subnet_id, e=str(exc), t=traceback.format_exc()))
            try:
                ec2.delete_vpc_route_table(route_table_id=self.route_table_id)
            except EC2UtilError as exc:
                log.warning('Problem deleting route table [{r}]: [{e}]\n{t}'.format(
                    r=self.route_table_id, e=str(exc), t=traceback.format_exc()))

        # If an existing network ACL was found, disassociate and delete it
        if self.network_acl_id:
            log.info('Attempting to disassociate and delete the network ACL: [{i}]'.format(i=self.network_acl_id))
            try:
                ec2.disassociate_network_acl(network_acl_id=self.network_acl_id, subnet_id=self.subnet_id,
                                             vpc_id=self.vpc_id)
            except EC2UtilError as exc:
                log.warning('Problem disassociating network ACL [{n}] from subnet [{s}]: [{e}]\n{t}'.format(
                    n=self.network_acl_id, s=self.subnet_id, e=str(exc), t=traceback.format_exc()))
            try:
                ec2.delete_network_acl(network_acl_id=self.network_acl_id)
            except EC2UtilError as exc:
                log.warning('Problem deleting network ACL [{n}]: [{e}]\n{t}'.format(
                    n=self.network_acl_id, e=str(exc), t=traceback.format_exc()))

        # Delete the subnet
        if self.subnet_id:
            log.info('Waiting 5 seconds...')
            time.sleep(5)
            try:
                ec2.delete_subnet(subnet_id=self.subnet_id)
            except EC2UtilError as exc:
                log.warning('Problem deleting subnet [{s}]: [{e}]\n{t}'.format(
                    s=self.subnet_id, e=str(exc), t=traceback.format_exc()))

        # Delete the NAT security group
        if self.nat_security_group_id:
            log.info('Waiting 20 seconds before deleting security groups...')
            time.sleep(20)
            try:
                ec2.delete_security_group(security_group_id=self.nat_security_group_id)
            except EC2UtilError as exc:
                log.warning('Problem deleting security group [{g}]: [{e}]\n{t}'.format(
                    g=self.nat_security_group_id, e=str(exc), t=traceback.format_exc()))
        if self.security_group_id:
            log.info('Waiting 20 seconds before deleting security groups...')
            time.sleep(20)
            try:
                ec2.delete_security_group(security_group_id=self.security_group_id)
            except EC2UtilError as exc:
                log.warning('Problem deleting security group [{g}]: [{e}]\n{t}'.format(
                    g=self.security_group_id, e=str(exc), t=traceback.format_exc()))

        log.info('Completed deallocation of subnet ID [{s}] in VPC ID [{v}]'.format(s=self.subnet_id, v=self.vpc_id))

    def launch_nat_instance(self, ec2):
        """Launches a NAT instance to attach to this CONS3RT network

        :param ec2: (EC2Util) boto3 client
        :return: None
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.launch_nat_instance')

        # Validate required data exists
        if not self.nat_instance_ami_id:
            raise EC2UtilError('AMI ID required to deploy NAT instance')

        # Get the remote access internal IP address
        remote_access_internal_ip=get_remote_access_internal_ip(
            cons3rt_net_cidr=self.cidr,
            remote_access_ip_last_octet=self.remote_access_internal_ip_last_octet
        )

        # Determine the hostname
        nat_hostname = self.cloudspace_name_safe + '-' + self.network_name

        # Ensure the AMI exists TODO

        # Read in the user-data script contents from the awsutil variable
        user_data_script_contents = get_linux_nat_config_user_data_script_contents()

        # Replace the guac server IP, port, and virt tech
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_GUAC_SERVER_IP', remote_access_internal_ip)
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_GUAC_SERVER_PORT', str(self.remote_access_internal_port))
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_HOSTNAME', nat_hostname)
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_SUBNET_CIDR_BLOCK', self.cidr)
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_VIRT_TECH', 'amazon')
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_FLEET_AGENT_VERSION', self.fleet_agent_version)
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_FLEET_SERVER_FQDN', self.cons3rt_infra.elastic_fleet_server_fqdn)
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_FLEET_MANAGER_PORT', str(self.cons3rt_infra.elastic_logging_port))
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_FLEET_TOKEN', self.fleet_token)
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_CONS3RT_ROOT_CA_DOWNLOAD_URL', self.cons3rt_infra.ca_download_url)

        # Create the firewalld rules
        firewalld_rules = 'firewall-cmd --permanent --add-forward-port=port={e}:proto=tcp:toport={i}:toaddr={r}'.format(
            e=self.remote_access_external_port, i=self.remote_access_internal_port, r=remote_access_internal_ip)
        firewalld_rules += '\n'

        # Replace the firewalld rules
        log.info('Replacing CODE_ADD_FIREWALLD_DNAT_RULES_HERE with:\n[{r}]'.format(r=firewalld_rules))
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_ADD_FIREWALLD_DNAT_RULES_HERE', firewalld_rules)

        # Determine the NAT instance name tag
        nat_instance_name = nat_hostname + '-nat'

        # Launch the NAT VM
        log.info('Attempting to launch the NAT instance with name: [{n}]'.format(n=nat_instance_name))
        try:
            instance_info = ec2.launch_instance(
                ami_id=self.nat_instance_ami_id,
                key_name=self.nat_key_pair_name,
                subnet_id=self.nat_subnet_id,
                security_group_id=self.nat_security_group_id,
                user_data_script_contents=user_data_script_contents,
                instance_type=self.nat_instance_type,
                root_volume_location=self.nat_root_volume_location,
                root_volume_size_gb=self.nat_root_volume_size_gib
            )
        except EC2UtilError as exc:
            msg = 'Problem launching the NAT instance with name: {n}'.format(n=nat_instance_name)
            raise EC2UtilError(msg) from exc

        # Get the NAT instance ID
        if 'InstanceId' not in instance_info.keys():
            raise EC2UtilError('InstanceId not found in instance data: [{d}]'.format(d=str(instance_info)))
        self.nat_instance_id = instance_info['InstanceId']
        log.info('Launched NAT instance ID: {i}'.format(i=self.nat_instance_id))

        # Ensure the instance ID exists
        if not ec2.ensure_exists(resource_id=self.nat_instance_id):
            raise EC2UtilError('Problem finding instance ID after successful creation: {i}'.format(
                i=self.nat_instance_id))

        # Apply the name tag
        if not ec2.create_name_tag(resource_id=self.nat_instance_id, resource_name=nat_instance_name):
            raise EC2UtilError('Problem adding name tag name of instance ID: {i}'.format(i=self.nat_instance_id))

        # Wait for instance availability
        if not ec2.wait_for_instance_availability(instance_id=self.nat_instance_id):
            msg = 'NAT instance did not become available'
            raise EC2UtilError(msg)
        log.info('NAT instance ID [{i}] is available and passed all checks'.format(i=self.nat_instance_id))

        # Set the source/dest checks to disabled/False
        ec2.set_instance_source_dest_check(instance_id=self.nat_instance_id, source_dest_check=False)
        log.info('Set NAT instance ID [{i}] source/destination check to disabled'.format(i=self.nat_instance_id))

        # Assign the elastic IP to the instance if specified, otherwise allocate a new elastic IP address
        if self.elastic_ip_address:
            self.allocation_id = ec2.get_elastic_ip_allocation_id(self.elastic_ip_address)
        else:
            eip_info = ec2.allocate_elastic_ip()
            # {'AllocationId': allocation_id, 'PublicIp': public_ip}
            if 'AllocationId' not in eip_info.keys():
                raise EC2UtilError('Elastic IP AllocationId not found to attach to the NAT instance')
            if 'PublicIp' not in eip_info.keys():
                raise EC2UtilError('Elastic IP PublicIp not found to attach to the NAT instance')
            self.elastic_ip_address = eip_info['PublicIp']
            self.allocation_id = eip_info['AllocationId']

        # Associate the elastic IP to the NAT
        ec2.associate_elastic_ip_to_instance_id(
            allocation_id=self.allocation_id,
            instance_id=self.nat_instance_id
        )
        return self.nat_instance_id

    def revoke_security_group_rules(self, ec2):
        """Revokes security group rules for this network

        :param ec2: (EC2Util) boto3 client
        :return: (bool) True if successful, False otherwise
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.revoke_security_group_rules')
        log.info('Revoking security group rules for cloudspace [{c}] network [{n}]...'.format(
            n=self.network_name, c=self.cloudspace_name))

        revoke_success = True

        # Revoke rules from the NAT security group
        if self.nat_security_group_id:
            try:
                ec2.revoke_security_group_rules(security_group_id=self.nat_security_group_id)
            except EC2UtilError as exc:
                log.warning('Problem revoking security group rules from [{g}]: [{e}]\n{t}'.format(
                    g=self.nat_security_group_id, e=str(exc), t=traceback.format_exc()))
                revoke_success = False

        # Revoke rules form the internal security group
        if self.security_group_id:
            try:
                ec2.revoke_security_group_rules(security_group_id=self.security_group_id)
            except EC2UtilError as exc:
                log.warning('Problem revoking security group rules from [{g}]: [{e}]\n{t}'.format(
                    g=self.security_group_id, e=str(exc), t=traceback.format_exc()))
                revoke_success = False
        return revoke_success


    def set_nat_subnet_id(self, nat_subnet_id):
        """Sets the nat_subnet_id

        :return: None
        """
        self.nat_subnet_id = nat_subnet_id


class IpPermission(object):
    """

    IpProtocol: tcp , udp , icmp , icmpv6, -1 for all
    FromPort --> ToPort is a range of ports (not a source/destination port)

    """
    def __init__(self, IpProtocol, CidrIp=None, CidrIpv6=None, Description=None, PrefixListId=None, GroupId=None,
                 FromPort=None, ToPort=None):
        self.IpProtocol = IpProtocol
        self.CidrIp = CidrIp
        self.CidrIpv6 = CidrIpv6
        self.Description = Description
        self.PrefixListId = PrefixListId
        self.GroupId = GroupId
        self.FromPort = FromPort
        self.ToPort = ToPort

    def __str__(self):
        out_str = 'Protocol: {p}'.format(p=self.IpProtocol)
        if self.FromPort:
            out_str += ', FromPort: {c}'.format(c=self.FromPort)
        if self.ToPort:
            out_str += ', ToPort: {c}'.format(c=self.ToPort)
        if self.CidrIp:
            out_str += ', CidrIp: {c}'.format(c=self.CidrIp)
        if self.CidrIpv6:
            out_str += ', CidrIpv6: {c}'.format(c=self.CidrIpv6)
        if self.PrefixListId:
            out_str += ', PrefixListId: {p}'.format(p=self.PrefixListId)
        if self.GroupId:
            out_str += ', GroupId: {p}'.format(p=self.GroupId)
        if self.Description:
            out_str += ', Description: {d}'.format(d=self.Description)
        return out_str

    def __eq__(self, other):
        if self.IpProtocol != other.IpProtocol:
            return False
        if self.FromPort and not other.FromPort:
            return False
        if self.ToPort and not other.ToPort:
            return False
        if not self.FromPort and other.FromPort:
            return False
        if not self.ToPort and other.ToPort:
            return False
        if self.FromPort and other.FromPort:
            if self.FromPort != other.FromPort:
                return False
        if self.ToPort and other.ToPort:
            if self.ToPort != other.ToPort:
                return False
        if self.CidrIp and other.CidrIp:
            return self.CidrIp == other.CidrIp
        if self.CidrIpv6 and other.CidrIpv6:
            return self.CidrIpv6 == other.CidrIpv6
        if self.PrefixListId and other.PrefixListId:
            return self.PrefixListId == other.PrefixListId
        if self.GroupId and other.GroupId:
            return self.GroupId == other.GroupId
        return False

    def get_json(self):
        json_output = {
            'IpProtocol': self.IpProtocol
        }
        if self.FromPort:
            json_output['FromPort'] = self.FromPort
        if self.ToPort:
            json_output['ToPort'] = self.ToPort
        if self.CidrIp:
            json_output['IpRanges'] = []
            rule = {
                'CidrIp': self.CidrIp
            }
            if self.Description:
                rule['Description'] = self.Description
            json_output['IpRanges'].append(rule)
        if self.CidrIpv6:
            json_output['Ipv6Ranges'] = []
            rule = {
                'CidrIpv6': self.CidrIpv6
            }
            if self.Description:
                rule['Description'] = self.Description
            json_output['Ipv6Ranges'].append(rule)
        if self.PrefixListId:
            json_output['PrefixListIds'] = []
            rule = {
                'PrefixListId': self.PrefixListId
            }
            if self.Description:
                rule['Description'] = self.Description
            json_output['PrefixListIds'].append(rule)
        print(json_output)
        if self.GroupId:
            json_output['UserIdGroupPairs'] = []
            rule = {
                'GroupId': self.GroupId
            }
            if self.Description:
                rule['Description'] = self.Description
            json_output['UserIdGroupPairs'].append(rule)
        return json_output


class IpRoute(object):
    """
    Represents a single route in AWS


    """
    def __init__(self, target, cidr=None, cidr_ipv6=None, description=None, instance_owner_id=None, state=None,
                 origin=None):
        self.target = target
        if cidr and cidr_ipv6:
            raise AttributeError('Can only have either cidr or cidr_ipv6')
        if not cidr and not cidr_ipv6:
            raise AttributeError('Must provide one of: cidr, cidr_ipv6')
        self.cidr = cidr
        self.cidr_ipv6 = cidr_ipv6
        self.description = description
        self.instance_owner_id = instance_owner_id
        self.state = state
        self.origin = origin

    def __str__(self):
        out_str = ''
        if self.cidr:
            out_str += 'Destination IPv4 CIDR: {c}'.format(c=self.cidr)
        if self.cidr_ipv6:
            out_str += 'Destination IPv6 CIDR: {c}'.format(c=self.cidr_ipv6)
        if self.target:
            out_str += ', Target: {t}'.format(t=self.target)
        if self.description:
            out_str += ', Description: {d}'.format(d=self.description)
        if self.instance_owner_id:
            out_str += ', Instance Owner ID: {i}'.format(i=self.instance_owner_id)
        if self.state:
            out_str += ', State: {s}'.format(s=self.state)
        if self.origin:
            out_str += ', Origin: {o}'.format(o=self.origin)
        return out_str

    def __eq__(self, other):
        if self.cidr and other.cidr:
            if self.cidr == other.cidr:
                if self.target == other.target:
                    return True
        if self.cidr_ipv6 and other.cidr_ipv6:
            if self.cidr_ipv6 == other.cidr_ipv6:
                if self.target == other.target:
                    return True
        return False

    def get_json(self):
        json_output = {
            self.get_target_type(): self.target
        }
        if self.cidr:
            json_output['DestinationCidrBlock'] = self.cidr
        if self.cidr_ipv6:
            json_output['DestinationIpv6CidrBlock'] = self.cidr_ipv6
        if self.instance_owner_id:
            json_output['InstanceOwnerId'] = self.instance_owner_id
        if self.state:
            json_output['State'] = self.state
        if self.origin:
            json_output['Origin'] = self.origin
        print(json_output)
        return json_output

    def get_target_type(self):
        if self.target == 'local' or self.target.startswith('igw-'):
            return 'GatewayId'
        elif self.target.startswith('tgw-'):
            return 'TransitGatewayId'
        elif self.target.startswith('i-'):
            return 'InstanceId'
        elif self.target.startswith('pcx-'):
            return 'VpcPeeringConnectionId'
        elif self.target.startswith('eni-'):
            return 'NetworkInterfaceId'
        elif self.target.startswith('eigw-'):
            return 'EgressOnlyInternetGatewayId'
        elif self.target.startswith('nat-'):
            return 'NatGatewayId'
        elif self.target.startswith('lgw-'):
            return 'LocalGatewayId'
        return None

    def get_cidr_type(self):
        if self.cidr:
            return 'DestinationCidrBlock'
        elif self.cidr_ipv6:
            return 'DestinationIpv6CidrBlock'
        return None


class TransitGateway(object):

    def __init__(self, transit_gateway_id=None, name=None, description='CONS3RT transit gateway'):
        self.cls_logger = mod_logger + '.TransitGateway'
        self.id = transit_gateway_id
        self.name = name
        self.description = description
        self.default_options = {
            'AmazonSideAsn': 64512,
            'AutoAcceptSharedAttachments': 'disable',
            'DefaultRouteTableAssociation': 'enable',
            'DefaultRouteTablePropagation': 'enable',
            'VpnEcmpSupport': 'enable',
            'DnsSupport': 'enable',
            'MulticastSupport': 'disable'
        }
        self.arn = None
        self.state = None
        self.owner_id = None
        self.creation_time = None
        self.options = None
        self.tags = None
        self.vpc_attachments = []
        self.route_tables = []
        self.associations = []
        self.propagations = []
        self.routes = []  # List of TransitGatewayRoute objects
        self.client = get_ec2_client()
        if self.id:
            self.update_state()
        elif self.name:
            self.create()

    def update_state(self):
        """Updates status on the transit gateway and its attachments

        :return: None
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.update_state')
        log.info('Getting state on transit gateway {t} and its attachments, route tables, associations, and '
                 'propagations'.format(t=self.id))
        try:
            response = self.client.describe_transit_gateways(
                TransitGatewayIds=[self.id],
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem describing transit gateway: {t}'.format(t=self.id)
            raise AwsTransitGatewayError(msg) from exc
        if 'TransitGateways' not in response.keys():
            raise AwsTransitGatewayError('TransitGateways not found in response: {r}'.format(r=str(response)))
        if len(response['TransitGateways']) != 1:
            raise AwsTransitGatewayError('Problem retrieving a single transit gateways from response: {r}'.format(
                r=str(response)))
        try:
            self.arn = response['TransitGateways'][0]['TransitGatewayArn']
            self.state = response['TransitGateways'][0]['State']
            self.owner_id = response['TransitGateways'][0]['OwnerId']
            self.creation_time = response['TransitGateways'][0]['CreationTime']
            self.options = response['TransitGateways'][0]['Options']
            self.tags = response['TransitGateways'][0]['Tags']
            for tag in self.tags:
                if tag['Key'] == 'Name':
                    self.name = tag['Value']
        except KeyError as exc:
            msg = 'Unable to retrieve transit gateway info from response: {d}'.format(d=str(response))
            raise AwsTransitGatewayError(msg) from exc
        self.update_vpc_attachments()
        self.update_route_tables()
        self.update_associations()
        self.update_propagations()
        state_msg = 'Updated state [{s}] for transit gateway [{t}], with {n} VPC attachments, {r} route tables, ' \
                    '{c} associations, and {p} propagations'.format(s=self.state, t=self.id,
                                                                    n=str(len(self.vpc_attachments)),
                                                                    r=str(len(self.route_tables)),
                                                                    c=str(len(self.associations)),
                                                                    p=str(len(self.propagations)))
        log.info(state_msg)

    def update_vpc_attachments(self):
        """Updates the VPC attachments for the transit gateway

        :return: None
        :raises: AwsTransitGatewayError
        """
        self.vpc_attachments = []
        filters = [{'Name': 'transit-gateway-id', 'Values': [self.id]}]
        try:
            response = self.client.describe_transit_gateway_vpc_attachments(
                Filters=filters,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem retrieving transit gateway attachments from transit gateway ID: {i}'.format(i=self.id)
            raise AwsTransitGatewayError(msg) from exc
        if 'TransitGatewayVpcAttachments' not in response.keys():
            raise AwsTransitGatewayError('TransitGatewayVpcAttachments not found in response: {r}'.format(
                r=str(response)))
        self.vpc_attachments = response['TransitGatewayVpcAttachments']

    def update_route_tables(self):
        """Update route tables for the transit gateway

        :return: None
        :raises: AwsTransitGatewayError
        """
        self.route_tables = []
        filters = [{'Name': 'transit-gateway-id', 'Values': [self.id]}]
        try:
            response = self.client.describe_transit_gateway_route_tables(
                Filters=filters,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem retrieving transit gateway route tables for transit gateway ID: {i}'.format(i=self.id)
            raise AwsTransitGatewayError(msg) from exc
        if 'TransitGatewayRouteTables' not in response.keys():
            raise AwsTransitGatewayError('TransitGatewayRouteTables not found in response: {r}'.format(r=str(response)))
        self.route_tables = response['TransitGatewayRouteTables']

    def update_associations(self):
        """Update associations for the route tables

        :return: None
        :raises: AwsTransitGatewayError
        """
        self.associations = []
        for route_table in self.route_tables:
            try:
                response = self.client.get_transit_gateway_route_table_associations(
                    TransitGatewayRouteTableId=route_table['TransitGatewayRouteTableId']
                )
            except ClientError as exc:
                msg = 'Problem retrieving route table associations for route table: {i}'.format(
                    i=route_table['TransitGatewayRouteTableId'])
                raise AwsTransitGatewayError(msg) from exc
            if 'Associations' not in response.keys():
                msg = 'Associations not found in response: {r}'.format(r=str(response))
                raise AwsTransitGatewayError(msg)
            for association_response in response['Associations']:
                association = dict(association_response)
                association['TransitGatewayRouteTableId'] = route_table['TransitGatewayRouteTableId']
                self.associations.append(association)

    def update_propagations(self):
        """Update propagations for the route tables

        :return: None
        :raises: AwsTransitGatewayError
        """
        self.propagations = []
        for route_table in self.route_tables:
            try:
                response = self.client.get_transit_gateway_route_table_propagations(
                    TransitGatewayRouteTableId=route_table['TransitGatewayRouteTableId']
                )
            except ClientError as exc:
                msg = 'Problem retrieving route table propagations for route table: {i}'.format(
                    i=route_table['TransitGatewayRouteTableId'])
                raise AwsTransitGatewayError(msg) from exc
            if 'TransitGatewayRouteTablePropagations' not in response.keys():
                msg = 'TransitGatewayRouteTablePropagations not found in response: {r}'.format(r=str(response))
                raise AwsTransitGatewayError(msg)
            for propagation_response in response['TransitGatewayRouteTablePropagations']:
                propagation = dict(propagation_response)
                propagation['TransitGatewayRouteTableId'] = route_table['TransitGatewayRouteTableId']
                self.propagations.append(propagation)

    def create(self):
        """Creates a transit gateway with default configurations

        :return: (dict) Transit gateway object
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.create')
        log.info('Creating transit gateway named: {n}'.format(n=self.name))
        try:
            response = self.client.create_transit_gateway(
                Description=self.description,
                Options=self.default_options,
                TagSpecifications=[
                    {
                        'ResourceType': 'transit-gateway',
                        'Tags': [
                            {
                                'Key': 'Name',
                                'Value': self.name
                            },
                        ]
                    },
                ],
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem creating transit gateway'
            raise AwsTransitGatewayError(msg) from exc
        try:
            self.id = response['TransitGateway']['TransitGatewayId']
            self.arn = response['TransitGateway']['TransitGatewayArn']
            self.state = response['TransitGateway']['State']
            self.owner_id = response['TransitGateway']['OwnerId']
            self.description = response['TransitGateway']['Description']
            self.creation_time = response['TransitGateway']['CreationTime']
            self.options = response['TransitGateway']['Options']
            self.tags = response['TransitGateway']['Tags']
        except KeyError as exc:
            msg = 'Unable to retrieve transit gateway info from response: {d}'.format(d=str(response))
            raise AwsTransitGatewayError(msg) from exc

    def delete(self):
        """Deletes this transit gateway

        :return: (dict) into about the deleted transit gateway (see boto3 docs)
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.delete_transit_gateway')
        log.info('Disabling propagations in transit gateway: {i}'.format(i=self.id))
        for propagation in self.propagations:
            self.disable_propagation(
                route_table_id=propagation['TransitGatewayRouteTableId'],
                attachment_id=propagation['TransitGatewayAttachmentId']
            )
        log.info('Disassociating route tables in transit gateway: {i}'.format(i=self.id))
        for association in self.associations:
            self.disassociate_route_table_from_attachment(
                route_table_id=association['TransitGatewayRouteTableId'],
                attachment_id=association['TransitGatewayAttachmentId']
            )
        self.wait_for_available()
        log.info('Deleting route tables in transit gateway: {i}'.format(i=self.id))
        for route_table in self.route_tables:
            if route_table['DefaultAssociationRouteTable']:
                log.info('Skipping deletion of default association route table: {i}'.format(
                    i=route_table['TransitGatewayRouteTableId']
                ))
                continue
            self.delete_route_table(route_table_id=route_table['TransitGatewayRouteTableId'])
        self.wait_for_available()
        for attached_vpc in self.vpc_attachments:
            self.delete_attachment(attachment_id=attached_vpc['TransitGatewayAttachmentId'])
        self.wait_for_available()
        log.info('Deleting transit gateway: {t}'.format(t=self.id))
        try:
            response = self.client.delete_transit_gateway(
                TransitGatewayId=self.id,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem deleting transit gateway: {i}'.format(i=self.id)
            raise AwsTransitGatewayError(msg) from exc
        if 'TransitGateway' not in response.keys():
            raise AwsTransitGatewayError('TransitGateway not found in response: {r}'.format(r=str(response)))
        try:
            self.state = response['TransitGateway']['State']
        except KeyError as exc:
            msg = 'Unable to retrieve deleted transit gateway info from response: {d}'.format(d=str(response))
            raise AwsTransitGatewayError(msg) from exc
        return response['TransitGateway']

    def add_vpc_attachment(self, vpc_id, subnet_ids):
        """Attached a VPC to the transit gateway using the provided subnet IDs

        :param vpc_id: (str) ID of the VPC to attach
        :param subnet_ids: (list) Subnet IDs in the VPC to attach
        :return: (str) Transit gateway attachment ID
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.add_vpc_attachment')
        for attachment in self.vpc_attachments:
            if attachment['VpcId'] == vpc_id:
                log.info('VPC [{v}] is already attached to transit gateway: {t}'.format(v=vpc_id, t=self.id))
                return attachment['TransitGatewayAttachmentId']
        log.info('Creating transit gateway [{t}] attachment to VPC ID [{v}] and subnet IDs: [{s}]'.format(
            t=self.id, v=vpc_id, s=','.join(subnet_ids)))
        try:
            response = self.client.create_transit_gateway_vpc_attachment(
                TransitGatewayId=self.id,
                VpcId=vpc_id,
                SubnetIds=subnet_ids,
                Options={
                    'DnsSupport': 'enable',
                    'Ipv6Support': 'disable'
                },
                TagSpecifications=[
                    {
                        'ResourceType': 'transit-gateway-attachment',
                        'Tags': [
                            {
                                'Key': 'Name',
                                'Value': '{t}-{v}'.format(t=self.name, v=vpc_id)
                            },
                        ]
                    },
                ],
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem attaching VPC ID {i} to transit gateway ID {t}'.format(i=vpc_id, t=self.id)
            raise AwsTransitGatewayError(msg) from exc
        if 'TransitGatewayVpcAttachment' not in response.keys():
            raise AwsTransitGatewayError('TransitGatewayVpcAttachment not found in response: {r}'.format(
                r=str(response)))
        self.vpc_attachments.append(response['TransitGatewayVpcAttachment'])
        return response['TransitGatewayVpcAttachment']['TransitGatewayAttachmentId']

    def delete_attachment(self, attachment_id):
        """Deletes a transit gateway attachment

        :param attachment_id: (str) attachment ID
        :return: (dict) info about the deleted attachment (see boto3 docs)
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.delete_attachment')
        found_attached_vpc = None
        for attached_vpc in self.vpc_attachments:
            if attached_vpc['TransitGatewayAttachmentId'] == attachment_id:
                found_attached_vpc = dict(attached_vpc)
                break
        if not found_attached_vpc:
            raise AwsTransitGatewayError('Attachment ID {a} not found in transit gateway {t}'.format(
                a=attachment_id, t=self.id))
        associated_route_table_ids = []
        for association in self.associations:
            if association['TransitGatewayAttachmentId'] == attachment_id:
                associated_route_table_ids.append(association['TransitGatewayRouteTableId'])
        for associated_route_table_id in associated_route_table_ids:
            self.disassociate_route_table_from_attachment(
                route_table_id=associated_route_table_id,
                attachment_id=attachment_id
            )
        log.info('Deleting transit gateway attachment {a} from transit gateway: {t}'.format(
            a=attachment_id, t=self.id))
        try:
            self.client.delete_transit_gateway_vpc_attachment(
                TransitGatewayAttachmentId=attachment_id,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem deleting transit gateway attachment {a} from transit gateway: {t}'.format(
                a=attachment_id, t=self.id)
            raise AwsTransitGatewayError(msg) from exc
        vpc_attachments = list(self.vpc_attachments)
        self.vpc_attachments = []
        for vpc_attachment in vpc_attachments:
            if vpc_attachment['TransitGatewayAttachmentId'] != attachment_id:
                self.vpc_attachments.append(vpc_attachment)
        return found_attached_vpc

    def delete_vpc_attachment(self, vpc_id):
        """Deletes a transit gateway attachment

        :param vpc_id: (str) ID of the VPC
        :return: (dict) info about the deleted attachment (see boto3 docs)
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.delete_vpc_attachment')
        attachment_id = None
        for attached_vpc in self.vpc_attachments:
            if attached_vpc['VpcId'] == vpc_id:
                attachment_id = attached_vpc['TransitGatewayAttachmentId']
                break
        if not attachment_id:
            log.info('VPC ID {v} not attached to transit gateway {t}'.format(v=vpc_id, t=self.id))
            return None
        log.info('Deleting attachment [{a}] for VPC [{v}] from transit gateway: {t}'.format(
            a=attachment_id, v=vpc_id, t=self.id))
        return self.delete_attachment(attachment_id=attachment_id)

    def get_attachment_for_vpc(self, vpc_id):
        """For the provided VPC ID, return the attachment ID if one exists

        :param vpc_id: (str) ID of the VPC
        :return: (str) ID of the attachment or None
        """
        log = logging.getLogger(self.cls_logger + '.get_attachment_for_vpc')
        self.update_state()
        attachment_id = None
        for attached_vpc in self.vpc_attachments:
            if attached_vpc['VpcId'] == vpc_id:
                attachment_id = attached_vpc['TransitGatewayAttachmentId']
        if attachment_id:
            log.info('Found attachment for VPC [{v}]: {a}'.format(v=vpc_id, a=attachment_id))
            return attachment_id
        else:
            log.info('No attachments found for VPC ID: {v}'.format(v=vpc_id))
            return None

    def create_route_table_for_attachment(self, attachment_id, remove_existing=True, propagation=False):
        """Creates a route table for the specified attachment ID

        :param attachment_id: (str) ID of the attachment
        :param remove_existing: (bool) Set True to remove existing association and create a new one if it exists
        :param propagation: (bool) set True to enable route propagation to the attachment ID
        :return: (str) route table ID
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.create_route_table_for_attachment')
        self.wait_for_available()

        # Check for existing associated route table
        route_table_id = None
        for association in self.associations:
            if association['TransitGatewayAttachmentId'] == attachment_id:
                route_table_id = association['TransitGatewayRouteTableId']
                break

        # If an associated route table was found, return it
        if route_table_id:
            log.info('Found existing route table for attachment [{a}]: {r}'.format(a=attachment_id, r=route_table_id))
            if not remove_existing:
                log.info('remove_existing not set, returning the existing route table ID: {i}'.format(i=route_table_id))
                return route_table_id
            else:
                log.info('Removing association to existing route table ID: {i}'.format(i=route_table_id))
                self.disassociate_route_table_from_attachment(
                    route_table_id=route_table_id,
                    attachment_id=attachment_id
                )
                self.wait_for_available()

        # If not found, create a new route table
        route_table_id = self.create_transit_gateway_route_table(route_table_name='{n}-rt'.format(n=self.name))

        # Associate the new route table
        self.associate_route_table_to_attachment(
            route_table_id=route_table_id,
            attachment_id=attachment_id
        )

        # Enable propagation
        if propagation:
            self.enable_propagation(
                route_table_id=route_table_id,
                attachment_id=attachment_id
            )
        log.info('Completed configuring route table for attachment: {a}'.format(a=attachment_id))
        return route_table_id

    def create_transit_gateway_route_table(self, route_table_name=None):
        """Creates a new route table

        :return: (str) route table ID
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.create_transit_gateway_route_table')
        if not route_table_name:
            route_table_name = self.name
        log.info('Creating route table in transit gateway: {i}'.format(i=self.id))
        try:
            response = self.client.create_transit_gateway_route_table(
                TransitGatewayId=self.id,
                TagSpecifications=[
                    {
                        'ResourceType': 'transit-gateway-route-table',
                        'Tags': [
                            {
                                'Key': 'Name',
                                'Value': route_table_name
                            },
                        ]
                    },
                ],
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem creating route table in transit gateway ID {i}'.format(i=self.id)
            raise AwsTransitGatewayError(msg) from exc
        if 'TransitGatewayRouteTable' not in response.keys():
            raise AwsTransitGatewayError('TransitGatewayRouteTable not found in response: {r}'.format(
                r=str(response)))
        self.route_tables.append(response['TransitGatewayRouteTable'])
        return response['TransitGatewayRouteTable']['TransitGatewayRouteTableId']

    def delete_route_table(self, route_table_id):
        """Deletes associations to and the specified route table ID

        :param route_table_id: (str) ID of the route table
        :return: (dict) info for the deleted route table (see boto3 docs)
        """
        log = logging.getLogger(self.cls_logger + '.delete_route_table')
        log.info('Deleting associations for route table: {i}'.format(i=route_table_id))
        for association in self.associations:
            if association['TransitGatewayRouteTableId'] == route_table_id:
                self.disassociate_route_table_from_attachment(
                    route_table_id=route_table_id,
                    attachment_id=association['TransitGatewayAttachmentId']
                )
        log.info('Deleting route table: {i}'.format(i=route_table_id))
        try:
            response = self.client.delete_transit_gateway_route_table(
                TransitGatewayRouteTableId=route_table_id,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem deleting route table: {i}'.format(i=route_table_id)
            raise AwsTransitGatewayError(msg) from exc
        if 'TransitGatewayRouteTable' not in response.keys():
            msg = 'TransitGatewayRouteTable not found in response: {r}'.format(r=str(response))
            raise AwsTransitGatewayError(msg)
        return response['TransitGatewayRouteTable']

    def associate_route_table_to_attachment(self, route_table_id, attachment_id):
        """Associates the route table ID with the transit gateway attachment

        :param route_table_id: (str) route table ID
        :param attachment_id: (str) attachment ID
        :return: (dict) transit route table association (see boto3 docs)
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.associate_route_table_to_attachment')
        if not self.wait_for_available():
            msg = 'Resources not available to create attachments'
            raise AwsTransitGatewayError(msg)
        for association in self.associations:
            if association['TransitGatewayRouteTableId'] == route_table_id and \
                    association['TransitGatewayAttachmentId'] == attachment_id:
                log.info('Route table {r} already associated to attachment: {a}'.format(
                    r=route_table_id, a=attachment_id))
                return association
        log.info('Associating route table {r} to attachment: {a}'.format(r=route_table_id, a=attachment_id))
        try:
            response = self.client.associate_transit_gateway_route_table(
                TransitGatewayRouteTableId=route_table_id,
                TransitGatewayAttachmentId=attachment_id,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem creating association between route table [{r}] and attachment: {a}'.format(
                r=route_table_id, a=attachment_id)
            raise AwsTransitGatewayError(msg) from exc
        if 'Association' not in response.keys():
            raise AwsTransitGatewayError('Association not found in response: {r}'.format(
                r=str(response)))
        self.associations.append(response['Association'])
        return response['Association']

    def disassociate_route_table_from_attachment(self, route_table_id, attachment_id):
        """Disassociate the route table from the specified attachment

        :param route_table_id: (str) ID of the route table
        :param attachment_id: (str) ID of the attachment
        :return: (dict) containing info about the deleted association
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.disassociate_route_table_from_attachment')
        log.info('Removing propagations in route table {r} to attachment: {a}'.format(
            r=route_table_id, a=attachment_id))
        for propagation in self.propagations:
            if propagation['TransitGatewayRouteTableId'] == route_table_id and \
               propagation['TransitGatewayAttachmentId'] == attachment_id:
                self.disable_propagation(
                    route_table_id=route_table_id,
                    attachment_id=attachment_id
                )
        self.wait_for_available()
        self.delete_routes(
            routes=self.get_routes_for_route_table(route_table_id=route_table_id, attachment_id=attachment_id)
        )
        log.info('Disassociating route table ID {r} from attachment: {a}'.format(r=route_table_id, a=attachment_id))
        try:
            response = self.client.disassociate_transit_gateway_route_table(
                TransitGatewayRouteTableId=route_table_id,
                TransitGatewayAttachmentId=attachment_id,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem disassociating route table {r} from attachment: {a}'.format(
                r=route_table_id, a=attachment_id)
            raise AwsTransitGatewayError(msg) from exc
        if 'Association' not in response.keys():
            msg = 'Association not found in response: {r}'.format(r=str(response))
            raise AwsTransitGatewayError(msg)
        return response['Association']

    def get_route_table_for_vpc(self, vpc_id):
        """For the provided VPC ID, return the route table if one exists

        :param vpc_id: (str) ID of the VPC
        :return: (str) ID of the route table or None
        """
        log = logging.getLogger(self.cls_logger + '.get_route_table_for_vpc')
        attachment_id = self.get_attachment_for_vpc(vpc_id=vpc_id)
        if not attachment_id:
            log.info('No attachment found for VPC: {v}'.format(v=vpc_id))
            return None
        for association in self.associations:
            if attachment_id == association['TransitGatewayAttachmentId']:
                return association['TransitGatewayRouteTableId']
        return None

    def enable_propagation(self, route_table_id, attachment_id):
        """Enables the route propagation for the provided route table ID and attachment ID

        :param route_table_id: (str) ID of the route table
        :param attachment_id: (str) ID of the attachment
        :return: (dict) info for the enabled propagation (see boto3 docs)
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.enable_propagation')
        log.info('Enabling route propagation from route table [{r}] to attachment: {a}'.format(
            r=route_table_id, a=attachment_id))
        try:
            response = self.client.enable_transit_gateway_route_table_propagation(
                TransitGatewayRouteTableId=route_table_id,
                TransitGatewayAttachmentId=attachment_id,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem enabling route propagation route route table (r) to attachment: {a}'.format(
                r=route_table_id, a=attachment_id)
            raise AwsTransitGatewayError(msg) from exc
        if 'Propagation' not in response.keys():
            msg = 'Propagation not found in response: {r}'.format(r=str(response))
            raise AwsTransitGatewayError(msg)
        return response['Propagation']

    def disable_propagation(self, route_table_id, attachment_id):
        """Disables the route propagation for the provided route table ID and attachment ID

        :param route_table_id: (str) ID of the route table
        :param attachment_id: (str) ID of the attachment
        :return: (dict) info for the disabled propagation (see boto3 docs)
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.disable_propagation')
        log.info('Disabling propagation to attachment {a} in route table: {r}'.format(
            r=route_table_id, a=attachment_id))
        try:
            response = self.client.disable_transit_gateway_route_table_propagation(
                TransitGatewayRouteTableId=route_table_id,
                TransitGatewayAttachmentId=attachment_id,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem disabling route propagation route route table (r) to attachment: {a}'.format(
                r=route_table_id, a=attachment_id)
            raise AwsTransitGatewayError(msg) from exc
        if 'Propagation' not in response.keys():
            msg = 'Propagation not found in response: {r}'.format(r=str(response))
            raise AwsTransitGatewayError(msg)
        return response['Propagation']

    def create_transit_gateway_route(self, cidr, route_table_id, attachment_id, black_hole=False):
        """Creates a route in the specified route table ID

        :param cidr: (str) destination CIDR block
        :param route_table_id: (str) ID of the route table
        :param attachment_id: (str) ID of the target attachment
        :param black_hole: (bool) True to black hole traffic, False otherwise
        :return: (dict) Route (see boto3 docs)
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.create_transit_gateway_route')
        log.info('Creating route in route table [{r}] with CIDR [{c}] to attachment [{a}] with black hole {b}'.format(
            r=route_table_id, a=attachment_id, b=str(black_hole), c=cidr))
        try:
            response = self.client.create_transit_gateway_route(
                DestinationCidrBlock=cidr,
                TransitGatewayRouteTableId=route_table_id,
                TransitGatewayAttachmentId=attachment_id,
                Blackhole=black_hole,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem creating route in route table [{r}] with CIDR [{c}] to attachment [{a}] with black hole ' \
                  '{b}'.format(r=route_table_id, a=attachment_id, b=str(black_hole), c=cidr)
            raise AwsTransitGatewayError(msg) from exc
        if 'Route' not in response.keys():
            msg = 'Route not found in response: {r}'.format(r=str(response))
            raise AwsTransitGatewayError(msg)
        return response['Route']

    def delete_transit_gateway_route(self, route_table_id, cidr):
        """Deletes the specified transit gateway route

        :param cidr: (str) destination CIDR block
        :param route_table_id: (str) ID of the route table
        :return:
        """
        log = logging.getLogger(self.cls_logger + '.delete_transit_gateway_route')
        log.info('Deleting route in route table [{r}] with CIDR [{c}]'.format(r=route_table_id, c=cidr))
        try:
            response = self.client.delete_transit_gateway_route(
                DestinationCidrBlock=cidr,
                TransitGatewayRouteTableId=route_table_id,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem deleting route in route table [{r}] with CIDR [{c}]'.format(r=route_table_id, c=cidr)
            raise AwsTransitGatewayError(msg) from exc
        if 'Route' not in response.keys():
            msg = 'Route not found in response: {r}'.format(r=str(response))
            raise AwsTransitGatewayError(msg)
        return response['Route']

    def get_routes_for_route_table(self, route_table_id, attachment_id=None, vpc_id=None):
        """Retrieves the routes for the route table ID

        :param route_table_id: (str) ID of the route table
        :param attachment_id: (str) ID of the attachment to filter on
        :param vpc_id: (str) ID of a VPC to filter on
        :return: (list) of TransitGatewayRoute objects
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.get_routes_for_route_table')
        filters = []
        if attachment_id:
            filters.append({'Name': 'attachment.transit-gateway-attachment-id', 'Values': [attachment_id]})
        if vpc_id:
            filters.append({'Name': 'attachment.resource-id', 'Values': [vpc_id]})
        log.info('Searching for routes in table [{r}] with filters: {f}'.format(r=route_table_id, f=str(filters)))
        try:
            response = self.client.search_transit_gateway_routes(
                TransitGatewayRouteTableId=route_table_id,
                Filters=filters,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem searching routes in route table: {r}'.format(r=route_table_id)
            raise AwsTransitGatewayError(msg) from exc
        if 'Routes' not in response.keys():
            msg = 'Routes not found in response: {r}'.format(r=str(response))
            raise AwsTransitGatewayError(msg)
        if 'AdditionalRoutesAvailable' in response.keys():
            if response['AdditionalRoutesAvailable']:
                log.warning('Additional routes are available but not provided in response')
        parsed_routes = parse_transit_gateway_routes(
            route_table_id=route_table_id,
            transit_gateway_routes=response['Routes']
        )
        for parsed_route in parsed_routes:
            log.info('Found route: {r}'.format(r=str(parsed_route)))
        return parsed_routes

    def delete_route(self, route):
        """Deletes the specified route from the route table

        :param route: (TransitGatewayRoute)
        :return: None
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.delete_route')
        if route.route_type:
            if route.route_type == 'propagated':
                log.info('Route type is propagated, will not be deleted, propagation must be disabled instead: '
                         '{r}'.format(r=str(route)))
                return
        if route.state:
            if route.state in ['deleting', 'deleted']:
                log.info('Route is already deleted or deleting: {r}'.format(r=str(route)))
                return
        self.delete_transit_gateway_route(route_table_id=route.route_table_id, cidr=route.cidr)

    def delete_routes(self, routes):
        """Deletes the list of routes

        :param routes: (list) of TransitGatewayRoute objects
        :return: None
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.delete_routes')
        log.info('Attempting to delete {n} routes'.format(n=str(len(routes))))
        for route in routes:
            self.delete_route(route=route)

    def add_route(self, route):
        """Adds the route

        :param route: (TransitGatewayRoute)
        :return: None
        :raises: AwsTransitGatewayError
        """
        self.create_transit_gateway_route(
            cidr=route.cidr,
            route_table_id=route.route_table_id,
            attachment_id=route.attachment_id,
            black_hole=route.black_hole
        )

    def add_routes(self, routes):
        """Adds the list of routes

        :param routes: (list) of TransitGatewayRoute objects
        :return: none
        :raises: AwsTransitGatewayError
        """
        for route in routes:
            self.add_route(route=route)

    def configure_routes(self, route_table_id, desired_routes):
        """Configure routes for the route table, deletes

        :param route_table_id: (str) ID of the route table
        :param desired_routes: (list) of TransitGatewayRoute objects
        :return: None
        :raise: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.configure_routes')
        existing_routes = self.get_routes_for_route_table(route_table_id=route_table_id)

        log.info('Existing routes:')
        for existing_route in existing_routes:
            log.info('Existing route: {r}'.format(r=str(existing_route)))
        log.info('Desired routes:')
        for desired_route in desired_routes:
            log.info('Desired route: {r}'.format(r=str(desired_route)))

        # Determine which routes to delete
        delete_routes = []
        for existing_route in existing_routes:
            delete = True
            for desired_route in desired_routes:
                if existing_route == desired_route:
                    delete = False
            if delete:
                delete_routes.append(existing_route)

        # Determine which routes to add
        add_routes = []
        for desired_route in desired_routes:
            if desired_route.route_table_id != route_table_id:
                continue
            add = True
            for existing_route in existing_routes:
                if desired_route == existing_route:
                    add = False
            if add:
                add_routes.append(desired_route)

        # Delete routes
        self.delete_routes(routes=delete_routes)

        # Add rules
        self.add_routes(routes=add_routes)
        log.info('Completed configuring rules for route table: {r}'.format(r=route_table_id))

    def remove_vpc(self, vpc_id):
        """Removed the specified VPC ID from the transit gateway

        :param vpc_id: (str) ID of the VPC
        :return: None
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.remove_vpc')
        log.info('Attempting to remove VPC ID {v} from transit gateway: {i}'.format(v=vpc_id, i=self.id))
        self.update_state()
        self.delete_vpc_attachment(vpc_id=vpc_id)

    def attachments_available(self):
        """Returns true when all the attachments have the available state

        :return: (bool) True when all the attachments have the available state, False otherwise
        """
        log = logging.getLogger(self.cls_logger + '.attachments_available')
        for attached_vpc in self.vpc_attachments:
            if attached_vpc['State'] not in ['available', 'deleted']:
                log.info('VPC attachment ID [{a}] in state: {s}'.format(
                    a=attached_vpc['TransitGatewayAttachmentId'], s=attached_vpc['State']))
                return False
        return True

    def route_tables_available(self):
        """Returns true when all the route tables have the available state

        :return: (bool) True when all the route tables have the available state, False otherwise
        """
        log = logging.getLogger(self.cls_logger + '.route_tables_available')
        for route_table in self.route_tables:
            if route_table['State'] not in ['available', 'deleted']:
                log.info('Route table [{r}] in state: {s}'.format(
                    r=route_table['TransitGatewayRouteTableId'], s=route_table['State']))
                return False
        return True

    def associations_available(self):
        """Returns true when all the associations have the associated state

        :return: (bool) True when all the associations have the associated state, False otherwise
        """
        log = logging.getLogger(self.cls_logger + '.associations_available')
        for association in self.associations:
            if association['State'] not in ['associated', 'disassociated']:
                log.info('Route table [{r}] association to attachment ID [{a}] in state: {s}'.format(
                    r=association['TransitGatewayRouteTableId'], a=association['TransitGatewayAttachmentId'],
                    s=association['State']))
                return False
        return True

    def propagations_available(self):
        """Returns true when all the propagations have the enabled state

        :return: (bool) True when all the propagations have the enabled state, False otherwise
        """
        log = logging.getLogger(self.cls_logger + '.propagations_available')
        for propagation in self.propagations:
            if propagation['State'] not in ['enabled', 'disabled']:
                log.info('Route table [{r}] propagation to attachment ID [{a}] in state: {s}'.format(
                    r=propagation['TransitGatewayRouteTableId'], a=propagation['TransitGatewayAttachmentId'],
                    s=propagation['State']))
                return False
        return True

    def available(self):
        """Returns True when all resources are available, False otherwise

        :return: (bool)
        """
        if self.state != 'available':
            return False
        if not self.attachments_available():
            return False
        if not self.route_tables_available():
            return False
        if not self.associations_available():
            return False
        if not self.propagations_available():
            return False
        return True

    def wait_for_available(self):
        """Waits a max time for resources to become available before proceeding

        :return: (bool) True if everything is available, False if max time is reached before availability
        """
        max_wait_time_sec = 1200
        start_time = time.time()
        while not self.available():
            if round((time.time() - start_time)) > max_wait_time_sec:
                return False
            time.sleep(5)
            self.update_state()
        return True


class TransitGatewayRoute(object):

    def __init__(self, route_table_id, cidr, attachment_id, resource_type=None, resource_id=None, route_type=None,
                 state=None):
        self.route_table_id = route_table_id
        self.cidr = cidr
        self.attachment_id = attachment_id
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.route_type = route_type
        self.state = state

    def __str__(self):
        out_str = 'Route Table {r}: CIDR [{c}], Attachment ID [{a}]'.format(
            r=self.route_table_id, c=self.cidr, a=self.attachment_id)
        if self.resource_type:
            out_str += ', Type [{t}]'.format(t=self.resource_type)
        if self.resource_id:
            out_str += ', ID: {i}'.format(i=self.resource_id)
        if self.route_type:
            out_str += ', Type: {t}'.format(t=self.route_type)
        if self.state:
            out_str += ', State: {s}'.format(s=self.state)
        return out_str

    def __eq__(self, other):
        if self.route_table_id and other.route_table_id:
            if self.route_table_id == other.route_table_id:
                if self.cidr == other.cidr:
                    if self.attachment_id == other.attachment_id:
                        return True
        return False

    def get_json(self):
        json_output = {
            'DestinationCidrBlock': self.cidr
        }
        if self.route_type:
            json_output['Type'] = self.route_type
        if self.state:
            json_output['State'] = self.state
        attachment = {
            'TransitGatewayAttachmentId': self.attachment_id
        }
        if self.resource_type:
            attachment['ResourceType'] = self.resource_type
        if self.resource_id:
            attachment['ResourceId'] = self.resource_id
        json_output['TransitGatewayAttachments'] = [attachment]
        return json_output


############################################################################
# Method for getting an EC2 client
############################################################################


def get_ec2_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
    """Gets an EC2 client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    return get_boto3_client(service='ec2', region_name=region_name, aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)


def parse_ip_permissions(ip_permissions):
    """Parse a list of IpPermissions or IpPermissionsEgress as defined in the boto3 documentation and returns
    a list of IpPermissions objects

    """
    log = logging.getLogger(mod_logger + '.parse_ip_permissions')
    if not isinstance(ip_permissions, list):
        log.warning('list expected, found: {t}'.format(t=ip_permissions.__class__.__name__))
        return []
    permissions_list = []
    for ip_permission in ip_permissions:
        if not isinstance(ip_permission, dict):
            log.warning('Dict expected, found type {t} for permission: {p}'.format(
                t=ip_permission.__class__.__name__, p=str(ip_permission)))
            return []
        if 'IpProtocol' not in ip_permission:
            log.warning('IpProtocol not found in IP permission: {p}'.format(p=ip_permission))
            continue
        from_port = None
        to_port = None
        if 'FromPort' in ip_permission:
            from_port = ip_permission['FromPort']
        if 'ToPort' in ip_permission:
            to_port = ip_permission['ToPort']
        if 'IpRanges' in ip_permission:
            for ip_v4_rule in ip_permission['IpRanges']:
                rule_description = None
                if 'Description' in ip_v4_rule:
                    rule_description = ip_v4_rule['Description']
                permissions_list.append(
                    IpPermission(
                        IpProtocol=ip_permission['IpProtocol'],
                        CidrIp=ip_v4_rule['CidrIp'],
                        Description=rule_description,
                        FromPort=from_port,
                        ToPort=to_port
                    )
                )
        if 'Ipv6Ranges' in ip_permission:
            for ip_v6_rule in ip_permission['Ipv6Ranges']:
                rule_description = None
                if 'Description' in ip_v6_rule:
                    rule_description = ip_v6_rule['Description']
                permissions_list.append(
                    IpPermission(
                        IpProtocol=ip_permission['IpProtocol'],
                        CidrIpv6=ip_v6_rule['CidrIpv6'],
                        Description=rule_description,
                        FromPort=from_port,
                        ToPort=to_port
                    )
                )
        if 'PrefixListIds' in ip_permission:
            for prefix_id_rule in ip_permission['PrefixListIds']:
                rule_description = None
                if 'Description' in prefix_id_rule:
                    rule_description = prefix_id_rule['Description']
                permissions_list.append(
                    IpPermission(
                        IpProtocol=ip_permission['IpProtocol'],
                        PrefixListId=prefix_id_rule['PrefixListId'],
                        Description=rule_description,
                        FromPort=from_port,
                        ToPort=to_port
                    )
                )
    return permissions_list


def get_aws_service_permissions(regions, ipv6=False):
    """Returns a list of IpPermissions objects for a list of regions

    :param regions: (list) of (str) regions to include in the permissions set (e.g. ['us-gov-west-1', 'us-gov-east-1'])
                    use the region 'GLOBAL' to include global non-region-specific ranges
    :param ipv6: (bool) Set True to include only IPv6 results, False for IPv4
    :return: (list) of IpPermissions objects
    """
    log = logging.getLogger(mod_logger + '.get_aws_service_permissions')
    if not isinstance(regions, list):
        log.warning('list expected, found: {t}'.format(t=regions.__class__.__name__))
        return []
    permissions_list = []
    ip_ranges = get_aws_service_ips(regions=regions, include_elastic_ips=False, ipv6=ipv6)
    for ip_range in ip_ranges:
        if ipv6:
            permissions_list.append(
                IpPermission(IpProtocol='-1', CidrIpv6=ip_range, Description='AWS_Service_Range')
            )
        else:
            permissions_list.append(
                IpPermission(IpProtocol='-1', CidrIp=ip_range, Description='AWS_Service_Range')
            )
    permissions_list.append(
        IpPermission(IpProtocol='-1', CidrIp='169.254.169.254/32', Description='AWS_MetaData_Service')
    )
    return permissions_list


def get_rhui_server_permissions_all_versions(regions):
    return get_rhui1_server_permissions(regions=regions) + \
           get_rhui2_server_permissions(regions=regions) + \
           get_rhui3_server_permissions(regions=regions)


def get_rhui1_server_permissions(regions):
    """Returns a list of IpPermissions objects for a list of regions

    :param regions: (list) of (str) regions to include in the permissions set (e.g. ['us-gov-west-1', 'us-gov-east-1'])
    :return: (list) of IpPermissions objects
    """
    log = logging.getLogger(mod_logger + '.get_rhui1_server_permissions')
    if not isinstance(regions, list):
        log.warning('list expected, found: {t}'.format(t=regions.__class__.__name__))
        return []
    permissions_list = []
    rhui1_server_ips = get_aws_rhui1_ips(regions=regions)
    for rhui1_server_ip in rhui1_server_ips:
        permissions_list.append(
            IpPermission(IpProtocol='tcp', FromPort=443, ToPort=443, CidrIp=rhui1_server_ip + '/32',
                         Description='RedHat_RHUI1_Server')
        )
    return permissions_list


def get_rhui2_server_permissions(regions):
    """Returns a list of IpPermissions objects for a list of regions

    :param regions: (list) of (str) regions to include in the permissions set (e.g. ['us-gov-west-1', 'us-gov-east-1'])
    :return: (list) of IpPermissions objects
    """
    log = logging.getLogger(mod_logger + '.get_rhui2_server_permissions')
    if not isinstance(regions, list):
        log.warning('list expected, found: {t}'.format(t=regions.__class__.__name__))
        return []
    permissions_list = []
    rhui2_server_ips = get_aws_rhui2_ips(regions=regions)
    for rhui2_server_ip in rhui2_server_ips:
        permissions_list.append(
            IpPermission(IpProtocol='tcp', FromPort=443, ToPort=443, CidrIp=rhui2_server_ip + '/32',
                         Description='RedHat_RHUI2_Server')
        )
    return permissions_list


def get_rhui3_server_permissions(regions):
    """Returns a list of IpPermissions objects for a list of regions

    :param regions: (list) of (str) regions to include in the permissions set (e.g. ['us-gov-west-1', 'us-gov-east-1'])
    :return: (list) of IpPermissions objects
    """
    log = logging.getLogger(mod_logger + '.get_rhui3_server_permissions')
    if not isinstance(regions, list):
        log.warning('list expected, found: {t}'.format(t=regions.__class__.__name__))
        return []
    permissions_list = []
    rhui3_server_ips = get_aws_rhui3_ips(regions=regions)
    for rhui3_server_ip in rhui3_server_ips:
        permissions_list.append(
            IpPermission(IpProtocol='tcp', FromPort=443, ToPort=443, CidrIp=rhui3_server_ip + '/32',
                         Description='RedHat_RHUI3_Server')
        )
    return permissions_list


def get_permissions_for_hostnames(hostname_list, protocol='-1', from_port=None, to_port=None):
    """Get a list of IP permissions from the provided list of hostnames

    :param hostname_list: (str) list of hostnames
    :param protocol: (str) Set to the desired protocol, -1 for any, tcp, udp
    :param from_port: (int) Port number to start the port range
    :param to_port: (int) Port number to end the port range
    :return: (list) IPPermission objects
    """
    log = logging.getLogger(mod_logger + '.get_permissions_for_hostnames')
    log.info('Getting IP addresses for hostname list...')
    hostnames_and_ip_addresses, failed_hostnames = get_ip_list_for_hostname_list(hostname_list=hostname_list)
    permissions_list = []
    for hostname_ip_addresses in hostnames_and_ip_addresses:
        if 'hostname' not in hostname_ip_addresses.keys():
            continue
        if 'ip_addresses' not in hostname_ip_addresses.keys():
            continue
        hostname = hostname_ip_addresses['hostname']
        ip_addresses = hostname_ip_addresses['ip_addresses']
        for ip_address in ip_addresses:
            if from_port and to_port:
                permissions_list.append(
                    IpPermission(IpProtocol=protocol, FromPort=from_port, ToPort=to_port, CidrIp=ip_address + '/32',
                                 Description=hostname)
                )
            else:
                permissions_list.append(
                    IpPermission(IpProtocol=protocol, CidrIp=ip_address + '/32', Description=hostname)
                )
    return permissions_list


def merge_permissions_by_description(primary_permission_list, merge_permission_list):
    """Merges the "merge" permission list into the "primary" permission list, by keeping permissions with matching
    descriptions.  This allows an existing list of permissions to persist and append into the new list

    :param primary_permission_list: (list) IPPermission objects
    :param merge_permission_list: (list) IPPermission objects
    :return: (list) IPPermission objects
    """
    merged_permission_list = []

    # Loop on the primary permission list
    for primary_permission in primary_permission_list:
        # Add all the primary permissions to the list
        if primary_permission not in merged_permission_list:
            merged_permission_list.append(primary_permission)

        # Skip merging if the description is blank
        if not primary_permission.Description:
            continue
        elif primary_permission.Description == '':
            continue

        # Loop through the merge list once for every primary
        for merge_permission in merge_permission_list:
            # Skip blank merged permissions
            if not merge_permission.Description:
                continue
            elif merge_permission.Description == '':
                continue
            if merge_permission not in merged_permission_list:
                # If the merge permission description matches, the primary, add it to the list
                if merge_permission.Description == primary_permission.Description:
                    merged_permission_list.append(merge_permission)
    return merged_permission_list


def parse_ip_routes(ip_routes):
    """Parse a list of Routes as defined in the boto3 documentation and returns
    a list of IpRoutes objects

    """
    log = logging.getLogger(mod_logger + '.parse_ip_routes')
    if not isinstance(ip_routes, list):
        log.warning('list expected, found: {t}'.format(t=ip_routes.__class__.__name__))
        return []
    routes_list = []
    for ip_route in ip_routes:
        if not isinstance(ip_route, dict):
            log.warning('Dict expected, found type {t} for permission: {p}'.format(
                t=ip_route.__class__.__name__, p=str(ip_route)))
            return []
        cidr = None
        cidr_ipv6 = None
        target = None
        instance_owner_id = None
        state = None
        origin = None
        if 'DestinationCidrBlock' in ip_route.keys():
            cidr = ip_route['DestinationCidrBlock']
        if 'DestinationIpv6CidrBlock' in ip_route.keys():
            cidr_ipv6 = ip_route['DestinationIpv6CidrBlock']
        if 'EgressOnlyInternetGatewayId' in ip_route.keys():
            target = ip_route['EgressOnlyInternetGatewayId']
        elif 'GatewayId' in ip_route.keys():
            target = ip_route['GatewayId']
        elif 'InstanceId' in ip_route.keys():
            target = ip_route['InstanceId']
        elif 'NatGatewayId' in ip_route.keys():
            target = ip_route['NatGatewayId']
        elif 'TransitGatewayId' in ip_route.keys():
            target = ip_route['TransitGatewayId']
        elif 'LocalGatewayId' in ip_route.keys():
            target = ip_route['LocalGatewayId']
        elif 'NetworkInterfaceId' in ip_route.keys():
            target = ip_route['NetworkInterfaceId']
        elif 'VpcPeeringConnectionId' in ip_route.keys():
            target = ip_route['VpcPeeringConnectionId']
        if 'InstanceOwnerId' in ip_route.keys():
            instance_owner_id = ip_route['InstanceOwnerId']
        if 'State' in ip_route.keys():
            state = ip_route['State']
        if 'Origin' in ip_route.keys():
            origin = ip_route['Origin']
        try:
            routes_list.append(
                IpRoute(
                    cidr=cidr,
                    cidr_ipv6=cidr_ipv6,
                    target=target,
                    instance_owner_id=instance_owner_id,
                    state=state,
                    origin=origin
                )
            )
        except AttributeError as exc:
            log.warning('Problem creating IpRoute object from data: {d}\n{e}\n{t}'.format(
                d=str(ip_route), e=str(exc), t=traceback.format_exc()))
    return routes_list


def parse_transit_gateway_routes(route_table_id, transit_gateway_routes):
    """Parse a list of Transit gateway Routes as defined in the boto3 documentation and returns
    a list of TransitGatewayRoute objects

    """
    log = logging.getLogger(mod_logger + '.parse_transit_gateway_routes')
    if not isinstance(transit_gateway_routes, list):
        log.warning('list expected, found: {t}'.format(t=transit_gateway_routes.__class__.__name__))
        return []
    transit_routes_list = []
    for transit_gateway_route in transit_gateway_routes:
        if not isinstance(transit_gateway_route, dict):
            log.warning('Dict expected, found type {t} for permission: {p}'.format(
                t=transit_gateway_route.__class__.__name__, p=str(transit_gateway_route)))
            return []
        cidr = None
        resource_type = None
        resource_id = None
        route_type = None
        state = None
        if 'DestinationCidrBlock' in transit_gateway_route.keys():
            cidr = transit_gateway_route['DestinationCidrBlock']
        if 'Type' in transit_gateway_route.keys():
            route_type = transit_gateway_route['Type']
        if 'State' in transit_gateway_route.keys():
            state = transit_gateway_route['State']
        if 'TransitGatewayAttachments' in transit_gateway_route.keys():
            for attachment in transit_gateway_route['TransitGatewayAttachments']:
                if 'TransitGatewayAttachmentId' not in attachment.keys():
                    continue
                attachment_id = attachment['TransitGatewayAttachmentId']
                if 'ResourceType' in attachment.keys():
                    resource_type = attachment['ResourceType']
                if 'ResourceId' in attachment.keys():
                    resource_id = attachment['ResourceId']
                transit_routes_list.append(
                    TransitGatewayRoute(
                        cidr=cidr,
                        route_table_id=route_table_id,
                        attachment_id=attachment_id,
                        resource_type=resource_type,
                        resource_id=resource_id,
                        route_type=route_type,
                        state=state
                    )
                )
    return transit_routes_list


############################################################################
# Method for retrieving AWS Service IP addresses
############################################################################


def get_aws_service_ips(regions=None, ipv6=False, include_amazon_service=True, include_elastic_ips=False,
                        service_list=None):
    """Returns a list of AWS service IP addresses

    Ref: https://docs.aws.amazon.com/general/latest/gr/aws-ip-ranges.html#aws-ip-egress-control

    :param regions: (list) region IDs to include in the results (e.g. [us-gov-west-1, us-gov-east-1])
                           use the region 'GLOBAL' to include global non-region-specific ranges
    :param ipv6: (bool) Set True to return only IPv6 results, False for IPv4 only
    :param include_amazon_service: (bool) Set True to include the AMAZON IPs, used to connect to APIs
    :param include_elastic_ips: (bool) Set True to include attachable EC2 elastic IPs in the results
    :param service_list: (list) of String service names: ['AMAZON', 'CHIME_VOICECONNECTOR', 'ROUTE53_HEALTHCHECKS',
            'S3', 'IVS_REALTIME', 'WORKSPACES_GATEWAYS', 'EC2', 'ROUTE53', 'CLOUDFRONT', 'GLOBALACCELERATOR',
            'AMAZON_CONNECT', 'ROUTE53_HEALTHCHECKS_PUBLISHING', 'CHIME_MEETINGS', 'CLOUDFRONT_ORIGIN_FACING',
            'CLOUD9', 'CODEBUILD', 'API_GATEWAY', 'ROUTE53_RESOLVER', 'EBS', 'EC2_INSTANCE_CONNECT',
            'KINESIS_VIDEO_STREAMS', 'AMAZON_APPFLOW', 'MEDIA_PACKAGE_V2', 'DYNAMODB']
    :return: (list) of IP addresses
    """
    log = logging.getLogger(mod_logger + '.get_aws_service_ips')

    # Gets the list of CIDR ranges matching the desired service list and "include" settings
    filtered_unique_amazon_cidr_ranges = []
    amazon_cidr_ranges = []

    # Validate the service list if provided
    if service_list:
        for service in service_list:
            if service not in amazon_service_names:
                log.error('Invalid service name provided: [{n}]'.format(n=service))
                return filtered_unique_amazon_cidr_ranges

    # Determine the prefix ID
    if ipv6:
        prefix_id = 'ipv6_prefixes'
    else:
        prefix_id = 'prefixes'

    # Get the full list from Amazon
    try:
        ip_ranges = requests.get('https://ip-ranges.amazonaws.com/ip-ranges.json').json()[prefix_id]
    except Exception as exc:
        log.error('Problem retrieving the list of IP ranges from AWS{e}\n'.format(e=str(exc)))
        return filtered_unique_amazon_cidr_ranges

    # Set the prfix key based on IPv4 or IPv6
    if ipv6:
        prefix_key = 'ipv6_prefix'
        log.info('Returning IPv6 results only')
    else:
        prefix_key = 'ip_prefix'
        log.info('Returning IPv4 results only')

    # Resolve include_elastic_ips if service list includes "EC2"
    if service_list:
        if 'EC2' in service_list:
            include_elastic_ips = True

    # Collect IPs based on whether to include the AMAZON IPs or use the service list
    for ip_range in ip_ranges:
        if prefix_key not in ip_range.keys():
            continue
        if regions:
            if ip_range['region'] not in regions:
                continue
        if ip_range['service'] == 'EC2':
            if include_elastic_ips:
                amazon_cidr_ranges.append(ip_range[prefix_key])
                continue
        elif ip_range['service'] == 'AMAZON':
            if include_amazon_service:
                amazon_cidr_ranges.append(ip_range[prefix_key])
                continue
        elif service_list:
            for service in service_list:
                if ip_range['service'] == service:
                    amazon_cidr_ranges.append(ip_range[prefix_key])

    # Ensure the list in unique
    unique_amazon_cidr_ranges = list(set(amazon_cidr_ranges))

    log.info('Found [{n}] unique CIDR blocks'.format(n=str(len(unique_amazon_cidr_ranges))))

    # Exclude EC2 elastic IPs if specified
    if not include_elastic_ips:
        ec2_cidr_ranges = [item[prefix_key] for item in ip_ranges if item['service'] == 'EC2']
        log.info('Excluding [{n}] EC2 elastic IP CIDR blocks'.format(n=str(len(ec2_cidr_ranges))))
        for amazon_cidr in unique_amazon_cidr_ranges:
            if amazon_cidr not in ec2_cidr_ranges:
                log.debug('Including non-EC2 CIDR: [{c}]'.format(c=amazon_cidr))
                filtered_unique_amazon_cidr_ranges.append(amazon_cidr)
            else:
                log.debug('Excluding EC2 CIDR: [{c}]'.format(c=amazon_cidr))
    else:
        log.info('Not excluding EC2 elastic IP CIDR blocks')
        filtered_unique_amazon_cidr_ranges = list(unique_amazon_cidr_ranges)
    log.info('Found [{n}] filtered unique CIDR blocks'.format(n=str(len(filtered_unique_amazon_cidr_ranges))))
    return filtered_unique_amazon_cidr_ranges


############################################################################
# Method for retrieving AWS Red Hat Update Server RHUI IP addresses
############################################################################

def get_aws_rhui_ips(regions=None, version=1):
    """Returns the list of Red Hat RHUI3 IP addresses

    Note: GovCloud uses the US-based servers

    :param regions: (list) region IDs to include in the results (e.g. [us-gov-west-1, us-gov-east-1])
    :param version: (int) version number of the RHUI (e.g., 1, 2, or 3)
    :return: (list) of IP addresses
    """
    log = logging.getLogger(mod_logger + '.get_aws_rhui_ips')

    # Versions of RHUI supported
    supported_rhui_versions = [1, 2, 3]

    # Store the collected list of RHUI IPs
    rhui_ips = []

    # Set the list of subdomains based on prefix
    if version == 1:
        subdomains = ['rhui']
    elif version == 2:
        subdomains = ['rhui2-cds01', 'rhui2-cds02']
    elif version == 3:
        subdomains = ['rhui3']
    else:
        log.error('Unsupported RHUI version found [{v}] expected: {s}'.format(
            v=str(version), s=','.join(map(str, supported_rhui_versions))))
        return rhui_ips

    # Get a list of AWS regions to query
    # If using a gov region, all the US-based commercial servers are included in the list
    if not regions:
        regions = global_regions
    else:
        for region in regions:
            if region in gov_regions:
                log.info('GovCloud region specified, returning only US-based RHUI servers...')
                regions = us_regions
                break

    log.info('Returning RHUI IP addresses in regions: {r}'.format(r=','.join(regions)))

    # Build the list of IPs for each region and RHUI subdomain
    for region in regions:
        for subdomain in subdomains:
            rhui_server = '{s}.{r}.aws.ce.redhat.com'.format(s=subdomain, r=region)
            log.info('Looking for the IP address for RHUI server: {s}'.format(s=rhui_server))
            try:
                _, _, rhui_region_ips = socket.gethostbyname_ex(rhui_server)
            except (socket.gaierror, socket.error, socket.herror) as exc:
                log.error('Problem retrieving RHUI IP address for region: {r}\n{e}'.format(r=region, e=str(exc)))
                continue
            if len(rhui_region_ips) < 1:
                log.error('No RHUI IP addresses returned for server: {s}'.format(s=rhui_server))
                continue
            for rhui_region_ip in rhui_region_ips:
                if validate_ip_address(rhui_region_ip):
                    log.info('Found RHUI IP address for server {s}: {i}'.format(s=rhui_server, i=rhui_region_ip))
                    rhui_ips.append(rhui_region_ip)
                else:
                    log.error('Invalid RHUI IP address returned for server [{s}]: {i}'.format(
                        s=rhui_server, i=rhui_region_ip))
    return rhui_ips


def get_aws_rhui1_ips(regions=None):
    return get_aws_rhui_ips(regions=regions, version=1)


def get_aws_rhui2_ips(regions=None):
    return get_aws_rhui_ips(regions=regions, version=2)


def get_aws_rhui3_ips(regions=None):
    return get_aws_rhui_ips(regions=regions, version=3)


def get_aws_rhui_ips_all_versions(regions=None):
    return get_aws_rhui1_ips(regions=regions) + get_aws_rhui2_ips(regions=regions) + get_aws_rhui3_ips(regions=regions)


############################################################################
# Methods for retrieving EC2 Instances
############################################################################


def list_instances_with_token(client, max_results=100, continuation_token=None):
    """Returns a list of instances using the provided token and owner ID

    :param client: boto3.client object
    :param max_results: (int) max results to query on
    :param continuation_token: (str) token to query on
    :return: (dict) response object containing response data
    """
    if continuation_token:
        return client.describe_instances(
            DryRun=False,
            MaxResults=max_results,
            NextToken=continuation_token
        )
    else:
        return client.describe_instances(
            DryRun=False,
            MaxResults=max_results
        )


def list_instances(client):
    """Gets a list of EC2 instances in this account/region

    :param client: boto3.client object
    :return: (list)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.list_instances')
    log.info('Getting a list of EC2 instances...')
    instances = []
    continuation_token = None
    next_query = True
    max_results = 100
    while True:
        if not next_query:
            break
        try:
            response = list_instances_with_token(
                client=client,
                max_results=max_results,
                continuation_token=continuation_token
            )
        except ClientError as exc:
            msg = 'Problem querying for EC2 instances'
            raise EC2UtilError(msg) from exc
        if 'Reservations' not in response.keys():
            log.warning('Reservations not found in response: {r}'.format(r=str(response.keys())))
            return instances
        if 'NextToken' not in response.keys():
            next_query = False
        else:
            continuation_token = response['NextToken']
        for reservation in response['Reservations']:
            if 'Instances' not in reservation.keys():
                log.warning('Instances not found in reservation: {r}'.format(r=str(reservation)))
                continue
            instances += reservation['Instances']
    log.info('Found {n} EC2 instances'.format(n=str(len(instances))))
    return instances


def list_instance_names(client):
    """Gets a list of EC2 instances that have name tags, and returns the list of names

    :param client: boto3.client object
    :return: (list) of (str) "Name" tag values, if any
    """
    log = logging.getLogger(mod_logger + '.list_instance_names')
    instance_names = []
    instances = list_instances(client=client)
    log.info('Looking for instances with the Name tag set...')
    for instance in instances:
        if 'Tags' not in instance.keys():
            continue
        for tag in instance['Tags']:
            if tag['Key'] == 'Name':
                instance_names.append(tag['Value'])
                log.info('Found instance with Name tag: {v}'.format(v=tag['Value']))
    return instance_names


def get_instance(client, instance_id):
    """Returns detailed info about the instance ID

    :param client: boto3.client object
    :param instance_id: (str) ID of the instance to retrieve
    :return: (dict) data about the instance (see boto3 docs)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.get_instance')
    log.info('Getting info about instance ID: {i}'.format(i=instance_id))
    try:
        response = client.describe_instances(DryRun=False, InstanceIds=[instance_id])
    except ClientError as exc:
        msg = 'Unable to describe instance ID: {a}'.format(a=instance_id)
        raise EC2UtilError(msg) from exc
    if 'Reservations' not in response.keys():
        msg = 'Reservations not found in response: {r}'.format(r=str(response))
        raise EC2UtilError(msg)
    reservations = response['Reservations']
    if not isinstance(reservations, list):
        msg = 'Expected Reservations to be a list, found: {t}'.format(t=reservations.__class__.__name__)
        raise EC2UtilError(msg)
    instances = []
    for reservation in reservations:
        if 'Instances' not in reservation.keys():
            msg = 'Instances not found in reservation: {r}'.format(r=str(reservation))
            raise EC2UtilError(msg)
        if not isinstance(reservation['Instances'], list):
            msg = 'Expected Instances to be a list, found: {t}'.format(t=reservation['Instances'].__class__.__name__)
            raise EC2UtilError(msg)
        instances += reservation['Instances']
    if len(instances) != 1:
        msg = 'Expected to find 1 instance, found: {n}'.format(n=str(len(instances)))
        raise EC2UtilError(msg)
    return instances[0]


def stop_instance(client, instance_id):
    """Stops the provided instance ID

    :param client: boto3.client object
    :param instance_id: (str) ID of instance
    :return: (tuple) instance ID, current state, and previous state
    """
    log = logging.getLogger(mod_logger + '.stop_instance')
    try:
        response = client.stop_instances(
            InstanceIds=[instance_id],
            DryRun=False,
            Hibernate=False,
            Force=False
        )
    except ClientError as exc:
        msg = 'Problem stopping instance: {i}'.format(i=instance_id)
        raise EC2UtilError(msg) from exc
    if 'StoppingInstances' not in response.keys():
        msg = 'StoppingInstances data not found in response: {r}'.format(r=str(response))
        raise EC2UtilError(msg)
    for stopping_instance in response['StoppingInstances']:
        if 'InstanceId' not in stopping_instance or 'CurrentState' not in stopping_instance \
        or 'PreviousState' not in stopping_instance:
            msg = 'InstanceId, CurrentState, or PreviousState data not found in response: {r}'.format(
                r=str(stopping_instance))
            raise EC2UtilError(msg)
        if stopping_instance['InstanceId'] == instance_id:
            return stopping_instance['InstanceId'], stopping_instance['CurrentState']['Name'], \
                   stopping_instance['PreviousState']['Name']
    log.info('Stopped instance ID: {i}'.format(i=instance_id))
    return instance_id, 'UNKNOWN', 'UNKNOWN'


def terminate_instance(client, instance_id):
    """Terminates the provided instance ID

    :param client: boto3.client object
    :param instance_id: (str) ID of instance
    :return: (tuple) instance ID, current state, and previous state
    """
    log = logging.getLogger(mod_logger + '.terminate_instance')
    try:
        response = client.terminate_instances(
            InstanceIds=[instance_id],
            DryRun=False
        )
    except ClientError as exc:
        msg = 'Problem terminating instance: {i}'.format(i=instance_id)
        raise EC2UtilError(msg) from exc
    if 'TerminatingInstances' not in response.keys():
        msg = 'TerminatingInstances data not found in response: {r}'.format(r=str(response))
        raise EC2UtilError(msg)
    for terminating_instance in response['TerminatingInstances']:
        if 'InstanceId' not in terminating_instance or 'CurrentState' not in terminating_instance \
                or 'PreviousState' not in terminating_instance:
            msg = 'InstanceId, CurrentState, or PreviousState data not found in response: {r}'.format(
                r=str(terminating_instance))
            raise EC2UtilError(msg)
        if terminating_instance['InstanceId'] == instance_id:
            return terminating_instance['InstanceId'], terminating_instance['CurrentState']['Name'], \
                   terminating_instance['PreviousState']['Name']
    log.info('Stopped instance ID: {i}'.format(i=instance_id))
    return instance_id, 'UNKNOWN', 'UNKNOWN'


############################################################################
# Methods for EC2 EBS Snapshots
############################################################################


def delete_snapshot(client, snapshot_id):
    """Deletes an EBS snapshot by ID

    :param client: boto3.client object
    :param snapshot_id: (str) ID of the snapshot to delete
    :return: (str) deleted snapshot ID
    :raises: Ec2UtilError
    """
    log = logging.getLogger(mod_logger + '.delete_snapshot')
    try:
        client.delete_snapshot(
            SnapshotId=snapshot_id,
            DryRun=False
        )
    except ClientError as exc:
        msg = 'Problem deleting EBS snapshot: {i}'.format(i=snapshot_id)
        raise EC2UtilError(msg) from exc
    log.info('Deleted EBS snapshot ID: {i}'.format(i=snapshot_id))
    return snapshot_id


def list_snapshots_with_token(client, owner_id, max_results=100, continuation_token=None):
    """Returns a list of snapshots using the provided token and owner ID

    :param client: boto3.client object
    :param owner_id: (str) owner ID for the account
    :param max_results: (int) max results to query on
    :param continuation_token: (str) token to query on
    :return: (dict) response object containing response data
    """
    if continuation_token:
        return client.describe_snapshots(
            DryRun=False,
            MaxResults=max_results,
            NextToken=continuation_token,
            OwnerIds=[owner_id]
        )
    else:
        return client.describe_snapshots(
            DryRun=False,
            MaxResults=max_results,
            OwnerIds=[owner_id]
        )


def list_snapshots(client, owner_id):
    """Gets a list of EC2 snapshots in this account/region

    :param client: boto3.client object
    :param owner_id: (str) ID of the account to search
    :return: (list)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.list_snapshots')
    log.info('Getting a list of EC2 snapshots in account ID: {i}'.format(i=owner_id))
    snapshots = []
    continuation_token = None
    next_query = True
    max_results = 100
    while True:
        if not next_query:
            break
        try:
            response = list_snapshots_with_token(
                client=client,
                owner_id=owner_id,
                max_results=max_results,
                continuation_token=continuation_token
            )
        except ClientError as exc:
            msg = 'Problem querying for EC2 snapshots'
            raise EC2UtilError(msg) from exc
        if 'Snapshots' not in response.keys():
            log.warning('Snapshots not found in response: {r}'.format(r=str(response.keys())))
            return snapshots
        if 'NextToken' not in response.keys():
            next_query = False
        else:
            continuation_token = response['NextToken']
        snapshots += response['Snapshots']
    log.info('Found {n} EC2 snapshots'.format(n=str(len(snapshots))))
    return snapshots


def get_snapshot(client, snapshot_id):
    """Returns detailed info about the snapshot ID

    :param client: boto3.client object
    :param snapshot_id: (str) ID of the snapshot to retrieve
    :return: (dict) data about the snapshot (see boto3 docs)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.get_snapshot')
    log.info('Getting info about snapshot ID: {i}'.format(i=snapshot_id))
    try:
        response = client.describe_snapshots(DryRun=False, SnapshotIds=[snapshot_id])
    except ClientError as exc:
        msg = 'Unable to describe snapshot ID: {a}'.format(a=snapshot_id)
        raise EC2UtilError(msg) from exc
    if 'Snapshots' not in response.keys():
        msg = 'Snapshots not found in response: {r}'.format(r=str(response))
        raise EC2UtilError(msg)
    snapshots = response['Snapshots']
    if not isinstance(snapshots, list):
        msg = 'Expected Snapshots to be a list, found: {t}'.format(t=snapshots.__class__.__name__)
        raise EC2UtilError(msg)
    if len(snapshots) != 1:
        msg = 'Expected to find 1 snapshot, found: {n}'.format(n=str(len(snapshots)))
        raise EC2UtilError(msg)
    return snapshots[0]


############################################################################
# Methods for retrieving EC2 AMIs / Images
############################################################################

def create_image(client, instance_id, image_name, image_description='', no_reboot=False):
    """Creates an EC2 image from the provided instance ID

    :param client: boto3.client object
    :param instance_id: (str) ID of the instance
    :param image_name: (str) name of the image to create
    :param image_description: (str) description of the image
    :param no_reboot: (bool) Set True to prevent AWS from rebooting the image as part of the creation process
    :return: (str) Image ID
    :raises EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.create_image')
    # Create the new image
    log.info('Creating new image from instance ID: {i}'.format(i=instance_id))
    try:
        response = client.create_image(
            DryRun=False,
            InstanceId=instance_id,
            Name=image_name,
            Description=image_description,
            NoReboot=no_reboot
        )
    except ClientError as exc:
        msg = 'There was a problem creating an image named [{m}] for image ID: {i}'.format(
            m=image_name, i=instance_id)
        raise EC2UtilError(msg) from exc
    if 'ImageId' not in response.keys():
        msg = 'ImageId not found in response: {r}'.format(r=str(response.keys()))
        raise EC2UtilError(msg)
    image_id = response['ImageId']
    log.info('Created image ID [{a}] from instance ID [{i}]'.format(a=image_id, i=instance_id))
    return image_id


def list_images(client, owner_id):
    """Gets a list of EC2 images in this account/region

    :param client: boto3.client object
    :param owner_id: (str) ID of the account to search
    :return: (list)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.list_images')
    log.info('Getting a list of EC2 images/AMIs in account ID: {i}'.format(i=owner_id))
    try:
        response = client.describe_images(
            DryRun=False,
            Owners=[owner_id]
        )
    except ClientError as exc:
        msg = 'Problem querying for EC2 images'
        raise EC2UtilError(msg) from exc
    if 'Images' not in response.keys():
        msg = 'Images not found in response: {r}'.format(r=str(response.keys()))
        raise EC2UtilError(msg)
    images = response['Images']
    log.info('Found {n} EC2 images'.format(n=str(len(images))))
    return images


def get_image(client, ami_id):
    """Returns detailed info about the AMI ID

    :param client: boto3.client object
    :param ami_id: (str) ID of the AMI to retrieve
    :return: (dict) data about the AMI (see boto3 docs)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.get_image')
    log.info('Getting info about AMI ID: {i}'.format(i=ami_id))
    try:
        response = client.describe_images(DryRun=False, ImageIds=[ami_id])
    except ClientError as exc:
        msg = 'Unable to describe image ID: {a}'.format(a=ami_id)
        raise EC2UtilError(msg) from exc
    if 'Images' not in response.keys():
        msg = 'Images not found in response: {r}'.format(r=str(response))
        raise EC2UtilError(msg)
    if len(response['Images']) != 1:
        msg = 'Expected to find 1 image, found {n} in response: {r}'.format(
            n=str(len(response['Images'])), r=str(response))
        raise EC2UtilError(msg)
    return response['Images'][0]


############################################################################
# Methods for EC2 EBS Volumes
############################################################################

def delete_volume(client, volume_id):
    """Deletes an EBS volume by ID

    :param client: boto3.client object
    :param volume_id: (str) ID of the volume to delete
    :return: (str) deleted volume ID
    :raises: Ec2UtilError
    """
    log = logging.getLogger(mod_logger + '.delete_volume')
    try:
        client.delete_volume(
            VolumeId=volume_id,
            DryRun=False
        )
    except ClientError as exc:
        msg = 'Problem deleing EBS volume: {i}'.format(i=volume_id)
        raise EC2UtilError(msg) from exc
    log.info('Deleted EBS volume ID: {i}'.format(i=volume_id))
    return volume_id


def list_volumes_with_token(client, max_results=100, continuation_token=None):
    """Returns a list of volumes using the provided token

    :param client: boto3.client object
    :param max_results: (int) max results to query on
    :param continuation_token: (str) token to query on
    :return: (dict) response object containing response data
    """
    if continuation_token:
        return client.describe_volumes(
            DryRun=False,
            MaxResults=max_results,
            NextToken=continuation_token
        )
    else:
        return client.describe_volumes(
            DryRun=False,
            MaxResults=max_results
        )


def list_volumes(client):
    """Gets a list of EBS volumes in this account/region

    :param client: boto3.client object
    :return: (list) of volumes
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.list_volumes')
    log.info('Getting a list of EBS volumes...')
    volumes = []
    continuation_token = None
    next_query = True
    max_results = 100
    while True:
        if not next_query:
            break
        try:
            response = list_volumes_with_token(
                client=client,
                max_results=max_results,
                continuation_token=continuation_token
            )
        except ClientError as exc:
            msg = 'Problem querying for EBS volumes'
            raise EC2UtilError(msg) from exc
        if 'Volumes' not in response.keys():
            log.warning('Volumes not found in response: {r}'.format(r=str(response.keys())))
            return volumes
        if 'NextToken' not in response.keys():
            next_query = False
        else:
            continuation_token = response['NextToken']
        volumes += response['Volumes']
    log.info('Found {n} EBS volumes'.format(n=str(len(volumes))))
    return volumes


def list_unattached_volumes(client):
    """Return a list of volumes not currently attached to EC2 instances

    :param client: boto3.client object
    :return: (list) of volumes that are unattached
    """
    log = logging.getLogger(mod_logger + '.list_unattached_volumes')
    log.info('Getting a list of unattached EBS volumes...')
    volumes = list_volumes(client)
    unattached_volumes = []
    for volume in volumes:
        if 'Attachments' not in volume.keys():
            log.info('Volume has no Attachments data: {v}'.format(v=volume['VolumeId']))
            unattached_volumes.append(volume)
        elif len(volume['Attachments']) < 1:
            log.info('Volume has Attachments data showing less than 1 attachment: {v}'.format(v=volume['VolumeId']))
            unattached_volumes.append(volume)
        else:
            log.info('Found volume with {n} attachments: {v}'.format(
                n=str(len(volume['Attachments'])), v=volume['VolumeId']))
    log.info('Found [{n}] unattached volumes'.format(n=str(len(unattached_volumes))))
    return unattached_volumes


def get_volume(client, volume_id):
    """Returns detailed info about the volume ID

    :param client: boto3.client object
    :param volume_id: (str) ID of the volume to retrieve
    :return: (dict) data about the volume (see boto3 docs)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.get_volume')
    log.info('Getting info about volume ID: {i}'.format(i=volume_id))
    try:
        response = client.describe_volumes(DryRun=False, VolumeIds=[volume_id])
    except ClientError as exc:
        msg = 'Unable to describe volume ID: {a}'.format(a=volume_id)
        raise EC2UtilError(msg) from exc
    if 'Volumes' not in response.keys():
        msg = 'Volumes not found in response: {r}'.format(r=str(response))
        raise EC2UtilError(msg)
    volumes = response['Volumes']
    if not isinstance(volumes, list):
        msg = 'Expected Volumes to be a list, found: {t}'.format(t=volumes.__class__.__name__)
        raise EC2UtilError(msg)
    if len(volumes) != 1:
        msg = 'Expected to find 1 volume, found: {n}'.format(n=str(len(volumes)))
        raise EC2UtilError(msg)
    return volumes[0]


############################################################################
# Methods for retrieving internet gateways
############################################################################


def list_internet_gateways_with_token(client, max_results=100, continuation_token=None):
    """Returns a list of internet gateways using the provided token

    :param client: boto3.client object
    :param max_results: (int) max results to query on
    :param continuation_token: (str) token to query on
    :return: (dict) response object containing response data
    """
    if continuation_token:
        return client.describe_internet_gateways(
            DryRun=False,
            MaxResults=max_results,
            NextToken=continuation_token
        )
    else:
        return client.describe_internet_gateways(
            DryRun=False,
            MaxResults=max_results
        )


def list_internet_gateways(client):
    """Gets a list of internet gateways in this account/region

    :param client: boto3.client object
    :return: (list)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.list_internet_gateways')
    log.info('Getting a list of internet gateways...')
    internet_gateways = []
    continuation_token = None
    next_query = True
    max_results = 100
    while True:
        if not next_query:
            break
        try:
            response = list_internet_gateways_with_token(
                client=client,
                max_results=max_results,
                continuation_token=continuation_token
            )
        except ClientError as exc:
            msg = 'Problem querying for internet gateways'
            raise EC2UtilError(msg) from exc
        if 'InternetGateways' not in response.keys():
            log.warning('InternetGateways not found in response: {r}'.format(r=str(response.keys())))
            return internet_gateways
        if 'NextToken' not in response.keys():
            next_query = False
        else:
            continuation_token = response['NextToken']
        internet_gateways += response['InternetGateways']
    log.info('Found {n} internet gateways'.format(n=str(len(internet_gateways))))
    return internet_gateways


def delete_internet_gateway(client, ig_id):
    """Deletes the provided Internet Gateway ID

    :param client: boto3.client object
    :param ig_id: (str) ID of the Internet Gateway
    :return: None
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.delete_internet_gateway')
    log.info('Deleting Internet Gateway ID: {i}'.format(i=ig_id))
    try:
        client.delete_internet_gateway(
            DryRun=False,
            InternetGatewayId=ig_id
        )
    except ClientError as exc:
        msg = 'Problem deleting Internet Gateway: {i}'.format(i=ig_id)
        raise EC2UtilError(msg) from exc


def detach_internet_gateway(client, ig_id, vpc_id):
    """Detaches the Internet Gateway from the VPC

    :param client: boto3.client object
    :param ig_id: (str) ID of the Internet Gateway
    :param vpc_id: (str) ID of the VPC
    :return: None
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.detach_internet_gateway')
    log.info('Deleting Internet Gateway ID: {i}'.format(i=ig_id))
    try:
        client.detach_internet_gateway(
            DryRun=False,
            InternetGatewayId=ig_id,
            VpcId=vpc_id
        )
    except ClientError as exc:
        msg = 'Problem deleting Internet Gateway: {i}'.format(i=ig_id)
        raise EC2UtilError(msg) from exc


############################################################################
# Methods for subnets
############################################################################

def delete_subnet(client, subnet_id):
    """Deletes the subnet ID

    :param client: boto3.client object
    :param subnet_id: (str) ID of the subnet
    :return: None
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.delete_subnet')
    log.info('Deleting subnet ID: {i}'.format(i=subnet_id))
    try:
        client.delete_subnet(
            DryRun=False,
            SubnetId=subnet_id
        )
    except ClientError as exc:
        msg = 'Problem deleting subnet: {i}'.format(i=subnet_id)
        raise EC2UtilError(msg) from exc

############################################################################
# Methods for network interfaces
############################################################################


def create_network_interface(client, subnet_id, security_group_list, private_ip_address):
    """Creates a network interface

    :param client: boto3.client object
    :param subnet_id: (str) ID of the subnet
    :param security_group_list: (list) of security group IDs
    :param private_ip_address: (str) IP address to assign to the ENI
    :return: (list)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.create_network_interface')
    log.info('Creating a new ENI on subnet [{s}], with Security Groups [{g}] and private IP: {i}'.format(
        s=subnet_id, g=str(security_group_list), i=private_ip_address))
    try:
        response = client.create_network_interface(
            DryRun=False,
            SubnetId=subnet_id,
            Groups=security_group_list,
            PrivateIpAddress=private_ip_address
        )
    except ClientError as exc:
        msg = 'Problem creating and ENI on Subnet {s} using Security Groups {g} and private IP address: {i}'.format(
            s=subnet_id, g=security_group_list, i=private_ip_address)
        raise EC2UtilError(msg) from exc
    if 'NetworkInterface' not in response.keys():
        msg = 'NetworkInterface not found in response: {r}'.format(r=str(response))
        raise EC2UtilError(msg)
    if 'NetworkInterfaceId' not in response['NetworkInterface'].keys():
        msg = 'NetworkInterfaceId not found in network interface data: {r}'.format(r=str(response['NetworkInterface']))
        raise EC2UtilError(msg)
    return response['NetworkInterface']


############################################################################
# Methods for dedicated hosts
############################################################################


def get_host(client, host_id):
    """Returns detailed info about the dedicated host

    :param client: boto3.client object
    :param host_id: (str) ID of the host to retrieve
    :return: (dict) data about the host (see boto3 docs)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.get_host')
    log.info('Getting info about host ID: {i}'.format(i=host_id))
    try:
        response = client.describe_hosts(HostIds=[host_id])
    except ClientError as exc:
        msg = 'Unable to describe host ID: {a}'.format(a=host_id)
        raise EC2UtilError(msg) from exc
    if 'Hosts' not in response.keys():
        msg = 'Hosts not found in response: {r}'.format(r=str(response))
        raise EC2UtilError(msg)
    hosts = response['Hosts']
    if not isinstance(hosts, list):
        msg = 'Expected Hosts to be a list, found: {t}'.format(t=hosts.__class__.__name__)
        raise EC2UtilError(msg)
    if len(hosts) != 1:
        msg = 'Expected to find 1 host, found: {n}'.format(n=str(len(hosts)))
        raise EC2UtilError(msg)
    return hosts[0]


def get_host_capacity_for_instance_type(client, host_id, instance_type):
    """Returns detailed info about the dedicated host

    :param client: boto3.client object
    :param host_id: (str) ID of the host to retrieve
    :param instance_type: (str) AWS instance type
    :return: (dict) data about the host (see boto3 docs)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.get_host_capacity_for_instance_type')
    log.info('Getting info about host ID: {i}'.format(i=host_id))
    try:
        host = get_host(client=client, host_id=host_id)
    except ClientError as exc:
        msg = 'Unable to get details of host: {a}'.format(a=host_id)
        raise EC2UtilError(msg) from exc
    if 'AvailableCapacity' not in host.keys():
        msg = 'AvailableCapacity not found in host data: {r}'.format(r=str(host))
        raise EC2UtilError(msg)
    if 'AvailableInstanceCapacity' not in host['AvailableCapacity'].keys():
        msg = 'AvailableInstanceCapacity not found in host AvailableCapacity data: {r}'.format(
            r=str(host['AvailableCapacity']))
        raise EC2UtilError(msg)
    available_instance_capacity = host['AvailableCapacity']['AvailableInstanceCapacity']
    log.info('Checking for capacity of instance type [{t}] on host: {h}'.format(t=instance_type, h=host_id))
    for instance_type_capacity in available_instance_capacity:
        if 'InstanceType' not in instance_type_capacity.keys():
            log.warning('InstanceType not found in data: {d}'.format(d=str(instance_type_capacity)))
            continue
        if instance_type_capacity['InstanceType'] == instance_type:
            if 'AvailableCapacity' not in instance_type_capacity.keys():
                msg = 'AvailableCapacity not found in instance capacity data: {d}'.format(d=str(instance_type_capacity))
                raise EC2UtilError(msg)
            available_capacity = instance_type_capacity['AvailableCapacity']
            try:
                available_capacity = int(available_capacity)
            except ValueError:
                msg = 'Found available capacity data but it was not an integer: {c}'.format(c=available_capacity)
                raise EC2UtilError(msg)
            log.info('Found available capacity for instance type [{t}] on host [{h}]: {c}'.format(
                t=instance_type, h=host_id, c=str(available_capacity)))
            return available_capacity
    log.info('Available capacity not found for instance type [{t}] on host: {h}'.format(t=instance_type, h=host_id))
    return 0

############################################################################
# Methods for general networking
############################################################################

def get_additional_net_egress_ip_permissions():
    """Return a list of IPPermission objects to represent an additional network's internal egress rules

    :return: (list) of IpPermission objects
    :raises: EC2UtilError
    """

    # List of ingress rules, add default rule to allow traffic from the internal cons3rt-net CIDR
    sg_egress_rules = [
        IpPermission(IpProtocol='-1', CidrIp='0.0.0.0/0', Description='Allow all out')
    ]
    return sg_egress_rules


def get_additional_net_ingress_ip_permissions(internal_security_group_ids):
    """Return a list of IPPermission objects to represent an additional network's internal ingress rules

    NOTE - The input should exclude NAT security groups

    :param internal_security_group_ids: (list) of internal security group IDs
    :return: (list) of IpPermission objects
    :raises: EC2UtilError
    """

    sg_ingress_rules = []

    # Add a rule to allow all traffic from each of the internal security group IDs
    for internal_security_group_id in internal_security_group_ids:
        sg_ingress_rules.append(
            IpPermission(IpProtocol='-1', GroupId=internal_security_group_id,
                         Description='Allow traffic from an internal additional non-cons3rt network'),
        )
    return sg_ingress_rules


def get_additional_net_nat_egress_ip_permissions(cons3rt_infra):
    """Return a list of IPPermission objects to represent a typical egress for a routable additional network

    :param cons3rt_infra: (Cons3rtInfra) object describing a CONS3RT infrastructure
    :return: (list) of IpPermission objects
    :raises: EC2UtilError
    """

    # Add the base egress rules DNS, NTP, CONS3RT Infra, Remote Access to internal, and Elastic
    nat_sg_egress_rules = [
        IpPermission(IpProtocol='tcp', FromPort=53, ToPort=53, CidrIp='0.0.0.0/0',
                     Description='Allow DNS TCP traffic out'),
        IpPermission(IpProtocol='udp', FromPort=53, ToPort=53, CidrIp='0.0.0.0/0',
                     Description='Allow DNS UDP traffic out'),
        IpPermission(IpProtocol='tcp', FromPort=80, ToPort=80, CidrIp='0.0.0.0/0',
                     Description='Allow HTTP traffic out'),
        IpPermission(IpProtocol='tcp', FromPort=123, ToPort=123, CidrIp='0.0.0.0/0',
                     Description='Allow NTP TCP traffic out'),
        IpPermission(IpProtocol='udp', FromPort=123, ToPort=123, CidrIp='0.0.0.0/0',
                     Description='Allow NTP UDP traffic out'),
        IpPermission(IpProtocol='tcp', FromPort=443, ToPort=443, CidrIp='0.0.0.0/0',
                     Description='Allow HTTPS traffic out'),
        IpPermission(IpProtocol='tcp', FromPort=8443, ToPort=8443, CidrIp='0.0.0.0/0',
                     Description='Allow TCP/8443 traffic out'),
        IpPermission(IpProtocol='tcp', FromPort=cons3rt_infra.elastic_logging_port,
                     ToPort=cons3rt_infra.elastic_logging_port,
                     CidrIp=cons3rt_infra.elastic_logging_ip + '/32',
                     Description='Allow logging traffic to Elastic/Kibana'),
    ]
    return nat_sg_egress_rules


def get_additional_net_nat_ingress_ip_permissions(internal_security_group_id):
    """Return a list of IPPermission objects to represent an additional network's NAT ingress rules

    :param internal_security_group_id: (str) internal security group ID for the network
    :return: (list) of IpPermission objects
    :raises: EC2UtilError
    """

    nat_sg_ingress_rules = [
        IpPermission(
            IpProtocol='-1',
            GroupId=internal_security_group_id,
            Description='Allow traffic from the internal additional network security group')
    ]

    # Add a rule to allow all traffic from the internal security group ID
    return nat_sg_ingress_rules


def get_cons3rt_net_egress_ip_permissions():
    """Return a list of IPPermission objects to represent cons3rt-net internal egress rules

    :return: (list) of IpPermission objects
    :raises: EC2UtilError
    """

    # List of ingress rules, add default rule to allow traffic from the internal cons3rt-net CIDR
    sg_egress_rules = [
        IpPermission(IpProtocol='-1', CidrIp='0.0.0.0/0', Description='Allow all out')
    ]
    return sg_egress_rules


def get_cons3rt_net_ingress_ip_permissions(internal_security_group_id, nat_security_group_id, remote_access_port=9443):
    """Return a list of IPPermission objects to represent cons3rt-net internal ingress rules

    :param internal_security_group_id: (str) ID of the internal cons3rt-net security group
    :param nat_security_group_id: (str) ID on the cons3rt-net NAT security group
    :param remote_access_port: (int) Internal guacd server port
    :return: (list) of IpPermission objects
    :raises: EC2UtilError
    """

    # List of ingress rules, add default rule to allow traffic from the internal cons3rt-net CIDR
    sg_ingress_rules = [
        IpPermission(IpProtocol='-1', GroupId=internal_security_group_id,
                     Description='Allow traffic from the internal cons3rt-net Security Group'),
        IpPermission(IpProtocol='tcp', FromPort=remote_access_port,
                     ToPort=remote_access_port,
                     GroupId=nat_security_group_id,
                     Description='Allow remote access traffic from the cons3rt-net NAT Security Group')
    ]
    return sg_ingress_rules


def get_cons3rt_net_nat_egress_ip_permissions(cons3rt_infra, rhui_update_server_ips,
                                              internal_cons3rt_net_security_group_id,
                                              nat_cons3rt_net_security_group_id, remote_access_internal_port=9443):
    """Return a list of IPPermission objects to represent cons3rt-net NAT egress rules

    :param cons3rt_infra: (Cons3rtInfra) object describing a CONS3RT infrastructure
    :param rhui_update_server_ips: (list) of IP addresses of the Red Hat Update (RHUI) servers
    :param internal_cons3rt_net_security_group_id: (str) ID of the internal cons3rt-net Security Group
    :param remote_access_internal_port: (int) Internal port for remote access server
    :param nat_cons3rt_net_security_group_id: (str) ID of the NAT cons3rt-net Security Group
    :return: (list) of IpPermission objects
    :raises: EC2UtilError
    """
    # Validate the cons3rt_infra type
    if not isinstance(cons3rt_infra, Cons3rtInfra):
        raise EC2UtilError('cons3rt_infra object must be type Cons3rtInfra, found: [{t}]'.format(
            t=type(cons3rt_infra)))

    # Add the base egress rules DNS, NTP, CONS3RT Infra, Remote Access to internal, and Elastic
    nat_sg_egress_rules = [
        IpPermission(IpProtocol='tcp', FromPort=53, ToPort=53, CidrIp='0.0.0.0/0',
                     Description='Allow DNS TCP traffic out'),
        IpPermission(IpProtocol='udp', FromPort=53, ToPort=53, CidrIp='0.0.0.0/0',
                     Description='Allow DNS UDP traffic out'),
        IpPermission(IpProtocol='tcp', FromPort=123, ToPort=123, CidrIp='0.0.0.0/0',
                     Description='Allow NTP TCP traffic out'),
        IpPermission(IpProtocol='udp', FromPort=123, ToPort=123, CidrIp='0.0.0.0/0',
                     Description='Allow NTP UDP traffic out'),
        IpPermission(IpProtocol='tcp', FromPort=cons3rt_infra.web_gateway_port, ToPort=cons3rt_infra.web_gateway_port,
                     CidrIp=cons3rt_infra.web_gateway_ip + '/32',
                     Description='Allow web-gateway traffic to CONS3RT'),
        IpPermission(IpProtocol='tcp', FromPort=cons3rt_infra.messaging_port, ToPort=cons3rt_infra.messaging_port,
                     CidrIp=cons3rt_infra.messaging_inbound_ip + '/32',
                     Description='Allow messaging traffic to CONS3RT'),
        IpPermission(IpProtocol='tcp', FromPort=cons3rt_infra.sourcebuilder_port,
                     ToPort=cons3rt_infra.sourcebuilder_port,
                     CidrIp=cons3rt_infra.sourcebuilder_inbound_ip + '/32',
                     Description='Allow gitlab container registry traffic to CONS3RT'),
        IpPermission(IpProtocol='tcp', FromPort=cons3rt_infra.webdav_port, ToPort=cons3rt_infra.webdav_port,
                     CidrIp=cons3rt_infra.webdav_inbound_ip + '/32',
                     Description='Allow cons3rt webdav traffic to CONS3RT'),
        IpPermission(IpProtocol='tcp', FromPort=cons3rt_infra.assetdb_port, ToPort=cons3rt_infra.assetdb_port,
                     CidrIp=cons3rt_infra.assetdb_inbound_ip + '/32',
                     Description='Allow blobstore traffic to CONS3RT'),
        IpPermission(IpProtocol='tcp', FromPort=cons3rt_infra.elastic_logging_port,
                     ToPort=cons3rt_infra.elastic_logging_port,
                     CidrIp=cons3rt_infra.elastic_logging_ip + '/32',
                     Description='Allow logging traffic to Elastic/Kibana'),
        IpPermission(IpProtocol='tcp', FromPort=remote_access_internal_port,
                     ToPort=remote_access_internal_port,
                     GroupId=internal_cons3rt_net_security_group_id,
                     Description='Allow remote access traffic to the internal cons3rt-net security group'),
        IpPermission(IpProtocol='-1', GroupId=nat_cons3rt_net_security_group_id,
                     Description='Allow traffic to the NAT cons3rt-net security group'),
    ]

    # Add rules for RHUI Red Hat update servers
    for rhui_update_server_ip in rhui_update_server_ips:
        if not validate_ip_address(rhui_update_server_ip):
            raise EC2UtilError('Invalid RHUI server IP found: [{i}]'.format(i=rhui_update_server_ip))
        nat_sg_egress_rules.append(
            IpPermission(IpProtocol='tcp', FromPort=443, ToPort=443,
                         CidrIp=rhui_update_server_ip + '/32',
                         Description='Allow traffic to Red Hat Update Server'),
        )
    return nat_sg_egress_rules


def get_cons3rt_net_nat_ingress_ip_permissions(cons3rt_infra, internal_security_group_id, nat_security_group_id,
                                               external_remote_access_port=9443):
    """Return a list of IPPermission objects to represent cons3rt-net NAT ingress rules

    :param cons3rt_infra: (Cons3rtInfra) object describing a CONS3RT infrastructure
    :param internal_security_group_id: (str) ID of the internal Security Group
    :param nat_security_group_id: (str) ID of the NAT Security Group
    :param external_remote_access_port: (int) External port for remote access traffic
    :return: (list) of IpPermission objects
    :raises: EC2UtilError
    """

    # List of ingress rules, add default rule to allow traffic from the internal cons3rt-net CIDR
    nat_sg_ingress_rules = [
        IpPermission(IpProtocol='-1', GroupId=internal_security_group_id,
                     Description='Allow traffic from the internal cons3rt-net Security Group'),
        IpPermission(IpProtocol='-1', GroupId=nat_security_group_id,
                     Description='Allow traffic from the NAT cons3rt-net Security Group')
    ]

    # Build a unique list of IPs to allow remote access traffic from
    remote_access_ingress_ips = []
    if cons3rt_infra.cons3rt_outbound_ip not in remote_access_ingress_ips:
        remote_access_ingress_ips.append(cons3rt_infra.cons3rt_outbound_ip)
    if cons3rt_infra.venue_outbound_ip not in remote_access_ingress_ips:
        remote_access_ingress_ips.append(cons3rt_infra.venue_outbound_ip)
    if cons3rt_infra.web_gateway_ip not in remote_access_ingress_ips:
        remote_access_ingress_ips.append(cons3rt_infra.web_gateway_ip)

    for remote_access_ingress_ip in remote_access_ingress_ips:
        nat_sg_ingress_rules.append(
            IpPermission(IpProtocol='tcp', FromPort=external_remote_access_port,
                         ToPort=external_remote_access_port,
                         CidrIp=remote_access_ingress_ip + '/32',
                         Description='Allow remote access traffic inbound to the RA box')
        )
    return nat_sg_ingress_rules


def get_remote_access_internal_ip(cons3rt_net_cidr, remote_access_ip_last_octet):
    """Given a CIDR and remote access last octet, return a list of IPPermission objects to represent
    cons3rt-net egress rules

    :param cons3rt_net_cidr: (str) CIDR block for the cons3rt-net
    :param remote_access_ip_last_octet: (str) Last octet for the internal remote access IP address
    :return: (list) of IpPermission
    :raises: EC2UtilError
    """

    # Validate args
    if not isinstance(cons3rt_net_cidr, str):
        raise EC2UtilError('Expected string for cons3rt_net_cidr, found: [{t}]'.format(t=type(cons3rt_net_cidr)))
    if not isinstance(remote_access_ip_last_octet, str):
        raise EC2UtilError('Expected string for remote_access_ip_last_octet, found: [{t}]'.format(
            t=type(remote_access_ip_last_octet)))

    # Split the CIDR by the /
    remote_access_cidr_base_parts = cons3rt_net_cidr.split('/')
    if len(remote_access_cidr_base_parts) != 2:
        raise EC2UtilError('Invalid cons3rt-net CIDR provided, unable to split on /, '
                           'expected format x.x.x.x/y: {s}'.format(s=cons3rt_net_cidr))
    remote_access_cidr_base = remote_access_cidr_base_parts[0]

    # Ensure the CIDR base is valid
    if not validate_ip_address(remote_access_cidr_base):
        raise EC2UtilError('Invalid cons3rt-net CIDR provided, CIDR base expected format x.x.x.x: {s}'.format(
            s=remote_access_cidr_base))

    # Split the IP octets
    octets = remote_access_cidr_base.split('.')
    if len(octets) != 4:
        raise EC2UtilError('Invalid cons3rt-net CIDR provided, unable to split on ., '
                           'expected format x.x.x.x/y: {s}'.format(s=cons3rt_net_cidr))

    # Build the remote access internal IP address string
    remote_access_internal_ip = octets[0] + '.'
    remote_access_internal_ip += octets[1] + '.'
    remote_access_internal_ip += octets[2] + '.'
    remote_access_internal_ip += remote_access_ip_last_octet

    if not validate_ip_address(remote_access_internal_ip):
        raise EC2UtilError('Invalid remote access internal IP address found: [{i}]'.format(
            i=remote_access_internal_ip))
    return remote_access_internal_ip
