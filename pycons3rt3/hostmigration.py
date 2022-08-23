#!/usr/bin/env python3
"""
Use this 'migrate' CLI command to migrate VMs on and off dedicated hosts.

Notes:
    - Currently only --cloudtype aws is supported
    - Currently only the "on" command is supported

Usage:
    migrate on --cloudtype aws --host 'h-12345' --id='i-12345' --size='m5.huge'

"""

import argparse
import datetime
import logging
import sys
import time

from .ec2util import EC2Util
from .exceptions import EC2UtilError
from .logify import Logify


__author__ = 'Joe Yennaco'

# Set up logger name for this module
mod_logger = Logify.get_name() + '.hostmigration'


def migrate_ec2_instance_to_host(ec2, instance_id, host_details, size, os_type=None, ami_id=None, nat=False):
    """Migrates a DR to a dedicated host

    :param ec2: boto3 EC2 client
    :param instance_id: (str) instance ID of the VM
    :param host_details: (str) dedicated host data
    :param size: (str) instance type for the instance on the host
    :param os_type: (str) windows or linux
    :param ami_id: (str) ID of the AMI
    :param nat: (bool) Set True when migrating a NAT box
    :return: (bool) True if successful, False otherwise
    """
    log = logging.getLogger(mod_logger + '.migrate_ec2_instance_to_host')

    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')

    # Get the host ID and availability zone
    try:
        host_id = host_details['HostId']
        host_availability_zone = host_details['AvailabilityZone']
    except KeyError as exc:
        msg = 'Problem getting data from host details: {h}\n{e}'.format(h=str(host_details), e=str(exc))
        log.error(msg)
        return False

    # Ensure the instance exists
    if not ec2.ensure_exists(resource_id=instance_id):
        msg = 'Instance ID not found: {i}'.format(i=instance_id)
        log.error(msg)
        return False

    # Get the network interfaces, subnet, and tag info from the original instance
    log.info('Getting info from instance ID: {i}'.format(i=instance_id))
    try:
        instance_info = ec2.get_instance(instance_id=instance_id)
    except EC2UtilError as exc:
        msg = 'Problem getting EC2 instance data: {i}\n{e}'.format(i=instance_id, e=str(exc))
        log.error(msg)
        return False

    # Check for platform data
    platform = None
    if 'Platform' in instance_info.keys():
        platform = instance_info['Platform']
    else:
        log.info('Platform not found in instance data: {d}'.format(d=str(instance_info)))

    # If platform data was found, use that for os_type
    if platform:
        if 'windows' in platform.lower():
            os_type = 'windows'
            log.info('Found Windows platform in instance data [{p}], using OS type: {t}'.format(p=platform, t=os_type))
        elif 'nix' in platform.lower():
            os_type = 'linux'
            log.info('Found Linux platform in instance data [{p}], using OS type: {t}'.format(p=platform, t=os_type))
    elif os_type:
        # If not platform data found, use the user-provided os_type
        log.info('Platform not found in instance data, using provided OS type: {t}'.format(t=os_type))

    # Exit if no os_type found
    if not os_type:
        log.error('Unable to determine the OS type')
        return False

    # Ensure required data was found
    if 'NetworkInterfaces' not in instance_info.keys():
        msg = 'NetworkInterfaces not found in instance data: {d}'.format(d=str(instance_info))
        log.error(msg)
        return False
    if 'Tags' not in instance_info.keys():
        msg = 'Tags not found in instance data: {d}'.format(d=str(instance_info))
        log.error(msg)
        return False
    if 'SubnetId' not in instance_info.keys():
        msg = 'SubnetId not found in instance data: {d}'.format(d=str(instance_info))
        log.error(msg)
        return False
    if 'SecurityGroups' not in instance_info.keys():
        msg = 'SecurityGroups not found in instance data: {d}'.format(d=str(instance_info))
        log.error(msg)
        return False
    if 'KeyName' not in instance_info.keys():
        msg = 'KeyName not found in instance data: {d}'.format(d=str(instance_info))
        log.warning(msg)
        key_name = 'ProductionApp-userkeypair'
        log.info('Using the default key name: {n}'.format(n=key_name))
    else:
        key_name = instance_info['KeyName']
        log.info('Using the key name we found: {n}'.format(n=key_name))

    # Get the info from the current instance
    network_interfaces = instance_info['NetworkInterfaces']
    tags = instance_info['Tags']
    subnet_id = instance_info['SubnetId']
    security_groups = instance_info['SecurityGroups']

    # Get the instance name
    instance_name = None
    for tag in tags:
        if tag['Key'] == 'Name':
            instance_name = tag['Value']
            break

    # Check for nat in the name
    if instance_name:
        if not nat:
            if 'nat' in instance_name:
                log.info('This name tag appears to be for a nat box: {n}'.format(n=instance_name))
                nat = True

    # Get the subnet details
    try:
        subnet_details = ec2.get_subnet(subnet_id=subnet_id)
    except EC2UtilError as exc:
        msg = 'Problem retrieving details for subnet: {s}\n{e}'.format(s=subnet_id, e=str(exc))
        log.error(msg)
        return False

    # Get the subnet availability zone
    if 'AvailabilityZone' not in subnet_details.keys():
        msg = 'AvailabilityZone not found in subnet data: {s}'.format(s=str(subnet_details))
        log.error(msg)
        return False
    subnet_availability_zone = subnet_details['AvailabilityZone']

    # Ensure the subnet availability zone matches the host availability zone
    if host_availability_zone != subnet_availability_zone:
        msg = 'Cannot deploy instance on subnet [{s}] in availability zone [{z1}] into host [{h}] in a different ' \
              'availability zone [{z2}]'.format(s=subnet_id, z1=subnet_availability_zone, h=host_id,
                                                z2=host_availability_zone)
        log.error(msg)
        return False

    # Get a list of security group IDs
    security_group_ids = []
    for security_group in security_groups:
        security_group_ids.append(security_group['GroupId'])

    # Stop the instance
    log.info('Stopping instance ID: {i}'.format(i=instance_id))
    try:
        _, current_state, previous_state = ec2.stop_instance(instance_id=instance_id)
    except EC2UtilError as exc:
        msg = 'Problem stopping instance ID: {i}\n{e}'.format(i=instance_id, e=str(exc))
        log.error(msg)
        return False
    log.info('Instance state transitioning from [{p}] to [{c}]'.format(p=previous_state, c=current_state))

    # Wait for the instance to reach the stopped state
    log.info('Waiting for instance ID {i} to reach the stopped state'.format(i=instance_id))
    if not ec2.wait_for_instance_stopped(instance_id=instance_id):
        log.error('EC2 instance did not reach the stopped state')
        return False

    # Wait 5 seconds
    log.info('Waiting 5 seconds....')
    time.sleep(5)

    # Create the image
    if not ami_id:
        image_name = '{i}_migration_{t}'.format(i=instance_id, t=timestamp)
        log.info('Creating the image for instance ID [{i}] with name: {n}'.format(i=instance_id, n=image_name))
        try:
            image_id = ec2.create_image(instance_id=instance_id, image_name=image_name)
        except EC2UtilError as exc:
            msg = 'Problem creating image for instance ID [{i}] with name[{n}]\n{e}'.format(
                i=instance_id, n=image_name, e=str(exc))
            log.error(msg)
            return False

        # Wait for the image to create
        log.info('Waiting for the image ID {w} to become available...'.format(w=image_id))
        if not ec2.wait_for_image_available(ami_id=image_id, timeout_sec=3600):
            log.error('AMI ID [{i}] did not reach the available state'.format(i=image_id))
            return False

        # Wait 5 seconds
        log.info('Waiting 5 seconds....')
        time.sleep(5)
    else:
        image_id = ami_id
        log.info('Using user-provided AMI ID: {i}'.format(i=image_id))

    # Terminate the original instance
    log.info('Terminating instance ID: {i}'.format(i=instance_id))
    try:
        _, current_state, previous_state = ec2.terminate_instance(instance_id=instance_id)
    except EC2UtilError as exc:
        msg = 'Problem terminating instance ID: {i}\n{e}'.format(i=instance_id, e=str(exc))
        log.error(msg)
        return False
    log.info('Instance state transitioning from [{p}] to [{c}]'.format(p=previous_state, c=current_state))

    # Wait for the instance to reach the terminated state
    log.info('Waiting for instance ID {i} to reach the terminated state'.format(i=instance_id))
    if not ec2.wait_for_instance_terminated(instance_id=instance_id):
        log.error('EC2 instance did not reach the terminated state')
        return False

    # Wait 5 seconds
    log.info('Waiting 5 seconds....')
    time.sleep(5)

    # Re-create any terminated NICs and format the list of network interfaces to attach
    attach_nics = []
    for network_interface in network_interfaces:
        if 'NetworkInterfaceId' not in network_interface.keys():
            log.error('NetworkInterfaceId not found in network interface data: {d}'.format(d=str(network_interface)))
            return False
        if 'PrivateIpAddress' not in network_interface.keys():
            log.error('PrivateIpAddress not found in network interface data: {d}'.format(
                d=str(network_interface)))
            return False
        if 'SubnetId' not in network_interface.keys():
            log.error('SubnetId not found in network interface data: {d}'.format(
                d=str(network_interface)))
            return False
        if 'Groups' not in network_interface.keys():
            log.error('Groups not found in network interface data: {d}'.format(
                d=str(network_interface)))
            return False
        if 'Attachment' not in network_interface.keys():
            log.error('Attachment not found in network interface data: {d}'.format(d=str(network_interface)))
            return False
        if 'DeviceIndex' not in network_interface['Attachment'].keys():
            log.error('Attachment not found in network interface attachment data: {d}'.format(
                d=str(network_interface['Attachment'])))
            return False

        # Get required data
        current_nic_id = network_interface['NetworkInterfaceId']
        nic_private_ip_address = network_interface['PrivateIpAddress']
        nic_subnet_id = network_interface['SubnetId']
        nic_device_index = network_interface['Attachment']['DeviceIndex']
        nic_security_groups = network_interface['Groups']

        # Get a list of security group IDs for the NIC
        nic_security_group_ids = []
        for nic_security_group in nic_security_groups:
            nic_security_group_ids.append(nic_security_group['GroupId'])

        # Check if the eni exists
        if ec2.ensure_exists(resource_id=network_interface['NetworkInterfaceId'], timeout_sec=20):
            log.info('Attaching network interface ID that still exists: {i}'.format(
                i=network_interface['NetworkInterfaceId']))
            attach_nics.append({
                'NetworkInterfaceId': current_nic_id,
                'DeviceIndex': nic_device_index,
                'DeleteOnTermination': False
            })
        else:
            log.info('Network interface [{i}] was deleted, creating a new one to attach...'.format(
                i=network_interface['NetworkInterfaceId']))
            new_nic = ec2.create_network_interface(
                subnet_id=nic_subnet_id,
                private_ip_address=nic_private_ip_address,
                security_group_list=nic_security_group_ids
            )
            if 'NetworkInterfaceId' not in new_nic:
                log.error('NetworkInterfaceId not found in the new network interface data: {d}'.format(d=str(new_nic)))
                return False
            new_nic_id = new_nic['NetworkInterfaceId']
            log.info('Created new network interface to attach: {i}'.format(i=new_nic_id))
            attach_nics.append({
                'NetworkInterfaceId': new_nic_id,
                'DeviceIndex': nic_device_index,
                'DeleteOnTermination': False
            })

    # Launch the instance onto the host
    log.info('Launching the instance from image [{i}] on to the dedicated host: {h}'.format(i=image_id, h=host_id))
    try:
        new_instance = ec2.launch_instance_onto_dedicated_host(
            ami_id=image_id,
            host_id=host_id,
            key_name=key_name,
            instance_type=size,
            network_interfaces=attach_nics,
            os_type=os_type,
            nat=nat
        )
    except EC2UtilError as exc:
        msg = 'Problem launching instance from image [{i}] on to dedicated host: {h}\n{e}'.format(
            i=image_id, h=host_id, e=str(exc))
        log.error(msg)
        return False
    if 'InstanceId' not in new_instance.keys():
        msg = 'InstanceId not found in instance data: {d}'.format(d=str(new_instance))
        log.error(msg)
        return False
    new_instance_id = new_instance['InstanceId']
    log.info('Created new instance ID: {i}'.format(i=new_instance_id))

    # Wait 5 seconds
    log.info('Waiting 5 seconds to proceed...')
    time.sleep(5)

    # Add the original instance tags to the new instance
    log.info('Adding tags to the new instance ID: {i}'.format(i=new_instance_id))
    try:
        ec2.create_tags(resource_id=new_instance_id, tags=tags)
    except EC2UtilError as exc:
        msg = 'There was a problem adding tags to the new image ID: {i}\n{e}\n\nTags: {t}'.format(
            i=new_instance_id, e=str(exc), t=tags)
        log.error(msg)
        return False

    # Wait for instance availability
    if not ec2.wait_for_instance_availability(instance_id=new_instance_id):
        msg = 'Instance did not become available: {i}'.format(i=new_instance_id)
        raise EC2UtilError(msg)
    log.info('Instance ID [{i}] is available and passed all checks'.format(i=new_instance_id))

    # Set the source/dest checks to disabled/False for NAT instances only
    if nat:
        log.info('Disabling the source/destination checks for a NAT host')
        try:
            ec2.set_instance_source_dest_check(instance_id=new_instance_id, source_dest_check=False)
        except EC2UtilError as exc:
            msg = 'Problem setting NAT instance ID [{i}] source/destination check to disabled'.format(i=new_instance_id)
            raise EC2UtilError(msg) from exc
        log.info('Set NAT instance ID [{i}] source/destination check to disabled'.format(i=new_instance_id))

    log.info('Completed migrating instance ID [{s}] to new instance ID [{i}] to host ID: {h}'.format(
        s=instance_id, i=new_instance_id, h=host_id))
    return True


def migrate_ec2_instances_to_host(instance_ids, host_id, size, os_type=None, ami_id=None, nat=False):
    """Migrate a list of instance IDs to a specific host

    :param instance_ids: (list) of string instance IDs
    :param host_id: (str) host ID
    :param size: (str) instance type for the instance on the host
    :param os_type: (str) windows or linux
    :param ami_id: (str) ID of the AMI
    :param nat: (bool) Set True when migrating a NAT box
    :return: (bool) True if all instances migrated successfully, False otherwise
    """
    log = logging.getLogger(mod_logger + '.migrate_ec2_instances_to_host')

    if os_type:
        if not isinstance(os_type, str):
            log.error('os_type arg must be a string, found: {t}'.format(t=os_type.__class__.__name__))
            return False

        if os_type not in ['linux', 'windows']:
            log.error('os_type args must be set to windows or linux, found: {t}'.format(t=os_type))
            return False
        log.info('Using provided OS type: {t}'.format(t=os_type))
    else:
        log.info('OS type not provided, will determine it from instance data')

    # Get an EC2Util object for querying AWS
    ec2 = EC2Util(skip_is_aws=True)

    # Ensure the host exists
    if not ec2.ensure_exists(resource_id=host_id):
        msg = 'Host ID not found: {i}'.format(i=host_id)
        log.error(msg)
        return False

    # Get the host details
    try:
        host_details = ec2.get_host(host_id=host_id)
    except EC2UtilError as exc:
        msg = 'Problem retrieving details for host: {h}\n{e}'.format(h=host_id, e=str(exc))
        log.error(msg)
        return False

    if 'HostId' not in host_details.keys():
        msg = 'HostId not found in host details: {h}'.format(h=str(host_details))
        log.error(msg)
        return False
    host_id = host_details['HostId']

    # Ensure there is enough capacity on the host for the requested size
    try:
        host_size_capacity = ec2.get_host_capacity_for_instance_type(host_id=host_id, instance_type=size)
    except EC2UtilError as exc:
        msg = 'Problem determining host {h} capacity for size {s}\n{e}'.format(h=host_id, s=size, e=str(exc))
        log.error(msg)
        return False
    if host_size_capacity < len(instance_ids):
        msg = 'Host available capacity for size {s} on host {h} is {c}, need at least {r}'.format(
            s=size, h=host_id, c=str(host_size_capacity), r=str(len(instance_ids)))
        log.error(msg)
        return False

    log.info('Migrating instances [{i}] to host: {h}'.format(i=','.join(instance_ids), h=host_id))
    fail_count = 0

    for instance_id in instance_ids:
        if not migrate_ec2_instance_to_host(
                ec2=ec2,
                instance_id=instance_id,
                host_details=host_details,
                size=size,
                os_type=os_type,
                ami_id=ami_id,
                nat=nat
        ):
            log.error('Failed to migrate instance ID {i} on to host: {h}'.format(i=instance_id, h=host_id))
            fail_count += 1
        else:
            log.info('Migrated instance ID {i} on to host: {h}'.format(i=instance_id, h=host_id))

    if fail_count == 0:
        log.info('Completed [{n}] migrations successfully for instance IDs [{i}] on to host: {h}'.format(
            n=str(len(instance_ids)), i=','.join(instance_ids), h=host_id))
        return True
    else:
        log.error('Failed to migrate {n} out of {t} instances on to host: {h}'.format(
            n=str(fail_count), t=str(len(instance_ids)), h=host_id))
        return False


def main():
    parser = argparse.ArgumentParser(description='CONS3RT command line interface (CLI)')
    parser.add_argument('command', help='Command for the cons3rt CLI')
    parser.add_argument('subcommands', help='Optional command subtype', nargs='*')
    parser.add_argument('--ami', help='ID of the AMI to use in the restoration', required=False)
    parser.add_argument('--cloudtype', help='Type of cloud: [aws, azure, or vcloud]', required=True)
    parser.add_argument('--host', help='ID of the dedicated host', required=False)
    parser.add_argument('--id', help='ID of instance to move on/off a dedicated host', required=False)
    parser.add_argument('--ids', help='ID of instances to move on/off a dedicated host', required=False)
    parser.add_argument('--nat', help='Identifies the instance(s) as a NAT box', required=False, action='store_true')
    parser.add_argument('--ostype', help='Type of OS: [windows or linux]', required=False)
    parser.add_argument('--size', help='Instance type to use for the instance on the host', required=False)
    args = parser.parse_args()

    # Valid commands and subcommands
    valid_commands = ['on', 'off']
    valid_subcommands = []

    # String representation of valid commands
    valid_commands_str = 'Valid commands: {c}'.format(c=', '.join(map(str, valid_commands)))
    valid_subcommands_str = 'Valid subcommands: {c}'.format(c=', '.join(map(str, valid_subcommands)))

    # Get the command
    command = args.command.strip()
    if command not in valid_commands:
        print('Invalid command found [{c}]\n'.format(c=command) + valid_commands_str)
        return 1

    # Get the subcommands
    if args.subcommands:
        subcommands = args.subcommands
    else:
        subcommands = None

    # Get the AMI ID
    ami_id = None
    if args.ami:
        ami_id = args.ami

    # Get the cloud type
    cloud_type = None
    if args.cloudtype:
        cloud_type = args.cloudtype

    # Ensure the cloud type was specified
    if not cloud_type:
        print('ERROR: Please specify --cloudtype: aws, azure, or vcloud')

    # Get the OS type
    os_type = None
    if args.ostype:
        os_type = args.ostype

    # Ensure the cloud type was specified
    if not os_type:
        print('ERROR: Please specify --ostype: windows or linux')

    # Collect instance IDs from the args
    instance_ids = []
    if args.id:
        instance_ids += [args.id]
    if args.ids:
        instance_ids += args.ids.split(',')

    # Get the host ID
    host_id = None
    if args.host:
        host_id = args.host

    # Get the size
    size = None
    if args.size:
        size = args.size

    # Get whether this is a NAT box
    nat = False
    if args.nat:
        nat = True

    # Ensure host ID is valid
    if cloud_type == 'aws':
        if host_id:
            if not host_id.startswith('h-'):
                print('ERROR: Host ID should start wit h-****, found: {h}'.format(h=host_id))
                return 2

        # Ensure instance IDs are valid
        for instance_id in instance_ids:
            if not instance_id.startswith('i-'):
                print('ERROR: Instance ID should start wit i-****, found: {i}'.format(i=instance_id))
                return 3

    if args.command == 'on':
        if not host_id:
            print('The --host arg is required to move an instance on to the host')
            return 4
        if not size:
            print('The --size arg is required to move an instance on to the host')
            return 5
        if cloud_type == 'aws':
            if not migrate_ec2_instances_to_host(instance_ids=instance_ids, host_id=host_id, size=size,
                                                 os_type=os_type, ami_id=ami_id, nat=nat):
                return 6
    elif args.command == 'off':
        print('Migration off the dedicated host is not yet supported')
    else:
        print('Command is not yet supported: {c}'.format(c=args.command))
    print('Completed.')
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
