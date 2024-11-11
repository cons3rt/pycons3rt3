#!/usr/bin/env python3
"""
Prints statistics on dedicated host usage in an AWS account/region

"""

import datetime
import json
import logging
import sys
import traceback
from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.ec2util import EC2Util
from pycons3rt3.exceptions import Cons3rtApiError, EC2UtilError
from pycons3rt3.logify import Logify

# Set up logger name for this module
mod_logger = Logify.get_name() + '.aws_dedicated_hosts_report'


# Instance type cpu mappings
instance_type_cpu = {
    'c5.large': 2,
    'c5.xlarge': 4,
    'c5.2xlarge': 8,
    'c5.4xlarge': 16,
    'c5a.large': 2,
    'c5d.4xlarge': 16,
    'c6i.4xlarge': 16,
    'c6in.4xlarge': 16,
    'm5.xlarge': 4,
    'm5.2xlarge': 8,
    't2.nano': 1,
    't3.micro': 2,
    't3.medium': 2
}

# Instance type cpu mappings
instance_type_ram_gb = {
    'c5.large': 4,
    'c5.xlarge': 8,
    'c5.2xlarge': 16,
    'c5.4xlarge': 32,
    'c5a.large': 4,
    'c5d.4xlarge': 32,
    'c6i.4xlarge': 32,
    'c6in.4xlarge': 32,
    'm5.xlarge': 16,
    'm5.2xlarge': 32,
    't2.nano': 1,
    't3.micro': 1,
    't3.medium': 4
}


def write_report(report):
    """Outputs the report to the current dir

    :param report: (dict)
    :return: None
    """
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file_name = 'dedicated_host_report_' + timestamp + '.json'
    json.dump(report, open(report_file_name, 'w'), sort_keys=True, indent=2, separators=(',', ': '))


def main():
    log = logging.getLogger(mod_logger + '.main')

    # Create a EC2Util object
    ec2 = EC2Util()

    # Create a cons3rt API object
    c = Cons3rtApi()

    # Get the list of instances
    log.info('Getting a list of instances...')
    try:
        instances = ec2.get_instances()
    except EC2UtilError as exc:
        print('There was a problem retrieving the list of instances from EC2\n{e}\n{t}'.format(
            e=str(exc), t=traceback.print_exc()
        ))
        return 1

    log.info('Found {n} EC2 instances'.format(n=str(len(instances))))

    """
    report = {
        'None': {
            'type_counts': {
                'm5.xlarge': 1,
                'm5.large': 3,
            }
            'instances': [
            {
                'id': 'i-12345',
                'size': 'm5.xlarge',
                'state': 'running',
                'name': 'dr12345',
                'nat': False,
                'remote_access': False,
                'cons3rt_run_name': 'Test',
                'cons3rt_cpus': cons3rt_cpus,
                'cons3rt_ram_gb': cons3rt_ram_gb,
                'aws_cpus': aws_cpus,
                'aws_ram_gb': aws_ram_gb
            }
        ],
        },
        'h-12345': [
            {
                'id': 'i-12345',
                'size': 'm5.xlarge',
                'state': 'running',
                'name': 'dr12345',
                'nat': False,
                'remote_access': False,
                'cons3rt_run_name': 'Test',
                'cons3rt_cpus': cons3rt_cpus,
                'cons3rt_ram_gb': cons3rt_ram_gb,
                'aws_cpus': aws_cpus,
                'aws_ram_gb': aws_ram_gb
            }
        ]
    }
    """

    # Keeps track of the instances and what hosts they belong to
    report = {
        'None': {
            'instances': [],
            'type_counts': {}
        },
        'type_total_counts': {}
    }

    # Keep track of a list of host IDs
    host_ids = []

    # Keep track of the number of NATs
    nat_count = 0

    # Keep track of the not running instances
    not_running_count = 0

    # Keep track of the number of remote access instances
    remote_access_count = 0

    # Keep track of the instances that are deployment runs by listing the names
    deployment_runs = []

    # Keep track of the list of CONS3RT deployment run hosts with an instance type that does not match
    instance_type_discrepancies = []
    missing_instance_type_info = []

    # Keep track of the list of non-RA, non-NAT instances that are NOT on a dedicated host
    non_ra_non_nat_non_dedicated_host_instance_names = []

    # Keep track of the number of orphan DR hosts in AWS
    orphan_drhs = []

    # Keep track of total CPU and RAM
    total_cpu = 0
    total_ram_gb = 0

    # Keep track of CONS3RT non-remote-access deployment run CPU and RAM
    cons3rt_deployment_run_cpu = 0
    cons3rt_deployment_run_ram = 0

    # Keep track of AWS non-remote-access deployment run CPU and RAM
    aws_deployment_run_cpu = 0
    aws_deployment_run_ram = 0

    # Check instances and populate a list of hosts
    for instance in instances:
        # Check instance for required data
        if 'InstanceId' not in instance.keys():
            log.warning('InstanceId not found in instance data: {d}'.format(d=str(instance)))
            continue
        if 'InstanceType' not in instance.keys():
            log.warning('InstanceType not found in instance data: {d}'.format(d=str(instance)))
            continue
        if 'State' not in instance.keys():
            log.warning('State not found in instance data: {d}'.format(d=str(instance)))
            continue
        if 'Name' not in instance['State'].keys():
            log.warning('Name not found in instance State data: {d}'.format(d=str(instance['State'])))
            continue
        if 'Tags' not in instance.keys():
            log.warning('Tags not found in instance data: {d}'.format(d=str(instance)))
            continue
        if 'Placement' not in instance.keys():
            log.warning('Placement not found in instance data: {d}'.format(d=str(instance)))
            continue

        # Get the name tag
        instance_name = None
        for tag in instance['Tags']:
            if tag['Key'] == 'Name':
                instance_name = tag['Value']

        # Determine if this is a NAT box
        is_nat = False
        if 'nat' in instance_name:
            log.info('Found NAT box: {n}'.format(n=instance_name))
            nat_count += 1
            is_nat = True
        else:
            log.info('Found deployment run: {n}'.format(n=instance_name))
            deployment_runs.append(instance_name)

        # Add to the not-running count
        if instance['State']['Name'] != 'running':
            not_running_count += 1

        # Warn if instance name not found
        if not instance_name:
            log.warning('Name not found for instance ID: {i}'.format(i=instance['InstanceId']))
            continue

        # Add to the total type counts
        log.info('Adding total count for instance type: {t}'.format(t=instance['InstanceType']))
        if instance['InstanceType'] in report['type_total_counts'].keys():
            report['type_total_counts'][instance['InstanceType']] += 1
        else:
            report['type_total_counts'][instance['InstanceType']] = 1

        # Default value for remote access
        is_remote_access = False

        # Default value for cons3rt run name
        cons3rt_run_name = 'NAT'

        # Default CPU and RAM values for CONS3RT
        cons3rt_cpus = 0
        cons3rt_ram_gb = 0

        # Get the AWS CPU and RAM
        aws_cpus = instance_type_cpu[instance['InstanceType']]
        aws_ram_gb = instance_type_ram_gb[instance['InstanceType']]

        # Add to the totals
        total_cpu += aws_cpus
        total_ram_gb += aws_ram_gb

        # Get a CONS3RT run ID
        if not is_nat:
            if not instance_name.startswith('dr'):
                log.warning('Deployment run should start with dr: {d}'.format(d=instance_name))
                continue
            cons3rt_run_id = instance_name.lstrip('dr').split('v')[0]
            try:
                cons3rt_run_id = int(cons3rt_run_id)
            except ValueError as exc:
                log.warning('Unable to convert run ID to an int: {i}\n{e}'.format(i=cons3rt_run_id, e=str(exc)))
                continue

            log.info('Querying deployment run ID: {i}'.format(i=str(cons3rt_run_id)))
            try:
                cons3rt_run_info = c.retrieve_deployment_run_details(dr_id=cons3rt_run_id)
            except Cons3rtApiError as exc:
                msg = 'Problem getting details for deployment run: {i}\n{e}'.format(i=str(cons3rt_run_id), e=str(exc))
                log.warning(msg)
                orphan_drhs.append(instance_name)
                continue

            # Ensure name is in the DR info
            if 'name' not in cons3rt_run_info.keys():
                log.warning('name not found in deployment run info: {r}'.format(r=str(cons3rt_run_info)))
                continue
            cons3rt_run_name = cons3rt_run_info['name']

            # Check if this is remote access
            if 'RemoteAccess' in cons3rt_run_name:
                remote_access_count += 1
                is_remote_access = True

            # Ensure deploymentRunHosts data is included
            if 'deploymentRunHosts' not in cons3rt_run_info.keys():
                log.warning('deploymentRunHosts not found in run info: {r}'.format(r=str(cons3rt_run_info)))
                continue

            # Check each host in the run for the matching host name to get the host ID
            cons3rt_host_id = None
            for host in cons3rt_run_info['deploymentRunHosts']:
                if 'id' not in host.keys():
                    continue
                if 'hostname' not in host.keys():
                    continue
                if host['hostname'] == instance_name:
                    cons3rt_host_id = host['id']
                    log.info('Found matching CONS3RT host ID for [{n}]: {i}'.format(
                        n=instance_name, i=str(cons3rt_host_id)))
                    break

            # Ensure cons3rt_host_id was found
            if not cons3rt_host_id:
                log.warning('CONS3RT host ID not found for instance named: {n}'.format(n=instance_name))
                continue

            # Query the CONS3RT host info to compare with AWS
            log.info('Querying CONS3RT for host ID: {i}'.format(i=str(cons3rt_host_id)))
            try:
                cons3rt_host_info = c.retrieve_deployment_run_host_details(dr_id=cons3rt_run_id, drh_id=cons3rt_host_id)
            except Cons3rtApiError as exc:
                log.warning('Problem retrieving CONS3RT info on host: {i}\n{e}'.format(
                    i=str(cons3rt_host_id), e=str(exc)))
                continue

            if 'numCpus' not in cons3rt_host_info.keys():
                log.warning('numCpus not found in cons3rt host info: {d}'.format(d=str(cons3rt_host_info)))
                continue
            if 'ram' not in cons3rt_host_info.keys():
                log.warning('ram not found in cons3rt host info: {d}'.format(d=str(cons3rt_host_info)))
                continue

            # Set the CONS3RT CPU and RAM
            cons3rt_cpus = cons3rt_host_info['numCpus']
            cons3rt_ram_gb = cons3rt_host_info['ram'] / 1024

            # Check if there is a discrepancy in CONS3RT and AWS on instance type
            if 'instanceTypeName' in cons3rt_host_info.keys():
                if cons3rt_host_info['instanceTypeName'] != instance['InstanceType']:
                    log.warning('Instance type in CONS3RT [{c}] does not match the instance type in AWS [{a}]'.format(
                        c=cons3rt_host_info['instanceTypeName'], a=instance['InstanceType']
                    ))
                    instance_type_discrepancies.append(instance_name + ' - ' + cons3rt_run_name)
                else:
                    log.info('AWS and CONS3RT instance types match for [{n}]: {t}'.format(
                        n=instance_name, t=instance['InstanceType']))
            else:
                log.warning('instanceTypeName not found in cons3rt host for instance: {i}'.format(i=instance_name))
                missing_instance_type_info.append(instance_name + ' - ' + cons3rt_run_name)

            # Count non-remote-access CPU and RAM
            if not is_remote_access:
                aws_deployment_run_cpu += aws_cpus
                aws_deployment_run_ram += aws_ram_gb
                cons3rt_deployment_run_cpu += cons3rt_cpus
                cons3rt_deployment_run_ram += cons3rt_ram_gb

        if 'HostId' not in instance['Placement']:
            report['None']['instances'].append(
                {
                    'id': instance['InstanceId'],
                    'size': instance['InstanceType'],
                    'state': instance['State']['Name'],
                    'name': instance_name,
                    'nat': is_nat,
                    'remote_access': is_remote_access,
                    'cons3rt_run_name': cons3rt_run_name,
                    'cons3rt_cpus': cons3rt_cpus,
                    'cons3rt_ram_gb': cons3rt_ram_gb,
                    'aws_cpus': aws_cpus,
                    'aws_ram_gb': aws_ram_gb
                }
            )

            # Check for the instance size and add it to the count
            log.info('Adding count for instance type: {t}'.format(t=instance['InstanceType']))
            if instance['InstanceType'] in report['None']['type_counts'].keys():
                report['None']['type_counts'][instance['InstanceType']] += 1
            else:
                report['None']['type_counts'][instance['InstanceType']] = 1

            # Add this to the list of non-RA non-NAT instances that are NOT on dedicated hosts
            if not is_nat and not is_remote_access:
                log.warning('Found a DR that is not on a dedicated host: {n}'.format(n=instance_name))
                non_ra_non_nat_non_dedicated_host_instance_names.append(instance_name + ' - ' + cons3rt_run_name)
        else:
            # Create an entry for the host if noe does not exist
            if instance['Placement']['HostId'] not in report.keys():
                log.info('Adding host to report: {h}'.format(h=instance['Placement']['HostId']))
                report[instance['Placement']['HostId']] = {
                    'instances': [],
                    'type_counts': {}
                }

            # Add the host to the list of host IDs
            if instance['Placement']['HostId'] not in host_ids:
                host_ids.append(instance['Placement']['HostId'])

            # Append this instance to the report for the host
            report[instance['Placement']['HostId']]['instances'].append(
                {
                    'id': instance['InstanceId'],
                    'size': instance['InstanceType'],
                    'state': instance['State']['Name'],
                    'name': instance_name,
                    'nat': is_nat,
                    'remote_access': is_remote_access,
                    'cons3rt_run_name': cons3rt_run_name,
                    'cons3rt_cpus': cons3rt_cpus,
                    'cons3rt_ram_gb': cons3rt_ram_gb,
                    'aws_cpus': aws_cpus,
                    'aws_ram_gb': aws_ram_gb
                }
            )

            # Check for the instance size and add it to the count
            log.info('Adding count for instance type: {t}'.format(t=instance['InstanceType']))
            if instance['InstanceType'] in report[instance['Placement']['HostId']]['type_counts'].keys():
                report[instance['Placement']['HostId']]['type_counts'][instance['InstanceType']] += 1
            else:
                report[instance['Placement']['HostId']]['type_counts'][instance['InstanceType']] = 1

    # Print instances not on dedicated hosts
    for instance in report['None']['instances']:
        log.info('Found instance not on a dedicated host with ID [{i}]: {n}'.format(
            i=instance['id'], n=instance['name']))

    # Add/print deployment run hosts that have instance type discrepancies
    report['discrepancies'] = []
    for instance_name in instance_type_discrepancies:
        log.warning('This instance has a discrepancy on instance type in CONS3RT: {n}'.format(n=instance_name))
        report['discrepancies'].append(instance_name)

    # Add/print deployment run hosts missing instance type data
    report['missing_instance_type'] = []
    for instance_name in missing_instance_type_info:
        log.warning('This instance is missing instance type in CONS3RT: {n}'.format(n=instance_name))
        report['missing_instance_type'].append(instance_name)

    # Add/print list of actual DRs that are not on dedicated hosts
    report['drhs_not_on_dedicated_hosts'] = []
    for instance_name in non_ra_non_nat_non_dedicated_host_instance_names:
        log.warning('DR that is not on a dedicated host: {n}'.format(n=instance_name))
        report['drhs_not_on_dedicated_hosts'].append(instance_name)

    # Add/print a list of orphan deployment run  hosts
    report['orphan_drhs'] = []
    for instance_name in orphan_drhs:
        log.warning('This instance is orphaned, not found in CONS3RT: {n}'.format(n=instance_name))
        report['orphan_drhs'].append(instance_name)

    # Print info
    log.info('Found {n} NAT boxes'.format(n=str(nat_count)))
    log.info('Found {n} remote access boxes'.format(n=str(remote_access_count)))
    log.info('Found {n} instances not running'.format(n=str(not_running_count)))
    log.info('Found {n} total number of instances'.format(n=str(len(instances))))
    log.info('Found {n} non-remote-access deployment run AWS CPUs'.format(n=str(aws_deployment_run_cpu)))
    log.info('Found {n} non-remote-access deployment run AWS RAM in GB'.format(n=str(aws_deployment_run_ram)))
    log.info('Found {n} non-remote-access deployment run CONS3RT CPUs'.format(n=str(cons3rt_deployment_run_cpu)))
    log.info('Found {n} non-remote-access deployment run CONS3RT RAM in GB'.format(
        n=str(cons3rt_deployment_run_ram)))
    log.info('Found {n} total CPU'.format(n=str(total_cpu)))
    log.info('Found {n} total RAM GBs'.format(n=str(total_ram_gb)))

    # Add additional data to the report
    report['nat_count'] = nat_count
    report['remote_access_count'] = remote_access_count
    report['not_running_count'] = not_running_count
    report['total_instance_count'] = len(instances)
    report['total_aws_dr_non_ra_cpus'] = aws_deployment_run_cpu
    report['total_aws_dr_non_ra_ram'] = aws_deployment_run_ram
    report['total_cons3rt_dr_non_ra_cpus'] = cons3rt_deployment_run_cpu
    report['total_cons3rt_dr_non_ra_ram'] = cons3rt_deployment_run_ram
    report['total_cpu'] = total_cpu
    report['total_ram_gb'] = total_ram_gb

    # Output the JSON report
    write_report(report=report)
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
