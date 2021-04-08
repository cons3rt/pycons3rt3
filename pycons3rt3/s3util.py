#!/usr/bin/python

"""Module: s3util

This module provides a set of useful utilities for accessing S3 buckets
in order to download and upload specific files. Sample usage is shown
below in the main module method.

Classes:
    S3Util: Provides a set of useful utilities for accessing S3 buckets
        in for finding, downloading and uploading objects.

    S3UtilError: Custom exception for raised when there is a problem
        connecting to S3, or a problem with a download or upload
        operation.
"""
import json
import logging
import re
import os
import socket
import threading
import time

import boto3
from botocore.client import ClientError
from botocore.exceptions import EndpointConnectionError
from s3transfer.exceptions import RetriesExceededError

from .awsutil import get_boto3_client
from .logify import Logify
from .exceptions import S3UtilError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.s3util'


class S3MultiUtil(threading.Thread):

    def __init__(self, client, bucket, s3_keys, bar=None):
        threading.Thread.__init__(self)
        self.cls_logger = mod_logger + '.S3MultiUtil'
        self.client = client
        self.bucket = bucket
        self.s3_keys = s3_keys
        self.bar = bar

    def run(self):
        pass


class S3Util(object):
    """Utility class for interacting with AWS S3

    This class provides a set of useful utilities for interacting with
    an AWS S3 bucket, including uploading and downloading files.

    Args:
        _bucket_name (str): Name of the S3 bucket to interact with.

    Attributes:
        bucket_name (dict): Name of the S3 bucket to interact with.
        s3client (boto3.client): Low-level client for interacting with
            the AWS S3 service.
        s3resource (boto3.resource): High level AWS S3 resource
        bucket (Bucket): S3 Bucket object for performing Bucket operations
    """
    def __init__(self, _bucket_name, region_name=None, aws_access_key_id=None, aws_secret_access_key=None):
        self.cls_logger = mod_logger + '.S3Util'
        log = logging.getLogger(self.cls_logger + '.__init__')
        self.bucket_name = _bucket_name

        log.debug('Configuring S3 client with AWS Access key ID {k} and region {r}'.format(
            k=aws_access_key_id, r=region_name))

        self.s3resource = boto3.resource('s3', region_name=region_name, aws_access_key_id=aws_access_key_id,
                                         aws_secret_access_key=aws_secret_access_key)
        try:
            self.s3client = boto3.client('s3', region_name=region_name, aws_access_key_id=aws_access_key_id,
                                         aws_secret_access_key=aws_secret_access_key)
        except ClientError as exc:
            msg = 'There was a problem connecting to S3, please check AWS configuration or credentials provided, ' \
                  'ensure credentials and region are set appropriately.'
            raise S3UtilError(msg) from exc
        self.validate_bucket()
        self.bucket = self.s3resource.Bucket(self.bucket_name)

    def validate_bucket(self):
        """Verify the specified bucket exists

        This method validates that the bucket name passed in the S3Util
        constructor actually exists.

        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.validate_bucket')
        log.info('Attempting to get bucket: {b}'.format(b=self.bucket_name))
        max_tries = 10
        count = 1
        while count <= max_tries:
            log.info('Attempting to connect to S3 bucket %s, try %s of %s',
                     self.bucket_name, count, max_tries)
            try:
                self.s3client.head_bucket(Bucket=self.bucket_name)
            except ClientError as exc:
                error_code = int(exc.response['Error']['Code'])
                log.debug(
                    'Connecting to bucket %s produced response code: %s',
                    self.bucket_name, error_code)
                if error_code == 404:
                    msg = 'Error 404 response indicates that bucket {b} does not exist'.format(b=self.bucket_name)
                    raise S3UtilError(msg) from exc
                elif error_code == 500 or error_code == 503:
                    if count >= max_tries:
                        msg = 'S3 bucket is not accessible at this time: {b}'.format(b=self.bucket_name)
                        raise S3UtilError(msg) from exc
                    else:
                        log.warning('AWS returned error code 500 or 503, re-trying in 2 sec...')
                        time.sleep(5)
                        count += 1
                        continue
                else:
                    msg = 'Connecting to S3 bucket {b} returned code: {c}'.format(b=self.bucket_name, c=error_code)
                    raise S3UtilError(msg) from exc
            except EndpointConnectionError as exc:
                raise S3UtilError from exc
            except socket.gaierror as exc:
                raise S3UtilError from exc
            else:
                log.info('Found bucket: %s', self.bucket_name)
                return

    def __download_from_s3(self, key, dest_dir):
        """Private method for downloading from S3

        This private helper method takes a key and the full path to
        the destination directory, assumes that the args have been
        validated by the public caller methods, and attempts to
        download the specified key to the dest_dir.

        :param key: (str) S3 key for the file to be downloaded
        :param dest_dir: (str) Full path destination directory
        :return: (str) Downloaded file destination if the file was
            downloaded successfully, None otherwise
        :raises: S3UtilError
        """
        log = logging.getLogger(self.cls_logger + '.__download_from_s3')
        filename = key.split('/')[-1]
        if filename is None:
            log.error('Could not determine the filename from key: %s', key)
            return None
        destination = dest_dir + '/' + filename
        log.info('Attempting to download %s from bucket %s to destination %s',
                 key, self.bucket_name, destination)
        max_tries = 10
        count = 1
        while count <= max_tries:
            log.info('Attempting to download file %s, try %s of %s', key, count, max_tries)
            try:
                self.s3client.download_file(
                    Bucket=self.bucket_name, Key=key, Filename=destination)
            except (ClientError, RetriesExceededError) as exc:
                if count >= max_tries:
                    msg = 'Unable to download key [{k}] from S3 bucket [{b}] after {n} attempts'.format(
                        k=key, b=self.bucket_name, n=str(max_tries))
                    raise S3UtilError(msg) from exc
                else:
                    log.warning('Download failed, re-trying...\n{e}'.format(e=str(exc)))
                    count += 1
                    time.sleep(5)
                    continue
            else:
                log.info('Successfully downloaded %s from S3 bucket %s to: %s',
                         key,
                         self.bucket_name,
                         destination)
                return destination

    def download_file_by_key(self, key, dest_dir):
        """Downloads a file by key from the specified S3 bucket

        This method takes the full 'key' as the arg, and attempts to
        download the file to the specified dest_dir as the destination
        directory. This method sets the downloaded filename to be the
        same as it is on S3.

        :param key: (str) S3 key for the file to be downloaded.
        :param dest_dir: (str) Full path destination directory
        :return: (str) Downloaded file destination if the file was
            downloaded successfully, None otherwise.
        :raises: S3UtilError
        """
        log = logging.getLogger(self.cls_logger + '.download_file_by_key')
        if not isinstance(key, str):
            log.error('key argument is not a string')
            return None
        if not isinstance(dest_dir, str):
            log.error('dest_dir argument is not a string')
            return None
        if not os.path.isdir(dest_dir):
            log.error('Directory not found on file system: %s', dest_dir)
            return None
        try:
            dest_path = self.__download_from_s3(key, dest_dir)
        except S3UtilError as exc:
            raise S3UtilError('Problem downloading S3 key: {k}'.format(k=key)) from exc
        return dest_path

    def download_file(self, regex, dest_dir):
        """Downloads a file by regex from the specified S3 bucket

        This method takes a regular expression as the arg, and attempts
        to download the file to the specified dest_dir as the
        destination directory. This method sets the downloaded filename
        to be the same as it is on S3.

        :param regex: (str) Regular expression matching the S3 key for
            the file to be downloaded.
        :param dest_dir: (str) Full path destination directory
        :return: (str) Downloaded file destination if the file was
            downloaded successfully, None otherwise.
        """
        log = logging.getLogger(self.cls_logger + '.download_file')
        if not isinstance(regex, str):
            log.error('regex argument is not a string')
            return None
        if not isinstance(dest_dir, str):
            log.error('dest_dir argument is not a string')
            return None
        if not os.path.isdir(dest_dir):
            log.error('Directory not found on file system: %s', dest_dir)
            return None
        key = self.find_key(regex)
        if key is None:
            log.warning('Could not find a matching S3 key for: %s', regex)
            return None
        try:
            dest_path = self.__download_from_s3(key, dest_dir)
        except S3UtilError as exc:
            raise S3UtilError('Problem downloading S3 key: {k}'.format(k=key)) from exc
        return dest_path

    def find_key(self, regex):
        """Attempts to find a single S3 key based on the passed regex

        Given a regular expression, this method searches the S3 bucket
        for a matching key, and returns it if exactly 1 key matches.
        Otherwise, None is returned.

        :param regex: (str) Regular expression for an S3 key
        :return: (str) Full length S3 key matching the regex, None
            otherwise
        """
        log = logging.getLogger(self.cls_logger + '.find_key')
        if not isinstance(regex, str):
            log.error('regex argument is not a string')
            return None
        log.info('Looking up a single S3 key based on regex: %s', regex)
        matched_keys = []
        for item in self.bucket.objects.all():
            log.debug('Checking if regex matches key: %s', item.key)
            match = re.search(regex, item.key)
            if match:
                matched_keys.append(item.key)
        if len(matched_keys) == 1:
            log.info('Found matching key: %s', matched_keys[0])
            return matched_keys[0]
        elif len(matched_keys) > 1:
            log.info('Passed regex matched more than 1 key: %s', regex)
            return None
        else:
            log.info('Passed regex did not match any key: %s', regex)
            return None

    def list_objects_metadata_with_token(self, prefix='', continuation_token=None):
        """Returns a list of S3 keys based on the provided token

        :param prefix: (str) Prefix to search on
        :param continuation_token: (str) S3 token to query on
        :return: (dict) response object containing response data
        """
        if continuation_token:
            return self.s3client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix,
                ContinuationToken=continuation_token
            )
        else:
            return self.s3client.list_objects_v2(
                Bucket=self.bucket_name,
                Prefix=prefix
            )

    def list_objects_metadata(self, prefix=''):
        """Lists S3 objects metadata in the S3 bucket matching the provided prefix

        :param prefix: (str) Prefix to search on
        :return: (list) of S3 bucket object metadata
        """
        log = logging.getLogger(self.cls_logger + '.list_objects_metadata')
        if not prefix:
            prefix_str = 'None'
        else:
            prefix_str = prefix
        continuation_token = None
        next_query = True
        object_metadata_list = []
        log.info('Attempting to list S3 keys in bucket {b} matching prefix: {p}'.format(
            b=self.bucket_name, p=prefix_str))
        while True:
            if not next_query:
                break
            response = self.list_objects_metadata_with_token(prefix=prefix, continuation_token=continuation_token)
            if 'IsTruncated' not in response.keys():
                log.warning('IsTruncated not found in response: {r}'.format(r=str(response.keys())))
                return object_metadata_list
            if 'Contents' not in response.keys():
                log.warning('Contents not found in response: {r}'.format(r=str(response.keys())))
                return object_metadata_list
            next_query = response['IsTruncated']
            object_metadata_list += response['Contents']
            if 'NextContinuationToken' not in response.keys():
                next_query = False
            else:
                continuation_token = response['NextContinuationToken']
        log.info('Found {n} objects matching prefix: {p}'.format(n=str(len(object_metadata_list)), p=prefix_str))
        return object_metadata_list

    def find_keys(self, regex, bucket_name=None):
        """Finds a list of S3 keys matching the passed regex

        Given a regular expression, this method searches the S3 bucket
        for matching keys, and returns an array of strings for matched
        keys, an empty array if non are found.

        :param regex: (str) Regular expression to use is the key search
        :param bucket_name: (str) Name of bucket to search (optional)
        :return: Array of strings containing matched S3 keys
        """
        log = logging.getLogger(self.cls_logger + '.find_keys')
        matched_keys = []
        if not isinstance(regex, str):
            log.error('regex argument is not a string, found: {t}'.format(t=regex.__class__.__name__))
            return None

        # Determine which bucket to use
        if bucket_name is None:
            s3bucket = self.bucket
        else:
            log.debug('Using the provided S3 bucket: {n}'.format(n=bucket_name))
            s3bucket = self.s3resource.Bucket(bucket_name)

        log.info('Looking up S3 keys based on regex: {r}'.format(r=regex))
        for item in s3bucket.objects.all():
            log.debug('Checking if regex matches key: {k}'.format(k=item.key))
            match = re.search(regex, item.key)
            if match:
                matched_keys.append(item.key)
        log.info('Found matching keys: {k}'.format(k=matched_keys))
        return matched_keys

    def upload_file(self, filepath, key):
        """Uploads a file using the passed S3 key

        This method uploads a file specified by the filepath to S3
        using the provided S3 key.

        :param filepath: (str) Full path to the file to be uploaded
        :param key: (str) S3 key to be set for the upload
        :return: True if upload is successful, False otherwise.
        """
        log = logging.getLogger(self.cls_logger + '.upload_file')
        log.info('Attempting to upload file %s to S3 bucket %s as key %s...',
                 filepath, self.bucket_name, key)

        if not isinstance(filepath, str):
            log.error('filepath argument is not a string')
            return False

        if not isinstance(key, str):
            log.error('key argument is not a string')
            return False

        if not os.path.isfile(filepath):
            log.error('File not found on file system: %s', filepath)
            return False

        try:
            self.s3client.upload_file(
                Filename=filepath, Bucket=self.bucket_name, Key=key)
        except ClientError as e:
            log.error('Unable to upload file %s to bucket %s as key %s:\n%s',
                      filepath, self.bucket_name, key, e)
            return False
        else:
            log.info('Successfully uploaded file to S3 bucket %s as key %s',
                     self.bucket_name, key)
            return True

    def delete_key(self, key_to_delete):
        """Deletes the specified key

        :param key_to_delete: (str) key to delete
        :return: bool
        """
        log = logging.getLogger(self.cls_logger + '.delete_key')

        log.info('Attempting to delete key: {k}'.format(k=key_to_delete))
        try:
            self.s3client.delete_object(Bucket=self.bucket_name, Key=key_to_delete)
        except ClientError as exc:
            log.debug('Unable to delete key: {k}\n{e}'.format(k=key_to_delete, e=str(exc)))
            return False
        log.debug('Successfully deleted key: {k}'.format(k=key_to_delete))
        return True

    def copy_object_in_same_bucket(self, current_key, new_key):
        """Copies the specified current key to a new key in the same bucket

        :param current_key: (str) key to copy
        :param new_key: (str) key to copy the object to
        :return: bool
        """
        log = logging.getLogger(self.cls_logger + '.copy_object_in_same_bucket')

        log.info('Attempting to copy key [{k}] to: {n}'.format(k=current_key, n=new_key))
        copy_source = {
            'Bucket': self.bucket_name,
            'Key': current_key
        }
        try:
            self.s3client.copy(copy_source, self.bucket_name, new_key)
        except ClientError as exc:
            log.debug('Unable to copy key [{k}] to: {n}\n{e}'.format(k=current_key, n=new_key, e=str(exc)))
            return False
        log.debug('Successfully copied key [{k}] to: {n}'.format(k=current_key, n=new_key))
        return True

    def copy_object_to_another_bucket(self, current_key, target_bucket, new_key):
        """Copies the specified current key to a new key in the target bucket

        :param current_key: (str) key to copy
        :param target_bucket: (str) name of the target bucket
        :param new_key: (str) key to copy the object to in the target bucket
        :return: bool
        """
        log = logging.getLogger(self.cls_logger + '.copy_object_to_another_bucket')

        log.info('Attempting to copy key [{k}] to bucket {b}: {n}'.format(k=current_key, b=target_bucket, n=new_key))
        copy_source = {
            'Bucket': self.bucket_name,
            'Key': current_key
        }
        try:
            self.s3client.copy(copy_source, target_bucket, new_key)
        except ClientError as exc:
            log.debug('Unable to copy key [{k}] to bucket: {b}\n{e}'.format(k=current_key, b=target_bucket, e=str(exc)))
            return False
        log.debug('Successfully copied key [{k}] to bucket {b}: {n}'.format(k=current_key, b=target_bucket, n=new_key))
        return True


############################################################################
# Methods for blocking public access
############################################################################


def block_public_access(client, bucket_name, block_public_acls=True, ignore_public_acls=True, block_public_policy=True,
                        restrict_public_buckets=True):
    """Enabled bucket encryption

    :param client: boto3.client
    :param bucket_name: (str) bucket name
    :param block_public_acls: (bool) Specifies whether Amazon S3 should block public access control lists (ACLs) for
        this bucket and objects in this bucket
    :param ignore_public_acls: (bool) Specifies whether Amazon S3 should ignore public ACLs for this bucket and
        objects in this bucket
    :param block_public_policy: (bool) Specifies whether Amazon S3 should block public bucket policies for this bucket
    :param restrict_public_buckets: (bool) Specifies whether Amazon S3 should restrict public bucket policies for this
        bucket
    :return: None
    :raises: S3UtilError
    """
    log = logging.getLogger(mod_logger + '.block_public_access')
    msg = 'For bucket [{n}], setting Block Public ACLs to [{b}], Ignore Public ACLs to [{i}], BlockPublic Policy to ' \
          '[{c}], and Restrict Public Buckets to [{r}]'.format(n=bucket_name, b=block_public_acls, i=ignore_public_acls,
                                                               c=block_public_policy, r=restrict_public_buckets)
    log.info(msg)
    try:
        client.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': block_public_acls,
                'IgnorePublicAcls': ignore_public_acls,
                'BlockPublicPolicy': block_public_policy,
                'RestrictPublicBuckets': restrict_public_buckets
            }
        )
    except ClientError as exc:
        msg = 'Problem setting block public access on [{n}]'.format(n=bucket_name)
        raise S3UtilError(msg) from exc


############################################################################
# Methods for creating S3 buckets
############################################################################


def create_bucket(client, bucket_name, region='us-east-1'):
    """Creates the specified bucket, if it already exists returns it

    Default configuration is set up

    :param client: boto3.client object
    :param bucket_name: (str) bucket name
    :param region: (str) region to create the bucket in
    :return: (dict) role data (specified in boto3)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.create_bucket')
    log.info('Attempting to create bucket [{n}]'.format(n=bucket_name))

    # Checking for existing bucket
    bucket_data = None
    existing_buckets = list_buckets(client=client)
    for existing_bucket in existing_buckets:
        if 'Name' not in existing_bucket.keys():
            log.warning('Name not found in bucket: {r}'.format(r=str(existing_bucket)))
            continue
        if bucket_name == existing_bucket['Name']:
            bucket_data = existing_bucket
    if bucket_data:
        log.info('Found existing bucket [{n}]'.format(n=bucket_name))
        return bucket_data
    log.info('Attempting to create bucket [{n}]'.format(n=bucket_name))
    try:
        response = client.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={
                'LocationConstraint': region
            }
        )
    except ClientError as exc:
        msg = 'Problem creating bucket [{n}]'.format(n=bucket_name)
        raise S3UtilError(msg) from exc
    if 'Location' not in response.keys():
        msg = 'Location not found in response: {d}'.format(d=str(response))
        raise S3UtilError(msg)
    log.info('Created new bucket: [{n}]'.format(n=bucket_name))
    return {
        'Name': bucket_name,
        'Location': response['Location']
    }


############################################################################
# Methods for downloading objects
############################################################################


def download(download_info):
    """Module  method for downloading from S3

    This public module method takes a key and the full path to
    the destination directory, assumes that the args have been
    validated by the public caller methods, and attempts to
    download the specified key to the dest_dir.

    :param download_info: (dict) Contains the following params
        key: (str) S3 key for the file to be downloaded
        dest_dir: (str) Full path destination directory
        bucket_name: (str) Name of the bucket to download from
        credentials: (dict) containing AWS credential info (optional)
            aws_region: (str) AWS S3 region
            aws_access_key_id: (str) AWS access key ID
            aws_secret_access_key: (str) AWS secret access key
    :return: (str) Downloaded file destination if the file was
        downloaded successfully
    :raises S3UtilError
    """
    log = logging.getLogger(mod_logger + '.download')

    # Ensure the passed arg is a dict
    if not isinstance(download_info, dict):
        msg = 'download_info arg should be a dict, found: {t}'.format(t=download_info.__class__.__name__)
        raise TypeError(msg)

    # Check for and obtain required args
    required_args = ['key', 'dest_dir', 'bucket_name']
    for required_arg in required_args:
        if required_arg not in download_info:
            msg = 'Required arg not provided: {r}'.format(r=required_arg)
            log.error(msg)
            raise S3UtilError(msg)

    log.debug('Processing download request: {r}'.format(r=download_info))
    key = download_info['key']
    dest_dir = download_info['dest_dir']
    bucket_name = download_info['bucket_name']
    region_name = None
    aws_access_key_id = None
    aws_secret_access_key = None

    try:
        creds = download_info['credentials']
    except KeyError:
        log.debug('No credentials found for this download request')
    else:
        try:
            region_name = creds['region_name']
            aws_access_key_id = creds['aws_access_key_id']
            aws_secret_access_key = creds['aws_secret_access_key']
        except KeyError:
            log.warning('Insufficient credentials found for download request')
            region_name = None
            aws_access_key_id = None
            aws_secret_access_key = None

    log.debug('Configuring S3 client with AWS Access key ID {k} and region {r}'.format(
        k=aws_access_key_id, r=region_name))

    # Establish an S3 client
    client = boto3.client('s3', region_name=region_name, aws_access_key_id=aws_access_key_id,
                          aws_secret_access_key=aws_secret_access_key)

    # Attempt to determine the file name from key
    filename = key.split('/')[-1]
    if filename is None:
        msg = 'Could not determine the filename from key: {k}'.format(k=key)
        log.error(msg)
        raise S3UtilError(msg)

    # Set the destination
    destination = os.path.join(dest_dir, filename)

    # Return if the destination file was already downloaded
    if os.path.isfile(destination):
        log.info('File already downloaded: {d}'.format(d=destination))
        return destination

    # Attempt the download
    log.info('Attempting to download %s from bucket %s to destination %s',
             key, bucket_name, destination)
    max_tries = 10
    retry_timer = 5
    count = 1
    while count <= max_tries:
        log.info('Attempting to download file {k}: try {c} of {m}'.format(k=key, c=count, m=max_tries))
        try:
            client.download_file(Bucket=bucket_name, Key=key, Filename=destination)
        except ClientError as exc:
            if count >= max_tries:
                msg = 'Unable to download key {k} from S3 bucket {b}'.format(k=key, b=bucket_name)
                raise S3UtilError(msg) from exc
            else:
                log.warning('Download failed, re-trying in {t} sec...'.format(t=retry_timer))
                count += 1
                time.sleep(retry_timer)
                continue
        else:
            log.info('Successfully downloaded {k} from S3 bucket {b} to: {d}'.format(
                    k=key, b=bucket_name, d=destination))
            return destination


############################################################################
# Methods for enabling default encryption
############################################################################


def enable_bucket_encryption(client, bucket_name, kms_id=None):
    """Enabled bucket encryption

    :param client: boto3.client
    :param bucket_name: (str) bucket name
    :param kms_id: (str) AWS Key Management Service (KMS) customer master key ID to use for the default encryption.
        You can specify the key ID or the Amazon Resource Name (ARN) of the CMK. However, if you are using encryption
        with cross-account operations, you must use a fully qualified CMK ARN. For more information, see Using
        encryption for cross-account operations.
    :return: None
    :raises: S3UtilError
    """
    log = logging.getLogger(mod_logger + '.enable_bucket_encryption')

    if kms_id:
        rule = {
            'ApplyServerSideEncryptionByDefault': {
                'SSEAlgorithm': 'aws:kms',
                'KMSMasterKeyID': kms_id
            }
        }
        msg = 'Enabling default encryption on [{n}] with KMS ID  [{k}]'.format(n=bucket_name, k=kms_id)
    else:
        rule = {
            'ApplyServerSideEncryptionByDefault': {
                'SSEAlgorithm': 'AES256',
            }
        }
        msg = 'Enabling default encryption on [{n}] with AES256'.format(n=bucket_name)
    rules = [rule]
    log.info(msg)
    try:
        client.put_bucket_encryption(
            Bucket=bucket_name,
            ServerSideEncryptionConfiguration={'Rules': rules}
        )
    except ClientError as exc:
        msg = 'Problem enabling bucket encryption on [{n}]'.format(n=bucket_name)
        raise S3UtilError(msg) from exc


############################################################################
# Methods for enabling logging
############################################################################


def enable_bucket_logging(client, bucket_name, target_bucket, prefix):
    """Enable bucket logging

    :param client: boto3.client
    :param bucket_name: (str) bucket name
    :param target_bucket: (str) target bucket name
    :param prefix: (str) prefix to append to logs stored in the target bucket
    :return: None
    :raises: S3UtilError
    """
    log = logging.getLogger(mod_logger + '.enable_bucket_logging')
    log.info('Enabling logging on bucket [{n}] to target bucket [{t}] with prefix [{p}]'.format(
        n=bucket_name, t=target_bucket, p=prefix))
    try:
        client.put_bucket_logging(
            Bucket=bucket_name,
            BucketLoggingStatus={
                'LoggingEnabled': {
                    'TargetBucket': target_bucket,
                    'TargetPrefix': prefix
                }
            }
        )
    except ClientError as exc:
        msg = 'Problem enabling bucket logging on [{n}]'.format(n=bucket_name)
        raise S3UtilError(msg) from exc


def enable_bucket_log_delivery(client, target_bucket_name):
    """Adds an ACL to allow log delivery to the provided target bucket.  Once configured, other buckets can
    send logs to this bucket

    :param client: boto3.client
    :param target_bucket_name: (str) bucket name of the logging target
    :return: None
    :raises: S3UtilError
    """
    log = logging.getLogger(mod_logger + '.enable_bucket_log_delivery')
    log.info('Enabling log delivery on target bucket [{n}]'.format(n=target_bucket_name))

    # Get the current ACL
    try:
        response = client.get_bucket_acl(Bucket=target_bucket_name)
    except ClientError as exc:
        msg = 'Problem getting ACL for bucket [{n}]'.format(n=target_bucket_name)
        raise S3UtilError(msg) from exc
    if 'Grants' not in response.keys():
        msg = 'Grants not found in response: {d}'.format(d=str(response))
        raise S3UtilError(msg)
    if 'Owner' not in response.keys():
        msg = 'Owner not found in response: {d}'.format(d=str(response))
        raise S3UtilError(msg)
    existing_grants = response['Grants']
    owner = response['Owner']

    # Determine the log delivery URI based on region
    log_delivery_uri = 'http://acs.amazonaws.com/groups/s3/LogDelivery'

    new_grants = [
        {
            'Grantee': {
                'URI': log_delivery_uri,
                'Type': 'Group'
            },
            'Permission': 'WRITE'
        },
        {
            'Grantee': {
                'URI': log_delivery_uri,
                'Type': 'Group'
            },
            'Permission': 'READ_ACP'
        }
    ]

    # Append existing ACL
    new_grants += existing_grants

    # Update the bucket ACL
    try:
        client.put_bucket_acl(
            Bucket=target_bucket_name,
            AccessControlPolicy={
                'Grants': new_grants,
                'Owner': owner
            }
        )
    except ClientError as exc:
        msg = 'Problem enabling bucket logging on [{n}]'.format(n=target_bucket_name)
        raise S3UtilError(msg) from exc


############################################################################
# Methods for enabling versioning
############################################################################


def enable_bucket_versioning(client, bucket_name, enable=True, mfa_delete=False, mfa_device=None):
    """Enable bucket versioning

    :param client: boto3.client
    :param bucket_name: (str) bucket name
    :param enable: (bool) Set True to enable, False to suspend versioning
    :param mfa_delete: (bool) Set True to force MFA for object deletion
    :param mfa_device: (str) ARN of the MFA device for this request
    :return: None
    :raises: S3UtilError
    """
    log = logging.getLogger(mod_logger + '.enable_bucket_versioning')
    log.info('Enabling versioning on bucket: {n}'.format(n=bucket_name))

    status = 'Suspended'
    if enable:
        status = 'Enabled'

    mfa_status = 'Disabled'
    if mfa_delete:
        mfa_status = 'Enabled'

    mfa_str = None
    if mfa_device:
        mfa_totp = input('Enter your MFA code for [{d}]: '.format(d=mfa_device))
        mfa_str = '{d} {c}'.format(d=mfa_device, c=mfa_totp)

    try:
        if mfa_str:
            client.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={
                    'MFADelete': mfa_status,
                    'Status': status
                },
                MFA=mfa_str
            )
        else:
            client.put_bucket_versioning(
                Bucket=bucket_name,
                VersioningConfiguration={
                    'MFADelete': mfa_status,
                    'Status': status
                }
            )
    except ClientError as exc:
        msg = 'Problem enabling bucket versioning on [{n}]'.format(n=bucket_name)
        raise S3UtilError(msg) from exc


############################################################################
# Methods for finding objects
############################################################################


def find_bucket_keys(bucket_name, regex, region_name=None, aws_access_key_id=None, aws_secret_access_key=None):
    """Finds a list of S3 keys matching the passed regex

    Given a regular expression, this method searches the S3 bucket
    for matching keys, and returns an array of strings for matched
    keys, an empty array if non are found.

    :param regex: (str) Regular expression to use is the key search
    :param bucket_name: (str) String S3 bucket name
    :param region_name: (str) AWS region for the S3 bucket (optional)
    :param aws_access_key_id: (str) AWS Access Key ID (optional)
    :param aws_secret_access_key: (str) AWS Secret Access Key (optional)
    :return: Array of strings containing matched S3 keys
    """
    log = logging.getLogger(mod_logger + '.find_bucket_keys')
    matched_keys = []
    if not isinstance(regex, str):
        log.error('regex argument is not a string, found: {t}'.format(t=regex.__class__.__name__))
        return None
    if not isinstance(bucket_name, str):
        log.error('bucket_name argument is not a string, found: {t}'.format(t=bucket_name.__class__.__name__))
        return None

    # Set up S3 resources
    s3resource = boto3.resource('s3', region_name=region_name, aws_access_key_id=aws_access_key_id,
                                aws_secret_access_key=aws_secret_access_key)
    bucket = s3resource.Bucket(bucket_name)

    log.info('Looking up S3 keys based on regex: {r}'.format(r=regex))
    for item in bucket.objects.all():
        log.debug('Checking if regex matches key: {k}'.format(k=item.key))
        match = re.search(regex, item.key)
        if match:
            matched_keys.append(item.key)
    log.info('Found matching keys: {k}'.format(k=matched_keys))
    return matched_keys


############################################################################
# Getting a boto3 client object for S3
############################################################################


def get_s3_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
    """Gets an S3 client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    return get_boto3_client(service='s3', region_name=region_name, aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)


############################################################################
# Listing S3 buckets
############################################################################


def list_buckets(client):
    """Returns a list of S3 buckets

    :param client: boto3.client
    :return: (list) of (dict) S3 buckets (see boto3 docs
    """
    log = logging.getLogger(mod_logger + '.list_buckets')
    log.info('Attempting to list S3 buckets...')
    try:
        response = client.list_buckets()
    except ClientError as exc:
        msg = 'Problem listing S3 buckets'
        raise S3UtilError(msg) from exc
    if 'Buckets' not in response.keys():
        msg = 'Buckets not found in response: {d}'.format(d=str(response))
        raise S3UtilError(msg)
    return response['Buckets']


############################################################################
# Methods for setting bucket policy
############################################################################


def set_bucket_policy(client, bucket_name, policy_document):
    """Set the bucket policy to the provided

    :param client: boto3.client
    :param bucket_name: (str) bucket name
    :param policy_document: (str) path to JSON policy file
    :return: None
    :raises: S3UtilError
    """
    log = logging.getLogger(mod_logger + '.set_bucket_policy')
    log.info('Setting policy on bucket [{n}] to policy document [{d}]'.format(
        n=bucket_name, d=policy_document))

    # Ensure the file exists
    if not os.path.isfile(policy_document):
        raise S3UtilError('Policy document not found: {f}'.format(f=policy_document))
    try:
        with open(policy_document, 'r') as f:
            policy_document_data = json.load(f)
    except(OSError, IOError) as exc:
        raise S3UtilError('Unable to read policy file: {f}'.format(f=policy_document)) from exc
    log.info('Loading policy from file: {f}'.format(f=policy_document))
    json_policy_data = json.dumps(policy_document_data)

    # Replace account ID in the policy
    json_policy_data = json_policy_data.replace('REPLACE_ACCOUNT_ID', '12345')

    try:
        client.put_bucket_policy(Bucket=bucket_name, Policy=json_policy_data)
    except ClientError as exc:
        msg = 'Problem setting bucket policy for [{n}] to [{d}] with contents:\n{c}'.format(
            n=bucket_name, d=policy_document, c=json_policy_data)
        raise S3UtilError(msg) from exc


def main():
    """Sample usage for this python module

    This main method simply illustrates sample usage for this python
    module.

    :return: None
    """
    log = logging.getLogger(mod_logger + '.main')
    log.debug('This is DEBUG!')
    log.info('This is INFO!')
    log.warning('This is WARNING!')
    log.error('This is ERROR!')
    log.info('Running s3util.main...')
    my_bucket = 'cons3rt-deploying-cons3rt'
    my_regex = 'sourcebuilder.*apache-maven-.*3.3.3.*'
    try:
        s3util = S3Util(my_bucket)
    except S3UtilError as e:
        log.error('There was a problem creating S3Util:\n%s', e)
    else:
        log.info('Created S3Util successfully')
        key = s3util.find_key(my_regex)
        test = None
        if key is not None:
            test = s3util.download_file(key, '/Users/yennaco/Downloads')
        if test is not None:
            upload = s3util.upload_file(test, 'media-files-offline-assets/test')
            log.info('Upload result: %s', upload)
    log.info('End of main!')


if __name__ == '__main__':
    main()
