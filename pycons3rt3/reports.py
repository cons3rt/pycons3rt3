#!/usr/bin/env python3

"""Module: reports

This module generates reports of team deployment run hosts

"""
import datetime
import logging
import os
import yaml

from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.exceptions import Cons3rtApiError, Cons3rtReportsError
from pycons3rt3.logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.reports'

# Report directory
report_dir = os.path.join(os.path.expanduser('~'), 'cons3rt_reports')

# Data files
cons3rt_data_file = os.path.join(report_dir, 'cons3rt_tmp_data.yml')


def generate_team_report(team_id, load=False):
    """Generates reports for the specified team ID

    :param team_id: (int) ID of the team
    :param load: (bool) Set True to load CONS3RT data from the local cons3rt_data_file, False to generate new data
    :return: None
    :raises: Cons3rtReportsError
    """
    log = logging.getLogger(mod_logger + '.generate_team_report')
    try:
        team_id = int(team_id)
    except ValueError:
        msg = 'Team ID provided is not a valid integer: {t}'.format(t=team_id)
        raise Cons3rtReportsError(msg)
    log.info('Generating team VM tally for team ID: {t}'.format(t=str(team_id)))

    if not os.path.isdir(report_dir):
        os.makedirs(report_dir, exist_ok=True)

    if load:
        cons3rt_vm_data = read_cons3rt_data()
    else:
        cons3rt_vm_data = generate_cons3rt_data(team_id=team_id)
        save_cons3rt_data(cons3rt_vm_data)
    if not cons3rt_vm_data:
        msg = 'Problem retrieving CONS3RT data'
        raise Cons3rtReportsError(msg)
    if len(cons3rt_vm_data) < 1:
        msg = 'No CONS3RT VMs found'
        raise Cons3rtReportsError(msg)
    # Generate the output
    generate_cons3rt_output(team_id=team_id, cons3rt_data=cons3rt_vm_data)
    log.info('Completed team VM tally for team ID: {i}'.format(i=team_id))


def generate_team_asset_report(team_id):
    """Generates reports for the specified team ID

    :param team_id: (int) ID of the team
    :return: None
    :raises: Cons3rtReportsError
    """
    log = logging.getLogger(mod_logger + '.generate_team_asset_report')
    try:
        team_id = int(team_id)
    except ValueError:
        msg = 'Team ID provided is not a valid integer: {t}'.format(t=team_id)
        raise Cons3rtReportsError(msg)
    log.info('Generating team VM tally for team ID: {t}'.format(t=str(team_id)))

    if not os.path.isdir(report_dir):
        os.makedirs(report_dir, exist_ok=True)

    asset_data = generate_team_asset_list(team_id=team_id)

    # Generate the output
    generate_asset_output(team_id=team_id, asset_data=asset_data)
    log.info('Completed team asset tally for team ID: {i}'.format(i=team_id))


def generate_cons3rt_data(team_id):
    """Returns data for the specified team ID

    :param team_id: (int) ID of the team
    :return: (list) of deployment run host data
    """
    log = logging.getLogger(mod_logger + '.generate_cons3rt_data')
    capi = Cons3rtApi()

    log.info('Retrieving team info for team ID: {i}'.format(i=str(team_id)))
    try:
        team_details = capi.get_team_details(team_id=team_id)
    except Cons3rtApiError as exc:
        msg = 'Problem retrieving team details for team ID: {i}'.format(i=str(team_id))
        raise Cons3rtReportsError(msg) from exc
    team_name = team_details['name']
    log.info('Retrieved details on team [{n}] with ID: {i}'.format(n=team_name, i=str(team_id)))

    log.info('Retrieving deployment run and host details for team ID: {i}'.format(i=str(team_id)))
    try:
        run_host_list = capi.list_host_details_in_team(team_id=team_id)
    except Cons3rtApiError as exc:
        msg = 'Problem getting a list of runs and hosts in team ID: {i}'.format(i=str(team_id))
        raise Cons3rtReportsError(msg) from exc

    # Get data from output
    log.info('Generating output from DR host...')
    drh_data = []
    for run_host_data in run_host_list:
        dr_details = run_host_data['run']
        custom_props = capi.retrieve_custom_properties_from_deployment_run_details(dr_details=dr_details)
        dep_props_str = ''
        if custom_props:
            for dep_prop in custom_props:
                dep_props_str += '{k}={v} '.format(k=dep_prop['key'], v=dep_prop['value'])
        else:
            log.info('No custom props found for run')
        for drh_details in run_host_data['hosts']:
            storage_mb = 0
            for disk in drh_details['disks']:
                storage_mb += disk['capacityInMegabytes']
            storage_gb = storage_mb / 1024
            network_str = ''
            if 'networkInterfaces' in drh_details.keys():
                for network in drh_details['networkInterfaces']:
                    network_str += network['networkName'] + '--' + network['internalIpAddress'] + ' '
            else:
                log.warning('networkInterfaces not found: {d}'.format(d=str(drh_details)))
            assets_str = ''
            if 'installations' in drh_details.keys():
                installations = sorted(drh_details['installations'], key=lambda k: k['loadOrder'])
                for installation in installations:
                    assets_str += '[{i}--{n}--{s}] '.format(
                        i=installation['assetId'],
                        n=installation['assetName'],
                        s=installation['status']
                    )
            else:
                log.warning('installations data not found in run host ID: {i}'.format(i=str(drh_details['id'])))
            system_role_str = ''
            if 'systemRole' in drh_details.keys():
                system_role_str = drh_details['systemRole']
            template_name = ''
            if 'physicalMachineOrTemplateName' in drh_details.keys():
                template_name = drh_details['physicalMachineOrTemplateName']
            drh_data.append(
                {
                    'team_id': team_id,
                    'team_name': team_name,
                    'project_id': dr_details['project']['id'],
                    'project_name': dr_details['project']['name'],
                    'cloudspace_id': dr_details['virtualizationRealm']['id'],
                    'cloudspace_name': dr_details['virtualizationRealm']['name'],
                    'dr_id': dr_details['id'],
                    'name': dr_details['name'],
                    'dr_status': dr_details['deploymentRunStatus'],
                    'dep_props': dep_props_str,
                    'host_id': drh_details['id'],
                    'hostname': drh_details['hostname'],
                    'system_role': system_role_str,
                    'host_status': drh_details['fapStatus'],
                    'template_name': template_name,
                    'cpus': drh_details['numCpus'],
                    'ram_mb': drh_details['ram'],
                    'storage_gb': storage_gb,
                    'networks': network_str,
                    'assets': assets_str
                }
            )
    log.info('Found {n} VMs in CONS3RT team: {t}'.format(n=str(len(drh_data)), t=str(team_id)))
    return drh_data


def generate_team_asset_list(team_id):
    """Returns software and container asset data for the specified team ID

    Assets used in currently active deployment runs.

    :param team_id: (int) ID of the team
    :return: (list) of assets used by the team:
    [
      {
        'id': ID,
        'name': NAME
      }
    ]
    """
    log = logging.getLogger(mod_logger + '.generate_team_asset_list')
    capi = Cons3rtApi()

    log.info('Retrieving team info for team ID: {i}'.format(i=str(team_id)))
    try:
        team_details = capi.get_team_details(team_id=team_id)
    except Cons3rtApiError as exc:
        msg = 'Problem retrieving team details for team ID: {i}'.format(i=str(team_id))
        raise Cons3rtReportsError(msg) from exc
    team_name = team_details['name']
    log.info('Retrieved details on team [{n}] with ID: {i}'.format(n=team_name, i=str(team_id)))

    log.info('Retrieving deployment run and host details for team ID: {i}'.format(i=str(team_id)))
    try:
        run_host_list = capi.list_host_details_in_team(team_id=team_id)
    except Cons3rtApiError as exc:
        msg = 'Problem getting a list of runs and hosts in team ID: {i}'.format(i=str(team_id))
        raise Cons3rtReportsError(msg) from exc

    # Generate the asset list
    asset_list = []
    for run_host_data in run_host_list:
        for drh_details in run_host_data['hosts']:
            if 'installations' in drh_details.keys():
                installations = sorted(drh_details['installations'], key=lambda k: k['loadOrder'])
                for installation in installations:
                    already_found = False
                    for asset in asset_list:
                        if asset['id'] == installation['assetId']:
                            already_found = True
                    if not already_found:
                        asset_list.append({
                            'id': installation['assetId'],
                            'name': installation['assetName']
                        })
            else:
                log.warning('installations data not found in run host ID: {i}'.format(i=str(drh_details['id'])))
    return asset_list


def generate_cons3rt_header():
    return 'TeamId,' \
           'TeamName,' \
           'ProjectId,' \
           'ProjectName,' \
           'CloudspaceId,' \
           'CloudspaceName,' \
           'RunId,' \
           'RunName,' \
           'RunStatus,' \
           'DeploymentProperties,' \
           'HostId,' \
           'Hostname,' \
           'SystemRole,' \
           'HostStatus,' \
           'OsTemplate,' \
           'Cpus,' \
           'RamMb,' \
           'StorageGb,' \
           'Networks,' \
           'Assets'


def generate_asset_header():
    return 'AssetId,AssetName'


def generate_cons3rt_row(cons3rt_vm):
    return str(cons3rt_vm['team_id']) + ',' + \
           str(cons3rt_vm['team_name']) + ',' + \
           str(cons3rt_vm['project_id']) + ',' + \
           str(cons3rt_vm['project_name']) + ',' + \
           str(cons3rt_vm['cloudspace_id']) + ',' + \
           cons3rt_vm['cloudspace_name'] + ',' + \
           str(cons3rt_vm['dr_id']) + ',' + \
           cons3rt_vm['name'] + ',' + \
           cons3rt_vm['dr_status'] + ',' + \
           cons3rt_vm['dep_props'] + ',' + \
           str(cons3rt_vm['host_id']) + ',' + \
           cons3rt_vm['hostname'] + ',' + \
           cons3rt_vm['system_role'] + ',' + \
           str(cons3rt_vm['host_status']) + ',' + \
           cons3rt_vm['template_name'] + ',' + \
           str(cons3rt_vm['cpus']) + ',' + \
           str(cons3rt_vm['ram_mb']) + ',' + \
           str(cons3rt_vm['storage_gb']) + ',' + \
           cons3rt_vm['networks'] + ',' + \
           cons3rt_vm['assets']


def generate_asset_row(asset_dict):
    return str(asset_dict['id']) + ',' + asset_dict['name']


def save_cons3rt_data(cons3rt_data):
    log = logging.getLogger(mod_logger + '.save_cons3rt_data')
    log.info('Saving cons3rt data to file: {f}'.format(f=cons3rt_data_file))
    if os.path.isfile(cons3rt_data_file):
        os.remove(cons3rt_data_file)
    with open(cons3rt_data_file, 'w') as f:
        yaml.dump(cons3rt_data, f, sort_keys=True)


def read_cons3rt_data():
    log = logging.getLogger(mod_logger + '.save_cons3rt_data')
    log.info('Reading cons3rt data from file: {f}'.format(f=cons3rt_data_file))
    with open(cons3rt_data_file, 'r') as f:
        return yaml.load(f, Loader=yaml.FullLoader)


def generate_cons3rt_output(team_id, cons3rt_data):
    log = logging.getLogger(mod_logger + '.generate_cons3rt_output')
    csv = str(generate_cons3rt_header()) + '\n'
    for cons3rt_vm in cons3rt_data:
        csv += generate_cons3rt_row(cons3rt_vm=cons3rt_vm) + '\n'
    report_time = datetime.datetime.now()
    report_timestamp = report_time.strftime('%Y%m%d-%H%M%S')
    output_file_name = 'team_{t}_data_{s}.csv'.format(t=str(team_id), s=str(report_timestamp))
    output_file_path = os.path.join(report_dir, output_file_name)
    if os.path.isfile(output_file_path):
        log.info('Removing existing output file: {f}'.format(f=output_file_path))
        os.remove(output_file_path)
    log.info('Generating output file: {f}'.format(f=output_file_path))
    with open(output_file_path, 'w') as f:
        f.write(csv)


def generate_asset_output(team_id, asset_data):
    log = logging.getLogger(mod_logger + '.generate_asset_output')
    csv = str(generate_asset_header()) + '\n'
    for asset_dict in asset_data:
        csv += generate_asset_row(asset_dict=asset_dict) + '\n'
    report_time = datetime.datetime.now()
    report_timestamp = report_time.strftime('%Y%m%d-%H%M%S')
    output_file_name = 'team_{t}_asset_data_{s}.csv'.format(t=str(team_id), s=str(report_timestamp))
    output_file_path = os.path.join(report_dir, output_file_name)
    if os.path.isfile(output_file_path):
        log.info('Removing existing output file: {f}'.format(f=output_file_path))
        os.remove(output_file_path)
    log.info('Generating output file: {f}'.format(f=output_file_path))
    with open(output_file_path, 'w') as f:
        f.write(csv)
