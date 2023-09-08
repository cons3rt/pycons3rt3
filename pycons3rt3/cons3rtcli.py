#!/usr/bin/env python

import datetime
import json
import traceback

from .cons3rtapi import Cons3rtApi
from .cons3rtdefaults import default_template_subscription_max_cpus
from .exceptions import Cons3rtApiError, Cons3rtReportsError
from .pycons3rtlibs import HostActionResult
from .reports import generate_team_report, generate_team_asset_report


class Cons3rtCliError(Exception):
    pass


class Cons3rtCli(object):

    def __init__(self, args, subcommands=None):
        self.subcommands = subcommands
        self.args = args
        self.config = None
        if args.config:
            self.config = args.config
        self.ids = None
        self.names = None
        self.runs = None
        self.csv = False
        if args.csv:
            self.csv = True
        try:
            self.c5t = Cons3rtApi(config_file=self.config)
        except Cons3rtApiError as exc:
            self.err('Missing or incomplete authentication information, run [cons3rt config] to fix\n{e}'.format(
                e=str(exc)))

    def dump_json_file(self, data):
        # Export the data to a JSON file
        if not self.args.json:
            return
        json_path = self.args.json

        # Create JSON content
        try:
            json.dump(data, open(json_path, 'w'), sort_keys=True, indent=2, separators=(',', ': '))
        except SyntaxError as exc:
            msg = 'Problem converting data to JSON: {d}'.format(d=str(data))
            raise Cons3rtCliError(msg) from exc
        except (OSError, IOError) as exc:
            msg = 'Problem creating JSON output file: {f}'.format(f=json_path)
            raise Cons3rtCliError(msg) from exc
        print('Created output JSON file: {f}'.format(f=json_path))

    def get_max_cpu(self):
        if self.args.cpu:
            try:
                max_cpus = int(self.args.cpu)
            except ValueError as exc:
                msg = 'Invalid --cpu arg provided, must be an int: {c}\n{e}'.format(c=str(self.args.cpu), e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
            else:
                return max_cpus
        else:
            return default_template_subscription_max_cpus

    def process_args(self):
        if not self.validate_args():
            return False
        if not self.process_subcommands():
            return False
        return True

    def process_subcommands(self):
        """
        This method must be overridden by the child class
        :return:
        """
        return True

    def validate_args(self):
        try:
            self.ids = validate_ids(self.args)
        except Cons3rtCliError:
            traceback.print_exc()
            return False
        self.names = validate_names(self.args)
        self.runs = validate_runs(self.args)
        return True

    def get_separator(self, num=1):
        if self.csv:
            return ','
        return '\t' * num

    @staticmethod
    def get_spaces(num=1):
        return ' ' * num

    @staticmethod
    def dict_id_comparator(element):
        if not isinstance(element, dict):
            return 0
        if 'id' in element:
            try:
                element_id = int(element['id'])
            except ValueError:
                return 0
            else:
                return element_id
        else:
            return 0

    @staticmethod
    def sort_by_id(unsorted_list):
        return sorted(unsorted_list, key=Cons3rtCli.dict_id_comparator)

    @staticmethod
    def err(msg):
        print('ERROR: {m}'.format(m=msg))
        traceback.print_exc()

    def print_formatted_list(self, item_list, included_columns=None):
        if len(item_list) < 1:
            return
        print('')
        if not included_columns:
            # Collect unique keys from all dictionaries to get column names
            included_columns = sorted({key for row in item_list for key in row})

        if self.csv:
            # Format and print the columns in csv format
            print(",".join(included_columns))
            for row in item_list:
                formatted_row = [str(row.get(key, "")) for key in included_columns]
                print(','.join(formatted_row))
        else:
            # Print table format
            # Calculate the maximum width for each column based on column names and values
            column_widths = {
                key: max(len(key), max(len(str(row.get(key, ""))) for row in item_list)) for key in included_columns
            }

            # Format and print the columns
            header_row = [f"{name:{column_widths[name]}}" for name in included_columns]
            print(" | ".join(header_row))
            print("-" * (sum(column_widths.values()) + (len(column_widths) - 1) * 3))
            for row in item_list:
                formatted_row = [f"{str(row.get(name, '')):{column_widths[name]}}" for name in included_columns]
                print(" | ".join(formatted_row))
        print('')

    def print_item_name_and_id(self, item_list):
        self.print_formatted_list(
            item_list=item_list,
            included_columns=['id', 'name']
        )

    def print_deployments(self, deployment_list):
        return self.print_item_name_and_id(deployment_list)

    def print_dr_hosts(self, dr_host_list):
        self.print_formatted_list(
            item_list=dr_host_list,
            included_columns=['id', 'hostname', 'fapStatus', 'numCpus', 'ram', 'hasGpu']
        )

    def print_drs(self, dr_list):

        # Build the roles_list item string and add it to the printable dict
        for dr in dr_list:
            creator_username = ''
            project_name = ''
            if 'creator' in dr:
                if 'username' in dr['creator']:
                    creator_username += dr['creator']['username']
            if 'project' in dr:
                if 'name' in dr['project']:
                    project_name += dr['project']['name']
            dr['creatorUsername'] = creator_username
            dr['projectName'] = project_name

        self.print_formatted_list(
            item_list=dr_list,
            included_columns=['id', 'name', 'fapStatus', 'projectName', 'creatorUsername']
        )

    def print_host_action_results(self, results):
        dict_results = []
        for result in results:
            dict_results.append(result.to_dict())
        self.print_formatted_list(
            item_list=dict_results,
            included_columns=['host_id', 'host_role', 'dr_id', 'action', 'num_disks', 'storage_gb', 'result', 'err_msg']
        )

    def print_projects(self, project_list):
        return self.print_item_name_and_id(project_list)

    def print_project_members(self, member_list):

        # Build the roles_list item string and add it to the printable dict
        for member in member_list:
            role_list_str = ''
            for role in member['roles']:
                role_list_str += role + ':'
            role_list_str = role_list_str.rstrip(':')
            member['projectRoles'] = role_list_str

        self.print_formatted_list(
            item_list=member_list,
            included_columns=['id', 'username', 'email', 'membershipState', 'projectRoles']
        )

    def print_clouds(self, cloud_list):
        self.print_formatted_list(
            item_list=cloud_list,
            included_columns=['id', 'name', 'cloudType']
        )

    def print_cloudspaces(self, cloudspaces_list):
        self.print_formatted_list(
            item_list=cloudspaces_list,
            included_columns=['id', 'name', 'virtualizationRealmType', 'state']
        )

    @staticmethod
    def print_host_action_results_list(host_action_results_list):
        msg = HostActionResult.get_host_action_result_header() + '\n'
        for host_action_result in host_action_results_list:
            msg += str(host_action_result) + '\n'
        print(msg)

    def print_scenarios(self, scenario_list):
        return self.print_item_name_and_id(scenario_list)

    def print_system_designs(self, system_design_list):
        return self.print_item_name_and_id(system_design_list)

    def print_teams(self, teams_list):
        self.print_formatted_list(
            item_list=teams_list,
            included_columns=['id', 'name', 'state', 'expirationDate']
        )

    def print_team_managers(self, team_manager_list):

        # Build the team IDs and team names list strings separated by :
        for team_manager in team_manager_list:
            team_ids_str = ''
            team_names_str = ''
            if 'teamIds' in team_manager.keys():
                team_ids_str += ':'.join(map(str, team_manager['teamIds']))
            if 'teamNames' in team_manager.keys():
                team_names_str += ':'.join(map(str, team_manager['teamNames']))
            team_ids_str = team_ids_str.rstrip(':')
            team_names_str = team_names_str.rstrip(':')
            team_manager['teamIdList'] = team_ids_str
            team_manager['teamNameList'] = team_names_str

        self.print_formatted_list(
            item_list=team_manager_list,
            included_columns=['id', 'username', 'email', 'teamIdList', 'teamNameList']
        )

    def print_templates(self, template_list):

        # Build the strings for template registration ID, template UUID, and offline
        for template in template_list:
            template_registration_id = ''
            template_uuid = ''
            template_offline = ''
            if 'templateRegistration' in template.keys():
                if 'id' in template['templateRegistration']:
                    template_registration_id += str(template['templateRegistration']['id'])
                if 'templateUuid' in template['templateRegistration']:
                    template_uuid += template['templateRegistration']['templateUuid']
                if 'offline' in template['templateRegistration']:
                    template_offline += str(template['templateRegistration']['offline'])
            template['templateRegistrationId'] = template_registration_id
            template['templateUuid'] = template_uuid
            template['templateOffline'] = template_offline

        self.print_formatted_list(
            item_list=template_list,
            included_columns=[
                'virtRealmId', 'virtRealmTemplateName', 'operatingSystem', 'id', 'templateRegistrationId',
                'templateUuid', 'templateOffline'
            ]
        )

    def print_users(self, users_list):
        self.print_formatted_list(
            item_list=users_list,
            included_columns=['id', 'username', 'email']
        )


class CloudCli(Cons3rtCli):

    def __init__(self, args, subcommands=None):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'create',
            'delete',
            'list',
            'retrieve',
            'run',
            'template'
        ]

    def process_subcommands(self):
        if not self.subcommands:
            return True
        if len(self.subcommands) < 1:
            return True
        if self.subcommands[0] not in self.valid_subcommands:
            self.err('Unrecognized command: {c}'.format(c=self.subcommands[0]))
            return False
        if self.subcommands[0] == 'create':
            try:
                self.create_cloud()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'delete':
            try:
                self.delete_clouds()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'list':
            try:
                self.list_clouds()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'retrieve':
            try:
                self.retrieve_clouds()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'run':
            try:
                self.deployment_runs()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'template':
            try:
                self.templates()
            except Cons3rtCliError:
                return False
        return True

    def create_cloud(self):

        if not self.args.cloud_ato_consent:
            msg = '--cloud_ato_consent arg is required for cloud creation, providing this arg implies consent'
            self.err(msg)
            raise Cons3rtCliError(msg)

        if self.args.json:
            return self.create_cloud_from_json()
        else:
            return self.create_cloud_from_args()

    def create_cloud_from_args(self):
        """Creates a cloud using the provided combination of CLI args

        TODO -- This is incomplete

        :return:
        """
        # Get the required args
        if not self.args.name:
            msg = '--name arg is required for cloud creation'
            self.err(msg)
            raise Cons3rtCliError(msg)

        if not self.args.cloud_type:
            msg = '--cloud_type arg is required for cloud creation (awsCloud, azureCloud, openStackCloud, ' \
                  'vCloudCloud, vCloudRestCloud)'
            self.err(msg)
            raise Cons3rtCliError(msg)

        # Get the optional args
        owning_team_id = None
        linux_repo_url = None
        # vcloud_username = None

        if self.args.owning_team_id:
            owning_team_id = self.args.owning_team_id
        if self.args.linux_repo_url:
            linux_repo_url = self.args.linux_repo_url

        try:
            self.c5t.create_cloud(
                cloud_ato_consent=True,
                name=self.args.name,
                owning_team_id=owning_team_id,
                allocation_capable=True,
                de_allocation_capable=True,
                linux_repo_url=linux_repo_url,
            )
        except Cons3rtApiError as exc:
            msg = 'Problem creating cloud\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc

    def create_cloud_from_json(self):
        """Creates a cloud using the json file specified with the --json CLI arg

        :return:
        """
        if not self.args.json:
            msg = '--json arg is required to create a cloud from JSON file'
            self.err(msg)
            raise Cons3rtCliError(msg)
        json_path = self.args.json

        try:
            self.c5t.register_cloud_from_json(json_file=json_path)
        except Cons3rtApiError as exc:
            msg = 'Problem creating cloud from JSON file: {f}\n{e}'.format(f=json_path, e=str(exc))
            self.err(msg)
            traceback.print_exc()
            raise Cons3rtCliError(msg) from exc

    def delete_clouds(self):
        if len(self.subcommands) == 1:
            self.delete_clouds_only()
        elif len(self.subcommands) > 1:
            delete_subcommand = self.subcommands[1]
            valid_delete_subcommands = [
                'cloudspaces'
            ]
            if delete_subcommand not in valid_delete_subcommands:
                self.err('Unrecognized cloud delete subcommand [{c}], options: {o}'.format(
                    c=delete_subcommand, o=','.join(valid_delete_subcommands)))
                return False
            if delete_subcommand == 'cloudspaces':
                self.delete_cloudspaces()

    def delete_clouds_only(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloud IDs to delete'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for cloud_id in self.ids:
            try:
                self.c5t.delete_cloud(cloud_id=cloud_id)
            except Cons3rtApiError as exc:
                msg = 'Problem deleting cloud ID: {c}\n{e}'.format(c=str(cloud_id), e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc

    def delete_cloudspaces(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloud IDs to delete'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for cloud_id in self.ids:
            try:
                deleted_cloudspaces, undeleted_cloudspaces = self.c5t.delete_virtualization_realms_for_cloud(
                    cloud_id=cloud_id)
            except Cons3rtApiError as exc:
                msg = 'Problem deleting VRs in cloud ID cloud ID: {c}\n{e}'.format(c=str(cloud_id), e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
            print('Deallocated/unregistered {n} cloudspaces for cloud {c}:'.format(
                n=str(len(deleted_cloudspaces)), c=str(cloud_id)))
            self.print_cloudspaces(cloudspaces_list=deleted_cloudspaces)
            if len(undeleted_cloudspaces) > 0:
                print('Unable to deallocate/unregister {n} cloudspaces for cloud {c}:'.format(
                    n=str(len(undeleted_cloudspaces)), c=str(cloud_id)))
                self.print_cloudspaces(cloudspaces_list=undeleted_cloudspaces)

    def deployment_runs(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloud IDs'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if len(self.subcommands) > 1:
            cloud_run_subcommand = self.subcommands[1]

            if cloud_run_subcommand == 'gpus':
                self.list_cloud_gpus()
                return
            elif cloud_run_subcommand == 'hosts':
                self.list_cloud_hosts()
                return
            elif cloud_run_subcommand == 'list':
                self.list_cloud_runs()
                return

    def list_cloud_gpus(self):

        # Set the load based on args
        load = False
        if self.args.load:
            load = True

        # Store host details that are using GPUs
        cloud_gpus = []

        for cloud_id in self.ids:
            try:
                cloud_gpus += self.c5t.list_cloud_gpu_hosts(cloud_id=cloud_id, load=load)
            except Cons3rtApiError as exc:
                msg = 'Problem retrieving GPUs in cloud ID: {c}\n{e}'.format(c=str(cloud_id), e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
        self.print_formatted_list(item_list=cloud_gpus)

    def list_cloud_runs(self):

        # If the --active flag was set, search_type=SEARCH_ACTIVE
        search_type = 'SEARCH_ALL'
        if self.args.active:
            search_type = 'SEARCH_ACTIVE'

        cloud_runs = []
        for cloud_id in self.ids:
            try:
                cloud_runs += self.c5t.list_deployment_runs_in_cloud(cloud_id=cloud_id, search_type=search_type)
            except Cons3rtApiError as exc:
                msg = 'Problem retrieving deployment runs for cloud ID: {c}\n{e}'.format(c=str(cloud_id), e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
        self.print_drs(dr_list=cloud_runs)

    def list_cloud_hosts(self):

        # Set the load based on args
        load = False
        if self.args.load:
            load = True

        # If the --active flag was set, search_type=SEARCH_ACTIVE
        search_type = 'SEARCH_ALL'
        if self.args.active:
            search_type = 'SEARCH_ACTIVE'

        cloud_run_hosts = []
        for cloud_id in self.ids:
            try:
                this_cloud_run_hosts, _, _ = self.c5t.list_deployment_run_hosts_in_cloud(
                    cloud_id=cloud_id, search_type=search_type, load=load)
            except Cons3rtApiError as exc:
                msg = 'Problem retrieving deployment run hosts for cloud ID: {c}\n{e}'.format(
                    c=str(cloud_id), e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
            cloud_run_hosts += this_cloud_run_hosts
        self.print_dr_hosts(dr_host_list=cloud_run_hosts)

    def retrieve_clouds(self):
        if not self.ids:
            msg = '--id or --ids arg required to retrieve cloud details'
            self.err(msg)
            raise Cons3rtCliError(msg)

        # Store the list of cloud dicts in this list
        clouds = []

        for cloud_id in self.ids:
            try:
                clouds.append(self.c5t.retrieve_cloud_details(cloud_id=cloud_id))
            except Cons3rtApiError as exc:
                msg = 'Problem retrieving cloud details for cloud ID: {c}\n{e}'.format(c=str(cloud_id), e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc

        # Export the clouds to a JSON file
        self.dump_json_file(clouds)

        # Output the cloud data to terminal
        for cloud in clouds:
            print(str(cloud))

        if self.args.cloudspaces:
            for cloud in clouds:
                if 'virtualizationRealms' in cloud.keys():
                    self.print_cloudspaces(cloud['virtualizationRealms'])

    def templates(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloud IDs share templates'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if not self.args.share:
            msg = '--share arg is required for cloud template actions'
            self.err(msg)
            raise Cons3rtCliError(msg)
        max_cpus = self.get_max_cpu()
        if self.args.all:
            for cloud_id in self.ids:
                try:
                    self.c5t.share_templates_to_vrs_in_cloud(cloud_id=cloud_id, max_cpus=max_cpus)
                except Cons3rtApiError as exc:
                    msg = 'Problem sharing templates in cloud ID: {c}\n{e}'.format(c=str(cloud_id), e=str(exc))
                    self.err(msg)
                    raise Cons3rtCliError(msg) from exc
        elif self.names:
            for cloud_id in self.ids:
                try:
                    self.c5t.share_templates_to_vrs_in_cloud(cloud_id=cloud_id, template_names=self.names,
                                                             max_cpus=max_cpus)
                except Cons3rtApiError as exc:
                    msg = 'Problem sharing templates in cloud ID: {c}\n{e}'.format(c=str(cloud_id), e=str(exc))
                    self.err(msg)
                    raise Cons3rtCliError(msg) from exc
        else:
            msg = '--all, --name, or --names arg required to specify templates to share'
            self.err(msg)
            raise Cons3rtCliError(msg)

    def list_clouds(self):
        clouds = []
        try:
            clouds += self.c5t.list_clouds()
        except Cons3rtApiError as exc:
            msg = 'There was a problem listing clouds\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        if len(clouds) > 0:
            clouds = self.sort_by_id(clouds)
            self.print_clouds(cloud_list=clouds)
        print('Total number of clouds found: {n}'.format(n=str(len(clouds))))


class CloudspaceCli(Cons3rtCli):

    def __init__(self, args, subcommands=None):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'allocate',
            'deallocate',
            'delete_inactive_runs',
            'list',
            'project',
            'register',
            'release_active_runs',
            'retrieve',
            'template',
            'unregister',
            'user'
        ]

    def process_subcommands(self):
        if not self.subcommands:
            return True
        if len(self.subcommands) < 1:
            return True
        if self.subcommands[0] not in self.valid_subcommands:
            self.err('Unrecognized command: {c}'.format(c=self.subcommands[0]))
            return False
        if self.subcommands[0] == 'allocate':
            try:
                self.allocate_cloudspace()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'deallocate':
            try:
                self.deallocate_cloudspace()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'delete_inactive_runs':
            try:
                self.delete_inactive_runs()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'list':
            try:
                self.list_cloudspace()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'project':
            try:
                self.list_multiple_cloudspace_projects()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'register':
            try:
                self.register_cloudspace()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'release_active_runs':
            try:
                self.release_active_runs()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'retrieve':
            try:
                self.retrieve_cloudspace()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'template':
            try:
                self.templates()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'unregister':
            try:
                self.unregister_cloudspace()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'user':
            try:
                self.list_multiple_cloudspace_users()
            except Cons3rtCliError:
                return False
        return True

    def allocate_cloudspace(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloud ID to allocate a cloudspace under'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if len(self.ids) != 1:
            msg = '--id or --ids requires 1 ID, found: {n}'.format(n=str(len(self.ids)))
            self.err(msg)
            raise Cons3rtCliError(msg)
        if not self.args.json:
            msg = '--json arg required to specify the json file to use for cloudspace allocation data'
            self.err(msg)
            raise Cons3rtCliError(msg)
        cloud_id = self.ids[0]
        json_path = self.args.json
        try:
            self.c5t.allocate_virtualization_realm_to_cloud_from_json(cloud_id=cloud_id, json_file=json_path)
        except Cons3rtApiError as exc:
            msg = 'Problem allocating a cloudspace: {i}\n{e}'.format(
                i=str(cloud_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc

    def clean_all_runs(self, unlock):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloudspace ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for cloudspace_id in self.ids:
            self.clean_all_runs_from_cloudspace(cloudspace_id, unlock)

    def clean_all_runs_from_cloudspace(self, cloudspace_id, unlock):
        try:
            self.c5t.clean_all_runs_in_virtualization_realm(vr_id=cloudspace_id, unlock=unlock)
        except Cons3rtApiError as exc:
            msg = 'There was a problem cleaning all runs from cloudspace ID: {i}\n{e}'.format(
                i=str(cloudspace_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc

    def deallocate_cloudspace(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloudspace ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for cloudspace_id in self.ids:
            self.c5t.deallocate_virtualization_realm(vr_id=cloudspace_id)

    def delete_inactive_runs(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloudspace ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for cloudspace_id in self.ids:
            self.delete_inactive_runs_from_cloudspace(cloudspace_id)

    def delete_inactive_runs_from_cloudspace(self, cloudspace_id):
        try:
            deleted_runs, not_deleted_runs = self.c5t.delete_inactive_runs_in_virtualization_realm(vr_id=cloudspace_id)
        except Cons3rtApiError as exc:
            msg = 'There was a problem deleting inactive runs from cloudspace ID: {i}\n{e}'.format(
                i=str(cloudspace_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        print('Deleted {n} inactive runs from cloudspace: {i}'.format(n=str(len(deleted_runs)), i=str(cloudspace_id)))
        if len(not_deleted_runs) > 0:
            print('Unable to delete {n} inactive runs from cloudspace: {i}'.format(
                n=str(len(not_deleted_runs)), i=str(cloudspace_id)))

    def delete_templates(self):
        for cloudspace_id in self.ids:
            if self.args.all:
                self.c5t.delete_all_template_registrations(vr_id=cloudspace_id)
            elif self.names:
                for template_name in self.names:
                    self.c5t.delete_template_registration(vr_id=cloudspace_id, template_name=template_name)

    def list_active_runs(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloudspace ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for cloudspace_id in self.ids:
            self.list_active_runs_in_cloudspace(cloudspace_id)

    def list_active_runs_in_cloudspace(self, cloudspace_id):
        try:
            drs = self.c5t.list_deployment_runs_in_virtualization_realm(
                vr_id=cloudspace_id,
                search_type='SEARCH_ACTIVE'
            )
        except Cons3rtApiError as exc:
            msg = 'There was a problem deleting inactive runs from cloudspace ID: {i}\n{e}'.format(
                i=str(cloudspace_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        print('Found {n} active runs in Cloudspace ID: {i}'.format(n=str(len(drs)), i=str(cloudspace_id)))
        if len(drs) > 0:
            self.print_drs(dr_list=drs)

    def list_cloudspace(self):
        if self.ids:
            self.list_cloudspace_resources()
        else:
            self.list_cloudspaces()

    def list_cloudspace_resources(self):
        if not self.ids:
            msg = '--id or --ids arg required to list resources in the specified cloudspace ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        unlock = False
        if self.args.unlock:
            unlock = True
        if self.args.list_active_runs:
            self.list_active_runs()
        if self.args.release_active_runs:
            self.release_active_runs()
        if self.args.delete_inactive_runs:
            self.delete_inactive_runs()
        if self.args.clean_all_runs:
            self.clean_all_runs(unlock=unlock)

    def list_cloudspace_projects(self, cloudspace_id):
        try:
            cloudspace_projects = self.c5t.list_projects_in_virtualization_realm(vr_id=cloudspace_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing projects in cloudspace: {c}'.format(c=str(cloudspace_id))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        cloudspace_projects = self.sort_by_id(cloudspace_projects)
        self.print_formatted_list(item_list=cloudspace_projects, included_columns=['id', 'name'])
        return cloudspace_projects

    def list_cloudspace_users(self, cloudspace_id):
        try:
            cloudspace_users = self.c5t.list_users_in_virtualization_realm(vr_id=cloudspace_id)
        except Cons3rtApiError as exc:
            msg = 'Problem listing users for cloudspace ID: {i}'.format(i=str(cloudspace_id))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc

        print('Cloudspace ID [{i}] has [{n}] active users'.format(i=str(cloudspace_id), n=str(len(cloudspace_users))))
        cloudspace_users = self.sort_by_id(cloudspace_users)
        self.print_formatted_list(item_list=cloudspace_users, included_columns=['id', 'username', 'email'])
        return cloudspace_users

    def list_multiple_cloudspace_projects(self):
        if self.args.all:
            self.set_ids_to_all_cloudspaces()
        else:
            if not self.ids:
                msg = '--id or --ids arg required to specify the cloudspace ID(s)'
                self.err(msg)
                raise Cons3rtCliError(msg)

        # Get the projects in the cloudspace
        for cloudspace_id in self.ids:
            self.list_cloudspace_projects(cloudspace_id=cloudspace_id)

    def list_multiple_cloudspace_users(self):
        if self.args.all:
            self.set_ids_to_all_cloudspaces()
        else:
            if not self.ids:
                msg = '--id or --ids arg required to specify the cloudspace ID(s)'
                self.err(msg)
                raise Cons3rtCliError(msg)

        # List of cloudspace IDs and the list of users
        cloudspaces = []

        # Get the users in the cloudspace
        for cloudspace_id in self.ids:
            cloudspace = self.c5t.get_virtualization_realm_details(vr_id=cloudspace_id)
            cloudspace['users'] = self.list_cloudspace_users(cloudspace_id=cloudspace_id)
            cloudspace['user_count'] = len(cloudspace['users'])
            cloudspaces.append(cloudspace)

        # Print the results
        cloudspaces = self.sort_by_id(cloudspaces)
        self.print_formatted_list(
            item_list=cloudspaces,
            included_columns=['id', 'name', 'state', 'virtualizationRealmType', 'user_count']
        )
        return cloudspaces

    def list_cloudspaces(self):
        cloudspaces = []
        try:
            cloudspaces += self.c5t.list_virtualization_realms()
        except Cons3rtApiError as exc:
            msg = 'There was a problem listing cloudspaces\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        if len(cloudspaces) > 0:
            cloudspaces = self.sort_by_id(cloudspaces)
            self.print_cloudspaces(cloudspaces_list=cloudspaces)
        print('Total number of cloudspaces found: {n}'.format(n=str(len(cloudspaces))))

    def list_templates(self):
        templates = []
        for cloudspace_id in self.ids:
            templates += self.list_templates_for_cloudspace(cloudspace_id=cloudspace_id)
        if len(templates) > 0:
            self.print_templates(template_list=templates)
        print('Total number of templates found: {n}'.format(n=str(len(templates))))

    def list_templates_for_cloudspace(self, cloudspace_id):
        try:
            templates = self.c5t.list_templates_in_virtualization_realm(
                vr_id=cloudspace_id,
                include_subscriptions=True,
                include_registrations=True,
            )
        except Cons3rtApiError as exc:
            msg = 'Problem listing templates in cloudspace ID: {i}\n{e}'.format(i=str(cloudspace_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        return templates

    def register_cloudspace(self):
        if not self.ids:
            msg = '--id required to specify the cloud ID to register the cloudspace under'
            self.err(msg)
            raise Cons3rtCliError(msg)
        cloud_id = self.ids[0]

        # Ensure --json was specified for the input file
        if not self.args.json:
            msg = '--json required to specify the JSON file to register from'
            self.err(msg)
            raise Cons3rtCliError(msg)
        json_path = self.args.json

        # register the cloudspace
        try:
            self.c5t.register_virtualization_realm_to_cloud_from_json(cloud_id=cloud_id, json_file=json_path)
        except Cons3rtApiError as exc:
            msg = 'Problem registering a cloudspace to cloud ID: {c}\n{e}'.format(
                c=str(cloud_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc

    def register_templates(self):
        successful_template_registrations = []
        failed_template_registrations = []
        for cloudspace_id in self.ids:
            if self.args.all:
                success, fail = self.c5t.register_all_templates_in_vr(vr_id=cloudspace_id)
                successful_template_registrations.append({
                    'cloudspace_id': cloudspace_id,
                    'registrations': success
                })
                failed_template_registrations.append({
                    'cloudspace_id': cloudspace_id,
                    'registrations': fail
                })
            elif self.names:
                for template_name in self.names:
                    try:
                        self.c5t.register_template_by_name_in_vr(vr_id=cloudspace_id, template_name=template_name)
                    except Cons3rtApiError as exc:
                        msg = 'Problem registering template {n} in cloudspace ID: {i}\n{e}'.format(
                            n=template_name, i=str(cloudspace_id), e=str(exc))
                        self.err(msg)
                        raise Cons3rtCliError(msg) from exc
                    else:
                        successful_template_registrations.append({
                            'cloudspace_id': cloudspace_id,
                            'registrations': [template_name]
                        })
        if len(successful_template_registrations) > 0:
            print('Successful Template Registrations:')
            print('----------------------------------')
            print('Cloudspace ID\t\tTemplate Name')
            for cloudspace in successful_template_registrations:
                for success in cloudspace['registrations']:
                    print(str(cloudspace['cloudspace_id']) + '\t\t\t\t' + success)
        if len(failed_template_registrations) > 0:
            print('Failed Template Registrations:')
            print('------------------------------')
            print('Cloudspace ID\t\tTemplate Name')
            for cloudspace in failed_template_registrations:
                for fail in cloudspace['registrations']:
                    print(str(cloudspace['cloudspace_id']) + '\t\t\t\t' + fail)

    def release_active_runs(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloudspace ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for cloudspace_id in self.ids:
            self.release_active_runs_from_cloudspace(cloudspace_id)

    def release_active_runs_from_cloudspace(self, cloudspace_id):
        try:
            released_runs, not_released_runs = self.c5t.release_active_runs_in_virtualization_realm(vr_id=cloudspace_id)
        except Cons3rtApiError as exc:
            msg = 'There was a problem releasing active runs from cloudspace ID: {i}\n{e}'.format(
                i=str(cloudspace_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        print('Release {n} active runs from cloudspace: {i}'.format(n=str(len(released_runs)), i=str(cloudspace_id)))
        if len(not_released_runs) > 0:
            print('Unable to release {n} active runs from cloudspace: {i}'.format(
                n=str(len(not_released_runs)), i=str(cloudspace_id)))

    def retrieve_cloudspace(self):
        if not self.ids:
            msg = '--id or --ids arg required to retrieve cloudspace details'
            self.err(msg)
            raise Cons3rtCliError(msg)

        # Store the list of cloudspace dicts in this list
        cloudspaces = []

        for cloudspace_id in self.ids:
            try:
                cloudspaces.append(self.c5t.get_virtualization_realm_details(vr_id=cloudspace_id))
            except Cons3rtApiError as exc:
                msg = 'Problem retrieving cloudspace details for cloudspace ID: {c}\n{e}'.format(
                    c=str(cloudspace_id), e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc

        # Export the clouds to a JSON file
        self.dump_json_file(cloudspaces)

        # Output the cloud data to terminal
        for cloudspace in cloudspaces:
            print(str(cloudspace))

    def share_template(self):
        if not self.args.provider_id:
            msg = '--provider_id arg required VR ID to share templates from'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if not self.ids:
            msg = '--id or --ids arg required list of VR IDs to share templates to'
            self.err(msg)
            raise Cons3rtCliError(msg)
        max_cpus = self.get_max_cpu()
        if self.names:
            self.c5t.share_templates_to_vrs_by_name(
                provider_vr_id=self.args.provider_id,
                template_names=self.names,
                vr_ids=self.ids,
                max_cpus=max_cpus
            )
        elif self.args.all:
            self.c5t.share_templates_to_vrs_by_name(
                provider_vr_id=self.args.provider_id,
                vr_ids=self.ids,
                max_cpus=max_cpus
            )

    def set_ids_to_all_cloudspaces(self):
        self.ids = []
        try:
            all_cloudspaces = self.c5t.list_virtualization_realms()
        except Cons3rtApiError as exc:
            msg = 'There was a problem listing cloudspaces\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc

        # Collect the list of cloudspace IDs from querying the whole site
        for cloudspace in all_cloudspaces:
            self.ids.append(cloudspace['id'])

    def templates(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloudspace ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if len(self.subcommands) > 1:
            template_subcommand = self.subcommands[1]

            if template_subcommand == 'delete':
                self.delete_templates()
                return
            elif template_subcommand == 'list':
                self.list_templates()
                return
            elif template_subcommand == 'register':
                self.register_templates()
                return
            elif template_subcommand == 'share':
                self.share_template()
                return

    def unregister_cloudspace(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloudspace ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for cloudspace_id in self.ids:
            self.c5t.unregister_virtualization_realm(vr_id=cloudspace_id)


class DeploymentCli(Cons3rtCli):

    def __init__(self, args, subcommands):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'list',
            'run'
        ]

    def process_subcommands(self):
        if not self.subcommands:
            return True
        if len(self.subcommands) < 1:
            return True
        if self.subcommands[0] not in self.valid_subcommands:
            self.err('Unrecognized command: {c}'.format(c=self.subcommands[0]))
            return False
        if self.subcommands[0] == 'list':
            try:
                self.list_deployments()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'run':
            try:
                self.run()
            except Cons3rtCliError:
                return False
        return True

    def run(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the deployment ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if len(self.subcommands) > 1:
            run_subcommand = self.subcommands[1]
            if run_subcommand == 'delete':
                self.delete_runs_for_deployments()
                return
            elif run_subcommand == 'list':
                self.list_runs_for_deployments()
                return
            elif run_subcommand == 'release':
                self.release_runs()
                return
            else:
                self.err('Unrecognized command: {c}'.format(c=run_subcommand))
            return False

    def list_deployments(self):
        deployments = []
        try:
            deployments += self.c5t.list_deployments()
        except Cons3rtApiError as exc:
            msg = 'There was a problem listing deployments\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        print('Found {n} deployments'.format(n=str(len(deployments))))
        if len(deployments) > 0:
            deployments = self.sort_by_id(deployments)
            self.print_deployments(deployment_list=deployments)

    def list_runs_for_deployments(self):
        runs = []
        for deployment_id in self.ids:
            try:
                runs += self.c5t.list_deployment_runs_for_deployment(deployment_id=deployment_id)
            except Cons3rtApiError as exc:
                msg = 'Problem listing deployment runs for deployment ID: {i}'.format(i=deployment_id)
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
        if len(runs) > 0:
            runs = self.sort_by_id(runs)
            self.print_drs(dr_list=runs)
        print('Total number of runs found: {n}'.format(n=str(len(runs))))
        return runs

    def delete_runs_for_deployments(self):
        runs = self.list_runs_for_deployments()
        inactive_run_ids = []
        for run in runs:
            if 'id' not in run.keys():
                print('WARN: id not found in run: {r}'.format(r=str(run)))
                continue
            if 'deploymentRunStatus' not in run.keys():
                print('WARN: deploymentRunStatus not found in run: {r}'.format(r=str(run)))
                continue
            if run['deploymentRunStatus'] in ['CANCELED', 'COMPLETED', 'TESTED']:
                inactive_run_ids.append(run['id'])
        if len(inactive_run_ids) > 0:
            inactive_run_ids = self.sort_by_id(inactive_run_ids)
        else:
            print('No inactive runs to delete for deployment IDs: [{i}]'.format(
                i=','.join(map(str, self.ids))))
            return
        print('Deleting [{n}] inactive runs: [{i}]'.format(
            n=str(len(inactive_run_ids)), i=','.join(map(str, inactive_run_ids))))
        for inactive_run_id in inactive_run_ids:
            print('Deleting inactive deployment run: {i}'.format(i=inactive_run_id))
            self.c5t.delete_inactive_run(dr_id=inactive_run_id)

    def release_runs(self):
        runs = self.list_runs_for_deployments()
        active_run_ids = []
        if len(runs) > 0:
            runs = self.sort_by_id(runs)
        else:
            print('No runs found to release')
            return
        for run in runs:
            if 'id' not in run.keys():
                print('WARN: id not found in run: {r}'.format(r=str(run)))
                continue
            if 'deploymentRunStatus' not in run.keys():
                print('WARN: deploymentRunStatus not found in run: {r}'.format(r=str(run)))
                continue
            if run['deploymentRunStatus'] in ['RESERVED']:
                active_run_ids.append(run['id'])
        if len(active_run_ids) > 0:
            active_run_ids = self.sort_by_id(active_run_ids)
        else:
            print('No active runs to release for deployment IDs: [{i}]'.format(
                i=','.join(map(str, self.ids))))
            return
        print('Releasing [{n}] active runs: [{i}]'.format(
            n=str(len(active_run_ids)), i=','.join(map(str, active_run_ids))))
        proceed = input('These runs will not be recoverable, proceed with release? (y/n) ')
        if not proceed:
            return
        if proceed != 'y':
            return
        for active_run_id in active_run_ids:
            self.c5t.release_deployment_run(dr_id=active_run_id)


class ProjectCli(Cons3rtCli):

    def __init__(self, args, subcommands):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'get',
            'list',
            'members',
            'run'
        ]
        self.runs = None
        self.member_list = None
        self.skip_run_ids = []

    def process_subcommands(self):
        if not self.subcommands:
            return True
        if len(self.subcommands) < 1:
            return True
        if self.subcommands[0] not in self.valid_subcommands:
            self.err('Unrecognized command: {c}'.format(c=self.subcommands[0]))
            return False
        if self.subcommands[0] == 'get':
            try:
                self.get_project()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'list':
            try:
                self.list_projects()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'members':
            try:
                self.members()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'run':
            try:
                self.handle_runs()
            except Cons3rtCliError:
                return False
        return True

    def create_snapshots(self):
        """Creates snapshots for project runs

        :return: None
        :raises: Cons3rtCliError
        """
        project_id_list = [str(num) for num in self.ids]
        results = []
        for project_id in self.ids:
            print('Creating snapshots for runs in project: {i}'.format(i=str(project_id)))
            results += self.c5t.create_snapshots_for_project(project_id=project_id, skip_run_ids=self.skip_run_ids)
        print('Completed creating snapshots for runs in projects: {i}'.format(i=','.join(map(str, project_id_list))))
        self.print_host_action_results(results=results)

    def delete_runs(self):
        runs = []
        for project_id in self.ids:
            runs += self.list_runs_for_project(project_id=project_id, search_type='SEARCH_INACTIVE')
        if len(runs) > 0:
            runs = self.sort_by_id(runs)
        else:
            print('No inactive runs to delete for project IDs: [{i}]'.format(
                i=','.join(map(str, self.ids))))
            return
        print('Total number of inactive runs found to delete: {n}'.format(n=str(len(runs))))
        for run in runs:
            self.c5t.delete_inactive_run(dr_id=run['id'])

    def delete_snapshots(self):
        """Deletes the snapshots for project runs

        :return: None
        :raises: Cons3rtCliError
        """
        project_id_list = [str(num) for num in self.ids]
        results = []
        for project_id in self.ids:
            print('Deleting snapshots for runs in project: {i}'.format(i=str(project_id)))
            results += self.c5t.delete_snapshots_for_project(project_id=project_id, skip_run_ids=self.skip_run_ids)
        print('Completed deleting snapshots for runs in projects: {i}'.format(i=','.join(map(str, project_id_list))))
        self.print_host_action_results(results=results)

    def get_project(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the project ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for project_id in self.ids:
            try:
                project_details = self.c5t.get_project_details(project_id=project_id)
            except Cons3rtApiError as exc:
                msg = 'There was a problem getting details for project: {i}\n{e}'.format(i=str(project_id), e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
            # TODO Do something better here
            print(str(project_details))

    def handle_runs(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the project ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if len(self.subcommands) > 1:
            run_subcommand = self.subcommands[1]
            if run_subcommand == 'delete':
                self.delete_runs()
                return
            elif run_subcommand == 'list':
                self.list_runs()
                return
            elif run_subcommand == 'off':
                self.power_off_runs()
                return
            elif run_subcommand == 'on':
                self.power_on_runs()
                return
            elif run_subcommand == 'release':
                self.release_runs()
                return
            elif run_subcommand == 'restore':
                self.restore_snapshots()
                return
            elif run_subcommand == 'snapshot':
                self.snapshot()
                return
            else:
                self.err('Unrecognized project command: {c}'.format(c=run_subcommand))
                return False

    def list_active_runs_for_projects(self):
        runs = []
        for project_id in self.ids:
            runs += self.list_runs_for_project(project_id=project_id, search_type='SEARCH_ACTIVE')
        return runs

    def list_project_members(self, state=None, role=None, username=None):
        members = []
        for project_id in self.ids:
            try:
                members += self.c5t.list_project_members(
                    project_id=project_id, state=state, role=role, username=username
                )
            except Cons3rtApiError as exc:
                msg = 'Problem listing members in project ID: {i}'.format(i=project_id)
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
        if len(members) > 0:
            members = self.sort_by_id(members)
            self.print_project_members(member_list=members)
        print('Number of project members found: {n}'.format(n=str(len(members))))

    def list_projects(self):
        projects = []
        try:
            projects += self.c5t.list_projects()
        except Cons3rtApiError as exc:
            msg = 'There was a problem listing projects\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        print('You are a member of {n} projects'.format(n=str(len(projects))))
        if not self.args.my:
            try:
                projects += self.c5t.list_expanded_projects()
            except Cons3rtApiError as exc:
                msg = 'There was a problem listing projects\n{e}'.format(e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
        if len(projects) > 0:
            projects = self.sort_by_id(projects)
            self.print_projects(project_list=projects)
        print('Total number of projects found: {n}'.format(n=str(len(projects))))

    def list_runs(self):
        runs = self.list_runs_for_projects()
        if len(runs) > 0:
            self.runs = self.sort_by_id(runs)
            self.print_drs(dr_list=self.runs)
        print('Total number of runs found: {n}'.format(n=str(len(runs))))

    def list_runs_for_project(self, project_id, search_type):
        try:
            runs = self.c5t.list_runs_in_project(
                project_id=project_id,
                search_type=search_type
            )
        except Cons3rtApiError as exc:
            msg = 'Problem listing runs in project ID: {i}\n{e}'.format(i=str(project_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        return runs

    def list_runs_for_projects(self):
        runs = []
        if self.args.all:
            search_type = 'SEARCH_ALL'
        elif self.args.active:
            search_type = 'SEARCH_ACTIVE'
        elif self.args.inactive:
            search_type = 'SEARCH_INACTIVE'
        else:
            search_type = 'SEARCH_ALL'
        for project_id in self.ids:
            runs += self.list_runs_for_project(project_id=project_id, search_type=search_type)
        return runs

    def members(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the project ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)

        # Collect args
        role = None
        if self.args.role:
            role = self.args.role
        state = None
        if self.args.state:
            state = self.args.state
        username = None
        if self.args.username:
            username = self.args.username

        # Check the project member command
        if len(self.subcommands) > 1:
            member_subcommand = self.subcommands[1]

            # Lists project members according to specified params
            if member_subcommand == 'list':
                try:
                    self.list_project_members(state=state, role=role, username=username)
                except Cons3rtCliError as exc:
                    raise Cons3rtCliError from exc

            else:
                self.err('Unrecognized member command: {c}'.format(c=member_subcommand))
            return False

    def power_off_runs(self):
        """Powers off the project runs

        :return: None
        :raises: Cons3rtCliError
        """
        runs = self.list_active_runs_for_projects()
        project_id_list = [str(num) for num in self.ids]
        print('Attempting to power off {n} runs in projects: {p}'.format(
                n=str(len(runs)), p=','.join(project_id_list)))
        try:
            self.c5t.power_off_multiple_runs(drs=runs)
        except Cons3rtApiError as exc:
            msg = 'Problem powering off runs in projects: {p}'.format(p=project_id_list)
            raise Cons3rtCliError(msg) from exc

    def power_on_runs(self):
        """Powers on the project runs

        :return: None
        :raises: Cons3rtCliError
        """
        runs = self.list_active_runs_for_projects()
        project_id_list = [str(num) for num in self.ids]
        print('Attempting to power on {n} runs in projects: {p}'.format(
            n=str(len(runs)), p=','.join(project_id_list)))
        try:
            self.c5t.power_on_multiple_runs(drs=runs)
        except Cons3rtApiError as exc:
            msg = 'Problem powering on runs in projects: {p}'.format(p=project_id_list)
            raise Cons3rtCliError(msg) from exc

    def release_runs(self):
        runs = []
        for project_id in self.ids:
            runs += self.list_runs_for_project(project_id=project_id, search_type='SEARCH_ACTIVE')
        if len(runs) > 0:
            runs = self.sort_by_id(runs)
        else:
            print('No inactive runs to release for project IDs: [{i}]'.format(
                i=','.join(map(str, self.ids))))
            return
        print('Total number of active runs found to release: {n}'.format(n=str(len(runs))))
        proceed = input('These runs will not be recoverable, proceed with release? (y/n) ')
        if not proceed:
            return
        if proceed != 'y':
            return
        for run in runs:
            if 'id' not in run.keys():
                print('WARNING: id not found in run: {r}'.format(r=str(run)))
                continue
            self.c5t.release_deployment_run(dr_id=run['id'])

    def restore_snapshots(self):
        """Restore the project runs from snapshots

        :return: None
        :raises: Cons3rtCliError
        """
        project_id_list = [str(num) for num in self.ids]
        results = []
        for project_id in self.ids:
            print('Restoring snapshots for runs in project: {i}'.format(i=str(project_id)))
            results += self.c5t.restore_snapshots_for_project(project_id=project_id, skip_run_ids=self.skip_run_ids)
        print('Completed restoring snapshots for runs in projects: {i}'.format(i=','.join(map(str, project_id_list))))
        self.print_host_action_results(results=results)

    def snapshot(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the project ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        skip_run_id_strs = []
        if self.args.skip:
            skip_run_id_strs = self.args.skip.split(',')
        for skip_run_id_str in skip_run_id_strs:
            self.skip_run_ids.append(int(skip_run_id_str))
        if len(self.subcommands) > 2:
            project_snapshot_subcommand = self.subcommands[2]
            if project_snapshot_subcommand == 'create':
                self.create_snapshots()
                return
            elif project_snapshot_subcommand == 'delete':
                self.delete_snapshots()
                return
            elif project_snapshot_subcommand == 'restore':
                self.restore_snapshots()
                return
            else:
                self.err('Unrecognized project run snapshot subcommand: {c}'.format(c=project_snapshot_subcommand))
                return


class RunCli(Cons3rtCli):

    def __init__(self, args, subcommands):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'cancel',
            'off',
            'on',
            'release',
            'restore',
            'snapshot'
        ]

    def process_subcommands(self):
        if not self.subcommands:
            return True
        if len(self.subcommands) < 1:
            return True
        if self.subcommands[0] not in self.valid_subcommands:
            self.err('Unrecognized command: {c}'.format(c=self.subcommands[0]))
            return False
        if self.subcommands[0] == 'cancel':
            try:
                self.cancel()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'off':
            try:
                self.power_off()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'on':
            try:
                self.power_on()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'release':
            try:
                self.cancel()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'restore':
            try:
                self.restore()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'snapshot':
            try:
                self.snapshot()
            except Cons3rtCliError:
                return False
        return True

    def cancel(self):
        for run_id in self.ids:
            self.c5t.release_deployment_run(dr_id=run_id)
            print('Attempted to cancel deployment run: {r}'.format(r=str(run_id)))

    def delete(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.delete_run_snapshots(dr_id=run_id)
        self.print_host_action_results(results=results)

    def power_off(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.power_off_run(dr_id=run_id)
        self.print_host_action_results(results=results)

    def power_on(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.power_on_run(dr_id=run_id)
        self.print_host_action_results(results=results)

    def restore(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.restore_run_snapshots(dr_id=run_id)
        self.print_host_action_results(results=results)

    def snapshot(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.create_run_snapshots(dr_id=run_id)
        self.print_host_action_results(results=results)


class ScenarioCli(Cons3rtCli):

    def __init__(self, args, subcommands=None):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'list',
            'retrieve'
        ]

    def process_subcommands(self):
        if not self.subcommands:
            return True
        if len(self.subcommands) < 1:
            return True
        if self.subcommands[0] not in self.valid_subcommands:
            self.err('Unrecognized command: {c}'.format(c=self.subcommands[0]))
            return False
        if self.subcommands[0] == 'list':
            try:
                self.list_scenarios()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'retrieve':
            try:
                self.retrieve_scenarios()
            except Cons3rtCliError:
                return False

    def list_scenarios(self):
        scenarios = []
        try:
            scenarios += self.c5t.list_scenarios()
        except Cons3rtApiError as exc:
            msg = 'There was a problem listing scenarios\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        if len(scenarios) > 0:
            scenarios = self.sort_by_id(scenarios)
            self.print_scenarios(scenario_list=scenarios)
        print('Total number of scenarios: {n}'.format(n=str(len(scenarios))))

    def retrieve_scenarios(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the scenario ID(s) to generate reports for'
            self.err(msg)
            raise Cons3rtCliError(msg)
        scenarios = []
        for scenario_id in self.ids:
            scenarios.append(self.c5t.get_system_details(system_id=scenario_id))

        # Export the clouds to a JSON file
        if self.args.json:
            json_path = self.args.json

            # Create JSON content
            try:
                json.dump(scenarios, open(json_path, 'w'), sort_keys=True, indent=2, separators=(',', ': '))
            except SyntaxError as exc:
                msg = 'Problem converting scenario data to JSON: {d}'.format(d=str(scenarios))
                raise Cons3rtCliError(msg) from exc
            except (OSError, IOError) as exc:
                msg = 'Problem creating JSON output file: {f}'.format(f=json_path)
                raise Cons3rtCliError(msg) from exc
            print('Created output JSON file containing cloud data: {f}'.format(f=json_path))

        # Output the scenario data to terminal
        for scenario in scenarios:
            print(str(scenario))


class SystemCli(Cons3rtCli):

    def __init__(self, args, subcommands=None):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'list',
            'retrieve'
        ]

    def process_subcommands(self):
        if not self.subcommands:
            return True
        if len(self.subcommands) < 1:
            return True
        if self.subcommands[0] not in self.valid_subcommands:
            self.err('Unrecognized command: {c}'.format(c=self.subcommands[0]))
            return False
        if self.subcommands[0] == 'list':
            try:
                self.list_systems()
            except Cons3rtCliError:
                return False
        if self.subcommands[0] == 'retrieve':
            try:
                self.retrieve_system_designs()
            except Cons3rtCliError:
                return False

    def list_systems(self):
        system_designs = []
        try:
            system_designs += self.c5t.list_system_designs()
        except Cons3rtApiError as exc:
            msg = 'There was a problem listing system designs\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        if len(system_designs) > 0:
            system_designs = self.sort_by_id(system_designs)
            self.print_system_designs(system_design_list=system_designs)
        print('Total number of system designs: {n}'.format(n=str(len(system_designs))))

    def retrieve_system_designs(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the system design ID(s) to generate reports for'
            self.err(msg)
            raise Cons3rtCliError(msg)
        system_designs = []
        for system_design_id in self.ids:
            system_designs.append(self.c5t.get_system_details(system_id=system_design_id))

        # Export the clouds to a JSON file
        if self.args.json:
            json_path = self.args.json

            # Create JSON content
            try:
                json.dump(system_designs, open(json_path, 'w'), sort_keys=True, indent=2, separators=(',', ': '))
            except SyntaxError as exc:
                msg = 'Problem converting system design data to JSON: {d}'.format(d=str(system_designs))
                raise Cons3rtCliError(msg) from exc
            except (OSError, IOError) as exc:
                msg = 'Problem creating JSON output file: {f}'.format(f=json_path)
                raise Cons3rtCliError(msg) from exc
            print('Created output JSON file containing cloud data: {f}'.format(f=json_path))

        # Output the system design data to terminal
        for system_design in system_designs:
            print(str(system_design))


class TeamCli(Cons3rtCli):

    def __init__(self, args, subcommands=None):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'collabtools',
            'list',
            'managers',
            'project',
            'report',
            'run'
        ]
        self.skip_run_ids = []

    def process_args(self):
        if not self.validate_args():
            return False
        if self.subcommands:
            self.process_subcommands()
        if self.args.list:
            try:
                self.list_teams()
            except Cons3rtCliError:
                return False
        return True

    def process_subcommands(self):
        if not self.subcommands:
            return True
        if len(self.subcommands) < 1:
            return True
        if self.subcommands[0] not in self.valid_subcommands:
            self.err('Unrecognized command: {c}'.format(c=self.subcommands[0]))
            return False
        if self.subcommands[0] == 'collabtools':
            try:
                self.collab_tools()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'list':
            try:
                self.list_teams()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'managers':
            try:
                self.list_team_managers()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'project':
            try:
                self.project()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'report':
            # If --assets was specified, run the asset report, otherwise run the full team report
            if self.args.assets:
                try:
                    self.generate_asset_reports()
                except Cons3rtCliError:
                    return False
            try:
                self.handle_reports()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'run':
            try:
                self.handle_runs()
            except Cons3rtCliError:
                return False
        return True

    def collab_tools(self):
        if len(self.subcommands) < 2:
            msg = 'team collabtools command not provided'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if self.subcommands[1] == 'list':
            self.list_team_collab_tools()
        elif self.subcommands[1] == 'users':
            if self.args.unique:
                self.list_team_unique_collab_tool_users()
            else:
                self.list_team_collab_tool_users()
        else:
            msg = 'Unrecognized command: {c}'.format(c=self.subcommands[1])
            self.err(msg)
            raise Cons3rtCliError(msg)

    def create_snapshots(self):
        results = []
        for team_id in self.ids:
            print('Creating snapshots for runs in team: {i}'.format(i=str(team_id)))
            results += self.c5t.create_snapshots_for_team(team_id=team_id, skip_run_ids=self.skip_run_ids)
        print('Completed creating snapshots for runs in teams: {i}'.format(i=str(self.ids)))
        self.print_host_action_results(results=results)

    def delete_snapshots(self):
        results = []
        for team_id in self.ids:
            print('Deleting snapshots for runs in team: {i}'.format(i=str(team_id)))
            results += self.c5t.delete_snapshots_for_team(team_id=team_id, skip_run_ids=self.skip_run_ids)
        print('Completed deleting snapshots for runs in teams: {i}'.format(i=str(self.ids)))
        self.print_host_action_results(results=results)

    def generate_reports(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the team ID(s) to generate reports for'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for team_id in self.ids:
            self.generate_report(team_id=team_id)

    def generate_asset_reports(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the team ID(s) to generate reports for'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for team_id in self.ids:
            self.generate_asset_report(team_id=team_id)

    def generate_report(self, team_id):
        load = False
        if self.args.load:
            load = True
        try:
            generate_team_report(team_id=team_id, load=load, cons3rt_api=self.c5t)
        except Cons3rtReportsError as exc:
            msg = 'Problem generating report for team ID: {i}\n{e}'.format(i=str(team_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc

    def generate_asset_report(self, team_id):
        try:
            generate_team_asset_report(team_id=team_id)
        except Cons3rtReportsError as exc:
            msg = 'Problem generating asset report for team ID: {i}\n{e}'.format(i=str(team_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc

    def handle_reports(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the project ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if len(self.subcommands) < 2:
            msg = 'team report subcommand not provided'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if self.subcommands[1] == 'assets':
            self.generate_asset_reports()
        elif self.subcommands[1] == 'runs':
            self.generate_reports()
        else:
            msg = 'Unrecognized team report subcommand: {c}'.format(c=self.subcommands[1])
            self.err(msg)
            raise Cons3rtCliError(msg)

    def handle_runs(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the project ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if len(self.subcommands) < 2:
            msg = 'team run subcommand not provided'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if self.subcommands[1] == 'list':
            self.list_team_runs()
        elif self.subcommands[1] == 'snapshot':
            self.snapshot()
        else:
            msg = 'Unrecognized command: {c}'.format(c=self.subcommands[1])
            self.err(msg)
            raise Cons3rtCliError(msg)

    def list_team_collab_tools(self):
        team_ids = []
        if not self.ids:
            teams = self.list_teams()
            for team in teams:
                team_ids.append(team['id'])
        else:
            team_ids = self.ids
        for team_id in team_ids:
            try:
                _, collab_tools_projects = self.c5t.list_collab_tools_projects_in_team(team_id=team_id)
            except Cons3rtApiError as exc:
                msg = 'Problem listing collab tools projects in team: {i}'.format(i=str(team_id))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
            if len(collab_tools_projects) > 0:
                collab_tools_projects = self.sort_by_id(collab_tools_projects)
                for collab_tools_project in collab_tools_projects:
                    collab_tools_project['tool_name'] = self.c5t.get_collab_tool_for_project_name(
                        collab_tools_project['name'])
                self.print_formatted_list(item_list=collab_tools_projects, included_columns=['id', 'tool_name'])

    def list_team_collab_tool_users(self):
        team_ids = []
        collab_tool_users = []
        if not self.ids:
            teams = self.list_teams()
            for team in teams:
                team_ids.append(team['id'])
        else:
            team_ids = self.ids
        for team_id in team_ids:
            try:
                team_details, collab_tools_projects = self.c5t.list_collab_tools_projects_in_team(team_id=team_id)
            except Cons3rtApiError as exc:
                msg = 'Problem listing collab tools projects in team: {i}'.format(i=str(team_id))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc

            for collab_tools_project in collab_tools_projects:
                tool_project_members = []

                # Add active members
                try:
                    tool_project_members += self.c5t.list_project_members(
                        project_id=collab_tools_project['id'], state='ACTIVE'
                    )
                except Cons3rtApiError as exc:
                    msg = 'Problem getting active project members from: {n}'.format(n=collab_tools_project['name'])
                    self.err(msg)
                    raise Cons3rtCliError(msg) from exc

                # Add blocked members
                if self.args.blocked:
                    try:
                        tool_project_members += self.c5t.list_project_members(
                            project_id=collab_tools_project['id'], state='BLOCKED'
                        )
                    except Cons3rtApiError as exc:
                        msg = 'Problem getting blocked project members from: {n}'.format(n=collab_tools_project['name'])
                        self.err(msg)
                        raise Cons3rtCliError(msg) from exc

                print('In team {i}, found {n} users in tool: {t}'.format(
                    i=str(team_id), n=str(len(tool_project_members)),
                    t=self.c5t.get_collab_tool_for_project_name(collab_tools_project['name']))
                )
                tool_project_members = self.sort_by_id(tool_project_members)
                collab_tool_users.append({
                    'team_id': str(team_id),
                    'team_name': team_details['name'],
                    'tool_name': self.c5t.get_collab_tool_for_project_name(collab_tools_project['name']),
                    'active_user_count': str(len(tool_project_members)),
                    'users': tool_project_members
                })

        if len(collab_tool_users) > 0:
            self.print_formatted_list(
                item_list=collab_tool_users,
                included_columns=['team_id', 'team_name', 'tool_name', 'active_user_count']
            )
        return collab_tool_users

    def list_team_unique_collab_tool_users(self):
        # Storge the list of unique collab tools users
        unique_collab_tool_users = []

        # Get the list of collab tool users for each team specified (or all teams)
        collab_tool_users = self.list_team_collab_tool_users()

        # Make a unique list
        for collab_tool_user in collab_tool_users:
            for user in collab_tool_user['users']:
                already_added = False
                for unique_collab_tool_user in unique_collab_tool_users:
                    if user['username'] == unique_collab_tool_user['username']:
                        already_added = True
                if not already_added:
                    unique_collab_tool_users.append(user)

        self.print_users(users_list=unique_collab_tool_users)
        print('Found {n} unique collab tools users'.format(n=str(len(unique_collab_tool_users))))
        return unique_collab_tool_users

    def list_team_managers(self):
        results = []
        not_expired = False
        active_only = False
        username = None
        if self.args.unexpired:
            not_expired = True
        if self.args.active:
            active_only = True
        if self.args.username:
            username = self.args.username
        if not self.ids or username:
            # No ids specified, getting a list for all teams
            results += self.c5t.list_team_managers(not_expired=not_expired, active_only=active_only)
        else:
            # Generate a list for each team ID specified
            for team_id in self.ids:
                results += self.c5t.list_team_managers_for_team(team_id=team_id)
        if len(results) > 0:
            if username:
                user_info = None
                for result in results:
                    if result['username'] == username:
                        user_info = result
                        break
                if not user_info:
                    print('User is not found as a team manager: {u}'.format(u=username))
                    return
                user_teams = []
                print(user_info['teamIds'])
                for team_id, team_name in zip(user_info['teamIds'], user_info['teamNames']):
                    user_teams.append({
                        'id': team_id,
                        'name': team_name
                    })
                user_teams = self.sort_by_id(user_teams)
                self.print_item_name_and_id(item_list=user_teams)
                print('User {u} is a manager of {n} teams'.format(u=username, n=str(len(user_teams))))
            else:
                results = self.sort_by_id(results)
                self.print_team_managers(team_manager_list=results)
                print('Found {n} team managers'.format(n=str(len(results))))

    def list_team_projects(self):
        team_ids = []
        if not self.ids:
            teams = self.list_teams()
            for team in teams:
                team_ids.append(team['id'])
        else:
            team_ids = self.ids

        for team_id in team_ids:
            _, team_projects = self.c5t.list_projects_in_team(team_id=team_id)
            if len(team_projects) > 0:
                team_projects = self.sort_by_id(team_projects)
                self.print_projects(project_list=team_projects)

    def list_team_runs(self):
        team_ids = []
        runs = []
        if not self.ids:
            teams = self.list_teams()
            for team in teams:
                team_ids.append(team['id'])
        else:
            team_ids = self.ids

        for team_id in team_ids:
            runs += self.c5t.list_active_runs_in_team_owned_projects(team_id=team_id)
        if len(runs) > 0:
            runs = self.sort_by_id(runs)
            self.print_drs(dr_list=runs)
        return runs

    def list_teams(self):
        teams = []
        not_expired = False
        active_only = False
        if self.args.unexpired:
            not_expired = True
        if self.args.active:
            active_only = True
        try:
            teams += self.c5t.list_teams(not_expired=not_expired, active_only=active_only)
        except Cons3rtApiError as exc:
            msg = 'There was a problem listing teams\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        if len(teams) > 0:
            teams = self.sort_by_id(teams)
            self.print_teams(teams_list=teams)
        print('Total number of teams: {n}'.format(n=str(len(teams))))
        return teams

    def project(self):
        if len(self.subcommands) < 2:
            msg = 'team project subcommand not provided'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if self.subcommands[1] == 'list':
            self.list_team_projects()
        else:
            msg = 'Unrecognized command: {c}'.format(c=self.subcommands[1])
            self.err(msg)
            raise Cons3rtCliError(msg)

    def restore_snapshots(self):
        results = []
        for team_id in self.ids:
            print('Restoring snapshots for runs in team: {i}'.format(i=str(team_id)))
            results += self.c5t.restore_snapshots_for_team(team_id=team_id, skip_run_ids=self.skip_run_ids)
        print('Completed restoring snapshots for runs in teams: {i}'.format(i=str(self.ids)))
        self.print_host_action_results(results=results)

    def snapshot(self):
        skip_run_id_strs = []
        if self.args.skip:
            skip_run_id_strs = self.args.skip.split(',')
        for skip_run_id_str in skip_run_id_strs:
            self.skip_run_ids.append(int(skip_run_id_str))
        if len(self.subcommands) > 2:
            team_snapshot_subcommand = self.subcommands[2]
            if team_snapshot_subcommand == 'create':
                self.create_snapshots()
                return
            elif team_snapshot_subcommand == 'delete':
                self.delete_snapshots()
                return
            elif team_snapshot_subcommand == 'restore':
                self.restore_snapshots()
                return
            else:
                self.err('Unrecognized team run snapshot subcommand: {c}'.format(c=team_snapshot_subcommand))
                return


class UserCli(Cons3rtCli):

    def __init__(self, args, subcommands=None):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'list',
        ]

    def process_subcommands(self):
        if not self.subcommands:
            return True
        if len(self.subcommands) < 1:
            return True
        if self.subcommands[0] not in self.valid_subcommands:
            self.err('Unrecognized command: {c}'.format(c=self.subcommands[0]))
            return False
        if self.subcommands[0] == 'list':
            try:
                self.list_users()
            except Cons3rtCliError:
                return False
        return True

    def list_users(self):
        users = []
        epoch = datetime.datetime(1970, 1, 1)
        state = None
        after = None
        before = None
        if self.args.state:
            state = self.args.state
        if self.args.after:
            try:
                after_dt = datetime.datetime.strptime("2023-01-01", "%Y-%m-%d")
            except ValueError as exc:
                msg = 'Invalid --after detected, must be format YYYY-MM-DD\n{e}'.format(e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
            after = int((after_dt - epoch).total_seconds())
        if self.args.before:
            try:
                before_dt = datetime.datetime.strptime("2023-01-01", "%Y-%m-%d")
            except ValueError as exc:
                msg = 'Invalid --before detected, must be format YYYY-MM-DD\n{e}'.format(e=str(exc))
                self.err(msg)
                raise Cons3rtCliError(msg) from exc
            before = int((before_dt - epoch).total_seconds())
        try:
            users += self.c5t.list_users(state=state, created_before=before, created_after=after)
        except Cons3rtApiError as exc:
            msg = 'There was a problem listing users\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        if len(users) > 0:
            users = self.sort_by_id(users)
            self.print_users(users_list=users)
        print('Total number of users: {n}'.format(n=str(len(users))))


def validate_ids(args):
    """Provided a set of args, validates and returns a list of IDs as ints

    :param args: argparser args
    :return: (list) of int IDs or None
    :raises: Cons3rtCliError
    """
    ids = []
    potential_ids = []
    if args.id:
        potential_ids.append(args.id)
    if args.ids:
        potential_ids += args.ids.split(',')
    if len(potential_ids) < 1:
        return
    for potential_id in potential_ids:
        try:
            valid_id = int(potential_id)
        except ValueError:
            raise Cons3rtCliError('--id or --ids provided contains an invalid int: {i}'.format(i=potential_id))
        ids.append(valid_id)
    return ids


def validate_names(args):
    """Provided a set of args, validates and returns a list of names as strings

    :param args: argparser args
    :return: (list) of string names or None
    :raises: Cons3rtCliError
    """
    names = []
    if args.name:
        names.append(args.name)
    if args.names:
        names += args.names.split(',')
    if len(names) < 1:
        return
    return names


def validate_runs(args):
    """Provided a set of args, validates and returns a list of IDs as ints

    :param args: argparser args
    :return: (list) of int IDs or None
    :raises: Cons3rtCliError
    """
    run_ids = []
    potential_run_ids = []
    if args.run:
        potential_run_ids.append(args.run)
    if args.runs:
        potential_run_ids += args.runs.split(',')
    if len(potential_run_ids) < 1:
        return
    for potential_run_id in potential_run_ids:
        try:
            valid_id = int(potential_run_id)
        except ValueError:
            raise Cons3rtCliError('--run or --runs provided contains an invalid int: {i}'.format(i=potential_run_id))
        run_ids.append(valid_id)
    return run_ids
