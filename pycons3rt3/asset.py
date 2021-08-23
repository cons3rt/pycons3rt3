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
import time
import traceback
import yaml
import zipfile

from .logify import Logify
from .bash import mkdir_p
from .cons3rtapi import Cons3rtApi
from .cons3rtcli import validate_ids
from .exceptions import AssetError, AssetZipCreationError, Cons3rtApiError, Cons3rtAssetStructureError, Cons3rtCliError

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


class Asset(object):

    def __init__(self, asset_dir_path, name=None, asset_type=None, asset_subtype=None, asset_zip_path=None,
                 asset_id=None, site_url=None):
        self.asset_dir_path = asset_dir_path
        self.name = name
        self.asset_type = asset_type
        self.asset_subtype = asset_subtype
        self.asset_zip_path = asset_zip_path
        self.asset_id = asset_id
        self.site_url = site_url
        self.site_asset_list = []
        self.asset_yml = os.path.join(self.asset_dir_path, 'asset_data.yml')

    def __str__(self):
        return str(self.name + ' @ ' + self.asset_dir_path)

    def get_asset_id_for_url(self, site_url):
        """Checks

        :param site_url: (str) site API URL
        :return: (int) asset ID or None
        """
        # Generate the site asset list to pull latest info
        self.generate_site_asset_list()

        # Return the first asset ID found matching the site URL
        for site_asset_data in self.site_asset_list:
            if site_asset_data.site_url == site_url:
                return site_asset_data.asset_id

    def get_asset_id_for_url_and_project(self, site_url, project):
        """Checks

        :param site_url: (str) site API URL
        :param project: (str) name of the project
        :return: (int) asset ID or None
        """
        # Generate the site asset list to pull latest info
        self.generate_site_asset_list()

        # Return the first asset ID found matching the site URL and project
        for site_asset_data in self.site_asset_list:
            if site_asset_data.site_url == site_url:
                if site_asset_data.project:
                    if site_asset_data.project == project:
                        return site_asset_data.asset_id

    def generate_site_asset_list(self):
        """Reads in the asset_data.yml file to generate a list of IDs/site/projects where this
        asset is imported

        :return: None
        """
        # Reset the site asset data list
        self.site_asset_list = []

        # Read in existing asset data yaml file
        asset_data_list = []
        if os.path.isfile(self.asset_yml):
            try:
                with open(self.asset_yml, 'r') as f:
                    loaded_yaml = yaml.load(f, Loader=yaml.FullLoader)
                    if loaded_yaml:
                        asset_data_list += loaded_yaml
            except (OSError, IOError) as exc:
                print('Invalid yaml file found: {f}\n{e}'.format(f=self.asset_yml, e=str(exc)))
                traceback.print_exc()
                return

        # Collect site asset data
        for site_asset_data in asset_data_list:
            if 'site_url' not in site_asset_data.keys():
                continue
            if 'asset_id' not in site_asset_data.keys():
                continue
            try:
                int(site_asset_data['asset_id'])
            except ValueError:
                print('WARNING: Invalid asset ID found: {i}, skipping...'.format(i=str(site_asset_data['asset_id'])))
                continue
            msg = 'Found asset ID [{i}] for site [{s}]'.format(
                i=str(site_asset_data['asset_id']), s=site_asset_data['site_url'])
            if 'project' in site_asset_data.keys():
                msg += ' in project [{p}]'.format(p=site_asset_data['project'])
                self.site_asset_list.append(
                    SiteAssetData(
                        asset_id=site_asset_data['asset_id'],
                        site_url=site_asset_data['site_url'],
                        project=site_asset_data['project']
                    )
                )
            else:
                msg += ' in no particular project'
                self.site_asset_list.append(
                    SiteAssetData(
                        asset_id=site_asset_data['asset_id'],
                        site_url=site_asset_data['site_url']
                    )
                )
            print(msg)

    def update_site_asset_id(self, site_url, asset_id, project=None):
        """Update or add the site's asset ID for the provided site URL

        * Add if its not already on the list
        * Include project if provided

        :param site_url: (str) CONS3RT site API URL
        :param asset_id: (int) ID of the asset to add/update
        :param project: (str) name of the project to include in the asset data
        :return: None
        """
        print('Adding asset ID [{i}] for site URL: [{u}]'.format(i=str(asset_id), u=site_url))

        # Update these to the most recent update/import
        self.asset_id = asset_id
        self.site_url = site_url

        # Update site asset data
        self.generate_site_asset_list()
        if project:
            self.__update_site_asset_id_with_project__(site_url=site_url, asset_id=asset_id, project=project)
        else:
            self.__update_site_asset_id_without_project__(site_url=site_url, asset_id=asset_id)

        # Remove and replace the asset data yaml file
        if os.path.isfile(self.asset_yml):
            os.remove(self.asset_yml)
        dump_data = []
        for site_asset_data in self.site_asset_list:
            print('Updating site data: {d}'.format(d=str(site_asset_data)))
            dump_data.append(site_asset_data.yaml_dump)
        with open(self.asset_yml, 'w') as f:
            yaml.dump(dump_data, f, sort_keys=True)

    def __update_site_asset_id_with_project__(self, site_url, asset_id, project):
        """Update or add the provided asset ID for the provided site URL and project

        :param site_url: (str) CONS3RT site API URL
        :param asset_id: (int) ID of the asset to add/update
        :param project: (str) name of the project to include in the asset data
        :return:
        """
        updated = False
        for site_asset_data in self.site_asset_list:
            if site_asset_data.site_url == site_url:
                if site_asset_data.project:
                    if site_asset_data.project == project:
                        print('Found existing asset ID: [{i}]'.format(i=site_asset_data.asset_id))
                        print('Updating asset ID to [{i}] for site URL [{u}] and project [{p}]'.format(
                            i=asset_id, u=site_url, p=project))
                        site_asset_data.update_asset_id(asset_id=asset_id)
                        updated = True
        if not updated:
            print('Adding asset ID to [{i}] for site URL [{u}] and project [{p}]'.format(
                i=asset_id, u=site_url, p=project))
            self.site_asset_list.append(
                SiteAssetData(
                    asset_id=asset_id,
                    site_url=site_url,
                    project=project
                ))

    def __update_site_asset_id_without_project__(self, site_url, asset_id):
        """Update or add the provided asset ID for the provided site URL project-agnostic

        :param site_url: (str) CONS3RT site API URL
        :param asset_id: (int) ID of the asset to add/update
        :return:
        """
        updated = False
        for site_asset_data in self.site_asset_list:
            if site_asset_data.site_url == site_url:
                print('Found existing asset ID: [{i}]'.format(i=site_asset_data.asset_id))
                print('Updating asset ID to [{i}] for site URL [{u}] without specifying a project'.format(
                    i=asset_id, u=site_url))
                site_asset_data.update_asset_id(asset_id=asset_id)
                updated = True
        if not updated:
            print('Adding asset ID to [{i}] for site URL [{u}] without a project'.format(
                i=asset_id, u=site_url))
            self.site_asset_list.append(
                SiteAssetData(
                    asset_id=asset_id,
                    site_url=site_url
                ))


class SiteAssetData(object):

    def __init__(self, asset_id, site_url, project=None):
        self.asset_id = asset_id
        self.site_url = site_url
        self.project = project
        self.yaml_dump = {
            'asset_id': asset_id,
            'site_url': site_url
        }
        if project:
            self.yaml_dump['project']: project

    def __str__(self):
        msg = 'AssetId: ' + str(self.asset_id) + ', URL: ' + self.site_url
        if self.project:
            msg += ', Project: ' + self.project
        return msg

    def to_yaml(self):
        yaml_dump = {
            'asset_id': self.asset_id,
            'site_url': self.site_url
        }
        if self.project:
            yaml_dump['project'] = self.project
        return yaml_dump

    def update_asset_id(self, asset_id):
        self.asset_id = asset_id
        self.yaml_dump['asset_id'] = asset_id


def download_asset(asset_id, download_dir):
    """Downloads the specified asset ID to the specified download directory

    :param asset_id: (int) ID of the asset
    :param download_dir: (str) path of the directory to download to
    :return: (str) path to the downloaded asset or None
    """
    log = logging.getLogger(mod_logger + '.validate_asset_structure')
    c = Cons3rtApi()
    try:
        asset_zip = c.download_asset(asset_id=asset_id, background=False, dest_dir=download_dir, suppress_status=False,
                                     overwrite=True)
    except Cons3rtApiError as exc:
        msg = 'Problem downloading asset ID [{i}] to download directory [{d}]\n{e}\n{t}'.format(
            i=str(asset_id), d=download_dir, e=str(exc), t=traceback.format_exc())
        log.error(msg)
        return
    return asset_zip


def download_cli(args):
    """Handles the asset download subcommand

    :param args: ArgParse
    :return: (int) 0 if successful, non-zero otherwise
    """
    # Determine and validate the asset ID
    if args.id:
        asset_id = args.id
    else:
        print('ERROR: Please provide the asset ID to download as the --id parameter')
        return 1
    if not isinstance(asset_id, int):
        try:
            asset_id = int(asset_id)
        except ValueError:
            print('ERROR: Please provide the --id args as an integer asset ID')
            return 1

    # Determine and validate the download directory
    if args.dest_dir:
        download_dir = args.dest_dir
    else:
        download_dir = os.path.join(os.path.expanduser('~'), 'Downloads')
    if not os.path.isdir(download_dir):
        print('ERROR: Download directory not found: {d}'.format(d=download_dir))
        return 1
    downloaded_asset = download_asset(asset_id=asset_id, download_dir=download_dir)
    if not downloaded_asset:
        print('ERROR: Problem downloading asset ID [{i}] to directory: {d}'.format(i=str(asset_id), d=download_dir))
        return 2
    print('Asset ID [{i}] downloaded successfully to: {z}'.format(i=str(asset_id), z=downloaded_asset))
    return 0


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
    :return: (Asset) containing asset name
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
    asset_subtype = None
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
                if asset_type == 'container':
                    asset_type = 'containers'
            elif 'AssetType=' in line.strip():
                asset_subtype = line.strip().split('=')[1]
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
    asset_info = Asset(asset_dir_path=asset_dir_path, name=asset_name, asset_subtype=asset_subtype,
                       asset_type=asset_type)
    return asset_info


def make_asset_zip(asset_dir_path, destination_directory=None):
    """Given an asset directory path, creates an asset zip file in the provided
    destination directory

    :param asset_dir_path: (str) path to the directory containing the asset
    :param destination_directory: (str) path to the destination directory for
            the asset
    :return: (Asset) with the path to the asset zip file
    :raises: AssetZipCreationError
    """
    log = logging.getLogger(mod_logger + '.make_asset_zip')
    log.info('Attempting to create an asset zip from directory: {d}'.format(d=asset_dir_path))
    print('Creating asset zip file from asset directory: {d}'.format(d=asset_dir_path))

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
        asset_info = validate_asset_structure(asset_dir_path=asset_dir_path)
    except Cons3rtAssetStructureError as exc:
        raise AssetZipCreationError('Cons3rtAssetStructureError: Problem found in the asset structure: {d}'.format(
            d=asset_dir_path)) from exc

    # Determine the asset zip file name (same as asset name without spaces)
    asset_name = asset_info.name
    zip_file_name = 'asset-' + asset_name.replace(' ', '') + '.zip'
    log.info('Using asset zip file name: {n}'.format(n=zip_file_name))

    # Determine the zip file path
    asset_info.asset_zip_path = os.path.join(destination_directory, zip_file_name)

    # Determine the staging directory
    staging_directory = os.path.join(destination_directory, 'asset-{n}'.format(n=asset_name.replace(' ', '')))

    # Remove the existing staging dir if it exists
    if os.path.exists(staging_directory):
        shutil.rmtree(staging_directory)

    # Remove existing zip file if it exists
    if os.path.isfile(asset_info.asset_zip_path):
        log.info('Removing existing asset zip file: {f}'.format(f=asset_info.asset_zip_path))
        os.remove(asset_info.asset_zip_path)

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
                print('Staged media file: {f}'.format(f=local_media_file))
                media_files_copied.append(local_media_file)

    # Attempt to create the zip
    log.info('Attempting to create asset zip file: {f}'.format(f=asset_info.asset_zip_path))
    try:
        with contextlib.closing(zipfile.ZipFile(asset_info.asset_zip_path, 'w', allowZip64=True)) as zip_w:
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
        raise AssetZipCreationError('Unable to create zip file: {f}'.format(f=asset_info.asset_zip_path)) from exc
    shutil.rmtree(staging_directory)
    log.info('Successfully created asset zip file: {f}'.format(f=asset_info.asset_zip_path))
    print('Created asset zip file: {f}'.format(f=asset_info.asset_zip_path))
    return asset_info


def validate(asset_dir):
    """Command line call to validate an asset structure

    :param asset_dir: (full path to the asset dir)
    :return: (int)
    """
    try:
        asset_info = validate_asset_structure(asset_dir_path=asset_dir)
    except Cons3rtAssetStructureError as exc:
        msg = 'Cons3rtAssetStructureError: Problem with asset validation\n{e}'.format(e=str(exc))
        print('ERROR: {m}'.format(m=msg))
        traceback.print_exc()
        return 1
    print('Validated asset with name: {n}'.format(n=asset_info.name))
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
        asset_info = make_asset_zip(asset_dir_path=asset_dir, destination_directory=dest_dir)
    except AssetZipCreationError as exc:
        msg = 'AssetZipCreationError: Problem with asset zip creation\n{e}'.format(e=str(exc))
        print('ERROR: {m}'.format(m=msg))
        traceback.print_exc()
        return 1
    print('Created asset zip file: {z}'.format(z=asset_info.asset_zip_path))
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


def import_asset(cons3rt_api, asset_info):
    """Imports an asset zip file using the provided Cons3rtApi object
    and returns data about the imported asset

    :param cons3rt_api: Cons3rtApi object
    :param asset_info: (Asset)
    :return: (tuple) Asset, imported_asset_id (int), Success (bool)
    """
    try:
        returned_asset_id = cons3rt_api.import_asset(asset_zip_file=asset_info.asset_zip_path)
    except Cons3rtApiError as exc:
        print('ERROR: Importing zip {z} into site: {u}\n{e}'.format(
            z=asset_info.asset_zip_path, u=cons3rt_api.rest_user.rest_api_url, e=str(exc)))
        traceback.print_exc()
        return asset_info, None, False

    print('Imported asset from zip: {z}'.format(z=asset_info.asset_zip_path))
    try:
        int(returned_asset_id)
    except ValueError:
        print('Attempting to determine imported asset ID in 10 seconds...')
        time.sleep(10)
        print('Querying for latest asset with type [{t}], subtype [{s}], and name [{n}]'.format(
            t=asset_info.asset_type, s=asset_info.asset_subtype, n=asset_info.name))
        try:
            filtered_assets = query_assets(
                asset_type=asset_info.asset_type,
                asset_subtype=asset_info.asset_subtype,
                expanded=False,
                community=False,
                latest=True,
                asset_name=asset_info.name,
                category_ids=None,
                max_results=200
            )
        except AssetError as exc:
            print('WARNING: Problem querying for the imported asset ID, will have to be manually added to '
                  'asset.yml\n{e}'.format(e=str(exc)))
            traceback.print_exc()
            return asset_info, None, True
        else:
            if len(filtered_assets) != 1:
                print('WARNING: Unable to determine the imported asset ID, will have to be manually added to asset.yml')
                return asset_info, None, True
            else:
                discovered_asset_id = int(filtered_assets[0]['id'])
                print('Discovered the imported asset ID: {n}'.format(n=str(discovered_asset_id)))

                # Update site asset data with the new asset ID
                asset_info.update_site_asset_id(
                    asset_id=discovered_asset_id,
                    site_url=cons3rt_api.rest_user.rest_api_url,
                    project=cons3rt_api.project
                )
                return asset_info, discovered_asset_id, True
    else:
        # Update site asset data with the new asset ID
        print('Imported new asset ID: {n}'.format(n=str(returned_asset_id)))
        asset_info.update_site_asset_id(
            asset_id=returned_asset_id,
            site_url=cons3rt_api.rest_user.rest_api_url,
            project=cons3rt_api.project
        )
        return asset_info, returned_asset_id, True


def update_asset(cons3rt_api, asset_info, asset_id):
    """Updates an asset ID with the provided Cons3rtApi object and asset zip

    :param cons3rt_api: Cons3rtApi object
    :param asset_info: (Asset)
    :param asset_id: (int) asset ID to update
    :return: (tuple) Asset, updated_asset_id (int), Success (bool)
    """
    print('Attempting to update asset ID: {i}'.format(i=str(asset_id)))
    asset_info.update_site_asset_id(
        asset_id=asset_id,
        site_url=cons3rt_api.rest_user.rest_api_url,
        project=cons3rt_api.project
    )
    try:
        cons3rt_api.update_asset_content(asset_id=asset_id, asset_zip_file=asset_info.asset_zip_path)
    except Cons3rtApiError as exc:
        print('ERROR: Updating asset ID [{a}] zip {z} into site: {u}\n{e}'.format(
            a=str(asset_id), z=asset_info.asset_zip_path, u=cons3rt_api.rest_user.rest_api_url, e=str(exc)))
        traceback.print_exc()
        return asset_info, asset_id, False
    print('Updated asset ID: {a}'.format(a=str(asset_id)))
    return asset_info, asset_id, True


def import_update(asset_dir, dest_dir, visibility=None, import_only=False, update_only=False, update_asset_id=None,
                  log_level=None, config_file=None, keep_asset_zip=False):
    """Creates an asset zip, and attempts to import/update the asset

    :param asset_dir: (str) path to asset directory
    :param dest_dir: (str) full path to the destination directory of the asset zip
    :param visibility: (str) desired visibility default: OWNER
    :param import_only: (bool) When True, import even if an existing ID is found
    :param update_only: (bool) When True, only process an asset updates, no failover to import if ID is not found
    :param update_asset_id: (int) When provided, update the provided asset ID
    :param log_level: (str) set the desired log level
    :param config_file: (str) path to a config file to use for the asset import/update
    :param keep_asset_zip: (bool) Set True to not remove the asset zip after import/update
    :return: (tuple) Asset, (int) 0 = Success, non-zero otherwise, (str) Error message
    :raises: AssetError
    """
    if log_level:
        Logify.set_log_level(log_level=log_level)

    # Make the asset zip file
    try:
        asset_info = make_asset_zip(asset_dir_path=asset_dir, destination_directory=dest_dir)
    except AssetZipCreationError as exc:
        msg = 'AssetZipCreationError: Problem with asset zip creation\n{e}'.format(e=str(exc))
        print('ERROR: {m}'.format(m=msg))
        traceback.print_exc()
        return None, 1, msg

    # Get the asset CONS3RT site info
    asset_info.generate_site_asset_list()

    # Create a Cons3rtApi
    c5t = Cons3rtApi(config_file=config_file)

    # Get existing asset ID
    if update_asset_id:
        existing_asset_id = update_asset_id
    else:
        existing_asset_id = asset_info.get_asset_id_for_url(site_url=c5t.rest_user.rest_api_url)

    # If import_only is set, import and update the asset data for the yaml
    if import_only:
        print('Attempting to import asset zip: {f}'.format(f=asset_info.asset_zip_path))
        asset_info, asset_id, result = import_asset(cons3rt_api=c5t, asset_info=asset_info)
        if result:
            print('Imported asset successfully')
        else:
            msg = 'ERROR: Failed to import asset'
            print(msg)
            return asset_info, 1, msg

    else:
        # If there is an existing asset ID, update it otherwise import it
        if existing_asset_id:
            print('Attempting to update asset ID [{i}] with asset zip: {f}'.format(
                i=str(existing_asset_id), f=asset_info.asset_zip_path))
            asset_info, asset_id, result = update_asset(cons3rt_api=c5t, asset_info=asset_info,
                                                        asset_id=existing_asset_id)
            if result:
                print('Updated asset ID successfully: {i}'.format(i=str(asset_id)))
            else:
                msg = 'ERROR: Problem updating asset ID: {i}'.format(i=str(asset_id))
                print(msg)
                return asset_info, 1, msg

        # If there is not an existing asset ID, import and append the resulting ID
        else:
            if not update_only:
                print('No existing asset ID found, attempting to import asset zip: {f}'.format(f=asset_info.asset_zip_path))
                asset_info, asset_id, result = import_asset(cons3rt_api=c5t, asset_info=asset_info)
                if result:
                    print('Imported asset successfully')
                else:
                    msg = 'ERROR: Failed to import asset'
                    print(msg)
                    return asset_info, 1, msg
            else:
                msg = 'updateonly command was specified, and no existing asset ID was found to update'
                print(msg)
                return asset_info, 1, msg

    # Remove the asset zip file
    if not keep_asset_zip:
        print('Removing asset zip file: {f}'.format(f=asset_info.asset_zip_path))
        os.remove(asset_info.asset_zip_path)
    else:
        print('FYI... keeping asset zip file: {f}'.format(f=asset_info.asset_zip_path))

    # Exit if no asset data with an ID exists
    if not asset_id:
        print('WARNING: No asset ID available, cannot set visibility')
        return asset_info, 0

    # Attempt to set visibility
    if visibility:
        print('Attempting to set visibility on asset ID {n} to: {v}'.format(n=str(asset_id), v=visibility))
        try:
            c5t.update_asset_visibility(
                asset_id=asset_id,
                visibility=visibility,
                trusted_projects=None
            )
        except Cons3rtApiError as exc:
            msg = 'ERROR: Problem setting visibility for asset ID {n} to: {v}\n{e}'.format(
                n=str(asset_id), v=visibility, e=str(exc))
            print(msg)
            traceback.print_exc()
            return asset_info, 1, msg
        print('Set visibility for asset ID {i} to: {v}'.format(i=str(asset_id), v=visibility))
    print('Completed import/update for asset ID: {i}'.format(i=str(asset_id)))
    return asset_info, 0, None


def print_assets(asset_list):
    msg = 'ID\tName\t\t\t\t\t\tVisibility\t\tState\t\t\tType\n'
    for asset in asset_list:

        if 'id' in asset:
            msg += str(asset['id'])
        else:
            msg += '      '
        msg += '\t'
        if 'name' in asset:
            msg += asset['name']
        else:
            msg += '          '
        msg += '\t\t\t\t\t\t'
        if 'visibility' in asset:
            msg += asset['visibility']
        else:
            msg += '              '
        msg += '\t\t'
        if 'state' in asset:
            msg += asset['state']
        else:
            msg += '                 '
        msg += '\t\t\t'
        if 'type' in asset:
            msg += asset['type']
        else:
            msg += '         '
        msg += '\n'
    print(msg)


def query_assets_args(args, id_only=False):
    """Queries assets and prints IDs of assets matching the query

    :param args: command line args
    :param id_only: print the ID(s) only
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

    try:
        filtered_assets = query_assets(
            asset_type=asset_type,
            asset_subtype=asset_subtype,
            expanded=expanded,
            community=community,
            latest=latest,
            asset_name=asset_name,
            category_ids=category_ids
        )
    except AssetError as exc:
        print('ERROR: Problem querying for assets\n{e}'.format(e=str(exc)))
        traceback.print_exc()
        return 4

    # Print either the asset IDs or the asset data for each asset
    if id_only:
        asset_id_str = ''
        for asset in filtered_assets:
            asset_id_str += str(asset['id']) + '\n'
        print(asset_id_str)
    else:
        print_assets(filtered_assets)
    return 0


def query_assets(asset_type, asset_subtype=None, expanded=False, community=False, latest=False, asset_name=None,
                 category_ids=None, max_results=None):
    """Queries assets and prints IDs of assets matching the query

    :param asset_type: (str) asset type
    :param asset_subtype: (str) asset subtype
    :param expanded: (bool) set true to query on expanded list of assets
    :param community: (bool) set true to query on community assets
    :param latest: (bool) set true to return just the latest asset (highest asset ID number)
    :param asset_name: (str) name to filter results on
    :param category_ids: (list) list of category IDs to filter on
    :param max_results: (int) maximum number of assets to query for
    :return: (list) of assets
    :raises: AssetError
    """
    log = logging.getLogger(mod_logger + '.query_assets')
    valid_asset_types = ['software', 'containers']
    if asset_type not in valid_asset_types:
        raise AssetError('Invalid asset_type found, valid asset types: {t}'.format(t=','.join(valid_asset_types)))
    assets = []
    c = Cons3rtApi()
    if asset_type == 'software':
        try:
            assets = c.retrieve_software_assets(
                asset_type=asset_subtype,
                community=community,
                expanded=expanded,
                category_ids=category_ids,
                max_results=max_results
            )
        except Cons3rtApiError as exc:
            raise AssetError('Problem retrieving software assets') from exc
    elif asset_type == 'containers':
        try:
            assets = c.retrieve_container_assets(
                asset_type=asset_subtype,
                community=community,
                expanded=expanded,
                category_ids=category_ids,
                max_results=max_results
            )
        except Cons3rtApiError as exc:
            raise AssetError('Problem retrieving container assets') from exc

    # Return empty list if no assets found
    if len(assets) < 1:
        log.info('No assets found')
        return []

    # Filter the list by the provided asset name
    if asset_name:
        filtered_assets = []
        for asset in assets:
            if asset_name in asset['name']:
                filtered_assets.append(asset)
    else:
        filtered_assets = assets
    log.info('Found {n} assets matching the query'.format(n=str(len(filtered_assets))))
    print('Found {n} assets matching the query'.format(n=str(len(filtered_assets))))

    # If the latest flag was provided, return a list containing just the latest asset
    # Otherwise return the full list of filtered assets
    if latest:
        log.info('Returning the latest asset...')
        highest_asset_id = 0
        latest_asset = None
        for asset in filtered_assets:
            asset_id = int(asset['id'])
            if asset_id > highest_asset_id:
                highest_asset_id = asset_id
                latest_asset = asset
        if not latest_asset:
            raise AssetError('Latest asset not found in asset data: {d}'.format(d=str(filtered_assets)))
        return [latest_asset]
    else:
        return filtered_assets


def main():
    parser = argparse.ArgumentParser(description='cons3rt asset CLI')
    parser.add_argument('command', help='Command for the Asset CLI')
    parser.add_argument('--asset_dir', help='Path to the asset to import')
    parser.add_argument('--asset_subtype', help='Asset subtype to query on')
    parser.add_argument('--asset_type', help='Set to: containers, software')
    parser.add_argument('--category_ids', help='List of category IDs to filter on')
    parser.add_argument('--community', help='Include to retrieve community assets', action='store_true')
    parser.add_argument('--dest_dir', help='Destination directory for the asset zip (default is Downloads)')
    parser.add_argument('--expanded', help='Include to retrieve expanded info on assets', action='store_true')
    parser.add_argument('--id', help='Asset ID to download or update')
    parser.add_argument('--keep', help='Include to keep the asset zip file after import/update', action='store_true')
    parser.add_argument('--latest', help='Include to only return the latest with the highest ID', action='store_true')
    parser.add_argument('--name', help='Asset name to filter on')
    parser.add_argument('--visibility', help='Set to the desired visibility')
    args = parser.parse_args()

    valid_commands = ['create', 'download', 'import', 'query', 'queryids', 'update', 'updateonly', 'validate']
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

    # Set visibility
    visibility = None
    if args.visibility:
        visibility = args.visibility

    # Set the keep flag
    keep = False
    if args.keep:
        keep = True

    # Set the ID
    asset_id = None
    if args.id:
        try:
            asset_id = int(args.id)
        except ValueError:
            print('ERROR: Invalid ID: {i}'.format(i=str(args.id)))
            return 5

    # Process the command
    res = 0

    if command == 'create':
        res = create(asset_dir=asset_dir, dest_dir=dest_dir)
    elif command == 'download':
        res = download_cli(args)
    elif command == 'import':
        asset, res, err = import_update(asset_dir=asset_dir, dest_dir=dest_dir, import_only=True,
                                        visibility=visibility, log_level='WARNING')
    elif command == 'query':
        res = query_assets_args(args)
    elif command == 'queryids':
        res = query_assets_args(args, id_only=True)
    elif command == 'update':
        asset, res, err = import_update(asset_dir=asset_dir, dest_dir=dest_dir, visibility=visibility,
                                        log_level='WARNING', keep_asset_zip=keep, update_asset_id=asset_id)
    elif command == 'updateonly':
        asset, res, err = import_update(asset_dir=asset_dir, dest_dir=dest_dir, visibility=visibility,
                                        log_level='WARNING', keep_asset_zip=keep, update_only=True,
                                        update_asset_id=asset_id)
    elif command == 'validate':
        validate(asset_dir=asset_dir)
    return res


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
