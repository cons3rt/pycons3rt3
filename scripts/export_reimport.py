#!/usr/bin/env python3
"""
export_reimport.py

This is a sample script for exporting and re-importing assets between CONS3RT sites.  To use:

1. Edit variables in the "EDIT HERE" section below
2. Run: ./export_reimport.py

"""

import os
import sys
import traceback
from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.exceptions import Cons3rtApiError


# ##################### EDIT HERE ##############################

# Asset type: software or container
asset_type = 'container'

# List of asset IDs to export
asset_ids = []
asset_ids_dev = []

# List of asset IDs to re-import.
# IMPORTANT -- The asset order must match the asset_ids list, and the lengths must be the same
re_import_asset_ids = []
re_import_asset_ids_dev = []

# Path to the config.json files for the CONS3RT sites to export and import
# See the sample-configs directory for sample config files
export_config_file = ''
import_config_file = ''

# Directory where the assets will be exported to before importing
export_import_dir = ''

# ################### END EDIT HERE ############################

# Ensure the lists of IDs are the same length
print('Number of asset IDs to export: {n}'.format(n=str(len(asset_ids))))
print('Number of asset IDs to re-import: {n}'.format(n=str(len(re_import_asset_ids))))
if len(asset_ids) != len(re_import_asset_ids):
    print('The lengths of the asset_ids and re_import_asset_ids lists must be equal')
    sys.exit(1)

# Establish Cons3rtApi clients for exporting and importing
exporter = Cons3rtApi(config_file=export_config_file)
importer = Cons3rtApi(config_file=import_config_file)

print('STARTING EXPORT/IMPORT')

successful_asset_ids = []
successful_re_imported_asset_ids = []
failed_export_asset_ids = []
failed_import_asset_ids = []
fix_visibility = []
fix_state = []
count = 0

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
        failed_export_asset_ids.append(asset_id)
        continue

    # Retrieve the exported asset data
    if asset_type == 'software':
        try:
            exported_asset_data = exporter.retrieve_software_asset(asset_id=asset_id)
        except Cons3rtApiError as exc:
            print('Problem retrieving software asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
            traceback.print_exc()
            failed_export_asset_ids.append(asset_id)
            continue
    elif asset_type == 'container':
        try:
            exported_asset_data = exporter.retrieve_container_asset(asset_id=asset_id)
        except Cons3rtApiError as exc:
            print('Problem retrieving container asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
            traceback.print_exc()
            failed_export_asset_ids.append(asset_id)
            continue
    else:
        print('Unsupported asset type [{t}], must be software or container'.format(t=asset_type))
        sys.exit(1)

    # Ensure state and visibility are found
    if 'state' not in exported_asset_data.keys():
        print('state not found in exported asset data: {d}'.format(d=str(exported_asset_data)))
        failed_export_asset_ids.append(asset_id)
        continue
    if 'visibility' not in exported_asset_data.keys():
        print('visibility not found in exported asset data: {d}'.format(d=str(exported_asset_data)))
        failed_export_asset_ids.append(asset_id)
        continue

    # Get the state and visibility from the exported site
    exported_asset_state = exported_asset_data['state']
    exported_asset_visibility = exported_asset_data['visibility']

    # Set the import asset ID
    imported_asset_id = re_import_asset_ids[count]

    # Update asset state to IN_DEVELOPMENT to allow updating
    print('Setting state to IN_DEVELOPMENT for asset ID: [{i}]'.format(i=str(imported_asset_id)))
    try:
        importer.update_asset_state(asset_id=imported_asset_id, state='IN_DEVELOPMENT')
    except Cons3rtApiError as exc:
        print('Problem setting state to IN_DEVELOPMENT on asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_import_asset_ids.append(asset_id)
        continue

    print('Re-importing asset ID [{i}]: #[{n}] of [{t}]'.format(
        i=str(imported_asset_id), n=str(count), t=str(len(asset_ids))))

    # Re-import the asset
    try:
        importer.update_asset_content(
            asset_id=imported_asset_id,
            asset_zip_file=exported_asset
        )
    except Cons3rtApiError as exc:
        print('Problem importing asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_import_asset_ids.append(asset_id)
        continue
    else:
        successful_asset_ids.append(asset_id)
        successful_re_imported_asset_ids.append(imported_asset_id)
    finally:
        print('Removing exported asset: {z}'.format(z=exported_asset))
        os.remove(exported_asset)

    # Set visibility to match the export site
    print('Setting visibility to [{v}] for asset ID: [{i}]'.format(
        i=str(imported_asset_id), v=exported_asset_visibility))
    try:
        importer.update_asset_visibility(asset_id=imported_asset_id, visibility=exported_asset_visibility)
    except Cons3rtApiError as exc:
        fix_visibility.append(imported_asset_id)
        print('Problem setting visibility to [{v}] on asset ID: {i}'.format(
            v=exported_asset_visibility, i=imported_asset_id))
        traceback.print_exc()

    # Set state to match the export site
    print('Setting state to [{s}] for asset ID: [{i}]'.format(i=str(imported_asset_id), s=exported_asset_state))
    try:
        importer.update_asset_state(asset_id=imported_asset_id, state=exported_asset_state)
    except Cons3rtApiError as exc:
        print('Problem setting state to [{s}] on asset ID: {i}\n{e}'.format(
            i=str(asset_id), s=exported_asset_state, e=str(exc)))
        traceback.print_exc()
        fix_state.append(asset_id)


print('COMPLETED EXPORT/RE-IMPORT')
print('Successful asset export/re-imports: [{s}]'.format(s=','.join(map(str, successful_asset_ids))))
print('Successful re-imports of asset IDs: [{s}]'.format(s=','.join(map(str, successful_re_imported_asset_ids))))
print('Failed asset exports: [{f}]'.format(f=','.join(map(str, failed_export_asset_ids))))
print('Failed asset re-imports: [{f}]'.format(f=','.join(map(str, failed_import_asset_ids))))
print('Failed setting visibility on assets: [{i}]'.format(i=','.join(map(str, fix_visibility))))
print('Failed setting state on assets: [{i}]'.format(i=','.join(map(str, fix_state))))
