#!/usr/bin/env python

"""Module: s3deleter

This module it a utility for deleting S3 objects from the specified S3 bucket matching the provided prefix

"""
import argparse
import logging
import sys
import progressbar
import random
import traceback
from .exceptions import S3OrganizationError
from .logify import Logify
from .s3util import S3Util


__author__ = 'Joe Yennaco'


# Set up logger name for this module
log_tag = 's3deleter'
mod_logger = Logify.get_name() + '.' + log_tag

widgets = [
    progressbar.AnimatedMarker(),
    ' help proceeding ',
    progressbar.AnimatedMarker(),
    ' [', progressbar.SimpleProgress(), '] ',
    ' [', progressbar.Timer(), '] ',
    progressbar.Bar(),
    ' (', progressbar.ETA(), ') ',
]


def show_deletes(command_str, deletes):
    """Displays objects before deletion

    :param command_str: (str) command to execute
    :param deletes: (list) of S3 objects to be deleted
    :return: bool
    """
    print('\n###############################################################################')
    print('-- Number of objects for [{c}]:\t\t{n}'.format(c=command_str, n=str(len(deletes))))
    print_num = 3
    while True:
        if print_num == 0 or len(deletes) < 10:
            print('-- Showing all {n} items for [{c}]:\n'.format(c=command_str, n=str(len(deletes))))
            for delete in deletes:
                print('-- Deleting: ' + delete)
        else:
            print('-- Showing {n} randomly selected objects of {t} for [{c}]:\n'.format(
                c=command_str, n=str(print_num), t=str(len(deletes))))
            for _ in range(print_num):
                print('-- {c}: '.format(c=command_str) + random.choice(deletes))
        ans = input('\nType a number, all, c to continue, or n to exit: ').lower()
        if not ans:
            print_num = 3
            continue
        if ans == 'n':
            return False
        if ans == 'c':
            return True
        if ans == 'all':
            print_num = 0
            continue
        try:
            print_num = int(ans)
        except ValueError:
            print_num = 3
            continue


def show_non_deletes(command_str, non_deletes, excludes):
    """Displays objects before deletion

    :param command_str: (str) command to execute
    :param non_deletes: (list) of S3 objects NOT to be deleted
    :param excludes: (list) of S3 objects excluded from deletion
    :return: bool
    """
    print('\n###############################################################################')
    total_not_deletes = non_deletes + excludes
    print('-- Number of objects NOT included in [{c}]:\t\t{n}'.format(c=command_str, n=str(len(total_not_deletes))))
    print_num = 3
    while True:
        if print_num == 0 or len(total_not_deletes) < 10:
            print('-- Showing all {n} items NOT included in [{c}]:\n'.format(
                c=command_str, n=str(len(total_not_deletes))))
            for delete in total_not_deletes:
                print('-- Not processing: ' + delete)
        else:
            print('-- Showing {n} randomly selected objects of {t} NOT included in [{c}]:\n'.format(
                c=command_str, n=str(print_num), t=str(len(total_not_deletes))))
            for _ in range(print_num):
                print('-- Not processing: ' + random.choice(total_not_deletes))
        ans = input('\nType a number, all, c to continue, or n to exit: ').lower()
        if not ans:
            print_num = 3
            continue
        if ans == 'n':
            return False
        if ans == 'c':
            return True
        if ans == 'all':
            print_num = 0
            continue
        try:
            print_num = int(ans)
        except ValueError:
            print_num = 3
            continue


def prompt_for_confirmation(bucket, num_deletes, num_keeps, prefix, exclude_list, organize):
    """Prompts for confirmation to delete objects from the S3 bucket

    :param bucket: (str) bucket name
    :param num_deletes: (int) number of objects to be deleted
    :param num_keeps: (int) number of objects to keep
    :param prefix: (str) prefix
    :param exclude_list: (list) of string excluded from deletion
    :param organize: (str) New prefix to copy deletes to
    :return: bool
    """
    print('\n###############################################################################')
    print('-- Processing S3 objects from bucket:\t\t{b}'.format(b=bucket))
    print('-- Number of objects to be deleted:\t\t{n}'.format(n=str(num_deletes)))
    print('-- Number of objects to keep:\t\t\t{n}'.format(n=str(num_keeps)))
    print('-- Prefix of objects to be deleted:\t\t{p}'.format(p=prefix))
    if exclude_list:
        print('-- Excluded from deletion:\t\t\t{e}'.format(e=','.join(exclude_list)))
    if organize:
        print('-- Organizing objects under folder:\t\t{f}'.format(f=organize))
    print('###############################################################################\n')
    while True:
        ans = input('Please confirm for delete of {n} objects (y/n): '.format(n=str(num_deletes))).lower()
        if not ans:
            print('please enter y or n')
            continue
        if ans not in ['y', 'n']:
            print('please enter y or n')
            continue
        if ans == 'y':
            print('Deletion confirmed, proceeding...\n')
            return True
        if ans == 'n':
            print('Not doing anything!\n')
            return False


def organize_s3_keys(command, bucket, target_bucket=None, prefix=None, exclude_list=None, length=0, exclude_length=0,
                     organize=None):
    """Deletes S3 keys from the provided bucket using prefix and exclude list as filters

    :param command: (str) command
    :param bucket: (str) name of the S3 bucket
    :param target_bucket: (str) name of the target S3 bucket to sync to
    :param prefix: (str) prefix to include in the search
    :param exclude_list: (list) of strings to exclude
    :param length: (int) specific length of chars for the file name to include
    :param exclude_length: (int) specific length of chars for the file name to exclude
    :param organize: (str) New prefix to copy the key to before delete the S3 keys
    :return: (tuple) list of deleted S3 keys or None, list of failed deleted S3 keys
    :raises: S3OrganizationError
    """
    deleted_s3_keys = []
    Logify.set_log_level(log_level='WARNING')

    if not command:
        raise S3OrganizationError('command arg is required')
    if command == 'all':
        command_str = 'sync and delete'
    else:
        command_str = command

    if not prefix:
        prefix_str = 'None'
    else:
        if not isinstance(prefix, str):
            raise S3OrganizationError('prefix arg must be a string')
        prefix_str = prefix

    if organize:
        if not isinstance(organize, str):
            raise S3OrganizationError('organize arg must be a string')
        if organize == '':
            raise S3OrganizationError('organize arg must not be an empty string')

    # Create a pycons3rt3.s3util
    s3util = S3Util(bucket)

    # Gather all objects from the S3 bucket
    print('\nGathering objects in S3 bucket [{b}]...'.format(b=bucket))
    s3objects = s3util.list_objects_metadata()
    print('Found {n} objects in bucket: {b}'.format(n=str(len(s3objects)), b=bucket))

    # Filter S3 keys matching the prefix string
    s3_keys_with_matched_prefix = []
    s3_keys_with_unmatched_prefix = []
    print('\nSearching for S3 objects in S3 bucket [{b}] with prefix: {p}'.format(b=bucket, p=prefix_str))
    for s3object in s3objects:
        if not prefix:
            s3_keys_with_matched_prefix.append(s3object['Key'])
            continue
        if s3object['Key'].startswith(prefix):
            s3_keys_with_matched_prefix.append(s3object['Key'])
        else:
            s3_keys_with_unmatched_prefix.append(s3object['Key'])

    print('Found {n} objects in bucket {b} matching prefix: {p}'.format(
        n=str(len(s3_keys_with_matched_prefix)), b=bucket, p=prefix_str))
    print('Found {n} objects in bucket {b} NOT matching prefix: {p}'.format(
        n=str(len(s3_keys_with_unmatched_prefix)), b=bucket, p=prefix_str))

    # Filtering keys based on length
    s3_keys_with_matched_length = []
    if length < 1:
        s3_keys_with_matched_length = list(s3_keys_with_matched_prefix)
    else:
        for s3_key in s3_keys_with_matched_prefix:
            file_name = s3_key.split('/')[-1]
            if len(file_name) == length:
                s3_keys_with_matched_length.append(s3_key)

    # Remove keys with matching prefixes that are on the exclude list
    s3_keys_to_delete = []
    s3_keys_to_exclude = []
    s3_keys_failed_to_delete = []
    if not exclude_list:
        exclude_list = []
    print('Filtering list based on exclude list: {e}'.format(e=','.join(exclude_list)))
    for s3_key in s3_keys_with_matched_length:
        is_excluded = False
        for exclude_item in exclude_list:
            if exclude_item in s3_key:
                # print('Excluding S3 key from deletion list: {k}'.format(k=s3_key))
                s3_keys_to_exclude.append(s3_key)
                is_excluded = True
                break
        if exclude_length > 0:
            file_name = s3_key.split('/')[-1]
            if len(file_name) == exclude_length:
                s3_keys_to_exclude.append(s3_key)
                is_excluded = True
        if not is_excluded:
            s3_keys_to_delete.append(s3_key)

    if len(s3_keys_to_delete) < 1:
        print('\n###############################################################################')
        print('No S3 keys to delete!')
        print('###############################################################################\n')
        return deleted_s3_keys, s3_keys_failed_to_delete

    print('Number of S3 objects for [{c}]: {n}'.format(c=command_str, n=str(len(s3_keys_to_delete))))
    print('Number of S3 objects excluded based on the provided exclude list: {n}'.format(
        n=str(len(s3_keys_to_exclude))))

    if not show_non_deletes(command_str=command_str, non_deletes=s3_keys_with_unmatched_prefix,
                            excludes=s3_keys_to_exclude):
        return deleted_s3_keys, s3_keys_failed_to_delete

    if not show_deletes(command_str=command_str, deletes=s3_keys_to_delete):
        return deleted_s3_keys, s3_keys_failed_to_delete

    num_keeps = len(s3_keys_with_unmatched_prefix) + len(s3_keys_to_exclude)
    if not prompt_for_confirmation(bucket=bucket, num_deletes=len(s3_keys_to_delete), num_keeps=num_keeps,
                                   prefix=prefix_str, exclude_list=exclude_list, organize=organize):
        return deleted_s3_keys, s3_keys_failed_to_delete

    # Delete or organize S3 keys
    bar = progressbar.ProgressBar(max_value=len(s3_keys_to_delete), widgets=widgets)
    for index, s3_key_to_delete in enumerate(s3_keys_to_delete):
        if command in ['sync', 'all']:
            new_key = organize + '/' + s3_key_to_delete
            if not s3util.copy_object_to_another_bucket(
                    current_key=s3_key_to_delete,
                    target_bucket=target_bucket,
                    new_key=new_key
            ):
                print('Failed to sync object: {k}'.format(k=s3_key_to_delete))
                continue
        if command in ['delete', 'all']:
            if s3util.delete_key(key_to_delete=s3_key_to_delete):
                deleted_s3_keys.append(s3_key_to_delete)
            else:
                s3_keys_failed_to_delete.append(s3_key_to_delete)
                print('Failed to delete: {d}'.format(d=s3_key_to_delete))
        bar.update(index)

    print('\nComplete!')
    print('###############################################################################')
    print('Successful deletions:\t\t{n}'.format(n=len(deleted_s3_keys)))
    print('Failed deletions:\t\t{n}'.format(n=len(s3_keys_failed_to_delete)))
    print('###############################################################################\n')
    return deleted_s3_keys, s3_keys_failed_to_delete


def main():
    log = logging.getLogger(mod_logger + '.main')
    log.info('Running: ' + log_tag)
    print('Running: ' + log_tag)

    # Add optional args to this script
    parser = argparse.ArgumentParser(description='Deletes S3 keys')
    parser.add_argument('command', help='Command for the helpful S3 utility')
    parser.add_argument('-b', '--bucket', help='Name of the S3 bucket', required=True)
    parser.add_argument('-t', '--targetbucket', help='Name of the target S3 bucket to sync to', required=False)
    parser.add_argument('-p', '--prefix', help='Prefix to filter S3 keys on', required=False)
    parser.add_argument('-e', '--exclude', help='List of regex to exclude deletion of matching keys', required=False)
    parser.add_argument('-o', '--organize', help='Prefix for synced files to the new bucket', required=False)
    parser.add_argument('-l', '--length', help='Length of file names to sync/delete', required=False)
    parser.add_argument('-x', '--excludelength', help='Length of file names to exclude from sync/delete',
                        required=False)
    args = parser.parse_args()

    # Get the command
    valid_commands = ['delete', 'sync', 'all']
    valid_commands_str = ','.join(valid_commands)

    if not args.command:
        print('No command found, use one of: {v}\n'.format(v=valid_commands_str))
    command = args.command.strip().lower()
    if command not in valid_commands:
        print('Invalid command found [{c}], use one of: {v}\n'.format(c=command, v=valid_commands_str))
        return 1

    if args.bucket:
        bucket = args.bucket
    else:
        print('The --bucket required')
        return 1
    target_bucket = None
    if args.targetbucket:
        target_bucket = args.targetbucket
    prefix = None
    if args.prefix:
        prefix = args.prefix
    exclude = None
    if args.exclude:
        exclude = args.exclude.split(',')
    if args.organize:
        organize = args.organize
    else:
        organize = bucket
    length = 0
    if args.length:
        try:
            length = int(args.length)
        except ValueError as exc:
            print('Invalid length, must be an integer\n{e}'.format(e=str(exc)))
            return 1
    exclude_length = 0
    if args.excludelength:
        try:
            exclude_length = int(args.excludelength)
        except ValueError as exc:
            print('Invalid excludelength, must be an integer\n{e}'.format(e=str(exc)))
            return 1

    if command in ['sync', 'all']:
        if not target_bucket:
            print('The --targetbucket arg is required for sync')
            return 1

    try:
        organize_s3_keys(command=command, bucket=bucket, target_bucket=target_bucket, prefix=prefix,
                         exclude_list=exclude, organize=organize, length=length, exclude_length=exclude_length)
    except S3OrganizationError as exc:
        print('Problem syncing/deleting S3 keys\n{e}'.format(e=str(exc)))
        traceback.print_exc()
        return 2

    print('Completed: ' + log_tag)
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
