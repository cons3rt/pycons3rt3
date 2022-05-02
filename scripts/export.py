#!/usr/bin/env python3
"""
export_import.py

This is a sample script for exporting and importing assets between CONS3RT sites.  To use:

1. Edit variables in the "EDIT HERE" section below
2. Run: ./export_import.py

"""

import traceback
from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.exceptions import Cons3rtApiError


# ##################### EDIT HERE ##############################

# List of asset IDs to export
software_asset_ids = []
container_asset_ids = []
test_asset_ids = []

# Path to the config.json files for the CONS3RT sites to export and import
# See the sample-configs directory for sample config files
export_config_file = ''

# Directory where the assets will be exported to before importing
export_dir = ''

# ################### END EDIT HERE ############################


# Establish Cons3rtApi clients for exporting and importing
exporter = Cons3rtApi(config_file=export_config_file)

print('STARTING EXPORT/IMPORT')

successful_asset_ids = []
failed_asset_ids = []

# Download the software assets
print('Exporting {n} software assets...'.format(n=str(len(software_asset_ids))))
count = 0
for asset_id in software_asset_ids:
    count += 1
    print('Exporting software asset #[{n}] of [{t}]'.format(n=str(count), t=str(len(software_asset_ids))))

    # Export the asset
    try:
        exported_asset = exporter.download_asset(asset_id=asset_id, background=False, dest_dir=export_dir,
                                                 overwrite=True, suppress_status=True)
    except Cons3rtApiError as exc:
        print('Problem exporting software asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_asset_ids.append(asset_id)
        continue
    else:
        successful_asset_ids.append(asset_id)

# Download the container assets
print('Exporting {n} container assets...'.format(n=str(len(container_asset_ids))))
count = 0
for asset_id in container_asset_ids:
    count += 1
    print('Exporting container asset #[{n}] of [{t}]'.format(n=str(count), t=str(len(container_asset_ids))))

    # Export the asset
    try:
        exported_asset = exporter.download_asset(asset_id=asset_id, background=False, dest_dir=export_dir,
                                                 overwrite=True, suppress_status=True)
    except Cons3rtApiError as exc:
        print('Problem exporting container asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_asset_ids.append(asset_id)
        continue
    else:
        successful_asset_ids.append(asset_id)

# Download the test assets
print('Exporting {n} test assets...'.format(n=str(len(test_asset_ids))))
count = 0
for asset_id in test_asset_ids:
    count += 1
    print('Exporting test asset #[{n}] of [{t}]'.format(n=str(count), t=str(len(test_asset_ids))))

    # Export the asset
    try:
        exported_asset = exporter.download_asset(asset_id=asset_id, background=False, dest_dir=export_dir,
                                                 overwrite=True, suppress_status=True)
    except Cons3rtApiError as exc:
        print('Problem exporting test asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_asset_ids.append(asset_id)
        continue
    else:
        successful_asset_ids.append(asset_id)

print('COMPLETED EXPORT')
print('Successful asset exports: [{s}]'.format(s=','.join(map(str, successful_asset_ids))))
print('Failed asset exports: [{f}]'.format(f=','.join(map(str, failed_asset_ids))))
