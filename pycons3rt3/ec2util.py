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

from .bash import get_ip_addresses, validate_ip_address
from .logify import Logify
from .network import get_ip_list_for_hostname_list
from .osutil import get_os, get_pycons3rt_scripts_dir
from .aws_metadata import is_aws, get_instance_id, get_vpc_id_from_mac_address
from .awsutil import get_boto3_client, global_regions, gov_regions, us_regions
from .exceptions import AWSAPIError, AwsTransitGatewayError, EC2UtilError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.ec2util'


# NAT AMI IDs used for cons3rt NAT VMs
nat_vm_ami = {
    'us-gov-west-1': 'ami-b62917d7',
    'us-gov-east-1': 'ami-5623cd27',
    'us-east-1': 'ami-01ef31f9f39c5aaed',
    'us-east-2': 'ami-06064740484d375de',
    'us-west-2': 'ami-0fcc6101b7f2370b9'
}

nat_user_data_script_path = os.path.join(get_pycons3rt_scripts_dir(), 'linux-nat-config.sh')

nat_default_size = 't3.micro'


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
            return

        if not self.instance_id:
            log.warning('Unable to get the Instance ID for this machine')
            return
        log.info('Found Instance ID: {i}'.format(i=self.instance_id))

        log.info('Querying AWS to get the VPC ID...')
        try:
            instance = get_instance(client=self.client, instance_id=self.instance_id)
        except ClientError as exc:
            log.warning('Unable to query AWS to get info for instance {i}\n{e}'.format(i=self.instance_id, e=str(exc)))
            return
        if 'VpcId' in instance.keys():
            log.info('Found VPC ID: {v}'.format(v=instance['VpcId']))
            return instance['VpcId']
        log.warning('Unable to get VPC ID from instance: {i}'.format(i=str(instance)))

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
        if 'Regions' not in response:
            raise EC2UtilError('Regions not found in response: {r}'.format(r=str(response)))
        return response['Regions']

    def get_rhui3_servers(self, all_available=False):
        """Returns a list of RHUI servers for my region

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

    def list_route_tables_with_token(self, next_token=None, vpc_id=None):
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

    def list_route_tables(self, vpc_id=None):
        """Returns the list of subnets for the VPC

        :param vpc_id: (str) VPC ID to filter on if provided
        :return: (list) of route tables (see boto3 docs)
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.list_route_tables')
        if vpc_id:
            log.info('Listing route tables in VPC ID: {v}'.format(v=vpc_id))
        else:
            log.info('Listing route tables...')
        next_token = None
        next_query = True
        route_tables = []
        while next_query:
            response = self.list_route_tables_with_token(vpc_id=vpc_id, next_token=next_token)
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

        :param interface: Integer associated to the interface/device number
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
        elastic IP to the interface number on this host.

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
        elastic IP to the instance

        :param allocation_id: String ID for the elastic IP
        :param instance_id: Integer associated to the interface/device number
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

    def attach_new_eni(self, subnet_name, security_group_ids, device_index=2, allocation_id=None, description=''):
        """Creates a new Elastic Network Interface on the Subnet
        matching the subnet_name, with Security Group identified by
        the security_group_name, then attaches an Elastic IP address
        if specified in the allocation_id parameter, and finally
        attaches the new ENI to the EC2 instance instance_id at
        device index device_index.

        :param subnet_name: String name of the subnet
        :param security_group_ids: List of str IDs of the security groups
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
            return
        else:
            log.info('Found Public IPs: {p}'.format(p=public_ips))

        # Get info for each Public/Elastic IP
        try:
            address_info = self.client.describe_addresses(DryRun=False, PublicIps=public_ips)
        except ClientError as exc:
            msg = 'Unable to query AWS to get info for addresses {p}'.format(p=public_ips)
            log.error(msg)
            raise EC2UtilError(msg) from exc
        if not address_info:
            msg = 'No address info return for Public IPs: {p}'.format(p=public_ips)
            log.error(msg)
            raise EC2UtilError(msg)
        return address_info

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
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_security_group_egress_rules')

        if not isinstance(add_rules, list):
            raise EC2UtilError('add_rules arg must be type list, found: {t}'.format(
                t=add_rules.__class__.__name__))

        if len(add_rules) < 1:
            log.info('No egress rules provided to add to security group: {g}'.format(g=security_group_id))
            return

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

    def add_security_group_ingress_rules(self, security_group_id, add_rules):
        """Revokes a list of security group rules

        :param security_group_id: (str) Security Group ID
        :param add_rules: (list) List of IpPermission objects to add
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_security_group_ingress_rules')

        if not isinstance(add_rules, list):
            raise EC2UtilError('add_rules arg must be type list, found: {t}'.format(
                t=add_rules.__class__.__name__))

        if len(add_rules) < 1:
            log.info('No ingress rules provided to add to security group: {g}'.format(g=security_group_id))
            return

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
        log.info('Getting egress rules for security group: {i}'.format(i=security_group_id))
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
        :return: None
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
        self.add_security_group_egress_rules(security_group_id=security_group_id, add_rules=add_ip_perms)
        log.info('Completed configuring egress rules for security group: {g}'.format(g=security_group_id))

    def configure_security_group_ingress(self, security_group_id, desired_ingress_rules):
        """Configures the security group ID allowing access
        only to the specified CIDR blocks, for the specified
        port number.

        :param security_group_id: (str) Security Group ID
        :param desired_ingress_rules: (list) List of IpPermissions as described in AWS boto3 docs
        :return: None
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.configure_security_group_egress')
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
        self.add_security_group_ingress_rules(security_group_id=security_group_id, add_rules=add_ip_perms)
        log.info('Completed configuring ingress rules for security group: {g}'.format(g=security_group_id))

    def configure_security_group_ingress_legacy(self, security_group_id, port, desired_cidr_blocks, protocol='tcp'):
        """Configures the security group ID allowing access
        only to the specified CIDR blocks, for the specified
        port number.

        :param security_group_id: (str) Security Group ID
        :param port: (str) Port number
        :param desired_cidr_blocks: (list) List of desired CIDR
               blocks, e.g. 192.168.1.2/32
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

        # Build ingress rule based on the provided CIDR block list
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
        """Revokes all ingress rules for a security group bu ID

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
        """Revokes all egress rules for a security group bu ID

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

    def verify_security_groups_in_vpc(self, security_group_id_list, vpc_id):
        """Determines if the provided list of security groups reside in the VPC
        
        :param security_group_id_list: (list) of security group IDs
        :param vpc_id: (str) ID of the VPC 
        :return: True if all of the security groups live in the provided VPC
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
                        user_data_script_path=None, instance_type='t3.small', root_volume_location='/dev/xvda',
                        root_volume_size_gb=100):
        """Launches an EC2 instance with the specified parameters, intended to launch
        an instance for creation of a CONS3RT template.

        :param ami_id: (str) ID of the AMI to launch from
        :param key_name: (str) Name of the key-pair to use
        :param subnet_id: (str) IF of the VPC subnet to attach the instance to
        :param security_group_id: (str) ID of the security group, of not provided the default will be applied
                appended to security_group_list if provided
        :param security_group_list: (list) of IDs of the security group, if not provided the default will be applied
        :param user_data_script_path: (str) Path to the user-data script to run
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
        if user_data_script_path is not None:
            if os.path.isfile(user_data_script_path):
                with open(user_data_script_path, 'r') as f:
                    user_data = f.read()
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

    def wait_for_instance_running(self, instance_id, timeout_sec=900):
        """Waits until the instance ID is in a running state

        :param instance_id: (str) ID of the instance
        :param timeout_sec: (int) Time in seconds before returning False
        :return: True when available, False if not available by the provided timeout
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.wait_for_instance_running')
        check_interval_sec = 10
        num_checks = timeout_sec // check_interval_sec
        start_time = time.time()
        log.info('Waiting a maximum of {t} seconds for instance ID [{i}] to reach a running state'.format(
            t=str(timeout_sec), i=instance_id))
        for _ in range(0, num_checks*2):
            log.info('Waiting {t} seconds to check state of instance ID: {i}'.format(
                t=str(check_interval_sec), i=instance_id))
            time.sleep(check_interval_sec)
            elapsed_time = round(time.time() - start_time, 1)
            if elapsed_time > timeout_sec:
                log.warning('Instance ID {i} not running after {t} seconds'.format(
                    i=instance_id, t=str(timeout_sec)))
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
            if instance['State']['Name'] == 'running':
                log.info('Instance ID [{i}] state is running, exiting...'.format(i=instance_id))
                return True
            else:
                log.info('Instance ID [{i}] is in state: {s}'.format(i=instance_id, s=instance['State']['Name']))
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

    def get_ec2_instances(self):
        """Describes the EC2 instances

        :return: dict containing EC2 instance data
        :raises: EC2UtilError
        """
        return list_instances(client=self.client)

    def get_ebs_volumes(self):
        """Describes the EBS volumes

        :return: dict containing EBS volume data
        :raises EC2UtilError
        """
        return list_volumes(client=self.client)

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
            return

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
            igs = list_internet_gateways(client=self.client)
        except EC2UtilError as exc:
            msg = 'Problem listing internet gateways'
            raise EC2UtilError(msg) from exc

        for ig in igs:
            if 'Attachments' in ig.keys():
                for attachment in ig['Attachments']:
                    if attachment['VpcId'] == vpc['VpcId']:
                        log.info('VPC [{v}] already has attached Internet gateway [{i}]'.format(
                            v=vpc['VpcId'], i=ig['InternetGatewayId']))
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

    def create_route_table(self, name, vpc_id):
        """Creates a subnet

        :param name: (str) route table name
        :param vpc_id: (str) VPC ID
        :return: (str) route table ID
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_route_table')
        log.info('Creating route table with name [{n}] in VPC ID: {v}'.format(n=name, v=vpc_id))
        try:
            response = self.client.create_route_table(VpcId=vpc_id, DryRun=False)
        except ClientError as exc:
            msg = 'There was a problem creating route table [{n}] in VPC ID: {i}'.format(n=name, i=vpc_id)
            raise EC2UtilError(msg) from exc

        # Get the new VPC ID
        if 'RouteTable' not in response.keys():
            raise EC2UtilError('Route Table not created with name: {n}'.format(n=name))

        if 'RouteTableId' not in response['RouteTable'].keys():
            raise EC2UtilError('RouteTableId data not found in: {d}'.format(d=str(response['RouteTable'])))
        route_table_id = response['RouteTable']['RouteTableId']

        # Ensure the route table ID created exists
        if not self.ensure_exists(resource_id=route_table_id):
            raise EC2UtilError('Created route table ID not found after timeout: {i}'.format(i=route_table_id))

        # Apply the name tag
        if not self.create_name_tag(resource_id=route_table_id, resource_name=name):
            raise EC2UtilError('Problem adding name tag name of route table ID: {i}'.format(i=route_table_id))
        log.info('Created new route table with ID: {i}'.format(i=route_table_id))
        return route_table_id

    def associate_route_table(self, route_table_id, subnet_id):
        """Associates the route table to the subnet

        :param route_table_id: (str) ID of the route table
        :param subnet_id: (str) ID of the subnet
        :return: (str) ID of the association
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.associate_route_table')
        log.info('Associating route table [{r}] with subnet ID: {s}'.format(r=route_table_id, s=subnet_id))
        try:
            response = self.client.associate_route_table(RouteTableId=route_table_id, SubnetId=subnet_id, DryRun=False)
        except ClientError as exc:
            msg = 'Problem associating route table [{r}] with subnet ID: {s}'.format(r=route_table_id, s=subnet_id)
            raise EC2UtilError(msg) from exc

        # Get the new VPC ID
        if 'AssociationId' not in response.keys():
            raise EC2UtilError('AssociationId not found in response: {d}'.format(d=str(response)))
        association_id = response['AssociationId']
        log.info('Associated route table [{r}] to subnet [{s}] with association ID: {a}'.format(
            r=route_table_id, s=subnet_id, a=association_id))
        return association_id

    def create_network_acl(self, name, vpc_id):
        """Creates a subnet

        :param name: (str) route table name
        :param vpc_id: (str) VPC ID
        :return: (str) route table ID
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

    def get_network_acl_for_subnet(self, subnet_id):
        """Returns the associated network ACL ID for the specified subnet ID

        :param subnet_id: (str) ID of the subnet
        :return: (tuple) Network ACL ID, association ID
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
            msg = 'NetworkAcls not in response: {r}'.format(r=str(response))
            raise EC2UtilError(msg)
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
        return network_acl_id, association_id

    def associate_network_acl(self, network_acl_id, subnet_id):
        """Associates the network ACL to the subnet

        :param network_acl_id: (str) ID of the network ACL
        :param subnet_id: (str) ID of the subnet
        :return: (str) ID of the association
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.associate_network_acl')

        # Get the current/default subnet association
        log.info('Getting the current network ACL association for subnet ID: {s}'.format(s=subnet_id))
        try:
            current_network_acl_id, association_id = self.get_network_acl_for_subnet(subnet_id=subnet_id)
        except EC2UtilError as exc:
            msg = 'Problem getting the network ACL ID from subnet ID: {i}'.format(i=subnet_id)
            raise EC2UtilError(msg) from exc

        log.info('Replacing current network ACL [{c}] under association ID [{a}] with network ACL [{n}] in '
                 'subnet ID: {s}'.format(c=current_network_acl_id, a=association_id, n=network_acl_id, s=subnet_id))
        try:
            response = self.client.replace_network_acl_association(
                AssociationId=association_id, NetworkAclId=network_acl_id, DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem associating network ACL [{n}] with subnet ID: {s}'.format(n=network_acl_id, s=subnet_id)
            raise EC2UtilError(msg) from exc

        # Get the new VPC ID
        if 'NewAssociationId' not in response.keys():
            raise EC2UtilError('NewAssociationId not found in response: {d}'.format(d=str(response)))
        new_association_id = response['NewAssociationId']
        log.info('Associated network ACL [{n}] to subnet [{s}] with association ID: {a}'.format(
            n=network_acl_id, s=subnet_id, a=new_association_id))
        return new_association_id

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

    def launch_nat_instance_for_cons3rt(self, name, nat_subnet_id, key_name, nat_security_group_id, subnet_cidr, region,
                                        remote_access_internal_ip, remote_access_port=9443):
        """Launches a NAT instance to attach to a CONS3RT network

        :param name: (str) name of the instance
        :param nat_subnet_id: (str) ID of the subnet to launch into
        :param key_name: (str) Name of the AWS keypair to use when launching
        :param nat_security_group_id: (str) ID of the NAT security group
        :param subnet_cidr: (str) CIDR block for the internal subnet the NAT instance will be NAT'ing for
        :param region: (str) region launching in to
        :param remote_access_internal_ip: (str) internal VPC IP address of the remote access box
        :param remote_access_port: (int) TCP port number for remote access
        :return: (str) NAT instance ID
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.launch_nat_instance_for_cons3rt')

        # Ensure the user-data skeleton script exists
        if not os.path.isfile(nat_user_data_script_path):
            msg = 'NAT user-data script not found: {f}'.format(f=nat_user_data_script_path)
            raise EC2UtilError(msg)

        # Ensure the RA server is a valid IP
        if not validate_ip_address(remote_access_internal_ip):
            msg = 'Provided remote access IP is not valid: {r}'.format(r=remote_access_internal_ip)
            raise EC2UtilError(msg)

        # Ensure the RA port is valid
        try:
            int(remote_access_port)
        except ValueError:
            msg = 'Remote access port must be an int, found: {p}'.format(p=str(remote_access_port))
            raise EC2UtilError(msg)
        remote_access_port = str(remote_access_port)

        # Determine the AMI ID
        try:
            ami_id = nat_vm_ami[region]
        except KeyError:
            msg = 'AMI ID for region [{r}] not found in NAT AMI data: {d}'.format(r=region, d=str(nat_vm_ami))
            raise EC2UtilError(msg)

        # Read in the user-data script
        with open(nat_user_data_script_path, 'r') as f:
            user_data_script_contents = f.read()

        # Replace the guac server IP, port, and virt tech
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_GUAC_SERVER_IP', remote_access_internal_ip)
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_GUAC_SERVER_PORT', remote_access_port)
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_REPLACE_ME_VIRT_TECH', 'amazon')

        # Replace the DNAT rules
        # Example:
        # iptables -t nat -I PREROUTING -d ${ipAddress} -p TCP --dport 9443 -j DNAT --to-destination 172.16.10.250:9443
        # iptables -t nat -I POSTROUTING -d 172.16.10.250 -j SNAT --to-source ${ipAddress}
        ra_dnat_rules = 'iptables -t nat -I PREROUTING -d $ipAddress -p TCP --dport {p} -j DNAT --to-destination ' \
                        '{i}:{p}'.format(i=remote_access_internal_ip, p=remote_access_port)
        ra_dnat_rules += '\n\t'
        ra_dnat_rules += 'iptables -t nat -I POSTROUTING -d {i} -j SNAT --to-source $ipAddress'.format(
            i=remote_access_internal_ip)
        ra_dnat_rules += '\n'

        log.info('Replacing DNAT rules with: {r}'.format(r=ra_dnat_rules))
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_ADD_IPTABLES_DNAT_RULES_HERE', ra_dnat_rules)

        # Replace the SNAT rule
        # Example:
        # iptables -t nat -A POSTROUTING -s 172.16.10.0/24 -j SNAT --to-source ${ipAddress}
        snat_rule = 'iptables -t nat -A POSTROUTING -s {s} -j SNAT --to-source $ipAddress'.format(s=subnet_cidr)
        user_data_script_contents = user_data_script_contents.replace(
            'CODE_ADD_IPTABLES_SNAT_RULES_HERE', snat_rule)

        # Write the updated user-data script
        user_data_script_path = os.path.join(get_pycons3rt_scripts_dir(), 'temp_user_data_script.sh')
        with open(user_data_script_path, 'w') as f:
            f.write(user_data_script_contents)

        # Launch the NAT VM
        log.info('Attempting to launch the NAT VM...')
        try:
            instance_info = self.launch_instance(
                ami_id=ami_id,
                key_name=key_name,
                subnet_id=nat_subnet_id,
                security_group_id=nat_security_group_id,
                user_data_script_path=user_data_script_path,
                instance_type=nat_default_size,
                root_volume_location='/dev/xvda',
                root_volume_size_gb=8
            )
        except EC2UtilError as exc:
            msg = 'Problem launching the NAT EC2 instance with name: {n}'.format(n=name)
            raise EC2UtilError(msg) from exc
        instance_id = instance_info['InstanceId']
        log.info('Launched NAT instance ID: {i}'.format(i=instance_id))

        # Ensure the instance ID exists
        if not self.ensure_exists(resource_id=instance_id):
            raise EC2UtilError('Problem finding instance ID after successful creation: {i}'.format(i=instance_id))

        # Apply the name tag
        if not self.create_name_tag(resource_id=instance_id, resource_name=name):
            raise EC2UtilError('Problem adding name tag name of instance ID: {i}'.format(i=instance_id))

        # Wait for instance availability
        if not self.wait_for_instance_availability(instance_id=instance_id):
            msg = 'NAT instance did not become available'
            raise EC2UtilError(msg)
        log.info('NAT instance ID [{i}] is available and passed all checks'.format(i=instance_id))

        # Set the source/dest checks to disabled/False
        try:
            self.set_instance_source_dest_check(instance_id=instance_id, source_dest_check=False)
        except EC2UtilError as exc:
            msg = 'Problem setting NAT instance ID [{i}] source/destination check to disabled'.format(i=instance_id)
            raise EC2UtilError(msg) from exc
        log.info('Set NAT instance ID [{i}] source/destination check to disabled'.format(i=instance_id))
        return instance_id

    def allocate_network_for_cons3rt(self, name, vpc_id, cidr, vpc_cidr_blocks, availability_zone,
                                     routable=False, key_name=None, nat_subnet_id=None, remote_access_internal_ip=None,
                                     remote_access_port=9443, is_nat_subnet=False, is_cons3rt_net=False,
                                     cons3rt_site_ip=None, ig_id=None):
        """Allocates a network and related resources for registration in CONS3RT

        :param name: (str) Name tag for the subnet and other resources
        :param vpc_id: (str) ID of the VPC to create resources in
        :param cidr: (str) CIDR block for the new subnet
        :param vpc_cidr_blocks: (list) of str VPC CIDR blocks
        :param availability_zone: (str) availability zone
        :param routable: (bool) Set True to make the network routable, creates a NAT SG and a NAT instance
        :param key_name: (str) Name of the key pair to use for the NAT instance
        :param nat_subnet_id: (str) ID of the subnet where NATs deploy into
        :param remote_access_internal_ip: (str) internal IP of remote access on the cons3rt-net
        :param remote_access_port: (int) TCP port for remote access
        :param is_nat_subnet: (bool) Set True only when allocating a subnet for NAT instances
        :param is_cons3rt_net: (bool) Set True only when allocating a cons3rt-net
        :param cons3rt_site_ip: (str) IP address of the CONS3RT site (required for cons3rt-net)
        :param ig_id: (str) ID of the Internet gateway (required for NAT subnet e.g. common-net)
        :return: (Cons3rtNetwork) containing information about the network and its resources
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.allocate_network_for_cons3rt')
        region = availability_zone[:len(availability_zone)-1]

        # NAT subnet is never considered "routable" -- doesn't need a NAT box
        if is_nat_subnet:
            if not ig_id:
                raise EC2UtilError('ig_id for the Internet Gateway must be specified for a NAT subnet')
            routable = False
            is_cons3rt_net = False

        # Ensure the cons3rt-net is set up to be routable
        if is_cons3rt_net:
            if not cons3rt_site_ip:
                raise EC2UtilError('cons3rt_site_ip must be specified for a cons3rt-net network')
            routable = True

        # Ensure additional routable params are provided when needed
        if routable:
            if not key_name:
                raise EC2UtilError('key_name must be specified for a routable network')
            if not nat_subnet_id:
                raise EC2UtilError('nat_subnet_id must be specified for a routable network')
            if not remote_access_internal_ip:
                raise EC2UtilError('remote_access_internal_ip must be specified for a routable network')
            if not remote_access_port:
                raise EC2UtilError('remote_access_port must be specified for a routable network')
            try:
                int(remote_access_port)
            except ValueError:
                raise EC2UtilError('remote_access_port must be an integer TCP port number')

        log.info('Attempting to allocate a CONS3RT network with resources named [{n}], in VPC ID [{v}], with CIDR '
                 '[{c}], in availability zone [{z}]'.format(n=name, v=vpc_id, c=cidr, z=availability_zone))
        try:
            subnet_id = self.create_subnet(name=name, cidr=cidr, vpc_id=vpc_id, availability_zone=availability_zone)
            self.set_subnet_auto_assign_public_ip(subnet_id=subnet_id, auto_assign=is_nat_subnet)

            # Apply the cons3rtenabled tag except for NAT subnets
            if not is_nat_subnet:
                if not self.create_cons3rt_enabled_tag(resource_id=subnet_id, enabled=True):
                    raise EC2UtilError('Problem setting cons3rtenabled true on subnet: {i}'.format(i=subnet_id))

            route_table_id = self.create_route_table(name=name + '-rt', vpc_id=vpc_id)
            self.associate_route_table(route_table_id=route_table_id, subnet_id=subnet_id)
            network_acl_id = self.create_network_acl(name=name + '-acl', vpc_id=vpc_id)
            self.associate_network_acl(network_acl_id=network_acl_id, subnet_id=subnet_id)
            self.create_network_acl_rule(network_acl_id=network_acl_id, rule_num=100, cidr='0.0.0.0/0',
                                         rule_action='allow', protocol='-1', egress=False)
            self.create_network_acl_rule(network_acl_id=network_acl_id, rule_num=100, cidr='0.0.0.0/0',
                                         rule_action='allow', protocol='-1', egress=True)
            security_group_id = self.create_security_group(name=name + '-sg', vpc_id=vpc_id,
                                                           description='Internal CONS3RT SUT SG')
            if not self.ensure_exists(resource_id=security_group_id):
                raise EC2UtilError('Resource not found: {r}'.format(r=security_group_id))
        except EC2UtilError as exc:
            msg = 'Problem creating network resources for subnet with name [{n}] in VPC ID: {v}'.format(
                n=name, v=vpc_id)
            raise EC2UtilError(msg) from exc

        # VPC Security group rules and routes
        security_group_ingress_rules = []
        route_table_routes = []
        for vpc_cidr in vpc_cidr_blocks:
            security_group_ingress_rules.append(
                IpPermission(IpProtocol='-1', CidrIp=vpc_cidr, Description='Allow all from the VPC CIDR')
            )
            route_table_routes.append(
                IpRoute(cidr=vpc_cidr, target='local')
            )
        security_group_egress_rules = [
            IpPermission(IpProtocol='-1', CidrIp='0.0.0.0/0', Description='Allow all out')
        ]

        # Create additional resources for routable networks
        if not routable:
            nat_security_group_id = None
            nat_instance_id = None
        else:
            log.info('Allocating a routable network, creating additional resources...')
            try:
                nat_security_group_id = self.create_security_group(name=name + '-nat-sg', vpc_id=vpc_id,
                                                                   description='CONS3RT NAT security group')

                # Specify the ingress rules for the NAT security group
                nat_sg_ingress_rules = [
                    IpPermission(IpProtocol='-1', CidrIp=cidr,
                                 Description='Allow from the internal subnet')
                ]
                nat_sg_egress_rules = [
                    IpPermission(IpProtocol='-1', CidrIp='0.0.0.0/0', Description='Allow all out')
                ]

                # Configure cons3rt-net specific ingress and egress rules
                if is_cons3rt_net:
                    # Additional ingress rules for the cons3rt-net internal security group
                    security_group_ingress_rules.append(
                        IpPermission(IpProtocol='tcp', FromPort=remote_access_port, ToPort=remote_access_port,
                                     CidrIp=remote_access_internal_ip, Description='Remote access from the NAT')
                    )

                    # Additional ingress rules for the cons3rt-net NAT security group
                    cons3rt_site_cidr = cons3rt_site_ip + '/32'
                    nat_sg_ingress_rules.append(
                        IpPermission(IpProtocol='tcp', FromPort=remote_access_port, ToPort=remote_access_port,
                                     CidrIp=cons3rt_site_cidr, Description='Remote access from CONS3RT site')
                    )
                    nat_sg_ingress_rules.append(
                        IpPermission(IpProtocol='tcp', FromPort=remote_access_port, ToPort=remote_access_port,
                                     CidrIp='140.24.0.0/16', Description='Remote access from CONS3RT site through DREN')
                    )
                    """ TODO add UserIdGroupPairs
                    nat_sg_ingress_rules.append(
                        IpPermission(IpProtocol='-1', PrefixListId=nat_security_group_id,
                                     Description='All traffic from itself')
                    )
                    """

                    # Replace egress rules for the cons3rt-net NAT security group
                    nat_sg_egress_rules = [
                        IpPermission(IpProtocol='tcp', FromPort=53, ToPort=53, CidrIp='0.0.0.0/0',
                                     Description='Allow DNS TCP traffic out'),
                        IpPermission(IpProtocol='udp', FromPort=53, ToPort=53, CidrIp='0.0.0.0/0',
                                     Description='Allow DNS UDP traffic out'),
                        IpPermission(IpProtocol='tcp', FromPort=443, ToPort=443, CidrIp='0.0.0.0/0',
                                     Description='Allow https traffic out'),
                        IpPermission(IpProtocol='tcp', FromPort=4443, ToPort=4443, CidrIp=cons3rt_site_cidr,
                                     Description='Allow messaging traffic to CONS3RT site'),
                        IpPermission(IpProtocol='tcp', FromPort=5443, ToPort=5443, CidrIp=cons3rt_site_cidr,
                                     Description='Allow gitlab container registry traffic to CONS3RT site'),
                        IpPermission(IpProtocol='tcp', FromPort=6443, ToPort=6443, CidrIp=cons3rt_site_cidr,
                                     Description='Allow docker registry traffic to CONS3RT site'),
                        IpPermission(IpProtocol='tcp', FromPort=7443, ToPort=7443, CidrIp=cons3rt_site_cidr,
                                     Description='Allow cons3rt webdav traffic to CONS3RT site'),
                        IpPermission(IpProtocol='tcp', FromPort=8443, ToPort=8443, CidrIp=cons3rt_site_cidr,
                                     Description='Allow blobstore traffic to CONS3RT site'),
                        IpPermission(IpProtocol='tcp', FromPort=remote_access_port, ToPort=remote_access_port,
                                     CidrIp=remote_access_internal_ip + '/32',
                                     Description='Allow remote access to the RA box')
                    ]
                    """ TODO add UserIdGroupPairs
                    nat_sg_egress_rules.append(
                        IpPermission(IpProtocol='-1', PrefixListId=nat_security_group_id,
                                     Description='All traffic to itself'),
                    """

                # Configure NAT security group rules
                self.configure_security_group_ingress(
                    security_group_id=nat_security_group_id,
                    desired_ingress_rules=nat_sg_ingress_rules
                )
                self.configure_security_group_egress(
                    security_group_id=nat_security_group_id,
                    desired_egress_rules=nat_sg_egress_rules
                )

                log.info('Launching a NAT instance for network: {n}'.format(n=name))
                nat_instance_id = self.launch_nat_instance_for_cons3rt(
                    name=name + '-nat',
                    nat_subnet_id=nat_subnet_id,
                    key_name=key_name,
                    nat_security_group_id=nat_security_group_id,
                    subnet_cidr=cidr,
                    region=region,
                    remote_access_internal_ip=remote_access_internal_ip,
                    remote_access_port=remote_access_port
                )

                # Append the NAT instance route for routable networks
                route_table_routes.append(
                    IpRoute(cidr='0.0.0.0/0', target=nat_instance_id)
                )
            except EC2UtilError as exc:
                msg = 'Problem creating additional external routing network resources for subnet with name [{n}] ' \
                      'in VPC ID: {v}'.format(n=name, v=vpc_id)
                raise EC2UtilError(msg) from exc
            log.info('NAT instance created successfully for network: {n}'.format(n=name))

        # For a NAT subnet, route Internet traffic to the Internet gateway
        if is_nat_subnet:
            route_table_routes.append(
                IpRoute(cidr='0.0.0.0/0', target=ig_id)
            )

        # Configure the route table rules
        self.configure_routes(
            route_table_id=route_table_id,
            desired_routes=route_table_routes
        )

        # Configure the internal security group rules
        self.configure_security_group_ingress(
            security_group_id=security_group_id,
            desired_ingress_rules=security_group_ingress_rules
        )
        self.configure_security_group_egress(
            security_group_id=security_group_id,
            desired_egress_rules=security_group_egress_rules
        )

        # Return a Cons3rtNetwork object containing the allocated network info
        return Cons3rtNetwork(
            name=name,
            vpc_id=vpc_id,
            cidr=cidr,
            availability_zone=availability_zone,
            subnet_id=subnet_id,
            route_table_id=route_table_id,
            security_group_id=security_group_id,
            routable=routable,
            nat_security_group_id=nat_security_group_id,
            nat_instance_id=nat_instance_id
        )


class Cons3rtNetwork(object):

    def __init__(self, name, vpc_id, cidr, availability_zone, subnet_id, route_table_id, security_group_id,
                 routable=False, nat_security_group_id=None, nat_instance_id=None):
        self.name = name
        self.vpc_id = vpc_id
        self.cidr = cidr
        self.availability_zone = availability_zone
        self.subnet_id = subnet_id
        self.route_table_id = route_table_id
        self.security_group_id = security_group_id
        self.routable = routable
        self.nat_security_group_id = nat_security_group_id
        self.nat_instance_id = nat_instance_id


class IpPermission(object):
    """

    IpProtocol: tcp , udp , icmp , icmpv6, -1 for all
    FromPort --> ToPort is a range of ports (not a source/destination port)

    """
    def __init__(self, IpProtocol, CidrIp=None, CidrIpv6=None, Description=None, PrefixListId=None, FromPort=None,
                 ToPort=None):
        self.IpProtocol = IpProtocol
        self.CidrIp = CidrIp
        self.CidrIpv6 = CidrIpv6
        self.Description = Description
        self.PrefixListId = PrefixListId
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

    def get_cidr_type(self):
        if self.cidr:
            return 'DestinationCidrBlock'
        elif self.cidr_ipv6:
            return 'DestinationIpv6CidrBlock'


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
        :param subnet_ids: (list) of subnet IDs in the VPC to attach
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
            return
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
                route_table_id = None

        # If not found, create a new route table
        route_table_id = self.create_route_table(route_table_name='{n}-rt'.format(n=self.name))

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

    def create_route_table(self, route_table_name=None):
        """Creates a new route table

        :return: (str) route table ID
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.create_route_table')
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
        """Associates the route table ID to the transit gateway attachment

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
            return
        for association in self.associations:
            if attachment_id == association['TransitGatewayAttachmentId']:
                return association['TransitGatewayRouteTableId']

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


def get_permissions_for_hostnames(hostname_list):
    """Get a list of IP permissions from hostname list

    :param hostname_list: (str) list of hostnames
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
            permissions_list.append(
                IpPermission(IpProtocol='-1', CidrIp=ip_address + '/32', Description=hostname)
            )
    return permissions_list


def merge_permissions_by_description(primary_permission_list, merge_permission_list):
    """Merges the "merge" permission list into the "primary" permission list, by keeping permissions with matching
    descriptions.  This allows an existing list of permissions to persist and append into the new list

    :param primary_permission_list: (list) IPPermission objects
    :param merge_permission_list: (list) IPPermission objects
    :return: (list) IPPermission objects
    """
    log = logging.getLogger(mod_logger + '.merge_permissions_by_description')
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


def get_aws_service_ips(regions=None, include_elastic_ips=False, ipv6=False):
    """Returns a list of AWS service IP addresses

    Ref: https://docs.aws.amazon.com/general/latest/gr/aws-ip-ranges.html#aws-ip-egress-control

    :param regions: (list) region IDs to include in the results (e.g. [us-gov-west-1, us-gov-east-1])
                           use the region 'GLOBAL' to include global non-region-specific ranges
    :param include_elastic_ips: (bool) Set True to include attachable EC2 elastic IPs in the results
    :param ipv6: (bool) Set True to return only IPv6 results, False for IPv4 only
    :return: (list) of IP addresses
    """
    log = logging.getLogger(mod_logger + '.get_aws_service_ips')
    matching_ip_ranges = []
    if ipv6:
        prefix_id = 'ipv6_prefixes'
    else:
        prefix_id = 'prefixes'
    try:
        ip_ranges = requests.get('https://ip-ranges.amazonaws.com/ip-ranges.json').json()[prefix_id]
    except Exception as exc:
        log.error('Problem retrieving the list of IP ranges from AWS{e}\n'.format(e=str(exc)))
        return matching_ip_ranges

    if ipv6:
        prefix_key = 'ipv6_prefix'
        log.info('Returning IPv6 results only')
    else:
        prefix_key = 'ip_prefix'
        log.info('Returning IPv4 results only')

    # Gets the list of 'AMAZON' prefixes, these are used for AWS services
    candidate_ip_ranges = []
    amazon_ips = []
    for ip_range in ip_ranges:
        if prefix_key not in ip_range.keys():
            continue
        if ip_range['service'] == 'AMAZON':
            amazon_ips.append(ip_range[prefix_key])
    log.info('Found {n} AMAZON IP prefixes'.format(n=str(len(amazon_ips))))

    # Exclude EC2 elastic IPs if specified
    if not include_elastic_ips:
        ec2_ips = [item[prefix_key] for item in ip_ranges if item['service'] == 'EC2']
        log.info('Excluding {n} EC2 elastic IP prefixes'.format(n=str(len(ec2_ips))))
        for ip in amazon_ips:
            if ip not in ec2_ips:
                candidate_ip_ranges.append(ip)
    else:
        log.info('Not excluding EC2 elastic IP addresses')
        candidate_ip_ranges = list(amazon_ips)
    log.info('Found {n} candidate IP address prefixes'.format(n=str(len(candidate_ip_ranges))))

    # If regions are not specified, return the candidate list
    if not regions:
        return candidate_ip_ranges

    # Filter results by region
    region_filtered_ip_ranges = []
    log.info('Filtering results by regions: {r}'.format(r=','.join(regions)))
    region_ips = []
    for region in regions:
        this_region_ips = [item[prefix_key] for item in ip_ranges if item['region'] == region]
        log.info('Found {n} IP ranges in region: {r}'.format(n=str(len(this_region_ips)), r=region))
        region_ips += this_region_ips
    log.info('Found {n} total IP ranges in regions: {r}'.format(n=str(len(region_ips)), r=','.join(regions)))
    for candidate_ip_range in candidate_ip_ranges:
        if candidate_ip_range in region_ips:
            region_filtered_ip_ranges.append(candidate_ip_range)
    log.info('Found {n} matching IP ranges in regions: {r}'.format(
        n=str(len(region_filtered_ip_ranges)), r=','.join(regions)))
    return region_filtered_ip_ranges


############################################################################
# Method for retrieving AWS Red Hat Update Server RHUI3 IP addresses
############################################################################


def get_aws_rhui3_ips(regions=None):
    """Returns the list of Red Hat RHUI3 IP addresses

    Note: GovCloud uses the US-based servers

    :param regions: (list) region IDs to include in the results (e.g. [us-gov-west-1, us-gov-east-1])
    :return: (list) of IP addresses
    """
    log = logging.getLogger(mod_logger + '.get_aws_rhui3_ips')

    if not regions:
        regions = global_regions
    else:
        for region in regions:
            if region in gov_regions:
                log.info('GovCloud region specified, returning only US-based RHUI3 servers...')
                regions = us_regions
                break

    log.info('Returning RHUI3 IP addresses in regions: {r}'.format(r=','.join(regions)))

    # Build the list of IPs
    rhui3_ips = []
    for region in regions:
        try:
            _, _, rhui3_region_ips = socket.gethostbyname_ex('rhui3.{r}.aws.ce.redhat.com'.format(r=region))
        except (socket.gaierror, socket.error, socket.herror) as exc:
            log.error('Problem retrieving RHUI3 IP address for region: {r}\n{e}'.format(r=region, e=str(exc)))
            continue
        if len(rhui3_region_ips) < 1:
            log.error('No RHUI3 IP addresses returned for region: {r}'.format(r=region))
            continue
        for rhui3_region_ip in rhui3_region_ips:
            if validate_ip_address(rhui3_region_ip):
                log.info('Found RHUI3 IP address for region {r}: {i}'.format(r=region, i=rhui3_region_ip))
                rhui3_ips.append(rhui3_region_ip)
            else:
                log.error('Invalid RHUI3 IP address returned for region {r}: {i}'.format(r=region, i=rhui3_region_ip))
    return rhui3_ips


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
    :param instance_id: (str) ID of the snapshot to retrieve
    :return: (dict) data about the snapshot (see boto3 docs)
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


############################################################################
# Methods for retrieving EC2 Snapshots
############################################################################


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
    if 'Snapshots' not in response:
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


def list_images(client, owner_id):
    """Gets a list of EC2 snapshots in this account/region

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
    if 'Images' not in response:
        msg = 'Images not found in response: {r}'.format(r=str(response))
        raise EC2UtilError(msg)
    if len(response['Images']) != 1:
        msg = 'Expected to find 1 image, found {n} in response: {r}'.format(
            n=str(len(response['Images'])), r=str(response))
        raise EC2UtilError(msg)
    return response['Images'][0]


############################################################################
# Methods for retrieving EC2 Volumes
############################################################################


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
    """Gets a list of EC2 volumes in this account/region

    :param client: boto3.client object
    :return: (list)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.list_volumes')
    log.info('Getting a list of EC2 volumes...')
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
            msg = 'Problem querying for EC2 volumes'
            raise EC2UtilError(msg) from exc
        if 'Volumes' not in response.keys():
            log.warning('Volumes not found in response: {r}'.format(r=str(response.keys())))
            return volumes
        if 'NextToken' not in response.keys():
            next_query = False
        else:
            continuation_token = response['NextToken']
        volumes += response['Volumes']
    log.info('Found {n} EC2 volumes'.format(n=str(len(volumes))))
    return volumes


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
    if 'Volumes' not in response:
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
