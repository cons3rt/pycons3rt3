#!/usr/bin/env python

import traceback

from .cons3rtapi import Cons3rtApi
from .exceptions import Cons3rtApiError, Cons3rtReportsError
from .reports import generate_team_report


class Cons3rtCliError(Exception):
    pass


class Cons3rtCli(object):

    def __init__(self, args, subcommands=None):
        self.subcommands = subcommands
        self.args = args
        self.ids = None
        self.names = None
        self.runs = None
        try:
            self.c5t = Cons3rtApi()
        except Cons3rtApiError as exc:
            self.err('Missing or incomplete authentication information, run [cons3rt config] to fix\n{e}'.format(
                e=str(exc)))

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
    def print_snapshot_results(snapshot_results_list):
        msg = 'DR_ID\tDR_Name\tHostID\tRoleName\tNumDisks\tStorageGb\tRequestTime\tResult\tError Message\n'
        for result in snapshot_results_list:
            msg += \
                str(result['dr_id']) + '\t' + \
                result['dr_name'] + '\t' + \
                str(result['host_id']) + '\t' + \
                result['host_role'] + '\t' + \
                str(result['num_disks']) + '\t' + \
                str(result['storage_gb']) + '\t' + \
                result['request_time'] + '\t' + \
                result['result'] + '\t' + \
                result['err_msg'] + '\n'
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
            'delete',
            'list',
            'template'
        ]

    def process_args(self):
        if not self.validate_args():
            return False
        if not self.process_subcommands():
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
        if self.subcommands[0] == 'delete':
            try:
                self.delete_clouds()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'list':
            try:
                self.list_clouds()
            except Cons3rtCliError:
                return False
        elif self.subcommands[0] == 'template':
            try:
                self.templates()
            except Cons3rtCliError:
                return False

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
            'deallocate',
            'list',
            'template',
            'unregister'
        ]

    def process_args(self):
        if not self.validate_args():
            return False
        sub = self.process_subcommands()
        if not sub:
            return False
        if not self.ids:
            self.err('No Cloudspace ID(s) provided, use --id=123 or --ids=3,4,5')
            return False
        unlock = False
        if self.args.unlock:
            unlock = True
        if self.subcommands:
            if len(self.subcommands) > 0:
                if self.subcommands[0] not in self.valid_subcommands:
                    self.err('Unrecognized command: {c}'.format(c=self.subcommands[0]))
                    return False
                if self.subcommands[0] == 'deallocate':
                    self.deallocate()
                elif self.subcommands[0] == 'unregister':
                    self.unregister()
        else:
            if self.args.list_active_runs or self.args.list:
                try:
                    self.list_active_runs()
                except Cons3rtCliError:
                    return False
            if self.args.release_active_runs:
                try:
                    self.release_active_runs()
                except Cons3rtCliError:
                    return False
            if self.args.delete_inactive_runs:
                try:
                    self.delete_inactive_runs()
                except Cons3rtCliError:
                    return False
            if self.args.clean_all_runs:
                try:
                    self.clean_all_runs(unlock=unlock)
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
        if self.subcommands[0] == 'template':
            try:
                self.templates()
            except Cons3rtCliError:
                return False
        return True

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

    def deallocate(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloudspace ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for cloudspace_id in self.ids:
            self.c5t.deallocate_virtualization_realm(vr_id=cloudspace_id)

    def unregister(self):
        if not self.ids:
            msg = '--id or --ids arg required to specify the cloudspace ID(s)'
            self.err(msg)
            raise Cons3rtCliError(msg)
        for cloudspace_id in self.ids:
            self.c5t.unregister_virtualization_realm(vr_id=cloudspace_id)

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

    def delete_templates(self):
        for cloudspace_id in self.ids:
            if self.args.all:
                self.c5t.delete_all_template_registrations(vr_id=cloudspace_id)
            elif self.names:
                for template_name in self.names:
                    self.c5t.delete_template_registration(vr_id=cloudspace_id, template_name=template_name)

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


class ProjectCli(Cons3rtCli):

    def __init__(self, args, subcommands):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'list',
            'run'
        ]

    def process_args(self):
        if not self.validate_args():
            return False
        if not self.process_subcommands():
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
                self.list_projects()
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
                self.err('Unrecognized command: {c}'.format(c=project_subcommand))
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
            print('No runs found to release')
            return
        print('Total number of inactive runs found to release: {n}'.format(n=str(len(runs))))
        proceed = input('These runs will not be recoverable, proceed with release? (y/n) ')
        if not proceed:
            return
        if proceed != 'y':
            return
        for run in runs:
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

    def process_args(self):
        if not self.validate_args():
            return False
        if not self.process_subcommands():
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
        self.print_snapshot_results(results)

    def power_on(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.power_on_run(dr_id=run_id)
        self.print_snapshot_results(results)

    def restore(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.restore_run_snapshots(dr_id=run_id)
        self.print_snapshot_results(results)

    def snapshot(self):
        results = []
        for run_id in self.ids:
            results += self.c5t.create_run_snapshots(dr_id=run_id)
        self.print_snapshot_results(results)


class TeamCli(Cons3rtCli):

    def __init__(self, args, subcommands=None):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
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
        elif self.subcommands[0] == 'report':
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
