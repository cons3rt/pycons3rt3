"""Module: kmsutil

This module provides utilities for interacting AWS KMS

"""
import logging
import os
import shutil
import time

from botocore.client import ClientError

from .awsutil import get_boto3_client
from .exceptions import KmsUtilError
from .logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.kmsutil'


def get_kms_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
    """Gets an STS client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    return get_boto3_client(service='kms', region_name=region_name, aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)


def get_kms_key(client, key_id):
    """Returns detailed info about the KMS key ID

    :param client: boto3.client object
    :param key_id: (str) ID of the key to retrieve
    :return: (dict) data about the key (see boto3 docs)
    :raises: EC2UtilError
    """
    log = logging.getLogger(mod_logger + '.get_kms_key')
    log.info('Getting info about KMS Key ID: {i}'.format(i=key_id))
    try:
        response = client.describe_key(KeyId=key_id)
    except ClientError as exc:
        msg = 'Unable to describe key ID: {a}'.format(a=key_id)
        raise KmsUtilError(msg) from exc
    if 'KeyMetadata' not in response.keys():
        msg = 'KeyMetadata not found in response: {r}'.format(r=str(response))
        raise KmsUtilError(msg)
    return response['KeyMetadata']
