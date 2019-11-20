#!/usr/bin/env python

"""Module: asset

This module provides utilities for creating asset zip files.

"""
import argparse
import contextlib
import logging
import os
import shutil
import sys
import traceback
import yaml
import zipfile

from .logify import Logify
from .bash import mkdir_p
from .cons3rtapi import Cons3rtApi
from .cons3rtcli import validate_ids
from .exceptions import AssetZipCreationError, Cons3rtApiError, Cons3rtAssetStructureError, Cons3rtCliError

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.asset'

# Files to ignore when creating assets
ignore_files = [
    '.DS_Store',
    '.gitignore',
    '._',
    'asset_data.yml',
    'media.yml'
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

    # Determine the staging directory
    staging_directory = os.path.join(destination_directory, 'asset-{n}'.format(n=asset_name.replace(' ', '')))

    # Remove the existing staging dir if it exists
    if os.path.exists(staging_directory):
        shutil.rmtree(staging_directory)

    # Remove existing zip file if it exists
    if os.path.isfile(zip_file_path):
        log.info('Removing existing asset zip file: {f}'.format(f=zip_file_path))
        os.remove(zip_file_path)

    # Copy asset dir to staging dir
    shutil.copytree(asset_dir_path, staging_directory)

    # Read media.yml to add media files from external sources
    media_yml = os.path.join(staging_directory, 'media.yml')
    media_dir = os.path.join(staging_directory, 'media')
    media_files_copied = []
    if os.path.isfile(media_yml):
        if not os.path.isdir(media_dir):
            os.makedirs(media_dir, exist_ok=True)
        with open(media_yml, 'r') as f:
            media_file_list = yaml.load(f, Loader=yaml.FullLoader)
        for media_file in media_file_list:
            if media_file.startswith('file:///'):
                local_media_file = media_file.lstrip('file:///')
                if local_media_file[0] == '~':
                    local_media_file = os.path.expanduser('~') + local_media_file[1:]
                if not os.path.isfile(local_media_file):
                    raise Cons3rtAssetStructureError(
                        'External media file not found: {f}'.format(f=local_media_file)
                    )
                shutil.copy2(local_media_file, media_dir)
                media_files_copied.append(local_media_file)

    # Attempt to create the zip
    log.info('Attempting to create asset zip file: {f}'.format(f=zip_file_path))
    try:
        with contextlib.closing(zipfile.ZipFile(zip_file_path, 'w', allowZip64=True)) as zip_w:
            for root, dirs, files in os.walk(staging_directory):
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
                    archive_name = os.path.join(root[len(staging_directory):], f)
                    if archive_name.startswith('/'):
                        log.debug('Trimming the leading char: [/]')
                        archive_name = archive_name[1:]
                    log.info('Adding to archive as: {a}'.format(a=archive_name))
                    zip_w.write(file_path, archive_name)
    except Exception as exc:
        raise AssetZipCreationError('Unable to create zip file: {f}'.format(f=zip_file_path)) from exc
    shutil.rmtree(staging_directory)
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
        traceback.print_exc()
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
        traceback.print_exc()
        return 1
    print('Created asset zip file: {z}'.format(z=asset_zip))
    return 0


def stage_media(asset_dir, destination_dir):
    """Stages install media in the destination directory

    :param asset_dir: (str) path to asset directory
    :param destination_dir: (str) path to the destination directory
    :return: True if successful, False otherwise
    """
    log = logging.getLogger(mod_logger + '.stage_media')
    if not os.path.isdir(asset_dir):
        log.error('Asset directory not found: {d}'.format(d=asset_dir))
        return False
    if not os.path.isdir(destination_dir):
        log.info('Creating destination directory: {d}'.format(d=destination_dir))
        os.makedirs(destination_dir, exist_ok=True)
    asset_media_dir = os.path.join(asset_dir, 'media')
    if not os.path.isdir(asset_media_dir):
        log.error('Asset media directory not found: {d}'.format(d=asset_media_dir))
        return False
    marker_file = os.path.join(asset_media_dir, 'MEDIA_ALREADY_COPIED')
    if os.path.isfile(marker_file):
        log.info('Found marker file, no media to copy: {f}'.format(f=marker_file))
        return True
    media_files = os.listdir(asset_media_dir)
    for media_file in media_files:
        log.info('Copying [{s}] to: {d}'.format(s=media_files, d=destination_dir))
        shutil.move(os.path.join(asset_media_dir, media_file), destination_dir)
    log.info('Adding marker file: {f}'.format(f=marker_file))
    with open(marker_file, 'w') as f:
        f.write('Files copied to: {d}'.format(d=destination_dir))
    log.info('Media files have been staged!')
    return True


def import_asset(cons3rt_api, asset_zip_path):
    """Imports an asset zip file using the provided Cons3rtApi object
    and returns data about the imported asset

    :param cons3rt_api: Cons3rtApi object
    :param asset_zip_path: (str) full path to the asset zip file
    :return: (dict) asset import data
    """
    asset_data = {}
    try:
        asset_id = cons3rt_api.import_asset(asset_zip_file=asset_zip_path)
    except Cons3rtApiError as exc:
        print('ERROR: Importing zip {z} into site: {u}\n{e}'.format(
            z=asset_zip_path, u=cons3rt_api.url_base, e=str(exc)))
        traceback.print_exc()
        return asset_data
    asset_data = {
        'asset_id': asset_id,
        'site_url': cons3rt_api.url_base
    }
    print('Imported asset from zip: {z}'.format(z=asset_zip_path))
    return asset_data


def update_asset(cons3rt_api, asset_zip_path, asset_id):
    """Updates an asset ID with the provided Cons3rtApi object and asset zip

    :param cons3rt_api: Cons3rtApi object
    :param asset_zip_path: full path to the asset zip file
    :param asset_id: (int) ID of the asset to update
    :return: True if success, False otherwise
    """
    try:
        cons3rt_api.update_asset_content(asset_id=asset_id, asset_zip_file=asset_zip_path)
    except Cons3rtApiError as exc:
        print('ERROR: Updating asset ID [{a}] zip {z} into site: {u}\n{e}'.format(
            a=str(asset_id), z=asset_zip_path, u=cons3rt_api.url_base, e=str(exc)))
        traceback.print_exc()
        return False
    print('Updated asset ID: {a}'.format(a=str(asset_id)))
    return True


def import_update(asset_dir, dest_dir, import_only=False):
    """Creates an asset zip, and attempts to import/update the asset

    :param asset_dir: (str) path to asset directory
    :param dest_dir: (full path to the destination directory)
    :param import_only: (bool) Whe True, import even if an existing ID is found
    :return:
    """
    try:
        asset_zip = make_asset_zip(asset_dir_path=asset_dir, destination_directory=dest_dir)
    except AssetZipCreationError as exc:
        msg = 'AssetZipCreationError: Problem with asset zip creation\n{e}'.format(e=str(exc))
        print('ERROR: {m}'.format(m=msg))
        traceback.print_exc()
        return 1
    asset_yml = os.path.join(asset_dir, 'asset_data.yml')
    asset_data_list = []
    c = Cons3rtApi()
    if os.path.isfile(asset_yml) and not import_only:
        with open(asset_yml, 'r') as f:
            asset_data_list = yaml.load(f, Loader=yaml.FullLoader)
        asset_id = None
        for asset_data in asset_data_list:
            if asset_data['site_url'] == c.url_base:
                asset_id = asset_data['asset_id']
        if asset_id:
            if not update_asset(cons3rt_api=c, asset_zip_path=asset_zip, asset_id=asset_id):
                return 1
        else:
            asset_data = import_asset(cons3rt_api=c, asset_zip_path=asset_zip)
            if asset_data != {}:
                asset_data_list.append(asset_data)
    else:
        asset_data = import_asset(cons3rt_api=c, asset_zip_path=asset_zip)
        if asset_data != {}:
            asset_data_list.append(asset_data)
    with open(asset_yml, 'w') as f:
        yaml.dump(asset_data_list, f, sort_keys=True)
    os.remove(asset_zip)


def query_assets(args):
    """Queries assets and prints IDs of assets matching the query

    :param args: command line args
    :return: (int) 0 if successful, non-zero otherwise
    """
    Logify.set_log_level(log_level='WARNING')
    if not args.asset_type:
        print('ERROR: Required arg not found: --asset_type')
        return 1
    asset_type = args.asset_type
    valid_asset_types = ['software', 'containers']

    if asset_type not in valid_asset_types:
        print('Invalid --asset_type found, valid asset types: {t}'.format(t=','.join(valid_asset_types)))
        return 2

    assets = []
    expanded = False
    community = False
    asset_subtype = None
    asset_name = None
    latest = False

    if args.expanded:
        expanded = True
    if args.community:
        community = True
    if args.asset_subtype:
        asset_subtype = args.asset_subtype
    if args.name:
        asset_name = args.name
    if args.latest:
        latest = True
    category_ids = None
    if args.category_ids:
        args.ids = args.category_ids
        try:
            category_ids = validate_ids(args)
        except Cons3rtCliError as exc:
            print('ERROR: Invalid --id or --ids arg found\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return 3

    c = Cons3rtApi()
    if asset_type == 'software' and expanded:
        try:
            assets = c.retrieve_expanded_software_assets(
                asset_type=asset_subtype,
                community=community,
                category_ids=category_ids
            )
        except Cons3rtApiError as exc:
            print('ERROR: Problem retrieving assets\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return 4
    elif asset_type == 'software' and not expanded:
        try:
            assets = c.retrieve_software_assets(
                asset_type=asset_subtype,
                community=community,
                category_ids=category_ids
            )
        except Cons3rtApiError as exc:
            print('ERROR: Problem retrieving assets\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return 4
    elif asset_type == 'containers' and expanded:
        try:
            assets = c.retrieve_expanded_container_assets(
                asset_type=asset_subtype,
                community=community,
                category_ids=category_ids
            )
        except Cons3rtApiError as exc:
            print('ERROR: Problem retrieving assets\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return 4
    elif asset_type == 'containers' and not expanded:
        try:
            assets = c.retrieve_container_assets(
                asset_type=asset_subtype,
                community=community,
                category_ids=category_ids
            )
        except Cons3rtApiError as exc:
            print('ERROR: Problem retrieving assets\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return 4

    if len(assets) < 1:
        print('No assets found matching the query!')
        return 0

    if asset_name:
        filtered_assets = []
        for asset in assets:
            if asset_name in asset['name']:
                filtered_assets.append(asset)
    else:
        filtered_assets = assets

    if latest:
        highest_asset_id = 0
        for asset in filtered_assets:
            asset_id = int(asset['id'])
            if asset_id > highest_asset_id:
                highest_asset_id = asset_id
        print(str(highest_asset_id))
    else:
        for asset in filtered_assets:
            print(str(asset['id']))
    return 0


def main():
    parser = argparse.ArgumentParser(description='cons3rt asset CLI')
    parser.add_argument('command', help='Command for the Asset CLI')
    parser.add_argument('--asset_dir', help='Path to the asset to import')
    parser.add_argument('--dest_dir', help='Destination directory for the asset zip (default is Downloads)')
    parser.add_argument('--asset_type', help='Set to: containers, software')
    parser.add_argument('--asset_subtype', help='Asset subtype to query on')
    parser.add_argument('--expanded', help='Include to retrieve expanded info on assets', action='store_true')
    parser.add_argument('--community', help='Include to retrieve community assets', action='store_true')
    parser.add_argument('--category_ids', help='List of category IDs to filter on')
    parser.add_argument('--name', help='Asset name to filter on')
    parser.add_argument('--latest', help='Include to only return the latest with the highest ID', action='store_true')
    args = parser.parse_args()

    valid_commands = ['create', 'import', 'query', 'update', 'validate']
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

    if command == 'create':
        res = create(asset_dir=asset_dir, dest_dir=dest_dir)
    elif command == 'import':
        res = import_update(asset_dir=asset_dir, dest_dir=dest_dir, import_only=True)
    elif command == 'query':
        res = query_assets(args)
    elif command == 'update':
        res = import_update(asset_dir=asset_dir, dest_dir=dest_dir)
    elif command == 'validate':
        res = validate(asset_dir=asset_dir)
    return res


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
