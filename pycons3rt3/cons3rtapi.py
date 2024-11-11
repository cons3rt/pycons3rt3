#!/usr/bin/env python

import datetime
import json
import logging
import os
import time
import traceback
import yaml

from .bash import validate_ip_address
from .logify import Logify

from .awsutil import aws_config_file_content_template, aws_credentials_file_content_template
from .cloud import Cloud
from .cons3rtclient import Cons3rtClient
from .cons3rtenums import (cons3rt_deployment_run_status_active, cons3rt_software_asset_types,
                           cons3rt_test_asset_types, interval_units, k8s_types, remote_access_sizes, service_types,
                           valid_search_type)
from .cons3rtwaiters import RunWaiter
from .deployment import Deployment
from .pycons3rtlibs import HostActionResult, RestUser
from .cons3rtconfig import cons3rtapi_config_file, get_pycons3rt_conf_dir, get_data_dir
from .exceptions import Cons3rtClientError, Cons3rtApiError, DeploymentError, InvalidCloudError, \
    InvalidOperatingSystemTemplate
from .ostemplates import OperatingSystemTemplate, OperatingSystemType


# Set up logger name for this module
mod_logger = Logify.get_name() + '.cons3rtapi'

# Valid states for project members
project_member_states = ['REQUESTED', 'ACTIVE', 'BLOCKED', 'DELETED']

# Project roles for an express user (excludes all others including STANDARD, which must be removed)
express_roles = ['MEMBER', 'CONSUMER']

# Project roles for a standard non-express user 
standard_roles = ['STANDARD']

# Project roles for a standard asset developer
asset_developer_roles = ['SOFTWARE_DEVELOPER', 'TEST_DEVELOPER', 'ASSET_SHARER', 'ASSET_PROMOTER', 'ASSET_UPLOADER', 
                         'POWER_SCHEDULE_UPDATER']

# Project roles for a project manager/owner (who does not develop assets)
project_manager_roles = ['PROJECT_OWNER', 'PROJECT_MANAGER', 'PROJECT_MODERATOR']

# All valid roles combined
valid_member_roles = express_roles + standard_roles + asset_developer_roles + project_manager_roles

# Collab tools project names
bitbucket_project_name = 'AtlassianBitbucket-project'
confluence_project_name = 'AtlassianConfluence-project'
jira_project_name = 'AtlassianJira-project'
gitlab_premium_project_name = 'GitlabPremium-project'
gitlab_ultimate_project_name = 'GitlabUltimate-project'
mattermost_project = 'Mattermost-project'
collab_tools_project_names = [
    bitbucket_project_name,
    confluence_project_name,
    jira_project_name,
    gitlab_premium_project_name,
    gitlab_ultimate_project_name,
    mattermost_project
]


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
        except (OSError, IOError) as exc:
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
            log.info('Set project and Rest API token to: [{p}]'.format(p=self.rest_user.project_name))
        else:
            log.warning('Matching ReST User not found for project: {p}'.format(p=project_name))

    def save_cons3rt_data(self, cons3rt_data, data_name):
        """Save cons3rt data to a file name that includes the provided data_name

        :param cons3rt_data: (list) or (dict) of cons3rt data
        :param data_name: (str) unique string to identify one kind of data
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.save_cons3rt_data')
        file_name = self.cons3rt_client.user.rest_api_url.lstrip('https://').split('/')[0] + '_' + data_name + '.yml'
        save_file_path = os.path.join(get_data_dir(), file_name)
        if os.path.isfile(save_file_path):
            os.remove(save_file_path)
        log.debug('Saving cons3rt data to: {f}'.format(f=save_file_path))
        with open(save_file_path, 'w') as f:
            yaml.dump(cons3rt_data, f, sort_keys=True)

    def load_cons3rt_data(self, data_name):
        """Loads cons3rt data from a filename derived from the site URL and the provided data name

        :param data_name: (str) unique string to identify one kind of data
        :return: (dict) or (list) containing the specified data or None
        """
        log = logging.getLogger(self.cls_logger + '.load_cons3rt_data')
        file_name = self.cons3rt_client.user.rest_api_url.lstrip('https://').split('/')[0] + '_' + data_name + '.yml'
        save_file_path = os.path.join(get_data_dir(), file_name)
        if not os.path.isfile(save_file_path):
            log.debug('Saved file does not exist for data name: {d}'.format(d=data_name))
            return
        log.info('Reading cons3rt data from file: {f}'.format(f=save_file_path))
        with open(save_file_path, 'r') as f:
            return yaml.load(f, Loader=yaml.FullLoader)

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
        """Returns a list of asset dependent on the provided asset ID

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
        :param state: (str) membership state (see project_member_states)
        :param role: (str) membership role (see valid_roles)
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
        
        # Ensure the args are valid
        if state:
            if not isinstance(state, str):
                msg = 'state arg must be a string, received: {t}'.format(t=state.__class__.__name__)
                raise Cons3rtApiError(msg)
            if state not in project_member_states:
                msg = 'state [{s}] invalid, must be one of: {v}'.format(s=state, v=','.join(project_member_states))
                raise Cons3rtApiError(msg)
        if role:
            if not isinstance(role, str):
                msg = 'role arg must be a string, received: {t}'.format(t=role.__class__.__name__)
                raise Cons3rtApiError(msg)
            if role not in valid_member_roles:
                msg = 'role [{r}] invalid, must be one of: {v}'.format(r=role, v=','.join(valid_member_roles))
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

    def get_project_resources(self, project_id):
        """Returns resources consumed by the specified project ID

        :param (int) project_id: ID of the project to query
        :return: (dict) project resources
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
            project_details = self.get_project_details(project_id=project_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for details on project: {i}'.format(i=str(project_id))
            raise Cons3rtApiError(msg) from exc

        # Get the project resources
        if 'resourceUsage' not in project_details.keys():
            msg = 'resourceUsage not found in project details: [{d}]'.format(d=str(project_details))
            raise Cons3rtApiError(msg)
        return project_details['resourceUsage']

    def get_project_host_metrics(self, project_id, start=None, end=None, interval=1, interval_unit='HOURS'):
        """Queries CONS3RT for metrics by project ID

        :param project_id: (int) ID of the project
        :param start: (int) start time for metrics in unix epoch time
        :param end: (int) end time for metrics in unix epoch time
        :param interval: (int) number of intervals
        :param interval_unit: (str) Enum: "Nanos" "Micros" "Millis" "Seconds" "Minutes" "Hours" "HalfDays" "Days"
            "Weeks" "Months" "Years" "Decades" "Centuries" "Millennia" "Eras" "Forever"
        :return: (dict) containing project metrics
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.get_project_host_metrics')

        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the start/end time
        if not start:
            start = int(time.time())
        else:
            if not isinstance(start, int):
                msg = 'start arg must be an Integer, found: {t}'.format(t=type(start).__name__)
                raise Cons3rtApiError(msg)
        if not end:
            end = int(time.time())
        else:
            if not isinstance(end, int):
                msg = 'end arg must be an Integer, found: {t}'.format(t=type(end).__name__)
                raise Cons3rtApiError(msg)

        # Ensure the interval is an int
        if not isinstance(interval, int):
            msg = 'interval arg must be an Integer, found: {t}'.format(t=type(interval).__name__)
            raise Cons3rtApiError(msg)

        # Ensure the interval_unit is a string, and is valid
        if not isinstance(interval_unit, str):
            msg = 'interval_unit arg must be a str, found: {t}'.format(t=type(interval_unit).__name__)
            raise Cons3rtApiError(msg)

        interval_unit = interval_unit.upper()
        if interval_unit not in interval_units:
            msg = 'Invalid interval_unit provided [{i}], must be one of: [{u}]'.format(
                i=interval_unit, u=','.join(interval_units))
            raise Cons3rtApiError(msg)

        log.debug('Attempting query host metrics from project ID {i}'.format(i=str(project_id)))
        try:
            project_metrics = self.cons3rt_client.get_project_host_metrics(
                project_id=project_id,
                start=start,
                end=end,
                interval=interval,
                interval_unit=interval_unit
            )
        except Cons3rtClientError as exc:
            msg = 'Unable to query CONS3RT for host metrics on project: {i}'.format(i=str(project_id))
            raise Cons3rtApiError(msg) from exc
        return project_metrics

    def get_team_host_metrics(self, team_id):
        """Compile team host metrics from the project host metrics

        :param team_id: (int) team ID
        :return: (tuple)
           (dict) compiling host metrics from each of the team projects
           (dict) team host maximums
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.get_team_host_metrics')

        # Tally up metrics for each project
        team_host_metrics = {
            'numCpus': 0,
            'ramInMegabytes': 0,
            'storageInMegabytes': 0,
            'virtualMachines': 0
        }

        # Get the list of owned projects
        team_details, owned_projects = self.list_projects_in_team(team_id=team_id)
        team_host_maximums = {
            'numCpus': team_details['maxNumCpus'],
            'ramInMegabytes': team_details['maxRamInMegabytes'],
            'storageInMegabytes': team_details['maxStorageInMegabytes'],
            'virtualMachines': team_details['maxVirtualMachines']
        }

        log.info('Collecting host metrics from [{n}] projects in team: {i}'.format(
            n=str(len(owned_projects)), i=str(team_id)))

        # Loops through team project and collect host metrics
        for owned_project in owned_projects:
            log.info('Adding host metrics for project [{n}]'.format(n=owned_project['name']))
            project_host_metrics = self.get_project_host_metrics(project_id=owned_project['id'])

            # Expecting 1 entry per project host metrics call
            if len(project_host_metrics.keys()) != 1:
                msg = 'Expected 1 entry for host metrics for project [{p}], found: {n}'.format(
                    p=str(owned_project['id']), n=str(len(project_host_metrics.keys())))
                raise Cons3rtApiError(msg)

            # Add each entry for host metrics
            for entry in project_host_metrics.keys():
                team_host_metrics['numCpus'] += project_host_metrics[entry]['numCpus']
                team_host_metrics['ramInMegabytes'] += project_host_metrics[entry]['ramInMegabytes']
                team_host_metrics['storageInMegabytes'] += project_host_metrics[entry]['storageInMegabytes']
                team_host_metrics['virtualMachines'] += project_host_metrics[entry]['virtualMachines']

        return team_host_metrics, team_host_maximums

    def get_team_resources(self, team_id):
        """Compile team resources from the project resources

        :param team_id: (int) team ID
        :return: (tuple)
           (dict) compiling resources from each of the team projects
           (dict) team host maximums
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.get_team_resources')

        # Tally up resources for each project
        team_resources = {
            'numCpus': 0,
            'ramInMegabytes': 0,
            'storageInMegabytes': 0,
            'virtualMachines': 0
        }

        # Get the list of owned projects
        team_details, owned_projects = self.list_projects_in_team(team_id=team_id)
        team_resource_maximums = {
            'numCpus': team_details['maxNumCpus'],
            'ramInMegabytes': team_details['maxRamInMegabytes'],
            'storageInMegabytes': team_details['maxStorageInMegabytes'],
            'virtualMachines': team_details['maxVirtualMachines']
        }

        log.info('Collecting resources from [{n}] projects in team: {i}'.format(
            n=str(len(owned_projects)), i=str(team_id)))

        # Loops through team project and collect host metrics
        for owned_project in owned_projects:
            log.info('Adding resources for project [{n}]'.format(n=owned_project['name']))
            project_resources = self.get_project_resources(project_id=owned_project['id'])

            # Add project resources to the team resources
            team_resources['numCpus'] += project_resources['numCpus']
            team_resources['ramInMegabytes'] += project_resources['ramInMegabytes']
            team_resources['storageInMegabytes'] += project_resources['storageInMegabytes']
            team_resources['virtualMachines'] += project_resources['virtualMachines']
        return team_resources, team_resource_maximums

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

    def list_teams(self, active_only=False, not_expired=False):
        """Query CONS3RT to return a list of Teams

        :param active_only (bool) Set true to return only teams that are active
        :param not_expired (bool) Set true to return only teams that are not expired
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
        log.info('Found {n} teams in all'.format(n=str(len(teams))))

        # Filter out the system team
        excluding_system_team = []
        for team in teams:
            if team['name'] == 'SystemTeam':
                continue
            else:
                excluding_system_team.append(team)
        teams = list(excluding_system_team)
        if active_only:
            log.info('Trimming teams by active teams only as requested...')
            active_teams = []
            for team in teams:
                if 'state' not in team.keys():
                    log.warning('state data not found in team: {d}'.format(d=str(team)))
                    continue
                if 'validUtil' not in team.keys():
                    log.warning('validUtil data not found in team: {d}'.format(d=str(team)))
                    continue
                team_expiration_date = team['validUtil'] / 1000
                team_expiration_date_unix = datetime.datetime.fromtimestamp(team_expiration_date)
                team_expiration_date_formatted = team_expiration_date_unix.strftime("%d %B %Y")
                team['expirationDate'] = team_expiration_date_formatted
                if team['state'] == 'ACTIVE':
                    log.info('Found active team: {n}'.format(n=team['name']))
                    active_teams.append(team)
            log.info('Found {n} active teams'.format(n=str(len(active_teams))))
            teams = list(active_teams)
        if not_expired:
            log.info('Trimming teams by unexpired teams only as requested...')
            unexpired_teams = []
            for team in teams:
                if 'validUtil' not in team.keys():
                    log.warning('validUtil data not found in team: {d}'.format(d=str(team)))
                    continue
                team_expiration_date = team['validUtil'] / 1000
                team_expiration_date_unix = datetime.datetime.fromtimestamp(team_expiration_date)
                team_expiration_date_formatted = team_expiration_date_unix.strftime("%d %B %Y")
                team['expirationDate'] = team_expiration_date_formatted
                now = datetime.datetime.now()
                if team_expiration_date_unix >= now:
                    log.info('Found unexpired team: {n}'.format(n=team['name']))
                    unexpired_teams.append(team)
                else:
                    log.info('Found team [{n}] expired on: {t}'.format(
                        n=team['name'], t=str(team_expiration_date_unix)))
            teams = list(unexpired_teams)
            log.info('Found {n} unexpired teams'.format(n=str(len(unexpired_teams))))
        return teams

    def list_active_teams(self):
        """Query CONS3RT to retrieve active site teams

        :return: (list) Containing all site teams
        :raises: Cons3rtClientError
        """
        return self.list_teams(active_only=True)

    def list_unexpired_teams(self):
        """Query CONS3RT to retrieve active site teams

        :return: (list) Containing all site teams
        :raises: Cons3rtClientError
        """
        return self.list_teams(not_expired=True)

    def list_active_unexpired_teams(self):
        """Query CONS3RT to retrieve active site teams

        :return: (list) Containing all site teams
        :raises: Cons3rtClientError
        """
        return self.list_teams(active_only=True, not_expired=True)

    def list_all_teams(self):
        """Query CONS3RT to retrieve all site teams (deprecated)

        :return: (list) Containing all site teams
        :raises: Cons3rtClientError
        """
        return self.list_teams()

    def list_expired_teams(self):
        """Query CONS3RT to return a list of expired teams

        :return: (list) of Team Info for expired teams
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_expired_teams')
        teams = self.list_teams()
        expired_teams = []
        for team in teams:
            if 'validUtil' not in team.keys():
                log.warning('validUtil data not found in team: {d}'.format(d=str(team)))
                continue
            team_expiration_date = team['validUtil'] / 1000
            team_expiration_date_unix = datetime.datetime.fromtimestamp(team_expiration_date)
            team_expiration_date_formatted = team_expiration_date_unix.strftime("%d %B %Y")
            team['expirationDate'] = team_expiration_date_formatted
            now = datetime.datetime.now()
            if team_expiration_date_unix < now:
                log.info('Team [{n}] expired on: {t}'.format(n=team['name'], t=str(team_expiration_date_unix)))
                expired_teams.append(team)
            else:
                log.info('Team [{n}] will expire on: {t}'.format(n=team['name'], t=str(team_expiration_date_unix)))
        log.info('Found {n} expired teams'.format(n=str(len(expired_teams))))
        return expired_teams

    def list_inactive_teams(self):
        """Query CONS3RT to return a list of teams with a state other than ACTIVE

        :return: (list) of Team Info for expired teams
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_inactive_teams')
        teams = self.list_teams()
        inactive_teams = []
        for team in teams:
            if 'state' not in team.keys():
                log.warning('state data not found in team: {d}'.format(d=str(team)))
                continue
            if 'validUtil' not in team.keys():
                log.warning('validUtil data not found in team: {d}'.format(d=str(team)))
                continue
            team_expiration_date = team['validUtil'] / 1000
            team_expiration_date_unix = datetime.datetime.fromtimestamp(team_expiration_date)
            team_expiration_date_formatted = team_expiration_date_unix.strftime("%d %B %Y")
            team['expirationDate'] = team_expiration_date_formatted
            if team['state'] != 'ACTIVE':
                log.info('Team [{n}] has inactive state: {s}'.format(n=team['name'], s=team['state']))
                inactive_teams.append(team)
            else:
                log.info('Team [{n}] is ACTIVE'.format(n=team['name']))
        log.info('Found {n} inactive teams'.format(n=str(len(inactive_teams))))
        return inactive_teams

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
        :return: (tuple) team details and list of owned projects
        :raises: Cons3rtApiError
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
        return team_details, owned_projects

    def list_collab_tools_projects_in_team(self, team_id):
        """Returns a list of collab tools projects in a team

        :param team_id: (int) team ID
        :return: (tuple) (dict) team details, (list) of (dict) collab tools projects
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_collab_tools_projects_in_team')
        log.info('Getting a list of collab tools projects in team: {i}'.format(i=str(team_id)))
        collab_tools_projects = []
        team_details, team_projects = self.list_projects_in_team(team_id=team_id)
        for project in team_projects:
            for collab_tools_project_name in collab_tools_project_names:
                if project['name'].endswith(collab_tools_project_name):
                    collab_tools_projects.append(project)
                    log.info('Found collab tools project: {n}'.format(n=project['name']))
        log.info('Found {n} collab tools projects in team ID: {i}'.format(
            n=str(len(collab_tools_projects)), i=str(team_id)))
        return team_details, collab_tools_projects

    @staticmethod
    def get_collab_tool_for_project_name(project_name):
        """Given a project name, return the name of the collab tool or "None"

        :param project_name: (str) name of the project
        :return: (str) name of the collab tool or None
        """
        if project_name.endswith(bitbucket_project_name):
            return 'ATLASSIAN_BITBUCKET'
        elif project_name.endswith(confluence_project_name):
            return 'ATLASSIAN_CONFLUENCE'
        elif project_name.endswith(jira_project_name):
            return 'ATLASSIAN_JIRA'
        elif project_name.endswith(gitlab_premium_project_name):
            return 'GITLAB_PREMIUM'
        elif project_name.endswith(gitlab_ultimate_project_name):
            return 'GITLAB_ULTIMATE'
        elif project_name.endswith(mattermost_project):
            return 'MATTERMOST'

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

    def list_deployment_runs(self, search_type='SEARCH_ACTIVE', in_project=False):
        """Returns a collection of the user's relevant Deployment Runs matching a specified query.

        :param search_type: (str) search type
        :param in_project: (bool) Include project runs
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_deployment_runs')

        # Ensure search_type and in_project is valid
        if not isinstance(search_type, str):
            raise Cons3rtApiError('Arg search_type must be a string, found type: {t}'.format(
                t=type(search_type)))
        if not isinstance(in_project, bool):
            raise Cons3rtApiError('Arg in_project must be a bool, found type: {t}'.format(
                t=type(in_project)))

        search_type = search_type.upper()
        if search_type not in valid_search_type:
            raise Cons3rtApiError('Arg status provided is not valid, must be one of: {s}'.format(
                s=', '.join(search_type)))

        # Attempt to get a list of deployment runs
        log.info('Attempting to get a list of deployment runs with search_type [{s}] and in_project [{i}]'.format(
            s=search_type, i=str(in_project)))
        try:
            drs = self.cons3rt_client.list_all_deployment_runs(
                search_type=search_type,
                in_project=in_project
            )
        except Cons3rtClientError as exc:
            msg = 'Problem listing runs with search type [{s}] and in_project [{i}]'.format(
                s=search_type, i=str(in_project))
            raise Cons3rtClientError(msg) from exc
        log.info('Found [{n}] runs with search type [{s}] and in_project [{i}]'.format(
            n=str(len(drs)), s=search_type, i=str(in_project)))
        return drs

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

        for dr in drs:
            if 'deploymentRunStatus' in dr:
                if dr['deploymentRunStatus'] in cons3rt_deployment_run_status_active:
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

        inactive_drs = []
        for dr in drs:
            if 'deploymentRunStatus' in dr:
                if dr['deploymentRunStatus'] not in cons3rt_deployment_run_status_active:
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

    def list_deployment_runs_in_cloud(self, cloud_id, search_type='SEARCH_ALL'):
        """Query each VR in the cloud to get a list of DR

        :param cloud_id: (int) cloud ID to query
        :param search_type: (str) Search type (see cons3rtenums:valid_search_type)
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_deployment_runs_in_cloud')

        log.info('Getting a list of deployment runs in cloud [{i}] with search type: {s}'.format(
            i=str(cloud_id), s=search_type))
        try:
            vrs = self.list_virtualization_realms_for_cloud(cloud_id=cloud_id)
        except Cons3rtApiError as exc:
            msg = 'Problem retrieving the list of virtualization realms for cloud ID: {i}'.format(i=str(cloud_id))
            raise Cons3rtApiError(msg) from exc

        # Store the list of DRs in the cloud
        cloud_drs = []

        log.info('Listing deployment runs in each virtualization realm...')
        for vr in vrs:
            log.info('Listing deployment runs in virtualization realm ID {i}'.format(i=str(vr['id'])))
            try:
                cloud_drs += self.list_deployment_runs_in_virtualization_realm(vr_id=vr['id'], search_type=search_type)
            except Cons3rtApiError as exc:
                msg = 'Problem retrieving the list of deployment runs in virtualization realm ID: {i}'.format(
                    i=str(vr['id']))
                raise Cons3rtApiError(msg) from exc
        log.info('Found {n} deployment runs in cloud: {i}'.format(n=str(len(cloud_drs)), i=str(cloud_id)))
        return cloud_drs

    def list_active_deployment_runs_in_cloud(self, cloud_id):
        """Query each VR in the cloud to get a list of active DRs

        :param cloud_id: (int) cloud ID to query
        :return: (list) of deployment runs
        :raises: Cons3rtApiError
        """
        return self.list_deployment_runs_in_cloud(cloud_id=cloud_id, search_type='SEARCH_ACTIVE')

    def list_deployment_run_hosts_in_cloud(self, cloud_id, search_type='SEARCH_ALL', load=False):
        """Query each VR in the cloud to get a list of DR hosts

        :param cloud_id: (int) cloud ID to query
        :param search_type: (str) Search type (see cons3rtenums:valid_search_type)
        :param load (bool) Set True to load local data if found
        :return: (tuple) of the following:
            1. (list) of deployment run details, and a list of host details
            [
                "run": {run details}
                "hosts": [{host details}]
            ]
            2. (int) count of the deployment run hosts
            3. (list) of failed DRs not found to get details
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_deployment_run_hosts_in_cloud')
        log.info('Getting a list of deployment run hosts in cloud [{i}] with search type: {s}'.format(
            i=str(cloud_id), s=search_type))

        cloud_drs = self.list_deployment_runs_in_cloud(cloud_id=cloud_id, search_type=search_type)

        # Get the list of cloud deployment run host details
        cloud_drh_list, cloud_drh_count, failed_drs = self.list_host_details_in_dr_list(dr_list=cloud_drs, load=load)

        log.info('Found {n} deployment run hosts in cloud ID: {i}'.format(n=str(len(cloud_drh_list)), i=str(cloud_id)))
        return cloud_drh_list, cloud_drh_count, failed_drs

    def list_active_deployment_run_hosts_in_cloud(self, cloud_id, load=False):
        """Query each VR in the cloud to get a list of active DR hosts

        :param cloud_id: (int) cloud ID to query
        :param load (bool) Set True to load local data if found
        :return: (tuple) of the following:
            1. (list) of deployment run details, and a list of host details
            [
                "run": {run details}
                "hosts": [{host details}]
            ]
            2. (int) count of the deployment run hosts
            3. (list) failed drs
        :raises: Cons3rtApiError
        """
        return self.list_deployment_run_hosts_in_cloud(cloud_id=cloud_id, search_type='SEARCH_ACTIVE', load=load)

    def list_cloud_gpu_hosts(self, cloud_id, load=False):
        """Query each cloud to get a list of deployment run hosts that are using GPU

        :param cloud_id: (int) cloud ID
        :param load (bool) Set True to load local data if found
        :return: (list) of dict deployment run and host data:
            {
                'run_id': run['run']['id'],
                'run_owner': run['run']['creator']['username'],
                'email': run['run']['creator']['email'],
                'host_id': host['id'],
                'host_name': host['hostname'],
                'gpu_type': host['gpuType'],
                'gpu_profile': host['gpuProfile']
            }
        """
        log = logging.getLogger(self.cls_logger + '.list_cloud_gpu_hosts')
        log.info('Attempting to get a list of deployment run hosts using GPUs in cloud ID: {i}'.format(i=str(cloud_id)))

        # Get a list of deployment run hosts in the cloud
        cloud_drhs, cloud_drh_count, _ = self.list_active_deployment_run_hosts_in_cloud(cloud_id=cloud_id, load=load)
        log.info('Found {n} active deployment run hosts in cloud ID: {i}'.format(
            n=str(cloud_drh_count), i=str(cloud_id)))

        # Store a list of GPU deployment run hosts
        gpu_hosts = []

        # Loop through the run hosts, find ones using GPU, and filter collect GPU info
        for run in cloud_drhs:
            if 'run' not in run.keys():
                log.warning('run data not found in entry: {d}'.format(d=str(run)))
                continue
            if 'id' not in run['run'].keys():
                log.warning('id data not found in run data: {d}'.format(d=str(run['run'])))
                continue
            if 'creator' not in run['run'].keys():
                log.warning('creator data not found in run data: {d}'.format(d=str(run['run'])))
                continue
            if 'username' not in run['run']['creator'].keys():
                log.warning('username data not found in creator data: {d}'.format(d=str(run['run']['creator'])))
                continue
            if 'hosts' not in run.keys():
                log.warning('hosts data not found in entry: {d}'.format(d=str(run)))
                continue

            # Loop through each host in the run
            for host in run['hosts']:
                if 'id' not in host.keys():
                    log.warning('id data not found in host: {d}'.format(d=str(host)))
                    continue
                if 'hostname' not in host.keys():
                    log.warning('hostname data not found in host: {d}'.format(d=str(host)))
                    continue

                # Check if the host has a GPU
                # TODO uncomment this when it is fixed -- currently hasGpu returns only false
                # if not host['hasGpu']:
                #     log.debug('Host [{i}/{n}] does not use GPU'.format(i=str(host['id']), n=host['hostname']))
                #     continue

                # Set default values foe GPU type and profile
                gpu_type = 'None'
                gpu_profile = 'None'

                # Track if GPU info was included in the DR host data
                gpu_info_found = False

                # Check for gpuType and gpuProfile
                if 'gpuType' in host.keys():
                    gpu_type = host['gpuType']
                    gpu_info_found = True
                if 'gpuProfile' in host.keys():
                    gpu_profile = host['gpuProfile']
                    gpu_info_found = True

                # Add the host to the list if GPU info was found
                if gpu_info_found:
                    log.info('Host [{i}/{n}] does uses GPU'.format(i=str(host['id']), n=host['hostname']))
                    gpu_hosts.append({
                        'run_id': run['run']['id'],
                        'run_owner': run['run']['creator']['username'],
                        'host_id': host['id'],
                        'host_name': host['hostname'],
                        'gpu_type': gpu_type,
                        'gpu_profile': gpu_profile
                    })
                else:
                    log.debug('Host [{i}/{n}] does not use GPU'.format(i=str(host['id']), n=host['hostname']))

        log.info('Found {n} deployment run hosts using GPU'.format(n=str(len(gpu_hosts))))
        return gpu_hosts

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
        if 'legacyProperties' not in dr_details['properties']:
            log.warning('No legacyProperties found for deployment run ID: {i}'.format(i=str(dr_details['id'])))
            return
        custom_props = []
        for dep_prop in dr_details['properties']['legacyProperties']:
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
        log.info('Found {n} virtualization realms in cloud ID: {i}'.format(n=str(len(vrs)), i=str(cloud_id)))
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

    def update_asset_state(self, asset_id, state):
        """Updates the asset state

        :param asset_id: (int) asset ID to update
        :param state: (str) desired state: IN_DEVELOPMENT, CERTIFIED, DEPRECATED
        :return: None
        """
        log = logging.getLogger(self.cls_logger + '.update_asset_state')

        valid_states = ['IN_DEVELOPMENT', 'CERTIFIED', 'DEPRECATED']

        # Ensure the asset_id is an int
        if not isinstance(asset_id, int):
            try:
                asset_id = int(asset_id)
            except ValueError as exc:
                msg = 'asset_id arg must be an Integer'
                raise Cons3rtApiError(msg) from exc

        #  Ensure the asset_zip_file arg is a string
        if not isinstance(state, str):
            msg = 'The state arg must be a string, found {t}'.format(t=state.__class__.__name__)
            raise Cons3rtApiError(msg)

        # Ensure state is valid
        state = state.upper().strip()
        if state not in valid_states:
            raise Cons3rtApiError('Provided state is not valid: {s}, must be one of: {v}'.format(
                s=state, v=valid_states))

        # Attempt to update the asset ID
        try:
            self.cons3rt_client.update_asset_state(asset_id=asset_id, state=state)
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

    def update_k8s_virtualization_realm_service(self, vr_id, display_name='kubernetes', k8s_type='RKE2',
                                                    retain_on_error=True, num_worker_nodes=3, service_id=None):
        """Adds or updates a virtualization realm service

        Provide the service_id param to update an existing service, leave it blank to add a new service

        {
         "k8sFlavorType": "RKE2",
         "retainOnError": true,
         "workerNodes": 3,
         "displayName": "kubernetes",
         "type": "Kubernetes"
        }

        :param vr_id: (int) Virtualization Realm ID
        :param display_name: (str) Display name for the service
        :param k8s_type: (str) Type of kubernetes service
        :param retain_on_error: (bool) Set True to retain if deployed services fail
        :param num_worker_nodes: (int) Number of worker nodes
        :param service_id: (int) Provide the service ID to update an existing service
        :return: (dict) Containing the service info
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.update_k8s_virtualization_realm_service')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise Cons3rtApiError('vr_id arg must be an Integer') from exc

        # Validate the kubernetes type
        if k8s_type not in k8s_types:
            msg = 'Invalid kubernetes type provided [{t}], must be one of: [{a}]'.format(
                t=k8s_type, a=','.join(k8s_types))
            raise Cons3rtApiError(msg)

        # Set the service type
        service_type = 'Kubernetes'

        # Build the content
        service_content = {
            'displayName': display_name,
            'k8sFlavorType': k8s_type,
            'retainOnError': retain_on_error,
            'type': service_type,
            'workerNodes': num_worker_nodes
        }

        # Attempt to enable remote access
        msg_body = ('virtualization realm ID [{i}] service type [{t}] with kubernetes type [{k}], display name '
                    '[{n}], retain set to [{r}], and [{w}] nodes').format(
            i=vr_id, t=service_type, k=k8s_type, n=display_name, r=str(retain_on_error), w=str(num_worker_nodes))

        if service_id:
            log.info('Attempting to update service ID [{s}] '.format(s=str(service_id)) + msg_body)
            try:
                vr_service = self.cons3rt_client.update_virtualization_realm_service(
                    vr_id=vr_id, service_id=service_id, service_content=service_content)
            except Cons3rtClientError as exc:
                raise Cons3rtApiError('Problem updating service ID [{s}] '.format(
                    s=str(service_id)) + msg_body) from exc
            log.info('Successfully updated service ID [{s}] '.format(s=str(service_id)) + msg_body)
        else:
            log.info('Attempting to add ' + msg_body)
            try:
                vr_service = self.cons3rt_client.add_virtualization_realm_service(
                    vr_id=vr_id, service_content=service_content)
            except Cons3rtClientError as exc:
                raise Cons3rtApiError('Problem adding ' + msg_body) from exc
            log.info('Successfully added ' + msg_body)
        return vr_service

    def update_remote_access_virtualization_realm_service(self, vr_id, display_name='remote-access',
                                                          guac_ip_address='172.16.10.253', instance_type='MEDIUM',
                                                          remote_access_port=9443, rdp_proxy_enabled=True,
                                                          retain_on_error=True, service_id=None):
        """Adds or updates a remote access service

        Provide the service_id param to update an existing service, leave it blank to add a new service

        {
         "guacIpAddress": "172.16.10.253",
         "instanceType": "SMALL",
         "rdpProxyingEnabled": true,
         "remoteAccessPort": 9443,
         "retainOnError": true,
         "displayName": "remote-access",
         "type": "RemoteAccess"
        }

        :param vr_id: (int) Virtualization Realm ID
        :param display_name: (str) Display name for the service
        :param guac_ip_address: (str) IP address of the guacd server
        :param instance_type: (str) SMALL/MEDIUM/LARGE
        :param remote_access_port: (int) TCP port for the guacd server
        :param rdp_proxy_enabled: (bool) Set True to enable RDP proxy
        :param retain_on_error: (bool) Set True to retain if deployed services fail
        :param service_id: (int) Provide the service ID to update an existing service
        :return: (dict) Containing the service info
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.update_remote_access_virtualization_realm_service')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise Cons3rtApiError('vr_id arg must be an Integer') from exc

        # Validate the kubernetes type
        if instance_type not in remote_access_sizes:
            msg = 'Invalid instance type provided [{t}], must be one of: [{a}]'.format(
                t=instance_type, a=','.join(remote_access_sizes))
            raise Cons3rtApiError(msg)

        # Set the service type
        service_type = 'RemoteAccess'

        # Build the content
        service_content = {
            'displayName': display_name,
            'guacIpAddress': guac_ip_address,
            'instanceType': instance_type,
            'rdpProxyingEnabled': rdp_proxy_enabled,
            'remoteAccessPort': remote_access_port,
            'retainOnError': retain_on_error,
            'type': service_type
        }

        # Attempt to enable remote access
        msg_body = ('virtualization realm ID [{i}] service type [{t}] with instance type [{k}], display name '
                    '[{n}], guac IP address:port [{a}:{p}], RDP proxy [x], and retain set to [{r}]').format(
            i=vr_id, t=service_type, k=instance_type, n=display_name, r=str(retain_on_error),
            a=guac_ip_address, p=str(remote_access_port), x=str(rdp_proxy_enabled))

        if service_id:
            log.info('Attempting to update service ID [{s}] '.format(s=str(service_id)) + msg_body)
            try:
                vr_service = self.cons3rt_client.update_virtualization_realm_service(
                    vr_id=vr_id, service_id=service_id, service_content=service_content)
            except Cons3rtClientError as exc:
                raise Cons3rtApiError('Problem updating service ID [{s}] '.format(
                    s=str(service_id)) + msg_body) from exc
            log.info('Successfully updated service ID [{s}] '.format(s=str(service_id)) + msg_body)
        else:
            log.info('Attempting to add ' + msg_body)
            try:
                vr_service = self.cons3rt_client.add_virtualization_realm_service(
                    vr_id=vr_id, service_content=service_content)
            except Cons3rtClientError as exc:
                raise Cons3rtApiError('Problem adding ' + msg_body) from exc
            log.info('Successfully added ' + msg_body)
        return vr_service

    def retrieve_virtualization_realm_service(self, vr_id, service_id):
        """Retrieves the virtualization realm service

        :param vr_id: (int) Virtualization Realm ID
        :param service_id: (int) Service ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_virtualization_realm_service')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise Cons3rtApiError('vr_id arg must be an Integer') from exc

        # Ensure the service_id is an int
        if not isinstance(service_id, int):
            try:
                service_id = int(service_id)
            except ValueError as exc:
                raise Cons3rtApiError('service_id arg must be an Integer') from exc

        # Get the VR service
        log.info('Retrieving VR [{v}] service ID [{s}]...'.format(v=str(vr_id), s=str(service_id)))
        try:
            vr_service = self.cons3rt_client.retrieve_virtualization_realm_service(
                vr_id=vr_id, service_id=service_id)
        except Cons3rtClientError as exc:
            msg = 'Retrieving service ID [{s}] from VR ID [{v}]'.format(
                s=str(service_id), v=str(vr_id))
            raise Cons3rtApiError(msg) from exc
        return vr_service

    def update_virtualization_realm_service_state(self, vr_id, service_id, state):
        """Updates the state of the virtualization realm service

        :param vr_id: (int) Virtualization Realm ID
        :param service_id: (int) Service ID
        :param state: (str) enable/disable
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.update_virtualization_realm_service_state')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise Cons3rtApiError('vr_id arg must be an Integer') from exc

        # Ensure the service_id is an int
        if not isinstance(service_id, int):
            try:
                service_id = int(service_id)
            except ValueError as exc:
                raise Cons3rtApiError('service_id arg must be an Integer') from exc

        # Ensure state is enable/disable
        valid_states = ['enable', 'disable']
        state = state.lower()
        if state not in valid_states:
            msg = 'Invalid state requested [{s}], must be one of: [{v}]'.format(s=state, v=','.join(valid_states))
            raise Cons3rtApiError(msg)

        # Set the end state and processing state
        if state == 'enable':
            end_state = 'ENABLED'
            processing_state = 'ENABLING'
        else:
            end_state = 'DISABLED'
            processing_state = 'DISABLING'

        # Check the current status
        vr_service = self.retrieve_virtualization_realm_service(vr_id=vr_id, service_id=service_id)
        if 'serviceStatus' not in vr_service.keys():
            msg = 'Problem determining current status for VR [{v}] service [{s}]'.format(
                v=str(vr_id), s=str(service_id))
            raise Cons3rtApiError(msg)
        current_state = vr_service['serviceStatus']

        # Return if requesting enable and already enabled/enabling
        if end_state == current_state:
            log.info('VR [{v}] service [{s}] is already [{x}]'.format(v=str(vr_id), s=str(service_id), x=end_state))
            return
        elif processing_state == current_state:
            log.info('VR [{v}] service [{s}] is already [{x}]...'.format(v=str(vr_id), s=str(service_id), x=end_state))
        else:
        # Update the VR service ID to the requested state
            log.info('Updating state for VR [{v}] service ID [{i}] to state [{s}]...'.format(
                v=str(vr_id), i=str(service_id), s=state))
            try:
                self.cons3rt_client.update_virtualization_realm_service_state(
                    vr_id=vr_id, service_id=service_id, state=state)
            except Cons3rtClientError as exc:
                msg = 'Updating state for VR [{v}] service ID [{i}] to state [{s}]\n{e}'.format(
                    v=str(vr_id), i=str(service_id), s=state, e=str(exc))
                raise Cons3rtApiError(msg) from exc

        # Wait for the service to reach the end state
        self.wait_virtualization_realm_service_state(vr_id=vr_id, service_id=service_id, end_state=end_state)

    def wait_virtualization_realm_service_state(self, vr_id, service_id, end_state, status_type='serviceStatus'):
        """Updates the state of the virtualization realm service

        :param vr_id: (int) Virtualization Realm ID
        :param service_id: (int) Service ID
        :param end_state: (str) ENABLED/DISABLED
        :param status_type: (str) Which type of status to monitor:
            serviceStatus - top level service
            raStatus      - remote access service while the DR releases
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.wait_virtualization_realm_service_state')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise Cons3rtApiError('vr_id arg must be an Integer') from exc

        # Validate the end state
        valid_end_states = ['DISABLED', 'ENABLED']
        end_state = end_state.upper()
        if end_state not in valid_end_states:
            msg = 'Invalid end_state found [{x}], must be one of [{v}]'.format(
                x=end_state, v=','.join(valid_end_states))
            raise Cons3rtApiError(msg)

        # Attempt to disable remote access
        log.info('Waiting for VR ID [{i}] service [{s}] to reach state: [x]'.format(
            i=str(vr_id), s=str(service_id), x=end_state))
        max_checks = 3600
        try_num = 1
        retry_time_sec = 30
        while True:
            # Fail when the maximum time exceeded
            if try_num > max_checks:
                msg = 'Max checks [{m}] exceeded waiting for VR ID [{i}] service [{s}] to reach state [{x}]'.format(
                    i=str(vr_id), m=str(max_checks), s=str(service_id), x=end_state)
                raise Cons3rtApiError(msg)

            # Check the status
            try:
                vr_service = self.retrieve_virtualization_realm_service(vr_id=vr_id, service_id=service_id)
            except Cons3rtApiError as exc:
                log.warning('Problem retrieving the VR ID [{i}] service [{s}]\n{e}'.format(
                    i=str(vr_id), s=str(service_id), e=str(exc)))
            else:
                # Fail if ERROR state reached
                if vr_service[status_type] == 'ERROR':
                    msg = 'VR ID [{i}] service [{s}] completed with [ERROR]'.format(i=str(vr_id), s=str(service_id))
                    raise Cons3rtApiError(msg)
                # Return when desired state reached
                elif vr_service[status_type] == end_state:
                    log.info('VR ID [{i}] service [{s}] reached desired state: [{x}]'.format(
                        i=str(vr_id), s=str(service_id), x=end_state))
                    return
                elif vr_service[status_type] in valid_end_states:
                    msg = 'VR ID [{i}] service [{s}] completed unexpected end state [{x}]'.format(
                        i=str(vr_id), s=str(service_id), x=vr_service[status_type])
                    raise Cons3rtApiError(msg)
                else:
                    log.info('VR ID [{i}] service [{s}] currently has state: [{x}]'.format(
                        i=str(vr_id), s=str(service_id), x=vr_service[status_type]))

            # Re-try after a waiting period
            log.info('Retrying in {t} sec...'.format(t=str(retry_time_sec)))
            try_num += 1
            time.sleep(retry_time_sec)

    def remove_virtualization_realm_service(self, vr_id, service_id):
        """Removes the service from the virtualization realm

        :param vr_id: (int) Virtualization Realm ID
        :param service_id: (int) Service ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.remove_virtualization_realm_service')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise Cons3rtApiError('vr_id arg must be an Integer') from exc

        # Ensure the service_id is an int
        if not isinstance(service_id, int):
            try:
                service_id = int(service_id)
            except ValueError as exc:
                raise Cons3rtApiError('service_id arg must be an Integer') from exc

        # Remove the VR service
        log.info('Removing VR [{v}] service [{s}]...'.format(v=str(vr_id), s=str(service_id)))
        try:
            self.cons3rt_client.remove_virtualization_realm_service(vr_id=vr_id, service_id=service_id)
        except Cons3rtClientError as exc:
            msg = 'Removing VR [{v}] service [{s}]'.format(v=str(vr_id), s=str(service_id))
            raise Cons3rtApiError(msg) from exc

    def get_remote_access_service(self, vr_id):
        """Query the VR to get the service ID for remote access

        :param vr_id: (int) Virtualization Realm ID
        :return: (dict) the Remote Access VR service info or None:
        {
            "id"
            "type"
            "displayName"
            "status"
        }
        """
        log = logging.getLogger(self.cls_logger + '.get_remote_access_service')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise Cons3rtApiError('vr_id arg must be an Integer') from exc

        # Get the VR details
        vr_details = self.get_virtualization_realm_details(vr_id=vr_id)

        # Check for services
        if 'services' not in vr_details.keys():
            log.info('VR ID [{{i}] has no services'.format(i=str(vr_id)))
            return

        # Loop through service to find the remote access service
        for service in vr_details['services']:
            if 'type' not in service.keys():
                continue
            if 'id' not in service.keys():
                continue
            if service['type'] != 'RemoteAccess':
                continue
            log.info('Found VR [{v}] remote access service ID: [{s}]'.format(v=str(vr_id), s=str(service['id'])))
            ra_service_details = self.retrieve_virtualization_realm_service(vr_id=vr_id, service_id=service['id'])
            return ra_service_details

        # Log RA service was not found
        log.info('Remote access service not found for VR ID: [{v}]'.format(v=str(vr_id)))

    def enable_remote_access(self, vr_id, rdp_proxy_enabled=True, instance_type=None, guac_ip_address=None,
                             remote_access_port=None, ra_vr_service=None):
        """Enables Remote Access for a specific virtualization realm, and uses SMALL
        as the default size if none is provided.

        :param vr_id: (int) Virtualization Realm ID
        :param rdp_proxy_enabled: (bool) Set True to enable RDP proxy
        :param instance_type: (str) SMALL/MEDIUM/LARGE
        :param guac_ip_address: (str) IP address of the guacd server
        :param remote_access_port: (int) TCP port for the guacd server
        :param ra_vr_service: (dict) Service info
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.enable_remote_access')

        # Default values
        default_instance_type = 'MEDIUM'
        default_guac_ip_address = '172.16.10.253'
        default_remote_access_port = 9443

        # Actual values to be determined
        actual_instance_type = None
        actual_guac_ip_address = None
        actual_remote_access_port = None

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise Cons3rtApiError('vr_id arg must be an Integer') from exc

        # Get the remote access service ID/info
        if not ra_vr_service:
            ra_vr_service = self.get_remote_access_service(vr_id=vr_id)

        # Acceptable sizes
        if instance_type:
            instance_type = instance_type.upper()
            if instance_type not in remote_access_sizes:
                raise Cons3rtApiError('The size arg must be one of [{s}]'.format(s=','.join(remote_access_sizes)))

        # Validate the guac IP address
        if guac_ip_address:
            if not validate_ip_address(guac_ip_address):
                raise Cons3rtApiError('Invalid guac IP address provided [{g}]'.format(g=guac_ip_address))

        # Validate the guac port
        if remote_access_port:
            try:
                int(remote_access_port)
            except ValueError:
                raise Cons3rtApiError('Invalid remote access port [{p}], must be an Integer'.format(
                    p=str(remote_access_port)))

        # Check if the RA service was found
        if not ra_vr_service:

            # Set values
            if instance_type:
                actual_instance_type = instance_type
            else:
                actual_instance_type = default_instance_type
            if guac_ip_address:
                actual_guac_ip_address =  guac_ip_address
            else:
                actual_guac_ip_address = default_guac_ip_address
            if remote_access_port:
                actual_remote_access_port =  remote_access_port
            else:
                actual_remote_access_port = default_remote_access_port

            log.info('Adding RA service for VR [{v}], with size [{s}], guac IP [{g}], port [{p}], and RDP proxy '
                     '[{r}]'.format(v=str(vr_id), s=actual_instance_type, g=actual_guac_ip_address,
                                    p=str(actual_remote_access_port), r=str(rdp_proxy_enabled)))
            ra_vr_service = self.update_remote_access_virtualization_realm_service(
                vr_id=vr_id,
                instance_type=actual_instance_type,
                guac_ip_address=actual_guac_ip_address,
                remote_access_port=actual_remote_access_port,
                rdp_proxy_enabled=rdp_proxy_enabled
            )
        else:
            # Track whether to update the cloudspace or RA config before enabling RA
            update_ra_config = False

            # Check to see if settings need to be updated
            if instance_type:
                if 'instanceType' in ra_vr_service.keys():
                    if instance_type != ra_vr_service['instanceType']:
                        actual_instance_type = instance_type
                        update_ra_config = True
                    else:
                        actual_instance_type = ra_vr_service['instanceType']
                else:
                    actual_instance_type = default_instance_type
            else:
                actual_instance_type = default_instance_type

            if guac_ip_address:
                if 'guacIpAddress' in ra_vr_service.keys():
                    if guac_ip_address != ra_vr_service['guacIpAddress']:
                        actual_guac_ip_address = guac_ip_address
                        update_ra_config = True
                    else:
                        actual_guac_ip_address = ra_vr_service['guacIpAddress']
                else:
                    actual_guac_ip_address = default_guac_ip_address
            else:
                actual_guac_ip_address = default_guac_ip_address

            if remote_access_port:
                if 'remoteAccessPort' in ra_vr_service.keys():
                    if remote_access_port != ra_vr_service['remoteAccessPort']:
                        actual_remote_access_port = remote_access_port
                        update_ra_config = True
                    else:
                        actual_remote_access_port = ra_vr_service['remoteAccessPort']
                else:
                    actual_remote_access_port = default_remote_access_port
            else:
                actual_remote_access_port = default_remote_access_port

            if rdp_proxy_enabled:
                if 'rdpProxyingEnabled' in ra_vr_service.keys():
                    if rdp_proxy_enabled != ra_vr_service['rdpProxyingEnabled']:
                        update_ra_config = True

            if update_ra_config:
                log.info('Updating RA service for VR [{v}], with size [{s}], guac IP [{g}], port [{p}], and RDP proxy '
                         '[{r}]'.format(v=str(vr_id), s=actual_instance_type, g=actual_guac_ip_address,
                                        p=str(actual_remote_access_port), r=str(rdp_proxy_enabled)))
                ra_vr_service = self.update_remote_access_virtualization_realm_service(
                    vr_id=vr_id,
                    instance_type=actual_instance_type,
                    guac_ip_address=actual_guac_ip_address,
                    remote_access_port=actual_remote_access_port,
                    rdp_proxy_enabled=rdp_proxy_enabled
                )

        # Attempt to enable remote access
        log.info('Attempting to enable the remote access VR service ID [{v}] in VR ID [{i}]...'.format(
            v=vr_id, i=str(ra_vr_service['serviceId'])))
        try:
            self.update_virtualization_realm_service_state(
                vr_id=vr_id, service_id=ra_vr_service['serviceId'], state='enable')
        except Cons3rtClientError as exc:
            msg = 'Problem enabling remote access in virtualization realm ID: {i}'.format(i=vr_id)
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully enabled remote access in virtualization realm: {i}'.format(i=vr_id))

    def disable_remote_access(self, vr_id):
        """Disables Remote Access for a specific virtualization realm

        :param vr_id: (int) ID of the virtualization
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.disable_remote_access')

        already_disabled_statuses = ['DISABLED', 'DISABLING']

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise ValueError('vr_id arg must be an Integer') from exc

        # Get the remote access service ID/info
        ra_vr_service = self.get_remote_access_service(vr_id=vr_id)

        # Check if the RA service was found
        if not ra_vr_service:
            log.info('Remote access service not found for VR ID {i}, nothing to disable'.format(i=str(vr_id)))
            return

        if ra_vr_service['serviceStatus'] in already_disabled_statuses:
            log.info('Remote access service in VR ID [{i}] service [{s}] is already disabled or disabling'.format(
                i=str(vr_id), s=str(ra_vr_service['serviceId'])))
        else:
            # Attempt to disable remote access
            log.info('Attempting to disable remote access in VR [{i}] service [{s}]...'.format(
                i=str(vr_id), s=str(ra_vr_service['serviceId'])))
            try:
                self.update_virtualization_realm_service_state(
                    vr_id=vr_id, service_id=ra_vr_service['serviceId'], state='disable')
            except Cons3rtClientError as exc:
                msg = 'Problem disabling remote access in VR [{i}] service [{s}]\n{e}'.format(
                    i=str(vr_id), s=str(ra_vr_service['serviceId']), e=str(exc))
                raise Cons3rtApiError(msg) from exc
            log.info('Successfully disabled remote access in VR [{i}] service [{s}]'.format(
                i=str(vr_id), s=str(ra_vr_service['serviceId'])))


    def toggle_remote_access(self, vr_id, rdp_proxy_enabled=True, instance_type=None, guac_ip_address=None,
                             remote_access_port=None):
        """Enables Remote Access for a specific virtualization realm, and uses SMALL
        as the default size if none is provided.

        :param vr_id: (int) Virtualization Realm ID
        :param rdp_proxy_enabled: (bool) Set True to enable RDP proxy
        :param instance_type: (str) SMALL/MEDIUM/LARGE
        :param guac_ip_address: (str) IP address of the guacd server
        :param remote_access_port: (int) TCP port for the guacd server
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.toggle_remote_access')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                raise ValueError('vr_id arg must be an Integer') from exc

        # Get the RA VR service
        ra_vr_service = self.get_remote_access_service(vr_id=vr_id)

        # Disable remote access
        log.info('Disabling remote access for VR ID: [{i}]'.format(i=str(vr_id)))
        try:
            self.disable_remote_access(vr_id=vr_id)
        except Cons3rtApiError as exc:
            msg = 'Problem disabling remote access for VR ID [{i}]\n{e}'.format(i=str(vr_id), e=str(exc))
            raise Cons3rtApiError(msg) from exc

        # Wait for the RA service to reach the end state
        self.wait_virtualization_realm_service_state(vr_id=vr_id, service_id=ra_vr_service['serviceId'],
                                                     end_state='DISABLED', status_type='raStatus')

        # Enable remote access
        log.info('Enabling remote access for VR ID: [{i}]'.format(i=str(vr_id)))
        try:
            self.enable_remote_access(vr_id=vr_id, rdp_proxy_enabled=rdp_proxy_enabled, instance_type=instance_type,
                                      guac_ip_address=guac_ip_address, remote_access_port=remote_access_port,
                                      ra_vr_service=ra_vr_service)
        except Cons3rtApiError as exc:
            msg = 'Problem enabling remote access for VR ID [{i}]\n{e}'.format(i=str(vr_id), e=str(exc))
            raise Cons3rtApiError(msg) from exc

        log.info('Remote access toggle complete for VR ID [{i}]'.format(i=str(vr_id)))

    def disable_vr_services(self, vr_id):
        """Disabled VR services for the specified VR

        :param vr_id: (int) Virtualization Realm ID
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.disable_vr_services')

        # Get VR details
        vr_details = self.get_virtualization_realm_details(vr_id=vr_id)

        # Check for services
        if 'services' not in vr_details.keys():
            log.info('VR ID [{{i}] has no services'.format(i=str(vr_id)))
            return

        # Loop through service to find the remote access service
        for service in vr_details['services']:
            if 'id' not in service.keys():
                continue
            log.info('Found VR [{v}] remote access service ID to disable: [{s}]'.format(
                v=str(vr_id), s=str(service['id'])))
            self.update_virtualization_realm_service_state(vr_id=vr_id, service_id=service['id'], state='disable')

    def retrieve_all_users(self):
        """Retrieve all users from the CONS3RT site

        :return: (list) containing all site users
        :raises: Cons3rtApiError
        """
        return self.list_users()

    def list_all_users(self):
        """Retrieve all users from the CONS3RT site

        :return: (list) containing all site users
        :raises: Cons3rtApiError
        """
        return self.list_users()

    def list_active_users(self):
        """Retrieve active users from the CONS3RT site

        :return: (list) containing all site users
        :raises: Cons3rtApiError
        """
        return self.list_users(state='ACTIVE')

    def list_inactive_users(self):
        """Retrieve inactive users from the CONS3RT site

        :return: (list) containing all site users
        :raises: Cons3rtApiError
        """
        return self.list_users(state='INACTIVE')

    def list_requested_users(self):
        """Retrieve requested users from the CONS3RT site

        :return: (list) containing all site users
        :raises: Cons3rtApiError
        """
        return self.list_users(state='REQUESTED')

    def list_users(self, state=None, created_before=None, created_after=None, max_results=500):
        """Query CONS3RT to list site users

        :param state: (state) user state "REQUESTED" "ACTIVE" "INACTIVE"
        :param created_before: (int) Date (seconds since epoch) to filter on
        :param created_after: (int) Date (seconds since epoch) to filter on
        :param max_results: (int) maximum results to return per page
        :return: (list) Containing all site users
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_users')
        if state:
            state_str = state
        else:
            state_str = 'ALL_STATES'
        log.info('Attempting to list site users: {s}'.format(s=state_str))

        # Get a list of users
        try:
            users = self.cons3rt_client.list_users(state=state, created_before=created_before,
                                                   created_after=created_after, max_results=max_results)
        except Cons3rtClientError as exc:
            msg = 'Problem getting a list of users'
            raise Cons3rtApiError(msg) from exc
        log.info('Found {n} users with state: {s}'.format(n=str(len(users)), s=state_str))
        return users

    def list_team_managers(self, active_only=False, not_expired=False):
        """Retrieves a list of team managers for all teams

        :param active_only (bool) Set true to return only teams that are active
        :param not_expired (bool) Set true to return only teams that are not expired
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
            teams = self.list_teams(active_only=active_only, not_expired=not_expired)
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
                    log.info('Found team manager for team ID [{t}], team name [{n}], user ID [{i}], and username [{u}]'
                             .format(t=team['id'], n=team['name'], i=team_manager['id'], u=team_manager['username']))
                    team_manager['teamIds'] = [team['id']]
                    team_manager['teamNames'] = [team['name']]
                    team_managers.append(team_manager)
        log.info('Found {n} team managers'.format(n=str(len(team_managers))))
        return team_managers

    def print_team_managers_emails(self, filter_domains=None):
        """Prints a semicolon separated list of email addresses of each team manager

        :param filter_domains: (list) of domains to keep out of the printed output
        :return: (list) of team managers filters by domain:
            {
                "id": ID,
                "username": USERNAME,
                "email": EMAIL,
                "teamIds": list of team IDs,
                "teamNames": list of team names
            }
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.print_team_managers_emails')
        if filter_domains:
            if not isinstance(filter_domains, list):
                raise Cons3rtApiError('Expected filter_domains to be a list, found: {t}'.format(
                    t=filter_domains.__class__.__name__))
        else:
            filter_domains = []
        team_managers = self.list_team_managers(active_only=True, not_expired=True)
        team_manager_emails = ''
        for team_manager in team_managers:
            if 'email' not in team_manager.keys():
                log.warning('Team manager did not include email data: {d}'.format(d=str(team_manager)))
                continue
            include_email = True
            for filter_domain in filter_domains:
                if filter_domain in team_manager['email']:
                    log.info('Skipping team manager email: {e}'.format(e=team_manager['email']))
                    include_email = False
            if include_email:
                log.info('Including team manager email: {e}'.format(e=team_manager['email']))
                team_manager_emails += team_manager['email'] + '; '
        team_manager_emails.rstrip(';')
        print(team_manager_emails)
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

    def list_teams_for_team_manager(self, username, not_expired=False, active_only=False):
        """Get a list of teams managers by the provided username

        :param username: (str) username of the team manager
        :param active_only (bool) Set true to return only teams that are active
        :param not_expired (bool) Set true to return only teams that are not expired
        :return: (list) of teams in format:
                        {
                            'id': team_id,
                            'name': team_name
                        }
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_teams_for_team_manager')

        # Store the list of teams this user manages
        user_teams = []

        # Get a list of team managers for all teams
        try:
            team_managers = self.list_team_managers(not_expired=not_expired, active_only=active_only)
        except Cons3rtApiError as exc:
            msg = 'Problem getting a list of team managers for the site'
            raise Cons3rtApiError(msg) from exc

        user_info = None
        for team_manager in team_managers:
            if team_manager['username'] == username:
                user_info = team_manager
                break

        # Return if no teams were found
        if not user_info:
            log.info('User is not found as a team manager: {u}'.format(u=username))
            return user_teams

        print(user_info['teamIds'])

        # Build the list of teams from the user info
        for team_id, team_name in zip(user_info['teamIds'], user_info['teamNames']):
            user_teams.append({
                'id': team_id,
                'name': team_name
            })
        log.info('User {u} is a manager of {n} teams'.format(u=username, n=str(len(user_teams))))
        print(user_teams)
        return user_teams

    def list_team_members(self, team_id, blocked=False, unique=False):
        """Retrieves a list of members for all projects in a team

        :param team_id (int) Team ID
        :param blocked (bool) Set true to include blocked project members
        :param unique (bool) Set true to return a unique list of team members
        :return: (list) of team members in this format:
                {
                    'team_id': team_id,
                    'project_name': team_project['name'],
                    'username': team_project_member['username'],
                    'email': team_project_member['email'],
                    'state': team_project_member['membershipState']
                }

            If unique is True, the project name is set to the team name, and the state is N/A
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_team_members')
        log.info('Attempting to list team project members...')

        # Get a list of project in the team
        try:
            team_details, team_projects = self.list_projects_in_team(team_id=team_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing projects in team: {i}'.format(i=str(team_id))
            raise Cons3rtApiError(msg) from exc

        # Save a list of team members
        team_members = []

        for team_project in team_projects:
            # Add active members
            try:
                team_project_members = self.list_project_members(
                    project_id=team_project['id'], state='ACTIVE'
                )
            except Cons3rtApiError as exc:
                msg = 'Problem getting active project members from: {n}'.format(n=team_project['name'])
                raise Cons3rtApiError(msg) from exc

            # Add blocked members
            if blocked:
                try:
                    team_project_members += self.list_project_members(
                        project_id=team_project['id'], state='BLOCKED'
                    )
                except Cons3rtApiError as exc:
                    msg = 'Problem getting blocked project members from: {n}'.format(n=team_project['name'])
                    raise Cons3rtApiError(msg) from exc

            log.debug('In team {i}, found {n} users in project: {t}'.format(
                i=str(team_id), n=str(len(team_project_members)),
                t=team_project['name']))

            # Build a unique list of users
            if unique:
                # Store the unique project members
                unique_team_project_members = []

                # Store the unique user IDs, which is used as the unique identifier
                unique_ids = set()

                # Build the list of project members unique by user ID
                for team_project_member in team_project_members:
                    if team_project_member['id'] not in unique_ids:
                        unique_ids.add(team_project_member['id'])
                        unique_team_project_members.append(team_project_member)

                # Build the output list of team members based on the unique list
                #   Fill in the team name for project name
                #   Fill in N/A for membership state
                for unique_team_project_member in unique_team_project_members:
                    team_members.append({
                        'team_id': team_id,
                        'project_name': team_details['name'],
                        'username': unique_team_project_member['username'],
                        'email': unique_team_project_member['email'],
                        'state': 'N/A'
                    })
            else:
                # Build a list including project data, can include the same user in multiple projects
                for team_project_member in team_project_members:
                    team_members.append({
                        'team_id': team_id,
                        'project_name': team_project['name'],
                        'username': team_project_member['username'],
                        'email': team_project_member['email'],
                        'state': team_project_member['membershipState']
                    })

        log.info('Found {n} team members'.format(n=str(len(team_members))))
        return team_members

    def list_unique_team_members_for_teams(self, team_ids, blocked=False):
        """Retrieves a list of members for all projects in a team

        :param team_ids (list) of int team ID
        :param blocked (bool) Set true to include blocked project members
        :return: (list) of team members in this format:
                {
                    'team_id': team_id,
                    'project_name': team_project['name'],
                    'username': team_project_member['username'],
                    'email': team_project_member['email'],
                    'state': team_project_member['membershipState']
                }

            If unique is True, the project name is set to the team name, and the state is N/A
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_unique_team_members_for_teams')
        log.info('Attempting to list unique members across multiple teams...')

        # Store the unique team members and user IDs
        unique_cross_team_members = []
        unique_users = set()

        # Get members for each of the teams
        for team_id in team_ids:
            # Get a list of members in the team
            try:
                team_members = self.list_team_members(team_id=team_id, blocked=blocked, unique=True)
            except Cons3rtApiError as exc:
                msg = 'Problem listing members in team: {i}'.format(i=str(team_id))
                raise Cons3rtApiError(msg) from exc

            for team_member in team_members:
                if 'username' not in team_member.keys():
                    msg = 'expected username in team member data: {d}'.format(d=str(team_member))
                    raise Cons3rtApiError(msg)
                if team_member['username'] not in unique_users:
                    unique_users.add(team_member['username'])
                    unique_cross_team_members.append(team_member)

        # Log and return the result
        log.info('Found {n} unique team members across team IDs: {i}'.format(
            n=str(len(unique_cross_team_members)), i=','.join(map(str, team_ids))))
        return unique_cross_team_members

    def list_services_for_team(self, team_id):
        """Lists the services for a team

        :param team_id: (int) team ID
        :return: (dict)
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_services_for_team')
        if not isinstance(team_id, int):
            try:
                team_id = int(team_id)
            except ValueError as exc:
                raise Cons3rtApiError('team_id arg must be an Integer') from exc

        # Attempt to list team services
        try:
            team_services = self.cons3rt_client.list_services_for_team(team_id=team_id)
        except Cons3rtClientError as exc:
            msg = 'Unable to list services for team: {i}'.format(i=str(team_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Found [{n}] services for team [{i}]'.format(n=str(len(team_services)), i=str(team_id)))
        return team_services

    def list_users_for_team_service(self, team_id, service_type):
        """Lists the users in a service for team

        :param team_id: (int) team ID
        :param service_type: (str) Service Type: 'AtlassianBitbucket', 'AtlassianConfluence', 'AtlassianJira',
            'AtlassianJiraAssetManagement', 'AtlassianJiraServiceManagement', 'GitlabPremium', 'GitlabUltimate',
            'Mattermost', 'ProvisioningUser'
        :return: (list) user (dict)
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_services_for_team')

        # Ensure the team ID is an int
        if not isinstance(team_id, int):
            try:
                team_id = int(team_id)
            except ValueError as exc:
                raise Cons3rtApiError('team_id arg must be an Integer') from exc

        if not isinstance(service_type, str):
            raise Cons3rtApiError('service_type arg must be a str')

        # Ensure the service type is valid
        if service_type not in service_types:
            raise Cons3rtApiError('Provided service type must be one of: [{s}]'.format(s=','.join(service_types)))

        # Retrieve users for team service
        log.info('Retrieving users for team ID [{t}] service type [{s}]'.format(t=str(team_id), s=service_type))
        try:
            service_users = self.cons3rt_client.list_users_for_team_service(team_id=team_id, service_type=service_type)
        except Cons3rtClientError as exc:
            msg = 'Unable to list users of service [{s}] in team ID: [{t}]'.format(s=service_type, t=str(team_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Found [{n}] users of service [{s}] in team ID: [{t}]'.format(
            n=str(len(service_users)), s=service_type, t=str(team_id)))
        return service_users

    def list_all_service_users_for_team(self, team_id):
        """Lists the users in all service for team

        :param team_id: (int) team ID
        :return: (list) of service user info with service type appended
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_all_service_users_for_team')

        try:
            team_services = self.list_services_for_team(team_id=team_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing services for team ID [{t}]'.format(t=str(team_id))
            raise Cons3rtApiError(msg) from exc

        log.info('List users in all services for team: [{t}]'.format(t=str(team_id)))
        service_users = []

        # Collect the users for each team service
        for team_service in team_services:
            if 'serviceType' not in team_service.keys():
                raise Cons3rtApiError('serviceType not found in team service: [{d}]'.format(d=str(team_service)))
            service_type = team_service['serviceType']
            service_type_users = self.cons3rt_client.list_users_for_team_service(
                team_id=team_id, service_type=service_type)
            for service_type_user in service_type_users:
                service_type_user['service_type'] = service_type
                service_users.append(service_type_user)
        log.info('Found [{n}] users of team services in team ID [{t}]'.format(
            n=str(len(service_users)), t=str(team_id)))
        return service_users

    def list_bitbucket_users_for_team(self, team_id):
        return self.list_users_for_team_service(team_id=team_id, service_type='AtlassianBitbucket')

    def list_confluence_users_for_team(self, team_id):
        return self.list_users_for_team_service(team_id=team_id, service_type='AtlassianConfluence')

    def list_jira_users_for_team(self, team_id):
        return self.list_users_for_team_service(team_id=team_id, service_type='AtlassianJira')

    def list_jira_asset_management_users_for_team(self, team_id):
        return self.list_users_for_team_service(team_id=team_id, service_type='AtlassianJiraAssetManagement')

    def list_jira_service_management_users_for_team(self, team_id):
        return self.list_users_for_team_service(team_id=team_id, service_type='AtlassianJiraServiceManagement')

    def list_gitlab_premium_users_for_team(self, team_id):
        return self.list_users_for_team_service(team_id=team_id, service_type='GitlabPremium')

    def list_gitlab_ultimate_users_for_team(self, team_id):
        return self.list_users_for_team_service(team_id=team_id, service_type='GitlabUltimate')

    def list_mattermost_users_for_team(self, team_id):
        return self.list_users_for_team_service(team_id=team_id, service_type='Mattermost')

    def list_provisioning_users_for_team(self, team_id):
        return self.list_users_for_team_service(team_id=team_id, service_type='ProvisioningUser')


    def create_user(self, username, email, first_name, last_name):
        """Creates a user using the specified parameters

        :param username: (str) Username
        :param email: (str) email address
        :param first_name: (str) first name
        :param last_name: (str) last name
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_user')

        # Create the dict containing the user content
        user_content = {
            'username': username,
            'email': email,
            'firstname': first_name,
            'lastname': last_name
        }

        # Attempt to create the user
        try:
            self.cons3rt_client.create_user(user_content=user_content)
        except Cons3rtClientError as exc:
            msg = 'Unable to create user from data: {d}'.format(d=str(user_content))
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully created user with username: {u}'.format(u=username))

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

        # Attempt to create the user
        try:
            self.cons3rt_client.create_user(user_file=json_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a User using JSON file: {f}'.format(f=json_file)
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully created User from file: {f}'.format(f=json_file))

    def create_single_user(self, username, first_name, last_name, email_address, encoded_pem, phone=None, organization=None):
        """Creates a CONS3RT User using the provided PEM file and information

        NOTE - Currently this call is not supporting the teamServiceMap and nonTeamServiceProjectMap objects

        :param username: (str) CONS3RT username
        :param first_name: (str) first name
        :param last_name: (str) last name
        :param email_address: (str) email address
        :param encoded_pem: (str) encoded public key pem file
        :param phone: (str) phone number (optional)
        :param organization: (str) organization (optional)
        :return: Created user data
        :raises: Cons3rtClientError
        """
        log = logging.getLogger(self.cls_logger + '.create_users')

        # Attempt to create the users
        try:
            created_user_data = self.cons3rt_client.create_single_user(
                username=username, first_name=first_name, last_name=last_name, email_address=email_address,
                encoded_pem=encoded_pem, phone=phone, organization=organization
            )
        except Cons3rtClientError as exc:
            msg = 'Unable to create username [{u}] with pem file [{p}]'.format(u=username, p=encoded_pem)
            raise Cons3rtApiError(msg) from exc
        log.info('Successfully created user with username: {u}'.format(u=username))
        return created_user_data

    def delete_user(self, user_id):
        """Delete a user by user ID

        TBD: THIS CALL DOES NOT EXIST IN CONS3RT AS OF 7/12/2022

        :param user_id: (int) ID of the user to delete
        :return:
        """
        pass

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

    def assign_role_to_project_member(self, project_id, username, role):
        """Assigns the provided role to the username in the project ID
        :param project_id: (int) project ID
        :param username: (str) CONS3RT username
        :param role: (str) project role
        :return: (bool) True if successful
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.assign_role_to_project_member')

        # Ensure the username and role args are strings
        if not isinstance(username, str):
            msg = 'The username arg must be a string'
            raise Cons3rtApiError(msg)
        if not isinstance(role, str):
            msg = 'The role arg must be a string'
            raise Cons3rtApiError(msg)

        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the role is valid
        if role not in valid_member_roles:
            msg = 'role [{r}] invalid, must be one of: {v}'.format(r=role, v=','.join(valid_member_roles))
            raise Cons3rtApiError(msg)

        # Attempt assign the role to the user
        try:
            res = self.cons3rt_client.assign_role_to_project_member(project_id=project_id, username=username, role=role)
        except Cons3rtClientError as exc:
            msg = 'Unable to assign role [{r}] to user [{u}] in project ID: {i}'.format(
                r=role, u=username, i=str(project_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Added role [{r}] to user [{u}] in project ID: {i}'.format(r=role, i=str(project_id), u=username))
        return res

    def unassign_role_from_project_member(self, project_id, username, role):
        """Assigns the provided role to the username in the project ID
        :param project_id: (int) project ID
        :param username: (str) CONS3RT username
        :param role: (str) project role
        :return: (bool) True if successful
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.unassign_role_from_project_member')

        # Ensure the username and role args are strings
        if not isinstance(username, str):
            msg = 'The username arg must be a string'
            raise Cons3rtApiError(msg)
        if not isinstance(role, str):
            msg = 'The role arg must be a string'
            raise Cons3rtApiError(msg)

        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the role is valid
        if role not in valid_member_roles:
            msg = 'role [{r}] invalid, must be one of: {v}'.format(r=role, v=','.join(valid_member_roles))
            raise Cons3rtApiError(msg)

        # Attempt assign the role to the user
        try:
            res = self.cons3rt_client.unassign_role_from_project_member(
                project_id=project_id, username=username, role=role)
        except Cons3rtClientError as exc:
            msg = 'Unable to unassign role [{r}] from user [{u}] in project ID: {i}'.format(
                r=role, u=username, i=str(project_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Removed role [{r}] from user [{u}] in project ID: {i}'.format(r=role, i=str(project_id), u=username))
        return res

    def assign_roles_to_project_member(self, project_id, username, project_role_list):
        """Assigns the all roles in the project ID
        :param project_id: (int) project ID
        :param username: (str) CONS3RT username
        :param project_role_list (list) List of str roles
        :return: (bool) True if successful
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.assign_roles_to_project_member')

        # Ensure the username is a string
        if not isinstance(username, str):
            msg = 'The username arg must be a string'
            raise Cons3rtApiError(msg)

        # Ensure the project_role_list is a list
        if not isinstance(project_role_list, list):
            msg = 'The project_role_list arg must be a list'
            raise Cons3rtApiError(msg)

        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Assign the standard and project manager roles
        for role in project_role_list:
            try:
                self.assign_role_to_project_member(project_id=project_id, username=username, role=role)
            except Cons3rtClientError as exc:
                msg = 'Unable to assign role [{r}] to user [{u}] in project ID: {i}'.format(
                    r=role, u=username, i=str(project_id))
                raise Cons3rtApiError(msg) from exc
        log.info('Assigned roles to user [{u}] in project ID {p}: {r}'.format(
            p=str(project_id), u=username, r=','.join(project_role_list)))
        return True

    def unassign_roles_from_project_member(self, project_id, username, project_role_list):
        """Removed the all roles for the member in the project ID
        :param project_id: (int) project ID
        :param username: (str) CONS3RT username
        :param project_role_list (list) List of str roles
        :return: (bool) True if successful
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.unassign_roles_from_project_member')

        # Ensure the username is a string
        if not isinstance(username, str):
            msg = 'The username arg must be a string'
            raise Cons3rtApiError(msg)

        # Ensure the project_role_list is a list
        if not isinstance(project_role_list, list):
            msg = 'The project_role_list arg must be a list'
            raise Cons3rtApiError(msg)

        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=project_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Get current list of permissions for user in project
        log.info('Getting current roles for user [{u}] in project ID: {p}'.format(u=username, p=str(project_id)))
        try:
            project_members = self.list_project_members(project_id=project_id, username=username)
        except Cons3rtApiError as exc:
            msg = 'Unable to get current roles for user [{u}] in project ID: {p}'.format(u=username, p=str(project_id))
            raise Cons3rtApiError(msg) from exc

        # Get the list of roles from the response
        current_project_roles = None
        for project_member in project_members:
            if 'username' not in project_member.keys():
                log.warning('username not found in project member data: {d}'.format(d=str(project_member)))
                continue
            if 'roles' not in project_member.keys():
                log.warning('roles not found in project member data: {d}'.format(d=str(project_member)))
                continue
            if project_member['username'] == username:
                current_project_roles = project_member['roles']
                break

        # Raise exception if the user roles were not found
        if not current_project_roles:
            msg = 'User [{u}] not found in project ID: {p}'.format(u=username, p=str(project_id))
            raise Cons3rtApiError(msg)

        log.info('User [{u}] currently has roles in project ID {p}: {r}'.format(
            u=username, p=str(project_id), r=','.join(current_project_roles)))

        # Build the list of project roles to unassign
        unassign_roles = []
        for project_role in project_role_list:
            if project_role in current_project_roles:
                unassign_roles.append(project_role)

        log.info('Unassigning roles for user [{u}] in project ID {p}: {r}'.format(
            u=username, p=str(project_id), r=','.join(unassign_roles)))

        # Assign the standard and project manager roles
        for project_role in unassign_roles:
            try:
                self.unassign_role_from_project_member(project_id=project_id, username=username, role=project_role)
            except Cons3rtApiError as exc:
                msg = 'Unable to unassign role [{r}] from user [{u}] in project ID: {i}'.format(
                    r=project_role, u=username, i=str(project_id))
                raise Cons3rtApiError(msg) from exc
        log.info('Unassigned roles from user [{u}] in project ID {p}: {r}'.format(
            p=str(project_id), u=username, r=','.join(unassign_roles)))
        return True

    def assign_express_member(self, project_id, username):
        """Assigns the express roles in the project ID
        :param project_id: (int) project ID
        :param username: (str) CONS3RT username
        :return: (bool) True if successful
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.assign_express_member')
        roles = standard_roles + asset_developer_roles + project_manager_roles
        self.unassign_roles_from_project_member(
            project_id=project_id,
            username=username,
            project_role_list=roles
        )
        log.info('User [{u}] has express roles in project ID: {p}'.format(p=str(project_id), u=username))
        return True

    def assign_project_manager(self, project_id, username):
        """Assigns the project owner+manager roles in the project ID
        :param project_id: (int) project ID
        :param username: (str) CONS3RT username
        :return: (bool) True if successful
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.assign_project_manager')
        roles = standard_roles + project_manager_roles
        self.assign_roles_to_project_member(
            project_id=project_id,
            username=username,
            project_role_list=roles
        )
        log.info('User [{u}] has project manager/owner roles in project ID: {p}'.format(p=str(project_id), u=username))
        return True

    def assign_asset_developer(self, project_id, username):
        """Assigns the asset developer roles in the project ID
        :param project_id: (int) project ID
        :param username: (str) CONS3RT username
        :return: (bool) True if successful
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.assign_asset_developer')
        roles = standard_roles + asset_developer_roles
        self.assign_roles_to_project_member(
            project_id=project_id,
            username=username,
            project_role_list=roles
        )
        log.info('User [{u}] has asset developer roles in project ID: {p}'.format(p=str(project_id), u=username))
        return True

    def assign_all_project_roles(self, project_id, username):
        """Assigns the all roles in the project ID
        :param project_id: (int) project ID
        :param username: (str) CONS3RT username
        :return: (bool) True if successful
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.assign_all_project_roles')
        roles = standard_roles + project_manager_roles + asset_developer_roles
        self.assign_roles_to_project_member(
            project_id=project_id,
            username=username,
            project_role_list=roles
        )
        log.info('User [{u}] has ALL roles in project ID: {p}'.format(p=str(project_id), u=username))
        return True

    def create_system(
            self,
            name=None,
            operating_system=None,
            min_num_cpus=2,
            min_ram=2000,
            min_boot_disk_capacity=100000,
            additional_disks=None,
            components=None,
            subtype='virtualHost',
            vgpu_required=False,
            physical_machine_id=None,
            json_content=None,
            json_file=None
    ):
        """Creates a system from the provided options

        :param name: (str) system name
        :param operating_system: (str) see CONS3RT API docs
        :param min_num_cpus: (int) see CONS3RT API docs
        :param min_ram: (int) see CONS3RT API docs
        :param min_boot_disk_capacity: (int) see CONS3RT API docs
        :param additional_disks: (list) see CONS3RT API docs
        :param components: (list) see CONS3RT API docs
        :param subtype: (str) see CONS3RT API docs
        :param vgpu_required: (bool) see CONS3RT API docs
        :param physical_machine_id (int) see CONS3RT API docs
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

                if not isinstance(physical_machine_id, int):
                    try:
                        physical_machine_id = int(physical_machine_id)
                    except ValueError as exc:
                        raise Cons3rtApiError('physical_machine_id must be an Integer, found: {t}'.format(
                            t=physical_machine_id.__class__.__name__)) from exc

                content['physicalMachine'] = {}
                content['physicalMachine']['id'] = physical_machine_id

            elif subtype == 'virtualHost':
                log.debug('Creating JSON content from params for a virtual host template profile...')
                content['templateProfile'] = {}
                content['templateProfile']['operatingSystem'] = operating_system
                content['templateProfile']['minNumCpus'] = min_num_cpus
                content['templateProfile']['minRam'] = min_ram
                content['templateProfile']['remoteAccessRequired'] = 'true'
                content['templateProfile']['minBootDiskCapacity'] = min_boot_disk_capacity
                if vgpu_required:
                    content['templateProfile']['vgpuRequired'] = 'true'
                else:
                    content['templateProfile']['vgpuRequired'] = 'false'
                if additional_disks:
                    if not isinstance(additional_disks, list):
                        raise Cons3rtApiError('additional_disks must be list, found: {t}'.format(
                            t=additional_disks.__class__.__name__))
                    content['templateProfile']['additionalDisks'] = additional_disks

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

    def release_deployment_run(self, dr_id, unlock=False):
        """Release a deployment run by ID

        :param: dr_id: (int) deployment run ID
        :param: unlock: (bool) set true to unlock before releasing the run
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

        # Unlock the run if specified
        if unlock:
            try:
                self.set_deployment_run_lock(dr_id=dr_id, lock=False)
            except Cons3rtClientError as exc:
                msg = 'Unable to unlock deployment run ID: {i}'.format(i=str(dr_id))
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

    def add_project_to_virtualization_realm(self, vr_id, project_id):
        """Deletes all inactive runs in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :param project_id: (int) project ID
        :return: (int) number of runs deleted
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.add_project_to_virtualization_realm')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=str(type(vr_id)))
                raise Cons3rtApiError(msg) from exc

        # Ensure the project_id is an int
        if not isinstance(project_id, int):
            try:
                project_id = int(project_id)
            except ValueError as exc:
                msg = 'project_id arg must be an Integer, found: {t}'.format(t=str(type(project_id)))
                raise Cons3rtApiError(msg) from exc

        # Add the project to the virtualization realm
        log.info('Adding project [{p}] to virtualization realm [{v}]'.format(p=str(project_id), v=str(vr_id)))
        try:
            self.cons3rt_client.add_project_to_virtualization_realm(vr_id=vr_id, project_id=project_id)
        except Cons3rtClientError as exc:
            msg = 'Problem adding project ID [{p}] to VR ID [{v}]'.format(v=str(vr_id), p=str(project_id))
            raise Cons3rtApiError(msg) from exc

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

        # Keep track of deleted runs and not deleted runs
        deleted_runs = []
        not_deleted_runs = []

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
            # Ensure id data exists
            if 'id' not in dr.keys():
                log.warning('Unable to determine the run ID from run: {r}'.format(r=str(dr)))
                not_deleted_runs.append(dr)
                continue

            # Try to delete the inactive run
            try:
                self.delete_inactive_run(dr_id=dr['id'])
            except Cons3rtApiError as exc:
                log.warning('Cons3rtApiError: Unable to delete run ID: {i}\n{e}'.format(i=str(dr['id']), e=str(exc)))
                not_deleted_runs.append(dr)
            else:
                log.info('Deleted run [{r}] from virtualization realm: {v}'.format(r=str(dr['id']), v=vr_id))
                deleted_runs.append(dr)

        processed_runs = len(deleted_runs) + len(not_deleted_runs)
        if len(drs) != processed_runs:
            log.warning('The total runs [{t}] in virtualization realm {v} did not equal the number of runs processed'
                        'for deletion: {p}'.format(t=str(len(drs)), v=str(vr_id), p=str(processed_runs)))

        log.info('Deleted {n} inactive runs in virtualization realm ID: {i}'.format(
            i=str(vr_id), n=str(len(deleted_runs))))
        if len(not_deleted_runs) > 0:
            log.info('Unable to delete {n} inactive runs in virtualization realm: {v}'.format(
                n=str(len(not_deleted_runs)), v=str(vr_id)))
        return deleted_runs, not_deleted_runs

    def release_active_runs_in_virtualization_realm(self, vr_id, unlock=False):
        """Releases all active runs in a virtualization realm

        :param vr_id: (int) virtualization realm ID
        :param unlock (bool) Set True to unset the run lock before releasing
        :return: (tuple) list of released runs, and not released runs
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

        # List of desired deployment run status for completed/cancelled runs
        desired_status_list = ['CANCELED', 'COMPLETED']

        # Store the released and not released runs
        released_runs = []
        not_released_runs = []
        released_runs_threads = []

        # List active runs in the virtualization realm
        try:
            initial_active_drs = self.list_deployment_runs_in_virtualization_realm(
                vr_id=vr_id, search_type='SEARCH_ACTIVE')
        except Cons3rtApiError as exc:
            msg = 'Cons3rtApiError: There was a problem listing active deployment runs in VR ID: {i}'.format(
                i=str(vr_id))
            raise Cons3rtApiError(msg) from exc

        # Release or cancel each active run
        log.debug('Found active runs in VR ID {i}:\n{r}'.format(i=str(vr_id), r=str(initial_active_drs)))
        log.info('Attempting to release or cancel active runs from VR ID: {i}'.format(i=str(vr_id)))
        for dr in initial_active_drs:
            if 'id' not in dr.keys():
                log.warning('Unable to determine the run ID: {r}'.format(r=str(dr)))
                not_released_runs.append(dr)
                continue
            if 'name' not in dr.keys():
                log.warning('Unable to determine the run name: {r}'.format(r=str(dr)))
                not_released_runs.append(dr)
                continue

            # Track if the run release should be attempted
            do_release = True

            # Track if the run is remote access
            is_remote_access = False

            # Determine if the run is locked, or assumed to be locked
            if 'locked' not in dr.keys():
                log.warning('Could not determine the locked status of run ID [{i}], assuming locked'.format(
                    i=dr['id']))
                dr_locked = True
            else:
                log.info('Found locked status of run {d}: {s}'.format(d=str(dr['id']), s=str(dr['locked'])))
                dr_locked = dr['locked']

            # Check if this is a remote access run, and skip releasing it
            if '-RemoteAccess' in dr['name']:
                log.info('Run ID [{r}] is the remote access run for virtualization realm: {v}'.format(
                    r=str(dr['id']), v=str(vr_id)))
                is_remote_access = True

            # Unlock the run if specified, and if it is locked, but not if it is remote access
            if unlock and dr_locked and not is_remote_access:
                try:
                    self.set_deployment_run_lock(dr_id=dr['id'], lock=False)
                except Cons3rtApiError as exc:
                    log.warning('Problem removing run lock on run ID: {i}\n{e}'.format(i=str(dr['id']), e=str(exc)))
                    do_release = False
                    not_released_runs.append(dr)
                else:
                    log.info('Removed run lock for run ID: {i}'.format(i=str(dr['id'])))
            elif dr_locked:
                log.info('Run [{r}] is locked, and unlock was not specified, this run will not be released from '
                         'virtualization run ID: {v}'.format(r=str(dr['id']), v=vr_id))
                not_released_runs.append(dr)
                do_release = False
            elif is_remote_access:
                log.info('Remote access run for virtualization realm {v} will not be released: {r}'.format(
                    v=str(vr_id), r=str(dr['id'])))
                not_released_runs.append(dr)
                do_release = False

            # Attempt to release the deployment run
            if do_release:
                try:
                    self.release_deployment_run(dr_id=dr['id'])
                except Cons3rtApiError as exc:
                    log.warning('Unable to release or cancel run ID: {i}\n{e}'.format(i=str(dr['id']), e=str(exc)))
                    not_released_runs.append(dr)
                    continue
                else:
                    log.info('Released run [{d}] from virtualization realm [{v}]'.format(d=str(dr['id']), v=str(vr_id)))
                    released_runs.append(dr)
                    run_waiter = RunWaiter(
                        cons3rt_api=self,
                        dr_id=dr['id'],
                        desired_status_list=desired_status_list,
                        max_wait_time_sec=43200,
                        check_interval_sec=60
                    )
                    log.info('Starting a thread to wait for DR to release: {d}'.format(d=str(dr['id'])))
                    run_waiter.start()
                    released_runs_threads.append(run_waiter)
        log.info('Completed releasing or cancelling active DRs in VR ID: {i}'.format(i=str(vr_id)))

        # Wait until all deployment threads are completed
        log.info('Waiting until all {n} released DRs have completed releasing'.format(
            n=str(len(released_runs_threads))))
        time.sleep(1)
        for t in released_runs_threads:
            t.join()
        log.info('All {n} runs have completed releasing, checking for failures...'.format(
            n=str(len(released_runs_threads))))

        # Check the threads for failures, and build a list of error messages
        error_messages = []
        for t in released_runs_threads:
            if t.error:
                error_messages.append(
                    'Releasing DR [{d}] failed with message: {m}'.format(d=str(t.dr_id), m=t.error_msg)
                )
        if len(error_messages) > 0:
            msg = '{n} DRs failed to release with messages: {m}'.format(
                n=str(len(error_messages)), m='\n'.join(error_messages))
            raise Cons3rtApiError(msg)
        log.info('No failures detected releasing {n} DRs'.format(n=str(len(released_runs_threads))))

        # Print the final status
        processed_runs = len(released_runs) + len(not_released_runs)
        if len(initial_active_drs) != processed_runs:
            log.warning('The total runs [{t}] in virtualization realm {v} did not equal the number of runs processed'
                        'for release: {p}'.format(t=str(len(initial_active_drs)), v=str(vr_id), p=str(processed_runs)))
        return released_runs, not_released_runs

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

        # Release active runs until none are left
        attempt_num = 1
        max_attempts = 10
        interval_sec = 30
        while True:
            if attempt_num > max_attempts:
                msg = 'Maximum number of attempts {n} exceeded for releasing active runs from VR ID: {i}'.format(
                    i=str(vr_id), n=str(max_attempts))
                raise Cons3rtApiError(msg)
            log.info('Attempting to release active runs from VR ID {i}, attempt #{n} of {m}'.format(
                i=str(vr_id), n=str(attempt_num), m=str(max_attempts)))
            try:
                released_runs, not_released_runs = self.release_active_runs_in_virtualization_realm(
                    vr_id=vr_id, unlock=unlock)
            except Cons3rtApiError as exc:
                msg = 'Problem releasing active runs in VR: {v}'.format(v=str(vr_id))
                raise Cons3rtApiError(msg) from exc
            log.info('Released {n} runs from VR ID: {v}'.format(n=str(len(released_runs)), v=str(vr_id)))
            if (len(released_runs) + len(not_released_runs)) == 0:
                log.info('Completed releasing active runs from VR ID: {i}'.format(i=str(vr_id)))
                break
            attempt_num += 1
            log.info('Waiting {n} seconds to re-attempt releasing active runs...'.format(n=str(interval_sec)))
            time.sleep(interval_sec)

        # Delete inactive runs until none are left (as runs release)
        attempt_num = 1
        max_attempts = 40
        interval_sec = 15
        while True:
            if attempt_num > max_attempts:
                msg = 'Maximum number of attempts {n} exceeded for deleting inactive runs from VR ID: {i}'.format(
                    i=str(vr_id), n=str(max_attempts))
                raise Cons3rtApiError(msg)
            log.info('Attempting to delete inactive runs from VR ID {i}, attempt #{n} of {m}'.format(
                i=str(vr_id), n=str(attempt_num), m=str(max_attempts)))
            deleted_runs, not_deleted_runs = self.delete_inactive_runs_in_virtualization_realm(vr_id=vr_id)
            log.info('Deleted {n} runs from VR ID: {v}'.format(n=str(len(deleted_runs)), v=str(vr_id)))
            if len(not_deleted_runs) == 0:
                log.info('Completed deleting all inactive runs from VR ID: {i}'.format(i=str(vr_id)))
                break
            attempt_num += 1
            log.info('Waiting {n} seconds to re-attempt inactive run deletion...'.format(n=str(interval_sec)))
            time.sleep(interval_sec)
        log.info('Completed cleaning runs from VR ID: {i}'.format(i=str(vr_id)))

    def set_virtualization_realm_state(self, vr_id, state, force=False):
        """Sets the virtualization realm ID to the provided state

        :param vr_id: (int) virtualization realm ID
        :param state: (bool) Set True to activate, False to deactivate
        :param force: (bool) Set True to force set the VR state
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
            result = self.cons3rt_client.set_virtualization_realm_state(vr_id=vr_id, state=state, force=force)
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
        self.disable_vr_services(vr_id=vr_id)
        self.remove_all_projects_in_virtualization_realm(vr_id=vr_id)
        log.info('Waiting 10 seconds to proceed to removing runs...')
        time.sleep(10)
        self.clean_all_runs_in_virtualization_realm(vr_id=vr_id, unlock=True)
        log.info('Waiting 10 seconds to proceed to deactivation of the VR...')
        time.sleep(10)
        state_result = self.set_virtualization_realm_state(vr_id=vr_id, state=False, force=True)
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

    def list_users_in_virtualization_realm(self, vr_id):
        """Return a list of unique users that belong to projects that have access to the provided VR ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (list) of unique users
        :raises: Cons3rtApiError
        """
        vr_users = []
        project_members = []
        vr_projects = self.list_projects_in_virtualization_realm(vr_id=vr_id)

        # Get the active members from each project
        for vr_project in vr_projects:
            try:
                project_members += self.list_project_members(project_id=vr_project['id'], state='ACTIVE')
            except Cons3rtApiError as exc:
                msg = 'Problem listing members for project ID: {i}'.format(i=str(vr_project['id']))
                raise Cons3rtApiError(msg) from exc

        # Get the members from each project, and add only unique ones to the list
        for member in project_members:
            found_member_in_list = False
            for vr_user in vr_users:
                if vr_user['id'] == member['id']:
                    found_member_in_list = True
            if not found_member_in_list:
                vr_users.append(member)
        print('Cloudspace ID [{i}] has [{n}] active users'.format(i=str(vr_id), n=str(len(vr_users))))
        return vr_users

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
        :param template_name: (str) actual name of the template in the virtualization realm
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
        :raises: Cons3rtApiError
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

    def get_virtualization_realm_details_multiple(self, vr_ids):
        """Queries for details of a list of virtualization realms by ID

        :param vr_ids: (list) of int VR IDs
        :return: (list) of virtualization realm details
        :raises: Cons3rtApiError
        """
        virtualization_realm_details = []
        for vr_id in vr_ids:
            virtualization_realm_details.append(self.get_virtualization_realm_details(vr_id=vr_id))
        return virtualization_realm_details

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

    def retrieve_software_assets(self, software_asset_type=None, community=False, expanded=False, category_ids=None,
                                 max_results=None):
        """Get a list of software assets

        :param software_asset_type: (str) the software asset type, defaults to null
        :param community: (bool) the boolean to include community assets
        :param expanded: (bool) the boolean to include project assets
        :param category_ids: (list) the list of categories to filter by
        :param max_results: (int) maximum number of software assets to return
        :return: List of software asset IDs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_software_assets')

        # Validate the software asset type arg if provided
        if software_asset_type:
            if not isinstance(software_asset_type, str):
                raise Cons3rtApiError('software_asset_type must be a string')
            if software_asset_type not in cons3rt_software_asset_types:
                raise Cons3rtApiError('Found software_asset_type [{t}], must be one of [{n}]'.format(
                    t=software_asset_type, n=','.join(cons3rt_software_asset_types)))

        log.info('Attempting to query CONS3RT to retrieve software assets...')
        try:
            software_assets = self.cons3rt_client.retrieve_all_software_assets(
                software_asset_type=software_asset_type,
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

    def retrieve_expanded_software_assets(self, software_asset_type=None, community=False, category_ids=None,
                                          max_results=None):
        """Get a list of software assets with expanded info

        :param software_asset_type: (str) the software asset type, defaults to null
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
                software_asset_type=software_asset_type,
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

    def retrieve_all_expanded_software_assets(self, software_asset_type=None, community=False, category_ids=None):
        """Leaving this for backwards compatibility
        """
        return self.retrieve_expanded_software_assets(software_asset_type=software_asset_type, community=community,
                                                      category_ids=category_ids)

    def retrieve_test_asset(self, asset_id):
        """Retrieves details for the software asset

        :param asset_id: (int) asset ID
        return: (dict) details about the software asset
        :return:
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_test_asset')
        log.info('Retrieving test asset ID: {i}'.format(i=str(asset_id)))
        try:
            test_asset = self.cons3rt_client.retrieve_test_asset(asset_id=asset_id)
        except Cons3rtClientError as exc:
            msg = 'Problem retrieving test asset ID: {i}'.format(i=str(asset_id))
            raise Cons3rtApiError(msg) from exc
        return test_asset

    def retrieve_test_assets(self, test_asset_type=None, community=False, expanded=False, category_ids=None,
                             max_results=None):
        """Get a list of test assets

        :param test_asset_type: (str) the test asset type
        :param community: (bool) the boolean to include community assets
        :param expanded: (bool) the boolean to include project assets
        :param category_ids: (list) the list of categories to filter by
        :param max_results: (int) maximum number of test assets to return
        :return: List of test asset IDs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.retrieve_test_assets')

        # Validate the test asset type arg if provided
        if test_asset_type:
            if not isinstance(test_asset_type, str):
                raise Cons3rtApiError('test_asset_type must be a string')
            if test_asset_type not in cons3rt_test_asset_types:
                raise Cons3rtApiError('Found test_asset_type [{t}], must be one of [{n}]'.format(
                    t=test_asset_type, n=','.join(cons3rt_test_asset_types)))

        log.info('Attempting to query CONS3RT to retrieve test assets...')
        try:
            test_assets = self.cons3rt_client.retrieve_all_test_assets(
                test_asset_type=test_asset_type,
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

    def retrieve_expanded_test_assets(self, test_asset_type=None, community=False, category_ids=None, max_results=None):
        """Get a list of test assets with expanded info

        :param test_asset_type: (str) the test asset type, defaults to null
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
                test_asset_type=test_asset_type,
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

    def retrieve_all_expanded_test_assets(self, test_asset_type=None, community=False, category_ids=None):
        """Leaving this for backwards compatibility
        """
        return self.retrieve_expanded_test_assets(test_asset_type=test_asset_type, community=community,
                                                  category_ids=category_ids)

    def retrieve_container_assets(self, community=False, expanded=False, category_ids=None, max_results=None):
        """Get a list of container assets

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

    def retrieve_expanded_container_assets(self, community=False, category_ids=None, max_results=None):
        """Get a list of container assets with expanded info

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
        :param cpu: (int) number of CPUs if the action is resize
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
            msg = 'Problem performing action [{a}] on DR ID {r} host ID {h}\n{e}'.format(
                a=action, r=str(dr_id), h=str(dr_host_id), e=str(exc))
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

    def perform_host_action_for_run(self, dr_id, action, unlock=False, cpu=None, ram=None,
                                    inter_host_action_delay_sec=None):
        """Performs the provided host action on the dr_id

        :param dr_id: (int) ID of the deployment run
        :param action: (str) host action to perform
        :param unlock: (bool) set true to unlock the run before performing host action
        :param cpu: (int) number of CPUs if the action is resize
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

        # Unlock the run if specified
        if unlock:
            try:
                self.set_deployment_run_lock(dr_id=dr_id, lock=False)
            except Cons3rtApiError as exc:
                raise Cons3rtApiError('Problem unlocking run: {i}'.format(i=str(dr_id))) from exc

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
                log.warning(str(exc))
                error_detail = str(exc).split('\n')[-1]
                host_action_result.set_err_msg(err_msg=error_detail)
                host_action_result.set_fail()
            else:
                host_action_result.set_success()
            results.append(host_action_result)
            log.info('Waiting {s} sec to perform the next host action for run ID {i}...'.format(
                s=str(inter_host_action_delay_sec), i=str(dr_id)))
            time.sleep(inter_host_action_delay_sec)
        log.info('Completed host action [{a}] on hosts in run ID: {i}'.format(a=action, i=str(dr_id)))
        return results

    def perform_host_action_for_run_list_with_delay(self, drs, action, unlock=False, inter_run_action_delay_sec=5):
        """Attempts to perform the provided action for all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data
        :param action: (str) host action to perform
        :param unlock: (bool) ser true to unlock the runs before performing host action
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
                results = self.perform_host_action_for_run(dr_id=dr['id'], action=action, unlock=unlock)
            except Cons3rtApiError as exc:
                raise Cons3rtApiError('Problem performing action {a} for run ID: {i}'.format(
                    a=action, i=str(dr['id']))) from exc
            else:
                all_results += results
            log.info('Waiting {t} seconds to move on to the next DR...'.format(t=str(inter_run_action_delay_sec)))
            time.sleep(inter_run_action_delay_sec)
        return all_results

    def create_run_snapshots(self, dr_id):
        """Attempts to create snapshots for all hosts in the provided DR ID

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

    def create_snapshots_for_team(self, team_id, skip_run_ids):
        """Creates snapshots for a team

        :param team_id: (int) team ID
        :param skip_run_ids: (list) of deployment run IDs to skip
        :return: (list) of HostActionResults
        """
        return self.snapshot_team_runs(team_id=team_id, action='CREATE_SNAPSHOT', skip_run_ids=skip_run_ids)

    def create_snapshots_for_project(self, project_id, skip_run_ids):
        """Creates snapshots for a project

        :param project_id: (int) project ID
        :param skip_run_ids: (list) of deployment run IDs to skip
        :return: (list) of HostActionResults
        """
        return self.snapshot_project_runs(project_id=project_id, action='CREATE_SNAPSHOT', skip_run_ids=skip_run_ids)

    def restore_run_snapshots(self, dr_id, unlock=False):
        """Attempts to restore snapshots for all hosts in the provided DR ID

        :param dr_id: (int) ID of the deployment run
        :param unlock: (bool) set true to unlock before restoring snapshots
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        try:
            results = self.perform_host_action_for_run(
                dr_id=dr_id,
                action='RESTORE_SNAPSHOT',
                unlock=unlock
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem restoring snapshot for run ID: {i}'.format(i=str(dr_id))) from exc
        return results

    def restore_snapshots_for_team(self, team_id, skip_run_ids, unlock=False):
        """Restores snapshots for a team

        :param team_id: (int) team ID
        :param skip_run_ids: (list) of deployment run IDs to skip
        :return: (list) of HostActionResults
        """
        return self.snapshot_team_runs(team_id=team_id, action='RESTORE_SNAPSHOT', skip_run_ids=skip_run_ids,
                                       unlock=unlock)

    def restore_snapshots_for_project(self, project_id, skip_run_ids):
        """Restores snapshots for a project

        :param project_id: (int) project ID
        :param skip_run_ids: (list) of deployment run IDs to skip
        :return: (list) of HostActionResults
        """
        return self.snapshot_project_runs(project_id=project_id, action='RESTORE_SNAPSHOT', skip_run_ids=skip_run_ids)

    def delete_run_snapshots(self, dr_id, unlock=False):
        """Attempts to delete snapshots for all hosts in the provided DR ID

        :param dr_id: (int) ID of the deployment run
        :param unlock: (bool) set true to unlock the run before deleting snapshots
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        try:
            results = self.perform_host_action_for_run(
                dr_id=dr_id,
                action='REMOVE_ALL_SNAPSHOTS',
                unlock=unlock
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem restoring snapshot for run ID: {i}'.format(i=str(dr_id))) from exc
        return results

    def delete_snapshots_for_team(self, team_id, skip_run_ids):
        """Deletes snapshots for a team

        :param team_id: (int) team ID
        :param skip_run_ids: (list) of deployment run IDs to skip
        :return: (list) of HostActionResults
        """
        return self.snapshot_team_runs(team_id=team_id, action='REMOVE_ALL_SNAPSHOTS', skip_run_ids=skip_run_ids)

    def delete_snapshots_for_project(self, project_id, skip_run_ids):
        """Restores snapshots for a project

        :param project_id: (int) project ID
        :param skip_run_ids: (list) of deployment run IDs to skip
        :return: (list) of HostActionResults
        """
        return self.snapshot_project_runs(project_id=project_id, action='REMOVE_ALL_SNAPSHOTS',
                                          skip_run_ids=skip_run_ids)

    def power_off_run(self, dr_id, unlock=False):
        """Attempts to power off all hosts in the provided DR ID

        :param dr_id: (int) ID of the deployment run
        :param unlock: (bool) set true to unlock the run before power off
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        try:
            results = self.perform_host_action_for_run(
                dr_id=dr_id,
                action='POWER_OFF',
                unlock=unlock
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem performing power off for run ID: {i}'.format(i=str(dr_id))) from exc
        return results

    def power_on_run(self, dr_id, unlock=False):
        """Attempts to power on all hosts in the provided DR ID

        :param dr_id: (int) ID of the deployment run
        :param unlock: (bool) set true to unlock the run before power on
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        try:
            results = self.perform_host_action_for_run(
                dr_id=dr_id,
                action='POWER_ON',
                unlock=unlock
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem performing power on for run ID: {i}'.format(i=str(dr_id))) from exc
        return results

    def restore_run_snapshots_multiple(self, drs):
        return self.process_run_snapshots_multiple(drs=drs, action='RESTORE_SNAPSHOT')

    def create_run_snapshots_multiple(self, drs):
        return self.process_run_snapshots_multiple(drs=drs, action='CREATE_SNAPSHOT')

    def delete_run_snapshots_multiple(self, drs):
        return self.process_run_snapshots_multiple(drs=drs, action='REMOVE_ALL_SNAPSHOTS')

    def process_run_snapshots_multiple(self, drs, action, unlock=False):
        """Attempts to create snapshots for all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data
        :param action: (str) CREATE_SNAPSHOT | RESTORE_SNAPSHOT | REMOVE_ALL_SNAPSHOTS
        :param unlock: (bool) set true to unlock the runs before processing snapshots
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_run_snapshots_multiple')
        try:
            all_results = self.perform_host_action_for_run_list(
                drs=drs,
                action=action,
                unlock=unlock
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

    def restart_multiple_runs(self, drs, unlock=False):
        """Attempts to restart all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data
        :param unlock: (bool) set true to unlock runs before restart
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.restart_multiple_runs')
        log.info('Restarting multiple runs...')
        try:
            all_results = self.perform_host_action_for_run_list(
                drs=drs,
                action='REBOOT',
                unlock=unlock
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem restarting runs from list: {r}'.format(
                r=str(drs))) from exc
        return all_results

    def power_off_multiple_runs(self, drs, unlock=False):
        """Attempts to power off all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data
        :param unlock: (bool) set true to unlock runs before power off
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.power_off_multiple_runs')
        log.info('Powering off multiple runs...')
        try:
            all_results = self.perform_host_action_for_run_list(
                drs=drs,
                action='POWER_OFF',
                unlock=unlock
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem powering off runs from list: {r}'.format(
                r=str(drs))) from exc
        return all_results

    def power_on_multiple_runs(self, drs, unlock=False):
        """Attempts to power on all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data
        :param unlock: (bool) set true to unlock the runs before power on
        :return: (list) of dict data on request results
        :raises Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.power_on_multiple_runs')
        log.info('Powering off multiple runs...')
        try:
            all_results = self.perform_host_action_for_run_list(
                drs=drs,
                action='POWER_ON',
                unlock=unlock
            )
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem powering on runs from list: {r}'.format(
                r=str(drs))) from exc
        return all_results

    def perform_host_action_for_run_list(self, drs, action, unlock=False):
        """Attempts to perform the provided action for all hosts in the provided DR list

        :param drs: (list) deployment runs dicts of DR data containing at least:
            {
                'id',
                'deploymentRunStatus',
                'project',
                'name'
            }
        :param action: (str) host action to perform
        :param unlock: (bool) Set True to unlock the run before performing the host action
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
            if 'id' not in dr.keys():
                raise Cons3rtApiError('id not found in DR data: {d}'.format(d=str(dr)))
            if 'deploymentRunStatus' not in dr:
                raise Cons3rtApiError('deploymentRunStatus not found in DR data: {d}'.format(d=str(dr)))
            if 'project' not in dr.keys():
                raise Cons3rtApiError('project not found in DR data: {d}'.format(d=str(dr)))
            if 'name' not in dr['project']:
                raise Cons3rtApiError('project name not found in DR data: {d}'.format(d=str(dr)))

        # Get the run ID if available
        my_run_id = self.get_my_run_id()

        # Filter runs to take actions on by status and remove this run ID
        action_approved_statuses = ['RESERVED', 'TESTED']
        action_drs = []
        for dr in drs:
            if my_run_id == dr['id']:
                log.info('Not including MY OWN run ID on the action DR list: {i}'.format(i=str(my_run_id)))
                continue
            if dr['deploymentRunStatus'] not in action_approved_statuses:
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
                    elif dr['virtualizationRealm']['virtualizationRealmType'] == 'VCloudRestCloud':
                        vcloud_drs.append(dr)
                    elif dr['virtualizationRealm']['virtualizationRealmType'] == 'VCloudRest':
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
                    inter_run_action_delay_sec=self.get_inter_host_action_delay_for_cloud_type(cloud_type='Amazon'),
                    unlock=unlock
                )
            except Cons3rtApiError as exc:
                raise Cons3rtApiError('Problem performing host action [{a}] for Amazon runs'.format(a=action)) from exc

        if len(azure_drs) > 0:
            log.info('Performing host actions {a} on Azure runs...'.format(a=action))
            try:
                all_results += self.perform_host_action_for_run_list_with_delay(
                    drs=action_drs,
                    action=action,
                    inter_run_action_delay_sec=self.get_inter_host_action_delay_for_cloud_type(cloud_type='Azure'),
                    unlock=unlock
                )
            except Cons3rtApiError as exc:
                raise Cons3rtApiError('Problem performing host action [{a}] for Azure runs'.format(a=action)) from exc

        if len(openstack_drs) > 0:
            log.info('Performing host actions {a} on Openstack runs...'.format(a=action))
            try:
                all_results += self.perform_host_action_for_run_list_with_delay(
                    drs=action_drs,
                    action=action,
                    inter_run_action_delay_sec=self.get_inter_host_action_delay_for_cloud_type(cloud_type='Openstack'),
                    unlock=unlock
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
                    inter_run_action_delay_sec=self.get_inter_host_action_delay_for_cloud_type(cloud_type='VCloud'),
                    unlock=unlock
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
                    inter_run_action_delay_sec=self.get_inter_host_action_delay_for_cloud_type(cloud_type='other'),
                    unlock=unlock
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

    def snapshot_project_runs(self, project_id, action, skip_run_ids=None):
        """Creates a snapshot for each active deployment run in the provided team ID

        :param project_id: (int) project ID
        :param action: (str) CREATE_SNAPSHOT | RESTORE_SNAPSHOT | REMOVE_ALL_SNAPSHOTS
        :param skip_run_ids: (list) of int run IDs to skip snapshots
        :return: (list) of HostActionResults
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.snapshot_project_runs')

        # Keep a list of deployment runs that had snapshots created
        snapshot_drs = []

        # Ensure this is a list
        if not skip_run_ids:
            skip_run_ids = []

        # Get a list of team DRs
        log.info('Retrieving a list of runs owned by project ID: {i}'.format(i=str(project_id)))
        try:
            project_drs = self.list_active_runs_in_project(project_id=project_id)
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem retrieving active DRs from project: {i}'.format(i=str(project_id))) from exc
        log.info('Found {n} DRs in project ID: {i}'.format(n=str(len(project_drs)), i=str(project_id)))

        # Filter out the skip DRs to get a list to snapshot
        my_run_id = self.get_my_run_id()
        if my_run_id:
            log.info('Found my run ID, adding to skip list: {i}'.format(i=str(my_run_id)))
            skip_run_ids.append(my_run_id)
        else:
            log.info('My run ID not found, not adding to skip list')

        # Loop through the list of team DRs and
        for project_dr in project_drs:
            if 'id' not in project_dr.keys():
                log.warning('id not found in DR data: {d}'.format(d=str(project_dr)))
                continue
            if project_dr['id'] in skip_run_ids:
                log.info('Skipping run: {i}'.format(i=str(project_dr['id'])))
                continue
            snapshot_drs.append(project_dr)

        log.info('Processing snapshots for [{n}] out of [{t}] deployment runs in project ID {i}'.format(
            n=str(len(snapshot_drs)), t=str(len(project_drs)), i=str(project_id)))
        results, start_time, end_time, skip_run_ids = self.snapshots_for_team_or_project(
            action=action, snapshot_drs=snapshot_drs, skip_run_ids=skip_run_ids)
        elapsed_time = end_time - start_time

        log.info('Completed processing snapshots for project ID {i} at: {t}, total time elapsed: {e}'.format(
            i=str(project_id), t=end_time, e=str(elapsed_time)))
        log.info('Returning a list of {n} snapshot results'.format(n=str(len(results))))
        return results

    def snapshot_team_runs(self, team_id, action, unlock=False, skip_run_ids=None):
        """Creates a snapshot for each active deployment run in the provided team ID

        :param team_id: (int) team ID
        :param action: (str) CREATE_SNAPSHOT | RESTORE_SNAPSHOT | REMOVE_ALL_SNAPSHOTS
        :param unlock: (bool) set true to unlock the runs before snapshot action
        :param skip_run_ids: (list) of int run IDs to skip snapshots
        :return: (list) of HostActionResults
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.snapshot_team_runs')

        # Keep a list of deployment runs that had snapshots created
        snapshot_drs = []

        # Ensure this is a list
        if not skip_run_ids:
            skip_run_ids = []

        # Get a list of team DRs
        log.info('Retrieving a list of runs owned by projects in Team ID: {i}'.format(i=str(team_id)))
        try:
            team_drs = self.list_active_runs_in_team_owned_projects(team_id=team_id)
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem retrieving active DRs from team: {i}'.format(i=str(team_id))) from exc
        log.info('Found {n} DRs in team ID: {i}'.format(n=str(len(team_drs)), i=str(team_id)))

        # Loop through the list of team DRs and
        for team_dr in team_drs:
            if 'id' not in team_dr.keys():
                log.warning('id not found in DR data: {d}'.format(d=str(team_dr)))
                continue
            if team_dr['id'] in skip_run_ids:
                log.info('Skipping run: {i}'.format(i=str(team_dr['id'])))
                continue
            snapshot_drs.append(team_dr)

        log.info('Processing snapshots for [{n}] out of [{t}] deployment runs in team ID {i}'.format(
            n=str(len(snapshot_drs)), t=str(len(team_drs)), i=str(team_id)))
        results, start_time, end_time, skip_run_ids = self.snapshots_for_team_or_project(
            action=action, snapshot_drs=snapshot_drs, skip_run_ids=skip_run_ids, unlock=unlock)
        elapsed_time = end_time - start_time

        log.info('Completed processing snapshots for team ID {i} at: {t}, total time elapsed: {e}'.format(
            i=str(team_id), t=end_time, e=str(elapsed_time)))
        log.info('Returning a list of {n} snapshot results'.format(n=str(len(results))))
        return results

    def snapshots_for_team_or_project(self, action, snapshot_drs, skip_run_ids, unlock=False):
        """Takes a snapshot action for each active deployment run in the provided team ID

        :param action: (str) CREATE_SNAPSHOT | RESTORE_SNAPSHOT | REMOVE_ALL_SNAPSHOTS
        :param snapshot_drs: (list) list of int deployment run IDs to snapshot
        :param skip_run_ids: (list) of int run IDs to skip snapshots
        :param unlock: (bool) set true to unlock the run before snapshot action
        :return: results, start_time, end_time, skip_run_ids
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.snapshots_for_team_or_project')

        # Ensure this is a list
        if not skip_run_ids:
            skip_run_ids = []

        # Filter out the skip DRs to get a list to snapshot
        my_run_id = self.get_my_run_id()
        if my_run_id:
            log.info('Found my run ID, adding to skip list: {i}'.format(i=str(my_run_id)))
            skip_run_ids.append(my_run_id)
        else:
            log.info('My run ID not found, not adding to skip list')

        # Check and exclude runs from the skip list
        if len(skip_run_ids) > 0:
            log.info('Skipping snapshot actions for {n} runs: {r}'.format(
                n=str(len(skip_run_ids)), r=','.join(map(str, skip_run_ids))))
            non_skipped_snapshot_drs = []
            for snapshot_dr in snapshot_drs:
                if snapshot_dr['id'] not in skip_run_ids:
                    non_skipped_snapshot_drs.append(snapshot_dr)
        else:
            log.info('No runs will be skipping in this snapshot action')
            non_skipped_snapshot_drs = snapshot_drs

        # Run the snapshots
        start_time = datetime.datetime.now()
        try:
            results = self.process_run_snapshots_multiple(drs=non_skipped_snapshot_drs, action=action, unlock=unlock)
        except Cons3rtApiError as exc:
            raise Cons3rtApiError('Problem creating snapshots for the team runs list') from exc

        # Log the end and elapsed times
        end_time = datetime.datetime.now()
        log.info('Returning a list of {n} snapshot results'.format(n=str(len(results))))
        return results, start_time, end_time, skip_run_ids

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
            _, projects = self.list_projects_in_team(team_id=team_id)
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
                msg = 'Problem listing active DRs from VR ID: {i}\n{e}'.format(i=str(vr['id']), e=str(exc))
                log.warning(msg)
            else:
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

    def list_host_details_in_dr_list(self, dr_list, load=False):
        """Lists details for every deployment run host deployed in the provided team ID

        :param dr_list: (list) list of DRs (see details for dict)
        :param load (bool) Set True to load local data if found
        :return: (tuple) of the following:
            1. (list) of deployment run details, and a list of host details
            [
                "run": {run details}
                "hosts": [{host details}]
            ]
            2. (int) count of the deployment run hosts
            3. (list) of failed DRs
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.list_host_details_in_dr_list')

        # Store the list of deployment run and host details
        drh_list = []

        # Store the count of deployment run hosts
        drh_count = 0

        # Store the list of failed deployment runs
        failed_dr_list = []

        # Attempt to load existing data from previous runs
        data_name = 'host_details'
        loaded_data = []

        if load:
            loaded_data = self.load_cons3rt_data(data_name)
            if not loaded_data:
                log.info('No data was loaded with host details')
                loaded_data = []
        else:
            log.info('Loaded {n} runs with host details'.format(n=str(len(loaded_data))))

        for dr in dr_list:
            if 'id' not in dr.keys():
                log.warning('id not found in DR data: {d}'.format(d=str(dr)))
                continue

            # Track whether data was already loaded for this run
            found_existing = False

            # Check for loaded host detail data for this run ID
            for loaded_run in loaded_data:
                if 'run' in loaded_run.keys():
                    if 'id' in loaded_run['run'].keys():
                        if loaded_run['run']['id'] == dr['id']:
                            if 'hosts' in loaded_run.keys():
                                log.info('Loading details for run ID: {i}'.format(i=str(dr['id'])))
                                found_existing = True
                                drh_count += len(loaded_run['hosts'])
                                drh_list.append(dict(loaded_run))

            # If not found, retrieve host details
            if not found_existing:
                log.info('Retrieving details for run ID: {i}'.format(i=str(dr['id'])))
                try:
                    dr_drh_list, dr_details = self.list_detailed_hosts_in_run(dr_id=dr['id'])
                except Cons3rtApiError as exc:
                    log.warning('Problem listing detailed host data for DR ID: {i}\n{e}'.format(
                        i=str(dr['id']), e=str(exc)))
                    failed_dr_list.append(dr)
                    continue

                new_host_details = {
                    'run': dr_details,
                    'hosts': dr_drh_list
                }
                drh_list.append(new_host_details)
                drh_count += len(dr_drh_list)
                loaded_data.append(new_host_details)
                self.save_cons3rt_data(cons3rt_data=loaded_data, data_name=data_name)
        return drh_list, drh_count, failed_dr_list

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

        # Get the list
        team_drh_list, team_drh_count, _ = self.list_host_details_in_dr_list(dr_list=drs)
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
            if 'id' not in dr.keys():
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

    def update_virtualization_realm_access_point(self, vr_id, access_point_ip):
        """Sets the access point IP address of a VR

        :param vr_id: (int) Virtualization Realm ID
        :param access_point_ip: (str) IP address to set as the access point
        :return: None
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.update_virtualization_realm_access_point')

        # Ensure the vr_id is an int
        if not isinstance(vr_id, int):
            try:
                vr_id = int(vr_id)
            except ValueError as exc:
                msg = 'vr_id arg must be an Integer, found: {t}'.format(t=vr_id.__class__.__name__)
                raise Cons3rtApiError(msg) from exc

        # Ensure the IP address is valid
        if not validate_ip_address(access_point_ip):
            msg = 'Invalid access point IP provided: [{i}]'.format(i=access_point_ip)
            raise Cons3rtApiError(msg)

        log.info('Setting the access point IP for VR [{v}] to: [{i}]'.format(v=str(vr_id), i=access_point_ip))
        try:
            self.cons3rt_client.update_virtualization_realm_access_point(vr_id=vr_id, access_point_ip=access_point_ip)
        except Cons3rtClientError as exc:
            msg = 'Problem updating access point to [{i}] for VR [{v}]'.format(i=access_point_ip, v=str(vr_id))
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
                              subscriber_vrs_subscriptions=None, max_cpus=32, max_ram_mb=131072):
        """Share a template to virtualization realms

        # TODO when Tracker 4459 is fixed, include max_cpus and max_ram_mb from reg_details['templateData']['maxCpu']

        :param provider_vr_id: (int) ID of the virtualization realm where the template is registered
        :param template: (dict) of template data
        :param vr_ids: (list) VR IDs to share the templates with
        :param subscribe: (bool) Set True to have the shared virtualization realm also subscribe to the template
        :param online: (bool) Set True to bring the template online in the subscriber virtualization realm
        :param subscriber_vrs_subscriptions: (list) of dict subscription data for each subscriber VR ID
        :param max_cpus: (int) maximum number of CPUs to include in the template subscription
        :param max_ram_mb: (int) maximum RAM in MB to include in the template subscription
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
            if subscriber_vr_existing_subs:
                for subscriber_vr_existing_sub in subscriber_vr_existing_subs:
                    if 'templateRegistration' not in subscriber_vr_existing_sub.keys():
                        continue
                    if (subscriber_vr_existing_sub['templateRegistration']['templateUuid'] ==
                            reg_details['templateUuid']):
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

    def share_templates_to_vrs(self, provider_vr_id, templates, vr_ids, subscribe=True, online=True, max_cpus=32,
                               max_ram_mb=131072):
        """Share a template to virtualization realms

        :param provider_vr_id: (int) ID of the virtualization realm where the template is registered
        :param templates: (list) of template data as dict
        :param vr_ids: (list) VR IDs to share the templates with
        :param subscribe: (bool) Set True to have the shared virtualization realm also subscribe to the template
        :param online: (bool) Set True to bring the template online in the subscriber virtualization realm
        :param max_cpus: (int) maximum number of CPUs to include in the template subscription
        :param max_ram_mb: (int) maximum RAM in MB to include in the template subscription
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
                    subscriber_vrs_subscriptions=subscriber_vrs_subscriptions,
                    max_cpus=max_cpus,
                    max_ram_mb=max_ram_mb
                )
            except Cons3rtApiError as exc:
                msg = 'Problem sharing template to VRs\n{e}\n{t}'.format(e=str(exc), t=traceback.format_exc())
                log.warning(msg)

    def share_templates_to_vrs_by_name(self, provider_vr_id, vr_ids, template_names=None, max_cpus=32,
                                       max_ram_mb=131072):
        """Shares template by name from the provider VR ID to the list of target VR IDs

        :param provider_vr_id: (int) ID of the template provider virtualization realm
        :param template_names: (list) name of the template names to share, None to share all templates
        :param vr_ids: (list) of IDs (int) of virtualization realms to share with
        :param max_cpus: (int) maximum number of CPUs to include in the template subscription
        :param max_ram_mb: (int) maximum RAM in MB to include in the template subscription
        131072
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
            vr_ids=vr_ids,
            max_cpus=max_cpus,
            max_ram_mb=max_ram_mb
        )

    def delete_virtualization_realms_for_cloud(self, cloud_id, unlock=False):
        """Unregisters and/or deallocates all virtualization realms for the provided cloud ID

        :param cloud_id: (str) cloud ID
        :param unlock: (bool) Set True to unlock all runs, otherwise this call could fail on a locked run
        :return: (tuple) list of deleted VRs, list of VRs not deleted
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.delete_virtualization_realms_for_cloud')

        # Store lists of deleted VRs and not deleted VRs
        not_deleted_vrs = []

        # Retrieve the list of virtualization realms
        try:
            cloud_vrs = self.list_virtualization_realms_for_cloud(cloud_id=cloud_id)
        except Cons3rtApiError as exc:
            msg = 'Problem list VRs from cloud ID {i} details'.format(i=str(cloud_id))
            raise Cons3rtApiError(msg) from exc
        log.info('Found {n} virtualization realms in cloud ID: {i}'.format(n=str(len(cloud_vrs)), i=cloud_id))
        if len(cloud_vrs) == 0:
            return [], []
        for cloud_vr in cloud_vrs:
            if 'id' not in cloud_vr.keys():
                log.warning('id not found in cloud VR data: {d}'.format(d=str(cloud_vr)))
                not_deleted_vrs.append(cloud_vr)
            cloud_vr_id = cloud_vr['id']
            self.clean_all_runs_in_virtualization_realm(vr_id=cloud_vr_id, unlock=unlock)

    def share_templates_to_vrs_in_cloud(self, cloud_id, provider_vr_id=None, templates_registration_data=None,
                                        template_names=None, subscribe=True, online=True, max_cpus=32,
                                        max_ram_mb=131072):
        """Shares a list of templates from a provider VR to all VRs in the provided cloud ID

        :param cloud_id: (int) ID of the cloud to share with
        :param provider_vr_id: (int) ID of the virtualization realm where the template is registered
        :param templates_registration_data: (list) of template objects (dict)
        :param template_names: (list) of template names (str)
        :param subscribe: (bool) Set True to have the shared virtualization realm also subscribe to the template
        :param online: (bool) Set True to bring the template online in the subscriber virtualization realm
        :param max_cpus: (int) maximum number of CPUs to include in the template subscription
        :param max_ram_mb: (int) maximum RAM in MB to include in the template subscription
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
            online=online,
            max_cpus=max_cpus,
            max_ram_mb=max_ram_mb
        )
        log.info('Completed sharing templates in cloud ID: {i}'.format(i=str(cloud_id)))

    def create_host_identity(self, dr_id, host_id, service_type, service_identifier, service_name=None):
        """Creates an identity on the provided DR host to the singular provided service

        :param dr_id: (int) deployment run ID
        :param host_id: (int) deployment run host ID
        :param service_type: (str) type of service "BUCKET"
        :param service_name: (str) name of the service
        :param service_identifier: (str) ID of the service to connect to.  For bucket names this is the bucket name
            with UUID for example "testbackups-a288d8c58ae74de"
        :return: (dict) Host identity with credentials
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_host_identity')

        # Ensure the dr_id is an int
        if not isinstance(dr_id, int):
            try:
                dr_id = int(dr_id)
            except ValueError as exc:
                msg = 'dr_id arg must be an Integer, found: {t}'.format(t=type(dr_id))
                raise Cons3rtApiError(msg) from exc

        # Ensure the host_id is an int
        if not isinstance(host_id, int):
            try:
                host_id = int(host_id)
            except ValueError as exc:
                msg = 'host_id arg must be an Integer, found: {t}'.format(t=type(host_id))
                raise Cons3rtApiError(msg) from exc

        # Build a re-usable message
        msg = 'identity for deployment run [{d}] host [{h}] in service type [{t}] with ID [{i}]'.format(
            d=str(dr_id), h=str(host_id), t=service_type, i=service_identifier)

        # Build service content
        service = {
            'type': service_type,
            'identifier': service_identifier
        }
        if service_name:
            service['name'] = service_name
            msg += ' and name: ' + service_name

        # Build the list of one item
        log.info('Creating ' + msg)
        try:
            identity = self.cons3rt_client.create_host_identity(dr_id=dr_id, host_id=host_id, service_list=[service])
        except Cons3rtClientError as exc:
            msg = 'Problem creating ' + msg
            raise Cons3rtApiError(msg) from exc

        # Ensure data was included
        if 'credentials' not in identity.keys():
            msg = 'credentials not found in identity data: {d}'.format(d=str(identity))
            raise Cons3rtApiError(msg)
        if 'context' not in identity.keys():
            msg = 'context not found in identity data: {d}'.format(d=str(identity))
            raise Cons3rtApiError(msg)
        if 'resources' not in identity.keys():
            msg = 'resources not found in identity data: {d}'.format(d=str(identity))
            raise Cons3rtApiError(msg)
        return identity

    def create_host_identity_aws_config(self, dr_id, host_id, service_type, service_identifier, service_name=None,
                                        aws_dir=None, aws_region='us-gov-west-1'):
        """Creates an AWS credentials and config file using a cons3rt-generated identity

        :param dr_id: (int) deployment run ID
        :param host_id: (int) deployment run host ID
        :param service_type: (str) type of service "BUCKET"
        :param service_name: (str) name of the service
        :param service_identifier: (str) ID of the service to connect to.  For bucket names this is the bucket name
            with UUID for example "testbackups-a288d8c58ae74de"
        :param aws_dir: (str) path to the AWS config directory
        :param aws_region: (str) AWS region (e.g. us-gov-west-1)
        :return: (dict) Host identity with credentials
        :raises: Cons3rtApiError
        """
        log = logging.getLogger(self.cls_logger + '.create_host_identity_aws_config')

        # First generate an identity
        try:
            identity = self.create_host_identity(dr_id=dr_id, host_id=host_id, service_type=service_type,
                                                 service_identifier=service_identifier, service_name=service_name)
        except Cons3rtApiError as exc:
            msg = 'Problem generating an identity, cannot create AWS config'
            raise Cons3rtApiError(msg) from exc

        # Check if aws_dir is set, if not attempt to determine the config and credentials file paths
        if aws_dir:
            aws_config_file = os.path.join(aws_dir, 'config')
            aws_credentials_file = os.path.join(aws_dir, 'credentials')
        else:
            # Check for the environment variable AWS_CONFIG_FILE
            if 'AWS_CONFIG_FILE' in os.environ.keys():
                aws_config_file = os.environ['AWS_CONFIG_FILE']
            else:
                aws_config_file = os.path.join(os.path.expanduser('~'), '.aws', 'config')

            # Check for the environment variable AWS_SHARED_CREDENTIALS_FILE
            if 'AWS_SHARED_CREDENTIALS_FILE' in os.environ.keys():
                aws_credentials_file = os.environ['AWS_SHARED_CREDENTIALS_FILE']
                aws_dir = os.environ['AWS_SHARED_CREDENTIALS_FILE'].split(os.sep)[:-1]
            else:
                aws_dir = os.path.join(os.path.expanduser('~'), '.aws')
                aws_credentials_file = os.path.join(aws_dir, 'credentials')

        # Get the access key, secret key, and session token from the identity
        if 'Access Key' not in identity['credentials'].keys():
            raise Cons3rtApiError('Access Key not found in identity credentials data')
        if 'Secret Access Key' not in identity['credentials'].keys():
            raise Cons3rtApiError('Secret Access Key not found in identity credentials data')
        if 'Session Token' not in identity['credentials'].keys():
            raise Cons3rtApiError('Session Token not found in identity credentials data')

        # Replace the content of the credential file
        aws_credentials_content = aws_credentials_file_content_template.replace(
            'REPLACE_ACCESS_KEY_ID', identity['credentials']['Access Key']).replace(
            'REPLACE_SECRET_ACCESS_KEY', identity['credentials']['Secret Access Key']).replace(
            'REPLACE_SESSION_TOKEN', identity['credentials']['Session Token'])

        # Replace the content of the config file
        aws_config_content = aws_config_file_content_template.replace(
            'REPLACE_REGION', aws_region)

        # Backup the current files if they exist
        timestamp_formatted = datetime.datetime.now().strftime("%Y-%M-%d_%H%m%S")
        if os.path.isfile(aws_credentials_file):
            backup_aws_creds_file = aws_credentials_file + '_' + timestamp_formatted
            log.info('Backing up existing credentials file to: {b}'.format(b=backup_aws_creds_file))
            os.rename(aws_credentials_file, backup_aws_creds_file)
        if os.path.isfile(aws_config_file):
            backup_aws_config_file = aws_config_file + '_' + timestamp_formatted
            log.info('Backing up existing config file to: {b}'.format(b=backup_aws_config_file))
            os.rename(aws_config_file, backup_aws_config_file)

        # Create the aws dir if it does not exist
        if not os.path.isdir(aws_dir):
            log.info('Creating aws credentials directory: {d}'.format(d=aws_dir))
            os.makedirs(aws_dir, exist_ok=True)

        # Write the config and credentials files
        log.info('Creating credentials file: {f}'.format(f=aws_credentials_file))
        with open(aws_credentials_file, 'w') as f:
            f.write(aws_credentials_content)

        log.info('Creating config file: {f}'.format(f=aws_config_file))
        with open(aws_config_file, 'w') as f:
            f.write(aws_config_content)
        return identity
