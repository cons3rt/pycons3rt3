#!/usr/bin/env python

import json
import logging
import os
import time

from .logify import Logify

from .cons3rtclient import Cons3rtClient
from .pycons3rtlibs import RestUser
from .cons3rtconfig import cons3rtapi_config_file
from .exceptions import Cons3rtClientError, Cons3rtApiError


# Set up logger name for this module
mod_logger = Logify.get_name() + '.cons3rtapi'


class Scenario(object):

    def __init__(self, name='', config_script=None, teardown_script=None):
        self.name = name
        self.scenario_hosts = []
        self.teardown_script = teardown_script
        self.config_script = config_script

    def add_scenario_host(self, role_name, system_id, subtype='virtualHost', build_order=1, master=False,
                          host_config_script=None, host_teardown_script=None):
        """Add a scenario host to the Scenario object

        :param role_name: (str) role name
        :param system_id: (int) system ID
        :param subtype: (str) see CONS3RT API docs
        :param build_order: (int) see CONS3RT API docs
        :param master: (bool) see CONS3RT API docs
        :param host_config_script: (str) see CONS3RT API docs
        :param host_teardown_script: (str) see CONS3RT API docs
        :return: None
        """
        scenario_host = {'systemRole': role_name, 'systemModule': {}}
        scenario_host['systemModule']['subtype'] = subtype
        scenario_host['systemModule']['id'] = system_id
        scenario_host['systemModule']['buildOrder'] = build_order
        if master:
            scenario_host['systemModule']['master'] = 'true'
        else:
            scenario_host['systemModule']['master'] = 'false'
        if host_config_script:
            scenario_host['systemModule']['configureScenarioConfiguration'] = host_config_script
        if host_teardown_script:
            scenario_host['systemModule']['teardownScenarioConfiguration'] = host_teardown_script
        self.scenario_hosts.append(scenario_host)

    def set_config_script(self, config_script):
        self.config_script = config_script

    def set_teardown_script(self, teardown_script):
        self.teardown_script = teardown_script

    def create(self, cons3rt_api):
        return cons3rt_api.create_scenario(
            name=self.name,
            scenario_hosts=self.scenario_hosts
        )


class Cons3rtApi(object):

    def __init__(self, url=None, base_dir=None, user=None, config_file=cons3rtapi_config_file, project=None):
        self.cls_logger = mod_logger + '.Cons3rtApi'
        self.user = user
        self.url_base = url
        self.base_dir = base_dir
        self.project = project
        self.retries = ''
        self.timeout = ''
        self.queries = ''
        self.virtrealm = ''
        self.config_file = config_file
        self.config_data = {}
        self.user_list = []
        if self.user is None:
            self.load_config()
        self.cons3rt_client = Cons3rtClient(base=self.url_base, user=self.user)

    def load_config(self):
        """Loads the default config file

        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.load_config')
        log.info('Loading configuration...')

        # Ensure the file_path file exists
        if not os.path.isfile(self.config_file):
            raise Cons3rtApiError('Cons3rtApi config file is required but not found: {f}'.format(f=self.config_file))

        # Load the config file
        try:
            with open(self.config_file, 'r') as f:
                self.config_data = json.load(f)
        except(OSError, IOError) as exc:
            raise Cons3rtApiError('Unable to read the Cons3rtApi config file: {f}'.format(f=self.config_file)) from exc
        else:
            log.debug('Loading config data from file: {f}'.format(f=self.config_file))

        # Attempt to load the URL
        try:
            self.url_base = self.config_data['api_url']
        except KeyError:
            raise Cons3rtApiError('api_url is required but not defined in the config file')
        log.info('Using CONS3RT API URL: {u}'.format(u=self.url_base))

        # Attempt to find a username in the config data
        try:
            username = self.config_data['name']
        except KeyError:
            username = None

        # Attempt to find a cert_file_path in the config data
        try:
            cert_file_path = self.config_data['cert']
        except KeyError:
            cert_file_path = None
        else:
            # Ensure the cert_file_path points to an actual file
            if not os.path.isfile(cert_file_path):
                raise Cons3rtApiError('config.json provided a cert, but the cert file was not found: {f}'.format(
                    f=cert_file_path))
            log.info('Found certificate file: {f}'.format(f=cert_file_path))

        # Ensure that either a username or cert_file_path was found
        if username is None and cert_file_path is None:
            raise Cons3rtApiError('The config.json file must contain values for either name or cert')

        # Ensure at least one token is found
        try:
            project_token_list = self.config_data['projects']
        except KeyError:
            raise Cons3rtApiError(
                'Element [projects] is required but not found in the config data, at least 1 project token must '
                'be configured')

        # Attempt to create a ReST user for each project in the list
        for project in project_token_list:
            try:
                token = project['rest_key']
                project_name = project['name']
            except KeyError:
                log.warning('Found an invalid project token, skipping: {p}'.format(p=str(project)))
                continue

            # Create a ReST User for the project/token pair
            log.debug('Found rest token for project {p}: {t}'.format(p=project, t=token))

            # Create a cert-based auth or username-based auth user depending on the config
            if cert_file_path:
                self.user_list.append(RestUser(token=token, project=project_name, cert_file_path=cert_file_path))
            elif username:
                self.user_list.append(RestUser(token=token, project=project_name, username=username))

        # Ensure that at least one valid project/token was found
        if len(self.user_list) < 1:
            raise Cons3rtApiError('A ReST API token was not found in config file: {f}'.format(f=self.config_file))

        log.info('Found {n} project/token pairs'.format(n=str(len(self.user_list))))

        # Select the first user to use as the default
        self.user = self.user_list[0]
        if self.project is not None:
            self.set_project_token(project_name=self.project)
        log.info('Set project to [{p}] and ReST API token: {t}'.format(p=self.user.project_name, t=self.user.token))

    def set_project_token(self, project_name):
        """Sets the project name and token to the specified project name.  This project name
        must already exist in config data

        :param project_name: (str) name of the project
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.set_project_token')

        # Ensure the project_name is a string
        if not type(project_name) is str:
            raise Cons3rtApiError('The arg project_name must be a string, found: {t}'.format(
                t=project_name.__class__.__name__))

        # Loop through the projects until the project matches
        found = False
        log.info('Attempting to set the project token pair for project: {p}'.format(p=project_name))
        for rest_user in self.user_list:
            log.debug('Checking if rest user matches project [{p}]: {u}'.format(p=project_name, u=str(rest_user)))
            if rest_user.project_name == project_name:
                log.info('Found matching rest user: {u}'.format(u=str(rest_user)))
                self.user = rest_user
                found = True
                break
        if found:
            log.info('Set project to [{p}] and ReST API token: {t}'.format(p=self.user.project_name, t=self.user.token))
        else:
            log.warning('Matching ReST User not found for project: {p}'.format(p=project_name))

    def get_asset_type(self, asset_type):
        """Translates the user-provided asset type to an actual ReST target

        :param asset_type: (str) provided asset type
        :return: (str) asset type ReSt target
        """
        log = logging.getLogger(self.cls_logger + '.get_asset_type')

        # Determine the target based on asset_type
        target = ''
        if 'scenario' in asset_type.lower():
            target = 'scenarios'
        elif 'deployment' in asset_type.lower():
            target = 'deployments'
        elif 'software' in asset_type.lower():
            target = 'software'
        elif 'system' in asset_type.lower():
            target = 'systems'
        elif 'test' in asset_type.lower():
            target = 'testassets'
        else:
            log.warning('Unable to determine the target from provided asset_type: {t}'.format(t=asset_type))
        return target

    def register_cloud_from_json(self, json_file):
        """Attempts to register a Cloud using the provided JSON
        file as the payload

        :param json_file: (str) path to the JSON file
        :return: (int) Cloud ID
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.register_cloud_from_json')

        # Ensure the json_file arg is a string
        if not type(json_file) is str:
            msg = 'The json_file arg must be a string'
            raise ValueError(msg)

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise OSError(msg)

        # Attempt to register the Cloud
        try:
            cloud_id = self.cons3rt_client.register_cloud(cloud_file=json_file)
        except Cons3rtClientError as exc:
            raise Cons3rtApiError('Unable to register a Cloud using JSON file: {f}'.format(f=json_file)) from exc
        log.info('Successfully registered Cloud ID: {c}'.format(c=str(cloud_id)))
        return cloud_id

    def create_team_from_json(self, json_file):
        """Attempts to create a Team using the provided JSON
        file as the payload

        :param json_file: (str) path to the JSON file
        :return: (int) Team ID
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_team_from_json')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, str):
            raise ValueError('The json_file arg must be a string')

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            raise OSError('JSON file not found: {f}'.format(f=json_file))

        # Attempt to create the team
        try:
            team_id = self.cons3rt_client.create_team(team_file=json_file)
        except Cons3rtClientError as exc:
            raise Cons3rtApiError('Unable to create a Team using JSON file: {f}'.format(f=json_file)) from exc
        log.info('Successfully created Team ID: {c}'.format(c=str(team_id)))
        return team_id

    def register_virtualization_realm_to_cloud_from_json(self, cloud_id, json_file):
        """Attempts to register a virtualization realm using
        the provided JSON file as the payload

        :param cloud_id: (int) Cloud ID to register the VR under
        :param json_file: (str) path to JSON file
        :return: (int) Virtualization Realm ID
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.register_virtualization_realm_to_cloud_from_json')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, str):
            raise Cons3rtApiError('The json_file arg must be a string')

        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError as exc:
                raise Cons3rtApiError('The cloud_id arg must be an int') from exc

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            raise OSError('JSON file not found: {f}'.format(f=json_file))

        # Attempt to register the virtualization realm to the Cloud ID
        try:
            vr_id = self.cons3rt_client.register_virtualization_realm(
                cloud_id=cloud_id,
                virtualization_realm_file=json_file)
        except Cons3rtClientError as exc:
            raise Cons3rtApiError('Unable to register virtualization realm to Cloud ID {c} from file: {f}'.format(
                c=cloud_id, f=json_file)) from exc
        log.info('Registered new Virtualization Realm ID {v} to Cloud ID: {c}'.format(v=str(vr_id), c=str(cloud_id)))
        return vr_id

    def allocate_virtualization_realm_to_cloud_from_json(self, cloud_id, json_file):
        """Attempts to allocate a virtualization realm using
        the provided JSON file as the payload

        :param cloud_id: (int) Cloud ID to allocate the VR under
        :param json_file: (str) path to JSON file
        :return: (int) Virtualization Realm ID
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.allocate_virtualization_realm_to_cloud_from_json')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, str):
            msg = 'The json_file arg must be a string'
            raise Cons3rtApiError(msg)

        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError as exc:
                msg = 'The cloud_id arg must be an int'
                raise Cons3rtApiError(msg) from exc

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise OSError(msg)

        # Attempt to register the virtualization realm to the Cloud ID
        try:
            vr_id = self.cons3rt_client.allocate_virtualization_realm(
                cloud_id=cloud_id,
                allocate_virtualization_realm_file=json_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to allocate virtualization realm to Cloud ID {c} from file: {f}'.format(
                c=cloud_id, f=json_file)
            raise Cons3rtApiError(msg) from exc
        log.info('Allocated new Virtualization Realm ID {v} to Cloud ID: {c}'.format(v=str(vr_id), c=str(cloud_id)))
        return vr_id

    def list_projects(self):
        """Query CONS3RT to return a list of projects for the current user

        :return: (list) of Project info
        """
        log = logging.getLogger(self.cls_logger + '.list_projects')
        log.info('Attempting to list all user projects...')
        projects = []
        page_num = 0
        max_results = 40
        while True:
            log.debug('Attempting to list projects for user: {u}, page: {p}, max results: {m}'.format(
                u=self.user.username, p=str(page_num), m=str(max_results)))
            try:
                page_of_projects = self.cons3rt_client.list_projects(
                    max_results=max_results,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'There was a problem querying CONS3RT for a list of projects'
                raise Cons3rtClientError(msg) from exc
            projects += page_of_projects
            if len(page_of_projects) < max_results:
                break
            else:
                page_num += 1
        log.info('Found {n} user projects'.format(n=str(len(projects))))
        return projects

    def list_expanded_projects(self):
        """Query CONS3RT to return a list of projects the current user is not a member of

        :return: (list) of Project info
        """
        log = logging.getLogger(self.cls_logger + '.list_expanded_projects')
        log.info('Attempting to list expanded projects...')
        projects = []
        page_num = 0
        max_results = 40
        while True:
            log.debug('Attempting to list non-member projects for user: {u}, page: {p}, max results: {m}'.format(
                u=self.user.username, p=str(page_num), m=str(max_results)))
            try:
                page_of_projects = self.cons3rt_client.list_expanded_projects(
                    max_results=max_results,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'There was a problem querying CONS3RT for a list of expanded projects'
                raise Cons3rtClientError(msg) from exc
            projects += page_of_projects
            if len(page_of_projects) < max_results:
                break
            else:
                page_num += 1
        log.info('Found {n} non-member projects'.format(n=str(len(projects))))
        return projects

    def list_all_projects(self):
        """Query CONS3RT to return a list of all projects on the site

        :return: (list) of Project info
        """
        log = logging.getLogger(self.cls_logger + '.list_all_projects')
        log.info('Attempting to list all projects...')
        try:
            member_projects = self.list_projects()
            non_member_projects = self.list_expanded_projects()
        except Cons3rtClientError as exc:
            raise Cons3rtApiError('There was a problem querying CONS3RT for a list of projects') from exc
        all_projects = member_projects + non_member_projects
        log.info('Found [{n}] projects in all'.format(n=str(len(all_projects))))
        return all_projects

    def get_project_details(self, project_id):
        """Returns details for the specified project ID

        :param (int) project_id: ID of the project to query
        :return: (dict) details for the project ID
        """
        log = logging.getLogger(self.cls_logger + '.get_project_details')

        # Ensure the vr_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.debug('Attempting query project ID {i}'.format(i=str(project_id)))
        try:
            project_details = self.cons3rt_client.get_project_details(project_id=project_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for details on project: {i}'.format(i=str(project_id))
            raise Cons3rtApiError(msg) from exc
        return project_details

    def get_project_id(self, project_name):
        """Given a project name, return a list of IDs with that name

        :param project_name: (str) name of the project
        :return: (list) of project IDs (int)
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.get_project_id')

        if not isinstance(project_name, str):
            raise Cons3rtApiError('Expected project_name arg to be a string, found: {t}'.format(
                t=project_name.__class__.__name__)
            )

        project_id_list = []

        # List all projects
        log.debug('Getting a list of all projects...')
        try:
            projects = self.list_all_projects()
        except Cons3rtApiError as exc:
            msg = 'Cons3rtApiError: There was a problem listing all projects'
            raise Cons3rtApiError(msg) from exc

        # Look for project IDs with matching names
        log.debug('Looking for projects with name: {n}'.format(n=project_name))
        for project in projects:
            if project['name'] == project_name:
                project_id_list.append(project['id'])

        # Raise an error if the project was not found
        if len(project_id_list) < 1:
            raise Cons3rtApiError('Project not found: {f}'.format(f=project_name))

        # Return the list of IDs
        return project_id_list

    def list_projects_in_virtualization_realm(self, vr_id):
        """Queries CONS3RT for a list of projects in the virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: (list) of projects
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_projects_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.info('Attempting to list projects in virtualization realm ID: {i}'.format(i=str(vr_id)))
        projects = []
        page_num = 0
        max_results = 40
        while True:
            log.debug('Attempting to list projects in virtualization realm ID: {i}, page: {p}, max results: {m}'.format(
                i=str(vr_id), p=str(page_num), m=str(max_results)))
            try:
                page_of_projects = self.cons3rt_client.list_projects_in_virtualization_realm(
                    vr_id=vr_id,
                    max_results=max_results,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'Unable to query CONS3RT for a list of projects in virtualization realm ID: {i}, ' \
                      'page: {p}, max results: {m}'.format(i=str(vr_id), p=str(page_num), m=str(max_results))
                raise Cons3rtClientError(msg) from exc
            projects += page_of_projects
            if len(page_of_projects) < max_results:
                break
            else:
                page_num += 1
        log.info('Found {n} projects in virtualization realm ID: {i}'.format(n=str(len(projects)), i=str(vr_id)))
        return projects

    def list_clouds(self):
        """Query CONS3RT to return a list of the currently configured Clouds

        :return: (list) of Cloud Info
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_clouds')
        log.info('Attempting to list clouds...')
        clouds = []
        page_num = 0
        max_results = 40
        while True:
            log.debug('Attempting to list clouds with {m} max results for page number: {p}'.format(
                m=str(max_results), p=str(page_num)))
            try:
                page_of_clouds = self.cons3rt_client.list_clouds(max_results=max_results, page_num=page_num)
            except Cons3rtClientError as exc:
                msg = 'Unable to query CONS3RT for a list of Clouds'
                raise Cons3rtClientError(msg) from exc
            clouds += page_of_clouds
            if len(page_of_clouds) < max_results:
                break
            else:
                page_num += 1
        log.info('Found {n} clouds'.format(n=str(len(clouds))))
        return clouds

    def list_teams(self):
        """Query CONS3RT to return a list of Teams

        :return: (list) of Team Info
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_teams')
        log.info('Attempting to list teams...')
        teams = []
        page_num = 0
        max_results = 40
        while True:
            log.debug('Attempting to list teams with {m} max results for page number: {p}'.format(
                m=str(max_results), p=str(page_num)))
            try:
                page_of_teams = self.cons3rt_client.list_teams(max_results=max_results, page_num=page_num)
            except Cons3rtClientError as exc:
                msg = 'Unable to query CONS3RT for a list of Teams'
                raise Cons3rtClientError(msg) from exc
            teams += page_of_teams
            if len(page_of_teams) < max_results:
                break
            else:
                page_num += 1
        log.info('Found {n} teams'.format(n=str(len(teams))))
        return teams

    def list_all_teams(self):
        """Query CONS3RT to retrieve all site teams (deprecated)

        :return: (list) Containing all site teams
        :raises: Cons3rtClientError
        """
        return self.list_teams()

    def get_team_details(self, team_id):
        """Returns details for the specified team ID

        :param (int) team_id: ID of the team to query
        :return: (dict) details for the team ID
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.get_team_details')

        # Ensure the team_id is an int
        if not isinstance(team_id, int):
            try:
                team_id = int(team_id)
            except ValueError as exc:
                msg = 'team_id arg must be an Integer, found: {t}'.format(t=team_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.debug('Attempting query team ID {i}'.format(i=str(team_id)))
        try:
            team_details = self.cons3rt_client.get_team_details(team_id=team_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for details on team: {i}'.format(i=str(team_id))
            raise Cons3rtApiError(msg) from exc
        return team_details

    def get_system_details(self, system_id):
        """Query CONS3RT to retrieve system details

        :param system_id: (int) system ID to retrieve
        :return: (dict) details for the system
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.get_system_details')

        # Ensure the system_id is an int
        if not isinstance(system_id, int):
            try:
                system_id = int(system_id)
            except ValueError as exc:
                msg = 'system_id arg must be an Integer, found: {t}'.format(t=system_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.debug('Attempting query system ID {i}'.format(i=str(system_id)))
        try:
            system_details = self.cons3rt_client.get_system_details(system_id=system_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for details on system: {i}'.format(i=str(system_id))
            raise Cons3rtApiError(msg) from exc
        return system_details

    def list_scenarios(self):
        """Query CONS3RT to return a list of Scenarios

        :return: (list) of Scenario Info
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_scenarios')
        log.info('Attempting to get a list of scenarios...')
        try:
            scenarios = self.cons3rt_client.list_scenarios()
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a list of scenarios'
            raise Cons3rtApiError(msg) from exc
        return scenarios

    def get_scenario_details(self, scenario_id):
        """Query CONS3RT to retrieve scenario details

        :param scenario_id: (int) scenario ID to retrieve
        :return: (dict) details for the scenario
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.get_scenario_details')

        # Ensure the team_id is an int
        if not isinstance(scenario_id, int):
            try:
                scenario_id = int(scenario_id)
            except ValueError as exc:
                msg = 'scenario_id arg must be an Integer, found: {t}'.format(t=scenario_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.debug('Attempting query scenario ID {i}'.format(i=str(scenario_id)))
        try:
            scenario_details = self.cons3rt_client.get_scenario_details(scenario_id=scenario_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for details on scenario: {i}'.format(i=str(scenario_id))
            raise Cons3rtApiError(msg) from exc
        return scenario_details

    def list_deployments(self):
        """Query CONS3RT to return a list of Deployments

        :return: (list) of Deployments Info
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_deployments')
        log.info('Attempting to get a list of deployments...')
        try:
            deployments = self.cons3rt_client.list_deployments()
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a list of deployments'
            raise Cons3rtApiError(msg) from exc
        return deployments

    def get_deployment_details(self, deployment_id):
        """Query CONS3RT to retrieve deployment details

        :param deployment_id: (int) deployment ID to retrieve
        :return: (dict) details for the deployment
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.get_deployment_details')

        # Ensure the deployment_id is an int
        if not isinstance(deployment_id, int):
            try:
                deployment_id = int(deployment_id)
            except ValueError as exc:
                msg = 'deployment_id arg must be an Integer, found: {t}'.format(t=deployment_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.debug('Attempting query deployment ID {i}'.format(i=str(deployment_id)))
        try:
            deployment_details = self.cons3rt_client.get_deployment_details(deployment_id=deployment_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for details on deployment: {i}'.format(i=str(deployment_id))
            raise Cons3rtApiError(msg) from exc
        return deployment_details

    def get_deployment_bindings_for_virtualization_realm(self, deployment_id, vr_id):
        """Get virtualization realm bindings for a deployment

        :param deployment_id: (int) deployment ID to retrieve
        :param vr_id (int) ID of the virtualization realm to retrieve bindings from
        :return: (list) bindings for the deployment
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.get_deployment_bindings_for_virtualization_realm')

        # Ensure the deployment_id is an int
        if not isinstance(deployment_id, int):
            try:
                deployment_id = int(deployment_id)
            except ValueError as exc:
                msg = 'deployment_id arg must be an Integer, found: {t}'.format(t=deployment_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Query cons3rt for VR bindings for the deployment
        log.debug('Attempting query deployment ID [{i}] for bindings in VR ID: {v}'.format(
            i=str(deployment_id), v=str(vr_id)))
        try:
            deployment_bindings = self.cons3rt_client.get_deployment_bindings_for_virtualization_realm(
                deployment_id=deployment_id, vr_id=vr_id
            )
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a deployment ID [{i}] bindings in VR ID [{v}]'.format(
                i=str(deployment_id), v=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        return deployment_bindings

    def list_deployment_runs_in_virtualization_realm(self, vr_id, search_type='SEARCH_ALL'):
        """Query CONS3RT to return a list of deployment runs in a virtualization realm

        :param: vr_id: (int) virtualization realm ID
        :param: search_type (str) the run status to filter the search on
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_deployment_runs_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure status is valid
        if not isinstance(search_type, str):
            raise Cons3rtApiError('Arg search_type must be a string, found type: {t}'.format(
                t=search_type.__class__.__name__))

        valid_search_type = ['SEARCH_ACTIVE', 'SEARCH_ALL', 'SEARCH_AVAILABLE', 'SEARCH_COMPOSING',
                             'SEARCH_DECOMPOSING', 'SEARCH_INACTIVE', 'SEARCH_PROCESSING', 'SEARCH_SCHEDULED',
                             'SEARCH_TESTING', 'SEARCH_SCHEDULED_AND_ACTIVE']

        search_type = search_type.upper()
        if search_type not in valid_search_type:
            raise Cons3rtApiError('Arg status provided is not valid, must be one of: {s}'.format(
                s=', '.join(search_type)))

        # Attempt to get a list of deployment runs
        log.info('Attempting to get a list of deployment runs with search_type {s} in '
                 'virtualization realm ID: {i}'.format(i=str(vr_id), s=search_type))

        drs = []
        page_num = 0
        max_results = 40
        while True:
            log.debug('Attempting to list runs in virtualization realm ID: {i}, page: {p}, max results: {m}'.format(
                i=str(vr_id), p=str(page_num), m=str(max_results)))
            try:
                page_of_drs = self.cons3rt_client.list_deployment_runs_in_virtualization_realm(
                    vr_id=vr_id,
                    max_results=max_results,
                    page_num=page_num,
                    search_type=search_type
                )
            except Cons3rtClientError as exc:
                msg = 'There was a problem querying CONS3RT for a list of runs in virtualization realm ID: {i}, ' \
                      'page: {p}, max results: {m}'.format(i=str(vr_id), p=str(page_num), m=str(max_results))
                raise Cons3rtClientError(msg) from exc
            drs += page_of_drs
            if len(page_of_drs) < max_results:
                break
            else:
                page_num += 1
        log.info('Found {n} runs in virtualization realm ID: {i}'.format(n=str(len(drs)), i=str(vr_id)))
        return drs

    def retrieve_deployment_run_details(self, dr_id):
        """Query CONS3RT to return details of a deployment run

        :param: dr_id: (int) deployment run ID
        :return: (dict) of deployment run detailed info
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_deployment_run_details')

        # Ensure the dr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError as exc:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Query for DR details
        log.info('Attempting to retrieve details for deployment run ID: {i}'.format(i=str(dr_id)))
        try:
            dr_details = self.cons3rt_client.retrieve_deployment_run_details(dr_id=dr_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a details of deployment run ID: {i}'.format(
                i=str(dr_id))
            raise Cons3rtApiError(msg) from exc
        return dr_details

    def list_virtualization_realms_for_cloud(self, cloud_id):
        """Query CONS3RT to return a list of VRs for a specified Cloud ID

        :param cloud_id: (int) Cloud ID
        :return: (list) of Virtualization Realm data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_virtualization_realms_for_cloud')
        log.info('Attempting to list virtualization realms for cloud ID: {i}'.format(i=cloud_id))
        try:
            vrs = self.cons3rt_client.list_virtualization_realms_for_cloud(cloud_id=cloud_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a list of Virtualization Realms for Cloud ID: {c}'.format(
                c=cloud_id)
            raise Cons3rtApiError(msg) from exc
        return vrs

    def add_cloud_admin(self, cloud_id, username=None):
        """Adds a users as a Cloud Admin

        :param username: (str) Username
        :param cloud_id: (int) Cloud ID
        :return: None
        :raises: Cons3rtApiError, ValueError
        """
        log = logging.getLogger(self.cls_logger + '.add_cloud_admin')
        if username is None:
            username = self.user.username
        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError as exc:
                msg = 'The cloud_id arg must be an int'
                raise Cons3rtApiError(msg) from exc
        try:
            self.cons3rt_client.add_cloud_admin(cloud_id=cloud_id, username=self.user.username)
        except Cons3rtClientError as exc:
            msg = 'Unable to add Cloud Admin {u} to Cloud: {c}'.format(u=username, c=cloud_id)
            raise Cons3rtApiError(msg) from exc
        else:
            log.info('Added Cloud Admin {u} to Cloud: {c}'.format(u=username, c=cloud_id))

    def delete_asset(self, asset_id):
        """Deletes the asset based on a provided asset type

        :param asset_id: (int) asset ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.delete_asset')

        # Ensure the asset_id is an int
        if not isinstance(asset_id, int):
            try:
                asset_id = int(asset_id)
            except ValueError as exc:
                msg = 'asset_id arg must be an Integer, found: {t}'.format(t=asset_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Attempt to delete the target
        try:
            self.cons3rt_client.delete_asset(asset_id=asset_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to delete asset ID: {i}'.format(
                i=str(asset_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully deleted asset ID: {i}'.format(i=str(asset_id)))

    def update_asset_content(self, asset_id, asset_zip_file):
        """Updates the asset content for the provided asset_id using the asset_zip_file

        :param asset_id: (int) ID of the asset to update
        :param asset_zip_file: (str) path to the asset zip file
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.update_asset_content')

        # Ensure the asset_id is an int
        if not isinstance(asset_id, int):
            try:
                asset_id = int(asset_id)
            except ValueError as exc:
                msg = 'asset_id arg must be an Integer'
                raise ValueError(msg) from exc

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(asset_zip_file, str):
            msg = 'The json_file arg must be a string'
            raise ValueError(msg)

        # Ensure the asset_zip_file file exists
        if not os.path.isfile(asset_zip_file):
            msg = 'Asset zip file file not found: {f}'.format(f=asset_zip_file)
            raise OSError(msg)

        # Attempt to update the asset ID
        try:
            self.cons3rt_client.update_asset_content(asset_id=asset_id, asset_zip_file=asset_zip_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to update asset ID {i} using asset zip file: {f}'.format(
                i=str(asset_id), f=asset_zip_file)
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully updated Asset ID: {i}'.format(i=str(asset_id)))

    def update_asset_state(self, asset_type, asset_id, state):
        """Updates the asset state

        :param asset_type: (str) asset type (scenario, deployment, system, etc)
        :param asset_id: (int) asset ID to update
        :param state: (str) desired state
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.update_asset_state')

        # Ensure the asset_id is an int
        if not isinstance(asset_id, int):
            try:
                asset_id = int(asset_id)
            except ValueError as exc:
                msg = 'asset_id arg must be an Integer'
                raise Cons3rtApiError(msg) from exc

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(asset_type, str):
            msg = 'The asset_type arg must be a string, found {t}'.format(t=asset_type.__class__.__name__)
            raise Cons3rtApiError(msg)

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(state, str):
            msg = 'The state arg must be a string, found {t}'.format(t=state.__class__.__name__)
            raise Cons3rtApiError(msg)

        # Determine the target based on asset_type
        target = self.get_asset_type(asset_type=asset_type)
        if target == '':
            raise Cons3rtApiError('Unable to determine the target from provided asset_type: {t}'.format(t=asset_type))

        # Ensure state is valid
        valid_states = ['DEVELOPMENT', 'PUBLISHED', 'CERTIFIED', 'DEPRECATED', 'OFFLINE']
        state = state.upper().strip()
        if state not in valid_states:
            raise Cons3rtApiError('Provided state is not valid: {s}, must be one of: {v}'.format(
                s=state, v=valid_states))

        # Attempt to update the asset ID
        try:
            self.cons3rt_client.update_asset_state(asset_id=asset_id, state=state, asset_type=target)
        except Cons3rtClientError as exc:
            msg = 'Unable to update the state for asset ID: {i}'.format(
                i=str(asset_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully updated state for Asset ID {i} to: {s}'.format(i=str(asset_id), s=state))

    def update_asset_visibility(self, asset_type, asset_id, visibility, trusted_projects=None):
        """Updates the asset visibility

        :param asset_type: (str) asset type (scenario, deployment, system, etc)
        :param asset_id: (int) asset ID to update
        :param visibility: (str) desired asset visibility
        :param trusted_projects (list) of int project IDs to add
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.update_asset_visibility')

        # Ensure the asset_id is an int
        if not isinstance(asset_id, int):
            try:
                asset_id = int(asset_id)
            except ValueError as exc:
                msg = 'asset_id arg must be an Integer'
                raise Cons3rtApiError(msg) from exc

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(asset_type, str):
            msg = 'The asset_type arg must be a string, found {t}'.format(t=asset_type.__class__.__name__)
            raise Cons3rtApiError(msg)

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(visibility, str):
            msg = 'The visibility arg must be a string, found {t}'.format(t=visibility.__class__.__name__)
            raise Cons3rtApiError(msg)

        # Determine the target based on asset_type
        target = self.get_asset_type(asset_type=asset_type)
        if target == '':
            raise Cons3rtApiError('Unable to determine the target from provided asset_type: {t}'.format(t=asset_type))

        # Valid values for visibility
        valid_visibility = ['OWNER', 'OWNING_PROJECT', 'TRUSTED_PROJECTS', 'COMMUNITY']

        # Ensure visibility is valid
        visibility = visibility.upper().strip()
        if visibility not in valid_visibility:
            raise Cons3rtApiError('Provided visibility is not valid: {s}, must be one of: {v}'.format(
                s=visibility, v=valid_visibility))

        # If a list of trusted project was provided, add them to the asset
        if trusted_projects and visibility == 'TRUSTED_PROJECTS':
            for trusted_project in trusted_projects:
                try:
                    self.cons3rt_client.add_trusted_project_to_asset(
                        asset_id=asset_id, trusted_project_id=trusted_project)
                except Cons3rtClientError as exc:
                    msg = 'Problem adding trusted project ID [{p}] to asset ID: {i}'.format(
                        p=str(trusted_project), i=str(asset_id))
                    raise Cons3rtApiError(msg) from exc
                log.info('Added trusted project ID [{p}] to asset ID: {i}'.format(
                    p=str(trusted_project), i=str(asset_id)))

        # Attempt to update the asset ID
        try:
            self.cons3rt_client.update_asset_visibility(asset_id=asset_id, visibility=visibility, asset_type=target)
        except Cons3rtClientError as exc:
            msg = 'Unable to update the visibility for asset ID: {i}'.format(i=str(asset_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully updated visibility for Asset ID {i} to: {s}'.format(i=str(asset_id), s=visibility))

    def import_asset(self, asset_zip_file):
        """Imports an asset zip file into CONS3RT

        :param asset_zip_file: (str) full path to the asset zip file
        :return: (int) asset ID
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.import_asset')

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(asset_zip_file, str):
            msg = 'The json_file arg must be a string'
            raise ValueError(msg)

        # Ensure the asset_zip_file file exists
        if not os.path.isfile(asset_zip_file):
            msg = 'Asset zip file file not found: {f}'.format(f=asset_zip_file)
            raise OSError(msg)

        # Attempt to import the asset
        try:
            asset_id = self.cons3rt_client.import_asset(asset_zip_file=asset_zip_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to import asset using asset zip file: {f}'.format(
                f=asset_zip_file)
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully imported asset from file [{f}] as asset ID: {i}'.format(
            f=asset_zip_file, i=str(asset_id)))
        return asset_id

    def enable_remote_access(self, vr_id, size=None):
        """Enables Remote Access for a specific virtualization realm, and uses SMALL
        as the default size if none is provided.

        :param vr_id: (int) ID of the virtualization
        :param size: (str) small, medium, or large
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.enable_remote_access')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise ValueError('vr_id arg must be an Integer') from exc

        # Use small as the default size
        if size is None:
            size = 'SMALL'

        # Ensure size is a string
        if not isinstance(size, str):
            raise ValueError('The size arg must be a string')

        # Acceptable sizes
        size_options = ['SMALL', 'MEDIUM', 'LARGE']
        size = size.upper()
        if size not in size_options:
            raise ValueError('The size arg must be set to SMALL, MEDIUM, or LARGE')

        # Attempt to enable remote access
        log.info('Attempting to enable remote access in virtualization realm ID {i} with size: {s}'.format(
            i=vr_id, s=size))
        try:
            self.cons3rt_client.enable_remote_access(vr_id=vr_id, size=size)
        except Cons3rtClientError as exc:
            msg = 'There was a problem enabling remote access in virtualization realm ID: {i} with size: ' \
                  '{s}'.format(i=vr_id, s=size)
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully enabled remote access in virtualization realm: {i}, with size: {s}'.format(
            i=vr_id, s=size))

    def disable_remote_access(self, vr_id):
        """Disables Remote Access for a specific virtualization realm

        :param vr_id: (int) ID of the virtualization
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.disable_remote_access')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise ValueError('vr_id arg must be an Integer') from exc

        # Attempt to disable remote access
        log.info('Attempting to disable remote access in virtualization realm ID: {i}'.format(i=vr_id))
        try:
            self.cons3rt_client.disable_remote_access(vr_id=vr_id)
        except Cons3rtClientError as exc:
            msg = 'There was a problem disabling remote access in virtualization realm ID: {i}'.format(
                i=vr_id)
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully disabled remote access in virtualization realm: {i}'.format(
            i=vr_id))

    def toggle_remote_access(self, vr_id, size=None):
        """Enables Remote Access for a specific virtualization realm, and uses SMALL
        as the default size if none is provided.

        :param vr_id: (int) ID of the virtualization
        :param size: (str) small, medium, or large
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.toggle_remote_access')

        # Re-try time for enable, disable, and checks
        retry_time_sec = 10

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise ValueError('vr_id arg must be an Integer') from exc

        # Use small as the default size
        if size is None:
            try:
                vr_details = self.get_virtualization_realm_details(vr_id=vr_id)
            except Cons3rtApiError as exc:
                msg = 'Cons3rtApiError: Unable to query VR details to determine the size'
                raise Cons3rtApiError(msg) from exc
            try:
                size = vr_details['remoteAccessConfig']['instanceType']
            except KeyError:
                raise Cons3rtApiError('Remote Access config instance type not found in VR details: {d}'.format(
                    d=str(vr_details)))

        # Ensure size is a string
        if not isinstance(size, str):
            raise ValueError('The size arg must be a string')

        # Acceptable sizes
        size_options = ['SMALL', 'MEDIUM', 'LARGE']
        size = size.upper()
        if size not in size_options:
            raise ValueError('The size arg must be set to SMALL, MEDIUM, or LARGE')

        # Attempt to disable remote access
        log.info('Attempting to disable remote access in virtualization realm ID {i}'.format(
            i=vr_id))
        max_disable_retries = 12
        disable_try_num = 1
        while True:
            if disable_try_num > max_disable_retries:
                raise Cons3rtApiError(
                    'Unable to disable remote access in virtualization realm ID [{i}] after {m} attempts'.format(
                        i=str(vr_id), m=str(max_disable_retries)))
            try:
                self.disable_remote_access(vr_id=vr_id)
            except Cons3rtApiError as exc:
                log.warning('Cons3rtApiError: There was a problem disabling remote access for VR ID: {i}\n{e}'.format(
                    i=str(vr_id), e=str(exc)))
                log.info('Retrying in {t} sec...'.format(t=str(retry_time_sec)))
                disable_try_num += 1
                time.sleep(retry_time_sec)
                continue
            break

        # Wait for the virtualization realm remote access to report itself disabled
        check_max_retries = 12
        check_try_num = 1
        while True:
            # Raise exception if the VR RA did not become disabled
            if check_try_num > check_max_retries:
                raise Cons3rtApiError('VR ID [{i}] remote access did not become disabled after {n} seconds'.format(
                    i=str(vr_id), n=str(check_max_retries * retry_time_sec)))

            # Query the VR
            try:
                vr_details = self.get_virtualization_realm_details(vr_id=vr_id)
            except Cons3rtApiError as exc:
                log.warning('Cons3rtApiError: Unable to query VR details to determine remote access status\n{e}'.format(
                    e=str(exc)))
            else:
                try:
                    ra_status = vr_details['remoteAccessStatus']
                except KeyError:
                    log.warning('Remote access status not found in VR details: {d}'.format(d=str(vr_details)))
                else:
                    if ra_status == 'DISABLED':
                        log.info('Remote access status is DISABLED for VR ID: {i}'.format(i=str(vr_id)))
                        break
                    else:
                        log.info('Found remote access status for VR ID {i}: {s}'.format(
                            i=str(vr_id), s=ra_status))
            check_try_num += 1
            time.sleep(retry_time_sec)

        # Attempt to enable RA with the specified size
        log.info('Attempting to enable remote access in cloudspace ID [{i}] with size: {s}'.format(
            i=str(vr_id), s=size))
        max_enable_retries = 12
        enable_try_num = 1
        while True:
            if enable_try_num > max_enable_retries:
                raise Cons3rtApiError(
                    'Unable to enable remote access in virtualization realm ID [{i}] after {m} attempts'.format(
                        i=str(vr_id), m=str(max_enable_retries)))
            log.info('Attempting to enable remote access, attempt [{n}] of [{m}]'.format(
                n=str(enable_try_num), m=str(max_enable_retries)))
            try:
                self.enable_remote_access(vr_id=vr_id, size=size)
            except Cons3rtApi:
                log.warning('Cons3rtApiError: There was a problem enabling remote access, could not complete the '
                            'remote access enable for cloudspace id [{i}] with size: {s}'.format(i=str(vr_id), s=size))
                log.info('Retrying in {t} sec...'.format(t=str(retry_time_sec)))
                enable_try_num += 1
                time.sleep(retry_time_sec)
                continue
            break
        log.info('Remote access toggle complete for VR ID: {i}'.format(i=str(vr_id)))

    def retrieve_all_users(self):
        """Retrieve all users from the CONS3RT site

        :return: (list) containing all site users
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.query_all_users')
        log.info('Attempting to query CONS3RT to retrieve all users...')
        try:
            users = self.cons3rt_client.retrieve_all_users()
        except Cons3rtClientError as exc:
            msg = 'There was a problem querying for all users'
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully enabled retrieved all site users')
        return users

    def list_all_users(self):
        """Retrieve all users from the CONS3RT site

        :return: (list) containing all site users
        :raises: Cons3rtApiError
        """
        return self.retrieve_all_users()

    def create_user_from_json(self, json_file):
        """Creates a single CONS3RT user using data from a JSON file

        :param json_file: (str) path to JSON file
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_user_from_json')
        log.info('Attempting to query CONS3RT to create a user from JSON file...')

        # Ensure the json_file arg is a string
        if not isinstance(json_file, str):
            msg = 'The json_file arg must be a string'
            raise ValueError(msg)

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            msg = 'JSON file not found: {f}'.format(f=json_file)
            raise OSError(msg)

        # Attempt to create the team
        try:
            self.cons3rt_client.create_user(user_file=json_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a User using JSON file: {f}'.format(
                f=json_file)
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully created User from file: {f}'.format(f=json_file))

    def add_user_to_project(self, username, project_id):
        """Add the username to the specified project ID

        :param username: (str) CONS3RT username to add to the project
        :param project_id: (int) ID of the project
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.add_user_to_project')

        # Ensure the username arg is a string
        if not isinstance(username, str):
            msg = 'The username arg must be a string'
            raise Cons3rtApiError(msg)

        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Attempt to add the user to the project
        try:
            self.cons3rt_client.add_user_to_project(username=username, project_id=project_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to add username {u} to project ID: {i}'.format(
                u=username, i=str(project_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully added username {u} to project ID: {i}'.format(i=str(project_id), u=username))

    def create_system(
            self,
            name=None,
            operatingSystem=None,
            minNumCpus=2,
            minRam=2000,
            minBootDiskCapacity=100000,
            additionalDisks=None,
            softwareComponents=None,
            subtype='virtualHost',
            vgpuRequired=False,
            physicalMachineId=None,
            json_content=None,
            json_file=None
    ):
        """Creates a system from the provided options

        :param name: (str) system name
        :param operatingSystem: (str) see CONS3RT API docs
        :param minNumCpus: (int) see CONS3RT API docs
        :param minRam: (int) see CONS3RT API docs
        :param minBootDiskCapacity: (int) see CONS3RT API docs
        :param additionalDisks: (list) see CONS3RT API docs
        :param softwareComponents: (list) see CONS3RT API docs
        :param subtype: (str) see CONS3RT API docs
        :param vgpuRequired: (bool) see CONS3RT API docs
        :param physicalMachineId (int) see CONS3RT API docs
        :param json_content (dict) JSON formatted content for the API call, supersedes other params except json_file
        :param json_file: (str) path to JSON file containing all required data, supersedes any other params
        :return: (int) ID of the system
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_system')
        log.debug('Attempting to create a system...')
        content = {}
        if json_file:
            if not os.path.isfile(json_file):
                raise Cons3rtApiError('JSON file not found: {f}'.format(f=json_file))

            try:
                content = json.load(open(json_file))
            except ValueError as exc:
                msg = 'ValueError: Unable to decode JSON from file: {f}'.format(f=json_file)
                raise Cons3rtApiError(msg) from exc

        elif json_content:
            if not isinstance(json_content, dict):
                raise Cons3rtApiError('json_content expected type dict, found: {t}'.format(
                    t=json_content.__class__.__name__))
            content = json_content

        else:
            content['name'] = name
            content['subtype'] = subtype
            if softwareComponents:
                if not isinstance(softwareComponents, list):
                    raise Cons3rtApiError('softwareComponents must be a list, found: {t}'.format(
                        t=softwareComponents.__class__.__name__))
                log.debug('Adding softwareComponents...')
                content['softwareComponents'] = softwareComponents

            if subtype == 'physicalHost':
                log.debug('Creating JSON content from params for a physical host...')

                if not isinstance(physicalMachineId, int):
                    try:
                        physicalMachineId = int(physicalMachineId)
                    except ValueError as exc:
                        raise Cons3rtApiError('physicalMachineId must be an Integer, found: {t}'.format(
                            t=physicalMachineId.__class__.__name__)) from exc

                content['physicalMachine'] = {}
                content['physicalMachine']['id'] = physicalMachineId

            elif subtype == 'virtualHost':
                log.debug('Creating JSON content from params for a virtual host template profile...')
                content['templateProfile'] = {}
                content['templateProfile']['operatingSystem'] = operatingSystem
                content['templateProfile']['minNumCpus'] = minNumCpus
                content['templateProfile']['minRam'] = minRam
                content['templateProfile']['remoteAccessRequired'] = 'true'
                content['templateProfile']['minBootDiskCapacity'] = minBootDiskCapacity
                if vgpuRequired:
                    content['templateProfile']['vgpuRequired'] = 'true'
                else:
                    content['templateProfile']['vgpuRequired'] = 'false'
                if additionalDisks:
                    if not isinstance(additionalDisks, list):
                        raise Cons3rtApiError('additionalDisks must be list, found: {t}'.format(
                            t=additionalDisks.__class__.__name__))
                    content['templateProfile']['additionalDisks'] = additionalDisks

            else:
                raise Cons3rtApiError('subType must be virtualHost or physicalHost, found: {s}'.format(s=subtype))

        log.debug('Attempting to create system with content: {d}'.format(d=content))
        try:
            system_id = self.cons3rt_client.create_system(system_data=content)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a system using contents: {d}'.format(
                d=str(content))
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully created system ID: {i}'.format(i=str(system_id)))
        return system_id

    def create_scenario(self, name=None, scenario_hosts=None, json_content=None, json_file=None):
        """Creates a scenario from the provided data

        :param name: (str) Name of the scenario
        :param scenario_hosts: (list) see CONS3RT API docs
        :param json_content: JSON formatted content for the API call, supersedes other params except json_file
        :param json_file: (str) path to JSON file containing all required data, supersedes any other params
        :return: (int) scenario ID
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_scenario')
        log.debug('Attempting to create a scenario...')
        content = {}
        if json_file:
            if not os.path.isfile(json_file):
                raise Cons3rtApiError('JSON file not found: {f}'.format(f=json_file))

            try:
                content = json.load(open(json_file))
            except ValueError as exc:
                msg = 'ValueError: Unable to decode JSON from file: {f}'.format(f=json_file)
                raise Cons3rtApiError(msg) from exc

        elif json_content:
            if not isinstance(json_content, dict):
                raise Cons3rtApiError('json_content expected type dict, found: {t}'.format(
                    t=json_content.__class__.__name__))
            content = json_content

        else:
            content['name'] = name
            if not isinstance(scenario_hosts, list):
                raise Cons3rtApiError('scenario_hosts expected type list, found: {t}'.format(
                    t=scenario_hosts.__class__.__name__))
            content['scenarioHosts'] = scenario_hosts

        # Attempt to create the team
        try:
            scenario_id = self.cons3rt_client.create_scenario(scenario_data=content)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a scenario using JSON content: {c}'.format(
                c=str(content))
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully created scenario ID: {i}'.format(i=str(scenario_id)))
        return scenario_id

    def create_scenario_from_json(self, json_file):
        """Creates a scenario using data from a JSON file

        :param json_file: (str) path to JSON file
        :return: (int) Scenario ID
        :raises: Cons3rtApiError
        """
        return self.create_scenario(json_file=json_file)

    def create_deployment(
            self,
            name=None,
            custom_properties=None,
            scenario_id=None,
            json_content=None,
            json_file=None
    ):
        """Created a deployment from the provided options

        :param name: (str) deployment name
        :param custom_properties (list) see CONS3RT API docs
        :param scenario_id: (int) ID of the scenario to include
        :param json_content: JSON formatted content for the API call, supersedes other params except json_file
        :param json_file: (str) path to JSON file containing all required data, supersedes any other params
        :return: deployment ID
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_deployment')
        log.debug('Attempting to create a deployment...')
        content = {}
        if json_file:
            if not os.path.isfile(json_file):
                raise Cons3rtApiError('JSON file not found: {f}'.format(f=json_file))

            try:
                content = json.load(open(json_file))
            except ValueError as exc:
                msg = 'ValueError: Unable to decode JSON from file: {f}'.format(f=json_file)
                raise Cons3rtApiError(msg) from exc

        elif json_content:
            if not isinstance(json_content, dict):
                raise Cons3rtApiError('json_content expected type dict, found: {t}'.format(
                    t=json_content.__class__.__name__))
            content = json_content

        else:
            content['name'] = name

            # Add custom props
            if custom_properties:
                if not isinstance(custom_properties, list):
                    raise Cons3rtApiError('custom_properties expected type list, found: {t}'.format(
                        t=custom_properties.__class__.__name__))
                formatted_properties = []
                for custom_prop in custom_properties:
                    formatted_prop = {}
                    if not isinstance(custom_prop, dict):
                        raise Cons3rtApiError('Expected custom prop in dict format, found: {t}'.format(
                            t=custom_prop.__class__.__name__))
                    try:
                        formatted_prop['key'] = custom_prop['key']
                        formatted_prop['value'] = custom_prop['value']
                    except KeyError:
                        raise Cons3rtApiError('Found improperly formatted custom property: {p}'.format(
                            p=custom_prop))
                    formatted_properties.append(formatted_prop)
                content['metadata'] = {'property': formatted_properties}

            if scenario_id:
                if not isinstance(scenario_id, int):
                    try:
                        scenario_id = int(scenario_id)
                    except ValueError as exc:
                        raise Cons3rtApiError('scenario_id must be an Integer, found: {t}'.format(
                            t=scenario_id.__class__.__name__)) from exc
                content['scenarios'] = [
                    {
                        'id': scenario_id
                    }
                ]

        # Create the deployment
        try:
            deployment_id = self.cons3rt_client.create_deployment(deployment_data=content)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a deployment using data: {d}'.format(
                d=str(content))
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully created deployment ID: {i}'.format(i=deployment_id))
        return deployment_id

    def create_deployment_from_json(self, json_file):
        """Creates a deployment using data from a JSON file

        :param json_file: (str) path to JSON file
        :return: (int) Deployment ID
        :raises: Cons3rtApiError
        """
        return self.create_deployment(json_file=json_file)

    def release_deployment_run(self, dr_id):
        """Release a deployment run by ID

        :param: dr_id: (int) deployment run ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.release_deployment_run')

        # Ensure the dr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError as exc:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Attempt to release the DR
        log.debug('Attempting to release deployment run ID: {i}'.format(i=str(dr_id)))
        try:
            result = self.cons3rt_client.release_deployment_run(dr_id=dr_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to release deployment run ID: {i}'.format(
                i=str(dr_id))
            raise Cons3rtApiError(msg) from exc

        if result:
            log.info('Successfully released deployment run ID: {i}'.format(i=str(dr_id)))
        else:
            raise Cons3rtApiError('Unable to release deployment run ID: {i}'.format(i=str(dr_id)))

    def launch_deployment_run_from_json(self, deployment_id, json_file):
        """Launches a deployment run using options provided in a JSON file

        :param deployment_id: (int) ID of the deployment to launch
        :param json_file: (str) path to JSON file containing data for deployment run options
        :return: (int) deployment run ID
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.launch_deployment_run_from_json')

        # Ensure the deployment_id is an int
        if not isinstance(deployment_id, int):
            try:
                deployment_id = int(deployment_id)
            except ValueError as exc:
                raise Cons3rtApiError('deployment_id arg must be an Integer, found: {t}'.format(
                    t=deployment_id.__class__.__name__)) from exc

        # Ensure the json_file arg is a string
        if not isinstance(json_file, str):
            raise Cons3rtApiError('The json_file arg must be a string')

        # Ensure the JSON file exists
        if not os.path.isfile(json_file):
            raise Cons3rtApiError('JSON file not found: {f}'.format(f=json_file))

        try:
            run_options = json.load(open(json_file))
        except ValueError as exc:
            msg = 'ValueError: Unable to decode JSON from file: {f}'.format(f=json_file)
            raise Cons3rtApiError(msg) from exc

        # Attempt to run the deployment
        try:
            dr_id = self.cons3rt_client.run_deployment(deployment_id=deployment_id, run_options=run_options)
        except Cons3rtClientError as exc:
            msg = 'Unable to launch deployment run: {f}'.format(
                f=json_file)
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully launched deployment run ID {i} from file: {f}'.format(i=dr_id, f=json_file))
        return dr_id

    def run_deployment(self, deployment_id, run_options):
        """Launches a deployment using provided data

        :param deployment_id: (int) ID of the deployment to launch
        :param run_options: (dict) data for deployment run options
        :return (int) deployment run ID
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.run_deployment')

        # Ensure the deployment_id is an int
        if not isinstance(deployment_id, int):
            try:
                deployment_id = int(deployment_id)
            except ValueError as exc:
                raise Cons3rtApiError('deployment_id arg must be an Integer, found: {t}'.format(
                    t=deployment_id.__class__.__name__)) from exc

        # Ensure the run_options is a dict
        if not isinstance(run_options, dict):
            raise Cons3rtApiError('run_options arg must be a dict, found: {t}'.format(t=run_options.__class__.__name__))

        # Attempt to run the deployment
        try:
            dr_id = self.cons3rt_client.run_deployment(deployment_id=deployment_id, run_options=run_options)
        except Cons3rtClientError as exc:
            msg = 'Unable to launch deployment run ID: {i}'.format(
                i=str(deployment_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully launched deployment ID {d} as deployment run ID: {i}'.format(
            i=str(dr_id), d=str(deployment_id)))
        return dr_id

    def delete_inactive_runs_in_virtualization_realm(self, vr_id):
        """Deletes all inactive runs in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.delete_inactive_runs_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # List runs in the virtualization realm
        try:
            drs = self.list_deployment_runs_in_virtualization_realm(vr_id=vr_id, search_type='SEARCH_INACTIVE')
        except Cons3rtApiError as exc:
            msg = 'Cons3rtApiError: There was a problem listing inactive deployment runs in VR ID: {i}'.format(
                i=str(vr_id))
            raise Cons3rtApiError(msg) from exc

        # Delete each inactive run
        log.debug('Found inactive runs in VR ID {i}:\n{r}'.format(i=str(vr_id), r=str(drs)))
        log.info('Attempting to delete inactive runs from VR ID: {i}'.format(i=str(vr_id)))
        for dr in drs:
            try:
                dr_id = dr['id']
            except KeyError:
                log.warning('Unable to determine the run ID from run: {r}'.format(r=str(dr)))
                continue
            try:
                self.delete_inactive_run(dr_id=dr_id)
            except Cons3rtApiError as exc:
                log.warning('Cons3rtApiError: Unable to delete run ID: {i}\n{e}'.format(i=str(dr_id), e=str(exc)))
                continue
        log.info('Completed deleting inactive DRs in VR ID: {i}'.format(i=str(vr_id)))

    def release_active_runs_in_virtualization_realm(self, vr_id):
        """Releases all active runs in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.release_active_runs_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # List active runs in the virtualization realm
        try:
            drs = self.list_deployment_runs_in_virtualization_realm(vr_id=vr_id, search_type='SEARCH_ACTIVE')
        except Cons3rtApiError as exc:
            msg = 'Cons3rtApiError: There was a problem listing active deployment runs in VR ID: {i}'.format(
                i=str(vr_id))
            raise Cons3rtApiError(msg) from exc

        # Release or cancel each active run
        log.debug('Found active runs in VR ID {i}:\n{r}'.format(i=str(vr_id), r=str(drs)))
        log.info('Attempting to release or cancel active runs from VR ID: {i}'.format(i=str(vr_id)))
        for dr in drs:
            try:
                dr_id = dr['id']
            except KeyError:
                log.warning('Unable to determine the run ID from run: {r}'.format(r=str(dr)))
                continue
            try:
                self.release_deployment_run(dr_id=dr_id)
            except Cons3rtApiError as exc:
                log.warning('Cons3rtApiError: Unable to release or cancel run ID: {i}\n{e}'.format(
                    i=str(dr_id), e=str(exc)))
                continue
        log.info('Completed releasing or cancelling active DRs in VR ID: {i}'.format(i=str(vr_id)))

    def list_networks_in_virtualization_realm(self, vr_id):
        """Lists all networks in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: list of networks (see API docs)
        """
        log = logging.getLogger(self.cls_logger + '.list_networks_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # List networks in the virtualization realm
        try:
            networks = self.cons3rt_client.list_networks_in_virtualization_realm(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Cons3rtApiError: There was a problem listing networks in VR ID: {i}'.format(
                i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        log.debug('Found networks in VR ID {v}: {n}'.format(v=str(vr_id), n=networks))
        return networks

    def list_templates_in_virtualization_realm(self, vr_id):
        """Lists all templates in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: list of templates (see API docs)
        """
        log = logging.getLogger(self.cls_logger + '.list_templates_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # List templates in the virtualization realm
        try:
            templates = self.cons3rt_client.list_templates_in_virtualization_realm(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Cons3rtApiError: There was a problem listing templates in VR ID: {i}'.format(
                i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        log.debug('Found templates in VR ID {v}: {t}'.format(v=str(vr_id), t=templates))
        return templates

    def get_primary_network_in_virtualization_realm(self, vr_id):
        """Returns a dict of info about the primary network in a virtualization realm

        :return: (dict) primary network info (see API docs)
        """
        log = logging.getLogger(self.cls_logger + '.get_primary_network_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Get a list of all networks in the virtualization realm
        try:
            networks = self.list_networks_in_virtualization_realm(vr_id=vr_id)
        except Cons3rtApiError:
            raise
        log.debug('Found networks in VR ID {v}: {n}'.format(v=str(vr_id), n=networks))

        # Determine the primary networks
        primary_network = None
        for network in networks:
            try:
                primary = network['primary']
            except KeyError:
                continue
            if not isinstance(primary, bool):
                raise Cons3rtApiError('Expected primary to be a bool, found: {t}'.format(
                    t=primary.__class__.__name__))
            if primary:
                primary_network = network
                break

        log.debug('Found primary network with info: {n}'.format(n=primary_network))
        return primary_network

    def delete_inactive_run(self, dr_id):
        """Deletes an inactive run

        :param dr_id: (int) deployment run ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.delete_inactive_run')

        # Ensure the vr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError as exc:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.debug('Attempting to delete run ID: {i}'.format(i=str(dr_id)))
        try:
            self.cons3rt_client.delete_deployment_run(dr_id=dr_id)
        except Cons3rtClientError as exc:
            msg = 'Cons3rtClientError: There was a problem deleting run ID: {i}'.format(i=str(dr_id))
            raise Cons3rtApiError(msg) from exc
        else:
            log.info('Successfully deleted run ID: {i}'.format(i=str(dr_id)))

    def get_virtualization_realm_details(self, vr_id):
        """Queries for details of the virtualization realm ID

        :param vr_id: (int) VR ID
        :return: (dict) VR details
        """
        log = logging.getLogger(self.cls_logger + '.get_virtualization_realm_details')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Query for VR details
        log.debug('Attempting query virtualization realm ID {i}'.format(i=str(vr_id)))
        try:
            vr_details = self.cons3rt_client.get_virtualization_realm_details(vr_id=vr_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for details on virtualization realm: {i}'.format(
                i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        return vr_details

    def set_deployment_run_lock(self, dr_id, lock):
        """Sets the run lock on the DR ID

        :param dr_id: (int) deployment run ID
        :param lock: (bool) true to set run lock, false to disable
        :return: (bool) result
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.set_deployment_run_lock')

        # Ensure the dr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError as exc:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure lock is a bool
        if not isinstance(lock, bool):
            raise Cons3rtApiError('lock arg must be an bool, found: {t}'.format(t=dr_id.__class__.__name__))

        # Lock the run
        log.info('Attempting set lock on deployment run ID [{i}] to: {b}'.format(i=str(dr_id), b=str(lock)))
        try:
            result = self.cons3rt_client.set_deployment_run_lock(dr_id=dr_id, lock=lock)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a details of deployment run ID: {i}'.format(
                i=str(dr_id))
            raise Cons3rtApiError(msg) from exc
        return result
