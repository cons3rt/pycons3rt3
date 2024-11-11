#!/usr/bin/env python3
"""Module: remote_access_controller

This module is mainly for use by CONS3RT site admins to manage site-wide
remote access actions including:

* Setting/removing site-wide remote access run locks
* Enabling/disabling site-wide remote access
* Cloud-wide remote access actions
* Cloudspace-specific remote access actions

Usage:

ractl [level] [action] [args]

level =    'cloud', 'cloudspace', 'site'
action = 'enable', 'disable', 'lock', 'print', 'toggle', 'unlock'
args =
    --access           Cloudspace access point IP address
    --delay            Override the default delay between remote access actions
    --id               Cloud or cloudspace ID to take action on
    --ids              Comma separated list of cloud or cloudspace ID to take action on
    --ip               Remote access server internal IP address
    --load             Load outputted data from the previous attempt
    --nordp            DISABLE RDP Proxy in the cloudspace
    --port             Cloudspace external remote access server port
    --skip             List of cloudspace IDs to skip acting upon
    --slackchannel     Slack channel to report status to
    --slackurl         Slack URL to report status to
    --unlock           Force unlock RA runs


# Print out cloudspace RA data to ~/cons3rt_reports/remote_access_data.csv

$ ractl site print
$ ractl cloud print --ids 22,24
$ ractl cloudspace print --ids 138,140

# Load data from the prior execution from ~/cons3rt_reports/remote_access_data.csv

$ ractl cloudspace print --ids 138,140 --load

# Disable/toggle remote access site-wide, add --unlock to force unlocking the RA DRs

$ ractl site disable
$ ractl site disable --unlock
$ ractl site disable --unlock --load

# Same for a list of cloud or cloudspace IDs

$ ractl cloud disable --id 22
$ ractl cloudspace toggle --unlock --ids 1,2,3
$ ractl cloud toggle --id 7 --unlock --load

"""

import argparse
import logging
import os
import sys
import time
import traceback

from .network import validate_ip_address
from .cons3rtapi import Cons3rtApi, Cons3rtApiError
from .cons3rtcli import validate_ids
from .cons3rtconfig import get_report_dir
from .logify import Logify
from .slack import SlackAttachment, SlackMessage


# Set up logger name for this module
mod_logger = Logify.get_name() + '.remoteaccesscontroller'

# Output File
out_file = os.path.join(get_report_dir(), 'remote_access_data.csv')

valid_levels = ['cloud', 'cloudspace', 'site']
valid_levels_str = ','.join(valid_levels)

valid_actions = ['enable', 'disable', 'lock', 'print', 'toggle', 'unlock']
valid_actions_str = ','.join(valid_actions)

# Default time between enabling/disabling remote access for a cloudspace
default_cloudspace_wait_time_sec = 180


class RemoteAccessControllerError(Exception):
    pass


class LockedStatus(object):
    """Enum for tracking RA run locked status"""
    LOCKED = 'LOCKED'
    UNLOCKED = 'UNLOCKED'


class EnabledStatus(object):
    """Enum for tracking cloudspace RA enabled status"""
    ENABLED = 'ENABLED'
    DISABLED = 'DISABLED'


class EnabledRemoteAccess(object):
    def __init__(self, cloud_id, cloud_name, cloud_type, cloudspace_id, cloudspace_name, cloudspace_status,
                 enabled=None, run_id=None, run_name=None, run_status=None, dep_id=None, instance_type=None,
                 locked_status=None, access_point_ip=None, boundary_ip=None, guac_ip_address=None,
                 remote_access_port=None, rdp_proxy_enabled=None, size=None, template_name=None, user_count=None,
                 nat_instance_type=None):
        self.cloud_id = cloud_id
        self.cloud_name = cloud_name
        self.cloud_type = cloud_type
        self.cloudspace_id = cloudspace_id
        self.cloudspace_name = cloudspace_name
        self.cloudspace_status = cloudspace_status
        self.enabled = enabled
        self.run_id = run_id
        self.run_name = run_name
        self.run_status = run_status
        self.dep_id = dep_id
        self.instance_type = instance_type
        self.locked_status = locked_status
        self.access_point_ip = access_point_ip
        self.boundary_ip = boundary_ip
        self.guac_ip_address = guac_ip_address
        self.remote_access_port = remote_access_port
        self.rdp_proxy_enabled = rdp_proxy_enabled
        self.template_name = template_name
        self.user_count = user_count
        self.nat_instance_type = nat_instance_type

    @staticmethod
    def header_row():
        return ('CloudId,CloudName,CloudType,CloudspaceId,CloudspaceName,CloudspaceStatus,RaEnabledStatus,RaRunId,'
                'RaRunName,RaRunStatus,DepId,InstanceType,LockedStatus,AccessPointIp,BoundaryIp,GuacIp,GuacPort,'
                'RdpProxyEnabled,TemplateName,NatInstancetype,UserCount')

    def __str__(self):
        out_str = ''
        if self.cloud_id:
            out_str += str(self.cloud_id) + ','
        else:
            out_str += 'None,'
        if self.cloud_name:
            out_str += self.cloud_name + ','
        else:
            out_str += 'None,'
        if self.cloud_type:
            out_str += self.cloud_type + ','
        else:
            out_str += 'None,'
        if self.cloudspace_id:
            out_str += str(self.cloudspace_id) + ','
        else:
            out_str += 'None,'
        if self.cloudspace_name:
            out_str += self.cloudspace_name + ','
        else:
            out_str += 'None,'
        if self.cloudspace_status:
            out_str += self.cloudspace_status + ','
        else:
            out_str += 'None,'
        if self.enabled:
            out_str += self.enabled + ','
        else:
            out_str += 'None,'
        if self.run_id:
            out_str += str(self.run_id) + ','
        else:
            out_str += 'None,'
        if self.run_name:
            out_str += self.run_name + ','
        else:
            out_str += 'None,'
        if self.run_status:
            out_str += self.run_status + ','
        else:
            out_str += 'None,'
        if self.dep_id:
            out_str += self.dep_id + ','
        else:
            out_str += 'None,'
        if self.instance_type:
            out_str += self.instance_type + ','
        else:
            out_str += 'None,'
        if self.locked_status:
            out_str += 'ENABLED,'
        else:
            out_str += 'DISABLED,'
        if self.access_point_ip:
            out_str += self.access_point_ip + ','
        else:
            out_str += 'None,'
        if self.boundary_ip:
            out_str += self.boundary_ip + ','
        else:
            out_str += 'None,'
        if self.guac_ip_address:
            out_str += self.guac_ip_address + ','
        else:
            out_str += 'None,'
        if self.remote_access_port:
            out_str += str(self.remote_access_port) + ','
        else:
            out_str += 'None,'
        if self.rdp_proxy_enabled:
            out_str += str(self.rdp_proxy_enabled) + ','
        else:
            out_str += 'None,'
        if self.template_name:
            out_str += str(self.template_name) + ','
        else:
            out_str += 'None,'
        if self.nat_instance_type:
            out_str += str(self.nat_instance_type) + ','
        else:
            out_str += 'None,'
        if self.user_count:
            out_str += str(self.user_count)
        else:
            out_str += 'None'
        return out_str


class RemoteAccessController(object):

    def __init__(self, level, config=None, ids=None, slack_channel=None, slack_url=None, unlock=False, load_data=False,
                 skip_cloudspace_ids=None, delay_sec=None, ra_port=9443, ra_ip='172.16.10.253', rdp_proxy=True):
        self.cls_logger = mod_logger + '.RemoteAccessController'
        if level not in valid_levels:
            msg = 'Invalid level [{z}], must be: {c}'.format(z=level, c=valid_levels_str)
            raise RemoteAccessControllerError(msg)
        self.level = level
        self.config = config
        self.ids = ids
        self.load_data = load_data
        self.skip_cloudspace_ids = skip_cloudspace_ids
        self.slack_msg = None
        if slack_channel and slack_url:
            self.slack_msg = SlackMessage(
                slack_url,
                channel=slack_channel,
                text='Remote Access Controller'
            )
        self.unlock = unlock
        self.ra_port = ra_port
        self.ra_ip = ra_ip
        self.rdp_proxy = rdp_proxy

        # Determine the wait time
        if not delay_sec:
            self.cloudspace_wait_time_sec = default_cloudspace_wait_time_sec

        # Create a Cons3rtApi
        try:
            self.c5t = Cons3rtApi(config_file=self.config)
        except Cons3rtApiError as exc:
            raise RemoteAccessControllerError('There was a problem initializing Cons3rtApi') from exc

        # Lists of clouds, cloudspaces, and remote access run info
        self.clouds = []
        self.cloudspaces = []
        self.cloudspace_ids = []
        self.remote_access_run_info = []

    @staticmethod
    def append_remote_access_run(ra_run_data):
        """Appends RA run data to the out file

        """
        with open(out_file, 'a') as f:
            f.write(str(ra_run_data) + '\n')

    def disable_remote_access(self):
        """Disables remote access for all enabled cloudspaces found, does not unlock

        :return: None
        :raises: RemoteAccessControllerError
        """
        log = logging.getLogger(self.cls_logger + '.disable_remote_access')

        for enabled_ra in self.remote_access_run_info:

            # Skip cloudspaces on the skip list
            if enabled_ra.cloudspace_id in self.skip_cloudspace_ids:
                log.info('Skipping cloudspace ID {c}, it is on the skip list'.format(c=str(enabled_ra.cloudspace_id)))
                continue

            # Skip cloudspaces with RA already DISABLED or DISABLING
            if enabled_ra.enabled != 'ENABLED':
                log.info('Skipping toggling remote access, not currently enabled for cloudspace: {c}'.format(
                    c=str(enabled_ra.cloudspace_id)))
                continue

            # Disable remote access
            log.info('Attempting to disable remote access for cloudspace ID: {i}'.format(
                i=str(enabled_ra.cloudspace_id)))
            try:
                self.c5t.disable_remote_access(vr_id=enabled_ra.cloudspace_id)
            except Cons3rtApiError as exc:
                msg = 'Problem disabling remote access for cloudspace: {i}'.format(i=str(enabled_ra.cloudspace_id))
                raise RemoteAccessControllerError(msg) from exc
            log.info('Waiting {t} seconds before proceeding to the next cloudspace'.format(
                t=str(self.cloudspace_wait_time_sec)))
            time.sleep(self.cloudspace_wait_time_sec)

    def enable_remote_access(self, instance_type=None, guac_ip_address=None, remote_access_port=None,
                             rdp_proxy_enabled=True, access_point_ip=None):
        """Enables remote access the specified cloudspaces

        {
         "guacIpAddress": "172.16.10.253",
         "instanceType": "SMALL",
         "rdpProxyingEnabled": true,
         "remoteAccessPort": 9443,
         "retainOnError": true,
         "displayName": "remote-access",
         "type": "RemoteAccess"
        }

        :param: instance_type: (str) Size of the RA box SMALL|MEDIUM|LARGE

        :return: None
        :raises: RemoteAccessControllerError
        """
        log = logging.getLogger(self.cls_logger + '.enable_remote_access')

        for ra_info in self.remote_access_run_info:

            # Skip cloudspaces on the skip list
            if ra_info.cloudspace_id in self.skip_cloudspace_ids:
                log.info('Skipping cloudspace ID {c}, it is on the skip list'.format(c=str(ra_info.cloudspace_id)))
                continue

            # Skip cloudspaces with RA already ENABLED or ENABLING
            if ra_info.enabled in ['ENABLED', 'ENABLING']:
                log.info('Skipping toggling remote access, already enabled or enabling for cloudspace: {c}'.format(
                    c=str(ra_info.cloudspace_id)))
                continue

            # Track whether to update the cloudspace or RA config before enabling RA
            update_ra_config = False
            update_cloudspace = False

            # Check to see if access point needs to be updated
            if access_point_ip:
                if access_point_ip != ra_info.access_point_ip:
                    update_cloudspace = True

            """
            # Update the cloudspace if needed
            if update_cloudspace:
                log.info('Updating cloudspace [{c}] access point IP address to: [{i}]'.format(
                    c=ra_info.cloudspace_id, i=access_point_ip))
                try:
                    self.c5t.virtu
            """

            # Enable RA for the cloudspace
            log.info('Attempting to enable remote access for cloudspace ID: {i}'.format(
                i=str(ra_info.cloudspace_id)))
            try:
                self.c5t.enable_remote_access(
                    vr_id=ra_info.cloudspace_id,
                    rdp_proxy_enabled=rdp_proxy_enabled,
                    instance_type=instance_type,
                    guac_ip_address=guac_ip_address,
                    remote_access_port=remote_access_port
                )
            except Cons3rtApiError as exc:
                msg = 'Problem enabling remote access for cloudspace: {i}'.format(i=str(ra_info.cloudspace_id))
                raise RemoteAccessControllerError(msg) from exc

            # Wait to proceed on to the next cloudspace
            log.info('Waiting {t} seconds before proceeding to the next cloudspace'.format(
                t=str(self.cloudspace_wait_time_sec)))
            time.sleep(self.cloudspace_wait_time_sec)

    def get_cloudspace_data(self):
        """Populates the list with cloud and cloudspace data

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.get_cloudspace_data')

        # If a list of cloudspaces was provided, get details for cloudspaces on that list
        if self.level == 'cloudspace':
            self.cloudspace_ids = list(self.ids)
        else:
            # For the "site" level, set the ids list to all clouds in the site
            if self.level == 'site':
                try:
                    site_clouds = self.c5t.list_clouds()
                except RemoteAccessControllerError as exc:
                    msg = 'Problem listing clouds for the site'
                    raise RemoteAccessControllerError(msg) from exc

                for site_cloud in site_clouds:
                    if 'id' not in site_cloud.keys():
                        log.warning('id not found in cloud: [{d}]'.format(d=str(site_cloud)))
                        continue
                    self.ids.append(site_cloud.id)

            # Get the cloudspace IDs for all the cloud IDs
            for cloud_id in self.ids:
                try:
                    cloud_cloudspaces = self.c5t.list_virtualization_realms_for_cloud(cloud_id=cloud_id)
                except Cons3rtApiError as exc:
                    msg = 'Problem retrieving VRs for cloud ID: {i}'.format(i=str(cloud_id))
                    raise RemoteAccessControllerError(msg) from exc
                for cloud_cloudspace in cloud_cloudspaces:
                    if 'id' not in cloud_cloudspace.keys():
                        log.warning('id not found in cloudspace: [{d}]'.format(d=str(cloud_cloudspace)))
                        continue
                    self.cloudspace_ids.append(cloud_cloudspace['id'])

        # Loop through the cloudspaces and gather RA data
        for cloudspace_id in self.cloudspace_ids:

            # Check if cloudspace data already exists
            data_exists = False
            for ra_data in self.remote_access_run_info:
                if cloudspace_id == ra_data.cloudspace_id:
                    data_exists = True
            if data_exists:
                log.info('Found cloudspace data already for cloudspace: {i}'.format(i=str(cloudspace_id)))
                continue

            # Get the cloudspace details
            try:
                cloudspace = self.c5t.get_virtualization_realm_details(vr_id=cloudspace_id)
            except Cons3rtApiError as exc:
                msg = 'Problem getting cloudspace details for cloudspace: {i}'.format(i=str(cloudspace_id))
                raise RemoteAccessControllerError(msg) from exc
            self.cloudspaces.append(cloudspace)

            # Get the parent cloud details
            try:
                cloud_details = self.c5t.retrieve_cloud_details(cloud_id=cloudspace['cloud']['id'])
            except Cons3rtApiError as exc:
                msg = 'Problem getting details for cloud ID: {i}'.format(i=str(cloudspace['cloud']['id']))
                raise RemoteAccessControllerError(msg) from exc
            self.clouds.append(cloud_details)

            # Get the RA service details
            try:
                ra_service = self.c5t.get_remote_access_service(vr_id=cloudspace['id'])
            except Cons3rtApiError as exc:
                msg = 'Problem getting RA service details for cloudspace: {i}'.format(i=str(cloudspace['id']))
                raise RemoteAccessControllerError(msg) from exc

            # Get the cloudspace data
            cloudspace_id = 'UNKNOWN'
            cloudspace_name = 'UNKNOWN'
            cloudspace_state = 'UNKNOWN'
            ra_deployment_id = None
            nat_instance_type = None
            if 'id' in cloudspace.keys():
                cloudspace_id = cloudspace['id']
            if 'name' in cloudspace.keys():
                cloudspace_name = cloudspace['name']
            if 'state' in cloudspace.keys():
                cloudspace_state = cloudspace['state']
            if 'remoteAccessDeploymentId' in cloudspace.keys():
                ra_deployment_id = cloudspace['remoteAccessDeploymentId']
            if 'natInstanceType' in cloudspace.keys():
                nat_instance_type = cloudspace['natInstanceType']

            # Get the cloud data
            cloud_id = 'UNKNOWN'
            cloud_name = 'UNKNOWN'
            cloud_type = 'UNKNOWN'
            if 'cloud' in cloudspace.keys():
                if 'id' in cloudspace['cloud'].keys():
                    cloud_id = cloudspace['cloud']['id']
                if 'name' in cloudspace['cloud'].keys():
                    cloud_name = cloudspace['cloud']['name']
                if 'cloudType' in cloudspace['cloud'].keys():
                    cloud_type = cloudspace['cloud']['cloudType']

            # Get the remote access service data
            remote_access_ip = 'UNKNOWN'
            remote_access_port = 'UNKNOWN'
            rdp_proxy_enabled = 'UNKNOWN'
            template_name = None
            instance_type = None
            boundary_ip = 'UNKNOWN'
            access_point_ip = None
            ra_dr_id = None
            ra_dr_status = None
            ra_enabled_state = 'UNKNOWN'
            if 'guacIpAddress' in ra_service.keys():
                remote_access_ip = ra_service['guacIpAddress']
            if 'raConfigRemoteAccessPort' in ra_service.keys():
                remote_access_port = ra_service['raConfigRemoteAccessPort']
            if 'raConfigRdpProxyingEnabled' in ra_service.keys():
                rdp_proxy_enabled = ra_service['raConfigRdpProxyingEnabled']
            if 'instanceType' in ra_service.keys():
                instance_type = ra_service['instanceType']
            if 'raDrTemplateName' in ra_service.keys():
                template_name = ra_service['raDrTemplateName']
            if 'virtRealmCons3rtNetExternalIp' in ra_service.keys():
                boundary_ip = ra_service['virtRealmCons3rtNetExternalIp']
            if 'virtRealmAccessPoint' in ra_service.keys():
                access_point_ip = ra_service['virtRealmAccessPoint']
            if 'raDrId' in ra_service.keys():
                ra_dr_id = ra_service['raDrId']
            if 'raDrStatus' in ra_service.keys():
                ra_dr_status = ra_service['raDrStatus']
            if 'serviceStatus' in ra_service.keys():
                ra_enabled_state = ra_service['serviceStatus']

            # Get the user count for the cloudspace
            try:
                cloudspace_users = self.c5t.list_users_in_virtualization_realm(vr_id=cloudspace_id)
            except Cons3rtApiError as exc:
                msg = 'Problem listing users for cloudspace ID: {i}'.format(i=str(cloudspace_id))
                raise RemoteAccessControllerError(msg) from exc
            cloudspace_user_count = len(cloudspace_users)

            # Get the DR
            if ra_dr_id:
                locked = self.get_run_lock_status(run_id=ra_dr_id)
            else:
                locked = False

            # Add cloudspace data
            log.info('Adding cloudspace data for cloudspace ID: {i}'.format(i=str(cloudspace['id'])))
            self.remote_access_run_info.append(
                EnabledRemoteAccess(
                    cloud_id=cloud_id,
                    cloud_name=cloud_name,
                    cloud_type=cloud_type,
                    cloudspace_id=cloudspace_id,
                    cloudspace_name=cloudspace_name,
                    cloudspace_status=cloudspace_state,
                    enabled=ra_enabled_state,
                    run_id=ra_dr_id,
                    run_name=None,
                    run_status=ra_dr_status,
                    dep_id=ra_deployment_id,
                    instance_type=instance_type,
                    locked_status=locked,
                    access_point_ip=access_point_ip,
                    boundary_ip=boundary_ip,
                    guac_ip_address=remote_access_ip,
                    remote_access_port=remote_access_port,
                    rdp_proxy_enabled=rdp_proxy_enabled,
                    template_name=template_name,
                    nat_instance_type=nat_instance_type,
                    user_count=cloudspace_user_count
                )
            )
        log.info('Found {n} total cloudspaces'.format(n=str(len(self.remote_access_run_info))))

    def get_run_lock_status(self, run_id):
        """Returns the lock status for a run ID

        :param: run_id: (int) ID of the RA run
        :return: (bool) lock status or None
        """
        log = logging.getLogger(self.cls_logger + '.get_run_lock_status')
        log.info('Attempting to get run lock status for run ID: {i}'.format(i=str(run_id)))
        max_attempts = 10
        retry_sec = 5
        attempt_num = 0
        run_details = {}
        while True:
            if attempt_num >= max_attempts:
                log.error('Unable to run ID {i} lock status {n} attempts'.format(
                    n=str(max_attempts), i=str(run_id)))
                return
            try:
                run_details = self.c5t.retrieve_deployment_run_details(dr_id=run_id)
            except Cons3rtApiError as exc:
                log.warning('Problem retrieving retails for run ID: {i}\n{e}'.format(
                    i=str(run_id), e=str(exc)))
                attempt_num += 1
                log.info('Re-trying in {n} seconds...'.format(n=str(retry_sec)))
                time.sleep(retry_sec)
                continue
            else:
                break
        if 'locked' in run_details:
            log.info('Found locked status for run ID {i}: {s}'.format(i=str(run_id), s=run_details['locked']))
            return run_details['locked']
        else:
            log.info('Locked status not found for run ID: {i}'.format(i=str(run_id)))
            return

    def parse_ra_data_record(self, line):
        """Parses data from a remote access file and returns a EnabledRemoteAccess object or None

        # CloudId,CloudName,CloudType,CloudspaceId,CloudspaceName,ActiveStatus,EnabledStatus,RaRunId,RaRunName,
                Size,LockedStatus

        :param: line: (str) line of data from output file
        :returns: EnabledRemoteAccess object or None
        """
        log = logging.getLogger(self.cls_logger + '.parse_ra_data_record')

        if EnabledRemoteAccess.header_row() in line:
            log.info('Skipping reading header row')
            return

        parts = line.split(',')
        if len(parts) != 21:
            log.warning('This line does not have 21 items: {d}'.format(d=line))
            return

        # Change text "None" into actual None if found
        read_data = []
        for part in parts:
            part = part.strip()
            if part == 'None':
                read_data.append(None)
            elif part.lower() == 'false':
                read_data.append(False)
            elif part.lower() == 'true':
                read_data.append(True)
            else:
                try:
                    int_data = int(part)
                except ValueError:
                    read_data.append(str(part))
                else:
                    read_data.append(int_data)

        cloud_id = read_data[0]
        cloud_name = read_data[1]
        cloud_type = read_data[2]
        cloudspace_id = read_data[3]
        cloudspace_name = read_data[4]
        cloudspace_status = read_data[5]
        enabled_status = read_data[6]
        run_id = read_data[7]
        run_name = read_data[8]
        run_status = read_data[9]
        dep_id = read_data[10]
        instance_type = read_data[11]
        locked_status = read_data[12]
        access_point_ip = read_data[13]
        boundary_ip = read_data[14]
        guac_ip = read_data[15]
        guac_port = read_data[16]
        rdp_proxy_enabled = read_data[17]
        template_name = read_data[18]
        nat_instance_type = read_data[19]
        user_count = read_data[20]

        # Ensure the required fields are found
        if not all([cloud_id, cloud_name, cloud_type, cloudspace_id, cloudspace_name, cloudspace_status]):
            log.warning('Line does not have all required data, will be removed: {t}'.format(t=line))
            return

        # Ensure cloud and cloudspace IDs are valid ints
        for validate_int in [cloud_id, cloudspace_id, guac_port, user_count, run_id]:
            if not validate_int:
                continue
            try:
                int(validate_int)
            except ValueError as exc:
                log.error('Invalid Integer found\n{e}'.format(e=str(exc)))
                return

        # Validate IP addresses
        for ip_address in [access_point_ip, boundary_ip, guac_ip]:
            if ip_address:
                if ip_address == 'UNKNOWN':
                    continue
                if not validate_ip_address(ip_address=ip_address):
                    log.error('Invalid IP address found: [{i}]'.format(i=ip_address))
                    return

        # Return the EnabledRemoteAccess object
        ra = EnabledRemoteAccess(
            cloud_id=cloud_id,
            cloud_name=cloud_name,
            cloud_type=cloud_type,
            cloudspace_id=cloudspace_id,
            cloudspace_name=cloudspace_name,
            cloudspace_status=cloudspace_status,
            enabled=enabled_status,
            run_id=run_id,
            run_name=run_name,
            run_status=run_status,
            dep_id=dep_id,
            instance_type=instance_type,
            locked_status=locked_status,
            access_point_ip=access_point_ip,
            boundary_ip=boundary_ip,
            guac_ip_address=guac_ip,
            remote_access_port=guac_port,
            rdp_proxy_enabled=rdp_proxy_enabled,
            template_name=template_name,
            nat_instance_type=nat_instance_type,
            user_count=user_count
        )
        return ra

    def read_remote_access_run_data_from_file(self):
        """Reads remote access run data from the output file

        """
        log = logging.getLogger(self.cls_logger + '.read_remote_access_run_data_from_file')

        if not self.load_data:
            if os.path.isfile(out_file):
                log.info('--load not specified, removing existing data file')
                os.remove(out_file)

        if not os.path.isfile(out_file):
            log.info('No remote access run data exists to read, creating with header...')
            with open(out_file, 'w') as f:
                f.write(EnabledRemoteAccess.header_row() + '\n')
            return
        log.info('Reading data from file: {f}'.format(f=out_file))
        with open(out_file, 'r') as f:
            content = f.readlines()
        content = [x.strip() for x in content]
        for line in content:
            if line.startswith('CloudspaceName'):
                log.info('Skipping header row: {r}'.format(r=line))
                continue
            ra_data = self.parse_ra_data_record(line)
            if ra_data:
                log.info('Found RA Data: {d}'.format(d=str(ra_data)))
                self.remote_access_run_info.append(ra_data)

    def send_slack(self, msg, color='good'):
        """Sends Slack message if URL and channel were provided

        :param msg: (str) message to send
        :param color: (str) color of the attachment
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.send_slack')
        if not self.slack_msg:
            return
        log.info('Sending slack message...')
        attachment = SlackAttachment(fallback=msg, text=msg, color=color)
        self.slack_msg.add_attachment(attachment)
        self.slack_msg.send()

    def set_remote_access_run_locks(self, lock):
        """Locks or unlocks all the remote access deployment runs

        :param lock: (bool) set True to lock RA DRs, false otherwise
        :return:
        """
        log = logging.getLogger(self.cls_logger + '.set_remote_access_run_locks')

        # Set the run locks
        for enabled_ra in self.remote_access_run_info:
            if enabled_ra.cloudspace_id in self.skip_cloudspace_ids:
                log.info('Skipping cloudspace ID {c}, it is on the skip list'.format(c=str(enabled_ra.cloudspace_id)))
                continue
            if enabled_ra.enabled != 'ENABLED':
                log.info('Skipping toggling remote access, not currently enabled for cloudspace: {c}'.format(
                    c=str(enabled_ra.cloudspace_id)))
                continue
            dr_id = enabled_ra.run_id
            if not dr_id:
                log.warning('No DR ID detected for enable ra: {r}'.format(r=str(enabled_ra)))
                continue
            cloudspace_id = enabled_ra.cloudspace_id
            cloudspace_name = enabled_ra.cloudspace_name
            log.info('Attempting to set run lock for run ID [{i}] to: {b}'.format(i=str(dr_id), b=str(lock)))
            lock_result = self.set_run_lock(dr_id=dr_id, lock=lock)
            if lock_result:
                msg = 'Set run lock [{b}] on run ID [{i}] in cloudspace ID [{c}]: {n}'.format(
                    b=str(lock), i=str(dr_id), c=str(cloudspace_id), n=cloudspace_name)
                log.info(msg)
                self.send_slack(msg=msg, color='good')
            else:
                msg = 'Unable to set run lock on run ID [{i}] in cloudspace ID [{c}]: {n}'.format(
                    b=str(lock), i=str(dr_id), c=str(cloudspace_id), n=cloudspace_name)
                log.error(msg)
                self.send_slack(msg=msg, color='danger')

    def set_run_lock(self, dr_id, lock):
        """Set the run lock for a run ID

        :param dr_id: (int) run ID
        :param lock: (bool) True to set run lock, False to unlock
        :return: (bool)
        """
        log = logging.getLogger(self.cls_logger + '.set_run_lock')
        max_retries = 120
        try_num = 0
        retry_time_sec = 5
        while True:
            if try_num > max_retries:
                log.error('Unable to set run lock to [{b}] on run ID: {i}'.format(
                    b=str(lock), i=str(dr_id)))
                return None
            try:
                lock_result = self.c5t.set_deployment_run_lock(dr_id=dr_id, lock=lock)
            except Cons3rtApiError as exc:
                log.warning('There was a problem setting run lock on run ID: {i}\n{e}'.format(i=str(dr_id), e=str(exc)))
                log.info('Re-trying in {t} seconds...'.format(t=str(retry_time_sec)))
                time.sleep(retry_time_sec)
                try_num += 1
            else:
                log.info('Run lock returned: {b}'.format(b=str(lock_result)))
                return lock_result

    def toggle_remote_access(self):
        """Toggles remote access for cloudspaces where RA is enabled

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.toggle_remote_access')
        for enabled_ra in self.remote_access_run_info:
            if enabled_ra.cloudspace_id in self.skip_cloudspace_ids:
                log.info('Skipping cloudspace ID {c}, it is on the skip list'.format(c=str(enabled_ra.cloudspace_id)))
                continue
            if enabled_ra.enabled != 'ENABLED':
                log.info('Skipping toggling remote access, not currently enabled for cloudspace: {c}'.format(
                    c=str(enabled_ra.cloudspace_id)))
                continue
            log.info('Toggling remote access for cloudspace ID: {c}'.format(c=str(enabled_ra.cloudspace_id)))
            try:
                self.c5t.toggle_remote_access(vr_id=enabled_ra.cloudspace_id, instance_type=enabled_ra.instance_type)
            except Cons3rtApiError as exc:
                msg = 'Problem remote access in cloudspace ID [{c}]: {n}\n{e}'.format(
                    c=str(enabled_ra.cloudspace_id), n=enabled_ra.cloudspace_name, e=str(exc))
                raise RemoteAccessControllerError(msg) from exc
            log.info('Waiting {t} seconds before proceeding to the next cloudspace'.format(
                t=str(self.cloudspace_wait_time_sec)))
            time.sleep(self.cloudspace_wait_time_sec)

    def unlock_and_disable_remote_access(self):
        """Unlocks and disables remote access for all enabled cloudspaces found

        :return: None
        :raises: RemoteAccessControllerError
        """
        log = logging.getLogger(self.cls_logger + '.unlock_and_disable_remote_access')
        log.info('Unlocking and disabling remote access at level [{r}] for IDs: [{i}]'.format(
            r=self.level, i=",".join(map(str, self.ids))))
        self.set_remote_access_run_locks(lock=False)
        self.disable_remote_access()

    def unlock_and_toggle_remote_access(self):
        """Unlocks and toggles remote access for all enabled cloudspaces found

        :return: None
        :raises: RemoteAccessControllerError
        """
        log = logging.getLogger(self.cls_logger + '.unlock_and_toggle_remote_access')
        log.info('Unlocking and toggling remote access at level [{r}] for IDs: [{i}]'.format(
            r=self.level, i=",".join(map(str, self.ids))))
        self.set_remote_access_run_locks(lock=False)
        self.toggle_remote_access()

    def write_output_file(self):
        """Dumps the remote access data into a CVS file

        """
        log = logging.getLogger(self.cls_logger + '.write_output_file')
        if os.path.isfile(out_file):
            os.remove(out_file)
        out_str = EnabledRemoteAccess.header_row() + '\n'
        for ra_run_data in self.remote_access_run_info:
            out_str += str(ra_run_data) + '\n'
        log.info('Updating file: {f}'.format(f=out_file))
        with open(out_file, 'w') as f:
            f.write(out_str)


def main():
    parser = argparse.ArgumentParser(description='cons3rt remote access controller CLI')
    parser.add_argument('command_level', help='ractl level [site, cloud, or cloudspace]')
    parser.add_argument('command_action',
                        help='ractl action [enable, disable, lock, print, toggle, unlock]')
    parser.add_argument('--access', help='Cloudspace access point IP address')
    parser.add_argument('--config', help='Path to a config file to load')
    parser.add_argument('--delay', help='Override the default delay between remote access actions')
    parser.add_argument('--id', help='Cloud or cloudspace ID to take action on')
    parser.add_argument('--ids', help='Comma-separated list of cloud or cloudspace IDs to take action on')
    parser.add_argument('--ip', help='Remote access server internal IP address')
    parser.add_argument('--load', help='Load outputted data from the previous attempt',
                        action='store_true')
    parser.add_argument('--nordp', help='DISABLE RDP Proxy in the cloudspace', action='store_true')
    parser.add_argument('--port', help='Cloudspace external remote access server port')
    parser.add_argument('--skip', help='Comma-separated list of cloud or cloudspace IDs to skip')
    parser.add_argument('--slackchannel', help='Slack channel to report status to')
    parser.add_argument('--slackurl', help='Slack URL to report status to')
    parser.add_argument('--unlock', help='Force unlock RA runs', action='store_true')
    args = parser.parse_args()

    # Get the command_level
    command_level = args.command_level.strip().lower()

    # Ensure the command_level is valid
    if command_level not in valid_levels:
        print('Invalid command_level found [{c}]\n'.format(c=command_level) + valid_levels_str)
        return 1

    # Get the command_action
    command_action = args.command_action.strip().lower()

    # Ensure the command_action is valid
    if command_action not in valid_actions:
        print('Invalid command_action found [{c}]\n'.format(c=command_action) + valid_actions_str)
        return 1

    # Parse the delay arg
    delay_sec = None
    if args.delay:
        try:
            delay_sec = int(args.delay)
        except ValueError:
            print('WARNING: --delay was not a valid int, using default...')

    # Parse the IDs args
    ids = None
    if command_level != 'site':
        ids = validate_ids(args=args)
        if not ids:
            print('--id or --ids required when the command_level is not [site]')
            return 1

    # Parse the load arg
    load_data = False
    if args.load:
        load_data = True

    # Parse the skip args
    skip_ids = []
    if args.skip:
        candidate_skip_ids = args.skip.split(',')
        for candidate_skip_id in candidate_skip_ids:
            try:
                candidate_skip_id = int(candidate_skip_id)
            except ValueError as exc:
                msg = 'Found invalid skip ID: {i}\n{e}'.format(i=str(candidate_skip_id), e=str(exc))
                print(msg)
                traceback.print_exc()
                return 1
            skip_ids.append(candidate_skip_id)

    # Parse the slack args
    slack_channel = None
    slack_url = None
    if args.slackchannel:
        slack_channel = args.slackchannel
    if args.slackurl:
        slack_url = args.slackurl

    # Parse the "unlock" arg
    unlock = False
    if args.unlock:
        unlock = True

    # Parse the "config" arg
    config = None
    if args.config:
        config = args.config

    # Parse the remote access port
    remote_access_port = None
    if args.port:
        remote_access_port = args.port

    # Parse the remote access internal IP
    remote_access_ip_address = None
    if args.ip:
        remote_access_ip_address = args.ip

    # Parse the "--nordp" proxy disabled arg -- omitting will keep it enabled
    if args.nordp:
        rdp_proxy_enabled = False
    else:
        rdp_proxy_enabled = True

    # Create a RemoteAccessController object will the desired settings
    rac = RemoteAccessController(level=command_level, config=config, ids=ids, slack_channel=slack_channel,
                                 slack_url=slack_url, unlock=unlock, load_data=load_data, skip_cloudspace_ids=skip_ids,
                                 delay_sec=delay_sec, ra_port=remote_access_port, ra_ip=remote_access_ip_address,
                                 rdp_proxy=rdp_proxy_enabled)

    rac.read_remote_access_run_data_from_file()
    rac.get_cloudspace_data()
    rac.write_output_file()

    # Process the provided command_action
    if command_action == 'enable':
        try:
            rac.enable_remote_access()
        except RemoteAccessControllerError as exc:
            print('Problem enabling remote access runs\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return 2
    elif command_action == 'disable':
        if unlock:
            try:
                rac.unlock_and_disable_remote_access()
            except RemoteAccessControllerError as exc:
                print('Problem unlocking and disabling remote access runs\n{e}'.format(e=str(exc)))
                traceback.print_exc()
                return 2
        else:
            try:
                rac.disable_remote_access()
            except RemoteAccessControllerError as exc:
                print('Problem disabling remote access runs\n{e}'.format(e=str(exc)))
                traceback.print_exc()
                return 2
    elif command_action == 'lock':
        try:
            rac.set_remote_access_run_locks(lock=True)
        except RemoteAccessControllerError as exc:
            print('Problem setting run locks\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return 2
    elif command_action == 'print':
        print('Remote Access run output completed!')
    elif command_action == 'toggle':
        if unlock:
            try:
                rac.unlock_and_toggle_remote_access()
            except RemoteAccessControllerError as exc:
                print('Problem unlocking and toggling remote access runs\n{e}'.format(e=str(exc)))
                traceback.print_exc()
                return 2
        else:
            try:
                rac.toggle_remote_access()
            except RemoteAccessControllerError as exc:
                print('Problem toggling remote access runs\n{e}'.format(e=str(exc)))
                traceback.print_exc()
                return 2
    elif command_action == 'unlock':
        try:
            rac.set_remote_access_run_locks(lock=False)
        except RemoteAccessControllerError as exc:
            print('Problem removing run locks\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return 2
    print('Completed Remote Access Controller!')
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
