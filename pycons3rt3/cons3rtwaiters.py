#!/usr/bin/env python3
"""
Handles tasks that require multithreading

"""
import logging
import threading
import time

from .cons3rtenums import cons3rt_deployment_run_status
from .exceptions import Cons3rtApiError
from .logify import Logify

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.cons3rtwaiters'


class CloudspaceReleaser(threading.Thread):
    """Performs an execution of tasks for this script ETT via the passed function

    TODO: Implement this class
    """

    def __init__(self, cons3rt_api, cloudspace_id, action, unlock=False):
        threading.Thread.__init__(self)
        self.cls_logger = mod_logger + '.CloudspaceReleaser'
        if not isinstance(action, int):
            msg = 'Invalid arg cloudspace_id, expected int, found: {t}'.format(t=cloudspace_id.__class__.__name__)
            raise TypeError(msg)
        if not isinstance(action, str):
            msg = 'Invalid arg action, expected string, found: {t}'.format(t=action.__class__.__name__)
            raise TypeError(msg)
        if not isinstance(unlock, bool):
            msg = 'Invalid arg unlock, expected bool, found: {t}'.format(t=action.__class__.__name__)
            raise TypeError(msg)
        self.cons3rt_api = cons3rt_api
        self.cloudspace_id = cloudspace_id
        self.action = action
        self.unlock = unlock
        # Valid actions
        self.valid_actions = [
            'delete',
            'release'
        ]

    def run(self):
        if self.action not in self.valid_actions:
            return None, None


class RunWaiter(threading.Thread):
    """
    Waits for a deployment run to reach a desired state.  Provide:

    cons3rt_api: Cons3rtApi object
    dr_id: (str) deployment run ID
    desired_status_list: (list) of desired deployment run status to stop
    check_interval_sec: (int) number of seconds in between status checks
    max_wait_time_sec: (int) maximum number of seconds to wait for the DR to reach the desired state

    Possible Status for Deployment Runs:
    "UNKNOWN" "SCHEDULED" "SUBMITTED" "PROVISIONING_HOSTS" "HOSTS_PROVISIONED" "RESERVED" "RELEASE_REQUESTED"
    "RELEASING" "TESTING" "TESTED" "REDEPLOYING_HOSTS" "COMPLETED" "CANCELED"
    """

    def __init__(self, cons3rt_api, dr_id, desired_status_list, check_interval_sec=30, max_wait_time_sec=28800):
        threading.Thread.__init__(self)
        self.cls_logger = mod_logger + '.RunWaiter'
        self.cons3rt_api = cons3rt_api
        self.dr_id = dr_id
        self.desired_status_list = desired_status_list
        self.check_interval_sec = check_interval_sec
        self.max_wait_time_sec = max_wait_time_sec
        self.stop = False
        self.error = False
        self.error_msg = ''
        self.success = False
        self.current_status = 'UNKNOWN'

    def report_fail(self, msg):
        log = logging.getLogger(self.cls_logger + '.report_fail')
        self.error_msg = msg
        self.error = True
        log.error(msg)

    def report_success(self, msg):
        log = logging.getLogger(self.cls_logger + '.report_success')
        self.error_msg = ''
        self.error = False
        self.success = True
        self.stop = True
        log.info(msg)

    def run(self):
        log = logging.getLogger(self.cls_logger + '.run')
        start_time = time.time()

        # Ensure the desired status is valid
        for desired_status in self.desired_status_list:
            if desired_status not in cons3rt_deployment_run_status:
                msg = 'Desired status [{d}] is not valid, must be one of: {s}'.format(
                    d=desired_status, s=','.join(cons3rt_deployment_run_status))
                self.report_fail(msg)
                return

        # Start monitoring
        log.info('Starting thread to monitor DR {d} to reach state(s) [{s}] for a maximum of {t} seconds'.format(
            d=str(self.dr_id), s=','.join(self.desired_status_list), t=str(self.max_wait_time_sec)))
        elapsed_time_sec = 0

        while not self.stop:
            # Check if elapsed time has exceeded the maximum
            elapsed_time_sec = round((time.time() - start_time))
            if elapsed_time_sec > self.max_wait_time_sec:
                msg = 'Elapsed time exceeded the maximum [{m}] waiting for DR [{d}] to reach status: {s}'.format(
                    m=str(self.max_wait_time_sec), d=str(self.dr_id), s=','.join(self.desired_status_list))
                self.report_fail(msg)
                return

            # Retrieve the DR details
            try:
                dr = self.cons3rt_api.retrieve_deployment_run_details(dr_id=self.dr_id)
            except Cons3rtApiError as exc:
                msg = 'Problem retrieving deployment run: {d}\n{e}'.format(d=str(self.dr_id), e=str(exc))
                self.report_fail(msg)
                return

            # Ensure the deploymentRunStatus data item was found
            if 'deploymentRunStatus' not in dr:
                msg = 'deploymentRunStatus not found in deployment run: {d}'.format(d=str(dr))
                self.report_fail(msg)
                return

            # Ensure the deploymentRunStatus was valid
            if dr['deploymentRunStatus'] not in cons3rt_deployment_run_status:
                msg = 'Invalid deploymentRunStatus found: {d}'.format(d=dr['deploymentRunStatus'])
                self.report_fail(msg)
                return

            # Set the current status
            self.current_status = dr['deploymentRunStatus']

            # Check if the desired status was reached
            if self.current_status in self.desired_status_list:
                msg = 'DR [{d}] has reached desired state of [{s}] after [{t}] seconds'.format(
                    d=str(self.dr_id), s=self.current_status, t=str(elapsed_time_sec))
                self.report_success(msg)
                break

            # Log the current status
            log.info('Found DR ID [{d}] with deployment run status [{s}] after [{t}] seconds'.format(
                d=str(self.dr_id), s=self.current_status, t=str(elapsed_time_sec)))

            log.info('Waiting {t} seconds to re-check status of DR [{d}]...'.format(
                t=str(self.check_interval_sec), d=str(self.dr_id)))
            time.sleep(self.check_interval_sec)

        log.info('Completed thread to monitor DR {d} to reach state [{s}] after {t} seconds'.format(
            d=str(self.dr_id), s=self.current_status, t=str(elapsed_time_sec)
        ))
