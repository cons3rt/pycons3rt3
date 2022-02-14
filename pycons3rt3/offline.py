#!/usr/bin/python

"""Module: offline

This module provides methods for handline offline assets

"""
import logging
import requests
import time
from .logify import Logify

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.offline'

# List of URLs to query to determine if this host is offline
query_urls = [
    'https://google.com',
    'https://portquiz.net',
    'https://pypi.org'
]


def is_offline(max_num_tries=3, retry_time_sec=3, query_timeout_sec=5):
    """Queries URLs to see if this host is offline

    :param max_num_tries: (int) number of seconds to timeout after
    :param retry_time_sec: (int) number of seconds to retry the query
    :param query_timeout_sec: (int) number of re-tries before giving up
    :return: bool True if this system is running on AWS
    """
    log = logging.getLogger(mod_logger + '.is_offline')
    log.info('Querying URLs to determine if this system is offline...')

    # Keep track of the number of attempts
    attempt_num = 1

    while True:
        if attempt_num > max_num_tries:
            log.info('Max attempts to query for online URLs reached, determining this host ot be OFFLINE')
            return True

        # Query the list of URLs
        for query_url in query_urls:
            log.info('Attempting to query URL: {u}'.format(u=query_url))
            try:
                response = requests.get(query_url, timeout=query_timeout_sec)
            except(IOError, OSError) as ex:
                log.info('OSError querying URL: {u}\n{e}'.format(u=query_url, e=str(ex)))
                time.sleep(retry_time_sec)
                continue
            except requests.exceptions.ConnectTimeout as ex:
                log.info('Timeout after [{t}] seconds on query URL: {u}\n{e}'.format(
                    u=query_url, t=str(query_timeout_sec), e=str(ex)))
                time.sleep(retry_time_sec)
                continue

            # Check the code
            if 200 <= response.status_code < 400:
                log.info('Querying URL [{u}] returned code {c}, this system is ONLINE'.format(
                    u=query_url, c=response.status_code))
                return False
            log.warning('Querying URL [{u}] returned error code: {c}'.format(
                u=query_url, c=str(response.status_code)))
            time.sleep(retry_time_sec)

        # All 3 query URLs did not succeed, attempt completed and trying again
        attempt_num += 1
        time.sleep(retry_time_sec)
