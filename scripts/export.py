#!/usr/bin/env python3
"""
export_import.py

This is a sample script for exporting and importing assets between CONS3RT sites.  To use:

1. Edit variables in the "EDIT HERE" section below
2. Run: ./export.py

"""
import logging
import os
import traceback

from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.exceptions import Cons3rtApiError


# ##################### EDIT HERE ##############################

# List of asset IDs to export
software_asset_ids = [1157,1158,1159,1160,1161,1162,1163,1164,1165,1166,1168,1169,1171,1173,1177,1180,1231,1232,1233,
                      1234,1235,1236,1238,1239,1241,1242,1243,1245,1246,1247,1356,1367,1373,1384,1392,1393,1399,1408,
                      1409,1412,1710,1892,1894,1902,2448,2810,2869,2884,3709,4267,4856,5999,6016,6399,6973,7487,7598,
                      7599,7600,7672,7673,7674,7742,7750,7760,7844,7945,8006,8007,8010,8011,8013,8014,8015,8016,8021,
                      8157,8163,8294,8806,8930,8931,9074,10196,10197,10198,10203,10265,10266,10348,10680,10681,10682,
                      12636,17350,17356,17360,17361,18427,18477,18478,18479,19739,19759,19792,19796,19797,19801,19808,
                      19812,19844,19866,19883,20407,21924,22144]
container_asset_ids = []
test_asset_ids = []

# Path to the config.json files for the CONS3RT sites to export and import
# See the sample-configs directory for sample config files
export_config_file = ''

# Directory where the assets will be exported to before importing
export_dir = '/Users/yennaco/Downloads/export_import'

# Overwrite assets already downloaded
overwrite = False

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

    # If overwrite is false, skip already downloaded assets
    download_file = os.path.join(export_dir, 'asset-{i}.zip'.format(i=str(asset_id)))
    if os.path.isfile(download_file) and not overwrite:
        successful_asset_ids.append(asset_id)
        logging.info('Asset already downloaded, and not overwriting: [{f}]'.format(f=download_file))
        continue

    # Export the asset
    try:
        exported_asset = exporter.download_asset(asset_id=asset_id, background=False, dest_dir=export_dir,
                                                 overwrite=overwrite, suppress_status=True)
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

    # If overwrite is false, skip already downloaded assets
    download_file = os.path.join(export_dir, 'asset-{i}.zip'.format(i=str(asset_id)))
    if os.path.isfile(download_file) and not overwrite:
        successful_asset_ids.append(asset_id)
        logging.info('Asset already downloaded, and not overwriting: [{f}]'.format(f=download_file))
        continue

    # Export the asset
    try:
        exported_asset = exporter.download_asset(asset_id=asset_id, background=False, dest_dir=export_dir,
                                                 overwrite=overwrite, suppress_status=True)
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

    # If overwrite is false, skip already downloaded assets
    download_file = os.path.join(export_dir, 'asset-{i}.zip'.format(i=str(asset_id)))
    if os.path.isfile(download_file) and not overwrite:
        successful_asset_ids.append(asset_id)
        logging.info('Asset already downloaded, and not overwriting: [{f}]'.format(f=download_file))
        continue

    # Export the asset
    try:
        exported_asset = exporter.download_asset(asset_id=asset_id, background=False, dest_dir=export_dir,
                                                 overwrite=overwrite, suppress_status=True)
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
