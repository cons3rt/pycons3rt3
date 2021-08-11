#!/usr/bin/env python3
"""Module: remote_access_controller

This module is mainly for use by CONS3RT site admins to manage site-wide
remote access actions including:

* Setting/removing site-wide remote access run locks
* Enabling/disabling site-wide remote access
* Cloud-wide remote access actions
* Cloudspace-specific remote access actions

Usage:

ractl [command] [level] [args]

commands = 'enable', 'disable', 'lock', 'print', 'toggle', 'unlock'
level =    'cloud', 'cloudspace', 'site'
args =
    --id               cloud/cloudspace ID
    --ids              comma separated list of cloud/cloudspace IDs
    --load             load data from the previous run
    --skip             List of cloudspace IDs to skip acting upon
    --slackchannel     Slack channel for status posting
    --slackurl         Slack webhook URL
    --unlock           force unlock RA DRs


# Print out cloudspace RA data to ~/cons3rt_reports/remote_access_data.csv

$ ractl print site
$ ractl print cloud --ids 22,24
$ ractl print cloudspace --ids 138,140

# Load data from the prior execution from ~/cons3rt_reports/remote_access_data.csv

$ ractl print cloudspace --ids 138,140 --load

# Disable/toggle remote access site-wide, add --unlock to force unlocking the RA DRs

$ ractl disable site
$ ractl disable site --unlock
$ ractl toggle site --unlock --load

# Same for a list of cloud or cloudspace IDs

$ ractl disable cloud --id 22
$ ractl toggle cloudspace --unlock --ids 1,2,3
$ ractl toggle cloud --id 7 --unlock --load

"""

import argparse
import logging
import os
import sys
import time
import traceback

from .cons3rtapi import Cons3rtApi, Cons3rtApiError
from .cons3rtcli import validate_ids
from .logify import Logify
from .slack import SlackAttachment, SlackMessage


# Set up logger name for this module
mod_logger = Logify.get_name() + '.remoteaccesscontroller'

# Report directory
report_dir = os.path.join(os.path.expanduser('~'), 'cons3rt_reports')

# Output File
out_file = os.path.join(report_dir, 'remote_access_data.csv')

valid_commands = ['enable', 'disable', 'lock', 'print', 'toggle', 'unlock']
valid_commands_str = ','.join(valid_commands)

valid_subcommands = ['cloud', 'cloudspace', 'site']
valid_subcommands_str = ','.join(valid_subcommands)

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
    def __init__(self, cloud_id, cloud_name, cloud_type, cloudspace_id, cloudspace_name, active_status,
                 enabled=None, run_id=None, run_name=None, instance_type=None, locked_status=None):
        self.cloud_id = cloud_id
        self.cloud_name = cloud_name
        self.cloud_type = cloud_type
        self.cloudspace_id = cloudspace_id
        self.cloudspace_name = cloudspace_name
        self.active_status = active_status
        self.enabled = enabled
        self.run_id = run_id
        self.run_name = run_name
        self.instance_type = instance_type
        self.locked_status = locked_status

    @staticmethod
    def header_row():
        return 'CloudId,CloudName,CloudType,CloudspaceId,CloudspaceName,ActiveStatus,EnabledStatus,RaRunId,RaRunName,' \
               'Size,LockedStatus'

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
        if self.active_status:
            out_str += self.active_status + ','
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
        if self.instance_type:
            out_str += self.instance_type + ','
        else:
            out_str += 'None,'
        if self.locked_status:
            out_str += 'ENABLED'
        else:
            out_str += 'None'
        return out_str


class RemoteAccessController(object):

    def __init__(self, level, ids=None, slack_channel=None, slack_url=None, unlock=False, load_data=False,
                 skip_cloudspace_ids=None, delay_sec=None):
        self.cls_logger = mod_logger + '.RemoteAccessController'
        if level not in valid_subcommands:
            msg = 'Invalid level [{z}], must be: {c}'.format(z=level, c=valid_subcommands_str)
            raise RemoteAccessControllerError(msg)
        self.level = level
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

        # Determine the wait time
        if not delay_sec:
            self.cloudspace_wait_time_sec = default_cloudspace_wait_time_sec

        # Create a Cons3rtApi
        try:
            self.c5t = Cons3rtApi()
        except Cons3rtApiError as exc:
            raise RemoteAccessControllerError('There was a problem initializing Cons3rtApi') from exc

        # Lists of clouds, cloudspaces, and remote access run info
        self.clouds = []
        self.cloudspaces = []
        self.remote_access_run_info = []

    def send_slack(self, msg, color='good'):
        """Sends slack message if URL and channel were provided

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

    def get_cloud_list(self):
        """Return the list of cloud IDs to act on

        :return: (list) of clouds' data:

        clouds = [
                    {
                        'state': 'ACTIVE',
                        'cloudType': 'VCloudCloud',
                        'id': 7,
                        'name': 'Hanscom Cloud'
                    }
                ]

        """
        log = logging.getLogger(self.cls_logger + '.get_cloud_list')
        clouds = []
        if self.level == 'site':
            log.info('Collecting site-wide cloud info...')
            try:
                clouds += self.c5t.list_clouds()
            except Cons3rtApiError as exc:
                msg = 'There was a problem listing clouds'
                raise RemoteAccessControllerError(msg) from exc
        elif self.level == 'cloud':
            for cloud_id in self.ids:
                try:
                    clouds.append(self.c5t.retrieve_cloud_details(cloud_id=cloud_id))
                except Cons3rtApiError as exc:
                    msg = 'Problem retrieving details for cloud ID: {i}'.format(i=str(cloud_id))
                    raise RemoteAccessControllerError(msg) from exc
        elif self.level == 'cloudspace':
            log.info('No cloud actions, cloudspace IDs were specified')
        log.info('Returning data on {n} clouds'.format(n=str(len(clouds))))
        return clouds

    def get_cloudspace_data(self):
        """Populates the list with cloud and cloudspace data

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.get_cloudspace_data')

        # If a list of cloudspaces was provided, get details for cloudspaces on that list
        if self.level == 'cloudspace':
            for cloudspace_id in self.ids:
                try:
                    self.cloudspaces.append(self.c5t.get_virtualization_realm_details(vr_id=cloudspace_id))
                except Cons3rtApiError as exc:
                    msg = 'Problem getting details for cloudspace ID: {i}'.format(i=str(cloudspace_id))
                    raise RemoteAccessControllerError(msg) from exc

            # Back-fill cloud IDs related to the provided cloudspaces
            cloud_ids = []
            for cloudspace in self.cloudspaces:
                if cloudspace['cloud']['id'] not in cloud_ids:
                    try:
                        cloud_details = self.c5t.retrieve_cloud_details(cloud_id=cloudspace['cloud']['id'])
                    except Cons3rtApiError as exc:
                        msg = 'Problem getting details for cloud ID: {i}'.format(i=str(cloudspace['cloud']['id']))
                        raise RemoteAccessControllerError(msg) from exc
                    cloud_ids.append(cloud_details['id'])
                    self.clouds.append(cloud_details)

        else:
            # List the clouds
            try:
                self.clouds += self.get_cloud_list()
            except RemoteAccessControllerError as exc:
                msg = 'Problem getting cloud data before getting cloudspace data'
                raise RemoteAccessControllerError(msg) from exc

            # Loop through each cloud and get a list cloudspaces
            for cloud in self.clouds:
                log.info('Found Cloud ID {i}: {n}'.format(i=str(cloud['id']), n=cloud['name']))
                try:
                    cloud_cloudspaces = self.c5t.list_virtualization_realms_for_cloud(cloud['id'])
                except Cons3rtApiError as exc:
                    msg = 'There was a problem listing cloudspaces in cloud ID: {i}'.format(i=str(cloud['id']))
                    raise RemoteAccessControllerError(msg) from exc
                log.info('Found [{n}] cloudspaces in cloud ID: {i}'.format(
                    n=str(len(cloud_cloudspaces)), i=str(cloud['id'])))

                # Get details for each cloudspace and append to the cloudspaces list
                for cloud_cloudspace in cloud_cloudspaces:
                    try:
                        self.cloudspaces.append(self.c5t.get_virtualization_realm_details(vr_id=cloud_cloudspace['id']))
                    except Cons3rtApiError as exc:
                        msg = 'Problem getting details for cloudspace: {i}'.format(i=str(cloud_cloudspace['id']))
                        raise RemoteAccessControllerError(msg) from exc

        for cloudspace in self.cloudspaces:

            # Check if cloudspace data already exists
            data_exists = False
            for ra_data in self.remote_access_run_info:
                if cloudspace['id'] == ra_data.cloudspace_id:
                    data_exists = True
            if data_exists:
                log.info('Found cloudspace data already for cloudspace: {i}'.format(i=str(cloudspace['id'])))
                continue

            # Add cloudspace data
            log.info('Adding cloudspace data for cloudspace ID: {i}'.format(i=str(cloudspace['id'])))
            self.remote_access_run_info.append(
                EnabledRemoteAccess(
                    cloud_id=cloudspace['cloud']['id'],
                    cloud_name=cloudspace['cloud']['name'],
                    cloud_type=cloudspace['cloud']['cloudType'],
                    cloudspace_id=cloudspace['id'],
                    cloudspace_name=cloudspace['name'],
                    active_status=cloudspace['state']
                )
            )
        log.info('Found {n} total cloudspaces'.format(n=str(len(self.remote_access_run_info))))

    def get_cloudspace_remote_access_enabled_status(self, cloudspace_id):
        """Adds the cloudspace remote access enabled status

        returns: (tuple):
                (str) remote access enabled status or UNKNOWN
                (int) ID of the remote access deployment
                (str) instance type or None
        """
        log = logging.getLogger(self.cls_logger + '.get_cloudspace_remote_access_enabled_status')

        log.info('Attempting to determine the cloudspace remote access enabled status for cloudspace ID: {i}'.format(
            i=str(cloudspace_id)))
        max_attempts = 10
        retry_sec = 5
        attempt_num = 0
        cloudspace_info = {}
        ra_status = 'UNKNOWN'
        while True:
            if attempt_num >= max_attempts:
                log.error('Unable to determine remote access status after {n} attempts for cloudspace ID {i}'.format(
                    n=str(max_attempts), i=str(cloudspace_id)))
                return ra_status
            try:
                cloudspace_info = self.c5t.get_virtualization_realm_details(vr_id=cloudspace_id)
            except Cons3rtApiError as exc:
                log.warning('There was a problem querying details on cloudspace ID: {i}\n{e}'.format(
                    i=str(cloudspace_id), e=str(exc)))
                attempt_num += 1
                log.info('Re-trying in {n} seconds...'.format(n=str(retry_sec)))
                time.sleep(retry_sec)
                continue
            else:
                ra_status = cloudspace_info['remoteAccessStatus']
                break

        # Get the remote access deployment ID
        deployment_id = None
        if 'remoteAccessDeploymentId' in cloudspace_info:
            deployment_id = cloudspace_info['remoteAccessDeploymentId']

        # Get the instance size
        instance_type = None
        if 'remoteAccessConfig' in cloudspace_info:
            if 'instanceType' in cloudspace_info['remoteAccessConfig']:
                instance_type = cloudspace_info['remoteAccessConfig']['instanceType']
        return ra_status, deployment_id, instance_type

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

    def get_remote_access_runs(self):
        """Populates the list of remote access enabled cloudspace and run info

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.get_remote_access_runs')

        log.info('Attempting to gather cloudspace data...')
        self.get_cloudspace_data()

        # RA data will be queried for VRs with this state
        active_statii = ['ACTIVE', 'ENTERING_MAINTENANCE', 'MAINTENANCE']

        for ra_data in self.remote_access_run_info:

            # Skip if the cloudspace is not active
            if ra_data.active_status not in active_statii:
                log.info('Skipping RA data retrieval for cloudspace ID {i} with state: {s}'.format(
                    i=str(ra_data.cloudspace_id), s=ra_data.active_status))
                RemoteAccessController.append_remote_access_run(ra_run_data=ra_data)
                continue

            # Skip if the RA data is already existing
            if ra_data.enabled and ra_data.run_id:
                log.info('Remote access enabled status already existing {s} and run ID: {i}'.format(
                    s=ra_data.enabled, i=str(ra_data.run_id)
                ))
                continue

            # Get the RA status and RA deployment ID from the cloudspace
            ra_status, deployment_id, instance_type = self.get_cloudspace_remote_access_enabled_status(
                cloudspace_id=ra_data.cloudspace_id)
            ra_data.enabled = ra_status

            # Set the instance type
            if instance_type:
                log.info('Found RA instance type for cloudspace ID {i}: {s}'.format(
                    i=str(ra_data.cloudspace_id), s=instance_type))
                ra_data.instance_type = instance_type

            # Attempt to determine an active RA run ID
            run_id = None
            locked = None
            if deployment_id:
                log.info('Found RA deployment ID: {i}, attempting to determine an active run ID...'.format(
                    i=str(deployment_id)))
                max_attempts = 10
                retry_sec = 5
                attempt_num = 0
                while True:
                    if attempt_num >= max_attempts:
                        log.error('Unable to determine RA run ID after {n} attempts for deployment {i}'.format(
                            n=str(max_attempts), i=str(deployment_id)))
                        break
                    try:
                        run_id = self.c5t.get_active_run_id_from_deployment(deployment_id=deployment_id)
                    except Cons3rtApiError as exc:
                        log.warning('Problem finding active run fpr deployment ID: {i}\n{e}'.format(
                            i=str(deployment_id), e=str(exc)))
                        attempt_num += 1
                        log.info('Re-trying in {n} seconds...'.format(n=str(retry_sec)))
                        time.sleep(retry_sec)
                        continue
                    else:
                        break
            else:
                log.info('No Remote access deployment for cloudspace: {i}'.format(i=str(ra_data.cloudspace_id)))
            if run_id:
                log.info('Found RA run ID: {i}, attempting to determine locked status...'.format(i=str(run_id)))
                ra_data.run_id = run_id
                locked = self.get_run_lock_status(run_id=run_id)
            else:
                log.info('No active remote access run ID found for cloudspace: {i}'.format(
                    i=str(ra_data.cloudspace_id)))

            if locked:
                ra_data.locked_status = locked
            log.info('Completed collecting remote access data: {d}'.format(d=ra_data))
            RemoteAccessController.append_remote_access_run(ra_run_data=ra_data)
        log.info('Completed collecting remote access data for all cloudspaces')

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

    def toggle_remote_access_for_cloudspace(self, cloudspace_id):
        """Disable and re-enable remote access in a cloudspace at the same size

        :param cloudspace_id: (int) ID of the cloudspace
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.toggle_remote_access_for_cloudspace')

        found = False
        for enabled_ra in self.remote_access_run_info:
            if cloudspace_id == enabled_ra.cloudspace_id:
                found = True
                instance_type = enabled_ra.instance_type
                cloudspace_name = enabled_ra.cloudspace_name
                try:
                    self.c5t.toggle_remote_access(vr_id=cloudspace_id, size=instance_type)
                except Cons3rtApiError as exc:
                    msg = 'Unable to toggle remote access in cloudspace ID [{c}]: {n}\n{e}'.format(
                        c=str(cloudspace_id), n=cloudspace_name, e=str(exc))
                    log.error(msg)
                    self.send_slack(msg=msg, color='danger')
                else:
                    msg = 'Toggled remote access in cloudspace ID [{c}]: {n}'.format(
                        c=str(cloudspace_id), n=cloudspace_name)
                    log.info(msg)
                    log.info('Sending slack message...')
                    self.send_slack(msg=msg, color='good')
        if not found:
            log.warning('Cloudspace ID [{i}] does not have remote access enabled, or a remote access run was '
                        'not found'.format(i=str(cloudspace_id)))

    def set_run_lock_for_cloudspace(self, cloudspace_id, lock):
        """Sets the run

        :param cloudspace_id: (int) ID of the cloudspace to set
        :param lock: (bool) True to set run lock, False to unlock
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.set_run_lock_for_cloudspace')
        found = False
        for enabled_ra in self.remote_access_run_info:
            if cloudspace_id == enabled_ra.cloudspace_id:
                found = True
                dr_id = enabled_ra.run_id
                cloudspace_name = enabled_ra.cloudspace_name
                lock_result = self.set_run_lock(dr_id=dr_id, lock=lock)
                if lock_result:
                    msg = 'Set run lock [{b}] on run ID [{i}] in cloudspace ID [{c}]: {n}'.format(
                        b=str(lock), i=str(dr_id), c=str(cloudspace_id), n=cloudspace_name)
                    log.info(msg)
                    log.info('Sending slack message...')
                    self.send_slack(msg=msg, color='good')
                else:
                    msg = 'Unable to set run lock on run ID [{i}] in cloudspace ID [{c}]: {n}'.format(
                        b=str(lock), i=str(dr_id), c=str(cloudspace_id), n=cloudspace_name)
                    log.error(msg)
                    self.send_slack(msg=msg, color='danger')
        if not found:
            log.warning('Cloudspace ID [{i}] does not have remote access enabled, or a remote access run was '
                        'not found'.format(i=str(cloudspace_id)))

    def set_remote_access_run_locks_all_cloudspaces(self, lock):
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

    def disable_remote_access(self):
        """Disables remote access for all enabled cloudspaces found, does not unlock

        :return: None
        :raises: RemoteAccessControllerError
        """
        log = logging.getLogger(self.cls_logger + '.disable_remote_access')

        for enabled_ra in self.remote_access_run_info:
            if enabled_ra.cloudspace_id in self.skip_cloudspace_ids:
                log.info('Skipping cloudspace ID {c}, it is on the skip list'.format(c=str(enabled_ra.cloudspace_id)))
                continue
            if enabled_ra.enabled != 'ENABLED':
                log.info('Skipping toggling remote access, not currently enabled for cloudspace: {c}'.format(
                    c=str(enabled_ra.cloudspace_id)))
                continue
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

    def unlock_and_disable_remote_access(self):
        """Unlocks and disables remote access for all enabled cloudspaces found

        :return: None
        :raises: RemoteAccessControllerError
        """
        log = logging.getLogger(self.cls_logger + '.unlock_and_disable_remote_access')

        for enabled_ra in self.remote_access_run_info:
            if enabled_ra.cloudspace_id in self.skip_cloudspace_ids:
                log.info('Skipping cloudspace ID {c}, it is on the skip list'.format(c=str(enabled_ra.cloudspace_id)))
                continue
            if enabled_ra.enabled != 'ENABLED':
                log.info('Skipping toggling remote access, not currently enabled for cloudspace: {c}'.format(
                    c=str(enabled_ra.cloudspace_id)))
                continue
            log.info('Attempting to unlock and disable remote access for cloudspace ID: {i}'.format(
                i=str(enabled_ra.cloudspace_id)))
            self.set_run_lock_for_cloudspace(cloudspace_id=enabled_ra.cloudspace_id, lock=False)
            try:
                self.c5t.disable_remote_access(vr_id=enabled_ra.cloudspace_id)
            except Cons3rtApiError as exc:
                msg = 'Problem disabling remote access for cloudspace: {i}'.format(i=str(enabled_ra.cloudspace_id))
                raise RemoteAccessControllerError(msg) from exc
            log.info('Waiting {t} seconds before proceeding to the next cloudspace'.format(
                t=str(self.cloudspace_wait_time_sec)))
            time.sleep(self.cloudspace_wait_time_sec)

    def unlock_and_disable_remote_access_for_cloudspace(self, cloudspace_id):
        """Unlocks and disables remote access for a cloudspace

        :param cloudspace_id: (int) ID of the cloudspace
        :return: None
        :raises: RemoteAccessControllerError
        """
        log = logging.getLogger(self.cls_logger + '.unlock_and_disable_remote_access_for_cloudspace')

        log.info('Unlocking and toggling remote access for cloudspace ID: {i}'.format(i=str(cloudspace_id)))
        self.set_run_lock_for_cloudspace(cloudspace_id=cloudspace_id, lock=False)
        try:
            self.c5t.disable_remote_access(vr_id=cloudspace_id)
        except Cons3rtApiError as exc:
            msg = 'Problem disabling remote access for cloudspace: {i}'.format(i=str(cloudspace_id))
            raise RemoteAccessControllerError(msg) from exc

    def unlock_and_disable_remote_access_for_list(self, cloudspace_id_list):
        """Unlocks and disables remote access for a list of cloudspaces

        :param cloudspace_id_list: (list) cloudspace IDs
        :return: None
        :raises: RemoteAccessControllerError
        """
        log = logging.getLogger(self.cls_logger + '.unlock_and_disable_remote_access_for_list')
        if not isinstance(cloudspace_id_list, list):
            log.error('Expected list, found: {t}'.format(t=cloudspace_id_list.__class__.__name__))

        for cloudspace_id in cloudspace_id_list:
            log.info('Attempting to unlock and toggle remote access for cloudspace ID: {i}'.format(
                i=str(cloudspace_id)))
            self.unlock_and_disable_remote_access_for_cloudspace(cloudspace_id=cloudspace_id)
            log.info('Waiting {t} seconds before proceeding to the next cloudspace'.format(
                t=str(self.cloudspace_wait_time_sec)))
            time.sleep(self.cloudspace_wait_time_sec)

    def unlock_and_toggle_remote_access(self):
        """Unlocks and toggles remote access for all enabled cloudspaces found

        :return: None
        :raises: RemoteAccessControllerError
        """
        log = logging.getLogger(self.cls_logger + '.unlock_and_toggle_remote_access')

        for enabled_ra in self.remote_access_run_info:
            if enabled_ra.cloudspace_id in self.skip_cloudspace_ids:
                log.info('Skipping cloudspace ID {c}, it is on the skip list'.format(c=str(enabled_ra.cloudspace_id)))
                continue
            if enabled_ra.enabled != 'ENABLED':
                log.info('Skipping toggling remote access, not currently enabled for cloudspace: {c}'.format(
                    c=str(enabled_ra.cloudspace_id)))
                continue
            log.info('Attempting to unlock and toggle remote access for cloudspace ID: {i}'.format(
                i=str(enabled_ra.cloudspace_id)))
            self.set_run_lock_for_cloudspace(cloudspace_id=enabled_ra.cloudspace_id, lock=False)
            try:
                self.c5t.toggle_remote_access(vr_id=enabled_ra.cloudspace_id)
            except Cons3rtApiError as exc:
                msg = 'Problem toggling remote access for cloudspace: {i}'.format(i=str(enabled_ra.cloudspace_id))
                raise RemoteAccessControllerError(msg) from exc
            log.info('Waiting {t} seconds before proceeding to the next cloudspace'.format(
                t=str(self.cloudspace_wait_time_sec)))
            time.sleep(self.cloudspace_wait_time_sec)

    def unlock_and_toggle_remote_access_for_cloudspace(self, cloudspace_id):
        """Unlocks and toggles remote access for a provided cloudspace

        :param cloudspace_id: (int) ID of the cloudspace
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.unlock_and_toggle_remote_access_for_cloudspace')

        log.info('Unlocking and toggling remote access for cloudspace ID: {i}'.format(i=str(cloudspace_id)))
        self.set_run_lock_for_cloudspace(cloudspace_id=cloudspace_id, lock=False)
        self.toggle_remote_access_for_cloudspace(cloudspace_id=cloudspace_id)

    def unlock_and_toggle_remote_access_for_list(self, cloudspace_id_list):
        """Unlocks and toggles remote access for a list of cloudspaces

        :param cloudspace_id_list: (list) cloudspace IDs
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.unlock_and_toggle_remote_access_for_list')
        if not isinstance(cloudspace_id_list, list):
            log.error('Expected list, found: {t}'.format(t=cloudspace_id_list.__class__.__name__))

        for cloudspace_id in cloudspace_id_list:
            log.info('Attempting to unlock and toggle remote access for cloudspace ID: {i}'.format(
                i=str(cloudspace_id)))
            self.unlock_and_toggle_remote_access_for_cloudspace(cloudspace_id=cloudspace_id)
            log.info('Waiting {t} seconds before proceeding to the next cloudspace'.format(
                t=str(self.cloudspace_wait_time_sec)))
            time.sleep(self.cloudspace_wait_time_sec)

    def toggle_remote_access_for_list(self):
        """Toggles remote access for cloudspaces where RA is enabled

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.toggle_remote_access_for_list')
        for enabled_ra in self.remote_access_run_info:
            if enabled_ra.cloudspace_id in self.skip_cloudspace_ids:
                log.info('Skipping cloudspace ID {c}, it is on the skip list'.format(c=str(enabled_ra.cloudspace_id)))
                continue
            if enabled_ra.enabled != 'ENABLED':
                log.info('Skipping toggling remote access, not currently enabled for cloudspace: {c}'.format(
                    c=str(enabled_ra.cloudspace_id)))
                continue
            log.info('Toggling remote access for cloudspace ID: {c}'.format(c=str(enabled_ra.cloudspace_id)))
            self.toggle_remote_access_for_cloudspace(cloudspace_id=enabled_ra.cloudspace_id)
            log.info('Waiting {t} seconds before proceeding to the next cloudspace'.format(
                t=str(self.cloudspace_wait_time_sec)))
            time.sleep(self.cloudspace_wait_time_sec)

    def print_remote_access_runs(self):
        """Prints out the cloudspace ID, RA run ID

        """
        log = logging.getLogger(self.cls_logger + '.print_remote_access_runs')
        if os.path.isfile(out_file):
            os.remove(out_file)
        out_str = EnabledRemoteAccess.header_row() + '\n'
        for ra_run_data in self.remote_access_run_info:
            out_str += str(ra_run_data) + '\n'
        log.info('Updating file: {f}'.format(f=out_file))
        with open(out_file, 'w') as f:
            f.write(out_str)

    @staticmethod
    def append_remote_access_run(ra_run_data):
        """Appends RA run data to the out file

        """
        with open(out_file, 'a') as f:
            f.write(str(ra_run_data) + '\n')

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
        if len(parts) != 11:
            log.warning('This line does not have 11 items: {d}'.format(d=line))
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
        active_status = read_data[5]
        enabled = read_data[6]
        run_id = read_data[7]
        run_name = read_data[8]
        instance_type = read_data[9]
        locked_status = read_data[10]

        # Ensure the required fields are found
        if not all([cloud_id, cloud_name, cloud_type, cloudspace_id, cloudspace_name, active_status]):
            log.warning('Line does not have all required data, will be removed: {t}'.format(t=line))
            return

        # Ensure cloud and cloudspace IDs are valid ints
        try:
            cloud_id = int(cloud_id)
            cloudspace_id = int(cloudspace_id)
        except ValueError as exc:
            log.error('Invalid ID found\n{e}'.format(e=str(exc)))
            return

        # If run ID is provided ensure it is a valid int
        if run_id:
            try:
                run_id = int(run_id)
            except ValueError:
                log.error('Not a valid run ID: {d}'.format(d=run_id))
                return

        # Return the EnabledRemoteAccess object
        ra = EnabledRemoteAccess(
            cloud_id=cloud_id,
            cloud_name=cloud_name,
            cloud_type=cloud_type,
            cloudspace_id=cloudspace_id,
            cloudspace_name=cloudspace_name,
            active_status=active_status,
            enabled=enabled,
            run_id=run_id,
            run_name=run_name,
            instance_type=instance_type,
            locked_status=locked_status
        )
        return ra

    def read_remote_access_run_data_from_file(self):
        """Reads remote access run data from the output file

        """
        log = logging.getLogger(self.cls_logger + '.read_remote_access_run_data_from_file')

        if not self.load_data:
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

        # Print remote access runs read in so far if any
        self.print_remote_access_runs()


def main():
    parser = argparse.ArgumentParser(description='cons3rt remote access controller CLI')
    parser.add_argument('command', help='Command for the RemoteAccessController CLI')
    parser.add_argument('subcommand', help='Subcommand for the RemoteAccessController CLI')
    parser.add_argument('--delay', help='Override the default delay between remote access actions', required=False)
    parser.add_argument('--id', help='cloud or cloudspace ID to take action on', required=False)
    parser.add_argument('--ids', help='Comma-separated list of cloud or cloudspace IDs to take action on',
                        required=False)
    parser.add_argument('--load', help='Load outputted data from the previous attempt', required=False,
                        action='store_true')
    parser.add_argument('--skip', help='Comma-separated list of cloud or cloudspace IDs to skip', required=False)
    parser.add_argument('--slackchannel', help='Slack channel to report status to', required=False)
    parser.add_argument('--slackurl', help='Slack URL to report status to', required=False)
    parser.add_argument('--unlock', help='Unlock the remote access run', required=False, action='store_true')
    args = parser.parse_args()

    # Get the command
    command = args.command.strip().lower()

    # Ensure the command is valid
    if command not in valid_commands:
        print('Invalid command found [{c}]\n'.format(c=command) + valid_commands_str)
        return 1

    # Get the subcommand
    subcommand = args.subcommand.strip().lower()

    # Ensure the subcommand is valid
    if subcommand not in valid_subcommands:
        print('Invalid subcommand found [{c}]\n'.format(c=subcommand) + valid_subcommands_str)
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
    if subcommand != 'site':
        ids = validate_ids(args=args)
        if not ids:
            print('--id or --ids required when the subcommand is not [site]')
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

    # Parse the slack args
    slack_channel = None
    slack_url = None
    if args.slackchannel:
        slack_channel = args.slackchannel
    if args.slackurl:
        slack_url = args.slackurl

    # Parse the unlock arg
    unlock = False
    if args.unlock:
        unlock = True

    rac = RemoteAccessController(level=subcommand, ids=ids, slack_channel=slack_channel, slack_url=slack_url,
                                 unlock=unlock, load_data=load_data, skip_cloudspace_ids=skip_ids, delay_sec=delay_sec)
    rac.read_remote_access_run_data_from_file()
    rac.get_remote_access_runs()
    rac.print_remote_access_runs()

    # Process the provided command
    if command == 'enable':
        print('COMING SOON: enable option is TBD')
    elif command == 'disable':
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
    elif command == 'lock':
        try:
            rac.set_remote_access_run_locks_all_cloudspaces(lock=True)
        except RemoteAccessControllerError as exc:
            print('Problem setting run locks\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return 2
    elif command == 'print':
        print('Remote Access run output completed!')
    elif command == 'toggle':
        if unlock:
            try:
                rac.unlock_and_toggle_remote_access()
            except RemoteAccessControllerError as exc:
                print('Problem unlocking and toggling remote access runs\n{e}'.format(e=str(exc)))
                traceback.print_exc()
                return 2
        else:
            try:
                rac.toggle_remote_access_for_list()
            except RemoteAccessControllerError as exc:
                print('Problem toggling remote access runs\n{e}'.format(e=str(exc)))
                traceback.print_exc()
                return 2
    elif command == 'unlock':
        try:
            rac.set_remote_access_run_locks_all_cloudspaces(lock=False)
        except RemoteAccessControllerError as exc:
            print('Problem removing run locks\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return 2
    print('Completed Remote Access Controller!')
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
