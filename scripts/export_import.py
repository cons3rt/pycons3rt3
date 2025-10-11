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
export_config_file = '/path/to/source/config.json'
import_config_file = '/path/to/destination/config.json'

# Directory where the assets will be exported to before importing
export_import_dir = '/Users/yennaco/Downloads/export_import'

# Visibility override - otherwise the import will attempt to match the export
valid_visibility = ['OWNER', 'OWNING_PROJECT', 'TRUSTED_PROJECTS', 'COMMUNITY']

# Default NONE to use the exported visibility
#import_visibility_override = 'NONE'

# Set to a valid visibility to override the exported value
import_visibility_override = 'OWNING_PROJECT'

# Set a list of trusted project IDs for the import if TRUSTED_PROJECTS
trusted_project_ids = []

# ################### END EDIT HERE ############################


# Establish Cons3rtApi clients for exporting and importing
exporter = Cons3rtApi(config_file=export_config_file)
importer = Cons3rtApi(config_file=import_config_file)

print('STARTING EXPORT/IMPORT')

successful_asset_ids = []
failed_export_asset_ids = []
failed_import_asset_ids = []
imported_asset_ids = []
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
    try:
        exported_asset_data = exporter.retrieve_software_asset(asset_id=asset_id)
    except Cons3rtApiError as exc:
        print('Problem retrieving asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_export_asset_ids.append(asset_id)
        continue

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

    print('Found asset state [{s}] for exported asset [{a}]'.format(s=exported_asset_state, a=str(asset_id)))
    print('Found asset visibility [{v}] for exported asset [{a}]'.format(v=exported_asset_visibility, a=str(asset_id)))

    print('Importing asset #[{n}] of [{t}]'.format(n=str(count), t=str(len(asset_ids))))

    # Import the asset
    try:
        imported_asset_id = importer.import_asset(asset_zip_file=exported_asset)
    except Cons3rtApiError as exc:
        print('Problem importing asset ID: {i}\n{e}'.format(i=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_import_asset_ids.append(asset_id)
        continue
    else:
        successful_asset_ids.append(asset_id)
        if isinstance(imported_asset_id, int):
            imported_asset_ids.append(imported_asset_id)
    finally:
        print('Removing exported asset: {z}'.format(z=exported_asset))
        os.remove(exported_asset)

    # Set visibility and state to match the exported site if the imported ID is known
    if isinstance(imported_asset_id, int):

        # Set visibility either to match the export site or the override
        if import_visibility_override in valid_visibility:
            exported_asset_visibility = import_visibility_override

        print('Setting visibility to [{v}] for asset ID: [{i}]'.format(
            i=str(imported_asset_id), v=exported_asset_visibility))
        try:
            importer.update_asset_visibility(asset_id=imported_asset_id, visibility=exported_asset_visibility,
                                             trusted_projects=trusted_project_ids)
        except Cons3rtApiError as exc:
            fix_visibility.append(imported_asset_id)
            print('Problem setting visibility to [{v}] on new asset ID: {i}'.format(
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
    else:
        print('New asset ID not known, cannot set visibility and state for the asset that was imported from '
              'exported asset: {i}'.format(i=str(asset_id)))
        fix_state.append(asset_id)
        fix_visibility.append(asset_id)


print('COMPLETED EXPORT/IMPORT')
print('Successful asset export/imports: [{s}]'.format(s=','.join(map(str, successful_asset_ids))))
print('Imported new asset IDs: [{i}]'.format(i=','.join(map(str, imported_asset_ids))))
print('Failed asset exports: [{f}]'.format(f=','.join(map(str, failed_export_asset_ids))))
print('Failed asset imports: [{f}]'.format(f=','.join(map(str, failed_import_asset_ids))))
print('Failed setting visibility on assets: [{i}]'.format(i=','.join(map(str, fix_visibility))))
print('Failed setting state on assets: [{i}]'.format(i=','.join(map(str, fix_state))))
