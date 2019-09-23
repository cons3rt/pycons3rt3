#!/usr/bin/python

import json

from .httpclient import Client
from .exceptions import Cons3rtClientError


class Cons3rtClient:

    def __init__(self, base, user):
        self.base = base
        self.user = user
        self.http_client = Client(base)

    def set_user(self, user):
        self.user = user

    def register_cloud(self, cloud_file):
        """Registers a Cloud using info in the provided JSON file

        :param cloud_file: (str) path to JSON file
        :return:  (int) Cloud ID
        :raises: Cons3rtClientError
        """
        if self.user is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid user')
        if self.base is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid base')

        # Register the Cloud
        try:
            response = self.http_client.http_post(rest_user=self.user, target='clouds', content_file=cloud_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to register a Cloud from file: {f}'.format(
                f=cloud_file)
            raise Cons3rtClientError(msg) from exc

        # Get the Cloud ID from the response
        try:
            cloud_id = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        return cloud_id

    def create_team(self, team_file):
        """Creates a Team using info in the provided JSON file

        :param team_file: (str) path to JSON file
        :return:  (int) Team ID
        :raises: Cons3rtClientError
        """
        if self.user is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid user')
        if self.base is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid base')

        # Create the Team
        try:
            response = self.http_client.http_post(rest_user=self.user, target='teams', content_file=team_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a Team from file: {f}'.format(
                f=team_file)
            raise Cons3rtClientError(msg) from exc

        # Get the Team ID from the response
        try:
            team_id = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        return team_id

    def create_user(self, user_file):
        """Creates a CONS3RT User using info in the provided JSON file

        :param user_file: (str) path to JSON file
        :return:  None
        :raises: Cons3rtClientError
        """
        if self.user is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid user')
        if self.base is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid base')

        # Create the user
        try:
            response = self.http_client.http_post(rest_user=self.user, target='users', content_file=user_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a User from file: {f}'.format(
                f=user_file)
            raise Cons3rtClientError(msg) from exc

        # Get the Team ID from the response
        try:
            self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc

    def add_user_to_project(self, username, project_id):
        """Adds the username to the project ID

        :param username: (str) CONS3RT username
        :param project_id: (int) project ID
        :return: None
        :raises: Cons3rtClientError
        """
        if self.user is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid user')
        if self.base is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid base')

        # Set the target URL
        target = 'projects/{i}/members/?username={u}'.format(i=str(project_id), u=username)

        # Add the user to the project
        try:
            response = self.http_client.http_put(rest_user=self.user, target=target)
        except Cons3rtClientError as exc:
            msg = 'Unable to add username {u} to project ID: {i}'.format(
                u=username, i=str(project_id))
            raise Cons3rtClientError(msg) from exc

        # Check the response
        try:
            self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc

    def create_system(self, system_data):
        """Creates a system and returns the system ID

        :param system_data: (dict) content to create the system
        :return: (int) system ID
        """

        # Create JSON content
        try:
            json_content = json.dumps(system_data)
        except SyntaxError:
            msg = 'There was a problem converting data to JSON: {d}\n{e}'.format(
                d=str(system_data))
            raise Cons3rtClientError(msg) from exc

        try:
            response = self.http_client.http_put(
                rest_user=self.user,
                target='systems/createsystem',
                content_data=json_content)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a system from data: {d}'.format(
                d=system_data)
            raise Cons3rtClientError(msg) from exc

        # Get the Scenario ID from the response
        try:
            system_id = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        return system_id

    def create_scenario(self, scenario_data):
        """Creates a Scenario using info in the provided data

        :param scenario_data: (dict) data to provide to create the scenario
        :return: (int) Scenario ID
        :raises: Cons3rtClientError
        """
        if self.user is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid user')
        if self.base is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid base')

        # Create JSON content
        try:
            json_content = json.dumps(scenario_data)
        except SyntaxError:
            msg = 'There was a problem converting data to JSON: {d}\n{e}'.format(
                d=str(scenario_data))
            raise Cons3rtClientError(msg) from exc

        # Create the Scenario
        try:
            response = self.http_client.http_put(
                rest_user=self.user,
                target='scenarios/createscenario',
                content_data=json_content)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a Scenario from data: {d}'.format(
                d=scenario_data)
            raise Cons3rtClientError(msg) from exc

        # Get the Scenario ID from the response
        try:
            scenario_id = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        return scenario_id

    def create_deployment(self, deployment_data):
        """Creates a deployment using info in the provided data

        :param deployment_data: (dict) data to create the deployment
        :return: (int) Deployment ID
        :raises: Cons3rtClientError
        """
        if self.user is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid user')
        if self.base is None:
            raise Cons3rtClientError('Cons3rtClient was initialized with an invalid base')

        # Create JSON content
        try:
            json_content = json.dumps(deployment_data)
        except SyntaxError:
            msg = 'There was a problem converting data to JSON: {d}\n{e}'.format(
                d=str(deployment_data))
            raise Cons3rtClientError(msg) from exc

        # Create the Deployment
        try:
            response = self.http_client.http_put(
                rest_user=self.user,
                target='deployments/createdeployment',
                content_data=json_content)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a deployment from data: {d}'.format(
                d=deployment_data)
            raise Cons3rtClientError(msg) from exc

        # Get the deployment ID from the response
        try:
            deployment_id = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        return deployment_id

    def add_cloud_admin(self, cloud_id, username):
        response = self.http_client.http_put(
            rest_user=self.user, target='clouds/' + str(cloud_id) + '/admins?username=' + username)
        result = self.http_client.parse_response(response=response)
        return result

    def register_virtualization_realm(self, cloud_id, virtualization_realm_file):
        """Registers an existing Virtualization Realm to a
        specific Cloud ID, using the specified JSON file

        :param cloud_id: (int) cloud ID
        :param virtualization_realm_file: (str) path to the JSON file
        :return: (int) Virtualization Realm ID
        :raises: Cons3rtClientError
        """
        try:
            response = self.http_client.http_post(
                rest_user=self.user,
                target='clouds/' + str(cloud_id) + '/virtualizationrealms',
                content_file=virtualization_realm_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to register virtualization realm to Cloud ID {c} from file: {f}\n{e}'.format(
                c=cloud_id, f=virtualization_realm_file)
            raise Cons3rtClientError(msg) from exc
        try:
            vr_id = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex), n=ex.__class__.__name__)
            raise Cons3rtClientError(msg) from exc
        return vr_id

    def allocate_virtualization_realm(self, cloud_id, allocate_virtualization_realm_file):
        """Allocates a Virtualization Realm to the specified Cloud ID,
        using the specified JSON file

        :param cloud_id: (int) cloud ID
        :param allocate_virtualization_realm_file: (str) path to the JSON file
        :return: (int) Virtualization Realm ID
        :raises: Cons3rtClientError
        """
        try:
            response = self.http_client.http_post(
                rest_user=self.user,
                target='clouds/' + str(cloud_id) + '/virtualizationrealms/allocate',
                content_file=allocate_virtualization_realm_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to allocate virtualization realm to Cloud ID {c} from file: {f}\n{e}'.format(
                c=cloud_id, f=allocate_virtualization_realm_file)
            raise Cons3rtClientError(msg) from exc
        try:
            vr_id = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        return vr_id

    def get_cloud_id(self, cloud_name):
        retval = None

        response = self.http_client.http_get(rest_user=self.user, target='clouds')
        content = self.http_client.parse_response(response=response)
        clouds = json.loads(content)
        for cloud in clouds:
            if cloud['name'] == cloud_name:
                retval = cloud['id']

        return retval

    def list_projects(self, max_results=40, page_num=0):
        """Queries CONS3RT for a list of projects for the current user

        :param max_results (int) maximum results to provide in the response
        :param page_num (int) page number to return
        :return: (list) of projects
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='projects?maxresults={m}&page={p}'.format(m=str(max_results), p=str(page_num))
        )
        content = self.http_client.parse_response(response=response)
        teams = json.loads(content)
        return teams

    def list_expanded_projects(self, max_results=40, page_num=0):
        """Queries CONS3RT for a list of projects the user is not a member of

        :param max_results (int) maximum results to provide in the response
        :param page_num (int) page number to return
        :return: (list) of projects
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='projects/expanded?maxresults={m}&page={p}'.format(m=str(max_results), p=str(page_num))
        )
        content = self.http_client.parse_response(response=response)
        projects = json.loads(content)
        return projects

    def get_project_details(self, project_id):
        """Queries CONS3RT for details by project ID

        :param project_id: (int) ID of the project
        :return: (dict) containing project details
        """
        response = self.http_client.http_get(rest_user=self.user, target='projects/{i}'.format(i=str(project_id)))
        content = self.http_client.parse_response(response=response)
        project_details = json.loads(content)
        return project_details

    def get_virtualization_realm_details(self, vr_id):
        """Queries CONS3RT for details by project ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (dict) containing virtualization realm details
        """
        response = self.http_client.http_get(rest_user=self.user, target='virtualizationrealms/{i}'.format(
            i=str(vr_id)))
        content = self.http_client.parse_response(response=response)
        vr_details = json.loads(content)
        return vr_details

    def list_clouds(self, max_results=40, page_num=0):
        """Queries CONS3RT for a list of Clouds

        :param max_results (int) maximum results to provide in the response
        :param page_num (int) page number to return
        :return: (dict) Containing Cloud info
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='clouds?maxresults={m}&page={p}'.format(m=str(max_results), p=str(page_num))
        )
        content = self.http_client.parse_response(response=response)
        clouds = json.loads(content)
        return clouds

    def list_teams(self, max_results=40, page_num=0):
        """Queries CONS3RT for a list of Teams

        :param max_results (int) maximum results to provide in the response
        :param page_num (int) page number to return
        :return: (list) Teams
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='teams?maxresults={m}&page={p}'.format(m=str(max_results), p=str(page_num))
        )
        content = self.http_client.parse_response(response=response)
        teams = json.loads(content)
        return teams

    def get_team_details(self, team_id):
        """Queries CONS3RT for details by team ID

        :param team_id: (int) ID of the team
        :return: (dict) containing team details
        """
        response = self.http_client.http_get(rest_user=self.user, target='teams/{i}'.format(i=str(team_id)))
        content = self.http_client.parse_response(response=response)
        team_details = json.loads(content)
        return team_details

    def get_system_details(self, system_id):
        """Queries CONS3RT for details of a system ID

        :param system_id (int) ID of the system to retrieve
        :return: (dict) containing system details
        """
        response = self.http_client.http_get(rest_user=self.user, target='systems/{i}'.format(i=str(system_id)))
        content = self.http_client.parse_response(response=response)
        system_details = json.loads(content)
        return system_details

    def list_scenarios(self):
        """Queries CONS3RT for a list of all scenarios

        :return: (list) Containing Scenario info
        """
        response = self.http_client.http_get(rest_user=self.user, target='scenarios?maxresults=0')
        content = self.http_client.parse_response(response=response)
        scenarios = json.loads(content)
        return scenarios

    def get_scenario_details(self, scenario_id):
        """Queries CONS3RT for details of a scenario ID

        :param scenario_id (int) ID of the scenario to retrieve
        :return: (dict) containing scenario details
        """
        response = self.http_client.http_get(rest_user=self.user, target='scenarios/{i}'.format(i=str(scenario_id)))
        content = self.http_client.parse_response(response=response)
        scenario_details = json.loads(content)
        return scenario_details

    def list_deployments(self):
        """Queries CONS3RT for a list of all deployments

        :return: (list) Containing Deployment info
        """
        response = self.http_client.http_get(rest_user=self.user, target='deployments?maxresults=0')
        content = self.http_client.parse_response(response=response)
        deployments = json.loads(content)
        return deployments

    def get_deployment_details(self, deployment_id):
        """Queries CONS3RT for details of a deployment ID

        :param deployment_id (int) ID of the deployment to retrieve
        :return: (dict) containing deployment details
        """
        response = self.http_client.http_get(rest_user=self.user, target='deployments/{i}'.format(i=str(deployment_id)))
        content = self.http_client.parse_response(response=response)
        deployment_details = json.loads(content)
        return deployment_details

    def get_deployment_bindings_for_virtualization_realm(self, deployment_id, vr_id):
        """Queries CONS3RT for details of a deployment ID

        :param deployment_id (int) ID of the deployment to retrieve
        :param vr_id (int) ID of the virtualization realm to retrieve bindings from
        :return: (dict) containing deployment binding details
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='deployments/{i}/bindings?virtualizationRealmId={v}'.format(
                i=str(deployment_id), v=str(vr_id)))
        content = self.http_client.parse_response(response=response)
        deployment_bindings = json.loads(content)
        return deployment_bindings

    def retrieve_deployment_run_details(self, dr_id):
        """Queries CONS3RT for details on a deployment run ID

        :param: (int) deployment run ID
        :return: (list) Containing Deployment info
        """
        response = self.http_client.http_get(rest_user=self.user, target='drs/{i}'.format(i=str(dr_id)))
        content = self.http_client.parse_response(response=response)
        dr_details = json.loads(content)
        return dr_details

    def get_virtualization_realm_id(self, cloud_id, vr_name):
        retval = None

        response = self.http_client.http_get(
            rest_user=self.user,
            target='clouds/' + str(cloud_id) + '/virtualizationrealms')
        content = self.http_client.parse_response(response=response)
        vrs = json.loads(content)
        for vr in vrs:
            if vr['name'] == vr_name:
                retval = vr['id']
        return retval

    def list_virtualization_realms_for_cloud(self, cloud_id):
        """Queries CONS3RT for a list of Virtualization Realms for a specified Cloud ID

        :param cloud_id: (int) Cloud ID to query
        :return:
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='clouds/' + str(cloud_id) + '/virtualizationrealms')
        content = self.http_client.parse_response(response=response)
        vrs = json.loads(content)
        return vrs

    def add_virtualization_realm_admin(self, vr_id, username):
        response = self.http_client.http_put(
            rest_user=self.user,
            target='virtualizationrealms/' + str(vr_id) + '/admins?username=' + username)
        result = self.http_client.parse_response(response=response)
        return result

    def add_project_to_virtualization_realm(self, vr_id, project_id):
        response = self.http_client.http_put(
            rest_user=self.user,
            target='virtualizationrealms/' + str(vr_id) + '/projects?projectId=' + str(project_id))
        result = self.http_client.parse_response(response=response)
        return result

    def deactivate_virtualization_realm(self, vr_id):
        response = self.http_client.http_put(
            rest_user=self.user,
            target='virtualizationrealms/' + str(vr_id) + '/activate?activate=false')
        result = self.http_client.parse_response(response=response)
        return result

    def list_projects_in_virtualization_realm(self, vr_id, max_results=40, page_num=0):
        response = self.http_client.http_get(
            rest_user=self.user,
            target='virtualizationrealms/{v}/projects?maxresults={m}&page={p}'.format(
                v=str(vr_id),
                m=str(max_results),
                p=str(page_num)
            ))
        result = self.http_client.parse_response(response=response)
        projects = json.loads(result)
        return projects

    def remove_project_from_virtualization_realm(self, vr_id, project_id):
        response = self.http_client.http_delete(
            rest_user=self.user,
            target='virtualizationrealms/' + str(vr_id) + '/projects?projectId=' + str(project_id))
        result = self.http_client.parse_response(response=response)
        return result

    def list_deployment_runs_in_virtualization_realm(self, vr_id, search_type='SEARCH_ALL', max_results=40, page_num=0):
        response = self.http_client.http_get(
            rest_user=self.user,
            target='virtualizationrealms/{i}/deploymentruns?search_type={s}&maxresults={m}&page={p}'.format(
                i=str(vr_id), s=search_type, m=str(max_results), p=str(page_num))
        )
        try:
            result = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        drs = json.loads(result)
        return drs

    def list_networks_in_virtualization_realm(self, vr_id):
        response = self.http_client.http_get(
            rest_user=self.user,
            target='virtualizationrealms/{i}/networks'.format(i=str(vr_id))
        )
        try:
            result = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        networks = json.loads(result)
        return networks

    def list_templates_in_virtualization_realm(self, vr_id):
        response = self.http_client.http_get(
            rest_user=self.user,
            target='virtualizationrealms/{i}/templates?include_registrations=true&include_subscriptions=true'.format(
                i=str(vr_id))
        )
        try:
            result = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        templates = json.loads(result)
        return templates

    def release_deployment_run(self, dr_id):
        response = self.http_client.http_put(
            rest_user=self.user,
            target='drs/' + str(dr_id) + '/release?force=true')
        try:
            result = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        return result

    def run_deployment(self, deployment_id, run_options):

        # Create JSON content
        try:
            json_content = json.dumps(run_options)
        except SyntaxError:
            msg = 'There was a problem converting data to JSON: {d}\n{e}'.format(
                d=str(run_options))
            raise Cons3rtClientError(msg) from exc

        response = self.http_client.http_put(
            rest_user=self.user,
            target='deployments/{i}/execute'.format(i=deployment_id),
            content_data=json_content)
        try:
            dr_id = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc
        return dr_id

    def delete_deployment_run(self, dr_id):
        response = self.http_client.http_delete(rest_user=self.user, target='drs/' + str(dr_id))
        result = self.http_client.parse_response(response=response)
        return result

    def set_deployment_run_lock(self, dr_id, lock):
        response = self.http_client.http_put(
            rest_user=self.user,
            target='drs/{i}/setlock?lock={k}'.format(i=str(dr_id), k=str(lock).lower()))
        result = self.http_client.parse_response(response=response)
        return result

    def delete_asset(self, asset_id):
        response = self.http_client.http_delete(
            rest_user=self.user,
            target='assets/{i}'.format(i=str(asset_id))
        )
        result = self.http_client.parse_response(response=response)
        return result

    def deallocate_virtualization_realm(self, cloud_id, vr_id):
        response = self.http_client.http_delete(
            rest_user=self.user,
            target='clouds/' + str(cloud_id) + '/virtualizationrealms/deallocate?virtRealmId=' + str(vr_id),
            keep_alive=True
        )
        result = self.http_client.parse_response(response=response)
        return result

    def update_asset_content(self, asset_id, asset_zip_file):
        """Updates the content of the specified asset_id with the
        contents of the asset_zip_file

        :param asset_id: (int) ID of the asset to update
        :param asset_zip_file: (str) path to the asset zip file
        :return: None
        :raises: Cons3rtClientError
        """
        try:
            response = self.http_client.http_put_multipart(
                rest_user=self.user,
                target='software/' + str(asset_id) + '/updatecontent/',
                content_file=asset_zip_file
            )
        except Cons3rtClientError as exc:
            msg = 'Unable to update asset ID {i} with asset zip file: {f}\n{e}'.format(
                i=asset_id, f=asset_zip_file)
            raise Cons3rtClientError(msg) from exc
        try:
            self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc

    def update_asset_state(self, asset_id, state, asset_type):
        """Updates the asset state for the provided asset ID

        :param asset_id: (int) asset ID to update
        :param state: (str) desired asset state
        :param asset_type: (str) asset type to update
        :return: None
        :raises: Cons3rtClientError
        """
        try:
            response = self.http_client.http_put(
                rest_user=self.user,
                target='{t}/{i}/updatestate?state={s}'.format(t=asset_type, i=str(asset_id), s=state))
        except Cons3rtClientError as exc:
            msg = 'Unable to set asset state for asset ID: {i}\n{e}'.format(
                i=str(asset_id))
            raise Cons3rtClientError(msg) from exc
        try:
            self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc

    def add_trusted_project_to_asset(self, asset_id, trusted_project_id):
        """Add a trusted project ID to the asset ID

        :param asset_id: (int) asset ID to update
        :param trusted_project_id: (int) trusted project ID to add
        :return: None
        :raises: Cons3rtClientError
        """
        try:
            response = self.http_client.http_put(
                rest_user=self.user,
                target='assets/{i}/addtrustedproject?trustedid={p}'.format(i=str(asset_id), p=str(trusted_project_id))
            )
        except Cons3rtClientError as exc:
            msg = 'Problem adding trusted project {p} to asset {a}'.format(p=str(trusted_project_id), a=str(asset_id))
            raise Cons3rtClientError(msg) from exc
        try:
            self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc

    def update_asset_visibility(self, asset_id, visibility, asset_type):
        """Updates the asset visibility for the provided asset ID

        :param asset_id: (int) asset ID to update
        :param visibility: (str) desired asset visibility
        :param asset_type: (str) asset type to update
        :return: None
        :raises: Cons3rtClientError
        """
        try:
            response = self.http_client.http_put(
                rest_user=self.user,
                target='{t}/{i}/updatevisibility?visibility={s}'.format(t=asset_type, i=str(asset_id), s=visibility))
        except Cons3rtClientError as exc:
            msg = 'Unable to set asset visibility for asset ID: {i}'.format(i=str(asset_id))
            raise Cons3rtClientError(msg) from exc
        try:
            self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc

    def import_asset(self, asset_zip_file):
        """Imports a new asset from the asset zip file

        :param asset_zip_file: (str) path to the asset zip file
        :return: (int) software asset ID
        :raises: Cons3rtClientError
        """
        try:
            response = self.http_client.http_post_multipart(
                rest_user=self.user,
                target='software/import/',
                content_file=asset_zip_file,
            )
        except Cons3rtClientError as exc:
            msg = 'Unable to import asset from zip file: {f}'.format(f=asset_zip_file)
            raise Cons3rtClientError(msg) from exc
        try:
            asset_id = self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code'
            raise Cons3rtClientError(msg) from exc
        return asset_id

    def enable_remote_access(self, vr_id, size):
        """Attempts to enable remote access in virtualization realm ID to the specified size

        :param vr_id: (int) Virtualization Realm ID
        :param size: (str) Size: SMALL | MEDIUM | LARGE
        :return: None
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/remoteaccess/?instanceType={s}'.format(
            i=str(vr_id), s=size)
        # Attempt to enable remote access
        try:
            response = self.http_client.http_post(rest_user=self.user, target=target)
        except Cons3rtClientError as exc:
            msg = 'Unable to enable remote access in virtualization realm: {i}'.format(
                i=vr_id)
            raise Cons3rtClientError(msg) from exc
        try:
            self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc

    def disable_remote_access(self, vr_id):
        """Attempts to enable remote access in virtualization realm ID to the specified size

        :param vr_id: (int) Virtualization Realm ID
        :return: None
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/remoteaccess'.format(
            i=str(vr_id))
        # Attempt to enable remote access
        try:
            response = self.http_client.http_delete(rest_user=self.user, target=target)
        except Cons3rtClientError as exc:
            msg = 'Unable to disable remote access in virtualization realm: {i}'.format(
                i=vr_id)
            raise Cons3rtClientError(msg) from exc
        try:
            self.http_client.parse_response(response=response)
        except Cons3rtClientError as exc:
            msg = 'The HTTP response contains a bad status code\n{e}'.format(e=str(ex))
            raise Cons3rtClientError(msg) from exc

    def retrieve_all_users(self):
        """Query CONS3RT to retrieve all site users

        :return: (list) Containing all site users
        :raises: Cons3rtClientError
        """
        users = []
        page_num = 0
        while True:
            target = 'users?maxresults=100&page={p}'.format(p=str(page_num))
            try:
                response = self.http_client.http_get(
                    rest_user=self.user,
                    target=target
                )
            except Cons3rtClientError as exc:
                msg = 'The HTTP response contains a bad status code\n{e}'.format(
                    e=str(ex))
                raise Cons3rtClientError(msg) from exc
            result = self.http_client.parse_response(response=response)
            found_users = json.loads(result)
            users += found_users
            if len(found_users) < 100:
                break
            else:
                page_num += 1
        return users
