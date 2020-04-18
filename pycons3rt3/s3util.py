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
import logging
import re
import os
import socket
import time

import boto3
from botocore.client import ClientError
from botocore.exceptions import EndpointConnectionError
from s3transfer.exceptions import RetriesExceededError

from .logify import Logify
from .exceptions import S3UtilError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.s3util'


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

    def list_objects_metadata_with_token(self, prefix=None, continuation_token=None):
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

    def list_objects_metadata(self, prefix=None):
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

        :param key_to_delete:
        :return:
        """
        log = logging.getLogger(self.cls_logger + '.delete_key')

        log.info('Attempting to delete key: {k}'.format(k=key_to_delete))
        try:
            self.s3client.delete_object(Bucket=self.bucket_name, Key=key_to_delete)
        except ClientError as exc:
            log.error('ClientError: Unable to delete key: {k}\n{e}'.format(k=key_to_delete, e=str(exc)))
            return False
        else:
            log.info('Successfully deleted key: {k}'.format(k=key_to_delete))
            return True


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
