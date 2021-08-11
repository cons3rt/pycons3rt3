#!/usr/bin/env python3
"""
export_import.py

This is a sample script for exporting and importing assets between CONS3RT sites.  To use:

1. Edit variables in the "EDIT HERE" section below
2. Run: ./export_import.py

"""

import os
import traceback
from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.exceptions import Cons3rtApiError


# ##################### EDIT HERE ##############################

# List of asset IDs to export
asset_ids = []

# Path to the config.json files for the CONS3RT sites to export and import
# See the sample-configs directory for sample config files
export_config_file = ''
import_config_file = ''

# Directory where the assets will be exported to before importing
export_import_dir = ''

# ################### END EDIT HERE ############################


# Establish Cons3rtApi clients for exporting and importing
exporter = Cons3rtApi(config_file=export_config_file)
importer = Cons3rtApi(config_file=import_config_file)

print('STARTING EXPORT/IMPORT')

successful_asset_ids = []
failed_asset_ids = []
imported_asset_ids = []
fix_visibility = []
count = -1

print('Exporting {n} assets...'.format(n=str(len(asset_ids))))

for asset_id in asset_ids:
    count += 1
    print('Exporting asset #[{n}] of [{t}]'.format(n=str(count), t=str(len(asset_ids))))

    # Export the asset
    try:
        exported_asset = exporter.download_asset(asset_id=asset_id, background=False, dest_dir=export_import_dir,
                                                 overwrite=True, suppress_status=True)
    except Cons3rtApiError as exc:
        print('Problem exporting asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_asset_ids.append(asset_id)
        continue

    print('Importing asset #[{n}] of [{t}]'.format(n=str(count), t=str(len(asset_ids))))

    # Import the asset
    try:
        imported_asset_id = importer.import_asset(asset_zip_file=exported_asset)
    except Cons3rtApiError as exc:
        print('Problem importing asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_asset_ids.append(asset_id)
        continue
    else:
        successful_asset_ids.append(asset_id)
        if isinstance(imported_asset_id, int):
            imported_asset_ids.append(imported_asset_id)
    finally:
        print('Removing exported asset: {z}'.format(z=exported_asset))
        os.remove(exported_asset)

    # Set visibility to COMMUNITY
    if isinstance(imported_asset_id, int):
        try:
            importer.update_asset_visibility(asset_id=imported_asset_id, visibility='COMMUNITY')
        except Cons3rtApiError as exc:
            fix_visibility.append(imported_asset_id)
            print('Problem setting visibility on new asset ID: {i}'.format(i=imported_asset_id))
            traceback.print_exc()
    else:
        print('Visibility not set, new asset ID not known')


print('COMPLETED EXPORT/IMPORT')
print('Successful asset export/imports: [{s}]'.format(s=','.join(map(str, successful_asset_ids))))
print('Imported new asset IDs: [{i}]'.format(i=','.join(map(str, imported_asset_ids))))
print('Failed asset export/imports: [{f}]'.format(f=','.join(map(str, failed_asset_ids))))
print('Failed setting visibility on new assets: [{i}]'.format(i=','.join(map(str, fix_visibility))))
