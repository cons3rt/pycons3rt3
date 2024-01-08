#!/usr/bin/env python3
"""
set_asset_visibility.py

This is a sample script for setting asset visibility across a project.  To use:

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

python3 set_asset_visibility.py --project PROJECT_ID --visibility VISIBILITY

Where:

  * PROJECT_ID is the ID of the project to set asset visibility for
  * VISIBILITY desired visibility for all the assets in the project: OWNER, OWNING_PROJECT, TRUSTED_PROJECTS, COMMUNITY

Example:

python3 set_asset_visibility.py --project 1 --visibility COMMUNITY

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
mod_logger = Logify.get_name() + '.set_asset_visibility'


def main():
    log = logging.getLogger(mod_logger + '.main')
    parser = argparse.ArgumentParser(description='cons3rt asset CLI')
    parser.add_argument('--project', help='ID of the project to set asset visibility for', required=True)
    parser.add_argument('--visibility', help='Asset visibility OWNER, OWNING_PROJECT, TRUSTED_PROJECTS, COMMUNITY',
                        required=True)
    args = parser.parse_args()

    # Handle args

    # Get the category
    project_id = args.project
    visibility = args.visibility

    try:
        project_id = int(project_id)
    except ValueError as exc:
        log.error('Project ID not an integer: {i}\n{e}'.format(i=str(project_id), e=str(exc)))
        traceback.print_exc()
        return 1

    # Get an API
    c = Cons3rtApi()

    # Retrieve the software assets
    log.info('Retrieving software assets for project ID: {i}'.format(i=str(project_id)))
    try:
        software_assets = c.retrieve_software_assets(asset_type='software')
    except Cons3rtApiError as exc:
        log.error('Problem retrieving software assets\n{e}'.format(e=str(exc)))
        traceback.print_exc()
        return 2

    log.info('Found {n} software assets for project: {p}'.format(n=str(len(software_assets)), p=str(project_id)))

    # Track problems
    problems = []

    # Set visibility for each asset
    for software_asset in software_assets:
        software_asset_id = software_asset['id']
        log.info('Setting visibility to [{v}] for asset: {a}'.format(v=visibility, a=str(software_asset_id)))
        try:
            c.update_asset_visibility(asset_id=software_asset_id, visibility=visibility)
        except Cons3rtApiError as exc:
            log.error('Problem setting visibility to [{v}] for software asset [{a}]\n{e}'.format(
                v=visibility, a=str(software_asset_id), e=str(exc)))
            problems.append(software_asset_id)

    # Print errors
    if len(problems) > 0:
        msg = 'Problem setting visibility on the following assets:\n'
        for problem in problems:
            msg += str(problem) + '\n'
        log.error(msg)
        return 3
    log.info('All asset visibility set successfully!')
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
