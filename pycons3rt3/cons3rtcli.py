#!/usr/bin/env python

import traceback

from .cons3rtapi import Cons3rtApi
from .exceptions import Cons3rtApiError


class Cons3rtCliError(Exception):
    pass


class Cons3rtCli(object):

    def __init__(self, args, subcommands=None):
        self.subcommands = subcommands
        self.args = args
        self.ids = []
        try:
            self.c5t = Cons3rtApi()
        except Cons3rtApiError as exc:
            self.err('Missing or incomplete authentication information, run [cons3rt config] to fix\n{e}'.format(
                e=str(exc)))

    def validate_args(self):
        if not self.args:
            self.err('No args provided')
            return False
        try:
            self.ids = validate_ids(self.args)
        except Cons3rtCliError:
            traceback.print_exc()
            return False
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


class CloudCli(Cons3rtCli):

    def __init__(self, args, subcommands=None):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)
        self.valid_subcommands = [
            'template',
            'list'
        ]

    def process_args(self):
        if not self.validate_args():
            return False
        sub = self.process_subcommands()
        if not sub:
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
        if self.subcommands[0] == 'list':
            try:
                self.list_clouds()
            except Cons3rtCliError:
                return False

    def templates(self):
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
        if len(self.ids) < 1:
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
        for cloudspace_id in self.ids:
            self.c5t.deallocate_virtualization_realm(vr_id=cloudspace_id)

    def unregister(self):
        for cloudspace_id in self.ids:
            self.c5t.unregister_virtualization_realm(vr_id=cloudspace_id)

    def templates(self):
        if self.args.delete:
            self.delete_templates()

    def delete_templates(self):
        for cloudspace_id in self.ids:
            if self.args.all:
                self.c5t.delete_all_template_registrations(vr_id=cloudspace_id)


class ProjectCli(Cons3rtCli):

    def __init__(self, args, subcommands):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)

    def process_args(self):
        if not self.validate_args():
            return False
        if self.args.list:
            try:
                self.list_projects()
            except Cons3rtCliError:
                return False
        return True

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


class TeamCli(Cons3rtCli):

    def __init__(self, args, subcommands=None):
        Cons3rtCli.__init__(self, args=args, subcommands=subcommands)

    def process_args(self):
        if self.subcommands:
            self.process_subcommands()
        if not self.validate_args():
            return False
        if self.args.list:
            try:
                self.list_teams()
            except Cons3rtCliError:
                return False
        return True

    def process_subcommands(self):
        print('Subcommands: ' + str(self.subcommands))

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


def validate_id(args):
    """Provided a set of args, validates and returns an int ID

    :param args: argparser args
    :return: (int) ID
    :raises: Cons3rtCliError
    """
    if not args.id:
        return
    try:
        provided_id = int(args.id)
    except ValueError:
        msg = 'ID provided is not an int: {i}'.format(i=str(args.id))
        raise Cons3rtCliError(msg)
    return provided_id


def validate_ids(args):
    """Provided a set of args, validates and returns a list of IDs as ints

    :param args: argparser args
    :return: (list) of int IDs
    :raises: Cons3rtCliError
    """
    ids = []
    try:
        lone_id = validate_id(args)
    except Cons3rtCliError as exc:
        raise Cons3rtCliError('Problem validating the --id arg') from exc
    if not args.ids:
        if lone_id:
            return [lone_id]
        return []
    elif not args.ids:
        return ids
    if lone_id:
        ids.append(lone_id)
    for an_id in args.ids.split(','):
        try:
            an_id = int(an_id)
        except ValueError:
            raise Cons3rtCliError('An ID provided is not an int: {i}'.format(i=str(an_id)))
        ids.append(an_id)
    return ids
