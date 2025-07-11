#!/usr/bin/env python3
"""
update_categories.py

This is a sample script for updating categories for a list of assets.  To use:

1. Edit variables in the "EDIT HERE" section below
2. Run: python3 update_categories.py

"""
import sys
import traceback

from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.exceptions import Cons3rtApiError


# ##################### EDIT HERE ##############################

# List of asset IDs to export
asset_ids = []

remove_category = 'REPLACE_CATEGORY_TO_REMOVE'
add_category = 'REPLACE_CATEGORY_TO_ADD'

# Establish Cons3rtApi clients for exporting and importing
c = Cons3rtApi()

successful_asset_ids = []
failed_asset_ids = []
remove_category_id = 0
add_category_id = 0

# Get a list of categories to retrieve the category IDs
print('Retrieving a list of asset categories...')
try:
    categories = c.retrieve_asset_categories()
except Cons3rtApiError as exc:
    print('ERROR: Retrieving a list of asset categories\n{e}'.format(e=str(exc)))
    traceback.print_exc()
    sys.exit(1)

# Find the category ID to be removed
for category in categories:
    if category['name'] == remove_category:
        remove_category_id = category['id']

# Find the category ID to be added
for category in categories:
    if category['name'] == add_category:
        add_category_id = category['id']

# Ensure the category IDs were found
if remove_category_id == 0:
    print('ERROR: The category ID to remove was not found')
    sys.exit(1)
if add_category_id == 0:
    print('ERROR: The category ID to add was not found')
    sys.exit(1)

# Download the software assets
print('Updating category from [{r}] to [{a}] on [{n}] software assets...'.format(
    r=remove_category, a=add_category, n=str(len(asset_ids))))
count = 0
for asset_id in asset_ids:
    count += 1

    # Remove the category
    print('Removing category [{c}] with ID [{i}] from asset ID: [{a}]'.format(
        c=remove_category, i=str(remove_category_id), a=str(asset_id)))
    try:
        c.remove_category_from_asset(asset_id=asset_id, category_id=remove_category_id)
    except Cons3rtApiError as exc:
        print('ERROR: Removing category [{c}] with ID [{i}] from add ID: [{a}]\n{e}'.format(
            c=remove_category, i=str(remove_category_id), a=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_asset_ids.append(asset_id)
        continue

    # Remove the category
    print('Adding category [{c}] with ID [{i}] to asset ID: [{a}]'.format(
        c=add_category, i=str(add_category_id), a=str(asset_id)))
    try:
        c.add_category_to_asset(asset_id=asset_id, category_id=add_category_id)
    except Cons3rtApiError as exc:
        print('ERROR: Adding category [{c}] with ID [{i}] to add ID: [{a}]\n{e}'.format(
            c=add_category, i=str(add_category_id), a=str(asset_id), e=str(exc)))
        traceback.print_exc()
        failed_asset_ids.append(asset_id)
        continue
    else:
        successful_asset_ids.append(asset_id)

print('Successful asset updates: [{s}]'.format(s=','.join(map(str, successful_asset_ids))))
print('Failed asset updates: [{f}]'.format(f=','.join(map(str, failed_asset_ids))))

sys.exit(0)
