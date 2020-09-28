"""Module: rdsutil

This module provides utilities for interacting with the AWS
RDS API, including creating new RDS clusters.

"""
import logging
import os

from botocore.client import ClientError

from .logify import Logify
from .awsutil import get_boto3_client
from .ec2util import EC2Util, IpPermission
from .exceptions import EC2UtilError, RdsUtilError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.rdsutil'

# Default settings for DB instances
default_db_instance_type = 'db.m5.large'
default_db_master_username = 'dbadmin'
default_db_master_password = 'dbadminpass'

# Required RDS config properties
required_props = [
    'DBInstanceIdentifier',
    'DBName',
    'Engine',
    'EngineVersion',
    'KmsKeyId',
    'SubnetIds',
    'VpcId',
    'VpcSecurityGroupId'
]

# Optional props with default values, overwritten if provided
optional_props = {
    'AllocatedStorage': 200,
    'AvailabilityZone': None,
    'AutoMinorVersionUpgrade': True,
    'BackupRetentionPeriod': 7,
    'CopyTagsToSnapshot': False,
    'DBInstanceClass': 'db.m5.large',
    'LicenseModel': 'license-included',
    'MasterUsername': 'jira_admin',
    'MasterUserPassword': 'J1ra2Admin465',
    'StorageType': 'standard'
}

# Supported DB engines
supported_db_engines = [
    'postgres',
    'sqlserver-ee'
]


class RdsUtil(object):
    """Utility for interacting with the AWS RDS SDK
    """
    def __init__(self, region_name=None, aws_access_key_id=None, aws_secret_access_key=None):
        self.cls_logger = mod_logger + '.RdsUtil'
        try:
            self.client = get_rds_client(region_name=region_name, aws_access_key_id=aws_access_key_id,
                                         aws_secret_access_key=aws_secret_access_key)
        except ClientError as exc:
            msg = 'Unable to create an EC2 client'
            raise RdsUtilError(msg) from exc
        self.region = self.client.meta.region_name

    def create_rds_instance(self, db_engine, db_name, db_instance_id, db_version, vpc_id, subnet_ids, availability_zone,
                            security_group_id=None, storage_gb=200, db_instance_type=default_db_instance_type,
                            master_username=default_db_master_username, master_password=default_db_master_password,
                            backup_days=7, license_model='license-included', storage_type='standard',
                            kms_key_alias='aws/rds'):
        """

        Reference: 
        https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/rds.html#RDS.Client.create_db_instance

        :param db_engine: (str) DB engine
        :param db_name: (str) name of the DB to create
        :param db_instance_id: (str) Unique identifier for the DB
        :param db_version: (str) Version of the DB, depends on the engine
        :param vpc_id: (str) ID of the VPC
        :param subnet_ids: (list) List of Subnet IDs to create a Subnet Group from
        :param availability_zone: (str) ID of the availability zone
        :param security_group_id: (str) ID of the VPC security group to apply (one will be created if not provided)
        :param storage_gb: (int) Storage in GB
        :param db_instance_type: (str) instance type for the RDS DB instance
        :param master_username: (str) DB master username
        :param master_password: (str) DB master password
        :param backup_days: (int) number of days to retain backups
        :param license_model: (str) license model
        :param storage_type: (str) type of RDS storage to use
        :param kms_key_alias: (str) alias of the KMS key
        :return: (dict) containing RDS instance data
        :raises: RdsUtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_rds_instance')

        # Engine-specific params
        port = None
        if db_engine == 'postgres':
            port = 5432
            license_model = 'postgresql-license'
        elif 'sqlserver' in db_engine:
            port = 1433
            db_name = None
            license_model = 'license-included'
        else:
            msg = 'DB engine [{d}] is not supported at this time'.format(d=db_engine)
            raise RdsUtilError(msg)

        # Ensure storage is an int
        try:
            storage_gb = int(storage_gb)
        except ValueError:
            msg = 'storage_gb must be an int, found: {t}'.format(t=storage_gb.__class__.__name__)
            raise RdsUtilError(msg)

        # Ensure the DB ID doesn't exist already, return it if found
        db = self.get_rds_instance_by_id(db_instance_id=db_instance_id)
        if db:
            log.info('Found existing DB, will not be created: {i}'.format(i=db_instance_id))
            return db

        # Create a subnet group from the provided list of subnet IDs
        try:
            subnet_group = self.create_db_subnet_group(
                subnet_ids=subnet_ids,
                group_name=db_instance_id,
                group_description='Subnet group for {n} ID: {i}'.format(n=db_name, i=db_instance_id)
            )
        except RdsUtilError as exc:
            msg = 'Problem creating DB subnet group for DB ID: {i}'.format(i=db_instance_id)
            raise RdsUtilError(msg) from exc

        # If a security group ID was not provided, create one
        if not security_group_id:
            ec2 = EC2Util(skip_is_aws=True)
            # Retrieve the VPC CIDR blocks
            try:
                vpc_cidr_blocks = ec2.retrieve_vpc_cidr_blocks(vpc_id=vpc_id)
            except EC2UtilError as exc:
                msg = 'Problem retrieving VPC CIDR blocks for VPC ID: {i}'.format(i=vpc_id)
                raise RdsUtilError(msg) from exc
            # Create a VPC security group
            sg_name = '{i}-sg'.format(i=db_instance_id)
            try:
                security_group_id = ec2.create_security_group(
                    name=sg_name,
                    description='Security group for RDS instance ID: {i}'.format(i=db_instance_id),
                    vpc_id=vpc_id
                )
            except EC2UtilError as exc:
                msg = 'Problem creating security group: {n}'.format(n=sg_name)
                raise RdsUtilError(msg) from exc
            log.info('Created VPC security group ID: {i}'.format(i=security_group_id))

            # Create SG rules
            sg_egress_rules = [
                IpPermission(IpProtocol='-1', CidrIp='0.0.0.0/0', Description='Allow all out')
            ]
            sg_ingress_rules = []
            for vpc_cidr_block in vpc_cidr_blocks:
                sg_ingress_rules.append(
                    IpPermission(IpProtocol='tcp', FromPort=port, ToPort=port,
                                 CidrIp=vpc_cidr_block, Description='Allow VPC CIDR')
                )
            log.info('Configuring security group rules for security group ID: {i}'.format(i=security_group_id))
            try:
                ec2.configure_security_group_ingress(
                    security_group_id=security_group_id,
                    desired_ingress_rules=sg_ingress_rules
                )
                ec2.configure_security_group_egress(
                    security_group_id=security_group_id,
                    desired_egress_rules=sg_egress_rules
                )
            except EC2UtilError as exc:
                msg = 'Problem configuring security group rule for: {i}'.format(i=security_group_id)
                raise RdsUtilError(msg) from exc

        db_subnet_group_name = subnet_group['DBSubnetGroupName']
        security_group_id_list = [security_group_id]

        log.info('Existing DB with ID [{i}] not found, attempting to create...'.format(i=db_instance_id))
        try:
            if db_name:
                response = self.create_rds_instance_with_db_name(
                    DBName=db_name,
                    DBInstanceIdentifier=db_instance_id,
                    AllocatedStorage=storage_gb,
                    DBInstanceClass=db_instance_type,
                    Engine=db_engine,
                    MasterUsername=master_username,
                    MasterUserPassword=master_password,
                    VpcSecurityGroupIds=security_group_id_list,
                    AvailabilityZone=availability_zone,
                    DBSubnetGroupName=db_subnet_group_name,
                    BackupRetentionPeriod=backup_days,
                    Port=port,
                    MultiAZ=False,
                    EngineVersion=db_version,
                    AutoMinorVersionUpgrade=True,
                    LicenseModel=license_model,
                    PubliclyAccessible=False,
                    StorageType=storage_type,
                    StorageEncrypted=True,
                    KmsKeyId=kms_key_alias,
                    CopyTagsToSnapshot=True,
                    MonitoringInterval=0,
                    EnableIAMDatabaseAuthentication=False,
                    EnablePerformanceInsights=False,
                    DeletionProtection=False,
                )
            else:
                response = self.create_rds_instance_without_db_name(
                    DBInstanceIdentifier=db_instance_id,
                    AllocatedStorage=storage_gb,
                    DBInstanceClass=db_instance_type,
                    Engine=db_engine,
                    MasterUsername=master_username,
                    MasterUserPassword=master_password,
                    VpcSecurityGroupIds=security_group_id_list,
                    AvailabilityZone=availability_zone,
                    DBSubnetGroupName=db_subnet_group_name,
                    BackupRetentionPeriod=backup_days,
                    Port=port,
                    MultiAZ=False,
                    EngineVersion=db_version,
                    AutoMinorVersionUpgrade=True,
                    LicenseModel=license_model,
                    PubliclyAccessible=False,
                    StorageType=storage_type,
                    StorageEncrypted=True,
                    KmsKeyId=kms_key_alias,
                    CopyTagsToSnapshot=True,
                    MonitoringInterval=0,
                    EnableIAMDatabaseAuthentication=False,
                    EnablePerformanceInsights=False,
                    DeletionProtection=False,
                )
        except ClientError as exc:
            msg = 'There was a problem launching the RDS instance\n{e}'.format(e=str(exc))
            raise RdsUtilError(msg) from exc
        if 'DBInstance' not in response.keys():
            msg = 'DBInstance not found in response: {r}'.format(r=str(response))
            raise RdsUtilError(msg)
        log.info('Created RDS database ID: {i}'.format(i=response['DBInstance']['DBInstanceIdentifier']))
        return response['DBInstance']

    def create_rds_instance_with_db_name(self, **kwargs):
        """Creates an RDS instance that requires a DB name (e.g. postgres)

        :param kwargs: (dict) args
        :return: EC2 client response
        """
        return self.client.create_db_instance(
            DBName=kwargs['DBName'],
            DBInstanceIdentifier=kwargs['DBInstanceIdentifier'],
            AllocatedStorage=kwargs['AllocatedStorage'],
            DBInstanceClass=kwargs['DBInstanceClass'],
            Engine=kwargs['Engine'],
            MasterUsername=kwargs['MasterUsername'],
            MasterUserPassword=kwargs['MasterUserPassword'],
            VpcSecurityGroupIds=kwargs['VpcSecurityGroupIds'],
            AvailabilityZone=kwargs['AvailabilityZone'],
            DBSubnetGroupName=kwargs['DBSubnetGroupName'],
            BackupRetentionPeriod=kwargs['BackupRetentionPeriod'],
            Port=kwargs['Port'],
            MultiAZ=kwargs['MultiAZ'],
            EngineVersion=kwargs['EngineVersion'],
            AutoMinorVersionUpgrade=kwargs['AutoMinorVersionUpgrade'],
            LicenseModel=kwargs['LicenseModel'],
            PubliclyAccessible=kwargs['PubliclyAccessible'],
            StorageType=kwargs['StorageType'],
            StorageEncrypted=kwargs['StorageEncrypted'],
            KmsKeyId=kwargs['KmsKeyId'],
            CopyTagsToSnapshot=kwargs['CopyTagsToSnapshot'],
            MonitoringInterval=kwargs['MonitoringInterval'],
            EnableIAMDatabaseAuthentication=kwargs['EnableIAMDatabaseAuthentication'],
            EnablePerformanceInsights=kwargs['EnablePerformanceInsights'],
            DeletionProtection=kwargs['DeletionProtection'],
        )

    def create_rds_instance_without_db_name(self, **kwargs):
        """Creates an RDS instance without a DB name (e.g. SQL server)

        :param kwargs: (dict) args
        :return: EC2 client response
        """
        return self.client.create_db_instance(
            DBInstanceIdentifier=kwargs['DBInstanceIdentifier'],
            AllocatedStorage=kwargs['AllocatedStorage'],
            DBInstanceClass=kwargs['DBInstanceClass'],
            Engine=kwargs['Engine'],
            MasterUsername=kwargs['MasterUsername'],
            MasterUserPassword=kwargs['MasterUserPassword'],
            VpcSecurityGroupIds=kwargs['VpcSecurityGroupIds'],
            AvailabilityZone=kwargs['AvailabilityZone'],
            DBSubnetGroupName=kwargs['DBSubnetGroupName'],
            BackupRetentionPeriod=kwargs['BackupRetentionPeriod'],
            Port=kwargs['Port'],
            MultiAZ=kwargs['MultiAZ'],
            EngineVersion=kwargs['EngineVersion'],
            AutoMinorVersionUpgrade=kwargs['AutoMinorVersionUpgrade'],
            LicenseModel=kwargs['LicenseModel'],
            PubliclyAccessible=kwargs['PubliclyAccessible'],
            StorageType=kwargs['StorageType'],
            StorageEncrypted=kwargs['StorageEncrypted'],
            KmsKeyId=kwargs['KmsKeyId'],
            CopyTagsToSnapshot=kwargs['CopyTagsToSnapshot'],
            MonitoringInterval=kwargs['MonitoringInterval'],
            EnableIAMDatabaseAuthentication=kwargs['EnableIAMDatabaseAuthentication'],
            EnablePerformanceInsights=kwargs['EnablePerformanceInsights'],
            DeletionProtection=kwargs['DeletionProtection'],
        )

    def list_rds_instances_with_marker(self, marker=None, max_records=100):
        """Lists RDS instances using the provided marker

        :param marker: (str) Pagination marker
        :param max_records: (int) max number of records to return
        :return: (dict) RDS instances query response
        """
        if marker:
            return self.client.describe_db_instances(
                Marker=marker,
                MaxRecords=max_records
            )
        else:
            return self.client.describe_db_instances(
                MaxRecords=max_records
            )

    def list_rds_instances(self):
        """Returns data on the existing DB instance or none

        :return: (list) of DB instances
        """
        log = logging.getLogger(self.cls_logger + '.list_rds_instances')
        log.info('Retrieving RDS instances...')
        marker = None
        next_query = True
        max_records = 100
        rds_instance_list = []
        while True:
            if not next_query:
                break
            response = self.list_rds_instances_with_marker(marker=marker, max_records=max_records)
            if 'DBInstances' not in response.keys():
                log.warning('DBInstances not found in response: {r}'.format(r=str(response)))
            else:
                rds_instance_list += response['DBInstances']
            if 'Marker' not in response.keys():
                marker = None
                next_query = False
            else:
                marker = response['Marker']
        log.info('Found {n} RDS instances'.format(n=str(len(rds_instance_list))))
        return rds_instance_list

    def list_rds_instances_in_vpc(self, vpc_id):
        """Returns info on the specified RDS database instance identifier

        :param vpc_id: (str) ID of the VPC
        :return: (list) of RDS instances in the provided VPC ID
        """
        log = logging.getLogger(self.cls_logger + '.list_rds_instances_in_vpc')
        vpc_db_instances = []
        db_instances = self.list_rds_instances()
        for db_instance in db_instances:
            if 'DBInstanceIdentifier' not in db_instance.keys():
                log.warning('DBInstanceIdentifier not found in DB instance data: {d}'.format(d=str(db_instance)))
                continue
            if 'DBSubnetGroup' not in db_instance.keys():
                continue
            if 'VpcId' not in db_instance['DBSubnetGroup']:
                log.warning('VpcId not found in DB instance subnet group data: {d}'.format(d=str(db_instance)))
                continue
            if db_instance['DBSubnetGroup']['VpcId'] == vpc_id:
                log.info('Found RDS DB instance in VPC ID {i}: {r}'.format(
                    i=vpc_id, r=db_instance['DBInstanceIdentifier']))
                vpc_db_instances.append(db_instance)
        log.info('Found {n} RDS DB instances in VPC ID: {i}'.format(n=str(len(vpc_db_instances)), i=vpc_id))
        return vpc_db_instances

    def get_rds_instance_by_id(self, db_instance_id):
        """Returns info on the specified RDS database instance identifier

        :param db_instance_id: (str) DB identifier
        :return: (dict) DB instance data or None
        """
        log = logging.getLogger(self.cls_logger + '.get_rds_instance_by_id')
        db_instances = self.list_rds_instances()
        for db_instance in db_instances:
            if 'DBInstanceIdentifier' not in db_instance.keys():
                log.warning('DBInstanceIdentifier not found in DB instance data: {d}'.format(d=str(db_instance)))
                continue
            if db_instance['DBInstanceIdentifier'] == db_instance_id:
                return db_instance

    def get_rds_instance_by_id_in_vpc(self, vpc_id, db_instance_id):
        """Gets the RDS instance in the specified VPC ID by DB identifier

        :param vpc_id: (str) ID of the VPC
        :param db_instance_id: (str) DB identifier
        :return: (dict) DB instance data or None
        """
        log = logging.getLogger(self.cls_logger + '.get_rds_instance_by_id_in_vpc')
        log.info('Looking for RDS DB instance in VPC ID [{v}] with DB identifier: {i}'.format(
            v=vpc_id, i=db_instance_id))
        vpc_db_instances = self.list_rds_instances_in_vpc(vpc_id=vpc_id)
        for vpc_db_instance in vpc_db_instances:
            if vpc_db_instance['DBInstanceIdentifier'] == db_instance_id:
                log.info('Found RDS DB instance in VPC ID [{v}] with DB identifier: {i}'.format(
                    v=vpc_id, i=db_instance_id))
                return vpc_db_instance
        log.info('RDS DB instance in VPC ID [{v}] with DB identifier [{i}] not found'.format(
            v=vpc_id, i=db_instance_id))

    def wait_for_rds_instance_available(self, db_instance_id):
        """Waits until the RDS instance is available

        :param db_instance_id: (str) RDS DB instance identifier
        :return: (dict)
        """
        log = logging.getLogger(self.cls_logger + '.wait_for_rds_instance_available')
        while True:
            try:
                rds_info = self.get_rds_instance_by_id(db_instance_id=db_instance_id)
            except (ClientError, RdsUtilError) as exc:
                pass

    def create_db_subnet_group(self, subnet_ids, group_name, group_description='DB subnet group'):
        """Creates a subnet group using the provided parameters

        :param subnet_ids: (list) of str subnet IDs to include in the group
        :param group_name: (str) name of the subnet group
        :param group_description: (str) Description for the subnet group
        :return: (dict) info for the subnet group
        :raises: RdsUtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_db_subnet_group')
        subnet_group = self.get_subnet_group(group_name=group_name)
        if subnet_group:
            existing_subnet_ids = []
            log.info('Found existing subnet group [{n}], evaluating...'.format(n=group_name))
            if 'Subnets' not in subnet_group.keys():
                msg = 'Subnets not found in existing subnet group data: {d}'.format(d=str(subnet_group))
                raise RdsUtilError(msg)
            for subnet in subnet_group['Subnets']:
                if 'SubnetIdentifier' not in subnet.keys():
                    msg = 'SubnetIdentifier not found in subnet data: {d}'.format(d=str(subnet))
                    raise RdsUtilError(msg)
                existing_subnet_ids.append(subnet['SubnetIdentifier'])

            # Compare the subnet IDs
            subnet_ids.sort()
            existing_subnet_ids.sort()
            if subnet_ids == existing_subnet_ids:
                log.info('Found existing subnet group [{n}] contains the desired subnet IDs: {s}'.format(
                    n=group_name, s=','.join(subnet_ids)))
                return subnet_group
            else:
                msg = 'Existing subnet group [{n}] has subnet IDs [{s}], which does not match desired: [{d}]'.format(
                    n=group_name, s=','.join(existing_subnet_ids), d=','.join(subnet_ids))
                raise RdsUtilError(msg)

        # If the existing subnet group is not found by name, create it
        log.info('Creating new subnet group with name [{n}] and subnet IDs: {s}'.format(
            n=group_name, s=','.join(subnet_ids)))
        try:
            response = self.client.create_db_subnet_group(
                DBSubnetGroupName=group_name,
                DBSubnetGroupDescription=group_description,
                SubnetIds=subnet_ids
            )
        except ClientError as exc:
            msg = 'Problem creating subnet group with name: {n}'.format(n=group_name)
            raise RdsUtilError(msg) from exc
        if 'DBSubnetGroup' not in response.keys():
            msg = 'DBSubnetGroup not found in response: {r}'.format(r=str(response))
            raise RdsUtilError(msg)
        return response['DBSubnetGroup']

    def list_db_subnet_groups_with_marker(self, marker=None, max_records=100):
        """Lists subnet groups using the provided marker

        :param marker: (str) Pagination marker
        :param max_records: (int) max number of records to return
        :return: (dict) subnet group query response
        """
        if marker:
            return self.client.describe_db_subnet_groups(
                Marker=marker,
                MaxRecords=max_records
            )
        else:
            return self.client.describe_db_subnet_groups(
                MaxRecords=max_records
            )

    def list_db_subnet_groups(self):
        """Returns data on the existing DB subnet groups or none

        :return: (list) of subnet groups
        """
        log = logging.getLogger(self.cls_logger + '.list_db_subnet_groups')
        log.info('Retrieving DB subnet groups...')
        marker = None
        next_query = True
        max_records = 100
        group_list = []
        while True:
            if not next_query:
                break
            response = self.list_db_subnet_groups_with_marker(marker=marker, max_records=max_records)
            if 'DBSubnetGroups' not in response.keys():
                log.warning('DBSubnetGroups not found in response: {r}'.format(r=str(response)))
            else:
                group_list += response['DBSubnetGroups']
            if 'Marker' not in response.keys():
                marker = None
                next_query = False
            else:
                marker = response['Marker']
        log.info('Found {n} DB subnet groups'.format(n=str(len(group_list))))
        return group_list

    def get_subnet_group(self, group_name):
        """Returns info about the subnet group

        :param group_name: (str) name of the subnet group
        :return: (dict) subnet group info
        """
        log = logging.getLogger(self.cls_logger + '.get_subnet_group')
        log.info('Retrieving subnet group with name: {n}'.format(n=group_name))
        subnet_groups = self.list_db_subnet_groups()
        for subnet_group in subnet_groups:
            if 'DBSubnetGroupName' not in subnet_group.keys():
                continue
            if subnet_group['DBSubnetGroupName'] == group_name:
                log.info('Found subnet group with name: {n}'.format(n=group_name))
                return subnet_group
        log.info('Subnet group with name [{n}] not found'.format(n=group_name))

    def delete_rds_instance(self, db_instance_id):
        """Deletes the specified instance ID

        By default this will take a final snapshot before deletion, and erase the automated backups

        :param db_instance_id: (str) identifier of the DB
        :return: (dict) data about the deleted instance
        :raises: RdsUtilError
        """
        log = logging.getLogger(self.cls_logger + '.delete_rds_instance')
        log.info('Deleting DB instance with ID: {i}'.format(i=db_instance_id))
        try:
            response = self.client.delete_db_instance(
                DBInstanceIdentifier=db_instance_id,
                SkipFinalSnapshot=False,
                FinalDBSnapshotIdentifier=db_instance_id + 'final_snapshot',
                DeleteAutomatedBackups=True
            )
        except ClientError as exc:
            msg = 'Problem deleting RDS database with ID: {i}'.format(i=db_instance_id)
            raise RdsUtilError(msg) from exc
        if 'DBInstance' not in response.keys():
            msg = 'DBInstance data not found in response: {r}'.format(r=str(response))
            raise RdsUtilError(msg)
        return response['DBInstance']


def get_rds_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
    """Gets an EC2 client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    return get_boto3_client(service='rds', region_name=region_name, aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)


def read_rds_config(rds_config_file):
    """Reads the RDS config properties file

    This method reads the RDS config properties file and returns a dict

    :param rds_config_file: (str) path to the RDS config file
    :return: (dict) key-value pairs from the properties file
    """
    log = logging.getLogger(mod_logger + '.read_rds_config')
    properties = {}
    
    # Ensure the RDS config props file exists
    if not os.path.isfile(rds_config_file):
        log.error('RDS config file not found: {f}'.format(f=rds_config_file))
        return properties
    
    log.info('Reading RDS config properties file: {r}'.format(r=rds_config_file))
    with open(rds_config_file, 'r') as f:
        for line in f:
            if line.startswith('#'):
                continue
            elif '=' in line:
                split_line = line.strip().split('=', 1)
                if len(split_line) == 2:
                    prop_name = split_line[0].strip()
                    prop_value = split_line[1].strip()
                    if prop_name is None or not prop_name or prop_value is None or not prop_value:
                        log.info('Property name <{n}> or value <v> is none or blank, not including it'.format(
                            n=prop_name, v=prop_value))
                    else:
                        log.debug('Adding property {n} with value {v}...'.format(n=prop_name, v=prop_value))
                        unescaped_prop_value = prop_value.replace('\\', '')
                        properties[prop_name] = unescaped_prop_value
                else:
                    log.warning('Skipping line that did not split into 2 part on an equal sign...')
    log.info('Successfully read in RDS config properties, verifying required props...')
    return properties


def validate_rds_properties(rds_config_props):
    """Returns True if the RDS config properties are found to be valid

    :param rds_config_props: (dict) key-value pairs read in from the RDS config properties file
    :return: (dict) RDS config properties
    :raises: RdsUtilError
    """
    log = logging.getLogger(mod_logger + '.validate_rds_properties')
    for required_prop in required_props:
        if required_prop not in rds_config_props.keys():
            msg = 'Required property missing from RDS config file: {p}'.format(p=required_prop)
            raise RdsUtilError(msg)
    for optional_prop in optional_props.keys():
        if optional_prop not in rds_config_props.keys():
            log.info('Adding default value for [{k}]: {v}'.format(k=optional_prop, v=optional_props[optional_prop]))
            rds_config_props[optional_prop] = optional_props[optional_prop]
        else:
            log.info('Found RDS config value for optional prop [{k}]: {v}'.format(
                k=optional_prop, v=rds_config_props[optional_prop]))
    if rds_config_props['Engine'] not in supported_db_engines:
        msg = 'Unsupported DB engine found [{e}], supported DB engines are: {s}'.format(
            e=rds_config_props['Engine'], s=','.join(supported_db_engines))
        raise RdsUtilError(msg)

    # Convert the subnet IDs from a string to a list
    rds_config_props['SubnetIds'] = rds_config_props['SubnetIds'].split(',')

    # Ensure at least 2 subnet IDs provided
    if len(rds_config_props['SubnetIds']) < 2:
        msg = 'At least 2 subnet IDs are required, found {n}: {s}'.format(
            n=str(len(rds_config_props['SubnetIds'])), s=','.join(rds_config_props['SubnetIds']))
        raise RdsUtilError(msg)

    # Ensure the subnet IDs are in the provided VPC ID
    ec2 = EC2Util(skip_is_aws=True)
    try:
        vpc_subnets = ec2.list_subnets(vpc_id=rds_config_props['VpcId'])
    except EC2UtilError as exc:
        msg = 'Problem listing subnets in VPC ID: {i}'.format(i=rds_config_props['VpcId'])
        raise RdsUtilError(msg) from exc
    for subnet_id in rds_config_props['SubnetIds']:
        found_in_vpc = False
        for vpc_subnet in vpc_subnets:
            if 'SubnetId' not in vpc_subnet.keys():
                msg = 'SubnetId not found in subnet data: {s}'.format(s=str(vpc_subnet))
                raise RdsUtilError(msg)
            if 'VpcId' not in vpc_subnet.keys():
                msg = 'VpcId not found in subnet data: {s}'.format(s=str(vpc_subnet))
                raise RdsUtilError(msg)
            if vpc_subnet['SubnetId'] == subnet_id:
                if vpc_subnet['VpcId'] != rds_config_props['VpcId']:
                    msg = 'Subnet ID [{s}] found in VPC [{f}] not in provided VPC: {v}'.format(
                        s=subnet_id, f=vpc_subnet['VpcId'], v=rds_config_props['VpcId'])
                    raise RdsUtilError(msg)
                else:
                    log.info('Found subnet {s} in provided VPC ID: {v}'.format(
                        s=subnet_id, v=rds_config_props['VpcId']))
                    found_in_vpc = True
        if not found_in_vpc:
            msg = 'Subnet {s} not found in VPC ID: {v}'.format(s=subnet_id, v=rds_config_props['VpcId'])
            raise RdsUtilError(msg)

    # Ensure there are at least 2 different availability zones represented in the provided subnet IDs
    availability_zones = []
    for vpc_subnet in vpc_subnets:
        if 'AvailabilityZone' not in vpc_subnet.keys():
            msg = 'AvailabilityZone not found in subnet data: {d}'.format(d=str(vpc_subnet))
            raise RdsUtilError(msg)
        if vpc_subnet['AvailabilityZone'] not in availability_zones:
            availability_zones.append(vpc_subnet['AvailabilityZone'])
    if len(availability_zones) < 2:
        msg = 'Subnet IDs must be in at least 2 availability zones, found availability zones: {z}'.format(
            z=','.join(availability_zones))
        raise RdsUtilError(msg)

    # Ensure the security group ID is in the provided VPC ID
    try:
        vpc_sgs = ec2.list_security_groups_in_vpc(vpc_id=rds_config_props['VpcId'])
    except EC2UtilError as exc:
        msg = 'Problem listing security groups in VPC ID: {i}'.format(i=rds_config_props['VpcId'])
        raise RdsUtilError(msg) from exc
    found_sg_in_vpc = False
    for vpc_sg in vpc_sgs:
        if 'GroupId' not in vpc_sg.keys():
            msg = 'GroupId not found in security group data: {s}'.format(s=str(vpc_sg))
            raise RdsUtilError(msg)
        if 'VpcId' not in vpc_sg.keys():
            msg = 'VpcId not found in security group data: {s}'.format(s=str(vpc_sg))
            raise RdsUtilError(msg)
        if vpc_sg['GroupId'] == rds_config_props['VpcSecurityGroupId']:
            if vpc_sg['VpcId'] == rds_config_props['VpcId']:
                log.info('Found security group {s} in provided VPC ID: {v}'.format(
                    s=vpc_sg['GroupId'], v=rds_config_props['VpcId']))
                found_sg_in_vpc = True
    if not found_sg_in_vpc:
        msg = 'Security group {s} not found in VPC ID: {v}'.format(
            s=rds_config_props['VpcSecurityGroupId'], v=rds_config_props['VpcId'])
        raise RdsUtilError(msg)
    for rds_config_prop in rds_config_props.keys():
        log.info('Using config prop: {k}={v}'.format(k=rds_config_prop, v=rds_config_props[rds_config_prop]))
    return rds_config_props
