"""Module: elbv2

This module provides utilities for interacting with the AWS
EC2 API, including networking and security group
configurations.

"""
import logging

from botocore.client import ClientError

from .awsutil import get_boto3_client
from .bash import validate_ip_address
from .ec2util import EC2Util
from .exceptions import EC2UtilError, ElbUtilError
from .logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.elbv2util'

# Required ELB config properties
required_props = [
    'Name',
    'VpcId',
    'Subnets',
    'SecurityGroups',
    'CertificateArn',
    'TargetIpAddressList'
]

# Optional props with default values, overwritten if provided
optional_props = {
}


class ElbUtil(object):
    """Utility for interacting with the AWS ELBv2 SDK
    """
    def __init__(self, region_name=None, aws_access_key_id=None, aws_secret_access_key=None):
        self.cls_logger = mod_logger + '.ElbUtil'
        try:
            self.client = get_elb_v2_client(region_name=region_name, aws_access_key_id=aws_access_key_id,
                                            aws_secret_access_key=aws_secret_access_key)
        except ClientError as exc:
            msg = 'Unable to create an EC2 client'
            raise ElbUtilError(msg) from exc
        self.region = self.client.meta.region_name

    def create_elb(self, name, subnets, security_groups, scheme='internal', load_balancer_type='application',
                   ip_address_type='ipv4'):
        """Creates an ELB using the provided

        Not supported:
        CustomerOwnedIpv4Pool
        Tags

        :param name: (str) Name of the ELB
        :param subnets: (list) of subnet IDs
        :param security_groups: (list) of security group IDs
        :param scheme: (str) internet-facing | internal
        :param load_balancer_type: (str) 'application'|'network'
        :param ip_address_type: (str) 'ipv4'|'dualstack'
        :return: (dict) see boto3 docs
        :raises: ElbUtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_elb')
        log.info('Attempting to create AWS ELB with name: {n}'.format(n=name))
        try:
            response = self.client.create_load_balancer(
                Name=name,
                Subnets=subnets,
                SecurityGroups=security_groups,
                Scheme=scheme,
                Type=load_balancer_type,
                IpAddressType=ip_address_type,
            )
        except ClientError as exc:
            msg = 'There was a problem launching the ELB instance with name: {n}\n{e}'.format(n=name, e=str(exc))
            raise ElbUtilError(msg) from exc
        if 'LoadBalancers' not in response.keys():
            msg = 'LoadBalancers not found in response: {r}'.format(r=str(response))
            raise ElbUtilError(msg)
        if len(response['LoadBalancers']) != 1:
            msg = 'Expected 1 load balancer in response, found: {n}'.format(n=str(len(response['LoadBalancers'])))
            raise ElbUtilError(msg)
        load_balancer = response['LoadBalancers'][0]
        log.info('Created ELB ARN: {i}'.format(i=load_balancer['LoadBalancerArn']))
        return load_balancer

    def create_https_listener_with_forward(self, load_balancer_arn, target_group_arn, certificate_arn,
                                           ssl_policy='ELBSecurityPolicy-TLS-1-2-2017-01'):
        """Creates an HTTPS listener that forwards to a target group

        Not supported:
        AlpnPolicy
        Tags

        :param load_balancer_arn: (str) ARN of the load balancer
        :param target_group_arn: (str) ARN of the target group
        :param certificate_arn: (str) ARN of the SSL certificate in ACM
        :param ssl_policy: (str) SSL policy to apply to the load balancer
        :return: (dict) see boto3 docs
        :raises: ElbUtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_https_listener_with_forward')
        log.info('Attempting to create listener for load balancer: {n}'.format(n=load_balancer_arn))
        try:
            response = self.client.create_listener(
                LoadBalancerArn=load_balancer_arn,
                Protocol='HTTPS',
                Port=443,
                SslPolicy=ssl_policy,
                Certificates=[
                    {
                        'CertificateArn': certificate_arn
                    },
                ],
                DefaultActions=[
                    {
                        'Type': 'forward',
                        'TargetGroupArn': target_group_arn,
                        'Order': 1,
                        'ForwardConfig': {
                            'TargetGroups': [
                                {
                                    'TargetGroupArn': target_group_arn,
                                    'Weight': 999
                                },
                            ]
                        }
                    },
                ]
            )
        except ClientError as exc:
            msg = 'There was a problem creating the ELB listener for load balancer: {n}\n{e}'.format(
                n=load_balancer_arn, e=str(exc))
            raise ElbUtilError(msg) from exc
        if 'Listeners' not in response.keys():
            msg = 'Listeners not found in response: {r}'.format(r=str(response))
            raise ElbUtilError(msg)
        if len(response['Listeners']) != 1:
            msg = 'Expected 1 listener in response, found: {n}'.format(n=str(len(response['LoadBalancers'])))
            raise ElbUtilError(msg)
        listener = response['Listeners'][0]
        if 'ListenerArn' not in listener:
            msg = 'ListenerArn not found in listener data: {d}'.format(d=str(listener))
            raise ElbUtilError(msg)
        log.info('Created Listener ARN: {i}'.format(i=listener['ListenerArn']))
        return listener

    def create_vpc_ipv4_https_elb(self, name, vpc_id, subnets, security_groups, certificate_arn, ip_address_list):
        """Creates an HTTPS IPv4-based ELB and a corresponding target group and listener

        :param name: (str) name of the ELB
        :param vpc_id: (str) ID of the VPC
        :param subnets: (list) of subnet IDs
        :param security_groups: (list) of security group IDs
        :param certificate_arn: (str) ARN of the SSL certificate in ACM
        :param ip_address_list: (list) list of (str) IP addresses
        :return: (dict) ELB info (see boto3 docs)
        :raises: ElbUtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_vpc_ipv4_https_elb')
        log.info('Attempting to create an HTTPS IPv4-based ELB [{n}] with listener in VPC ID: {v}'.format(
            n=name, v=vpc_id))

        # Create the target group
        target_group = self.create_https_ip_target_group(
            target_group_name=name + '-tg',
            vpc_id=vpc_id,
            ip_address_list=ip_address_list
        )

        # Create the ELB
        elb = self.create_elb(name=name, subnets=subnets, security_groups=security_groups)

        # Create the listener
        listener = self.create_https_listener_with_forward(
            load_balancer_arn=elb['LoadBalancerArn'],
            target_group_arn=target_group['TargetGroupArn'],
            certificate_arn=certificate_arn
        )
        log.info('Created listener: {n}'.format(n=listener['ListenerArn']))
        return elb

    def describe_all_target_groups(self):
        """Returns a list of the existing target groups

        :return: (dict) see boto3 docs
        :raises: ElbUtilError
        """
        log = logging.getLogger(self.cls_logger + '.describe_all_target_groups')
        log.info('Describing target groups...')
        try:
            response = self.client.describe_target_groups()
        except ClientError as exc:
            msg = 'There was a problem describing target groups\n{e}'.format(e=str(exc))
            raise ElbUtilError(msg) from exc
        if 'TargetGroups' not in response.keys():
            msg = 'TargetGroups not found in response: {r}'.format(r=str(response))
            raise ElbUtilError(msg)
        log.info('Found [{n}] target groups'.format(n=str(len(response['TargetGroups']))))
        return response['TargetGroups']

    def describe_target_health(self, target_group_arn):
        """Return a list of targets and their health info in the target group

        :param target_group_arn: (str) target group ARN
        :return: (dict) see boto3 docs
        :raises: ElbUtilError
        """
        log = logging.getLogger(self.cls_logger + '.describe_target_health')
        log.info('Getting target heath in target group: {g}'.format(g=target_group_arn))
        try:
            response = self.client.describe_target_health(TargetGroupArn=target_group_arn)
        except ClientError as exc:
            msg = 'There was a problem describing target health for target group: {n}\n{e}'.format(
                n=target_group_arn, e=str(exc))
            raise ElbUtilError(msg) from exc
        if 'TargetHealthDescriptions' not in response.keys():
            msg = 'TargetHealthDescriptions not found in response: {r}'.format(r=str(response))
            raise ElbUtilError(msg)
        log.info('Found [{n}] targets in target group: {g}'.format(
            n=str(len(response['TargetHealthDescriptions'])), g=target_group_arn))
        return response['TargetHealthDescriptions']

    def create_https_ip_target_group(self, target_group_name, vpc_id, ip_address_list):
        """Creates a target group

        :param target_group_name: (str) name of the target group
        :param vpc_id: (str) ID of the VPC
        :param ip_address_list: (list) list of (str) IP addresses
        :return: (dict) see boto3 docs
        :raises: ElbUtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_https_ip_target_group')

        # Check for existing target groups
        existing_target_groups = self.find_vpc_target_groups_for_ips(vpc_id=vpc_id, ip_address_list=ip_address_list)
        for existing_target_group in existing_target_groups:
            if existing_target_group['Protocol'] != 'HTTPS':
                continue
            if existing_target_group['Port'] != 443:
                continue
            if existing_target_group['TargetType'] != 'ip':
                continue
            if existing_target_group['TargetGroupName'] != target_group_name:
                continue
            log.info('Found existing target group with matching config: {g}'.format(g=target_group_name))
            return existing_target_group

        log.info('Creating HTTPS IP-based target group with name: {n}'.format(n=target_group_name))
        try:
            response = self.client.create_target_group(
                Name=target_group_name,
                Protocol='HTTPS',
                Port=443,
                VpcId=vpc_id,
                HealthCheckProtocol='HTTPS',
                HealthCheckPort='443',
                TargetType='ip'
            )
        except ClientError as exc:
            msg = 'Problem creating target group [{n}] in VPC ID: {v}\n{e}'.format(
                n=target_group_name, v=vpc_id, e=str(exc))
            raise ElbUtilError(msg) from exc
        if 'TargetGroups' not in response.keys():
            msg = 'TargetGroups not found in response: {r}'.format(r=str(response))
            raise ElbUtilError(msg)
        if len(response['TargetGroups']) != 1:
            msg = 'Expected 1 target group in response, found: {n}'.format(n=str(len(response['TargetGroups'])))
            raise ElbUtilError(msg)
        target_group = response['TargetGroups'][0]
        if 'TargetGroupArn' not in target_group.keys():
            msg = 'TargetGroupArn not found in target group data: {d}'.format(d=str(target_group))
            raise ElbUtilError(msg)
        log.info('Created target group in VPC ID [{v}]: {i}'.format(v=vpc_id, i=target_group['TargetGroupArn']))

        # Register the IP address targets
        self.register_ip_targets(target_group_arn=target_group['TargetGroupArn'], ip_address_list=ip_address_list)
        return target_group

    def register_ip_targets(self, target_group_arn, ip_address_list):
        """Register IP-based targets to the provided target group

        :param target_group_arn: (str) target group ARN
        :param ip_address_list: (list) list of (str) IP addresses
        :return: None
        :raises: ElbUtilError
        """
        log = logging.getLogger(self.cls_logger + '.register_ip_targets')
        if not isinstance(ip_address_list, list):
            msg = 'ip_address_list expected list, found: {t}'.format(t=ip_address_list.__class__.__name__)
            raise ElbUtilError(msg)
        targets = []
        for ip_address in ip_address_list:
            if not validate_ip_address(ip_address):
                msg = 'Provided IP address is not valid: {i}'.format(i=ip_address)
                raise ElbUtilError(msg)
            targets.append({'Id': ip_address, 'Port': 443})
        log.info('Registering targets [{t}] to target group: {g}'.format(
            t=','.join(ip_address_list), g=target_group_arn))
        try:
            self.client.register_targets(
                TargetGroupArn=target_group_arn,
                Targets=targets
            )
        except ClientError as exc:
            msg = 'Problem registering targets [{t}] to target group: {g}\n{e}'.format(
                t=','.join(ip_address_list), g=target_group_arn, e=str(exc))
            raise ElbUtilError(msg) from exc

    def find_vpc_target_groups_for_ips(self, vpc_id, ip_address_list):
        """Returns a Target Group in the provided VPC matching the provided IP address list, or None if not found

        :param vpc_id: (str) ID of the VPC
        :param ip_address_list: (list) of the IP addresses
        :return: (dict) see boto3 docs
        :raises: ElbUtilError
        """
        log = logging.getLogger(self.cls_logger + '.find_vpc_target_groups_for_ips')
        for ip_address in ip_address_list:
            if not validate_ip_address(ip_address):
                msg = 'Provided IP address is not valid: {i}'.format(i=ip_address)
                raise ElbUtilError(msg)
        target_groups = self.describe_all_target_groups()
        vpc_target_groups = []
        for target_group in target_groups:
            if 'VpcId' not in target_group:
                log.warning('VpcId not found in target group data: {d}'.format(d=str(target_group)))
                continue
            if 'TargetGroupArn' not in target_group:
                log.warning('TargetGroupArn not found in target group data: {d}'.format(d=str(target_group)))
                continue
            if 'TargetGroupName' not in target_group:
                log.warning('TargetGroupName not found in target group data: {d}'.format(d=str(target_group)))
                continue
            if vpc_id == target_group['VpcId']:
                vpc_target_groups.append(target_group)
        matching_target_groups = []
        for vpc_target_group in vpc_target_groups:
            targets = self.describe_target_health(target_group_arn=vpc_target_group['TargetGroupArn'])
            found_list = []
            for ip_address in ip_address_list:
                ip_found = False
                for target in targets:
                    if 'Target' not in target:
                        continue
                    if 'Id' not in target['Target']:
                        continue
                    if target['Target']['Id'] == ip_address:
                        ip_found = True
                found_list.append(ip_found)
            if all(found_list) and (len(found_list) == len(targets)):
                log.info('Found matching target group in VPC [{v}]: {t}'.format(
                    v=vpc_id, t=vpc_target_group['TargetGroupArn']))
                matching_target_groups.append(vpc_target_group)
        log.info('Matching target group in VPC [{v}] not found for targets: {t}'.format(
            v=vpc_id, t=','.join(ip_address_list)))
        return matching_target_groups


def get_elb_v2_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
    """Gets an EC2 client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    return get_boto3_client(service='elbv2', region_name=region_name, aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)


def validate_elb_properties(elb_config_props):
    """Returns True if the ELB config properties are found to be valid

    :param elb_config_props: (dict) key-value pairs read in from the ELB config properties file
    :return: (dict) ELB config properties
    :raises: ElbUtilError
    """
    log = logging.getLogger(mod_logger + '.validate_elb_properties')
    for required_prop in required_props:
        if required_prop not in elb_config_props.keys():
            msg = 'Required property missing from ELB config file: {p}'.format(p=required_prop)
            raise ElbUtilError(msg)
    for optional_prop in optional_props.keys():
        if optional_prop not in elb_config_props.keys():
            log.info('Adding default value for [{k}]: {v}'.format(k=optional_prop, v=optional_props[optional_prop]))
            elb_config_props[optional_prop] = optional_props[optional_prop]
        else:
            log.info('Found ELB config value for optional prop [{k}]: {v}'.format(
                k=optional_prop, v=elb_config_props[optional_prop]))

    # Convert the subnet IDs from a string to a list
    elb_config_props['Subnets'] = elb_config_props['Subnets'].split(',')
    elb_config_props['SecurityGroups'] = elb_config_props['SecurityGroups'].split(',')
    elb_config_props['TargetIpAddressList'] = elb_config_props['TargetIpAddressList'].split(',')

    # Ensure at least 2 subnet IDs provided
    if len(elb_config_props['Subnets']) < 2:
        msg = 'At least 2 subnet IDs are required, found {n}: {s}'.format(
            n=str(len(elb_config_props['Subnets'])), s=','.join(elb_config_props['Subnets']))
        raise ElbUtilError(msg)

    # Ensure the IP addresses are valid
    for ip_address in elb_config_props['TargetIpAddressList']:
        if not validate_ip_address(ip_address):
            msg = 'Found invalid IP address in properties: {i}'.format(i=ip_address)
            raise ElbUtilError(msg)

    try:
        # Ensure the subnet IDs are in the provided VPC ID
        ec2 = EC2Util(skip_is_aws=True)
        if not ec2.verify_subnets_in_vpc(vpc_id=elb_config_props['VpcId'], subnet_list=elb_config_props['Subnets']):
            msg = 'One or more subnets [{s}] not found in VPC ID: {v}'.format(
                s=','.join(elb_config_props['Subnets']), v=elb_config_props['VpcId'])
            raise ElbUtilError(msg)

        # Ensure there are at least 2 different availability zones represented in the provided subnet IDs
        if not ec2.verify_subnets_affinity(subnet_id_list=elb_config_props['Subnets'], num_availability_zones=2):
            msg = 'Subnet IDs must be in at least 2 availability zones'
            raise ElbUtilError(msg)

        # Ensure the security groups are in the provided VPC ID
        if not ec2.verify_security_groups_in_vpc(
                vpc_id=elb_config_props['VpcId'], security_group_id_list=elb_config_props['SecurityGroups']):
            msg = 'One or more security groups [{s}] not found in VPC ID: {v}'.format(
                s=','.join(elb_config_props['SecurityGroups']), v=elb_config_props['VpcId'])
            raise ElbUtilError(msg)
    except EC2UtilError as exc:
        msg = 'Problem found verifying properties with EC2Util'
        raise ElbUtilError(msg) from exc

    for elb_config_prop in elb_config_props.keys():
        log.info('Using config prop: {k}={v}'.format(k=elb_config_prop, v=elb_config_props[elb_config_prop]))
    return elb_config_props

