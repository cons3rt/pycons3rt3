#!/usr/bin/env python3
"""
import_asset_zips.py

This is a sample script for importing assets from a directory.  To use:

Prerequisites:

1. Install python3
2. Install pycons3rt3:

python3 -m pip install pycons3rt3

or

git clone https://github.com/cons3rt/pycons3rt3
cd pycons3rt3
python3 -m pip install -r cfg/requirements.txt
python3 setup.py install

3. Run:

python3 import_asset_zips.py --importdir IMPORT_DIR

Where:

  * IMPORT_DIR is the full path to the directory of asset zip files to import

Example:

python3 import_asset_zips.py --importdir "/path/to/imports"

"""

import argparse
import logging
import os
import sys
import traceback
import yaml
from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.exceptions import Cons3rtApiError
from pycons3rt3.logify import Logify

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.import_asset_zips'

# File name to track already downloaded assets
imported_asset_file_name = 'completed_imports.txt'


def get_imported_assets(import_dir):
    """Returns a list of imported asset IDs from the file

    :param import_dir:
    :return: (list) of asset IDs as ints
    :raises: ValueError, OSError
    """
    log = logging.getLogger(mod_logger + '.get_imported_assets')

    import_list = os.path.join(import_dir, imported_asset_file_name)
    if not os.path.isfile(import_list):
        log.info('No asset import list exists yet')
        return []
    try:
        with open(import_list, 'r') as f:
            imported_asset_zips = yaml.load(f, Loader=yaml.FullLoader)
    except (OSError, IOError) as exc:
        msg = 'Invalid yaml file found: {f}\n{e}'.format(f=import_list, e=str(exc))
        log.error(msg)
        traceback.print_exc()
        raise OSError(msg) from exc
    else:
        if not isinstance(imported_asset_zips, list):
            log.error('Expected imported asset zips to be a list, found: {t}'.format(
                t=imported_asset_zips.__class__.__name__))
            return []
        log.info('Found {n} imported asset zips'.format(n=str(len(imported_asset_zips))))
        return imported_asset_zips


def set_imported_assets(import_dir, asset_zip_list):
    """Creates the downloaded asset ID list to prevent re-downloading

    :param import_dir: (str) path to the download directory
    :param asset_zip_list: (list) of asset zip files of format asset-12345.zip
    :return: None
    """
    log = logging.getLogger(mod_logger + '.set_imported_assets')
    import_list = os.path.join(import_dir, imported_asset_file_name)
    if os.path.isfile(import_list):
        os.remove(import_list)
    unique_asset_zip_files = list(set(asset_zip_list))
    unique_asset_zip_files.sort()
    with open(import_list, 'w') as f:
        yaml.dump(unique_asset_zip_files, f, sort_keys=True)
    log.info('Saved list of {n} imported assets: {f}'.format(n=str(len(unique_asset_zip_files)), f=import_list))


def main():
    log = logging.getLogger(mod_logger + '.main')
    parser = argparse.ArgumentParser(description='cons3rt asset CLI')
    parser.add_argument('--importdir', help='Path to the directory of zip files to import', required=True)
    args = parser.parse_args()

    # Handle args

    # Determine and validate the download directory
    if args.importdir:
        import_dir = args.importdir
    else:
        log.error('The --importdir arg is required')
        return 1

    # Ensure the download directory exists
    if not os.path.isdir(import_dir):
        log.error('Import directory does not exist: {d}'.format(d=import_dir))
        return 1

    # Get an API
    c = Cons3rtApi()

    # Read in the existing download list
    imported_asset_zips = get_imported_assets(import_dir=import_dir)

    # Store the list of asset zip files ot import in the directory
    asset_zip_files = []

    # Get a list of zip files in the import directory
    directory_items = os.listdir(import_dir)

    for directory_item in directory_items:
        if directory_item.startswith('asset-') and directory_item.endswith('.zip'):
            if directory_item not in imported_asset_zips:
                log.info('Found asset to import: {f}'.format(f=directory_item))
                asset_zip_files.append(directory_item)
            else:
                log.info('Found asset already imported in file [{f}]: {a}'.format(
                    f=imported_asset_file_name, a=directory_item))

    # Make sure the list is unique and sorted
    asset_zip_files = list(set(asset_zip_files))
    asset_zip_files.sort()

    # Count the asset imports
    asset_import_count = 0

    # Track the problem imports
    import_problem_list = []

    # Download assets not on the downloaded list until the size limits are met
    for asset_zip_file in asset_zip_files:
        asset_import_count += 1
        log.info('Importing asset zip file [{i}]: #[{n}] of [{m}]...'.format(
            i=str(asset_zip_file), n=str(asset_import_count), m=str(len(asset_zip_files))))

        # Get the full asset zip path and ensure it exists
        asset_zip_path = os.path.join(import_dir, asset_zip_file)
        if not os.path.isfile(asset_zip_path):
            msg = 'Asset zip file not found: {f}'.format(f=asset_zip_path)
            log.error(msg)
            import_problem_list.append(asset_zip_file)
            continue

        # Import the asset
        try:
            asset_id = c.import_asset(asset_zip_path)
        except Cons3rtApiError as exc:
            msg = 'Problem importing asset zip from path [{i}]\n{e}\n{t}'.format(
                i=str(asset_zip_path), e=str(exc), t=traceback.format_exc())
            log.error(msg)
            import_problem_list.append(asset_zip_file)
            continue
        log.info('Imported asset zip file [{f}] with ID: {i}'.format(f=asset_zip_file, i=str(asset_id)))
        imported_asset_zips.append(asset_zip_file)
        set_imported_assets(import_dir=import_dir, asset_zip_list=imported_asset_zips)

    if len(import_problem_list) > 0:
        # Print out the problem list
        msg = 'The following asset zip files had problems importing:\n'
        for import_problem in import_problem_list:
            msg += import_problem + '\n'
        log.warning(msg)
        return 1
    else:
        log.info('No import problems found, all asset zip files imported successfully!')
        return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
