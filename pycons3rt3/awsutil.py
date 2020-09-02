"""Module: awsutil

This module provides utilities for interacting with the AWS
API, common to other AWS utils in this project.

"""
import boto3
from botocore.client import ClientError

from .exceptions import AWSAPIError

__author__ = 'Joe Yennaco'


# Global list of all AWS regions divided into useful lists
foreign_regions = ['af-south-1', 'ap-east-1', 'ap-northeast-1', 'ap-northeast-2', 'ap-northeast-3', 'ap-south-1',
                   'ap-southeast-1', 'ap-southeast-2', 'ca-central-1', 'eu-central-1', 'eu-north-1', 'eu-south-1',
                   'eu-west-1', 'eu-west-2', 'eu-west-3', 'me-south-1', 'sa-east-1']
us_regions = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']
gov_regions = ['us-gov-east-1', 'us-gov-west-1']
global_regions = foreign_regions + us_regions
all_regions = global_regions + gov_regions


def get_boto3_client(service, region_name=None, aws_access_key_id=None, aws_secret_access_key=None,
                     aws_session_token=None):
    """Gets an EC2 client

    :param service: (str) name of the service to configure
    :param region_name: (str) name of the region
    :param aws_access_key_id: (str) AWS Access Key ID
    :param aws_secret_access_key: (str) AWS Secret Access Key
    :param aws_session_token: (str) AWS Session Token
    :return: boto3.client object
    :raises: AWSAPIError
    """
    try:
        client = boto3.client(
            service,
            region_name=region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token
        )
    except ClientError as exc:
        msg = 'Problem creating a boto3 client, ensure credentials and region are set appropriately.'
        raise AWSAPIError(msg) from exc
    return client
