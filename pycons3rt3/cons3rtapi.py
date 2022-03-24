#!/usr/bin/env python

import datetime
import json
import logging
import os
import time
import traceback

from .logify import Logify

from .cloud import Cloud
from .cons3rtclient import Cons3rtClient
from .deployment import Deployment
from .pycons3rtlibs import HostActionResult, RestUser
from .cons3rtconfig import cons3rtapi_config_file, get_pycons3rt_conf_dir, site_urls
from .exceptions import Cons3rtClientError, Cons3rtApiError, DeploymentError, InvalidCloudError, \
    InvalidOperatingSystemTemplate
from .ostemplates import OperatingSystemTemplate, OperatingSystemType


# Set up logger name for this module
mod_logger = Logify.get_name() + '.cons3rtapi'


class Cons3rtApi(object):

    def __init__(self, rest_user=None, config_file=None, url=None, username=None, project=None, api_token=None,
                 cert_path=None, root_ca_bundle_path=None):
        self.cls_logger = mod_logger + '.Cons3rtApi'
        self.rest_user = rest_user
        self.config_file = config_file
        self.url_base = url
        self.username = username
        self.project = project
        self.api_token = api_token
        self.cert_path = cert_path
        if root_ca_bundle_path:
            self.root_ca_bundle_path = root_ca_bundle_path
        else:
            self.root_ca_bundle_path = True
        self.retries = ''
        self.timeout = ''
        self.queries = ''
        self.virtrealm = ''
        self.rest_user_list = []
        self.load_config()
        self.cons3rt_client = Cons3rtClient(user=self.rest_user)

    def load_config(self):
        """Load config data from args, environment vars, or config files

        :return: None
        :raises: Cons3rtApiError
        """
        # First use a RestUser object if provided directly
        if self.rest_user:
            if isinstance(self.rest_user, RestUser):
                self.rest_user_list.append(self.rest_user)
                return

        # 2nd, if a config file was specified, use that
        if self.config_file:
            if self.load_config_file():
                return

        # 3rd, use args provided to create a RestUser
        if self.load_config_args():
            return

        # 4th, use environment variables if set
        if self.load_config_env_vars():
            return

        # Lastly, check the default config file location
        self.config_file = cons3rtapi_config_file
        if self.load_config_file():
            return

        raise Cons3rtApiError('Unable to load configuration data')

    def load_config_args(self):
        """Attempts to load configuration from provided args

        :return: True if successful, False otherwise
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.load_config_args')

        # Check for username-based args
        if all([self.url_base, self.username, self.project, self.api_token]):
            self.load_config_root_ca_bundle()
            log.info('Loading config: URL: [{u}], username: [{n}], project: [{p}], cert validation: [{v}]'.format(
                u=self.url_base, n=self.username, p=self.project, v=str(self.root_ca_bundle_path)))
            self.rest_user_list.append(RestUser(
                rest_api_url=self.url_base,
                token=self.api_token,
                project=self.project,
                username=self.username,
                cert_bundle=self.root_ca_bundle_path
            ))
            self.rest_user = self.rest_user_list[0]
            return True
        elif all([self.url_base, self.cert_path, self.project, self.api_token]):
            self.load_config_root_ca_bundle()
            log.info('Loading config: URL: [{u}], client cert: [{c}], project: [{p}], cert validation: [{v}]'.format(
                u=self.url_base, c=self.cert_path, p=self.project, v=str(self.root_ca_bundle_path)))
            self.rest_user_list.append(RestUser(
                rest_api_url=self.url_base,
                token=self.api_token,
                project=self.project,
                cert_file_path=self.cert_path,
                cert_bundle=self.root_ca_bundle_path
            ))
            self.rest_user = self.rest_user_list[0]
            return True
        return False

    def load_config_env_vars(self):
        """Attempts to load configuration from environment variables:

        CONS3RT_USER
        CONS3RT_PROJECT
        CONS3RT_ENDPOINT
        CONS3RT_API_TOKEN
        CONS3RT_CLIENT_CERT
        CONS3RT_ROOT_CA_BUNDLE

        :return: True if successful, False otherwise
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.load_config_env_vars')

        # Check for environment vars, and convert to args when found
        if 'CONS3RT_ROOT_CA_BUNDLE' in os.environ.keys():
            self.root_ca_bundle_path = os.environ['CONS3RT_ROOT_CA_BUNDLE']
            log.info('Found environment variable CONS3RT_ROOT_CA_BUNDLE: {v}'.format(v=self.root_ca_bundle_path))
        if 'CONS3RT_USER' in os.environ.keys():
            self.username = os.environ['CONS3RT_USER']
            log.info('Found environment variable CONS3RT_USER: {v}'.format(v=self.username))
        if 'CONS3RT_PROJECT' in os.environ.keys():
            self.project = os.environ['CONS3RT_PROJECT']
            log.info('Found environment variable CONS3RT_PROJECT: {v}'.format(v=self.project))
        if 'CONS3RT_ENDPOINT' in os.environ.keys():
            self.url_base = os.environ['CONS3RT_ENDPOINT']
            log.info('Found environment variable CONS3RT_ENDPOINT: {v}'.format(v=self.url_base))
        if 'CONS3RT_API_TOKEN' in os.environ.keys():
            self.api_token = os.environ['CONS3RT_API_TOKEN']
            log.info('Found environment variable CONS3RT_API_TOKEN: {v}'.format(v=self.api_token))
        if 'CONS3RT_CLIENT_CERT' in os.environ.keys():
            self.cert_path = os.environ['CONS3RT_CLIENT_CERT']
            log.info('Found environment variable CONS3RT_CLIENT_CERT: {v}'.format(v=self.cert_path))
        return self.load_config_args()

    def load_site_config_data(self, config_data):
        """Loads config data for a site

        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.load_site_config_data')

        # Attempt to load the URL
        try:
            url_base = config_data['api_url']
        except KeyError:
            raise Cons3rtApiError('api_url not defined in config data: {d}'.format(d=str(config_data)))
        log.info('Using ReST API URL: {u}'.format(u=url_base))

        # Attempt to find a username in the config data
        try:
            username = config_data['name']
        except KeyError:
            username = None
        else:
            log.info('Running as CONS3RT username: {n}'.format(n=username))

        # Attempt to find a cert_file_path in the config data
        try:
            cert_file_path = config_data['cert']
        except KeyError:
            cert_file_path = None
        else:
            # Ensure the cert_file_path points to an actual file
            if not os.path.isfile(cert_file_path):
                cert_file_path = os.path.join(get_pycons3rt_conf_dir(), cert_file_path)
                if not os.path.isfile(cert_file_path):
                    raise Cons3rtApiError('config.json provided a cert, but the cert file was not found: {f}'.format(
                        f=cert_file_path))
                log.info('Using client certificate file: {f}'.format(f=cert_file_path))

        # Check for root CA certificate bundle path
        if 'root_ca_bundle' in config_data.keys():
            self.root_ca_bundle_path = config_data['root_ca_bundle']
        self.load_config_root_ca_bundle()

        # Ensure that either a username or cert_file_path was found
        if username is None and cert_file_path is None:
            raise Cons3rtApiError('The config data must contain values for either: name or cert: {d}'.format(
                d=str(config_data)))

        # Ensure at least one token is found
        try:
            project_token_list = config_data['projects']
        except KeyError:
            msg = '[projects] not found in the config file, at least 1 project must be provided'
            raise Cons3rtApiError(msg)

        # Attempt to create a ReST user for each project in the list
        for project in project_token_list:
            try:
                token = project['rest_key']
                project_name = project['name']
            except KeyError:
                log.warning('Found an invalid project token, skipping: {p}'.format(p=str(project)))
                continue

            # Create a cert-based auth or username-based auth user depending on the config
            if cert_file_path:
                self.rest_user_list.append(RestUser(
                    rest_api_url=url_base,
                    token=token,
                    project=project_name,
                    cert_file_path=cert_file_path,
                    cert_bundle=self.root_ca_bundle_path
                ))
            elif username:
                self.rest_user_list.append(RestUser(
                    rest_api_url=url_base,
                    token=token,
                    project=project_name,
                    username=username,
                    cert_bundle=self.root_ca_bundle_path
                ))

    def load_config_file(self):
        """Loads either the specified config file or the default config file

        :return: True if successful, False otherwise
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.load_config_file')

        # Ensure the file_path file exists
        if not os.path.isfile(self.config_file):
            raise Cons3rtApiError('Config file not found: {f}'.format(f=self.config_file))

        # Load the config file
        try:
            with open(self.config_file, 'r') as f:
                config_data = json.load(f)
        except(OSError, IOError) as exc:
            raise Cons3rtApiError('Unable to read config file: {f}'.format(f=self.config_file)) from exc
        log.info('Loading config from file: {f}'.format(f=self.config_file))

        # Check for multi-site configuration
        try:
            if 'sites' in config_data.keys():
                for site_config_data in config_data['sites']:
                    self.load_site_config_data(config_data=site_config_data)
            else:
                self.load_site_config_data(config_data=config_data)
        except Cons3rtApiError as exc:
            msg = 'Problem loading configuration from file: {f}'.format(f=self.config_file)
            raise Cons3rtApiError(msg) from exc

        # Ensure that at least one valid project/token was found
        if len(self.rest_user_list) < 1:
            raise Cons3rtApiError('A ReST API token was not found in config file: {f}'.format(f=self.config_file))

        log.info('Found {n} project/token pairs'.format(n=str(len(self.rest_user_list))))

        # Select the first user to use as the default
        self.rest_user = self.rest_user_list[0]
        if self.project:
            self.set_project_token(project_name=self.project)
        log.info('Using ReST API token for project: {p}'.format(p=self.rest_user.project_name))
        return True

    def load_config_root_ca_bundle(self):
        """Handles the root CA bundle config item

        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.load_config_root_ca_bundle')

        # Process root CA bundle if it is a string
        if isinstance(self.root_ca_bundle_path, str):
            if self.root_ca_bundle_path.lower() == 'false':
                self.root_ca_bundle_path = False
            elif self.root_ca_bundle_path.lower() == 'true':
                self.root_ca_bundle_path = True
            else:
                # Ensure the root_ca_bundle points to an actual file
                if not os.path.isfile(self.root_ca_bundle_path):
                    msg = 'root_ca_bundle specified in the config file was not found: {f}'.format(
                        f=self.root_ca_bundle_path)
                    raise Cons3rtApiError(msg)
                log.info('Found root CA certificate bundle: {f}'.format(f=self.root_ca_bundle_path))
        elif isinstance(self.root_ca_bundle_path, bool):
            pass
        else:
            msg = 'Expected root_ca_bundle_path to be bool or str, found: {t}'.format(t=__class__.__name__)
            raise Cons3rtApiError(msg)
        if isinstance(self.root_ca_bundle_path, bool):
            if self.root_ca_bundle_path:
                log.info('Using the built-in root certificates for server-side SSL verification')
            else:
                log.warning('WARNING: Config for root_ca_bundle_path set to False, will not verify SSL connections')

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
        for rest_user in self.rest_user_list:
            log.debug('Checking if rest user matches project [{p}]: {u}'.format(p=project_name, u=str(rest_user)))
            if rest_user.project_name == project_name:
                log.info('Found matching rest user: {u}'.format(u=str(rest_user)))
                self.rest_user = rest_user
                self.cons3rt_client = Cons3rtClient(user=self.rest_user)
                found = True
                break
        if found:
            log.info('Set project to [{p}] and ReST API token: {t}'.format(p=self.rest_user.project_name,
                                                                           t=self.rest_user.token))
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
        elif 'container' in asset_type.lower():
            target = 'containers'
        else:
            log.warning('Unable to determine the target from provided asset_type: {t}'.format(t=asset_type))
        return target

    def get_dependent_assets(self, asset_id):
        """Returns o list of asset dependent on the provided asset ID

        :param asset_id: (int) asset ID
        :return: (list) of dependent assets (dict)
        """
        log = logging.getLogger(self.cls_logger + '.get_dependent_assets')
        # Ensure the asset_id is an int
        if not isinstance(asset_id, int):
            try:
                asset_id = int(asset_id)
            except ValueError as exc:
                msg = 'asset_id arg must be an Integer, found: {t}'.format(t=asset_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Attempt to delete the target
        try:
            dependent_assets = self.cons3rt_client.get_dependent_assets(asset_id=asset_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to list dependent assets for asset ID: {i}'.format(i=str(asset_id))
            raise Cons3rtApiError(msg) from exc
        if dependent_assets == '[null]':
            msg = 'Dependent assets did not return properly, this could be an odd asset type that no longer exists'
            raise Cons3rtApiError(msg)
        log.info('Found {n} dependent assets for asset ID: {i}'.format(n=str(len(dependent_assets)), i=str(asset_id)))
        return dependent_assets

    def create_cloud(self, cloud_ato_consent=False, **kwargs):
        """Creates a new cloud

        Cloud Authority To Operate (ATO) Consent.

        Teams are allowed to register their own Clouds and to use the site capabilities to allocate Cloudspaces,
        configure security, and deploy Systems & Services and/or access them remotely. However, without a Memorandum
        of Understanding (MOU) or Memorandum of Agreement (MOA) with the site owner, customer-owned Clouds and
        Cloudspaces are not covered by the site Authority To Operate (ATO). Customers are responsible for compliance
        with all DoD security requirements for protecting and maintaining their systems.

        > Note: Does not handle at this time:
          * cloud network templates
          * templateVirtualizationRealm

        :param cloud_ato_consent: (bool) By setting true, the user acknowledges that - as a Team Manager - they
                a) are authorized to represent their organization, and
                b) they understand that their organization is responsible for all security and authorization to
                operate requirements for Systems deployed in their Cloudspaces.

        :return: (int) cloud ID
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_cloud')

        try:
            cloud = Cloud(**kwargs)
        except InvalidCloudError as exc:
            raise Cons3rtApiError('Invalid cloud data provided') from exc

        # Attempt to register the Cloud
        try:
            cloud_id = self.cons3rt_client.create_cloud(
                cloud_ato_consent=cloud_ato_consent,
                cloud_data=cloud.cloud_data
            )
        except Cons3rtClientError as exc:
            raise Cons3rtApiError('Problem creating cloud named {n} using cloud_ato_consent={c} and data: {d}'.format(
                n=cloud.cloud_data['name'], c=str(cloud_ato_consent), d=str(cloud.cloud_data))) from exc
        log.info('Created cloud [{n}] ID: {c}'.format(n=cloud.cloud_data['name'], c=str(cloud_id)))
        return cloud_id

    def update_cloud(self, cloud_id, **kwargs):
        """Updates the provided cloud ID

        :param cloud_id: (int) cloud ID
        :return: bool
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.update_cloud')

        try:
            cloud = Cloud(**kwargs)
        except InvalidCloudError as exc:
            raise Cons3rtApiError('Invalid cloud data provided') from exc

        # Attempt to register the Cloud
        try:
            result = self.cons3rt_client.update_cloud(
                cloud_id=cloud_id,
                cloud_data=cloud.cloud_data
            )
        except Cons3rtClientError as exc:
            raise Cons3rtApiError('Problem updating cloud ID {i} named {n} with data: {d}'.format(
                n=cloud.cloud_data['name'], i=str(cloud_id), d=str(cloud.cloud_data))) from exc
        log.info('Updated cloud [{n}] ID: {c}'.format(n=cloud.cloud_data['name'], c=str(cloud_id)))
        return result

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

    def delete_cloud(self, cloud_id):
        """Deletes the provided cloud ID

        :param cloud_id: (int) cloud ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.delete_cloud')

        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError as exc:
                msg = 'cloud_id arg must be an Integer, found: {t}'.format(t=cloud_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Attempt to delete the target
        try:
            self.cons3rt_client.delete_cloud(cloud_id=cloud_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to delete cloud ID: {i}'.format(i=str(cloud_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Deleted cloud ID: {i}'.format(i=str(cloud_id)))

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
                u=self.rest_user.username, p=str(page_num), m=str(max_results)))
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

    def list_project_members(self, project_id, state=None, role=None, username=None):
        """Returns a list of members in a project based on the provided query parameters

        :param project_id: (int) ID of the project
        :param state: (str) membership state "REQUESTED" "ACTIVE" "BLOCKED" "DELETED"
        :param role: (str) membership role "ADMINISTRATOR" "ASSET_RESTORER" "STATUS_READER" "UI_MACHINE" "TEST_TOOL"
            "MEMBER" "CONSUMER" "STANDARD" "SOFTWARE_DEVELOPER" "TEST_DEVELOPER" "ASSET_SHARER" "ASSET_PROMOTER"
            "POWER_SCHEDULE_UPDATER" "PROJECT_OWNER" "PROJECT_MANAGER" "PROJECT_MODERATOR" "REMOTE_ACCESS"
            "MAESTRO_MACHINE" "FAP_MACHINE" "SCHEDULER_MACHINE" "CONS3RT_MACHINE" "SOURCEBUILDER_MACHINE"
            "SYSTEM_ASSET_IMPORTER" "ASSET_CERTIFIER" "ASSET_UPLOADER"
        :param username: (str) username to search for
        :return: (list) of projects
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_project_members')
        
        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc
        
        valid_states = ['REQUESTED', 'ACTIVE', 'BLOCKED', 'DELETED']
        valid_roles = ['ADMINISTRATOR', 'ASSET_RESTORER', 'STATUS_READER', 'UI_MACHINE', 'TEST_TOOL', 'MEMBER',
                       'CONSUMER', 'STANDARD', 'SOFTWARE_DEVELOPER', 'TEST_DEVELOPER', 'ASSET_SHARER', 'ASSET_PROMOTER',
                       'POWER_SCHEDULE_UPDATER', 'PROJECT_OWNER', 'PROJECT_MANAGER', 'PROJECT_MODERATOR',
                       'REMOTE_ACCESS', 'MAESTRO_MACHINE', 'FAP_MACHINE', 'SCHEDULER_MACHINE', 'CONS3RT_MACHINE',
                       'SOURCEBUILDER_MACHINE', 'SYSTEM_ASSET_IMPORTER', 'ASSET_CERTIFIER', 'ASSET_UPLOADER']
        
        # Ensure the args are valid
        if state:
            if not isinstance(state, str):
                msg = 'state arg must be a string, received: {t}'.format(t=state.__class__.__name__)
                raise Cons3rtApiError(msg)
            if state not in valid_states:
                msg = 'state [{s}] invalid, must be one of: {v}'.format(s=state, v=','.join(valid_states))
                raise Cons3rtApiError(msg)
        if role:
            if not isinstance(role, str):
                msg = 'role arg must be a string, received: {t}'.format(t=role.__class__.__name__)
                raise Cons3rtApiError(msg)
            if role not in valid_roles:
                msg = 'role [{r}] invalid, must be one of: {v}'.format(r=role, v=','.join(valid_roles))
                raise Cons3rtApiError(msg)
        if username:
            if not isinstance(username, str):
                msg = 'username arg must be a string, received: {t}'.format(t=username.__class__.__name__)
                raise Cons3rtApiError(msg)

        info_msg = 'project [{i}]'.format(i=str(project_id))
        if state:
            info_msg += ', membership state [{s}]'.format(s=state)
        if role:
            info_msg += ', project role [{r}]'.format(r=role)
        if username:
            info_msg += ', username [{n}]'.format(n=username)
        log.info('Searching for members: {i}'.format(i=info_msg))
        try:
            project_members = self.cons3rt_client.list_all_project_members(
                project_id=project_id,
                state=state,
                role=role,
                username=username
            )
        except Cons3rtClientError as exc:
            msg = 'Problem listing members in project: {i}'.format(i=info_msg)
            raise Cons3rtApiError(msg) from exc
        return project_members

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
                u=self.rest_user.username, p=str(page_num), m=str(max_results)))
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

        # Ensure the project_id is an int
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

    def remove_all_projects_in_virtualization_realm(self, vr_id):
        """Queries CONS3RT for a list of projects in the virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: (list) of projects removed from the VR
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.remove_all_projects_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Get a list of all the projects in the virtualization realm
        vr_projects = self.list_projects_in_virtualization_realm(vr_id=vr_id)
        for vr_project in vr_projects:
            self.remove_project_from_virtualization_realm(project_id=vr_project['id'], vr_id=vr_id)
        log.info('Completed removing all projects from VR ID: {i}'.format(i=str(vr_id)))

    def remove_project_from_virtualization_realm(self, project_id, vr_id):
        """Removes the project ID from the virtualization realm ID

        :param project_id: (int) project ID
        :param vr_id: (int) virtualization realm ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.remove_project_from_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.info('Removing project ID {p} from VR ID: {v}'.format(p=str(project_id), v=str(vr_id)))
        try:
            self.cons3rt_client.remove_project_from_virtualization_realm(vr_id=vr_id, project_id=project_id)
        except Cons3rtClientError as exc:
            msg = 'Problem removing project IF {p} from VR ID: {v}'.format(p=str(project_id), v=str(vr_id))
            raise Cons3rtApiError(msg) from exc

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

    def retrieve_cloud_details(self, cloud_id):
        """Returns details for the provided cloud ID

        :param cloud_id: (int) Cloud ID
        :return: (dict)
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_cloud_details')

        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError as exc:
                msg = 'cloud_id arg must be an Integer, found: {t}'.format(t=cloud_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.debug('Attempting query cloud ID {i}'.format(i=str(cloud_id)))
        try:
            cloud_details = self.cons3rt_client.retrieve_cloud_details(cloud_id=cloud_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for details on cloud ID: {i}'.format(i=str(cloud_id))
            raise Cons3rtApiError(msg) from exc
        return cloud_details

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

    def list_projects_in_team(self, team_id):
        """Returns a list of project IDs

        :param team_id: (int) ID of the team
        :return: (list) of dict containing owned project data
        """
        log = logging.getLogger(self.cls_logger + '.list_projects_in_team')

        # Ensure the team_id is an int
        if not isinstance(team_id, int):
            try:
                team_id = int(team_id)
            except ValueError as exc:
                msg = 'team_id arg must be an Integer, found: {t}'.format(t=team_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Get team details
        log.info('Getting details for team ID: {i}'.format(i=str(team_id)))
        try:
            team_details = self.get_team_details(team_id=team_id)
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem getting details for team ID: {i}'.format(i=str(team_id))) from exc

        # Get the team name
        team_name = 'unknown'
        if 'name' not in team_details:
            log.warning('name not found in team details')
        else:
            team_name = team_details['name']

        # Get the owned projects, return empty list if not provided
        owned_projects = []
        if 'ownedProjects' not in team_details:
            log.info('No owned projects found in team [{n}] with ID: {i}'.format(n=team_name, i=str(team_id)))
            return owned_projects

        # Ensure owned_projects is a list
        if not isinstance(team_details['ownedProjects'], list):
            raise Cons3rtApiError('ownedProjects expected to be a list, found: {t}'.format(
                t=team_details['ownedProjects'].__class__.__name__))

        for owned_project in team_details['ownedProjects']:
            if 'id' not in owned_project:
                log.warning('id not found in owned project: {p}'.format(p=str(owned_project)))
                continue
            if 'name' not in owned_project:
                log.warning('name not found in owned project: {p}'.format(p=str(owned_project)))
                continue
            log.info('Found owned project [{n}] with ID: {i}'.format(
                n=owned_project['name'], i=str(owned_project['id'])))
            owned_projects.append(owned_project)
        log.info('Found {n} projects owned by team [{t}] with ID: {i}'.format(
            n=str(len(owned_projects)), t=team_name, i=str(team_id)))
        return owned_projects

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

    def list_system_designs(self):
        """Query CONS3RT to return a list of system designs

        :return: (list) of system designs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_system_designs')
        log.info('Attempting to get a list of system designs...')
        try:
            scenarios = self.cons3rt_client.list_all_system_designs()
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a list of system designs'
            raise Cons3rtApiError(msg) from exc
        return scenarios

    def list_scenarios(self):
        """Query CONS3RT to return a list of all scenarios

        :return: (list) of Scenario Info
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_scenarios')
        log.info('Attempting to get a list of scenarios...')
        try:
            scenarios = self.cons3rt_client.list_all_scenarios()
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

    def list_deployment_runs_for_deployment(self, deployment_id):
        """Query CONS3RT to return a list of deployment runs for a deployment

        :param: deployment_id: (int) deployment ID
        :returns: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_deployment_runs_for_deployment')

        # Ensure the deployment_id is an int
        if not isinstance(deployment_id, int):
            try:
                deployment_id = int(deployment_id)
            except ValueError as exc:
                msg = 'deployment_id arg must be an Integer, found: {t}'.format(t=deployment_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        try:
            drs = self.cons3rt_client.list_all_deployment_runs_for_deployment(deployment_id=deployment_id)
        except Cons3rtClientError as exc:
            msg = 'Problem listing runs for deployment ID: {i}'.format(i=str(deployment_id))
            raise Cons3rtClientError(msg) from exc
        log.info('Found {n} runs for deployment ID: {i}'.format(n=str(len(drs)), i=str(deployment_id)))
        return drs

    def get_active_run_id_from_deployment(self, deployment_id):
        """Given a deployment ID, determine its active run ID

        :param: deployment_id: (int) deployment ID
        :returns: (int) run ID or None if no active run exists
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.get_active_run_id_from_deployment')

        # Ensure the deployment_id is an int
        if not isinstance(deployment_id, int):
            try:
                deployment_id = int(deployment_id)
            except ValueError as exc:
                msg = 'deployment_id arg must be an Integer, found: {t}'.format(t=deployment_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        try:
            drs = self.list_deployment_runs_for_deployment(deployment_id=deployment_id)
        except Cons3rtClientError as exc:
            msg = 'Problem listing runs for deployment ID: {i}'.format(i=str(deployment_id))
            raise Cons3rtClientError(msg) from exc

        # Check for a DR with an active status
        active_statii = ['SUBMITTED', 'PROVISIONING_HOSTS', 'HOSTS_PROVISIONED', 'RESERVED', 'TESTING', 'TESTED']

        for dr in drs:
            if 'deploymentRunStatus' in dr:
                if dr['deploymentRunStatus'] in active_statii:
                    log.info('Found a DR with an active status: {i}'.format(i=str(dr['id'])))
                    return dr['id']
        log.info('No active DR found for deployment ID: {i}'.format(i=str(deployment_id)))
        return

    def list_inactive_run_ids_for_deployment(self, deployment_id):
        """Given a deployment ID, return a list of inactive deployment run IDs

        :param: deployment_id: (int) deployment ID
        :returns: (list) of inactive deployment runs or None if no inactive runs exist
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_inactive_run_ids_for_deployment')

        # Ensure the deployment_id is an int
        if not isinstance(deployment_id, int):
            try:
                deployment_id = int(deployment_id)
            except ValueError as exc:
                msg = 'deployment_id arg must be an Integer, found: {t}'.format(t=deployment_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        try:
            drs = self.list_deployment_runs_for_deployment(deployment_id=deployment_id)
        except Cons3rtClientError as exc:
            msg = 'Problem listing runs for deployment ID: {i}'.format(i=str(deployment_id))
            raise Cons3rtClientError(msg) from exc

        # Check for a DR with an active status
        active_statii = ['SUBMITTED', 'PROVISIONING_HOSTS', 'HOSTS_PROVISIONED', 'RESERVED', 'TESTING', 'TESTED']

        inactive_drs = []
        for dr in drs:
            if 'deploymentRunStatus' in dr:
                if dr['deploymentRunStatus'] not in active_statii:
                    log.info('Found a DR with an inactive status: {i}'.format(i=str(dr['id'])))
                    inactive_drs.append(dr)
        log.info('Found {n} inactive DRs found for deployment ID: {i}'.format(
            n=str(len(inactive_drs)), i=str(deployment_id)))
        return inactive_drs

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
        try:
            drs = self.cons3rt_client.list_all_deployment_runs_in_virtualization_realm(
                vr_id=vr_id,
                search_type=search_type
            )
        except Cons3rtClientError as exc:
            msg = 'Problem listing runs in virtualization realm ID: {i} with search type {t}'.format(
                i=str(vr_id), t=search_type)
            raise Cons3rtClientError(msg) from exc
        log.info('Found {n} runs in virtualization realm ID: {i}'.format(n=str(len(drs)), i=str(vr_id)))
        return drs

    def list_active_deployment_runs_in_virtualization_realm(self, vr_id):
        """Query CONS3RT to return a list of active deployment runs in a virtualization realm

        :param: vr_id: (int) virtualization realm ID
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        try:
            drs = self.list_deployment_runs_in_virtualization_realm(
                vr_id=vr_id,
                search_type='SEARCH_ACTIVE'
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem retrieving active runs from virtualization realm ID: {i}'.format(
                i=str(vr_id))) from exc
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

    def retrieve_custom_properties_from_deployment_run_details(self, dr_details):
        """Returns a list of custom properties given deployment run details

        :param dr_details: (dict) deployment run details data
        :return: (list) of custom deployment properties or None
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_custom_properties_from_deployment_run_details')
        if 'id' not in dr_details:
            log.warning('id not found in deployment run detail data: {d}'.format(d=str(dr_details)))
            return
        if 'properties' not in dr_details:
            log.warning('No properties found for deployment run ID: {i}'.format(i=str(dr_details['id'])))
            return
        custom_props = []
        for dep_prop in dr_details['properties']:
            if 'cons3rt.fap.' in dep_prop['key']:
                continue
            elif 'cons3rt.deploymentRun.' in dep_prop['key']:
                continue
            elif 'cons3rt.cloud.' in dep_prop['key']:
                continue
            elif 'cons3rt.deploymentRun.' in dep_prop['key']:
                continue
            elif 'guac.ipaddress' in dep_prop['key']:
                continue
            elif 'cons3rt.deployment' in dep_prop['key']:
                continue
            elif 'cons3rt.user' in dep_prop['key']:
                continue
            elif 'cons3rt.siteAddress' in dep_prop['key']:
                continue
            custom_props.append(dep_prop)
        return custom_props

    def retrieve_deployment_run_host_details(self, dr_id, drh_id):
        """Query CONS3RT to return details of a deployment run host

        :param: dr_id: (int) deployment run ID
        :param: drh_id: (int) deployment run host ID
        :return: (dict) of deployment run host detailed info
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_deployment_run_host_details')

        # Ensure the dr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError as exc:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the drh_id is an int
        if not isinstance(drh_id, int):
            try:
                drh_id = int(drh_id)
            except ValueError as exc:
                msg = 'drh_id arg must be an Integer, found: {t}'.format(t=drh_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Query for DR details
        log.info('Attempting to retrieve details for deployment run ID [{d}] host ID: {h}'.format(
            d=str(dr_id), h=str(drh_id)))
        try:
            drh_details = self.cons3rt_client.retrieve_deployment_run_host_details(dr_id=dr_id, drh_id=drh_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a details of deployment run host ID: {i}'.format(
                i=str(drh_id))
            raise Cons3rtApiError(msg) from exc
        return drh_details

    def list_virtualization_realms(self):
        """Query CONS3RT to return a list of VRs

        :return: (list) of Virtualization Realm data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_virtualization_realms')
        log.info('Attempting to list virtualization realms')
        try:
            vrs = self.cons3rt_client.list_all_virtualization_realms()
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a list of Virtualization Realms'
            raise Cons3rtApiError(msg) from exc
        return vrs

    def list_virtualization_realms_for_cloud(self, cloud_id):
        """Query CONS3RT to return a list of VRs for a specified Cloud ID

        :param cloud_id: (int) Cloud ID
        :return: (list) of Virtualization Realm data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_virtualization_realms_for_cloud')
        log.info('Attempting to list virtualization realms for cloud ID: {i}'.format(i=cloud_id))
        try:
            vrs = self.cons3rt_client.list_all_virtualization_realms_for_cloud(cloud_id=cloud_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a list of Virtualization Realms for Cloud ID: {c}'.format(
                c=cloud_id)
            raise Cons3rtApiError(msg) from exc
        return vrs

    def list_virtualization_realms_for_project(self, project_id):
        """Query CONS3RT to return a list of VRs for a specified Cloud ID

        :param project_id: (int) project ID
        :return: (list) of Virtualization Realm data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_virtualization_realms_for_project')
        log.info('Attempting to list virtualization realms for project ID: {i}'.format(i=project_id))
        try:
            vrs = self.cons3rt_client.list_all_virtualization_realms_for_project(project_id=project_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a list of Virtualization Realms for project ID: {c}'.format(
                c=project_id)
            raise Cons3rtApiError(msg) from exc
        return vrs

    def list_virtualization_realms_for_team(self, team_id):
        """Query CONS3RT to return a list of VRs for a specified team ID

        :param team_id: (int) team ID
        :return: (list) of Virtualization Realm data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_virtualization_realms_for_team')
        log.info('Attempting to list virtualization realms for team ID: {i}'.format(i=team_id))
        try:
            vrs = self.cons3rt_client.list_all_virtualization_realms_for_team(team_id=team_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for a list of Virtualization Realms for team ID: {c}'.format(
                c=team_id)
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
            username = self.rest_user.username
        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError as exc:
                msg = 'The cloud_id arg must be an int'
                raise Cons3rtApiError(msg) from exc
        try:
            self.cons3rt_client.add_cloud_admin(cloud_id=cloud_id, username=self.rest_user.username)
        except Cons3rtClientError as exc:
            msg = 'Unable to add Cloud Admin {u} to Cloud: {c}'.format(u=username, c=cloud_id)
            raise Cons3rtApiError(msg) from exc
        else:
            log.info('Added Cloud Admin {u} to Cloud: {c}'.format(u=username, c=cloud_id))

    def delete_asset(self, asset_id, force=False):
        """Deletes the asset based on a provided asset type

        :param asset_id: (int) asset ID
        :param force: (bool) Set true to force the asset deletion of dependent assets
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

        # Ensure the asset_id is an int
        if not isinstance(force, bool):
            msg = 'force arg must be a boolean, found: {t}'.format(t=asset_id.__class__.__name__)
            raise Cons3rtApiError(msg)

        # Attempt to delete the target
        try:
            self.cons3rt_client.delete_asset(asset_id=asset_id, force=force)
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
                msg = 'asset_id arg must be an Integer, found: {t}'.format(t=asset_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(asset_zip_file, str):
            msg = 'The asset_zip_file arg must be a string, found: {t}'.format(t=asset_zip_file.__class__.__name__),
            raise Cons3rtApiError(msg)

        # Ensure the asset_zip_file file exists
        if not os.path.isfile(asset_zip_file):
            msg = 'Asset zip file file not found: {f}'.format(f=asset_zip_file)
            raise Cons3rtApiError(msg)

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

    def update_asset_visibility(self, asset_id, visibility, trusted_projects=None):
        """Updates the asset visibility

        :param asset_id: (int) asset ID to update
        :param visibility: (str) desired asset visibility
        :param trusted_projects (list) of int project IDs to add
        :return: None
        :raises: Cons3rtApiError
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
        if not isinstance(visibility, str):
            msg = 'The visibility arg must be a string, found {t}'.format(t=visibility.__class__.__name__)
            raise Cons3rtApiError(msg)

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
            self.cons3rt_client.update_asset_visibility(asset_id=asset_id, visibility=visibility)
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

        already_disabled_statii = ['DISABLED', 'DISABLING']

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise ValueError('vr_id arg must be an Integer') from exc

        # Determine remote access status
        try:
            vr_details = self.get_virtualization_realm_details(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Cons3rtApiError: Unable to query VR details to determine the size'
            raise Cons3rtApiError(msg) from exc

        if 'remoteAccessStatus' not in vr_details.keys():
            log.warning('remoteAccessStatus data not found in VR details, will attempt to disable: {d}'.format(
                d=str(vr_details)))
        else:
            if vr_details['remoteAccessStatus'] in already_disabled_statii:
                log.info('Remote access for VR ID {i} is already disabled or disabling'.format(i=str(vr_id)))
                return

        # Attempt to disable remote access
        log.info('Attempting to disable remote access in virtualization realm ID: {i}'.format(i=vr_id))
        try:
            self.cons3rt_client.disable_remote_access(vr_id=vr_id)
        except Cons3rtClientError as exc:
            msg = 'There was a problem disabling remote access in virtualization realm ID: {i}'.format(i=vr_id)
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully disabled remote access in virtualization realm: {i}'.format(i=vr_id))

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

    def list_team_managers(self):
        """Retrieves a list of team managers for all teams

        :return: (list) of team managers:
            {
                "id": ID,
                "username": USERNAME,
                "email": EMAIL,
                "teamIds": list of team IDs,
                "teamNames": list of team names
            }
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_team_managers')
        log.info('Attempting to list team managers...')

        # Get a list of teams
        try:
            teams = self.list_teams()
        except Cons3rtApiError as exc:
            msg = 'Problem getting a list of teams, unable to determine team managers'
            raise Cons3rtApiError(msg) from exc

        # Get a list of managers from each team
        team_managers = []
        for team in teams:
            # Retrieve team managers from team details
            try:
                team_details = self.get_team_details(team_id=team['id'])
            except Cons3rtApiError as exc:
                msg = 'Problem getting details for team ID: {i}'.format(i=str(team['id']))
                raise Cons3rtApiError(msg) from exc
            if 'teamManagers' not in team_details.keys():
                log.warning('No team managers found for team ID: {i}'.format(i=str(team['id'])))
                continue

            # Add team managers to the list if they're not already on it, checking by user ID
            for team_manager in team_details['teamManagers']:
                already_on_list = False
                for existing_team_manager in team_managers:
                    if existing_team_manager['id'] == team_manager['id']:
                        already_on_list = True
                        existing_team_manager['teamIds'] += [team['id']]
                        existing_team_manager['teamNames'] += [team['name']]
                if not already_on_list:
                    log.info('Found team manager with user ID [{i}] and username [{u}]'.format(
                        i=team_manager['id'], u=team_manager['username']))
                    team_manager['teamIds'] = [team['id']]
                    team_manager['teamNames'] = [team['name']]
                    team_managers.append(team_manager)
        log.info('Found {n} team managers'.format(n=str(len(team_managers))))
        return team_managers

    def list_team_managers_for_team(self, team_id):
        """Returns a list of team managers for a team

        :param team_id: (int) ID of the team
        :return: (list) of team managers:
            {
                "id": ID,
                "username": USERNAME,
                "email": EMAIL,
                "teamIds": list of team IDs,
                "teamNames": list of team names
            }
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_team_managers_for_team')
        team_managers = []
        # Retrieve team managers from team details
        try:
            team_details = self.get_team_details(team_id=team_id)
        except Cons3rtApiError as exc:
            msg = 'Problem getting details for team ID: {i}'.format(i=str(team_id))
            raise Cons3rtApiError(msg) from exc
        if 'teamManagers' not in team_details.keys():
            log.warning('No team managers found for team ID: {i}'.format(i=str(team_id)))
            return team_managers
        for team_manager in team_details['teamManagers']:
            log.info('Found team manager with user ID [{i}] and username [{u}]'.format(
                i=team_manager['id'], u=team_manager['username']))
            team_manager['teamIds'] = [team_id]
            team_manager['teamNames'] = [team_details['name']]
            team_managers.append(team_manager)
        return team_managers

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
            components=None,
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
        :param components: (list) see CONS3RT API docs
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
            if components:
                if not isinstance(components, list):
                    raise Cons3rtApiError('components must be a list, found: {t}'.format(
                        t=components.__class__.__name__))
                log.debug('Adding components...')
                content['components'] = components

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
            msg = 'Unable to release deployment run ID: {i}'.format(i=str(dr_id))
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
            dr_info = self.cons3rt_client.run_deployment(deployment_id=deployment_id, run_options=run_options)
        except Cons3rtClientError as exc:
            msg = 'Unable to launch deployment run ID: {i}'.format(i=str(deployment_id))
            raise Cons3rtApiError(msg) from exc
        try:
            dr_id = int(dr_info)
        except ValueError as exc:
            msg = 'deploymentRunId was not an int: {d}'.format(d=str(dr_info['deploymentRunId']))
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully launched deployment ID {d} as deployment run ID: {i}'.format(
            i=str(dr_id), d=str(deployment_id)))
        return dr_id

    def delete_inactive_runs_in_virtualization_realm(self, vr_id):
        """Deletes all inactive runs in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: (int) number of runs deleted
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
        log.info('Completed deleting {n} inactive DRs in VR ID: {i}'.format(i=str(vr_id), n=str(len(drs))))
        return len(drs)

    def release_active_runs_in_virtualization_realm(self, vr_id, unlock=False):
        """Releases all active runs in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :param unlock (bool) Set True to unset the run lock before releasing
        :return: None
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.release_active_runs_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure unlock is a bool
        if not isinstance(unlock, bool):
            msg = 'unlock arg must be a bool, found: {t}'.format(t=unlock.__class__.__name__)
            raise Cons3rtApiError(msg)

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

            # Unlock the run if specified
            do_unlock = False
            if unlock:
                if 'locked' not in dr:
                    log.warning('locked data not found in DR, unlock will be attempted: {d}'.format(d=str(dr)))
                    do_unlock = True
                elif dr['locked']:
                    do_unlock = True
            if do_unlock:
                try:
                    self.set_deployment_run_lock(dr_id=dr_id, lock=False)
                except Cons3rtApiError as exc:
                    msg = 'Problem removing run lock on run ID: {i}\n{e}'.format(i=str(dr_id), e=str(exc))
                    log.warning(msg)
                else:
                    log.info('Removed run lock for run ID: {i}'.format(i=str(dr_id)))
            try:
                self.release_deployment_run(dr_id=dr_id)
            except Cons3rtApiError as exc:
                log.warning('Cons3rtApiError: Unable to release or cancel run ID: {i}\n{e}'.format(
                    i=str(dr_id), e=str(exc)))
                continue
        log.info('Completed releasing or cancelling active DRs in VR ID: {i}'.format(i=str(vr_id)))

    def clean_all_runs_in_virtualization_realm(self, vr_id, unlock=False):
        """Releases all active runs in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :param unlock (bool) Set True to unset the run lock before releasing
        :return: None
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.clean_all_runs_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure unlock is a bool
        if not isinstance(unlock, bool):
            msg = 'unlock arg must be a bool, found: {t}'.format(t=unlock.__class__.__name__)
            raise Cons3rtApiError(msg)

        if unlock:
            log.info('Attempting to unlock, release, and delete all runs from VR ID: {i}'.format(i=str(vr_id)))
        else:
            log.info('Attempting release and delete all runs, except for locked runs from VR ID: {i}'.format(
                i=str(vr_id)))

        self.release_active_runs_in_virtualization_realm(vr_id=vr_id, unlock=unlock)
        log.info('Waiting 120 seconds to proceed to deletion of inactive runs...')
        time.sleep(120)

        # Once a minute for 5 minutes, delete inactive runs (as runs release)
        attempt_num = 1
        max_attempts = 10
        interval_sec = 60
        while True:
            if attempt_num > max_attempts:
                msg = 'Maximum number of attempts {n} exceeded for deleting inactive runs from VR ID: {i}'.format(
                    i=str(vr_id), n=str(max_attempts))
                raise Cons3rtApiError(msg)
            log.info('Attempting to delete inactive runs from VR ID {i}, attempt #{n} of {m}'.format(
                i=str(vr_id), n=str(attempt_num), m=str(max_attempts)))
            num_deleted = self.delete_inactive_runs_in_virtualization_realm(vr_id=vr_id)
            if num_deleted < 1:
                log.info('Completed deleting all inactive runs from VR ID: {i}'.format(i=str(vr_id)))
                break
            attempt_num += 1
            log.info('Waiting {n} seconds to re-attempt inactive run deletion...'.format(n=str(interval_sec)))
            time.sleep(interval_sec)
        log.info('Completed cleaning all runs from VR ID: {i}'.format(i=str(vr_id)))

    def set_virtualization_realm_state(self, vr_id, state):
        """Sets the virtualization realm ID to the provided state

        :param vr_id: (int) virtualization realm ID
        :param state: (bool) Set True to activate, False to deactivate
        :return: (bool) True if successful
        """
        log = logging.getLogger(self.cls_logger + '.set_virtualization_realm_state')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the state is a boolean
        if not isinstance(state, bool):
            msg = 'state arg must be a bool, found: {t}'.format(t=state.__class__.__name__)
            raise Cons3rtApiError(msg)

        try:
            result = self.cons3rt_client.set_virtualization_realm_state(vr_id=vr_id, state=state)
        except Cons3rtClientError as exc:
            msg = 'Problem setting state to {s} for VR ID: {i}'.format(s=str(state), i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        if state:
            state_str = 'active'
        else:
            state_str = 'inactive'
        if result:
            log.info('Set state to {s} for VR ID: {i}'.format(s=state_str, i=str(vr_id)))
        else:
            log.warning('Unable to set state to {s} for VR ID: {i}'.format(s=state_str, i=str(vr_id)))
        return result

    def prep_virtualization_realm_for_removal(self, vr_id):
        """Cleans and de-allocates a virtualization realm

        :param vr_id: (int) ID of the virtualization realm
        :returns: (tuple) cloud ID, and details of the prepped virtualization realm or None
        :return: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.prep_virtualization_realm_for_removal')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Get the cloud ID needed to de-allocation
        vr_details = self.get_virtualization_realm_details(vr_id=vr_id)
        if 'cloud' not in vr_details:
            raise Cons3rtApiError('cloud data not found in VR details: {d}'.format(d=str(vr_details)))
        if 'id' not in vr_details['cloud']:
            msg = 'id not found in cloud data for VR {i} details: {d}'.format(i=str(vr_id), d=str(vr_details))
            raise Cons3rtApiError(msg)
        cloud_id = vr_details['cloud']['id']

        # Clean out all DRs, remove all projects, deactivate
        log.info('Preparing VR ID {i} for de-allocation or unregistering...'.format(i=str(vr_id)))
        self.disable_remote_access(vr_id=vr_id)
        self.remove_all_projects_in_virtualization_realm(vr_id=vr_id)
        log.info('Waiting 60 seconds to proceed to removing runs...')
        time.sleep(60)
        self.clean_all_runs_in_virtualization_realm(vr_id=vr_id, unlock=True)
        log.info('Waiting 60 seconds to proceed to deactivation of the VR...')
        time.sleep(60)
        state_result = self.set_virtualization_realm_state(vr_id=vr_id, state=False)
        if not state_result:
            msg = 'Unable to deactivate VR ID {i} before attempting to unregister/de-allocate'.format(i=str(vr_id))
            raise Cons3rtApiError(msg)
        log.info('Completed prepping VR ID {i} for unregister or de-allocation'.format(i=str(vr_id)))
        return cloud_id, vr_details

    def deallocate_virtualization_realm(self, vr_id):
        """Cleans and de-allocates a virtualization realm

        :param vr_id: (int) ID of the virtualization realm
        :returns: (dict) details of the deallocated virtualization realm or None
        :return: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.deallocate_virtualization_realm')
        cloud_id, vr_details = self.prep_virtualization_realm_for_removal(vr_id=vr_id)
        log.info('Attempting to de-allocate VR ID {v} from cloud ID: {c}'.format(v=str(vr_id), c=str(cloud_id)))
        try:
            result = self.cons3rt_client.deallocate_virtualization_realm(cloud_id=cloud_id, vr_id=vr_id)
        except Cons3rtClientError as exc:
            msg = 'Problem de-allocating VR ID {v} from cloud ID {c}'.format(v=str(vr_id), c=str(cloud_id))
            raise Cons3rtApiError(msg) from exc
        if result:
            log.info('De-allocation of VR ID {v} from cloud ID {c} succeeded'.format(v=str(vr_id), c=str(cloud_id)))
            return vr_details
        else:
            log.warning('De-allocation of VR ID {v} from cloud ID {c} failed'.format(v=str(vr_id), c=str(cloud_id)))

    def unregister_virtualization_realm(self, vr_id):
        """Cleans and de-allocates a virtualization realm

        :param vr_id: (int) ID of the virtualization realm
        :returns: (dict) details of the unregistered virtualization realm or None
        :return: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.unregister_virtualization_realm')
        cloud_id, vr_details = self.prep_virtualization_realm_for_removal(vr_id=vr_id)
        log.info('Attempting to unregister VR ID {v} from cloud ID: {c}'.format(v=str(vr_id), c=str(cloud_id)))
        try:
            result = self.cons3rt_client.unregister_virtualization_realm(cloud_id=cloud_id, vr_id=vr_id)
        except Cons3rtClientError as exc:
            msg = 'Problem unregistering VR ID {v} from cloud ID {c}'.format(v=str(vr_id), c=str(cloud_id))
            raise Cons3rtApiError(msg) from exc
        if result:
            log.info('Unregister of VR ID {v} from cloud ID {c} succeeded'.format(v=str(vr_id), c=str(cloud_id)))
            return vr_details
        else:
            log.warning('Unregister of VR ID {v} from cloud ID {c} failed'.format(v=str(vr_id), c=str(cloud_id)))

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

    def list_templates_in_virtualization_realm(self, vr_id, include_registrations=True, include_subscriptions=True):
        """Lists all templates in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :param include_registrations: (bool) Set True to include templates registered in this virtualization realm
        :param include_subscriptions: (bool) Set True to include templates registered in this virtualization realm
        :return: list of templates (see API docs)
        :raises: Cons3rtApiError
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
        log.info('Listing templates in VR ID: {v}'.format(v=str(vr_id)))
        try:
            templates = self.cons3rt_client.list_templates_in_virtualization_realm(
                vr_id=vr_id,
                include_registrations=include_registrations,
                include_subscriptions=include_subscriptions
            )
        except Cons3rtApiError as exc:
            msg = 'Problem listing templates in VR ID {i} with registrations={r} and subscriptions={s}'.format(
                i=str(vr_id), r=str(include_registrations), s=str(include_subscriptions))
            raise Cons3rtApiError(msg) from exc
        log.debug('Found {n} templates in VR ID {v} with registrations={r} and subscriptions={s}'.format(
            v=str(vr_id), n=str(len(templates)), r=str(include_registrations), s=str(include_subscriptions)))
        return templates

    def list_template_registrations_in_virtualization_realm(self, vr_id):
        """Lists all template registrations in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: list of templates (see API docs)
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_template_registrations_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # List templates in the virtualization realm
        log.info('Listing template registrations in VR ID: {v}'.format(v=str(vr_id)))
        try:
            templates = self.cons3rt_client.list_template_registrations_in_virtualization_realm(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing template registrations in VR ID {i}'.format(i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Found {n} template registrations in VR ID: {i}'.format(i=str(vr_id), n=str(len(templates))))
        return templates

    def list_template_subscriptions_in_virtualization_realm(self, vr_id):
        """Lists all template subscriptions in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :return: list of templates (see API docs)
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_template_subscriptions_in_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # List templates in the virtualization realm
        log.info('Listing template subscriptions in VR ID {v}'.format(v=str(vr_id)))
        try:
            templates = self.cons3rt_client.list_template_subscriptions_in_virtualization_realm(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing template subscriptions in VR ID: {i}'.format(i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Found {n} template subscriptions in VR ID: {i}'.format(i=str(vr_id), n=str(len(templates))))
        return templates

    def list_pending_template_subscriptions_in_virtualization_realm(self, vr_id):
        """Lists template subscriptions in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (list) of template data
        :raises: Cons3rtClientError
        """
        log = logging.getLogger(self.cls_logger + '.list_pending_template_subscriptions_in_virtualization_realm')
        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # List pending template subscriptions in the virtualization realm
        log.info('Listing pending template subscriptions in VR ID: {v}'.format(v=str(vr_id)))
        try:
            templates = self.cons3rt_client.list_pending_template_subscriptions_in_virtualization_realm(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing pending template subscriptions in VR ID {i}'.format(i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Found {n} pending template subscriptions in VR ID: {i}'.format(i=str(vr_id), n=str(len(templates))))
        return templates

    def retrieve_template_registration(self, vr_id, template_registration_id):
        """Returns template registration details

        :param vr_id: (int) virtualization realm ID
        :param template_registration_id: (int) ID of the template registration
        :return: (dict) of template registration data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_template_registration')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the template_registration_id is an int
        if not isinstance(template_registration_id, int):
            try:
                template_registration_id = int(template_registration_id)
            except ValueError as exc:
                msg = 'template_registration_id arg must be an Integer, found: {t}'.format(
                    t=template_registration_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Retrieve details on the template registration
        log.info('Retrieving details on registration ID {r} in VR ID: {i}'.format(
            r=str(template_registration_id), i=str(vr_id)))
        try:
            template_reg_details = self.cons3rt_client.retrieve_template_registration(
                vr_id=vr_id, template_registration_id=template_registration_id)
        except Cons3rtApiError as exc:
            msg = 'Problem retrieving template registration ID {r} in VR ID {i}'.format(
                r=str(template_registration_id), i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        return template_reg_details

    def retrieve_template_subscription(self, vr_id, template_subscription_id):
        """Returns template subscription details

        :param vr_id: (int) virtualization realm ID
        :param template_subscription_id: (int) ID of the template subscription
        :return: (dict) of template subscription data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_template_subscription')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the template_subscription_id is an int
        if not isinstance(template_subscription_id, int):
            try:
                template_subscription_id = int(template_subscription_id)
            except ValueError as exc:
                msg = 'template_subscription_id arg must be an Integer, found: {t}'.format(
                    t=template_subscription_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Retrieve details on the template subscription
        log.info('Retrieving details on subscription ID {r} in VR ID: {i}'.format(
            r=str(template_subscription_id), i=str(vr_id)))
        try:
            template_sub_details = self.cons3rt_client.retrieve_template_subscription(
                vr_id=vr_id, template_subscription_id=template_subscription_id)
        except Cons3rtApiError as exc:
            msg = 'Problem retrieving template subscription ID {r} in VR ID {i}'.format(
                r=str(template_subscription_id), i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        return template_sub_details

    def refresh_template_cache(self, vr_id):
        """Refreshes the template cache for the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (bool) True if successful
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.refresh_template_cache')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Refresh the template cache
        log.info('Refreshing the template cache for VR ID: {i}'.format(i=str(vr_id)))
        try:
            result = self.cons3rt_client.refresh_template_cache(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Problem refreshing the template cache in VR ID {i}'.format(i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        return result

    def list_unregistered_templates(self, vr_id):
        """Returns a list of unregistered templates in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (list) of unregistered templates
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_unregistered_templates')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # List unregistered templates in the VR
        log.info('Listing unregistered templates in VR ID: {i}'.format(i=str(vr_id)))
        try:
            unregistered_templates = self.cons3rt_client.list_unregistered_templates(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing unregistered templates in VR ID {i}'.format(i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        return unregistered_templates

    def create_template_registration(self, vr_id, template_name, operating_system=None, display_name=None,
                                     cons3rt_agent_installed=True, container_capable=False, default_username=None,
                                     default_password=None, license_str=None, note=None, max_cpus=20,
                                     max_ram_mb=131072, root_disk_size_mb=102400, additional_disks=None,
                                     linux_package_manager=None, power_on_delay_override=None, powershell_version=None,
                                     linux_service_management=None):
        """Creates a template registration in the provided virtualization realm ID

        NOTE: This does not support special permissions

        :param vr_id: (int) ID of the virtualization realm
        :param template_name: (str) actual name of the template in the virtualization realm (or cons3rttemplatename tag)
        :param operating_system: (str) operating system type
        :param display_name: (str) optional display name for the template
        :param cons3rt_agent_installed: (bool) set True if cons3rt agent is installed
        :param container_capable: (bool) Set true if the OS can launch containers
        :param default_username: (str) Default template username
        :param default_password: (str) Default template password
        :param license_str: (str) Optional license info
        :param note: (str) Optional note
        :param max_cpus: (int) Maximum number of CPUs for the template
        :param max_ram_mb: (int) Maximum amount of RAM for the template in MB
        :param root_disk_size_mb: (int) Size of the root disk in MB
        :param additional_disks: (list) of additional disks (dict), must have capacityInMegabytes (int)
        :param linux_package_manager: (str) package manager for linux distros
        :param power_on_delay_override: (int) seconds to delay power on
        :param powershell_version: (str) powershell version for Windows
        :param linux_service_management: (str) service management system for linux
        :return: (dict) of template registration data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_template_registration')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc
        if not isinstance(template_name, str):
            msg = 'template_name arg must be a str, found: {t}'.format(t=template_name.__class__.__name__)
            raise Cons3rtApiError(msg)

        if not operating_system:
            operating_system = OperatingSystemType.guess_os_type(template_name)
            if not operating_system:
                msg = 'Unable to determine OS type from template name: {n}'.format(n=template_name)
                raise Cons3rtApiError(msg)
        else:
            if not isinstance(operating_system, str):
                msg = 'operating_system arg must be a str, found: {t}'.format(t=operating_system.__class__.__name__)
                raise Cons3rtApiError(msg)
        log.info('Attempting to register template {n} as OS type: {t}'.format(n=template_name, t=operating_system))

        disks = [
            {
                'capacityInMegabytes': root_disk_size_mb,
                'isAdditionalDisk': False,
                'isBootDisk': True
            }
        ]
        if additional_disks:
            if not isinstance(additional_disks, list):
                msg = 'additional_disks arg must be a list, found: {t}'.format(t=additional_disks.__class__.__name__)
                raise Cons3rtApiError(msg)
            for additional_disk in additional_disks:
                disks.append(additional_disk)

        template = OperatingSystemTemplate(template_name=template_name, operating_system_type=operating_system)
        try:
            template_data = template.generate_registration_data(
                display_name=display_name, cons3rt_agent_installed=cons3rt_agent_installed,
                container_capable=container_capable, default_username=default_username,
                default_password=default_password, license_str=license_str, note=note,
                max_cpus=max_cpus, max_ram_mb=max_ram_mb, disks=disks, linux_package_manager=linux_package_manager,
                power_on_delay_override=power_on_delay_override, powershell_version=powershell_version,
                linux_service_management=linux_service_management
            )
        except InvalidOperatingSystemTemplate as exc:
            msg = 'Problem generating registration data\n{e}'.format(e=str(exc))
            raise Cons3rtApiError(msg) from exc
        log.info('Generated template data for template {n} with type: {t}'.format(n=template_name, t=operating_system))

        # Create the template subscription
        log.info('Creating template registration in VR ID {i} for template: {n}'.format(
            n=template_name, i=str(vr_id)))
        try:
            template_registration_data = self.cons3rt_client.create_template_registration(
                vr_id=vr_id,
                template_data=template_data
            )
        except Cons3rtApiError as exc:
            msg = 'Problem creating template registration in VR ID {i} for template: {n}'.format(
                n=template_name, i=str(vr_id))
            raise Cons3rtApiError(msg) from exc

        if 'id' not in template_registration_data:
            raise Cons3rtApiError('id not found in template registration data: {d}'.format(
                d=str(template_registration_data)))
        template_registration_id = template_registration_data['id']
        log.info('Setting template registration ID {i} to ONLINE for: {n}'.format(
            i=str(template_registration_id), n=template_name))
        try:
            self.cons3rt_client.update_template_registration(
                vr_id=vr_id,
                template_registration_id=template_registration_id,
                offline=False,
                registration_data=template_data
            )
        except Cons3rtApiError as exc:
            msg = 'Problem updating VR ID {i} template registration ID {r} to be online'.format(
                r=str(template_registration_id), i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        return template_registration_data

    def set_template_registration_online(self, vr_id, template_registration_id):
        """Updates the template registration to set status to online

        :param vr_id: (int) ID of the virtualization realm
        :param template_registration_id:
        :return:
        """
        log = logging.getLogger(self.cls_logger + '.create_template_subscription')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the template_registration_id is an int
        if not isinstance(template_registration_id, int):
            try:
                template_registration_id = int(template_registration_id)
            except ValueError as exc:
                msg = 'template_registration_id arg must be an Integer, found: {t}'.format(
                    t=template_registration_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        try:
            reg_details = self.retrieve_template_registration(
                vr_id=vr_id,
                template_registration_id=template_registration_id
            )
        except Cons3rtApiError as exc:
            msg = 'Problem retrieving details on template registration: {i}'.format(i=str(template_registration_id))
            raise Cons3rtApiError(msg) from exc

        # Update the template registration
        log.info('Updating VR ID {i} to template registration ID: {r} to be online'.format(
            r=str(template_registration_id), i=str(vr_id)))
        try:
            is_success = self.cons3rt_client.update_template_registration(
                vr_id=vr_id,
                template_registration_id=template_registration_id,
                offline=False,
                registration_data=reg_details['templateData']
            )
        except Cons3rtApiError as exc:
            msg = 'Problem updating VR ID {i} template registration ID {r} to be online'.format(
                r=str(template_registration_id), i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        return is_success

    def create_template_subscription(self, vr_id, template_registration_id):
        """Creates template subscription in the provided virtualization realm ID to the provided
        template registration ID

        :param vr_id: (int) ID of the virtualization realm
        :param template_registration_id: (int) ID of the template registration
        :return: (dict) of template subscription data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_template_subscription')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the template_registration_id is an int
        if not isinstance(template_registration_id, int):
            try:
                template_registration_id = int(template_registration_id)
            except ValueError as exc:
                msg = 'template_registration_id arg must be an Integer, found: {t}'.format(
                    t=template_registration_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Create the template subscription
        log.info('Creating template subscription VR ID {i} to template registration ID: {r}'.format(
            r=str(template_registration_id), i=str(vr_id)))
        try:
            is_success = self.cons3rt_client.create_template_subscription(
                vr_id=vr_id,
                template_registration_id=template_registration_id
            )
        except Cons3rtApiError as exc:
            msg = 'Problem creating template subscription in VR ID {i} for template registration ID: {r}'.format(
                r=str(template_registration_id), i=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        return is_success

    def update_template_subscription(self, vr_id, template_subscription_id, offline, state='IN_DEVELOPMENT',
                                     max_cpus=20, max_ram_mb=131072):
        """Updates template subscription data in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :param template_subscription_id: (int) ID of the template subscription
        :param offline: (bool) Set True to set the template to offline, False for online
        :param state: (str) Subscription state
        :param max_cpus: (int) Set to the maximum number of CPUs allowed
        :param max_ram_mb: (int) Set to the maximum RAM in megabytes allowed
        :return: (dict) of template subscription data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.update_template_subscription')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the template_subscription_id is an int
        if not isinstance(template_subscription_id, int):
            try:
                template_subscription_id = int(template_subscription_id)
            except ValueError as exc:
                msg = 'template_subscription_id arg must be an Integer, found: {t}'.format(
                    t=template_subscription_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure offline is a bool
        if not isinstance(offline, bool):
            msg = 'offline arg must be an bool, found: {t}'.format(t=offline.__class__.__name__)
            raise Cons3rtApiError(msg)

        # Ensure state is a string
        if not isinstance(state, str):
            msg = 'state arg must be a str, found: {t}'.format(t=state.__class__.__name__)
            raise Cons3rtApiError(msg)

        # Ensure the max_cpus is an int
        if not isinstance(max_cpus, int):
            try:
                max_cpus = int(max_cpus)
            except ValueError as exc:
                msg = 'max_cpus arg must be an Integer, found: {t}'.format(
                    t=max_cpus.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the max_ram_mb is an int
        if not isinstance(max_ram_mb, int):
            try:
                max_ram_mb = int(max_ram_mb)
            except ValueError as exc:
                msg = 'max_ram_mb arg must be an Integer, found: {t}'.format(
                    t=max_ram_mb.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Validate the state
        valid_states = ['IN_DEVELOPMENT', 'CERTIFIED', 'DEPRECATED', 'RETIRED']
        if state not in valid_states:
            msg = 'Invalid state [{s}], expected: {e}'.format(s=state, e=','.join(valid_states))
            raise Cons3rtApiError(msg)

        # Validate the subscription data
        subscription_data = {
            'state': state,
            'maxNumCpus': max_cpus,
            'maxRamInMegabytes': max_ram_mb
        }

        # Update the template subscription
        log.info('Updating template subscription ID {r} in VR ID {i} with offline set to: {o} with payload: {p}'.format(
            r=str(template_subscription_id), i=str(vr_id), o=str(offline), p=str(subscription_data)))
        try:
            is_success = self.cons3rt_client.update_template_subscription(
                vr_id=vr_id,
                template_subscription_id=template_subscription_id,
                offline=offline,
                subscription_data=subscription_data
            )
        except Cons3rtApiError as exc:
            msg = 'Problem updating template subscription ID {r} in VR ID {i} to: {o} with payload: {p}'.format(
                r=str(template_subscription_id), i=str(vr_id), o=str(offline), p=str(subscription_data))
            raise Cons3rtApiError(msg) from exc
        return is_success

    def delete_template_registration(self, vr_id, template_registration_id=None, template_name=None):
        """Unregisters the template registration from the VR ID

        NOTE: This does not support removeSubscriptions=False nor special permissions

        :param vr_id: (int) ID of the virtualization realm
        :param template_registration_id: (int) ID of the template registration
        :param template_name: (str) name of the template
        :return: bool
        :raises: Cons3rtClientError
        """
        log = logging.getLogger(self.cls_logger + '.delete_template_registration')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the template_registration_id is an int
        if template_registration_id:
            if not isinstance(template_registration_id, int):
                try:
                    template_registration_id = int(template_registration_id)
                except ValueError as exc:
                    msg = 'template_registration_id arg must be an Integer, found: {t}'.format(
                        t=template_registration_id.__class__.__name__)
                    raise Cons3rtApiError(msg) from exc
        else:
            if template_name:
                if not isinstance(template_name, str):
                    msg = 'template_name arg must be a string, found: {t}'.format(
                        t=template_name.__class__.__name__)
                    raise Cons3rtApiError(msg)

                # Get the template registration ID from the name
                vr_templates = self.list_templates_in_virtualization_realm(
                    vr_id=vr_id,
                    include_registrations=True,
                    include_subscriptions=False
                )
                for vr_template in vr_templates:
                    if 'virtRealmTemplateName' not in vr_template:
                        continue
                    if vr_template['virtRealmTemplateName'] == template_name:
                        if 'templateRegistration' not in vr_template:
                            msg = 'templateRegistration data missing from template: {d}'.format(d=str(vr_template))
                            raise Cons3rtApiError(msg)
                        if 'id' not in vr_template['templateRegistration']:
                            msg = 'id data missing from template registration: {d}'.format(d=str(vr_template))
                            raise Cons3rtApiError(msg)
                        template_registration_id = vr_template['templateRegistration']['id']
            else:
                msg = 'Either template_registration_id or template_name must be provided'
                raise Cons3rtApiError(msg)

        if not template_registration_id:
            msg = 'Unable to determine template registration ID  in VR ID {v} from template name: {n}'.format(
                v=str(vr_id), n=template_name)
            raise Cons3rtApiError(msg)

        # List templates in the virtualization realm
        log.info('Deleting template registration {r} from VR ID {v}'.format(
            r=str(template_registration_id), v=str(vr_id)))
        try:
            result = self.cons3rt_client.delete_template_registration(
                vr_id=vr_id,
                template_registration_id=template_registration_id
            )
        except Cons3rtApiError as exc:
            msg = 'Problem template registration {r} from VR ID {v}'.format(
                v=str(vr_id), r=str(template_registration_id))
            raise Cons3rtApiError(msg) from exc
        return result

    def delete_all_template_registrations(self, vr_id):
        """Deletes all template registrations from the virtualization realm

        :param vr_id: (int) ID of the virtualization realm
        :return: bool
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.delete_all_template_registrations')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Get the list of template registrations
        template_registrations = self.list_template_registrations_in_virtualization_realm(vr_id=vr_id)
        for template_registration in template_registrations:
            if 'id' not in template_registration.keys():
                msg = 'id not found in template registration data: {d}'.format(d=str(template_registration))
                raise Cons3rtApiError(msg)
            if 'templateData' not in template_registration:
                msg = 'templateData not found in template registration data: {d}'.format(d=str(template_registration))
                raise Cons3rtApiError(msg)
            if 'virtRealmTemplateName' not in template_registration['templateData']:
                msg = 'virtRealmTemplateName not found in template registration data: {d}'.format(
                    d=str(template_registration))
                raise Cons3rtApiError(msg)
            template_name = template_registration['templateData']['virtRealmTemplateName']
            log.info('Removing template registration [{n}] from VR ID: {i}'.format(n=template_name, i=str(vr_id)))
            self.delete_template_registration(vr_id=vr_id, template_registration_id=template_registration['id'])
        log.info('Completed removing all template registrations from VR ID: {i}'.format(i=str(vr_id)))

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

    def retrieve_container_asset(self, asset_id):
        """Retrieves details for the container asset

        :param asset_id: (int) asset ID
        return: (dict) details about the container asset
        :return:
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_container_asset')
        log.info('Retrieving container asset ID: {i}'.format(i=str(asset_id)))
        try:
            container_asset = self.cons3rt_client.retrieve_container_asset(asset_id=asset_id)
        except Cons3rtClientError as exc:
            msg = 'Problem container asset ID: {i}'.format(i=str(asset_id))
            raise Cons3rtApiError(msg) from exc
        return container_asset

    def retrieve_software_asset(self, asset_id):
        """Retrieves details for the software asset

        :param asset_id: (int) asset ID
        return: (dict) details about the software asset
        :return:
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_software_asset')
        log.info('Retrieving software asset ID: {i}'.format(i=str(asset_id)))
        try:
            software_asset = self.cons3rt_client.retrieve_software_asset(asset_id=asset_id)
        except Cons3rtClientError as exc:
            msg = 'Problem retrieving software asset ID: {i}'.format(i=str(asset_id))
            raise Cons3rtApiError(msg) from exc
        return software_asset

    def retrieve_software_assets(self, asset_type=None, community=False, expanded=False, category_ids=None,
                                 max_results=None):
        """Get a list of software assets

        :param asset_type: (str) the software asset type, defaults to null
        :param community: (bool) the boolean to include community assets
        :param expanded: (bool) the boolean to include project assets
        :param category_ids: (list) the list of categories to filter by
        :param max_results: (int) maximum number of software assets to return
        :return: List of software asset IDs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_software_assets')
        log.info('Attempting to query CONS3RT to retrieve software assets...')
        try:
            software_assets = self.cons3rt_client.retrieve_all_software_assets(
                asset_type=asset_type,
                community=community,
                category_ids=category_ids,
                expanded=expanded,
                max_results=max_results
            )
        except Cons3rtClientError as exc:
            msg = 'There was a problem querying for software assets'
            raise Cons3rtApiError(msg) from exc
        log.info('Retrieved {n} software assets'.format(n=str(len(software_assets))))
        return software_assets

    def retrieve_expanded_software_assets(self, asset_type=None, community=False, category_ids=None, max_results=None):
        """Get a list of software assets with expanded info

        :param asset_type: (str) the software asset type, defaults to null
        :param community: (bool) the boolean to include community assets
        :param category_ids: (list) the list of categories to filter by
        :param max_results: (int) maximum number of software assets to return
        :return: List of software asset IDs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_expanded_software_assets')
        log.info('Attempting to query CONS3RT to retrieve expanded software assets...')
        try:
            software_asset_ids = self.retrieve_software_assets(
                asset_type=asset_type,
                community=community,
                category_ids=category_ids,
                expanded=True,
                max_results=max_results
            )
        except Cons3rtClientError as exc:
            msg = 'There was a problem querying for expanded software assets'
            raise Cons3rtApiError(msg) from exc
        log.info('Retrieved {n} software assets'.format(n=str(len(software_asset_ids))))
        return software_asset_ids

    def retrieve_all_expanded_software_assets(self, asset_type=None, community=False, category_ids=None):
        """Leaving this for backwards compatibility
        """
        return self.retrieve_expanded_software_assets(asset_type=asset_type, community=community,
                                                      category_ids=category_ids)

    def retrieve_test_assets(self, asset_type=None, community=False, expanded=False, category_ids=None,
                             max_results=None):
        """Get a list of test assets

        :param asset_type: (str) the test asset type, defaults to null
        :param community: (bool) the boolean to include community assets
        :param expanded: (bool) the boolean to include project assets
        :param category_ids: (list) the list of categories to filter by
        :param max_results: (int) maximum number of test assets to return
        :return: List of test asset IDs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_test_assets')
        log.info('Attempting to query CONS3RT to retrieve test assets...')
        try:
            test_assets = self.cons3rt_client.retrieve_all_test_assets(
                asset_type=asset_type,
                community=community,
                category_ids=category_ids,
                expanded=expanded,
                max_results=max_results
            )
        except Cons3rtClientError as exc:
            msg = 'There was a problem querying for test assets'
            raise Cons3rtApiError(msg) from exc
        log.info('Retrieved {n} test assets'.format(n=str(len(test_assets))))
        return test_assets

    def retrieve_expanded_test_assets(self, asset_type=None, community=False, category_ids=None, max_results=None):
        """Get a list of test assets with expanded info

        :param asset_type: (str) the test asset type, defaults to null
        :param community: (bool) the boolean to include community assets
        :param category_ids: (list) the list of categories to filter by
        :param max_results: (int) maximum number of test assets to return
        :return: List of test asset IDs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_expanded_test_assets')
        log.info('Attempting to query CONS3RT to retrieve expanded test assets...')
        try:
            test_asset_ids = self.retrieve_test_assets(
                asset_type=asset_type,
                community=community,
                category_ids=category_ids,
                expanded=True,
                max_results=max_results
            )
        except Cons3rtClientError as exc:
            msg = 'There was a problem querying for expanded test assets'
            raise Cons3rtApiError(msg) from exc
        log.info('Retrieved {n} test assets'.format(n=str(len(test_asset_ids))))
        return test_asset_ids

    def retrieve_all_expanded_test_assets(self, asset_type=None, community=False, category_ids=None):
        """Leaving this for backwards compatibility
        """
        return self.retrieve_expanded_test_assets(asset_type=asset_type, community=community,
                                                      category_ids=category_ids)

    def retrieve_container_assets(self, asset_type=None, community=False, expanded=False, category_ids=None,
                                  max_results=None):
        """Get a list of container assets

        :param asset_type: (str) the container asset type, defaults to null
        :param community: (bool) the boolean to include community assets
        :param expanded: (bool) the boolean to include project assets
        :param category_ids: (list) the list of categories to filter by
        :param max_results: (int) maximum number of container assets to return
        :return: List of container asset IDs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_container_assets')
        log.info('Attempting to query CONS3RT to retrieve container assets...')
        try:
            container_assets = self.cons3rt_client.retrieve_all_container_assets(
                asset_type=asset_type,
                community=community,
                expanded=expanded,
                category_ids=category_ids,
                max_results=max_results
            )
        except Cons3rtClientError as exc:
            msg = 'There was a problem querying for container assets'
            raise Cons3rtApiError(msg) from exc
        log.info('Retrieved {n} container assets'.format(n=str(len(container_assets))))
        return container_assets

    def retrieve_expanded_container_assets(self, asset_type=None, community=False, category_ids=None, max_results=None):
        """Get a list of container assets with expanded info

        :param asset_type: (str) the container asset type, defaults to null
        :param community: (bool) the boolean to include community assets
        :param category_ids: (list) the list of categories to filter by
        :param max_results: (int) maximum number of container assets to return
        :return: List of container asset IDs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_expanded_container_assets')
        log.info('Attempting to query CONS3RT to retrieve expanded data on container assets...')
        try:
            container_assets = self.retrieve_container_assets(
                asset_type=asset_type,
                community=community,
                category_ids=category_ids,
                expanded=True,
                max_results=max_results
            )
        except Cons3rtClientError as exc:
            msg = 'There was a problem querying for expanded container assets'
            raise Cons3rtApiError(msg) from exc
        log.info('Retrieved {n} container assets'.format(n=str(len(container_assets))))
        return container_assets

    def retrieve_asset_categories(self):
        """Retrieves a list of the asset categories in the site

        :return: (list) of asset categories
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_asset_categories')
        log.info('Attempting to retrieve a list of asset categories...')
        try:
            categories = self.cons3rt_client.retrieve_asset_categories()
        except Cons3rtClientError as exc:
            msg = 'Problem retrieving asset categories'
            raise Cons3rtApiError(msg) from exc
        return categories

    def add_category_to_asset(self, asset_id, category_id):
        """Adds the category ID to the asset ID

        :param asset_id: (int) asset ID
        :param category_id: (int) category ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.add_category_to_asset')
        if not isinstance(asset_id, int):
            raise Cons3rtClientError('asset_id arg must be in any')
        if not isinstance(category_id, int):
            raise Cons3rtClientError('category_id arg must be in any')

        log.info('Attempting to add category ID {c} to asset ID {a}...'.format(c=str(category_id), a=str(asset_id)))
        try:
            self.cons3rt_client.add_category_to_asset(asset_id=asset_id, category_id=category_id)
        except Cons3rtClientError as exc:
            msg = 'Problem adding category ID {c} to asset ID {a}'.format(c=str(category_id), a=str(asset_id))
            raise Cons3rtApiError(msg) from exc

    def remove_category_from_asset(self, asset_id, category_id):
        """Removes the category ID from the asset ID

        :param asset_id: (int) asset ID
        :param category_id: (int) category ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.remove_category_from_asset')
        if not isinstance(asset_id, int):
            raise Cons3rtClientError('asset_id arg must be in any')
        if not isinstance(category_id, int):
            raise Cons3rtClientError('category_id arg must be in any')

        log.info('Attempting to remove category ID {c} from asset ID {a}...'.format(
            c=str(category_id), a=str(asset_id)))
        try:
            self.cons3rt_client.remove_category_from_asset(asset_id=asset_id, category_id=category_id)
        except Cons3rtClientError as exc:
            msg = 'Problem removing category ID {c} from asset ID {a}'.format(c=str(category_id), a=str(asset_id))
            raise Cons3rtApiError(msg) from exc

    def download_asset(self, asset_id, background=False, dest_dir=None, overwrite=True, suppress_status=True):
        """Requests download of the asset ID

        :param asset_id: (int) asset ID
        :param background: (bool) set True to download in the background and receive an email when ready
        :param dest_dir: (str) path to the destination directory
        :param overwrite (bool) set True to overwrite the existing file
        :param suppress_status: (bool) Set to True to suppress printing download status
        :return: (str) path to the downloaded asset zip
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.download_asset')
        if not dest_dir:
            dest_dir = os.path.expanduser('~')
        download_file = os.path.join(dest_dir, 'asset-{i}.zip'.format(i=str(asset_id)))
        log.info('Attempting to download asset ID: {a}'.format(a=str(asset_id)))
        try:
            asset_zip = self.cons3rt_client.download_asset(
                asset_id=asset_id,
                background=background,
                download_file=download_file,
                overwrite=overwrite,
                suppress_status=suppress_status
            )
        except Cons3rtClientError as exc:
            msg = 'Problem downloading asset ID: {a}'.format(a=str(asset_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Completed download of asset ID {a} to: {d}'.format(a=str(asset_id), d=download_file))
        return asset_zip

    def get_my_run_id(self):
        """From deployment properties on this host, gets the run ID

        cons3rt.deploymentRun.id

        :return: (int) run ID or None
        """
        log = logging.getLogger(self.cls_logger + '.get_my_run_id')
        try:
            dep = Deployment()
        except DeploymentError as exc:
            log.error('Problem loading deployment info, no run ID found\n{e}'.format(e=str(exc)))
            return
        run_id = dep.get_value('cons3rt.deploymentRun.id')
        if not run_id:
            log.warning('Deployment property not found: cons3rt.deploymentRun.id')
            return
        try:
            run_id = int(run_id)
        except ValueError:
            log.error('Unable to convert run ID {i} to an Integer'.format(i=run_id))
            return
        log.info('Found my own deployment run ID: {i}'.format(i=str(run_id)))
        return run_id

    def get_my_project(self):
        """From deployment properties on this host, gets the project ID and name

        cons3rt.deploymentRun.project.id
        cons3rt.deploymentRun.project.name

        :return: (tuple) int project ID and string project name or None, None
        """
        log = logging.getLogger(self.cls_logger + '.get_my_project_id')
        try:
            dep = Deployment()
        except DeploymentError as exc:
            log.error('Problem loading deployment info, no project ID found\n{e}'.format(e=str(exc)))
            return None, None
        project_id = dep.get_value('cons3rt.deploymentRun.project.id')
        try:
            project_id = int(project_id)
        except ValueError:
            log.error('Unable to convert project ID {i} to an Integer'.format(i=project_id))
            return
        log.info('Found my own project ID: {i}'.format(i=str(project_id)))
        project_name = dep.get_value('cons3rt.deploymentRun.project.name')
        return project_id, project_name

    def release_myself(self):
        """From deployment properties on this host, gets the run ID and attempts to self-release

        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.release_myself')
        log.info('Attempting to release this run...')
        project_id, project_name = self.get_my_project()
        self.set_project_token(project_name=project_name)
        run_id = self.get_my_run_id()
        if not run_id:
            raise Cons3rtApiError('Problem getting my run ID to release myself')
        log.info('Attempting to release myself, deployment run ID: {i}'.format(i=str(run_id)))
        try:
            self.release_deployment_run(dr_id=run_id)
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem releasing deployment run ID: {i}'.format(i=str(run_id))) from exc
        log.info('Requested release of myself, deployment run ID: {i}'.format(i=str(run_id)))

    def delete_inactive_runs_for_myself(self):
        """Deletes inactive deployment runs for my deployment

        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.delete_inactive_runs_for_myself')
        log.info('Attempting to delete inactive deployment runs for my deployment...')
        project_id, project_name = self.get_my_project()
        self.set_project_token(project_name=project_name)
        my_run_id = self.get_my_run_id()
        if not my_run_id:
            raise Cons3rtApiError('Problem getting my run ID to delete myself')
        try:
            run_details = self.retrieve_deployment_run_details(dr_id=my_run_id)
        except Cons3rtApiError as exc:
            msg = 'Problem retrieving details on this deployment run ID: {i}'.format(i=str(my_run_id))
            raise Cons3rtApiError(msg) from exc
        if 'deployment' not in run_details.keys():
            msg = 'deployment data not found in run data: {d}'.format(d=str(run_details))
            raise Cons3rtApiError(msg)
        if 'if' not in run_details['deployment'].keys():
            msg = 'id data not found in deployment data for run ID [{i}]: {d}'.format(
                i=str(my_run_id), d=str(run_details['deployment']))
            raise Cons3rtApiError(msg)
        try:
            self.delete_inactive_runs_for_deployment(deployment_id=run_details['deployment']['id'])
        except Cons3rtApiError as exc:
            msg = 'Problem deleting inactive deployment runs for my deployment ID: {i}'.format(
                i=str(run_details['deployment']['id']))
            raise Cons3rtApiError(msg) from exc
        log.info('Completed deleting inactive deployment runs for my deployment ID: {i}'.format(
            i=str(run_details['deployment']['id'])))

    def delete_inactive_runs_for_deployment(self, deployment_id):
        """Deletes only the inactive runs for the deployment ID

        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.delete_inactive_runs_for_deployment')
        try:
            inactive_dr_list = self.list_inactive_run_ids_for_deployment(deployment_id=deployment_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing inactive deployment runs for deployment ID: {i}'.format(i=str(deployment_id))
            raise Cons3rtApiError(msg) from exc
        for inactive_dr in inactive_dr_list:
            log.info('Deleting inactive run for deployment ID {d}: {r}'.format(
                d=str(deployment_id), r=str(inactive_dr['id'])))
            try:
                self.delete_inactive_run(dr_id=inactive_dr['id'])
            except Cons3rtApiError as exc:
                log.warning('Problem deleting inactive run ID: {i}\n{e}'.format(i=str(inactive_dr['id']), e=str(exc)))

    def list_host_ids_in_run(self, dr_id):
        """Returns a list of host IDs in a deployment run

        :param dr_id: (int) ID of the deployment run
        :return: (list) of host IDs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_host_ids_in_run')

        # Ensure the dr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError as exc:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.info('Retrieving details on run ID: {i}'.format(i=str(dr_id)))
        try:
            dr_details = self.retrieve_deployment_run_details(dr_id=dr_id)
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem retrieving details on run ID: {i}'.format(i=str(dr_id))) from exc

        if 'deploymentRunHosts' not in dr_details:
            raise Cons3rtApiError('deploymentRunHosts not found in run details: {d}'.format(d=str(dr_details)))

        if not isinstance(dr_details['deploymentRunHosts'], list):
            raise Cons3rtApiError('expected deploymentRunHosts to be a list, found: {t}'.format(
                t=dr_details['deploymentRunHosts'].__class__.__name__))

        host_ids = []
        for run_host in dr_details['deploymentRunHosts']:
            if 'id' not in run_host:
                log.warning('id not found in run host details: {d}'.format(d=run_host))
                continue
            host_ids.append(run_host['id'])
        log.info('Found {n} host IDs in DR ID: {i}'.format(n=str(len(host_ids)), i=str(dr_id)))
        return host_ids

    def list_detailed_hosts_in_run(self, dr_id):
        """Returns a list of host details in a deployment run

        :param dr_id: (int) ID of the deployment run
        :return: (tuple) host_details_list, dr_details
            1. A list of detailed host dict data in the provided deployment run ID
            2. DR dict data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_detailed_hosts_in_run')

        # Ensure the dr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError as exc:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.info('Retrieving details on run ID: {i}'.format(i=str(dr_id)))
        try:
            dr_details = self.retrieve_deployment_run_details(dr_id=dr_id)
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem retrieving details on run ID: {i}'.format(i=str(dr_id))) from exc

        if 'deploymentRunHosts' not in dr_details:
            raise Cons3rtApiError('deploymentRunHosts not found in run details: {d}'.format(d=str(dr_details)))

        if not isinstance(dr_details['deploymentRunHosts'], list):
            raise Cons3rtApiError('expected deploymentRunHosts to be a list, found: {t}'.format(
                t=dr_details['deploymentRunHosts'].__class__.__name__))

        host_details_list = []
        for run_host in dr_details['deploymentRunHosts']:
            if 'id' not in run_host:
                log.warning('id not found in run host details: {d}'.format(d=run_host))
                continue
            try:
                host_details = self.retrieve_deployment_run_host_details(dr_id=dr_id, drh_id=run_host['id'])
            except Cons3rtApiError as exc:
                msg = 'Problem retrieving details on host ID {h} in deployment run: {r}'.format(
                    h=str(run_host['id']), r=str(dr_id))
                raise Cons3rtApiError(msg) from exc

            host_details_list.append(host_details)
        log.info('Retrieved details for {n} hosts in DR ID: {i}'.format(n=str(len(host_details_list)), i=str(dr_id)))
        return host_details_list, dr_details

    def perform_host_action(self, dr_id, dr_host_id, action, cpu=None, ram=None):
        """Performs the provided host action on the host ID

        :param dr_id: (int) ID of the deployment run
        :param dr_host_id: (int) ID of the deployment run host
        :param action: (str) host action to perform
        :param cpu: (int) number of CPUs if the action if the action is resize
        :param ram: (int) amount of ram in megabytes if the action is resize
        :return: None
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.perform_host_action')

        # Ensure the dr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError as exc:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=dr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the dr_host_id is an int
        if not isinstance(dr_host_id, int):
            try:
                dr_host_id = int(dr_host_id)
            except ValueError as exc:
                msg = 'dr_host_id arg must be an Integer, found: {t}'.format(t=dr_host_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure action is a string
        if not isinstance(action, str):
            msg = 'action arg must be an string, found: {t}'.format(t=action.__class__.__name__)
            raise Cons3rtApiError(msg)

        # Ensure CPU and RAM provided for RESIZE action
        if action == 'RESIZE':
            if not cpu:
                raise Cons3rtApiError('Action RESIZE must include a value for cpu')
            if not ram:
                raise Cons3rtApiError('Action RESIZE must include a value for ram')

        # Perform the host action
        log.info('Performing [{a}] on DR ID {r} host ID: {h}...'.format(
            a=action, r=str(dr_id), h=str(dr_host_id)))
        try:
            self.cons3rt_client.perform_host_action(
                dr_id=dr_id,
                dr_host_id=dr_host_id,
                action=action,
                cpu=cpu,
                ram=ram
            )
        except Cons3rtClientError as exc:
            msg = 'Problem performing action [{a}] on DR ID {r} host ID: {h}'.format(
                a=action, r=str(dr_id), h=str(dr_host_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Completed [{a}] on DR ID {r} host ID: {h}'.format(a=action, r=str(dr_id), h=str(dr_host_id)))

    @staticmethod
    def get_inter_host_action_delay_for_cloud_type(cloud_type=None):
        """Returns the ideal delay time between host actions based on cloud type

        :param cloud_type: (str) cloud type
        :return: (int) delay in seconds
        """
        worst_case_delay_sec = 5
        if not cloud_type:
            return worst_case_delay_sec
        cloud_type = cloud_type.lower()
        if cloud_type in ['vcloud', 'vmware']:
            return worst_case_delay_sec
        elif cloud_type == 'openStack':
            return worst_case_delay_sec
        elif cloud_type in ['aws', 'amazon']:
            return 2
        elif cloud_type == 'azure':
            return 2
        else:
            return worst_case_delay_sec

    def perform_host_action_for_run(self, dr_id, action, cpu=None, ram=None, inter_host_action_delay_sec=None):
        """Performs the provided host action on the dr_id

        :param dr_id: (int) ID of the deployment run
        :param action: (str) host action to perform
        :param cpu: (int) number of CPUs if the action if the action is resize
        :param ram: (int) amount of ram in megabytes if the action is resize
        :param inter_host_action_delay_sec: (int) number of seconds between hosts
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.perform_host_action_for_run')
        log.info('Getting a list of host IDs in run: {i}'.format(i=str(dr_id)))
        try:
            hosts, dr_info = self.list_detailed_hosts_in_run(dr_id=dr_id)
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem listing hosts in run: {i}'.format(i=str(dr_id))) from exc

        # Set the host action delay higher for vCloud and OpenStack
        vr_type = None
        if not inter_host_action_delay_sec:
            if 'virtualizationRealm' in dr_info:
                if 'virtualizationRealmType' in dr_info['virtualizationRealm']:
                    vr_type = dr_info['virtualizationRealm']['virtualizationRealmType']
                    log.info('Found virtualization realm type: {t}'.format(t=vr_type))
                else:
                    log.warning('virtualizationRealmType data not found in DR info: {d}'.format(
                        d=str(dr_info['virtualizationRealm'])))
            else:
                log.warning('virtualizationRealm data not found in DR info: {d}'.format(d=str(dr_info)))
        inter_host_action_delay_sec = self.get_inter_host_action_delay_for_cloud_type(cloud_type=vr_type)
        log.info('Using inter host action delay: {s} sec'.format(s=str(inter_host_action_delay_sec)))
        results = []

        # Perform actions on each host ID
        for host in hosts:
            required_fields = ['id', 'systemRole', 'disks']
            requirements = True
            for required_field in required_fields:
                if required_field not in host:
                    log.warning('Required data {f} not found in host data: {d}'.format(f=required_field, d=str(host)))
                    requirements = False
                    break
            if not requirements:
                continue
            # Skip if the host has an action in progress
            if 'hostActionInProcess' in host:
                log.info('Found [hostActionInProcess] for host [{h}]: {d}'.format(
                    h=str(host['id']), d=str(host['hostActionInProcess'])))
                if host['hostActionInProcess']:
                    log.info('Skipping DR [{d}] host with a host action already in progress: {h}'.format(
                        d=str(dr_id), h=str(host['id'])))
                    continue
                else:
                    log.info('No host action in progress for DR [{d}] host [{h}]'.format(
                        d=str(dr_id), h=str(host['id'])))
            else:
                log.info('No data returned for [hostActionInProcess] for host [{h}]'.format(h=str(host['id'])))
            total_disk_capacity_mb = 0
            for disk in host['disks']:
                if 'capacityInMegabytes' not in disk:
                    log.warning('No capacityInMegabytes found in disk data: {d}'.format(d=str(disk)))
                    continue
                total_disk_capacity_mb += disk['capacityInMegabytes']
            total_disk_capacity_gb = total_disk_capacity_mb / 1024
            log.info('Found {n} disks with capacity {g} GBs for host: {h}'.format(
                h=str(host['id']), n=str(len(host['disks'])), g=str(total_disk_capacity_gb)))
            host_action_result = HostActionResult(
                dr_id=dr_id,
                dr_name=dr_info['name'],
                host_id=host['id'],
                host_role=host['systemRole'],
                action=action,
                request_time=datetime.datetime.now().strftime('%Y%m%d-%H%M%S'),
                num_disks=len(host['disks']),
                storage_gb=total_disk_capacity_gb
            )
            try:
                self.perform_host_action(
                    dr_id=dr_id,
                    dr_host_id=host['id'],
                    action=action,
                    cpu=cpu,
                    ram=ram
                )
            except Cons3rtApiError as exc:
                err_msg = 'Problem performing host action [{a}] on host ID: {i}\n{e}'.format(
                    a=action, i=str(host['id']), e=str(exc))
                log.warning(err_msg)
                host_action_result.set_err_msg(err_msg=err_msg)
                host_action_result.set_fail()
            else:
                host_action_result.set_success()
            results.append(host_action_result)
            log.info('Waiting {s} sec to perform the next host action for run ID {i}...'.format(
                s=str(inter_host_action_delay_sec), i=str(dr_id)))
            time.sleep(inter_host_action_delay_sec)
        log.info('Completed host action [{a}] on hosts in run ID: {i}'.format(a=action, i=str(dr_id)))
        return results

    def perform_host_action_for_run_list_with_delay(self, drs, action, inter_run_action_delay_sec=5):
        """Attempts to perform the provided action for all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data
        :param action: (str) host action to perform
        :param inter_run_action_delay_sec: (int) Amount of time to wait in between run actions
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.perform_host_action_for_run_list_with_delay')

        log.info('Using inter-run delay of {t} seconds'.format(t=str(inter_run_action_delay_sec)))

        # Perform actions for each run, with a delay in between, and collect results
        all_results = []
        for dr in drs:
            log.info('Attempting to perform action [{a}] for hosts in DR ID: {i}'.format(
                a=action, i=str(dr['id'])))
            try:
                self.set_project_token(project_name=dr['project']['name'])
                results = self.perform_host_action_for_run(dr_id=dr['id'], action=action)
            except Cons3rtApiError as exc:
                raise Cons3rtApiError('Problem performing action {a} for run ID: {i}'.format(
                    a=action, i=str(dr['id']))) from exc
            else:
                all_results += results
            log.info('Waiting {t} seconds to move on to the next DR...'.format(t=str(inter_run_action_delay_sec)))
            time.sleep(inter_run_action_delay_sec)
        return all_results

    def create_run_snapshots(self, dr_id):
        """Attempts to creates snapshots for all hosts in the provided DR ID

        :param dr_id: (int) ID of the deployment run
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        try:
            results = self.perform_host_action_for_run(
                dr_id=dr_id,
                action='CREATE_SNAPSHOT'
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem creating snapshot for run ID: {i}'.format(i=str(dr_id))) from exc
        return results

    def restore_run_snapshots(self, dr_id):
        """Attempts to creates snapshots for all hosts in the provided DR ID

        :param dr_id: (int) ID of the deployment run
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        try:
            results = self.perform_host_action_for_run(
                dr_id=dr_id,
                action='RESTORE_SNAPSHOT'
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem restoring snapshot for run ID: {i}'.format(i=str(dr_id))) from exc
        return results

    def power_off_run(self, dr_id):
        """Attempts to power off all hosts in the provided DR ID

        :param dr_id: (int) ID of the deployment run
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        try:
            results = self.perform_host_action_for_run(
                dr_id=dr_id,
                action='POWER_OFF'
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem performing power off for run ID: {i}'.format(i=str(dr_id))) from exc
        return results

    def power_on_run(self, dr_id):
        """Attempts to power on all hosts in the provided DR ID

        :param dr_id: (int) ID of the deployment run
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        try:
            results = self.perform_host_action_for_run(
                dr_id=dr_id,
                action='POWER_ON'
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem performing power on for run ID: {i}'.format(i=str(dr_id))) from exc
        return results

    def restore_run_snapshots_multiple(self, drs):
        return self.process_run_snapshots_multiple(drs=drs, action='RESTORE_SNAPSHOT')

    def create_run_snapshots_multiple(self, drs):
        return self.process_run_snapshots_multiple(drs=drs, action='CREATE_SNAPSHOT')

    def process_run_snapshots_multiple(self, drs, action):
        """Attempts to creates snapshots for all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data
        :param action: (str) CREATE_SNAPSHOT | RESTORE_SNAPSHOT
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_run_snapshots_multiple')
        try:
            all_results = self.perform_host_action_for_run_list(
                drs=drs,
                action=action
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem performing action [{a}] on DR list'.format(a=action)) from exc

        successful_snapshots_count = 0
        failed_snapshots_count = 0
        snapshot_disk_count = 0
        snapshot_disk_capacity_gb = 0
        for host_action_result in all_results:
            if not isinstance(host_action_result, HostActionResult):
                continue
            if host_action_result.is_fail():
                failed_snapshots_count += 1
            else:
                successful_snapshots_count += 1
                snapshot_disk_count += host_action_result.num_disks
                snapshot_disk_capacity_gb += host_action_result.storage_gb
        log.info('Requested {n} total snapshots with action: {a}'.format(n=str(len(all_results)), a=action))
        log.info('Completed with {s} successful snapshots and {f} failed snapshots'.format(
            s=str(successful_snapshots_count),
            f=str(failed_snapshots_count)))
        log.info('[{a}] succeeded on a total of {n} disks with a total storage capacity of {g} GBs'.format(
            a=action, n=str(snapshot_disk_count), g=str(snapshot_disk_capacity_gb)))
        return all_results

    def power_off_multiple_runs(self, drs):
        """Attempts to power off all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.power_off_multiple_runs')
        log.info('Powering off multiple runs...')
        try:
            all_results = self.perform_host_action_for_run_list(
                drs=drs,
                action='POWER_OFF'
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem powering off runs from list: {r}'.format(
                r=str(drs))) from exc
        return all_results

    def power_on_multiple_runs(self, drs):
        """Attempts to power on all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.power_on_multiple_runs')
        log.info('Powering off multiple runs...')
        try:
            all_results = self.perform_host_action_for_run_list(
                drs=drs,
                action='POWER_ON'
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem powering on runs from list: {r}'.format(
                r=str(drs))) from exc
        return all_results

    def perform_host_action_for_run_list(self, drs, action):
        """Attempts to perform the provided action for all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data containing at least:
            {
                'id',
                'deploymentRunStatus',
                'project',
                'name'
            }
        :param action: (str) host action to perform
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.perform_host_action_for_run_list')

        log.info('Attempting to perform action {a} on run list'.format(a=action))

        # Ensure required data was provided
        if not isinstance(drs, list):
            raise Cons3rtApiError('Provided drs must be a list, found: {t}'.format(t=drs.__class__.__name__))
        for dr in drs:
            if not isinstance(dr, dict):
                raise Cons3rtApiError('Provided dr data was not a dict, found: {t}'.format(t=dr.__class__.__name__))
            if 'id' not in dr:
                raise Cons3rtApiError('id not found in DR data: {d}'.format(d=str(dr)))
            if 'deploymentRunStatus' not in dr:
                raise Cons3rtApiError('deploymentRunStatus not found in DR data: {d}'.format(d=str(dr)))
            if 'project' not in dr:
                raise Cons3rtApiError('project not found in DR data: {d}'.format(d=str(dr)))
            if 'name' not in dr['project']:
                raise Cons3rtApiError('project name not found in DR data: {d}'.format(d=str(dr)))

        # Get the run ID if available
        my_run_id = self.get_my_run_id()

        # Filter runs to take actions on by status and remove this run ID
        action_approved_statii = ['RESERVED', 'TESTED']
        action_drs = []
        for dr in drs:
            if my_run_id == dr['id']:
                log.info('Not including MY OWN run ID on the action DR list: {i}'.format(i=str(my_run_id)))
                continue
            if dr['deploymentRunStatus'] not in action_approved_statii:
                log.info('Not including run ID {i} with status {s} on the action DR list'.format(
                    i=str(dr['id']), s=dr['deploymentRunStatus']))
                continue

            # Retrieve DR details if VR data is not included
            if 'virtualizationRealm' not in dr.keys():
                log.info('Adding DR to list of DRs to take action {a}: {i}'.format(a=action, i=str(dr['id'])))
                try:
                    dr = self.retrieve_deployment_run_details(dr_id=dr['id'])
                except Cons3rtApiError as exc:
                    log.warning('Problem retrieving details on DR ID {i}\n{e}'.format(i=str(dr['id']), e=str(exc)))

            log.info('Adding DR to list of DRs to take action {a}: {i}'.format(a=action, i=str(dr['id'])))
            action_drs.append(dr)

        log.info('Sorting run list by cloud type...')
        vcloud_drs = []
        openstack_drs = []
        aws_drs = []
        azure_drs = []
        other_drs = []

        # Split up DRs by VR type, each has a different delay
        for dr in action_drs:
            if 'virtualizationRealm' in dr:
                if 'virtualizationRealmType' in dr['virtualizationRealm']:
                    if dr['virtualizationRealm']['virtualizationRealmType'] == 'VCloud':
                        vcloud_drs.append(dr)
                    elif dr['virtualizationRealm']['virtualizationRealmType'] == 'OpenStack':
                        openstack_drs.append(dr)
                    elif dr['virtualizationRealm']['virtualizationRealmType'] == 'Amazon':
                        aws_drs.append(dr)
                    elif dr['virtualizationRealm']['virtualizationRealmType'] == 'Azure':
                        azure_drs.append(dr)
                    else:
                        other_drs.append(dr)
                else:
                    other_drs.append(dr)
            else:
                other_drs.append(dr)
        log.info('Found {n} VCloud DRs'.format(n=str(len(vcloud_drs))))
        log.info('Found {n} Openstack DRs'.format(n=str(len(openstack_drs))))
        log.info('Found {n} Amazon DRs'.format(n=str(len(aws_drs))))
        log.info('Found {n} Azure DRs'.format(n=str(len(azure_drs))))
        log.info('Found {n} DRs with VR type not specified'.format(n=str(len(other_drs))))

        all_results = []
        if len(aws_drs) > 0:
            log.info('Performing host actions {a} on AWS runs...'.format(a=action))
            try:
                all_results += self.perform_host_action_for_run_list_with_delay(
                    drs=action_drs,
                    action=action,
                    inter_run_action_delay_sec=self.get_inter_host_action_delay_for_cloud_type(cloud_type='Amazon')
                )
            except Cons3rtApiError as exc:
                raise Cons3rtApiError('Problem performing host action [{a}] for Amazon runs'.format(a=action)) from exc

        if len(azure_drs) > 0:
            log.info('Performing host actions {a} on Azure runs...'.format(a=action))
            try:
                all_results += self.perform_host_action_for_run_list_with_delay(
                    drs=action_drs,
                    action=action,
                    inter_run_action_delay_sec=self.get_inter_host_action_delay_for_cloud_type(cloud_type='Azure')
                )
            except Cons3rtApiError as exc:
                raise Cons3rtApiError('Problem performing host action [{a}] for Azure runs'.format(a=action)) from exc

        if len(openstack_drs) > 0:
            log.info('Performing host actions {a} on Openstack runs...'.format(a=action))
            try:
                all_results += self.perform_host_action_for_run_list_with_delay(
                    drs=action_drs,
                    action=action,
                    inter_run_action_delay_sec=self.get_inter_host_action_delay_for_cloud_type(cloud_type='Openstack')
                )
            except Cons3rtApiError as exc:
                raise Cons3rtApiError('Problem performing host action [{a}] for Openstack runs'.format(
                    a=action)) from exc

        if len(vcloud_drs) > 0:
            log.info('Performing host actions {a} on VCloud runs...'.format(a=action))
            try:
                all_results += self.perform_host_action_for_run_list_with_delay(
                    drs=action_drs,
                    action=action,
                    inter_run_action_delay_sec=self.get_inter_host_action_delay_for_cloud_type(cloud_type='VCloud')
                )
            except Cons3rtApiError as exc:
                raise Cons3rtApiError('Problem performing host action [{a}] for VCloud runs'.format(
                    a=action)) from exc

        if len(other_drs) > 0:
            log.info('Performing host actions {a} on runs with unknown cloud type...'.format(a=action))
            try:
                all_results += self.perform_host_action_for_run_list_with_delay(
                    drs=action_drs,
                    action=action,
                    inter_run_action_delay_sec=self.get_inter_host_action_delay_for_cloud_type(cloud_type='other')
                )
            except Cons3rtApiError as exc:
                raise Cons3rtApiError('Problem performing host action [{a}] for other runs'.format(
                    a=action)) from exc

        successful_action_count = 0
        failed_action_count = 0
        for host_action_result in all_results:
            if not isinstance(host_action_result, HostActionResult):
                continue
            if host_action_result.is_fail():
                failed_action_count += 1
            else:
                successful_action_count += 1
        log.info('Requested {n} total hosts with action: {a}'.format(n=str(len(all_results)), a=action))
        log.info('Completed [{a}] with {s} successful and {f} failed'.format(
            a=action,
            s=str(successful_action_count),
            f=str(failed_action_count)))
        return all_results

    def list_project_virtualization_realms_for_team(self, team_id):
        """Given a team ID, returns a list of the virtualization realms that the team's projects
        are allowed to deploy into

        Note: This is a different list then the team's managed virtualization realms

        :param team_id: (int) ID of the team
        :return: (list) of virtualization realms
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_project_virtualization_realms_for_team')

        # Ensure the team_id is an int
        if not isinstance(team_id, int):
            try:
                team_id = int(team_id)
            except ValueError as exc:
                msg = 'team_id arg must be an Integer, found: {t}'.format(t=team_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.info('Attempting to get a list of projects in team ID: {i}'.format(i=str(team_id)))
        project_names = []
        try:
            projects = self.list_projects_in_team(team_id=team_id)
        except Cons3rtApiError as exc:
            msg = 'Problem getting a list of projects in team ID: {i}'.format(i=str(team_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Found {n} projects in team ID: {i}'.format(n=str(len(projects)), i=str(team_id)))
        for project in projects:
            project_names.append(project['name'])
            log.info('Found project [{n}] with ID: {i}'.format(i=str(project['id']), n=project['name']))
        log.info('Attempting to get a list of VRs accessible by projects in team ID: {i}'.format(i=str(team_id)))
        vrs = []
        vr_project_list = []
        for project in projects:
            try:
                vr_project_list += self.list_virtualization_realms_for_project(project_id=project['id'])
            except Cons3rtApiError as exc:
                msg = 'Problem listing virtualization realms for project: {i}'.format(i=str(project['id']))
                raise Cons3rtApiError(msg) from exc
        for found_vr in vr_project_list:
            already_added = False
            for vr in vrs:
                if vr['id'] == found_vr['id']:
                    already_added = True
            if not already_added:
                vrs.append(found_vr)
        log.info('Found {n} unique VRs accessible from projects in team ID: {i}'.format(
            n=str(len(vrs)), i=str(team_id)))
        for vr in vrs:
            log.info('Found VR [{n}] with ID: {i}'.format(n=vr['name'], i=str(vr['id'])))
        return vrs

    def list_active_runs_in_team(self, team_id):
        """Returns a list of active deployment runs in the provided team ID

        May include remote access runs and other VR-DRs not owned by the team's projects

        :param team_id: (int) ID of the team
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_active_runs_in_team')

        # Ensure the team_id is an int
        if not isinstance(team_id, int):
            try:
                team_id = int(team_id)
            except ValueError as exc:
                msg = 'team_id arg must be an Integer, found: {t}'.format(t=team_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # List all the virtualization realms that this team's projects can deploy into
        try:
            vrs = self.list_project_virtualization_realms_for_team(team_id=team_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing project virtualization realms for team: {i}'.format(i=str(team_id))
            raise Cons3rtApiError(msg) from exc

        # Get a list of DR IDs
        log.info('Retrieving the list of active DRs in each virtualization realm...')
        drs = []
        for vr in vrs:
            try:
                vr_drs = self.list_active_deployment_runs_in_virtualization_realm(vr_id=vr['id'])
            except Cons3rtApiError as exc:
                msg = 'Problem listing active DRs from VR ID: {i}'.format(i=str(vr['id']))
                raise Cons3rtApiError(msg) from exc
            log.info('Found {n} DRs in VR ID: {i}'.format(n=str(len(vr_drs)), i=str(vr['id'])))
            for vr_dr in vr_drs:
                drs.append(vr_dr)
        log.info('Found {n} active deployment runs in team ID: {i}'.format(i=str(team_id), n=str(len(drs))))
        return drs

    def list_active_runs_in_team_owned_projects(self, team_id):
        """Returns a list of active deployment runs in the provided team ID in owned projects

        May include remote access runs and other VR-DRs not owned by the team's projects

        :param team_id: (int) ID of the team
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_active_runs_in_team_owned_projects')
        team_details = self.get_team_details(team_id=team_id)
        if 'ownedProjects' not in team_details.keys():
            msg = 'ownedProjects not found in team detail data: {d}'.format(d=str(team_details))
            raise Cons3rtApiError(msg)
        owned_project_names = []
        team_owned_project_drs = []
        for project in team_details['ownedProjects']:
            if 'name' not in project.keys():
                log.warning('name not found in project data: {p}'.format(p=str(project)))
                continue
            owned_project_names.append(project['name'])
        team_drs = self.list_active_runs_in_team(team_id=team_id)

        # Filter on DRs in owned projects
        for team_dr in team_drs:
            if 'id' not in team_dr:
                log.warning('id not found in deployment run data: {p}'.format(p=str(team_dr)))
                continue
            if 'project' not in team_dr:
                log.warning('project not found in deployment run data: {p}'.format(p=str(team_dr)))
                continue
            if 'name' not in team_dr['project']:
                log.warning('name not found in deployment run data: {p}'.format(p=str(team_dr)))
                continue
            if team_dr['project']['name'] in owned_project_names:
                log.info('Adding DR {i} in project {p} to the list of team owned runs'.format(
                    i=str(team_dr['id']), p=team_dr['project']['name']))
                team_owned_project_drs.append(team_dr)
            else:
                log.info('Excluding DR {i} in project {p} to the list of of team owned runs'.format(
                    i=str(team_dr['id']), p=team_dr['project']['name']))
        log.info('Found {n} team [{t}] project-owned deployment runs'.format(
            n=str(len(team_owned_project_drs)), t=team_details['name']))
        return team_owned_project_drs

    def list_runs_in_project(self, project_id, search_type='SEARCH_ALL'):
        """Returns a list of deployment runs in the provided project ID, using the provided search type

        :param project_id: (int) ID of the project
        :param search_type: (str) defines to search for, all, inactive, or active DRs
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_runs_in_project')

        # Ensure the team_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # List all the virtualization realms that this project can deploy into
        try:
            vrs = self.list_virtualization_realms_for_project(project_id=project_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing project virtualization realms for project: {i}'.format(i=str(project_id))
            raise Cons3rtApiError(msg) from exc

        # Get a list of DR IDs
        log.info('Retrieving the list of DRs in each virtualization realm with search type: {t}'.format(t=search_type))
        drs = []
        for vr in vrs:
            try:
                vr_drs = self.list_deployment_runs_in_virtualization_realm(vr_id=vr['id'], search_type=search_type)
            except Cons3rtApiError as exc:
                msg = 'Problem listing DRs from VR ID [{i}] with search type: {t}'.format(
                    i=str(vr['id']), t=search_type)
                raise Cons3rtApiError(msg) from exc
            log.info('Found {n} DRs in VR ID: {i}'.format(n=str(len(vr_drs)), i=str(vr['id'])))
            for vr_dr in vr_drs:
                if 'project' not in vr_dr:
                    log.warning('Found DR with no project data: {d}'.format(d=str(vr_dr)))
                    continue
                if 'id' not in vr_dr['project']:
                    log.warning('No ID in DR project data: {d}'.format(d=str(vr_dr)))
                    continue
                if project_id == vr_dr['project']['id']:
                    log.info('Found project {p} DR: {i}'.format(p=str(project_id), i=str(vr_dr['id'])))
                    drs.append(vr_dr)
                else:
                    log.info('Found DR ID {i} not in project ID: {p}'.format(p=str(project_id), i=str(vr_dr['id'])))
        log.info('Found {n} deployment runs in project ID: {i}'.format(i=str(project_id), n=str(len(drs))))
        return drs

    def list_active_runs_in_project(self, project_id):
        """Returns a list of active deployment runs in the provided project ID

        :param project_id: (int) ID of the team
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        return self.list_runs_in_project(project_id=project_id, search_type='SEARCH_ACTIVE')

    def list_inactive_runs_in_project(self, project_id):
        """Returns a list of inactive deployment runs in the provided project ID

        :param project_id: (int) ID of the team
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        return self.list_runs_in_project(project_id=project_id, search_type='SEARCH_INACTIVE')

    def list_all_runs_in_project(self, project_id):
        """Returns a list of all deployment runs in the provided project ID

        :param project_id: (int) ID of the team
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        return self.list_runs_in_project(project_id=project_id, search_type='SEARCH_ALL')

    def list_host_details_in_team(self, team_id):
        """Lists details for every deployment run host deployed in the provided team ID

        :param team_id: (int) ID of the team
        :return: (list) of deployment run details, and a list of host details
        [
            "run": {run details}
            "hosts": [{host details}]
        ]
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_host_details_in_team')

        # Ensure the team_id is an int
        if not isinstance(team_id, int):
            try:
                team_id = int(team_id)
            except ValueError as exc:
                msg = 'team_id arg must be an Integer, found: {t}'.format(t=team_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.info('Attempting to list all host details for team ID: {i}'.format(i=str(team_id)))
        try:
            drs = self.list_active_runs_in_team(team_id=team_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing active runs in team ID: {i}'.format(i=str(team_id))
            raise Cons3rtApiError(msg) from exc

        team_drh_list = []
        team_drh_count = 0
        for dr in drs:
            if 'id' not in dr:
                log.warning('id not found in DR data: {d}'.format(d=str(dr)))
                continue
            log.info('Retrieving details for run ID: {i}'.format(i=str(dr['id'])))
            try:
                dr_drh_list, dr_details = self.list_detailed_hosts_in_run(dr_id=dr['id'])
            except Cons3rtApiError as exc:
                msg = 'Problem listing detailed host data for DR ID: {i}'.format(i=str(dr['id']))
                raise Cons3rtApiError(msg) from exc
            team_drh_list.append({
                'run': dr_details,
                'hosts': dr_drh_list
            })
            team_drh_count += len(dr_drh_list)
        log.info('Found {n} deployment run hosts in team ID {i}'.format(i=str(team_id), n=str(team_drh_count)))
        return team_drh_list

    def list_host_details_in_project(self, project_id):
        """Lists details for every deployment run host deployed in the provided project ID

        :param project_id: (int) ID of the project
        :return: (list) of deployment run details, and a list of host details
        [
            "run": {run details}
            "hosts": [{host details}]
        ]
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_host_details_in_project')

        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.info('Attempting to list all host details for project ID: {i}'.format(i=str(project_id)))
        try:
            drs = self.list_active_runs_in_project(project_id=project_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing active runs in project ID: {i}'.format(i=str(project_id))
            raise Cons3rtApiError(msg) from exc

        project_drh_list = []
        project_drh_count = 0
        for dr in drs:
            if 'id' not in dr:
                log.warning('id not found in DR data: {d}'.format(d=str(dr)))
                continue
            log.info('Retrieving details for run ID: {i}'.format(i=str(dr['id'])))
            try:
                dr_drh_list, dr_details = self.list_detailed_hosts_in_run(dr_id=dr['id'])
            except Cons3rtApiError as exc:
                msg = 'Problem listing detailed host data for DR ID: {i}'.format(i=str(dr['id']))
                raise Cons3rtApiError(msg) from exc
            project_drh_list.append({
                'run': dr_details,
                'hosts': dr_drh_list
            })
            project_drh_count += len(dr_drh_list)
        log.info('Found {n} deployment run hosts in project ID {i}'.format(i=str(project_id), n=str(project_drh_count)))
        return project_drh_list

    def update_virtualization_realm_reachability(self, vr_id):
        """Updates the virtualization realm's reachability

        :param vr_id: (int) ID of the virtualization realm
        :return: None
        :raises: Cons3rtClientError
        """
        log = logging.getLogger(self.cls_logger + '.update_virtualization_realm_reachability')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.info('Updating reachability status for virtualization realm ID: {i}'.format(i=str(vr_id)))
        try:
            self.cons3rt_client.update_virtualization_realm_reachability(vr_id=vr_id)
        except Cons3rtClientError as exc:
            msg = 'Problem updating reachability for virtualization realm ID: {i}'.format(i=str(vr_id))
            raise Cons3rtApiError(msg) from exc

    def update_virtualization_realm_reachability_for_cloud(self, cloud_id):
        """Updates virtualization realm reachability for all active VRs in the provided cloud ID

        :param cloud_id: (int) ID of the cloud
        :return: None
        :raises: Cons3rtClientError
        """
        log = logging.getLogger(self.cls_logger + '.update_virtualization_realm_reachability')

        # Delay between each reachability check
        inter_vr_delay_sec = 5

        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError as exc:
                msg = 'cloud_id arg must be an Integer, found: {t}'.format(t=cloud_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        log.info('Listing virtualization realms for cloud ID: {i}'.format(i=str(cloud_id)))
        try:
            vrs = self.list_virtualization_realms_for_cloud(cloud_id=cloud_id)
        except Cons3rtApiError as exc:
            msg = 'Problem retrieving the list of virtualization realms for cloud ID: {i}'.format(i=str(cloud_id))
            raise Cons3rtApiError(msg) from exc

        active_vrs = []
        for vr in vrs:
            if 'state' not in vr.keys() or 'id' not in vr.keys():
                log.warning('Virtualization realm has no state or id data: {d}'.format(d=str(vr)))
                continue
            if vr['state'] == 'ACTIVE':
                log.info('Adding active virtualization realm to the reachability update list: {i}'.format(
                    i=str(vr['id'])))
                active_vrs.append(vr)
            else:
                log.info('Excluding virtualization from the reachability update list in state [{s}]: {i}'.format(
                    s=str(vr['state']), i=str(vr['id'])))
                continue

        # Update reachability for each VR
        log.info('Updating reachability status for {n} active virtualization realms in cloud ID: {i}'.format(
            n=str(len(active_vrs)), i=str(cloud_id)))
        for vr in active_vrs:
            try:
                self.update_virtualization_realm_reachability(vr_id=vr['id'])
            except Cons3rtClientError as exc:
                msg = 'Problem updating reachability for virtualization realm ID: {i}'.format(i=str(vr['id']))
                raise Cons3rtApiError(msg) from exc
            log.info('Requested reachability update for virtualization realm ID: {i}'.format(i=str(vr['id'])))
            time.sleep(inter_vr_delay_sec)
        log.info('Completed virtualization realm reachability updates for cloud ID: {i}'.format(i=str(cloud_id)))

    def register_template_by_name_in_vr(self, vr_id, template_name):
        """Creates template registrations the template name the provided VR ID

        :param vr_id: (int) ID of the virtualization realm
        :param template_name: (str) name of the unregistered template to register
        return: (dict) of template registration data
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.register_template_by_name_in_vr')

        # Ensure the provider_vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        try:
            self.refresh_template_cache(vr_id=vr_id)
            unregistered_templates = self.list_unregistered_templates(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing unregistered templates in VR ID: {i}'.format(i=str(vr_id))
            raise Cons3rtApiError(msg) from exc

        template_found = False
        template_registration_data = []
        for unregistered_template in unregistered_templates:
            if 'virtRealmTemplateName' not in unregistered_template:
                log.warning('virtRealmTemplateName not found in template: {d}'.format(d=str(unregistered_template)))
                continue
            if unregistered_template['virtRealmTemplateName'] != template_name:
                continue
            template_found = True
            try:
                template_registration_data = self.create_template_registration(
                    vr_id=vr_id,
                    template_name=unregistered_template['virtRealmTemplateName']
                )
            except Cons3rtApiError as exc:
                msg = 'Problem registering template: {n}\n{e}'.format(
                    n=unregistered_template['virtRealmTemplateName'], e=str(exc))
                raise Cons3rtApiError(msg) from exc
            break

        if not template_found:
            msg = 'Unregistered template with name [{n}] not found in VR ID: {i}'.format(n=template_name, i=str(vr_id))
            raise Cons3rtApiError(msg)

        log.info('Successfully registered template [{n}] in VR ID: {i}'.format(n=template_name, i=str(vr_id)))
        return template_registration_data

    def register_all_templates_in_vr(self, vr_id):
        """Creates template registrations for all unregistered templates in the provided VR ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (tuple) a list of successfully registered template names and a list of failed ones
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.register_all_templates_in_vr')

        # Ensure the provider_vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        try:
            self.refresh_template_cache(vr_id=vr_id)
            unregistered_templates = self.list_unregistered_templates(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing unregistered templates in VR ID: {i}'.format(i=str(vr_id))
            raise Cons3rtApiError(msg) from exc

        # Track lists of template names that succeeded and failed for return
        successful_registrations = []
        failed_registrations = []

        for unregistered_template in unregistered_templates:
            if 'virtRealmTemplateName' not in unregistered_template:
                log.warning('virtRealmTemplateName not found in template: {d}'.format(d=str(unregistered_template)))
                continue
            try:
                self.create_template_registration(
                    vr_id=vr_id,
                    template_name=unregistered_template['virtRealmTemplateName']
                )
            except Cons3rtApiError as exc:
                msg = 'Problem registering template: {n}\n{e}'.format(
                    n=unregistered_template['virtRealmTemplateName'], e=str(exc))
                log.warning(msg)
                failed_registrations.append(unregistered_template['virtRealmTemplateName'])
            else:
                successful_registrations.append(unregistered_template['virtRealmTemplateName'])
        log.info('{n} template registrations succeeded in VR ID: {i}'.format(
            n=str(len(successful_registrations)), i=str(vr_id)))
        log.info('{n} template registrations failed in VR ID: {i}'.format(
            n=str(len(failed_registrations)), i=str(vr_id)))
        return successful_registrations, failed_registrations

    def share_template(self, provider_vr_id, template_registration_id, target_vr_ids):
        """Shares the provided template registration with this provided list
        of target virtualization realm IDs

        :param provider_vr_id: (int) ID of the template provider virtualization realm
        :param template_registration_id: (int) ID of the template registration
        :param target_vr_ids: (list) of IDs (int) of virtualization realms to share with
        :return: bool
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.share_template')

        # Ensure the provider_vr_id is an int
        if not isinstance(provider_vr_id, int):
            try:
                provider_vr_id = int(provider_vr_id)
            except ValueError as exc:
                msg = 'provider_vr_id arg must be an Integer, found: {t}'.format(t=provider_vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the template_registration_id is an int
        if not isinstance(template_registration_id, int):
            try:
                template_registration_id = int(template_registration_id)
            except ValueError as exc:
                msg = 'template_registration_id arg must be an Integer, found: {t}'.format(
                    t=template_registration_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the target VR IDs are a list of ints
        if not isinstance(target_vr_ids, list):
            raise Cons3rtApiError('Expected type list for target_vr_ids, found: {t}'.format(
                t=target_vr_ids.__class__.__name__))

        if len(target_vr_ids) < 1:
            log.info('No Target VRs to share template ID {r} from VR ID: {i}'.format(
                r=str(template_registration_id), i=str(provider_vr_id)))
            return

        # Ensure the target_vr_id is a list of ints
        for target_vr_id in target_vr_ids:
            if not isinstance(target_vr_id, int):
                try:
                    target_vr_id = int(target_vr_id)
                except ValueError as exc:
                    msg = 'target_vr_id arg must be an Integer, found: {t}'.format(
                        t=target_vr_id.__class__.__name__)
                    raise Cons3rtApiError(msg) from exc

        target_vrs_str = ','.join(str(x) for x in target_vr_ids)
        log.info('Sharing template registration ID {r} from VR ID: {i} to VR list: {s}'.format(
            r=str(template_registration_id), i=str(provider_vr_id), s=target_vrs_str))
        try:
            result = self.cons3rt_client.share_template(
                vr_id=provider_vr_id,
                template_registration_id=template_registration_id,
                target_vr_ids=target_vr_ids
            )
        except Cons3rtClientError as exc:
            msg = 'Problem sharing template {r} from VR ID {i} to list: {s}'.format(
                r=str(template_registration_id), i=str(provider_vr_id), s=target_vrs_str)
            raise Cons3rtApiError(msg) from exc
        if not result:
            msg = 'Sharing template {r} from VR ID {i} to list [{s}] returned false'.format(
                r=str(template_registration_id), i=str(provider_vr_id), s=target_vrs_str)
            raise Cons3rtApiError(msg)

    def share_template_to_vrs(self, provider_vr_id, template, vr_ids, subscribe=True, online=True,
                              subscriber_vrs_subscriptions=None):
        """Share a template to virtualization realms

        :param provider_vr_id: (int) ID of the virtualization realm where the template is registered
        :param template: (dict) of template data
        :param vr_ids: (list) VR IDs to share the templates with
        :param subscribe: (bool) Set True to have the shared virtualization realm also subscribe to the template
        :param online: (bool) Set True to bring the template online in the subscriber virtualization realm
        :param subscriber_vrs_subscriptions: (list) of dict subscription data for each subscriber VR ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.share_template_to_vrs')
        if not isinstance(provider_vr_id, int):
            try:
                provider_vr_id = int(provider_vr_id)
            except ValueError as exc:
                msg = 'provider_vr_id arg must be an Integer, found: {t}'.format(t=provider_vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc
        if not isinstance(template, dict):
            raise Cons3rtApiError('template data expected dict found: {t}'.format(t=template.__class__.__name__))
        if 'id' not in template.keys():
            raise Cons3rtApiError('id not found in template data: {d}'.format(d=template))
        if 'templateData' not in template.keys():
            raise Cons3rtApiError('templateData not found in template data: {d}'.format(d=template))
        if 'virtRealmTemplateName' not in template['templateData'].keys():
            raise Cons3rtApiError('virtRealmTemplateName not found in template data: {d}'.format(d=template))
        if not isinstance(vr_ids, list):
            raise Cons3rtApiError('vr_ids arg expected int found: {t}'.format(t=vr_ids.__class__.__name__))
        if not isinstance(subscribe, bool):
            raise Cons3rtApiError('subscribe arg expected bool found: {t}'.format(t=subscribe.__class__.__name__))
        if not isinstance(online, bool):
            raise Cons3rtApiError('online arg expected bool found: {t}'.format(t=online.__class__.__name__))

        template_name = template['templateData']['virtRealmTemplateName']
        try:
            reg_details = self.retrieve_template_registration(
                vr_id=provider_vr_id,
                template_registration_id=template['id']
            )
        except Cons3rtApiError as exc:
            msg = 'Problem retrieving details on template {n} registration: {i}'.format(
                n=template_name, i=str(template['id']))
            raise Cons3rtApiError(msg) from exc

        # Get a list of VR IDs
        subscriber_vr_ids = []
        for vr_id in vr_ids:
            if vr_id != provider_vr_id:
                subscriber_vr_ids.append(vr_id)

        # Determine which VRs already have the template shared
        vr_ids_to_share = []
        if 'virtRealmsSharedTo' not in reg_details.keys():
            log.info('Template {n} is not shared to any VRs from provider VR ID: {i}'.format(
                n=template_name, i=str(provider_vr_id)))
            vr_ids_to_share = list(subscriber_vr_ids)
        else:
            for subscriber_vr_id in subscriber_vr_ids:
                already_shared = False
                for already_shared_vr in reg_details['virtRealmsSharedTo']:
                    if already_shared_vr['id'] == subscriber_vr_id:
                        log.debug('Template {n} already shared to VR ID {i}'.format(
                            n=template_name, i=str(subscriber_vr_id)))
                        already_shared = True
                        break
                if not already_shared:
                    vr_ids_to_share.append(subscriber_vr_id)

        # Share the template with the list of VR IDs
        if len(vr_ids_to_share) > 0:
            log.info('Attempting to share template {n} to {v} VRs'.format(n=template_name, v=str(len(vr_ids_to_share))))
            try:
                self.share_template(
                    provider_vr_id=provider_vr_id,
                    template_registration_id=template['id'],
                    target_vr_ids=vr_ids_to_share
                )
            except Cons3rtApiError as exc:
                msg = 'Problem sharing template {i} from provider ID {p} to VR IDs: {v}'.format(
                    i=str(template['id']), p=str(provider_vr_id), v=str(subscriber_vr_ids))
                raise Cons3rtApiError(msg) from exc

        if not subscribe:
            log.info('Template [{n}] will not be subscribed to in the shared VRs'.format(n=template_name))
            return

        create_subscription_vr_ids = []
        for subscriber_vr_id in subscriber_vr_ids:
            subscriber_vr_existing_subs = None
            if subscriber_vrs_subscriptions:
                for subscriber_vr_subscriptions in subscriber_vrs_subscriptions:
                    if subscriber_vr_subscriptions['subscriber_vr_id'] == subscriber_vr_id:
                        subscriber_vr_existing_subs = subscriber_vr_subscriptions['subscriptions']
                        break
            if not subscriber_vr_existing_subs:
                subscriber_vr_existing_subs = self.list_template_subscriptions_in_virtualization_realm(
                    vr_id=subscriber_vr_id
                )
            existing_subscription = False
            for subscriber_vr_existing_sub in subscriber_vr_existing_subs:
                if subscriber_vr_existing_sub['templateRegistration']['templateUuid'] == reg_details['templateUuid']:
                    log.info('Template {n} already subscribed in VR ID: {i}'.format(
                        n=template_name, i=str(subscriber_vr_id)))
                    existing_subscription = True
            if not existing_subscription:
                create_subscription_vr_ids.append(subscriber_vr_id)

        for vr_id in create_subscription_vr_ids:
            log.info('Subscribing to template {n} in VR ID: {i}'.format(n=template_name, i=str(vr_id)))
            try:
                subscription = self.create_template_subscription(
                    vr_id=vr_id, template_registration_id=template['id']
                )
            except Cons3rtApiError as exc:
                msg = 'Problem subscribing template [{n}] to VR ID: {i}'.format(n=template_name, i=str(vr_id))
                raise Cons3rtApiError(msg) from exc

            if not online:
                log.info('Template [{n}] will not set online in VR ID: {i}'.format(n=template_name, i=str(vr_id)))
                continue

            # TODO when Tracker 4459 is fixed, include the reg_details['templateData']['maxCpu']
            max_ram_mb = 131072
            max_cpus = 16
            if 'templateData' in reg_details.keys():
                if 'maxRamInMegabytes' in reg_details['templateData']:
                    max_ram_mb = reg_details['templateData']['maxRamInMegabytes']
                if 'maxNumCpus' in reg_details['templateData']:
                    max_cpus = reg_details['templateData']['maxNumCpus']

            log.info('Setting template {n} online in VR ID: {i}'.format(n=template_name, i=str(vr_id)))

            try:
                self.update_template_subscription(
                    vr_id=vr_id,
                    template_subscription_id=subscription['id'],
                    offline=False,
                    state='IN_DEVELOPMENT',
                    max_cpus=max_cpus,
                    max_ram_mb=max_ram_mb
                )
            except Cons3rtApiError as exc:
                msg = 'Problem setting template [{n}] online in VR ID: {i}'.format(n=template_name, i=str(vr_id))
                raise Cons3rtApiError(msg) from exc
        log.info('Completed sharing and subscribing template [{n}] from VR ID: {i}'.format(
            n=template_name, i=str(provider_vr_id)))

    def share_templates_to_vrs(self, provider_vr_id, templates, vr_ids, subscribe=True, online=True):
        """Share a template to virtualization realms

        :param provider_vr_id: (int) ID of the virtualization realm where the template is registered
        :param templates: (list) of template data as dict
        :param vr_ids: (list) VR IDs to share the templates with
        :param subscribe: (bool) Set True to have the shared virtualization realm also subscribe to the template
        :param online: (bool) Set True to bring the template online in the subscriber virtualization realm
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.share_templates_to_vrs')
        if not isinstance(templates, list):
            raise Cons3rtApiError('templates arg must be an list, found: {t}'.format(
                t=templates.__class__.__name__))
        log.info('Sharing {n} templates from provider VR ID {i} to {v} VRs'.format(
            n=str(len(templates)), i=str(provider_vr_id), v=str(len(vr_ids))))

        subscriber_vrs_subscriptions = []
        for subscriber_vr_id in vr_ids:
            subscriber_vrs_subscriptions.append(
                {
                    'subscriber_vr_id': subscriber_vr_id,
                    'subscriptions': self.list_template_subscriptions_in_virtualization_realm(vr_id=subscriber_vr_id)
                }
            )

        for template in templates:
            try:
                self.share_template_to_vrs(
                    provider_vr_id=provider_vr_id,
                    template=template,
                    vr_ids=vr_ids,
                    subscribe=subscribe,
                    online=online,
                    subscriber_vrs_subscriptions=subscriber_vrs_subscriptions
                )
            except Cons3rtApiError as exc:
                msg = 'Problem sharing template to VRs\n{e}\n{t}'.format(e=str(exc), t=traceback.format_exc())
                log.warning(msg)

    def share_templates_to_vrs_by_name(self, provider_vr_id, vr_ids, template_names=None):
        """Shares template by name from the provider VR ID to the list of target VR IDs

        :param provider_vr_id: (int) ID of the template provider virtualization realm
        :param template_names: (list) name of the template names to share, None to share all templates
        :param vr_ids: (list) of IDs (int) of virtualization realms to share with
        :return: bool
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.share_templates_to_vrs_by_name')

        # Ensure the provider_vr_id is an int
        if not isinstance(provider_vr_id, int):
            try:
                provider_vr_id = int(provider_vr_id)
            except ValueError as exc:
                msg = 'provider_vr_id arg must be an Integer, found: {t}'.format(t=provider_vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        try:
            registered_templates = self.list_template_registrations_in_virtualization_realm(vr_id=provider_vr_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing registered templates in VR ID: {i}'.format(i=str(provider_vr_id))
            raise Cons3rtApiError(msg) from exc

        if len(registered_templates) < 1:
            msg = 'No registered templates found to share in VR ID: {i}'.format(i=str(provider_vr_id))
            raise Cons3rtApiError(msg)

        templates_to_share = []
        if template_names:
            for registered_template in registered_templates:
                if 'templateData' not in registered_template:
                    log.warning('templateData not found in template data: {d}'.format(d=str(registered_template)))
                    continue
                if 'virtRealmTemplateName' not in registered_template['templateData']:
                    log.warning('virtRealmTemplateName not found in templateData: {d}'.format(
                        d=str(registered_template)))
                    continue
                if registered_template['templateData']['virtRealmTemplateName'] in template_names:
                    templates_to_share.append(registered_template)
            if len(templates_to_share) < 1:
                msg = 'Registered templates not found in VR ID {i} with names: {n}'.format(
                    n=str(template_names), i=str(provider_vr_id))
                raise Cons3rtApiError(msg)
        else:
            templates_to_share = registered_templates

        # Share the template to the target VRs
        log.info('Found template [{n}] templates to share in VR ID: {i}'.format(
            n=str(len(templates_to_share)), i=str(provider_vr_id)))
        self.share_templates_to_vrs(
            provider_vr_id=provider_vr_id,
            templates=templates_to_share,
            vr_ids=vr_ids
        )

    def share_templates_to_vrs_in_cloud(self, cloud_id, provider_vr_id=None, templates_registration_data=None,
                                        template_names=None, subscribe=True, online=True):
        """Shares a list of templates from a provider VR to all VRs in the provided cloud ID

        :param cloud_id: (int) ID of the cloud to share with
        :param provider_vr_id: (int) ID of the virtualization realm where the template is registered
        :param templates_registration_data: (list) of template objects (dict)
        :param template_names: (list) of template names (str)
        :param subscribe: (bool) Set True to have the shared virtualization realm also subscribe to the template
        :param online: (bool) Set True to bring the template online in the subscriber virtualization realm
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.share_templates_to_vrs_in_cloud')

        # Ensure the cloud_id is an int
        if not isinstance(cloud_id, int):
            try:
                cloud_id = int(cloud_id)
            except ValueError as exc:
                msg = 'cloud_id arg must be an Integer, found: {t}'.format(t=cloud_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Retrieve details on the provided cloud ID
        try:
            cloud_details = self.retrieve_cloud_details(cloud_id=cloud_id)
        except Cons3rtApiError as exc:
            msg = 'Problem retrieving cloud ID {i} details'.format(i=str(cloud_id))
            raise Cons3rtApiError(msg) from exc

        # Retrieve the list of virtualization realms
        try:
            cloud_vrs = self.list_virtualization_realms_for_cloud(cloud_id=cloud_id)
        except Cons3rtApiError as exc:
            msg = 'Problem list VRs from cloud ID {i} details'.format(i=str(cloud_id))
            raise Cons3rtApiError(msg) from exc

        if not provider_vr_id:
            if 'templateVirtualizationRealm' not in cloud_details:
                msg = 'provider_vr_id not provided and templateVirtualizationRealm not found in cloud details'
                raise Cons3rtApiError(msg)
            if 'id' not in cloud_details['templateVirtualizationRealm']:
                msg = 'id not found in cloud template provided data: {d}'.format(
                    d=cloud_details['templateVirtualizationRealm'])
                raise Cons3rtApiError(msg)
            provider_vr_id = cloud_details['templateVirtualizationRealm']['id']
        log.info('Using template provider virtualization realm ID: {i}'.format(i=str(provider_vr_id)))

        # Get a list of VR IDs
        subscriber_vr_ids = []
        for vr in cloud_vrs:
            if vr['id'] != provider_vr_id:
                subscriber_vr_ids.append(vr['id'])

        # Determine the list of templates to share
        templates = []

        # If a list of templates was provided, validate
        if not templates_registration_data:
            log.info('Retrieving a list of template registrations in the provider VR...')
            try:
                all_template_registrations_data = self.list_template_registrations_in_virtualization_realm(
                    vr_id=provider_vr_id)
            except Cons3rtApiError as exc:
                msg = 'Problem listing template registrations in the provider VR ID: {i}'.format(i=str(provider_vr_id))
                raise Cons3rtApiError(msg) from exc
            if not template_names:
                log.info('Sharing all templates from provider VR ID: {i}'.format(i=str(provider_vr_id)))
                templates = all_template_registrations_data
            else:
                log.info('Searching for template data to share for template names: {n}'.format(
                    n=','.join(template_names)))
                for template_registration_data in all_template_registrations_data:
                    if 'templateData' not in template_registration_data.keys():
                        raise Cons3rtApiError('templateData not found in template data: {d}'.format(
                            d=str(template_registration_data)))
                    if 'virtRealmTemplateName' not in template_registration_data['templateData'].keys():
                        raise Cons3rtApiError('virtRealmTemplateName not found in template data: {d}'.format(
                            d=str(template_registration_data)))
                    if template_registration_data['templateData']['virtRealmTemplateName'] in template_names:
                        templates.append(template_registration_data)
        else:
            templates = templates_registration_data

        if len(templates) < 1:
            log.warning('No templates found to share from cloud ID: {i}'.format(i=str(cloud_id)))
            return

        log.info('Attempting to share {n} templates from cloud ID: {i}'.format(n=str(len(templates)), i=str(cloud_id)))
        self.share_templates_to_vrs(
            provider_vr_id=provider_vr_id,
            templates=templates,
            vr_ids=subscriber_vr_ids,
            subscribe=subscribe,
            online=online
        )
        log.info('Completed sharing templates in cloud ID: {i}'.format(i=str(cloud_id)))
