#!/usr/bin/env python

"""Module: asset

This module provides utilities for creating asset zip files.

"""
import logging
import os
import sys
import zipfile
import contextlib
import argparse

from .logify import Logify
from .bash import mkdir_p
from .exceptions import Cons3rtAssetStructureError, AssetZipCreationError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.asset'

# Files to ignore when creating assets
ignore_files = [
    '.DS_Store',
    '.gitignore',
    '._',
]

ignore_file_extensions = [
    'iml'
]

# Directories to ignore when creating assets
ignore_dirs = [
    '.git',
    '.svn',
    '.cons3rt',
    '.idea',
    '.metadata',
    '.project',
    '.settings',
    '.gradle'
]

# Acceptable items at the asset root
acceptable_items = [
    'asset.properties',
    'scripts',
    'media',
    'config',
    'README',
    'HELP',
    'LICENSE',
    'HELP.md',
    'README.md',
    'LICENSE.md'
]

# Acceptable dirs at the root
acceptable_dirs = [
    'scripts',
    'media',
    'config'
]

# Items to warn about
warn_items = [
    'HELP.html',
    'README.html',
    'LICENSE.html'
]

potential_doc_files = [
    'HELP.html',
    'README.html',
    'HELP',
    'README',
    'HELP.md',
    'README.md',
    'ALTERNATE_README'
]

potential_license_files = [
    'LICENSE.html',
    'LICENSE',
    'LICENSE.md',
    'ALTERNATE_LICENSE'
]

# All items to ignore when creating assets
ignore_items = ignore_files + ignore_dirs

# Current shell working directory
try:
    working_dir = os.environ['PWD']
except KeyError:
    working_dir = os.getcwd()


def ignore_by_extension(item_path):
    if not os.path.isfile(item_path):
        return False
    for ignore_file_extension in ignore_file_extensions:
        if item_path.endswith('.{e}'.format(e=ignore_file_extension)):
            return True
    return False


def validate_asset_structure(asset_dir_path):
    """Checks asset structure validity

    :param asset_dir_path: (str) path to the directory containing the asset
    :return: (str) Asset name
    :raises: Cons3rtAssetStructureError
    """
    log = logging.getLogger(mod_logger + '.validate_asset_structure')

    log.info('Validating asset directory: {d}'.format(d=asset_dir_path))

    # Ensure there is an asset.properties file
    asset_props = os.path.join(asset_dir_path, 'asset.properties')

    if not os.path.isfile(asset_props):
        raise Cons3rtAssetStructureError('Asset properties file not found: {f}'.format(f=asset_props))

    # Props to find
    install_script_rel_path = None
    doc_file_rel_path = None
    license_file_rel_path = None
    asset_type = None
    license_file_path = ''
    doc_file_path = ''
    asset_name = None

    log.info('Reading asset properties file: {f}'.format(f=asset_props))
    with open(asset_props, 'r') as f:
        for line in f:
            if line.strip().startswith('installScript='):
                install_script_name = line.strip().split('=')[1]
                install_script_rel_path = os.path.join('scripts', install_script_name)
            elif line.strip().startswith('documentationFile='):
                doc_file_rel_path = line.strip().split('=')[1]
            elif line.strip().startswith('licenseFile='):
                license_file_rel_path = line.strip().split('=')[1]
            elif line.strip().startswith('assetType='):
                asset_type = line.strip().split('=')[1]
                asset_type = asset_type.lower()
            elif line.strip().startswith('name='):
                asset_name = line.strip().split('=')[1]

    # Ensure a name was provided
    if asset_name is None:
        raise Cons3rtAssetStructureError('Required property [name] not found in asset properties file: {f}'.format(
            f=asset_props))
    if asset_name == '':
        raise Cons3rtAssetStructureError('Required property [name] found blank in asset properties file: {f}'.format(
            f=asset_props))

    # Ensure asset_type was provided
    if asset_type is None:
        raise Cons3rtAssetStructureError('Required property [asset_type] not found in asset properties '
                                         'file: {f}'.format(f=asset_props))
    if asset_type == '':
        raise Cons3rtAssetStructureError('Required property [asset_type] found blank in asset properties '
                                         'file: {f}'.format(f=asset_props))

    log.info('Found installScript={f}'.format(f=install_script_rel_path))
    log.info('Found assetType={f}'.format(f=asset_type))

    # Verify the doc file exists if specified
    if doc_file_rel_path:
        log.info('Found documentationFile={f}'.format(f=doc_file_rel_path))
        doc_file_path = os.path.join(asset_dir_path, doc_file_rel_path)
        if not os.path.isfile(doc_file_path):
            raise Cons3rtAssetStructureError('Documentation file not found: {f}'.format(f=doc_file_path))
        else:
            log.info('Verified documentation file: {f}'.format(f=doc_file_path))
    else:
        log.info('The documentationFile property was not specified in asset.properties')

    # Verify the license file exists if specified
    if license_file_rel_path:
        log.info('Found licenseFile={f}'.format(f=license_file_rel_path))
        license_file_path = os.path.join(asset_dir_path, license_file_rel_path)
        if not os.path.isfile(license_file_path):
            raise Cons3rtAssetStructureError('License file not found: {f}'.format(f=license_file_path))
        else:
            log.info('Verified license file: {f}'.format(f=license_file_path))
    else:
        log.info('The licenseFile property was not specified in asset.properties')

    if asset_type == 'software':
        if not install_script_rel_path:
            raise Cons3rtAssetStructureError('Software asset has an asset.properties missing the installScript '
                                             'prop: {f}'.format(f=asset_props))
        else:
            install_script_path = os.path.join(asset_dir_path, install_script_rel_path)
            if not os.path.isfile(install_script_path):
                raise Cons3rtAssetStructureError('Install script file not found: {f}'.format(f=install_script_path))
            else:
                log.info('Verified install script for software asset: {f}'.format(f=install_script_path))

    log.info('Checking items at the root of the asset directory...')
    for item in os.listdir(asset_dir_path):
        log.info('Checking item: {i}'.format(i=item))
        item_path = os.path.join(asset_dir_path, item)
        if item_path == license_file_path:
            continue
        elif item_path == doc_file_path:
            continue
        elif item_path == asset_props:
            continue
        elif item in ignore_items:
            continue
        elif ignore_by_extension(item_path=item_path):
            continue
        elif item in acceptable_dirs and os.path.isdir(item_path):
            continue
        else:
            if item == 'VERSION':
                os.remove(item_path)
                log.warning('Deleted file: {f}'.format(f=item_path))
            elif item == 'doc':
                raise Cons3rtAssetStructureError('Found a doc directory at the asset root, this is not allowed')
            elif item in potential_doc_files:
                if not doc_file_rel_path:
                    raise Cons3rtAssetStructureError('Documentation file found but not specified in '
                                                     'asset.properties: {f}'.format(f=item_path))
                else:
                    raise Cons3rtAssetStructureError('Extra documentation file found: {f}'.format(f=item_path))
            elif item in potential_license_files:
                if not license_file_rel_path:
                    raise Cons3rtAssetStructureError('License file found but not specified in '
                                                     'asset.properties: {f}'.format(f=item_path))
                else:
                    raise Cons3rtAssetStructureError('Extra license file found: {f}'.format(f=item_path))
            else:
                raise Cons3rtAssetStructureError('Found illegal item at the asset root dir: {i}'.format(i=item))
    log.info('Validated asset directory successfully: {d}'.format(d=asset_dir_path))
    return asset_name


def make_asset_zip(asset_dir_path, destination_directory=None):
    """Given an asset directory path, creates an asset zip file in the provided
    destination directory

    :param asset_dir_path: (str) path to the directory containing the asset
    :param destination_directory: (str) path to the destination directory for
            the asset
    :return: (str) Path to the asset zip file
    :raises: AssetZipCreationError
    """
    log = logging.getLogger(mod_logger + '.make_asset_zip')
    log.info('Attempting to create an asset zip from directory: {d}'.format(d=asset_dir_path))

    # Ensure the path is a directory
    if not os.path.isdir(asset_dir_path):
        raise AssetZipCreationError('Provided asset_dir_path is not a directory: {d}'.format(d=asset_dir_path))

    # Determine a destination directory if not provided
    if destination_directory is None:
        destination_directory = os.path.join(os.path.expanduser('~'), 'Downloads')
        mkdir_p(destination_directory)

    # Ensure the destination is a directory
    if not os.path.isdir(destination_directory):
        raise AssetZipCreationError('Provided destination_directory is not a directory: {d}'.format(
            d=destination_directory))

    # Validate the asset structure
    try:
        asset_name = validate_asset_structure(asset_dir_path=asset_dir_path)
    except Cons3rtAssetStructureError as exc:
        raise AssetZipCreationError('Cons3rtAssetStructureError: Problem found in the asset structure: {d}'.format(
            d=asset_dir_path)) from exc

    # Determine the asset zip file name (same as asset name without spaces)
    zip_file_name = 'asset-' + asset_name.replace(' ', '') + '.zip'
    log.info('Using asset zip file name: {n}'.format(n=zip_file_name))

    # Determine the zip file path
    zip_file_path = os.path.join(destination_directory, zip_file_name)

    # Remove existing zip file if it exists
    if os.path.isfile(zip_file_path):
        log.info('Removing existing asset zip file: {f}'.format(f=zip_file_path))
        os.remove(zip_file_path)

    # Attempt to create the zip
    log.info('Attempting to create asset zip file: {f}'.format(f=zip_file_path))
    try:
        with contextlib.closing(zipfile.ZipFile(zip_file_path, 'w', allowZip64=True)) as zip_w:
            for root, dirs, files in os.walk(asset_dir_path):
                for f in files:
                    skip = False
                    file_path = os.path.join(root, f)

                    # Skip files in the ignore directories list
                    for ignore_dir in ignore_dirs:
                        if ignore_dir in file_path:
                            skip = True
                            break

                    # Skip file in the ignore files list
                    for ignore_file in ignore_files:
                        if f.startswith(ignore_file):
                            skip = True
                            break

                    # Skip if the file ends with the specified extension
                    if ignore_by_extension(item_path=file_path):
                        skip = True

                    if skip:
                        log.info('Skipping file: {f}'.format(f=file_path))
                        continue

                    log.info('Adding file to zip: {f}'.format(f=file_path))
                    archive_name = os.path.join(root[len(asset_dir_path):], f)
                    if archive_name.startswith('/'):
                        log.debug('Trimming the leading char: [/]')
                        archive_name = archive_name[1:]
                    log.info('Adding to archive as: {a}'.format(a=archive_name))
                    zip_w.write(file_path, archive_name)
    except Exception as exc:
        raise AssetZipCreationError('Unable to create zip file: {f}'.format(f=zip_file_path)) from exc
    log.info('Successfully created asset zip file: {f}'.format(f=zip_file_path))
    return zip_file_path


def validate(asset_dir):
    """Command line call to validate an asset structure

    :param asset_dir: (full path to the asset dir)
    :return: (int)
    """
    try:
        asset_name = validate_asset_structure(asset_dir_path=asset_dir)
    except Cons3rtAssetStructureError as exc:
        msg = 'Cons3rtAssetStructureError: Problem with asset validation\n{e}'.format(e=str(exc))
        print('ERROR: {m}'.format(m=msg))
        return 1
    print('Validated asset with name: {n}'.format(n=asset_name))
    return 0


def create(asset_dir, dest_dir):
    """Command line call to create an asset zip

    :param asset_dir: (full path to the asset dir)
    :param dest_dir: (full path to the destination directory)
    :return: (int)
    """
    val = validate(asset_dir=asset_dir)
    if val != 0:
        return 1
    try:
        asset_zip = make_asset_zip(asset_dir_path=asset_dir, destination_directory=dest_dir)
    except AssetZipCreationError as exc:
        msg = 'AssetZipCreationError: Problem with asset zip creation\n{e}'.format(e=str(exc))
        print('ERROR: {m}'.format(m=msg))
        return 1
    print('Created asset zip file: {z}'.format(z=asset_zip))
    return 0


def main():
    parser = argparse.ArgumentParser(description='cons3rt asset CLI')
    parser.add_argument('command', help='Command for the Asset CLI')
    parser.add_argument('--asset_dir', help='Path to the asset to import')
    parser.add_argument('--dest_dir', help='Destination directory for the asset zip (default is Downloads)')
    args = parser.parse_args()

    valid_commands = ['create', 'validate']
    valid_commands_str = ','.join(valid_commands)

    # Get the command
    command = args.command.strip().lower()

    # Ensure the command is valid
    if command not in valid_commands:
        print('Invalid command found [{c}]\n'.format(c=command) + valid_commands_str)
        return 1

    # Determine asset_dir, use current directory if not provided
    if args.asset_dir:
        # Get the asset directory and ensure it exists
        asset_dir_provided = args.asset_dir.strip()

        # Handle ~ as the leading char
        if asset_dir_provided.startswith('~'):
            asset_dir = str(asset_dir_provided.replace('~', os.path.expanduser('~')))
        else:
            asset_dir = str(asset_dir_provided)

        if not os.path.isdir(asset_dir):
            asset_dir = os.path.join(working_dir, asset_dir)
        if not os.path.isdir(asset_dir):
            print('ERROR: Asset directory not found: {d}'.format(d=asset_dir_provided))
            return 2
    else:
        asset_dir = working_dir

    # Determine the destination directory
    if args.dest_dir:
        dest_dir_provided = args.dest_dir.strip()

        # Handle ~ as the leading char
        if dest_dir_provided.startswith('~'):
            dest_dir = str(dest_dir_provided.replace('~', os.path.expanduser('~')))
        else:
            dest_dir = str(dest_dir_provided)

        if not os.path.isdir(dest_dir):
            print('ERROR: Destination directory not found: {d}'.format(d=dest_dir))
            return 3
    else:
        dest_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
        if not os.path.isdir(dest_dir):
            dest_dir = os.path.join(os.path.expanduser('~'), 'Download')
        if not os.path.isdir(dest_dir):
            dest_dir = os.path.expanduser('~')

    # Error if the destination directory is not found
    if not os.path.isdir(dest_dir):
        print('ERROR: Unable to find a destination directory for the asset, please specify with "--dest-dir"')
        return 4

    # Process the command
    res = 0
    if command == 'validate':
        res = validate(asset_dir=asset_dir)
    elif command == 'create':
        res = create(asset_dir=asset_dir, dest_dir=dest_dir)
    return res


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
