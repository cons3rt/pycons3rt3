"""Module: ec2util

This module provides utilities for interacting with the AWS
EC2 API, including networking and security group
configurations.

"""
import logging
import os
import time
import traceback

import boto3
from botocore.client import ClientError

from .bash import get_ip_addresses
from .logify import Logify
from .osutil import get_os
from .aws_metadata import is_aws, get_instance_id, get_vpc_id_from_mac_address
from .exceptions import AWSAPIError, AwsTransitGatewayError, EC2UtilError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.ec2util'


class EC2Util(object):
    """Utility for interacting with the AWS API
    """
    def __init__(self, region_name=None, aws_access_key_id=None, aws_secret_access_key=None):
        self.cls_logger = mod_logger + '.EC2Util'
        try:
            self.client = get_ec2_client(region_name=region_name, aws_access_key_id=aws_access_key_id,
                                         aws_secret_access_key=aws_secret_access_key)
        except ClientError as exc:
            msg = 'Unable to create an EC2 client'
            raise EC2UtilError(msg) from exc
        if get_os() != 'Darwin':
            self.is_aws = is_aws()
        else:
            self.is_aws = False
        if self.is_aws:
            self.instance_id = get_instance_id()
        else:
            self.instance_id = None
        if self.instance_id and self.is_aws:
            self.vpc_id = get_vpc_id_from_mac_address()
        else:
            self.vpc_id = None

    def get_vpc_id(self):
        """Gets the VPC ID for this EC2 instance

        :return: String instance ID or None
        """
        log = logging.getLogger(self.cls_logger + '.get_vpc_id')

        # Exit if not running on AWS
        if not self.is_aws:
            log.info('This machine is not running in AWS, exiting...')
            return

        if self.instance_id is None:
            log.error('Unable to get the Instance ID for this machine')
            return
        log.info('Found Instance ID: {i}'.format(i=self.instance_id))

        log.info('Querying AWS to get the VPC ID...')
        try:
            response = self.client.describe_instances(
                    DryRun=False,
                    InstanceIds=[self.instance_id])
        except ClientError as exc:
            log.error('Unable to query AWS to get info for instance {i}\n{e}'.format(
                    i=self.instance_id, e=str(exc)))
            return

        # Get the VPC ID from the response
        try:
            vpc_id = response['Reservations'][0]['Instances'][0]['VpcId']
        except KeyError:
            log.error('Unable to get VPC ID from response: {r}'.format(r=response))
            return
        log.info('Found VPC ID: {v}'.format(v=vpc_id))
        return vpc_id

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
        if self.instance_id is None:
            msg = 'Instance ID not found for this machine'
            log.error(msg)
            raise OSError(msg)
        log.info('Found instance ID: {i}'.format(i=self.instance_id))

        log.debug('Querying EC2 instances...')
        try:
            response = self.client.describe_instances(
                    DryRun=False,
                    InstanceIds=[self.instance_id]
            )
        except ClientError as exc:
            msg = 'Unable to query EC2 for instances'
            log.error(msg)
            raise AWSAPIError(msg) from exc
        log.debug('Found instance info: {r}'.format(r=response))

        # Find the ENI ID
        log.info('Looking for the ENI ID to alias...')
        eni_id = None
        try:
            for reservation in response['Reservations']:
                for instance in reservation['Instances']:
                    if instance['InstanceId'] == self.instance_id:
                        for network_interface in instance['NetworkInterfaces']:
                            if network_interface['Attachment']['DeviceIndex'] == interface:
                                eni_id = network_interface['NetworkInterfaceId']
        except KeyError as exc:
            msg = 'ENI ID not found in AWS response for interface: {i}'.format(i=interface)
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

    def get_elastic_ips(self):
        """Returns the elastic IP info for this instance any are
        attached

        :return: (dict) Info about the Elastic IPs
        :raises AWSAPIError
        """
        log = logging.getLogger(self.cls_logger + '.get_elastic_ips')
        instance_id = get_instance_id()
        if instance_id is None:
            log.error('Unable to get the Instance ID for this machine')
            return
        log.info('Found Instance ID: {i}'.format(i=instance_id))

        log.info('Querying AWS for info about instance ID {i}...'.format(i=instance_id))
        try:
            instance_info = self.client.describe_instances(DryRun=False, InstanceIds=[instance_id])
        except ClientError as exc:
            msg = 'Unable to query AWS to get info for instance {i}'.format(i=instance_id)
            raise AWSAPIError(msg) from exc

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
            raise AWSAPIError(msg) from exc
        if not address_info:
            msg = 'No address info return for Public IPs: {p}'.format(p=public_ips)
            log.error(msg)
            raise AWSAPIError(msg)
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
            msg = 'Unable to create Security Group <{n}> in VPC: {v}'.format(n=name, v=vpc_id)
            log.error(msg)
            raise AWSAPIError(msg) from exc
        else:
            log.info('Successfully created Security Group <{n}> in VPC: {v}'.format(n=name, v=vpc_id))
        return response['GroupId']

    def list_security_groups_in_vpc(self, vpc_id=None):
        """Lists security groups in the VPC.  If vpc_id is not provided, use self.vpc_id

        :param vpc_id: (str) VPC ID to list security groups for
        :return: (list) Security Group info
        :raises: AWSAPIError, EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.list_security_groups_in_vpc')
        if vpc_id is None and self.vpc_id is not None:
            vpc_id = self.vpc_id
        else:
            msg = 'Unable to determine VPC ID to use to create the Security Group'
            log.error(msg)
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
            security_groups = self.client.describe_security_groups(DryRun=False, Filters=filters)
        except ClientError as exc:
            msg = 'Unable to query AWS for a list of security groups in VPC ID: {v}'.format(
                v=vpc_id)
            raise AWSAPIError(msg) from exc
        return security_groups

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

        log.info('Configuring Security Group ID {g}...'.format(g=security_group_id))

        try:
            security_group_info = self.client.describe_security_groups(DryRun=False, GroupIds=[security_group_id])
        except ClientError as exc:
            msg = 'Unable to query AWS for Security Group ID: {g}'.format(g=security_group_id)
            raise AWSAPIError(msg) from exc
        try:
            existing_egress_rules = security_group_info['SecurityGroups'][0]['IpPermissionsEgress']
        except KeyError as exc:
            msg = 'Unable to get list of egress rules for Security Group ID: {g}'.format(
                    g=security_group_id)
            raise AWSAPIError(msg) from exc

        # Parse permissions into comparable IpPermissions objects
        existing_ip_perms = parse_ip_permissions(existing_egress_rules)

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

        log.info('Configuring Security Group ID {g}...'.format(g=security_group_id))
        try:
            security_group_info = self.client.describe_security_groups(DryRun=False, GroupIds=[security_group_id])
        except ClientError as exc:
            msg = 'Unable to query AWS for Security Group ID: {g}'.format(g=security_group_id)
            raise AWSAPIError(msg) from exc
        try:
            existing_ingress_rules = security_group_info['SecurityGroups'][0]['IpPermissions']
        except KeyError as exc:
            msg = 'Unable to get list of ingress rules for Security Group ID: {g}'.format(
                g=security_group_id)
            raise AWSAPIError(msg) from exc

        # Parse permissions into comparable IpPermissions objects
        existing_ip_perms = parse_ip_permissions(existing_ingress_rules)

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

    def launch_instance(self, ami_id, key_name, subnet_id, security_group_id=None, security_group_list=None,
                        user_data_script_path=None, instance_type='t2.small', root_device_name='/dev/xvda'):
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
        :param root_device_name: (str) The device name for the root volume
        :return:
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
                'DeviceName': root_device_name,
                'Ebs': {
                    'VolumeSize': 100,
                    'DeleteOnTermination': True
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

    def get_ec2_instances(self):
        """Describes the EC2 instances

        :return: dict containing EC2 instance data
        :raises: EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.get_ec2_instances')
        log.info('Describing EC2 instances...')
        try:
            response = self.client.describe_instances()
        except ClientError as exc:
            msg = 'There was a problem describing EC2 instances'
            raise EC2UtilError(msg) from exc
        return response

    def get_ebs_volumes(self):
        """Describes the EBS volumes

        :return: dict containing EBS volume data
        :raises EC2UtilError
        """
        log = logging.getLogger(self.cls_logger + '.get_ebs_volumes')
        log.info('Describing EBS volumes...')
        try:
            response = self.client.describe_volumes()
        except ClientError as exc:
            msg = 'There was a problem describing EBS volumes'
            raise EC2UtilError(msg) from exc
        return response

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
        return response

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
        :return: (id) of the VPC or None if not found
        """
        log = logging.getLogger(self.cls_logger + '.get_vpc_id_by_name')
        log.info('Getting a list of VPCS...')
        try:
            vpcs = self.get_vpcs()
        except EC2UtilError as exc:
            raise EC2UtilError('Problem listing VPCs') from exc

        # Ensure VPCs were found
        if 'Vpcs' not in vpcs.keys():
            log.info('No VPCs found')
            return

        # Check eac VPC for matching name
        log.info('Found [{n}] VPCs'.format(n=str(len(vpcs['Vpcs']))))
        for vpc in vpcs['Vpcs']:
            if 'VpcId' not in vpc.keys():
                continue
            if 'Tags' not in vpc.keys():
                continue
            for tag in vpc['Tags']:
                if tag['Key'] == 'Name' and tag['Value'] == vpc_name:
                    log.info('Found VPC with name [{n}] has ID: {i}'.format(n=vpc_name, i=vpc['VpcId']))
                    return vpc['VpcId']
        log.info('VPC with name {n} not found'.format(n=vpc_name))

    def create_vpc(self, vpc_name, cidr_block, amazon_ipv6_cidr=False, instance_tenancy='default', dry_run=False):
        """Creates a VPC with the provided name

        :param vpc_name: (str) desired VPC name
        :param cidr_block: (str) desired CIDR block for the VPC
        :param instance_tenancy: (str) default or dedicated
        :param amazon_ipv6_cidr: (bool) Set true to request an Amazon IPv6 CIDR block
        :param dry_run: (bool) Set true to dry run the call
        :return: (str) VPC ID
        """
        log = logging.getLogger(self.cls_logger + '.create_vpc')

        # Check for an existing VPC with the desired name
        try:
            vpc_id = self.get_vpc_id_by_name(vpc_name=vpc_name)
        except EC2UtilError as exc:
            raise EC2UtilError('Problem checking for existing VPCs') from exc
        if vpc_id:
            log.info('Found existing VPC named {n} with ID: {i}'.format(n=vpc_name, i=vpc_id))
            return vpc_id

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
            raise EC2UtilError('VpcId data not found in{ {d}'.format(d=str(response['Vpc'])))
        vpc_id = response['Vpc']['VpcId']
        log.info('Created new VPC with ID: {i}'.format(i=vpc_id))

        # Apply the name tag
        try:
            self.client.create_tags(
                DryRun=False,
                Resources=[
                    vpc_id
                ],
                Tags=[
                    {
                        'Key': 'Name',
                        'Value': vpc_name
                    }
                ]
            )
        except ClientError as exc:
            raise EC2UtilError('Problem adding tags to set the name of VPC ID: {i}'.format(i=vpc_id)) from exc
        log.info('Successfully created VPC name {n} with ID: {n}'.format(n=vpc_name, i=vpc_id))
        return vpc_id

    def create_usable_vpc(self, vpc_name, cidr_block):
        """Creates a VPC with a subnet that routes to an Internet Gateway, and default Network ACL and routes

        :param vpc_name: (str) name of the VPC
        :param cidr_block: (str) desired CIDR block
        :return: (str) ID of the VPC that was created or configured
        """
        log = logging.getLogger(self.cls_logger + '.create_usable_vpc')

        # Create a VPC
        try:
            vpc_id = self.create_vpc(vpc_name=vpc_name, cidr_block=cidr_block)
        except EC2UtilError as exc:
            raise EC2UtilError('Problem creating a VPC') from exc
        log.info('Created VPC ID: {i]'.format(i=vpc_id))

        # Create an Internet Gateway
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

        try:
            self.client.attach_internet_gateway(
                DryRun=False,
                InternetGatewayId=ig_id,
                VpcId=vpc_id
            )
        except ClientError as exc:
            raise EC2UtilError('Problem attaching Internet gateway {i} to VPC {v}'.format(i=ig_id, v=vpc_id)) from exc
        log.info('Successfully attach Internet gateway {i} to VPC: {v}'.format(i=ig_id, v=vpc_id))


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
                    '{c} associations, and {p} propagations'.format(
            s=self.state, t=self.id, n=str(len(self.vpc_attachments)), r=str(len(self.route_tables)),
            c=str(len(self.associations)), p=str(len(self.propagations))
        )
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

    def delete_transit_gateway(self):
        """Deletes this transit gateway

        :return: (dict) into about the deleted transit gateway (see boto3 docs)
        :raises: AwsTransitGatewayError
        """
        log = logging.getLogger(self.cls_logger + '.delete_transit_gateway')
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
        log.info('Disassociating route table ID {r} from attachment: {a}'.format(r=route_table_id, a=attachment_id))
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
        log.info('Disabling route propagation route route table (r) to attachment: {a}'.format(
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
        parsed_routes =  parse_transit_gateway_routes(
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


def get_ec2_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None):
    """Gets an EC2 client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    log = logging.getLogger(mod_logger + '.get_ec2_client')
    # Connect to EC2 API
    try:
        client = boto3.client('ec2', region_name=region_name, aws_access_key_id=aws_access_key_id,
                              aws_secret_access_key=aws_secret_access_key)
    except ClientError as exc:
        msg = 'There was a problem connecting to EC2, please check AWS CLI and boto configuration, ensure ' \
              'credentials and region are set appropriately.'
        log.error(msg)
        raise AWSAPIError(msg) from exc
    else:
        log.debug('Successfully created an EC2 client')
        return client


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
