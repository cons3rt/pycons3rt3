"""Module: stsutil

This module provides utilities for interacting AWS STS

"""
import logging

from botocore.client import ClientError

from .awsutil import get_boto3_client
from .logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.stsutil'


def get_caller_identity(client=None):
    """Gets the identity of the calling client

    :param client: boto3.client (see boto3 docs)
    :return: (dict) caller identity or None
    """
    log = logging.getLogger(mod_logger + '.get_caller_identity')
    if not client:
        client = get_sts_client()
    try:
        response = client.get_caller_identity()
    except ClientError as exc:
        log.warning('Problem getting caller identity\n{e}'.format(e=str(exc)))
        return
    return response


def get_sts_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
    """Gets a Route53 client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    return get_boto3_client(service='sts', region_name=region_name, aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)
