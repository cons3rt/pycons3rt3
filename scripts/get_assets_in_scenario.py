#!/usr/bin/env python3
"""

get_assets_in_scenario.py

This is a sample script for exporting and importing assets between CONS3RT sites.  To use:

1. Edit variables in the "EDIT HERE" section below
2. Run: ./get_assets_in_scenario.py

"""

import os
import sys
import traceback
from pycons3rt3.cons3rtapi import Cons3rtApi
from pycons3rt3.exceptions import Cons3rtApiError

# ##################### EDIT HERE ##############################

# List of scenario IDs to examine
scenario_ids = []

# Path to the config.json files for the CONS3RT sites to export and import
# See the sample-configs directory for sample config files
config_file = ''

# ################### END EDIT HERE ############################

c = Cons3rtApi(config_file=config_file)


def get_systems_in_scenario(scenario_id):
    """Returns a list of system IDs in the provided scenario

    :param scenario_id: (str) scenario ID
    :return: (tuple): (bool) True for success, False for Error, and (list) of system IDs
    """
    system_ids = []
    scenario_details = c.get_scenario_details(scenario_id=scenario_id)
    if 'scenarioHosts' not in scenario_details.keys():
        print('ERROR: scenarioHosts not found in scenario: {s}'.format(s=str(scenario_details)))
        return False, []
    for scenario_host in scenario_details['scenarioHosts']:
        if 'systemModule' not in scenario_host.keys():
            print('ERROR: systemModule not found in scenario host: {h}'.format(h=str(scenario_host)))
            return False, []
        if 'id' not in scenario_host['systemModule']:
            print('ERROR: if not found in systemModule: {s}'.format(s=str(scenario_host['systemModule'])))
            return False, []
        system_ids.append(scenario_host['systemModule']['id'])
        print('Found system ID: {i}'.format(i=scenario_host['systemModule']['id']))
    print('Found {n} system IDs in scenario: {i}'.format(n=str(len(system_ids)), i=scenario_id))
    return True, system_ids


def get_asset_ids_in_system_design(system_id):
    """Returns a list of asset IDs in the provided system

    :param system_id: (str) system ID
    :return: (tuple): (bool) True for success, False for Error, and (list) of asset IDs
    """
    system_design_details = c.get_system_details(system_id=system_id)
    asset_ids = []
    if 'components' not in system_design_details.keys():
        print('ERROR: No components found in system ID: {i}'.format(i=str(system_id)))
        return False, []
    for component in system_design_details['components']:
        if 'id' not in component['asset'].keys():
            print('ERROR: if not found in component: {c}'.format(c=str(component['asset'])))
            return False, []
        asset_id = component['asset']['id']
        if asset_id not in asset_ids:
            print('Found asset ID: {i}'.format(i=asset_id))
            asset_ids.append(asset_id)
    return True, asset_ids


def get_asset_ids_for_systems(system_id_list):
    system_asset_ids = []
    successful_system_ids = []
    failed_system_ids = []
    for system_id in system_id_list:
        res, system_asset_ids = get_asset_ids_in_system_design(system_id=system_id)
        successful_system_ids.append(system_id) if res else failed_system_ids.append(system_id)
    print('Found {n} assets in system'.format(n=str(len(system_asset_ids))))
    system_asset_ids = list(set(system_asset_ids))
    system_asset_ids.sort()
    return system_asset_ids, successful_system_ids, failed_system_ids


def main():
    system_ids = []
    failed_scenario_ids = []
    successful_scenario_ids = []
    for scenario_id in scenario_ids:
        res, scenario_system_ids = get_systems_in_scenario(scenario_id=scenario_id)
        system_ids += scenario_system_ids
        successful_scenario_ids.append(scenario_id) if res else failed_scenario_ids.append(scenario_id)

    asset_ids, successful_system_ids, failed_system_ids = get_asset_ids_for_systems(system_id_list=system_ids)
    print('Failed scenario IDs: [{f}]'.format(f=','.join(map(str, failed_scenario_ids))))
    print('Failed system IDs: [{f}]'.format(f=','.join(map(str, failed_system_ids))))
    print('Successful scenario IDs: [{f}]'.format(f=','.join(map(str, successful_scenario_ids))))
    print('Successful system IDs: [{f}]'.format(f=','.join(map(str, successful_system_ids))))
    print('Asset IDs: [{f}]'.format(f=','.join(map(str, asset_ids))))
    return 0


if __name__ == '__main__':
    exit_code = main()
    sys.exit(exit_code)
