"""Module: route53util

This module provides utilities for interacting with the AWS
route53 API

"""
import datetime
import logging

from botocore.client import ClientError

from .awsutil import get_boto3_client
from .ec2util import EC2Util
from .exceptions import EC2UtilError, Route53UtilError
from .logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.route53util'


class Route53Util(object):
    """Utility for interacting with the AWS Route53
    """
    def __init__(self, domain, private=False, vpc_id=None, vpc_region=None,
                 region_name=None, aws_access_key_id=None, aws_secret_access_key=None):
        self.cls_logger = mod_logger + '.Route53Util'
        self.domain = domain + '.'
        self.private = private
        self.vpc_id = vpc_id
        self.vpc_region = vpc_region
        self.hosted_zone_id = None
        if self.vpc_id:
            self.private = True
        try:
            self.client = get_route53_client(region_name=region_name, aws_access_key_id=aws_access_key_id,
                                             aws_secret_access_key=aws_secret_access_key)
        except ClientError as exc:
            msg = 'Unable to create a Route53 client'
            raise Route53UtilError(msg) from exc
        self.region = self.client.meta.region_name
        self.dns_records = []

    def add_record(self, record_type, name, value, time_to_live=300):
        """Returns a formatted simple record for adding to Route53

        :param record_type: (str) type of record (see boto3 docs)
        :param name: (str) name of the record to create (e.g. www)
        :param value: (str) value for the record (e.g. IP address)
        :param time_to_live: (int) time to live in seconds for the record
        :return: (dict) record set (see boto3 docs)
        :raises: Route53UtilError
        """
        log = logging.getLogger(self.cls_logger + '.add_record')
        if name == '':
            name = self.domain
        elif name == '.':
            name = self.domain
        elif self.domain not in name:
            name = name + '.' + self.domain
        log.info('Adding record: [ {t} | {n} | {v} | {x} ]'.format(t=record_type, n=name, v=value, x=str(time_to_live)))
        self.dns_records.append(
            create_simple_change_record(
                record_type=record_type, name=name, value=value, action='UPSERT', time_to_live=time_to_live
            )
        )

    def create_hosted_zone(self):
        """Creates a hosted zone

        :return: (dict) host zone (see boto3 docs)
        :raises: Route53UtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_hosted_zone')

        log.info('Getting existing hosted zones')

        # Ensure private params are provided
        if self.private:
            if not all([self.vpc_id, self.region]):
                msg = 'Cannot create private zone without both VPC ID and region'
                raise Route53UtilError(msg)

        # Check for existing hosted zones
        hosted_zone = self.get_existing_public_zone()
        if not hosted_zone:
            hosted_zone = self.get_existing_private_zone()
        if hosted_zone:
            self.hosted_zone_id = hosted_zone['Id']
            log.info('Found existing hosted zone ID: {i}'.format(i=self.hosted_zone_id))
            if self.private:
                enable_vpc_private_dns(vpc_id=self.vpc_id)
            return hosted_zone

        # Create hosted zone
        try:
            if self.private:
                hosted_zone = create_private_hosted_zone(
                    client=self.client, domain=self.domain, vpc_id=self.vpc_id, vpc_region=self.vpc_region
                )
                enable_vpc_private_dns(vpc_id=self.vpc_id)
            else:
                hosted_zone = create_public_hosted_zone(
                    client=self.client, domain=self.domain
                )
        except Route53UtilError as exc:
            msg = 'Problem creating hosted zone: {d}'.format(d=self.domain)
            raise Route53UtilError(msg) from exc
        self.hosted_zone_id = hosted_zone['Id']
        return hosted_zone

    def delete_record(self, record_type, name, value):
        """Returns a formatted simple record for adding to Route53

        :param record_type: (str) type of record (see boto3 docs)
        :param name: (str) name of the record to create (e.g. www)
        :param value: (str) value for the record (e.g. IP address)
        :return: (dict) record set (see boto3 docs)
        :raises: Route53UtilError
        """
        log = logging.getLogger(self.cls_logger + '.delete_record')
        if self.domain not in name:
            name = name + '.' + self.domain
        log.info('Deleting record: [ {t} | {n} | {v} ]'.format(t=record_type, n=name, v=value))
        delete_record = create_simple_change_record(record_type=record_type, name=name, value=value, action='DELETE')
        if not self.hosted_zone_id:
            msg = 'Must create a hosted zone first, there is no hosted zone ID to delete from!'
            raise Route53UtilError(msg)
        change_record_sets(
            client=self.client,
            hosted_zone_id=self.hosted_zone_id,
            changes=[delete_record]
        )

    def get_existing_private_zone(self):
        """Determine if there is an existing private zone for the same domain

        :return: (dict) Hosted zone data if found, or None
        :raises: Route53UtilError
        """
        log = logging.getLogger(self.cls_logger + '.get_existing_private_zone')
        if not self.private:
            return
        hosted_zones = list_private_hosted_zones(self.client)
        for hosted_zone in hosted_zones:
            if 'Name' not in hosted_zone.keys():
                continue
            if 'Id' not in hosted_zone.keys():
                continue
            if self.domain == hosted_zone['Name']:
                log.info('Found existing public hosted zone: {n}'.format(n=self.domain))
                if self.is_matching_private_zone(hosted_zone_id=hosted_zone['Id']):
                    return hosted_zone
                else:
                    msg = 'Existing hosted zone does not match VPC specifications'
                    raise Route53UtilError(msg)
        log.info('Existing private hosted zone not found for domain: {d}'.format(d=self.domain))

    def get_existing_public_zone(self):
        """Determine if there is an existing public zone for the same domain

        :return: (dict) Hosted zone data if found, or None
        """
        log = logging.getLogger(self.cls_logger + '.get_existing_public_zone')
        if self.private:
            return
        hosted_zones = list_public_hosted_zones(self.client)
        for hosted_zone in hosted_zones:
            if 'Name' not in hosted_zone.keys():
                continue
            if 'Id' not in hosted_zone.keys():
                continue
            if self.domain == hosted_zone['Name']:
                log.info('Found existing public hosted zone: {n}'.format(n=self.domain))
                return hosted_zone
        log.info('Existing public hosted zone not found for domain: {d}'.format(d=self.domain))

    def is_matching_private_zone(self, hosted_zone_id):
        """Determine if the provided hosted zone ID matches the private hosted zone specified in this object

        :param hosted_zone_id: (str) ID of the existing hosted zone
        :return: (bool) True if the existing hosted zone matches this object
        """
        log = logging.getLogger(self.cls_logger + '.is_matching_private_zone')
        if not all([self.vpc_id, self.region, self.private]):
            return False
        existing_hosted_zone_details = get_hosted_zone(client=self.client, hosted_zone_id=hosted_zone_id)
        if 'VPCs' not in existing_hosted_zone_details:
            log.warning('VPCs data not found for existing private zone ID: {i}'.format(i=hosted_zone_id))
            return False
        for vpc in existing_hosted_zone_details['VPCs']:
            if all(x in vpc.keys() for x in ['VPCRegion', 'VPCId']):
                if self.vpc_region == vpc['VPCRegion'] and self.vpc_id == vpc['VPCId']:
                    log.info('Found matching hosted zone ID: {z}'.format(z=hosted_zone_id))
                    return True
            else:
                log.warning('Missing VPC data in hosted zone: {z}'.format(z=str(vpc)))
                return False
        log.info('This is not a matching private hosted zone: {z}'.format(z=hosted_zone_id))
        return False

    def update_records(self):
        """Updates the hosted zone with the records in self.dns_records

        :return: (dict) Change info (see boto3 docs)
        :raises: Route53UtilError
        """
        log = logging.getLogger(mod_logger + '.update_records')
        if not self.hosted_zone_id:
            msg = 'Unable to update records, create a hosted zone first!'
            raise Route53UtilError(msg)
        log.info('Updating records for hosted zone: {i}'.format(i=self.hosted_zone_id))
        return change_record_sets(
            client=self.client,
            hosted_zone_id=self.hosted_zone_id,
            changes=self.dns_records
        )


def change_record_sets(client, hosted_zone_id, changes, comment=''):
    """Updates record sets for a hosted zone

    :param client: Route53 client object
    :param hosted_zone_id: (str) hosted zone ID
    :param changes: (list) of changes (see boto3 docs)
    :param comment: (str) comment for the changes
    :return: (dict) change info (see boto3 docs)
    :raises: Route53UtilError
    """
    log = logging.getLogger(mod_logger + '.change_record_sets')
    log.info('Changing record sets for hosted zone: {i}'.format(i=hosted_zone_id))
    try:
        response = client.change_resource_record_sets(
            HostedZoneId=hosted_zone_id,
            ChangeBatch={
                'Comment': comment,
                'Changes': changes
            }
        )
    except ClientError as exc:
        msg = 'Problem creating updating records for hosted zone: {h}'.format(h=hosted_zone_id)
        raise Route53UtilError(msg) from exc
    if 'ChangeInfo' not in response.keys():
        msg = 'ChangeInfo not found in response: {r}'.format(r=str(response))
        raise Route53UtilError(msg)
    return response['ChangeInfo']


def create_private_hosted_zone(client, domain, vpc_id, vpc_region, comment=''):
    """Creates a private hosted zone

    :param client: Route53 client object
    :param domain: (str) domain name / FQDN
    :param vpc_id: (str) ID of the VPC for the private
    :param vpc_region: (str) region
    :param comment: (str) comment
    :return: (dict) see boto3 docs
    :raises: Route53UtilError
    """
    log = logging.getLogger(mod_logger + '.create_private_hosted_zone')
    log.info('Creating private hosted zone for [{d}], in VPC [{v}]'.format(d=domain, v=vpc_id))
    caller_reference = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    try:
        response = client.create_hosted_zone(
            Name=domain,
            VPC={
                'VPCRegion': vpc_region,
                'VPCId': vpc_id
            },
            CallerReference=caller_reference,
            HostedZoneConfig={
                'Comment': comment,
                'PrivateZone': True
            },
        )
    except ClientError as exc:
        msg = 'Problem creating private hosted zone [{h}] in VPC ID: [{v}]'.format(h=domain, v=vpc_id)
        raise Route53UtilError(msg) from exc
    if 'HostedZone' not in response.keys():
        msg = 'HostedZone not found in response: {r}'.format(r=str(response))
        raise Route53UtilError(msg)
    if 'Id' not in response['HostedZone'].keys():
        msg = 'Id not found in HostedZone data: {d}'.format(d=str(response['HostedZone']))
        raise Route53UtilError(msg)
    log.info('Created private hosted zone: {d}'.format(d=domain))
    return response['HostedZone']


def create_public_hosted_zone(client, domain, comment=''):
    """Creates a public hosted zone

    :param client: Route53 client object
    :param domain: (str) domain name / FQDN
    :param comment: (str) comment
    :return: (dict) see boto3 docs
    :raises: Route53UtilError
    """
    log = logging.getLogger(mod_logger + '.create_public_hosted_zone')
    log.info('Creating public hosted zone: [{d}]'.format(d=domain))
    caller_reference = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    try:
        response = client.create_hosted_zone(
            Name=domain,
            CallerReference=caller_reference,
            HostedZoneConfig={
                'Comment': comment,
                'PrivateZone': False
            },
        )
    except ClientError as exc:
        msg = 'Problem creating public hosted zone: [{h}]'.format(h=domain)
        raise Route53UtilError(msg) from exc
    if 'HostedZone' not in response.keys():
        msg = 'HostedZone not found in response: {r}'.format(r=str(response))
        raise Route53UtilError(msg)
    if 'Id' not in response['HostedZone'].keys():
        msg = 'Id not found in HostedZone data: {d}'.format(d=str(response['HostedZone']))
        raise Route53UtilError(msg)
    log.info('Created public hosted zone: {d}'.format(d=domain))
    return response['HostedZone']


def create_simple_change_record(record_type, name, value, action='UPSERT', time_to_live=300):
    """Returns a formatted simple record for adding to Route53
    
    :param record_type: (str) type of record (see boto3 docs)
    :param name: (str) name of the record to create (e.g. www)
    :param value: (str) value for the record (e.g. IP address)
    :param action: (str) 'CREATE'|'DELETE'|'UPSERT'
    :param time_to_live: (int) time to live in seconds for the record
    :return: (dict) record set (see boto3 docs)
    """
    log = logging.getLogger(mod_logger + '.create_simple_change_record')
    if action not in ['CREATE', 'DELETE', 'UPSERT']:
        msg = 'Invalid action [{a}], must be: CREATE, DELETE, or UPSERT'
        raise Route53UtilError(msg)
    log.debug('Creating record: [{a}] - [ {t} | {n} | {v} | {x} ]'.format(
        a=action, t=record_type, n=name, v=value, x=str(time_to_live)))
    return {
        'Action': action,
        'ResourceRecordSet': {
            'Name': name,
            'TTL': time_to_live,
            'Type': record_type,
            'ResourceRecords': [
                {
                    'Value': value
                }
            ]
        }
    }


def enable_vpc_private_dns(vpc_id):
    """Enabled private DNS in the VPC

    :param vpc_id: (str) ID of the VPC
    :return: (None)
    :raises: Route53UtilError
    """
    ec2 = EC2Util()
    try:
        ec2.enable_vpc_dns(vpc_id=vpc_id)
    except EC2UtilError as exc:
        msg = 'Unable to enable private DNS for VPC: {v}'.format(v=vpc_id)
        raise Route53UtilError(msg) from exc


def get_hosted_zone(client, hosted_zone_id):
    """Returns the hosted zone ID

    :param client: boto3.client object
    :param hosted_zone_id: (str) ID of the hosted zone
    :return: (dict) hosted zone data (see boto3 docs)
    :raises: Route53UtilError
    """
    log = logging.getLogger(mod_logger + '.get_hosted_zone')
    log.info('Getting details for hosted zone ID: {i}'.format(i=hosted_zone_id))
    try:
        response = client.get_hosted_zone(Id=hosted_zone_id)
    except ClientError as exc:
        msg = 'Problem getting details for hosted zone ID: {h}'.format(h=hosted_zone_id)
        raise Route53UtilError(msg) from exc
    if 'HostedZone' not in response.keys():
        msg = 'HostedZone not found in response: {r}'.format(r=str(response))
        raise Route53UtilError(msg)
    return response


def get_route53_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
    """Gets a Route53 client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    return get_boto3_client(service='route53', region_name=region_name, aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)


def list_hosted_zones(client):
    """Returns a list of hosted zones

    :param client: boto3.client object
    :return: (list) of hosted zones (see boto3 docs)
    """
    log = logging.getLogger(mod_logger + '.list_hosted_zones')
    marker = None
    next_query = True
    hosted_zone_list = []
    log.info('Attempting to list Route53 hosted zones')
    while True:
        if not next_query:
            break
        response = list_hosted_zones_with_marker(client=client, marker=marker)
        if 'IsTruncated' not in response.keys():
            log.warning('IsTruncated not found in response: {r}'.format(r=str(response)))
            return hosted_zone_list
        if 'HostedZones' not in response.keys():
            log.warning('HostedZones not found in response: {r}'.format(r=str(response)))
            return hosted_zone_list
        next_query = response['IsTruncated']
        hosted_zone_list += response['HostedZones']
        if 'Marker' not in response.keys():
            next_query = False
        else:
            marker = response['Marker']
    log.info('Found {n} hosted zones'.format(n=str(len(hosted_zone_list))))
    return hosted_zone_list


def list_hosted_zones_with_marker(client, marker=None):
    """Gets a list of hosted zones provided a marker, or None

    :param client: boto3.client object
    :param marker: (str) Location of the NextToken
    :return: (list) of hosted zones (see boto3 docs)
    """
    if marker:
        return client.list_hosted_zones(Marker=marker)
    else:
        return client.list_hosted_zones()


def list_private_hosted_zones(client):
    """Gets a list of ony the private hosted zones

    :param client: boto3.client object
    :return: (list) of private hosted zones (see boto3 docs)
    """
    private_hosted_zones = []
    for hosted_zone in list_hosted_zones(client):
        if 'Config' in hosted_zone.keys():
            if 'PrivateZone' in hosted_zone['Config']:
                if hosted_zone['Config']['PrivateZone']:
                    private_hosted_zones.append(hosted_zone)
    return private_hosted_zones


def list_public_hosted_zones(client):
    """Gets a list of ony the public hosted zones

    :param client: boto3.client object
    :return: (list) of public hosted zones (see boto3 docs)
    """
    public_hosted_zones = []
    for hosted_zone in list_hosted_zones(client):
        if 'Config' in hosted_zone.keys():
            if 'PrivateZone' in hosted_zone['Config']:
                if not hosted_zone['Config']['PrivateZone']:
                    public_hosted_zones.append(hosted_zone)
            else:
                public_hosted_zones.append(hosted_zone)
        else:
            public_hosted_zones.append(hosted_zone)
    return public_hosted_zones
