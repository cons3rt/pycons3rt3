#!/usr/bin/env python3
"""
export_by_category.py

This is a sample script for exporting assets from CONS3RT by tag (also called category).  To use:

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

python3 export_by_category.py --category CATEGORY_NAME --destination DOWNLOAD_DIR --max MAX_NUM_ASSETS

Where:

  * CATEGORY_NAME is the name of the category to query for export (required)
  * DOWNLOAD_DIR is the full path to the download directory for the exported assets (optional)
  * MAX_NUM_ASSETS the maximum number of assets to download outside of disk space requirements (optional)

Example:

python3 export_by_category.py --category "JDAM-S" --destination "/Users/yennaco/Downloads/JDAMS" --max 10

"""

import argparse
import logging
import os
import shutil
import sys
import traceback
import yaml
from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.exceptions import Cons3rtApiError
from pycons3rt3.logify import Logify

__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.export_by_category'

# File name to track already downloaded assets
downloaded_asset_file_name = 'completed_downloads.txt'

# Default maximum number of assets to download in one round
default_maximum_asset_downloads = 25

# Max size in bytes to put on a DVD
max_dvd_size_bytes = 4294967296


def get_downloaded_assets(download_dir):
    """Returns a list of downloaded asset IDs from the file

    :param download_dir:
    :return: (list) of asset IDs as ints
    :raises: ValueError, OSError
    """
    log = logging.getLogger(mod_logger + '.get_downloaded_assets')

    download_list = os.path.join(download_dir, downloaded_asset_file_name)
    if not os.path.isfile(download_list):
        log.info('No asset download list exists yet')
        return []
    try:
        with open(download_list, 'r') as f:
            downloaded_asset_ids = yaml.load(f, Loader=yaml.FullLoader)
    except (OSError, IOError) as exc:
        msg = 'Invalid yaml file found: {f}\n{e}'.format(f=download_list, e=str(exc))
        log.error(msg)
        traceback.print_exc()
        raise OSError(msg) from exc
    else:
        if not isinstance(downloaded_asset_ids, list):
            log.error('Expected downloaded asset IDs to be a list, found: {t}'.format(
                t=downloaded_asset_ids.__class__.__name__))
            return []
        log.info('Found {n} downloaded asset IDs'.format(n=str(len(downloaded_asset_ids))))
        downloaded_asset_ids_ints = []
        for downloaded_asset_id in downloaded_asset_ids:
            try:
                downloaded_asset_ids_ints.append(int(downloaded_asset_id))
            except ValueError as exc:
                msg = 'Problem reading downloaded asset ID from file: {i}\n{e}'.format(
                    i=str(downloaded_asset_id), e=str(exc))
                log.error(msg)
                traceback.print_exc()
                raise ValueError(msg) from exc
        downloaded_asset_ids_ints.sort()
        return downloaded_asset_ids_ints


def get_download_dir_size(download_dir):
    """Calculates the current size of the download directory

    :param download_dir: (str) path to the download directory
    :return: (int) size of the contents of the download directory in bytes
    """
    log = logging.getLogger(mod_logger + '.get_download_dir_size')
    if not os.path.isdir(download_dir):
        log.warning('Download directory does not exist: {d}'.format(d=download_dir))
        return 0
    total_size = 0
    file_count = 0
    for dirpath, dirnames, filenames in os.walk(download_dir):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)
                file_count += 1
    log.info('Found current size of download directory [{d}] to be {s} bytes, containing {n} files'.format(
        d=download_dir, s=str(total_size), n=str(file_count)))
    return total_size


def set_downloaded_assets(download_dir, asset_id_list):
    """Creates the downloaded asset ID list to prevent re-downloading

    :param download_dir: (str) path to the download directory
    :param asset_id_list: (list) of integer asset IDs
    :return: None
    """
    log = logging.getLogger(mod_logger + '.set_downloaded_assets')
    download_list = os.path.join(download_dir, downloaded_asset_file_name)
    if os.path.isfile(download_list):
        os.remove(download_list)
    unique_asset_ids = list(set(asset_id_list))
    unique_asset_ids.sort()
    with open(download_list, 'w') as f:
        yaml.dump(unique_asset_ids, f, sort_keys=True)
    log.info('Saved list of {n} downloaded assets: {f}'.format(n=str(len(unique_asset_ids)), f=download_list))


def verify_disk_space(file_size, file_path):
    """Ensures the destination disk has enough space

    :return: True is enough disk space is determines, False otherwise
    """
    log = logging.getLogger(mod_logger + '.verify_disk_space')
    free_disk_space = shutil.disk_usage(file_path).free
    log.info('Found {n} bytes free for destination: {d}'.format(n=str(free_disk_space), d=file_path))
    if (file_size * 3) < free_disk_space:
        log.info('There appears to be enough remaining disk space: {s} bytes'.format(s=str(free_disk_space)))
        return True
    else:
        log.warning('There may not be enough disk space: {s} bytes left'.format(s=str(free_disk_space)))
        return False


def verify_dvd_size(file_size):
    """Ensures the DVD disk has enough space

    :return: True is enough disk space is determined, False otherwise
    """
    log = logging.getLogger(mod_logger + '.verify_dvd_size')

    if file_size > max_dvd_size_bytes:
        log.info('Current size is [{f} bytes], enough to fit on a DVD size [{d} bytes]'.format(
            f=str(file_size), d=max_dvd_size_bytes))
        return False
    else:
        remaining_space = max_dvd_size_bytes - file_size
        log.info('There is more space for burning a DVD, remaining bytes: {r}'.format(r=str(remaining_space)))
        return True


def main():
    log = logging.getLogger(mod_logger + '.main')
    parser = argparse.ArgumentParser(description='cons3rt asset CLI')
    parser.add_argument('--category', help='Name of the asset category to export', required=True)
    parser.add_argument('--destination', help='Local directory to download exported assets to', required=False)
    parser.add_argument('--max', help='Maximum number of assets to download', required=False)
    args = parser.parse_args()

    # Handle args

    # Get the category
    category_name = args.category
    category_id = None

    # Determine and validate the download directory
    if args.destination:
        download_dir = args.destination
    else:
        download_dir = os.path.join(os.path.expanduser('~'), 'Downloads')

    # Ensure the download directory exists
    if not os.path.isdir(download_dir):
        log.error('Download directory does not exist: {d}'.format(d=download_dir))
        return 1

    # Get the max
    maximum_asset_downloads = default_maximum_asset_downloads
    if args.max:
        try:
            maximum_asset_downloads = int(args.max)
        except ValueError:
            log.error('The --max arg must be an integer, found: {m}'.format(m=args.max))
            return 2

    # Get an API
    c = Cons3rtApi()

    # Get the categories
    categories = c.retrieve_asset_categories()

    # Match the provided category name
    for category in categories:
        if category['name'] == category_name:
            category_id = category['id']
            log.info('Found category {n} with ID: {i}'.format(n=category_name, i=str(category_id)))

    # Ensure the category ID was found
    if not category_id:
        log.error('Category ID not found for category: [{n}]'.format(n=category_name))
        return 3

    # Retrieve the software assets
    log.info('Retrieving software assets by category ID: {i}'.format(i=str(category_id)))
    export_assets = c.retrieve_expanded_software_assets(software_asset_type='APPLICATION', community=True,
                                                        category_ids=[category_id])
    log.info('Found {n} software assets for category: {c}'.format(n=str(len(export_assets)), c=category_name))

    # Read in the existing download list
    downloaded_asset_ids = get_downloaded_assets(download_dir=download_dir)

    # Build a sorted unique list of asset IDs to export
    export_asset_ids = []
    for export_asset in export_assets:
        try:
            export_asset_id = int(export_asset['id'])
        except ValueError as exc:
            log.error('Problem with asset ID not an integer: {i}\n{e}'.format(i=str(export_asset['id']), e=str(exc)))
            traceback.print_exc()
            return 4
        else:
            if export_asset_id not in downloaded_asset_ids:
                log.info('Adding asset to the export list: {i}'.format(i=str(export_asset_id)))
                export_asset_ids.append(export_asset_id)
            else:
                log.info('Already downloaded asset ID: {i}'.format(i=str(export_asset_id)))
    export_asset_ids = list(set(export_asset_ids))
    export_asset_ids.sort()

    # Set the max if the export asset IDs number is < the provided max
    remaining_downloads = maximum_asset_downloads
    if len(export_asset_ids) < maximum_asset_downloads:
        remaining_downloads = len(export_asset_ids)

    # Total size of downloaded files
    total_downloaded_file_size_bytes = get_download_dir_size(download_dir=download_dir)
    asset_download_count = 0

    # Problem downloads
    problem_downloads = []

    # Download assets not on the downloaded list until the size limits are met
    for export_asset_id in export_asset_ids:
        if asset_download_count >= maximum_asset_downloads:
            log.info('Reached the maximum number of asset downloads [{n} of {m}], exiting...'.format(
                n=str(asset_download_count), m=str(maximum_asset_downloads)))
            break
        if not verify_disk_space(file_size=total_downloaded_file_size_bytes, file_path=download_dir):
            log.warning('Running short of hard disk space to continue')
            break
        if not verify_dvd_size(file_size=total_downloaded_file_size_bytes):
            log.info('There is about enough to fit on a DVD, exiting...')
            break
        asset_download_count += 1
        log.info('Downloading asset ID [{i}] #[{n}] of [{m}]...'.format(
            i=str(export_asset_id), n=str(asset_download_count), m=str(remaining_downloads)))
        try:
            asset_zip = c.download_asset(asset_id=export_asset_id, background=False, dest_dir=download_dir,
                                         suppress_status=True, overwrite=True)
        except Cons3rtApiError as exc:
            msg = 'Problem downloading asset ID [{i}] to download directory [{d}]\n{e}\n{t}'.format(
                i=str(export_asset_id), d=download_dir, e=str(exc), t=traceback.format_exc())
            log.error(msg)
            problem_downloads.append(export_asset_id)
            continue
        else:
            file_size_bytes = os.path.getsize(asset_zip)
            log.info('Downloaded asset ID [{i}] with size [{b} bytes]'.format(
                i=str(export_asset_id), b=str(file_size_bytes)))
            total_downloaded_file_size_bytes += file_size_bytes
            downloaded_asset_ids.append(export_asset_id)
            set_downloaded_assets(download_dir=download_dir, asset_id_list=downloaded_asset_ids)

    # Print errors
    if len(problem_downloads) > 0:
        msg = 'Problem downloading the following asset IDs:\n'
        for problem_download in problem_downloads:
            msg += str(problem_download) + '\n'
        log.error(msg)
        return 1
    log.info('All asset downloads completed successfully!')
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
