#!/usr/bin/env python

import argparse
import logging
import sys
import traceback

from pycons3rt3.exceptions import S3UtilError
from pycons3rt3.logify import Logify
from pycons3rt3.s3util import S3Util

__author__ = 'Joe Yennaco'

# Set up logger name for this module
mod_logger = Logify.get_name() + '.delete_bucket'


def main():
    log = logging.getLogger(mod_logger + '.main')

    parser = argparse.ArgumentParser(description='Deletes S3 keys')
    parser.add_argument('-b', '--bucket', help='Name of the S3 bucket to delete', required=False)
    args = parser.parse_args()

    # Check for a --bucket arg, if not provided query the user for input
    if args.bucket:
        bucket_name = args.bucket
    else:
        bucket_name = input('Type the S3 bucket name to delete: ')

    # Create the S3Util for this bucket
    bucket = S3Util(bucket_name=bucket_name)

    # Validate the bucket exists
    try:
        bucket.validate_bucket()
    except S3UtilError as exc:
        print('Problem validating bucket [{b}]\n{e}'.format(b=bucket_name, e=str(exc)))
        traceback.print_exc()
        return 1

    # Attempt to delete the bucket
    log.info('Deleting bucket: {b}'.format(b=bucket_name))
    try:
        bucket.delete_bucket(enable_debug=True)
    except S3UtilError as exc:
        print('Problem deleting bucket [{b}]\n{e}'.format(b=bucket_name, e=str(exc)))
        traceback.print_exc()
        return 2

    log.info('Completed deleting bucket: {b}'.format(b=bucket_name))
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
