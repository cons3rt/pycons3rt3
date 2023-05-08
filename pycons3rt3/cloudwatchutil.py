"""Module: cloudwatchutil

This module provides utilities for interacting AWS Cloudwatch Logs

"""
import logging

from botocore.client import ClientError

from .awsutil import get_boto3_client
from .exceptions import CloudwatchUtilError
from .logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.cloudwatchutil'


class CloudwatchUtil(object):
    """Utility for interacting with the AWS Cloudwatch API
    """
    def __init__(self, region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
        self.cls_logger = mod_logger + '.CloudwatchUtil'
        try:
            self.client = get_log_client(region_name=region_name, aws_access_key_id=aws_access_key_id,
                                         aws_secret_access_key=aws_secret_access_key,
                                         aws_session_token=aws_session_token)
        except ClientError as exc:
            msg = 'Unable to create an IAM client'
            raise CloudwatchUtilError(msg) from exc
        self.region = self.client.meta.region_name

    def associate_kms_key(self, log_group_name, kms_key_arn):
        return associate_kms_key(client=self.client, log_group_name=log_group_name, kms_key_arn=kms_key_arn)

    def list_log_groups(self):
        return list_log_groups(client=self.client)


############################################################################
# Getting a boto3 client object for Cloudwatch
############################################################################


def get_log_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
    """Gets an IAM client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    return get_boto3_client(service='logs', region_name=region_name, aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)


############################################################################
# Methods for listing log groups
############################################################################


def list_log_groups_with_marker(client, marker=None):
    """Returns a list of Log Groups using the provided marker

    :param client: boto3.client object
    :param marker: (str) token to query on
    :return: (dict) response object containing response data
    """
    if marker:
        return client.describe_log_groups(nextToken=marker)
    else:
        return client.describe_log_groups()


def list_log_groups(client):
    """Lists Log Groups

    :param client: boto3.client object
    :return: (list) of groups (dict)
    :raises: CloudwatchUtilError
    """
    log = logging.getLogger(mod_logger + '.list_log_groups')
    marker = None
    next_query = True
    log_group_list = []
    log.info('Attempting to list cloudwatch log groups...')
    while True:
        if not next_query:
            break
        response = list_log_groups_with_marker(client=client, marker=marker)
        if 'logGroups' not in response.keys():
            log.warning('logGroups not found in response: {r}'.format(r=str(response)))
            return log_group_list
        log_group_list += response['logGroups']
        if 'nextToken' not in response.keys():
            next_query = False
        else:
            marker = response['nextToken']
            next_query = True
    log.info('Found {n} cloudwatch log groups'.format(n=str(len(log_group_list))))
    return log_group_list


############################################################################
# Methods for associating a KMS key
############################################################################


def associate_kms_key(client, log_group_name, kms_key_arn):
    """Associates a KMS key ID with the log group

    :param client: boto3.client object
    :param log_group_name: (str) Name of the log group
    :param kms_key_arn: (str) Full ARN of the KMS key
    :return: None
    :raises: CloudwatchUtilError
    """
    log = logging.getLogger(mod_logger + '.associate_kms_key')
    log.info('Associating KMS key [{k}] with log group: {g}'.format(k=kms_key_arn, g=log_group_name))
    try:
        client.associate_kms_key(
            logGroupName='string',
            kmsKeyId='string'
        )
    except ClientError as exc:
        msg = 'Problem associating KMS key [{k}] with log group: {g}'.format(k=kms_key_arn, g=log_group_name)
        raise CloudwatchUtilError(msg) from exc
