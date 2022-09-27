#!/usr/bin/env python3
"""
Handles tasks that require multithreading

"""
import logging
import threading

from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.logify import Logify

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.service_runner'


class CloudspaceReleaser(threading.Thread):
    """Performs an execution of tasks for this script ETT via the passed function

    TODO: Implement this class
    """

    def __init__(self, cons3rt_api, cloudspace_id, action, unlock=False):
        threading.Thread.__init__(self)
        self.cls_logger = mod_logger + '.CloudspaceReleaser'
        if not isinstance(cons3rt_api, Cons3rtApi):
            msg = 'Invalid arg cons3rt_api, expected Cons3rtApi, found: {t}'.format(t=cons3rt_api.__class__.__name__)
            raise TypeError(msg)
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
        log = logging.getLogger(self.cls_logger + '.run')
        if self.action not in self.valid_actions:
            return None, None


