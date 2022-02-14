#!/usr/bin/env python

import json
import traceback

from .cons3rtapi import Cons3rtApi
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
        try:
            self.c5t = Cons3rtApi(config_file=self.config)
        except Cons3rtApiError as exc:
            self.err('Missing or incomplete authentication information, run [cons3rt config] to fix\n{e}'.format(
                e=str(exc)))

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

    @staticmethod
    def print_deployments(deployment_list):
        msg = 'ID\tName\n'
        for deployment in deployment_list:
            if 'id' in deployment:
                msg += str(deployment['id'])
            else:
                msg += '      '
            msg += '\t'
            if 'name' in deployment:
                msg += deployment['name']
            else:
                msg += '                '
            msg += '\n'
        print(msg)

    @staticmethod
    def print_drs(dr_list):
        msg = 'ID\tName\t\t\t\t\t\tStatus\t\tProject\t\tCreator\n'
        for dr_info in dr_list:

            if 'id' in dr_info:
                msg += str(dr_info['id'])
            else:
                msg += '      '
            msg += '\t'
            if 'name' in dr_info:
                msg += dr_info['name']
            else:
                msg += '                '
            msg += '\t\t\t\t\t\t'
            if 'fapStatus' in dr_info:
                msg += dr_info['fapStatus']
            else:
                msg += '              '
            msg += '\t\t'
            if 'project' in dr_info:
                msg += dr_info['project']['name']
            else:
                msg += '                 '
            msg += '\t\t'
            if 'creator' in dr_info:
                msg += dr_info['creator']['username']
            else:
                msg += '         '
            msg += '\n'
        print(msg)

    @staticmethod
    def print_projects(project_list):
        msg = 'ID\tName\n'
        for project in project_list:
            if 'id' in project:
                msg += str(project['id'])
            else:
                msg += '      '
            msg += '\t'
            if 'name' in project:
                msg += project['name']
            else:
                msg += '                '
            msg += '\n'
        print(msg)

    @staticmethod
    def print_project_members(member_list):
        msg = 'ID\tUsername\t\tEmail\t\t\t\t\tState\t\t\tRoles\n'
        for member in member_list:
            if 'id' in member:
                msg += str(member['id'])
            else:
                msg += '      '
            msg += '\t'
            if 'username' in member:
                msg += member['username']
            else:
                msg += '                '
            msg += '\t\t'
            if 'email' in member:
                msg += member['email']
            else:
                msg += '                '
            msg += '\t\t\t'
            if 'membershipState' in member:
                msg += member['membershipState']
            else:
                msg += '                '
            msg += '\t\t'
            if 'roles' in member:
                for role in member['roles']:
                    msg += role + ':'
                msg = msg.rstrip(':')
            else:
                msg += '                '
            msg += '\n'
        print(msg)

    @staticmethod
    def print_clouds(cloud_list):
        msg = 'ID\tName\t\t\t\tType\n'
        for cloud in cloud_list:
            if 'id' in cloud:
                msg += str(cloud['id'])
            else:
                msg += '      '
            msg += '\t'
            if 'name' in cloud:
                msg += cloud['name']
            else:
                msg += '                '
            msg += '\t\t\t'
            if 'cloudType' in cloud:
                msg += cloud['cloudType']
            else:
                msg += '           '
            msg += '\n'
        print(msg)

    @staticmethod
    def print_cloudspaces(cloudspaces_list):
        msg = 'ID\tName\t\t\t\tType\n'
        for cloudspace in cloudspaces_list:
            if 'id' in cloudspace:
                msg += str(cloudspace['id'])
            else:
                msg += '      '
            msg += '\t'
            if 'name' in cloudspace:
                msg += cloudspace['name']
            else:
                msg += '                '
            msg += '\t\t\t\t'
            if 'virtualizationRealmType' in cloudspace:
                msg += cloudspace['virtualizationRealmType']
            else:
                msg += '           '
            msg += '\t\t'
            if 'state' in cloudspace:
                msg += cloudspace['state']
            else:
                msg += '           '
            msg += '\n'
        print(msg)

    @staticmethod
    def print_host_action_results_list(host_action_results_list):
        msg = HostActionResult.get_host_action_result_header() + '\n'
        for host_action_result in host_action_results_list:
            msg += str(host_action_result) + '\n'
        print(msg)

    @staticmethod
    def print_scenarios(scenario_list):
        msg = 'ID\tName\n'
        for scenario in scenario_list:
            if 'id' in scenario:
                msg += str(scenario['id'])
            else:
                msg += '      '
            msg += '\t'
            if 'name' in scenario:
                msg += scenario['name']
            else:
                msg += '                '
            msg += '\n'
        print(msg)

    @staticmethod
    def print_system_designs(system_design_list):
        msg = 'ID\tName\n'
        for system in system_design_list:
            if 'id' in system:
                msg += str(system['id'])
            else:
                msg += '      '
            msg += '\t'
            if 'name' in system:
                msg += system['name']
            else:
                msg += '                '
            msg += '\n'
        print(msg)

    @staticmethod
    def print_teams(teams_list):
        msg = 'ID\tName\n'
        for team in teams_list:
            if 'id' in team:
                msg += str(team['id'])
            else:
                msg += '      '
            msg += '\t'
            if 'name' in team:
                msg += team['name']
            else:
                msg += '                '
            msg += '\n'
        print(msg)

    @staticmethod
    def print_team_managers(team_manager_list):
        msg = 'ID\t\tUserName\t\tEmail\t\t\tTeamIds\t\t\tTeamNames\n'
        for team_manager in team_manager_list:
            msg += str(team_manager['id']) + '\t\t' + team_manager['username']
            if 'email' in team_manager.keys():
                msg += '\t' + team_manager['email']
            else:
                msg += '                           '
            if 'teamIds' in team_manager.keys():
                msg += '\t' + ','.join(map(str, team_manager['teamIds']))
            else:
                msg += '         '
            if 'teamNames' in team_manager.keys():
                msg += '\t\t\t' + ','.join(map(str, team_manager['teamNames']))
            else:
                msg += '                      '
            msg += '\n'
        print(msg)

    @staticmethod
    def print_templates(template_list):
        msg = 'CloudspaceID\t\tName\t\t\t\tosType\t\tTemplateID\t\tTemplateRegistrationId\tTemplateUUID\tOffline\n'
        for template in template_list:
            if 'virtRealmId' in template:
                msg += str(template['virtRealmId'])
            else:
                msg += '    '
            msg += '\t\t\t'
            if 'virtRealmTemplateName' in template:
                msg += template['virtRealmTemplateName']
            else:
                msg += '                   '
            msg += '\t\t'
            if 'operatingSystem' in template:
                msg += template['operatingSystem']
            else:
                msg += '                 '
            msg += '\t\t'
            if 'id' in template:
                msg += str(template['id'])
            else:
                msg += '    '
            msg += '\t\t'
            if 'templateRegistration' in template:
                if 'id' in template['templateRegistration']:
                    msg += str(template['templateRegistration']['id'])
                else:
                    msg += '    '
                msg += '\t\t\t'
                if 'templateUuid' in template['templateRegistration']:
                    msg += template['templateRegistration']['templateUuid']
                else:
                    msg += '                              '
                msg += '\t\t'
                if 'offline' in template['templateRegistration']:
                    msg += str(template['templateRegistration']['offline'])
                else:
                    msg += '                              '
                msg += '\t\t'
            else:
                msg += '                                                                \t\t\t'
            msg += '\n'
        print(msg)


class CloudCli(Cons3rtCli):

    def __init__(self, args, subcommands=None):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'create',
            'delete',
            'list',
            'retrieve',
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
        if self.args.json:
            json_path = self.args.json

            # Create JSON content
            try:
                json.dump(clouds, open(json_path, 'w'), sort_keys=True, indent=2, separators=(',', ': '))
            except SyntaxError as exc:
                msg = 'Problem converting clouds data to JSON: {d}'.format(d=str(clouds))
                raise Cons3rtCliError(msg) from exc
            except (OSError, IOError) as exc:
                msg = 'Problem creating JSON output file: {f}'.format(f=json_path)
                raise Cons3rtCliError(msg) from exc
            print('Created output JSON file containing cloud data: {f}'.format(f=json_path))

        # Output the cloud data to terminal
        for cloud in clouds:
            print(str(cloud))

    def templates(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloud IDs share templates'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if not self.args.share:
            msg = '--share arg is required for cloud template actions'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if self.args.all:
            for cloud_id in self.ids:
                try:
                    self.c5t.share_templates_to_vrs_in_cloud(cloud_id=cloud_id)
                except Cons3rtApiError as exc:
                    msg = 'Problem sharing templates in cloud ID: {c}\n{e}'.format(c=str(cloud_id), e=str(exc))
                    self.err(msg)
                    raise Cons3rtCliError(msg) from exc
        elif self.names:
            for cloud_id in self.ids:
                try:
                    self.c5t.share_templates_to_vrs_in_cloud(cloud_id=cloud_id, template_names=self.names)
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
            'list',
            'template',
            'register',
            'retrieve',
            'unregister'
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
        elif self.subcommands[0] == 'list':
            try:
                self.list_cloudspace()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'register':
            try:
                self.register_cloudspace()
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
            msg = '--json arg required to specify the json file to use for cloudspaace allocation data'
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
            self.c5t.delete_inactive_runs_in_virtualization_realm(vr_id=cloudspace_id)
        except Cons3rtApiError as exc:
            msg = 'There was a problem deleting inactive runs from cloudspace ID: {i}\n{e}'.format(
                i=str(cloudspace_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc

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
            self.c5t.release_active_runs_in_virtualization_realm(vr_id=cloudspace_id)
        except Cons3rtApiError as exc:
            msg = 'There was a problem releasing active runs from cloudspace ID: {i}\n{e}'.format(
                i=str(cloudspace_id), e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc

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
        if self.args.json:
            json_path = self.args.json

            # Create JSON content
            try:
                json.dump(cloudspaces, open(json_path, 'w'), sort_keys=True, indent=2, separators=(',', ': '))
            except SyntaxError as exc:
                msg = 'Problem converting clouds data to JSON: {d}'.format(d=str(cloudspaces))
                raise Cons3rtCliError(msg) from exc
            except (OSError, IOError) as exc:
                msg = 'Problem creating JSON output file: {f}'.format(f=json_path)
                raise Cons3rtCliError(msg) from exc
            print('Created output JSON file containing cloud data: {f}'.format(f=json_path))

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
        if self.names:
            self.c5t.share_templates_to_vrs_by_name(
                provider_vr_id=self.args.provider_id,
                template_names=self.names,
                vr_ids=self.ids
            )
        elif self.args.all:
            self.c5t.share_templates_to_vrs_by_name(
                provider_vr_id=self.args.provider_id,
                vr_ids=self.ids
            )

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
            'list',
            'members',
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
                self.run()
            except Cons3rtCliError:
                return False
        return True

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

    def run(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the project ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        if len(self.subcommands) > 1:
            project_subcommand = self.subcommands[1]
            if project_subcommand == 'delete':
                self.delete_runs()
                return
            elif project_subcommand == 'list':
                self.list_runs()
                return
            elif project_subcommand == 'release':
                self.release_runs()
                return
            else:
                self.err('Unrecognized project command: {c}'.format(c=project_subcommand))
            return False

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

    def list_runs(self):
        runs = self.list_runs_for_projects()
        if len(runs) > 0:
            runs = self.sort_by_id(runs)
            self.print_drs(dr_list=runs)
        print('Total number of runs found: {n}'.format(n=str(len(runs))))

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


class RunCli(Cons3rtCli):

    def __init__(self, args, subcommands):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'off',
            'on',
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

    def power_off(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.power_off_run(dr_id=run_id)
        self.print_host_action_results_list(results)

    def power_on(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.power_on_run(dr_id=run_id)
        self.print_host_action_results_list(results)

    def restore(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.restore_run_snapshots(dr_id=run_id)
        self.print_host_action_results_list(results)

    def snapshot(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.create_run_snapshots(dr_id=run_id)
        self.print_host_action_results_list(results)


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
            system_designs = self.sort_by_id(scenarios)
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
            'list',
            'managers',
            'report'
        ]

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
        if self.subcommands[0] == 'list':
            try:
                self.list_teams()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'managers':
            try:
                self.list_team_managers()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'report':
            # If --assets was specified, run the asset report, otherwise run the full team report
            if self.args.assets:
                try:
                    self.generate_asset_reports()
                except Cons3rtCliError:
                    return False
            else:
                try:
                    self.generate_reports()
                except Cons3rtCliError:
                    return False
        return True

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
            generate_team_report(team_id=team_id, load=load)
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

    def list_team_managers(self):
        results = []
        if not self.ids:
            # No ids specified, getting a list for all teams
            results += self.c5t.list_team_managers()
        else:
            # Generate a list for each team ID specified
            for team_id in self.ids:
                results += self.c5t.list_team_managers_for_team(team_id=team_id)
        self.print_team_managers(team_manager_list=results)

    def list_teams(self):
        teams = []
        try:
            teams += self.c5t.list_teams()
        except Cons3rtApiError as exc:
            msg = 'There was a problem listing teams\n{e}'.format(e=str(exc))
            self.err(msg)
            raise Cons3rtCliError(msg) from exc
        if len(teams) > 0:
            teams = self.sort_by_id(teams)
            self.print_teams(teams_list=teams)
        print('Total number of teams: {n}'.format(n=str(len(teams))))


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
