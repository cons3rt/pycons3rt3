#!/usr/bin/python

import json
import logging
import os.path

from .httpclient import Client, parse_response
from .exceptions import Cons3rtClientError


class Cons3rtClient:

    def __init__(self, user):
        self.user = user
        self.http_client = Client(base=self.user.rest_api_url)

    def set_user(self, user):
        self.user = user

    @staticmethod
    def get_file_content(content_file):
        """Returns dict content from the provided file

        :param content_file: (str) path to the file
        :return: (dict) or None
        """
        # Read data from the file if provided
        if not os.path.isfile(content_file):
            return
        try:
            with open(content_file, 'r') as f:
                content = f.read()
        except (OSError, IOError) as exc:
            msg = 'Unable to read contents of file: {f}\n{e}'.format(f=content_file, e=str(exc))
            logging.warning(msg)
            return
        return content

    def create_cloud(self, cloud_ato_consent, cloud_data):
        """Created a cloud using the provided cloud data

        :param cloud_ato_consent: (bool) By setting true, the user acknowledges that - as a Team Manager - they
                a) are authorized to represent their organization, and
                b) they understand that their organization is responsible for all security and authorization to
                operate requirements for Systems deployed in their Cloudspaces.
        :param cloud_data: (dict) containing data formatted according to the CONS3RT API docs
        :return: (int) Cloud ID
        :raises: Cons3rtClientError
        """
        if cloud_ato_consent:
            cloud_ato_consent_str = 'true'
        else:
            cloud_ato_consent_str = 'false'
        target = 'clouds?cloudATOConsent={c}'.format(c=cloud_ato_consent_str)

        # Create JSON content
        try:
            json_content = json.dumps(cloud_data)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(cloud_data))
            raise Cons3rtClientError(msg) from exc

        # Create the Cloud
        try:
            response = self.http_client.http_post(rest_user=self.user, target=target, content_data=json_content)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a cloud from data: {d}'.format(d=str(cloud_data))
            raise Cons3rtClientError(msg) from exc

        # Get the Cloud ID from the response
        try:
            cloud_id = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return cloud_id

    def update_cloud(self, cloud_id, cloud_data):
        """Update the provided cloud ID using the provided cloud data

        :param cloud_id: (int) ID of the cloud to update
        :param cloud_data: (dict) containing data formatted according to the CONS3RT API docs
        :return: (bool) True if successful
        :raises: Cons3rtClientError
        """
        target = 'clouds/{i}'.format(i=str(cloud_id))

        # Create JSON content
        try:
            json_content = json.dumps(cloud_data)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(cloud_data))
            raise Cons3rtClientError(msg) from exc

        # Update the Cloud
        try:
            response = self.http_client.http_put(rest_user=self.user, target=target, content_data=json_content)
        except Cons3rtClientError as exc:
            msg = 'Unable to update cloud ID {i} from data: {d}'.format(i=str(cloud_id), d=str(cloud_data))
            raise Cons3rtClientError(msg) from exc

        # Get the response
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return result

    def delete_cloud(self, cloud_id):
        """Delete the provided cloud ID

        :param cloud_id: (int) cloud ID
        :return: (bool) True if successful
        """
        target = 'clouds/{i}'.format(i=str(cloud_id))
        response = self.http_client.http_delete(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return result

    def register_cloud(self, cloud_file):
        """Registers a Cloud using info in the provided JSON file

        :param cloud_file: (str) path to JSON file
        :return: (int) Cloud ID
        :raises: Cons3rtClientError
        """
        # Register the Cloud
        try:
            response = self.http_client.http_post(rest_user=self.user, target='clouds', content_file=cloud_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to register a Cloud from file: {f}'.format(
                f=cloud_file)
            raise Cons3rtClientError(msg) from exc

        # Get the Cloud ID from the response
        try:
            cloud_id = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return cloud_id

    def create_team(self, team_file):
        """Creates a Team using info in the provided JSON file

        :param team_file: (str) path to JSON file
        :return:  (int) Team ID
        :raises: Cons3rtClientError
        """
        # Create the Team
        try:
            response = self.http_client.http_post(rest_user=self.user, target='teams', content_file=team_file)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a Team from file: {f}'.format(
                f=team_file)
            raise Cons3rtClientError(msg) from exc

        # Get the Team ID from the response
        try:
            team_id = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return team_id

    def create_user(self, user_file=None, user_content=None):
        """Creates a CONS3RT User using info in the provided JSON file

        :param user_file: (str) path to JSON file
        :param user_content: (str or dict) user content
        :return:  None
        :raises: Cons3rtClientError
        """
        if user_file:
            user_content = Cons3rtClient.get_file_content(content_file=user_file)

        # Create JSON content
        try:
            json_content = json.dumps(user_content)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(user_content))
            raise Cons3rtClientError(msg) from exc

        # Create the user
        try:
            response = self.http_client.http_post(rest_user=self.user, target='admin/users', content_data=json_content)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a user from content: {d}'.format(d=str(user_content))
            raise Cons3rtClientError(msg) from exc

        # Get the Team ID from the response
        try:
            parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc

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
        poc_info = {
            'email': email_address,
            'firstname': first_name,
            'lastname': last_name
        }
        if phone:
            poc_info['phone'] = phone
        if organization:
            poc_info['organization'] = organization
        user_content = [{
            'pocInfo': poc_info,
            'encodedPem': encoded_pem,
            'username': username
        }]

        # Create JSON content
        try:
            json_content = json.dumps(user_content)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(user_content))
            raise Cons3rtClientError(msg) from exc

        # Create the user
        try:
            response = self.http_client.http_post(rest_user=self.user, target='/users', content_data=json_content)
        except Cons3rtClientError as exc:
            msg = 'Unable to create a user from content: {d}'.format(d=str(user_content))
            raise Cons3rtClientError(msg) from exc

        # Get the created users from the response
        try:
            created_users_response = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return created_users_response

    def add_user_to_project(self, username, project_id):
        """Adds the username to the project ID

        :param username: (str) CONS3RT username
        :param project_id: (int) project ID
        :return: None
        :raises: Cons3rtClientError
        """
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
            parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc

    def assign_role_to_project_member(self, project_id, username, role):
        """Assigns the provided role to the username in the project ID
        :param project_id: (int) project ID
        :param username: (str) CONS3RT username
        :param role: (str) project role
        :return: (bool) True if successful
        :raises: Cons3rtClientError
        """
        # Set the target URL
        target = 'projects/{i}/members/roles/?username={u}&role={r}'.format(i=str(project_id), u=username, r=role)

        # Add the user to the project
        try:
            response = self.http_client.http_put(rest_user=self.user, target=target)
        except Cons3rtClientError as exc:
            msg = 'Unable to assign role [{r}] to user [{u}] in project ID: {i}'.format(
                r=role, u=username, i=str(project_id))
            raise Cons3rtClientError(msg) from exc

        # Check the response
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return result

    def unassign_role_from_project_member(self, project_id, username, role):
        """Assigns the provided role to the username in the project ID
        :param project_id: (int) project ID
        :param username: (str) CONS3RT username
        :param role: (str) project role
        :return: (bool) True if successful
        :raises: Cons3rtClientError
        """
        # Set the target URL
        target = 'projects/{i}/members/roles/?username={u}&role={r}'.format(i=str(project_id), u=username, r=role)

        # Add the user to the project
        try:
            response = self.http_client.http_delete(rest_user=self.user, target=target)
        except Cons3rtClientError as exc:
            msg = 'Unable to unassign role [{r}] from user [{u}] in project ID: {i}'.format(
                r=role, u=username, i=str(project_id))
            raise Cons3rtClientError(msg) from exc

        # Check the response
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return result

    def create_system(self, system_data):
        """Creates a system and returns the system ID

        :param system_data: (dict) content to create the system
        :return: (int) system ID
        """

        # Create JSON content
        try:
            json_content = json.dumps(system_data)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(system_data))
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
            system_id = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return system_id

    def create_scenario(self, scenario_data):
        """Creates a Scenario using info in the provided data

        :param scenario_data: (dict) data to provide to create the scenario
        :return: (int) Scenario ID
        :raises: Cons3rtClientError
        """
        # Create JSON content
        try:
            json_content = json.dumps(scenario_data)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(scenario_data))
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
            scenario_id = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return scenario_id

    def create_deployment(self, deployment_data):
        """Creates a deployment using info in the provided data

        :param deployment_data: (dict) data to create the deployment
        :return: (int) Deployment ID
        :raises: Cons3rtClientError
        """
        # Create JSON content
        try:
            json_content = json.dumps(deployment_data)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(deployment_data))
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
            deployment_id = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return deployment_id

    def add_cloud_admin(self, cloud_id, username):
        response = self.http_client.http_put(
            rest_user=self.user, target='clouds/' + str(cloud_id) + '/admins?username=' + username)
        result = parse_response(response=response)
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
            msg = 'Unable to register virtualization realm to Cloud ID {c} from file: {f}'.format(
                c=cloud_id, f=virtualization_realm_file)
            raise Cons3rtClientError(msg) from exc
        try:
            vr_id = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
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
            msg = 'Unable to allocate virtualization realm to Cloud ID {c} from file: {f}'.format(
                c=cloud_id, f=allocate_virtualization_realm_file)
            raise Cons3rtClientError(msg) from exc
        try:
            vr_id = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return vr_id

    def get_cloud_id(self, cloud_name):
        result = None

        response = self.http_client.http_get(rest_user=self.user, target='clouds')
        content = parse_response(response=response)
        clouds = json.loads(content)
        for cloud in clouds:
            if cloud['name'] == cloud_name:
                result = cloud['id']

        return result

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
        content = parse_response(response=response)
        teams = json.loads(content)
        return teams

    def list_project_members(self, project_id, max_results=40, page_num=0, state=None, role=None, username=None):
        """Queries CONS3RT for a list of members for a project

        :param project_id: (int) ID of the project
        :param max_results: (int) maximum results to provide in the response
        :param page_num: (int) page number to return
        :param state: (str) membership state "REQUESTED" "ACTIVE" "BLOCKED" "DELETED"
        :param role: (str) membership role "ADMINISTRATOR" "ASSET_RESTORER" "STATUS_READER" "UI_MACHINE" "TEST_TOOL"
            "MEMBER" "CONSUMER" "STANDARD" "SOFTWARE_DEVELOPER" "TEST_DEVELOPER" "ASSET_SHARER" "ASSET_PROMOTER"
            "POWER_SCHEDULE_UPDATER" "PROJECT_OWNER" "PROJECT_MANAGER" "PROJECT_MODERATOR" "REMOTE_ACCESS"
            "MAESTRO_MACHINE" "FAP_MACHINE" "SCHEDULER_MACHINE" "CONS3RT_MACHINE" "SOURCEBUILDER_MACHINE"
            "SYSTEM_ASSET_IMPORTER" "ASSET_CERTIFIER" "ASSET_UPLOADER"
        :param username: (str) username to search for
        :return: (list) of projects
        :raises: Cons3rtClientError
        """
        target = 'projects/{i}/members?maxresults={m}&page={p}'.format(
            i=str(project_id),
            m=str(max_results),
            p=str(page_num)
        )
        if state:
            target += '&membershipState={s}'.format(s=state)
        if role:
            target += '&role={r}'.format(r=role)
        if username:
            target += '&name={n}'.format(n=username)
        response = self.http_client.http_get(rest_user=self.user, target=target)
        content = parse_response(response=response)
        members = json.loads(content)
        return members

    def list_all_project_members(self, project_id, state=None, role=None, username=None):
        """List all project members matching the provided search parameters

        :param project_id: (int) ID of the project
        :param state: (str) membership state "REQUESTED" "ACTIVE" "BLOCKED" "DELETED"
        :param role: (str) membership role "ADMINISTRATOR" "ASSET_RESTORER" "STATUS_READER" "UI_MACHINE" "TEST_TOOL"
            "MEMBER" "CONSUMER" "STANDARD" "SOFTWARE_DEVELOPER" "TEST_DEVELOPER" "ASSET_SHARER" "ASSET_PROMOTER"
            "POWER_SCHEDULE_UPDATER" "PROJECT_OWNER" "PROJECT_MANAGER" "PROJECT_MODERATOR" "REMOTE_ACCESS"
            "MAESTRO_MACHINE" "FAP_MACHINE" "SCHEDULER_MACHINE" "CONS3RT_MACHINE" "SOURCEBUILDER_MACHINE"
            "SYSTEM_ASSET_IMPORTER" "ASSET_CERTIFIER" "ASSET_UPLOADER"
        :param username: (str) username to search for
        :return: (list) of projects
        :raises: Cons3rtClientError
        """
        members = []
        page_num = 0
        max_results = 40
        info_msg = 'project [{i}]'.format(i=str(project_id))
        if state:
            info_msg += ', membership state [{s}]'.format(s=state)
        if role:
            info_msg += ', project role [{r}]'.format(r=role)
        if username:
            info_msg += ', username [{n}]'.format(n=username)
        while True:
            msg = 'Retrieving members page [{p}]: '.format(p=str(page_num)) + info_msg
            print(msg)
            try:
                page_of_members = self.list_project_members(
                    project_id=project_id,
                    max_results=max_results,
                    page_num=page_num,
                    state=state,
                    role=role,
                    username=username
                )
            except Cons3rtClientError as exc:
                msg = 'Problem getting members page [{p}], max results [{m}] from: {i}'.format(
                    p=str(page_num), m=str(max_results), i=info_msg)
                raise Cons3rtClientError(msg) from exc
            members += page_of_members
            if len(page_of_members) < max_results:
                break
            else:
                page_num += 1
            print('Found {n} members in: {i}'.format(n=str(len(members)), i=info_msg))
        return members

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
        content = parse_response(response=response)
        projects = json.loads(content)
        return projects

    def get_project_details(self, project_id):
        """Queries CONS3RT for details by project ID

        :param project_id: (int) ID of the project
        :return: (dict) containing project details
        """
        target = 'projects/{i}'.format(i=str(project_id))
        response = self.http_client.http_get(rest_user=self.user, target=target)
        content = parse_response(response=response)
        project_details = json.loads(content)
        return project_details

    def get_project_host_metrics(self, project_id, start, end, interval=1, interval_unit='HOURS'):
        """Queries CONS3RT for metrics by project ID

        :param project_id: (int) ID of the project
        :param start: (int) start time for metrics in unix epoch time
        :param end: (int) end time for metrics in unix epoch time
        :param interval: (int) number of intervals
        :param interval_unit: (str) Enum: "Nanos" "Micros" "Millis" "Seconds" "Minutes" "Hours" "HalfDays" "Days"
            "Weeks" "Months" "Years" "Decades" "Centuries" "Millennia" "Eras" "Forever"
        :return: (dict) containing project metrics
        """
        target = 'projects/{i}/metrics/hostconfiguration?start={s}&end={e}&interval={v}&intervalUnit={u}'.format(
            i=str(project_id),
            s=str(start),
            e=str(end),
            v=str(interval),
            u=interval_unit
        )
        response = self.http_client.http_get(rest_user=self.user, target=target)
        content = parse_response(response=response)
        project_metrics = json.loads(content)
        return project_metrics

    def get_virtualization_realm_details(self, vr_id):
        """Queries CONS3RT for details by project ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (dict) containing virtualization realm details
        """
        response = self.http_client.http_get(rest_user=self.user, target='virtualizationrealms/{i}'.format(
            i=str(vr_id)))
        content = parse_response(response=response)
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
        content = parse_response(response=response)
        clouds = json.loads(content)
        return clouds

    def retrieve_cloud_details(self, cloud_id):
        """Returns details for the provided cloud ID

        :param cloud_id: (int) Cloud ID
        :return: (dict)
        """
        target = 'clouds/{i}'.format(i=str(cloud_id))
        response = self.http_client.http_get(rest_user=self.user, target=target)
        content = parse_response(response=response)
        cloud_details = json.loads(content)
        return cloud_details

    def list_teams(self, max_results=40, page_num=0):
        """Queries CONS3RT for a list of Teams

        :param max_results (int) maximum results to provide in the response
        :param page_num (int) page number to return
        :return: (list) Teams
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='admin/teams?maxresults={m}&page={p}'.format(m=str(max_results), p=str(page_num))
        )
        content = parse_response(response=response)
        teams = json.loads(content)
        return teams

    def get_team_details(self, team_id):
        """Queries CONS3RT for details by team ID

        :param team_id: (int) ID of the team
        :return: (dict) containing team details
        """
        response = self.http_client.http_get(rest_user=self.user, target='teams/{i}'.format(i=str(team_id)))
        content = parse_response(response=response)
        team_details = json.loads(content)
        return team_details

    def list_services_for_team(self, team_id):
        """Lists the services for a team

        :param team_id: (int) team ID
        :return: (dict)
        """
        response = self.http_client.http_get(rest_user=self.user, target='teams/{i}/services'.format(i=str(team_id)))
        content = parse_response(response=response)
        team_services = json.loads(content)
        return team_services

    def list_users_for_team_service(self, team_id, service_type):
        """Lists the services for a team

        :param team_id: (int) team ID
        :param service_type: (str) Service Type
        :return: (list) user (dict)
        """
        response = self.http_client.http_get(rest_user=self.user, target='teams/{t}/services/{s}/users'.format(
            t=str(team_id), s=service_type))
        content = parse_response(response=response)
        service_users = json.loads(content)
        return service_users

    def get_system_details(self, system_id):
        """Queries CONS3RT for details of a system ID

        :param system_id (int) ID of the system to retrieve
        :return: (dict) containing system details
        """
        response = self.http_client.http_get(rest_user=self.user, target='systems/{i}'.format(i=str(system_id)))
        content = parse_response(response=response)
        system_details = json.loads(content)
        return system_details

    def list_system_designs(self, max_results=40, page_num=0):
        """Returns a list of systems

        :param max_results: (int) maximum number of results to retrieve
        :param page_num: (int) page number to return
        :return: (list) Containing Scenario info
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='systems?maxresults={m}&page={p}'.format(
                m=str(max_results),
                p=str(page_num)
            ))
        content = parse_response(response=response)
        systems = json.loads(content)
        return systems

    def list_all_system_designs(self):
        """Returns a list of all system designs

        :return: (list) of system designs
        :raises: Cons3rtClientError
        """
        system_designs = []
        page_num = 0
        max_results = 40
        while True:
            print('Retrieving system designs: page {p}'.format(p=str(page_num)))
            try:
                page_of_system_designs = self.list_system_designs(
                    max_results=max_results,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'Problem querying CONS3RT for a list of system designs, ' \
                      'page: {p}, max results: {m}'.format(p=str(page_num), m=str(max_results))
                raise Cons3rtClientError(msg) from exc
            system_designs += page_of_system_designs
            if len(page_of_system_designs) < max_results:
                break
            else:
                page_num += 1
            print('Found {n} system designs'.format(n=str(len(system_designs))))
        return system_designs

    def list_scenarios(self, max_results=40, page_num=0):
        """Queries CONS3RT for a list of all scenarios

        :param max_results: (int) maximum number of results to retrieve
        :param page_num: (int) page number to return
        :return: (list) Containing Scenario info
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='scenarios?maxresults={m}&page={p}'.format(
                m=str(max_results),
                p=str(page_num)
            ))
        content = parse_response(response=response)
        scenarios = json.loads(content)
        return scenarios

    def list_all_scenarios(self):
        """Returns a list of all scenarios

        :return: (list) of scenarios
        :raises: Cons3rtClientError
        """
        scenarios = []
        page_num = 0
        max_results = 40
        while True:
            print('Retrieving scenarios: page {p}'.format(p=str(page_num)))
            try:
                page_of_scenarios = self.list_system_designs(
                    max_results=max_results,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'Problem querying CONS3RT for a list of scenarios, ' \
                      'page: {p}, max results: {m}'.format(p=str(page_num), m=str(max_results))
                raise Cons3rtClientError(msg) from exc
            scenarios += page_of_scenarios
            if len(page_of_scenarios) < max_results:
                break
            else:
                page_num += 1
            print('Found {n} scenarios'.format(n=str(len(scenarios))))
        return scenarios

    def get_scenario_details(self, scenario_id):
        """Queries CONS3RT for details of a scenario ID

        :param scenario_id (int) ID of the scenario to retrieve
        :return: (dict) containing scenario details
        """
        response = self.http_client.http_get(rest_user=self.user, target='scenarios/{i}'.format(i=str(scenario_id)))
        content = parse_response(response=response)
        scenario_details = json.loads(content)
        return scenario_details

    def list_deployments(self):
        """Queries CONS3RT for a list of all deployments

        :return: (list) Containing Deployment info
        """
        response = self.http_client.http_get(rest_user=self.user, target='deployments?maxresults=0')
        content = parse_response(response=response)
        deployments = json.loads(content)
        return deployments

    def get_deployment_details(self, deployment_id):
        """Queries CONS3RT for details of a deployment ID

        :param deployment_id (int) ID of the deployment to retrieve
        :return: (dict) containing deployment details
        """
        response = self.http_client.http_get(rest_user=self.user, target='deployments/{i}'.format(i=str(deployment_id)))
        content = parse_response(response=response)
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
        content = parse_response(response=response)
        deployment_bindings = json.loads(content)
        return deployment_bindings

    def retrieve_deployment_run_details(self, dr_id):
        """Queries CONS3RT for details on a deployment run ID

        :param dr_id: (int) deployment run ID
        :return: (dict) Containing Deployment Run Info
        """
        response = self.http_client.http_get(rest_user=self.user, target='drs/{i}'.format(i=str(dr_id)))
        content = parse_response(response=response)
        dr_details = json.loads(content)
        return dr_details

    def retrieve_deployment_run_host_details(self, dr_id, drh_id):
        """Queries CONS3RT for details on a deployment run host ID

        :param dr_id: (int) deployment run ID
        :param drh_id: (int) deployment run host ID
        :return: (dict) Containing Deployment Run Host Info
        """
        response = self.http_client.http_get(rest_user=self.user, target='drs/{d}/host/{h}'.format(
            d=str(dr_id), h=str(drh_id)))
        content = parse_response(response=response)
        drh_details = json.loads(content)
        return drh_details

    def get_virtualization_realm_id(self, cloud_id, vr_name):
        result = None

        response = self.http_client.http_get(
            rest_user=self.user,
            target='clouds/' + str(cloud_id) + '/virtualizationrealms')
        content = parse_response(response=response)
        vrs = json.loads(content)
        for vr in vrs:
            if vr['name'] == vr_name:
                result = vr['id']
        return result

    def list_all_virtualization_realms(self):
        """Returns a list of virtualization realms

        :return: (list) of virtualization realms
        :raises: Cons3rtClientError
        """
        vrs = []
        page_num = 0
        max_results = 40
        while True:
            print('Retrieving virtualization realms: page {p}'.format(p=str(page_num)))
            try:
                page_of_vrs = self.list_virtualization_realms(
                    max_results=max_results,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'Problem querying CONS3RT for a list of virtualization realms, ' \
                      'page: {p}, max results: {m}'.format(p=str(page_num), m=str(max_results))
                raise Cons3rtClientError(msg) from exc
            vrs += page_of_vrs
            if len(page_of_vrs) < max_results:
                break
            else:
                page_num += 1
            print('Found {n} virtualization realms'.format(n=str(len(vrs))))
        return vrs

    def list_all_virtualization_realms_for_cloud(self, cloud_id):
        """Returns a list of virtualization realms in the provided cloud ID

        :param cloud_id: (int) ID of the cloud
        :return: (list) of virtualization realms
        :raises: Cons3rtClientError
        """
        vrs = []
        page_num = 0
        max_results = 40
        while True:
            print('Retrieving virtualization realms for cloud {i}: page {p}'.format(
                i=str(cloud_id), p=str(page_num)))
            try:
                page_of_vrs = self.list_virtualization_realms_for_cloud(
                    cloud_id=cloud_id,
                    max_results=max_results,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'Problem querying CONS3RT for a list of virtualization realms in cloud ID: {i}, ' \
                      'page: {p}, max results: {m}'.format(i=str(cloud_id), p=str(page_num), m=str(max_results))
                raise Cons3rtClientError(msg) from exc
            vrs += page_of_vrs
            if len(page_of_vrs) < max_results:
                break
            else:
                page_num += 1
            print('Found {n} virtualization realms in cloud {i}...'.format(n=str(len(vrs)), i=str(cloud_id)))
        return vrs

    def list_all_virtualization_realms_for_project(self, project_id):
        """Returns a list of virtualization realms in the provided project ID

        :param project_id: (int) ID of the project
        :return: (list) of virtualization realms
        :raises: Cons3rtClientError
        """
        vrs = []
        page_num = 0
        max_results = 40
        while True:
            print('Retrieving virtualization realms for project {i}: page {p}'.format(
                i=str(project_id), p=str(page_num)))
            try:
                page_of_vrs = self.list_virtualization_realms_for_project(
                    project_id=project_id,
                    max_results=max_results,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'Problem querying CONS3RT for a list of virtualization realms in project ID: {i}, ' \
                      'page: {p}, max results: {m}'.format(i=str(project_id), p=str(page_num), m=str(max_results))
                raise Cons3rtClientError(msg) from exc
            vrs += page_of_vrs
            if len(page_of_vrs) < max_results:
                break
            else:
                page_num += 1
            print('Found {n} virtualization realms in project {i}...'.format(n=str(len(vrs)), i=str(project_id)))
        return vrs

    def list_all_virtualization_realms_for_team(self, team_id):
        """Returns a list of virtualization realms in the provided team ID

        :param team_id: (int) ID of the team
        :return: (list) of virtualization realms
        :raises: Cons3rtClientError
        """
        vrs = []
        page_num = 0
        max_results = 40
        while True:
            print('Retrieving virtualization realms for team {i}: page {p}'.format(
                i=str(team_id), p=str(page_num)))
            try:
                page_of_vrs = self.list_virtualization_realms_for_team(
                    team_id=team_id,
                    max_results=max_results,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'Problem querying CONS3RT for a list of virtualization realms in team ID: {i}, ' \
                      'page: {p}, max results: {m}'.format(i=str(team_id), p=str(page_num), m=str(max_results))
                raise Cons3rtClientError(msg) from exc
            vrs += page_of_vrs
            if len(page_of_vrs) < max_results:
                break
            else:
                page_num += 1
            print('Found {n} virtualization realms in team {i}...'.format(n=str(len(vrs)), i=str(team_id)))
        return vrs

    def list_virtualization_realms(self, max_results=40, page_num=0):
        """Queries CONS3RT for a list of Virtualization Realms for a specified team ID

        :param max_results: (int) maximum number of results to retrieve
        :param page_num: (int) page number to return
        :return: (list) of virtualization realms
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='virtualizationrealms?maxresults={m}&page={p}'.format(
                m=str(max_results),
                p=str(page_num)
            ))
        content = parse_response(response=response)
        vrs = json.loads(content)
        return vrs

    def list_virtualization_realms_for_cloud(self, cloud_id, max_results=40, page_num=0):
        """Queries CONS3RT for a list of Virtualization Realms for a specified Cloud ID

        :param cloud_id: (int) Cloud ID to query
        :param max_results: (int) maximum number of results to retrieve
        :param page_num: (int) page number to return
        :return: (list) of virtualization realms
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='clouds/{i}/virtualizationrealms?maxresults={m}&page={p}'.format(
                i=str(cloud_id),
                m=str(max_results),
                p=str(page_num)
            ))
        content = parse_response(response=response)
        vrs = json.loads(content)
        return vrs

    def list_virtualization_realms_for_project(self, project_id, max_results=40, page_num=0):
        """Queries CONS3RT for a list of Virtualization Realms for a specified project ID

        :param project_id: (int) project ID to query
        :param max_results: (int) maximum number of results to retrieve
        :param page_num: (int) page number to return
        :return: (list) of virtualization realms
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='projects/{i}/virtualizationrealms?maxresults={m}&page={p}'.format(
                i=str(project_id),
                m=str(max_results),
                p=str(page_num)
            ))
        content = parse_response(response=response)
        vrs = json.loads(content)
        return vrs

    def list_virtualization_realms_for_team(self, team_id, max_results=40, page_num=0):
        """Queries CONS3RT for a list of Virtualization Realms for a specified team ID

        :param team_id: (int) project ID to query
        :param max_results: (int) maximum number of results to retrieve
        :param page_num: (int) page number to return
        :return: (list) of virtualization realms
        """
        response = self.http_client.http_get(
            rest_user=self.user,
            target='teams/{i}/virtualizationrealms?maxresults={m}&page={p}'.format(
                i=str(team_id),
                m=str(max_results),
                p=str(page_num)
            ))
        content = parse_response(response=response)
        vrs = json.loads(content)
        return vrs

    def add_project_to_virtualization_realm(self, vr_id, project_id):
        response = self.http_client.http_put(
            rest_user=self.user,
            target='virtualizationrealms/' + str(vr_id) + '/projects?projectId=' + str(project_id))
        result = parse_response(response=response)
        return result

    def set_virtualization_realm_state(self, vr_id, state, force=False):
        if state:
            state_str = 'true'
        else:
            state_str = 'false'
        target = 'virtualizationrealms/{i}/activate?activate={s}'.format(i=str(vr_id), s=state_str)
        if force:
            target += '&force=true'
        response = self.http_client.http_put(rest_user=self.user, target=target)
        result = parse_response(response=response)
        return result

    def list_projects_in_virtualization_realm(self, vr_id, max_results=40, page_num=0):
        response = self.http_client.http_get(
            rest_user=self.user,
            target='virtualizationrealms/{v}/projects?maxresults={m}&page={p}'.format(
                v=str(vr_id),
                m=str(max_results),
                p=str(page_num)
            ))
        result = parse_response(response=response)
        projects = json.loads(result)
        return projects

    def remove_project_from_virtualization_realm(self, vr_id, project_id):
        response = self.http_client.http_delete(
            rest_user=self.user,
            target='virtualizationrealms/' + str(vr_id) + '/projects?projectId=' + str(project_id))
        result = parse_response(response=response)
        return result

    def list_deployment_runs(self, search_type='SEARCH_ACTIVE', in_project=False, max_results=40, page_num=0):
        response = self.http_client.http_get(
            rest_user=self.user,
            target='drs?search_type={s}&in_project={i}&maxresults={m}&page={p}'.format(
                s=search_type, i=str(in_project).lower(), m=str(max_results), p=str(page_num)))
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        drs = json.loads(result)
        return drs

    def list_all_deployment_runs(self, search_type='SEARCH_ALL', in_project=False):
        """Lists all the deployment runs with the specified search_type and in_project

        :param search_type: (str) search type
        :param in_project: (bool) Include project runs
        :return: (list) of deployment runs
        :raises: Cons3rtClientError
        """
        drs = []
        page_num = 0
        max_results = 40
        while True:
            try:
                page_of_drs = self.list_deployment_runs(
                    max_results=max_results,
                    page_num=page_num,
                    search_type=search_type,
                    in_project=in_project
                )
            except Cons3rtClientError as exc:
                msg = ('Problem listing runs with search_type [{s}] and in_project [{i}] page: {p}, max results: '
                       '{m}').format(s=search_type, i=str(in_project), p=str(page_num), m=str(max_results))
                raise Cons3rtClientError(msg) from exc
            drs += page_of_drs
            if len(page_of_drs) < max_results:
                break
            else:
                page_num += 1
            print('Found {n} deployment runs...'.format(n=str(len(drs))))
        return drs

    def list_deployment_runs_for_deployment(self, deployment_id, max_results=40, page_num=0):
        response = self.http_client.http_get(
            rest_user=self.user,
            target='deployments/{i}/runs?maxresults={m}&page={p}'.format(
                i=str(deployment_id), m=str(max_results), p=str(page_num)))
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        drs = json.loads(result)
        return drs

    def list_all_deployment_runs_for_deployment(self, deployment_id):
        """Lists all the deployment runs in a deployment by page

        :param deployment_id: (int) ID of the virtualization realm
        :return: (list) of deployment runs
        :raises: Cons3rtClientError
        """
        drs = []
        page_num = 0
        max_results = 40
        while True:
            print('Retrieving deployment runs in deployment [{i}]: page {p}'.format(
                i=str(deployment_id), p=str(page_num)))
            try:
                page_of_drs = self.list_deployment_runs_for_deployment(
                    deployment_id=deployment_id,
                    max_results=max_results,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'There was a problem querying CONS3RT for a list of runs in deployment ID: {i}, ' \
                      'page: {p}, max results: {m}'.format(i=str(deployment_id), p=str(page_num), m=str(max_results))
                raise Cons3rtClientError(msg) from exc
            drs += page_of_drs
            if len(page_of_drs) < max_results:
                break
            else:
                page_num += 1
            print('Found {n} deployment runs...'.format(n=str(len(drs))))
        return drs

    def list_deployment_runs_in_virtualization_realm(self, vr_id, search_type='SEARCH_ALL', max_results=40, page_num=0):
        response = self.http_client.http_get(
            rest_user=self.user,
            target='virtualizationrealms/{i}/deploymentruns?search_type={s}&maxresults={m}&page={p}'.format(
                i=str(vr_id), s=search_type, m=str(max_results), p=str(page_num))
        )
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        drs = json.loads(result)
        return drs

    def list_all_deployment_runs_in_virtualization_realm(self, vr_id, search_type='SEARCH_ALL'):
        """Lists the deployment runs in a virtualization realm by page

        :param vr_id: (int) ID of the virtualization realm
        :param search_type: (str) search type
        :return: (list) of deployment runs
        :raises: Cons3rtClientError
        """
        drs = []
        page_num = 0
        max_results = 40
        while True:
            try:
                page_of_drs = self.list_deployment_runs_in_virtualization_realm(
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
            print('Found {n} deployment runs...'.format(n=str(len(drs))))
        return drs

    def list_networks_in_virtualization_realm(self, vr_id):
        response = self.http_client.http_get(
            rest_user=self.user,
            target='virtualizationrealms/{i}/networks'.format(i=str(vr_id))
        )
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        networks = json.loads(result)
        return networks

    def list_templates_in_virtualization_realm(self, vr_id, include_registrations=True, include_subscriptions=True):
        """Lists template registrations in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :param include_registrations: (bool) Set True to include templates registered in this virtualization realm
        :param include_subscriptions: (bool) Set True to include templates registered in this virtualization realm
        :return: (list) of template data
        :raises: Cons3rtClientError
        """
        if include_registrations:
            reg_str = 'true'
        else:
            reg_str = 'false'
        if include_subscriptions:
            sub_str = 'true'
        else:
            sub_str = 'false'
        target = 'virtualizationrealms/{i}/templates?include_registrations={r}&include_subscriptions={s}'.format(
            i=str(vr_id), r=reg_str, s=sub_str)
        response = self.http_client.http_get(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        templates = json.loads(result)
        return templates

    def list_template_registrations_in_virtualization_realm(self, vr_id):
        """Lists template registrations in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (list) of template data
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/templates/registrations'.format(i=str(vr_id))
        response = self.http_client.http_get(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        templates = json.loads(result)
        return templates

    def list_template_subscriptions_in_virtualization_realm(self, vr_id):
        """Lists template subscriptions in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (list) of template data
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/templates/subscriptions'.format(i=str(vr_id))
        response = self.http_client.http_get(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        templates = json.loads(result)
        return templates

    def list_pending_template_subscriptions_in_virtualization_realm(self, vr_id):
        """Lists template subscriptions in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (list) of template data
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/templates/subscriptions/pending'.format(i=str(vr_id))
        response = self.http_client.http_get(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        templates = json.loads(result)
        return templates

    def retrieve_template_registration(self, vr_id, template_registration_id):
        """Retrieves template registration data in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :param template_registration_id: (int) ID of the template registration
        :return: (dict) of template registration data
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/templates/registrations/{r}'.format(
            i=str(vr_id), r=str(template_registration_id))
        response = self.http_client.http_get(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        template_registration_data = json.loads(result)
        return template_registration_data

    def retrieve_template_subscription(self, vr_id, template_subscription_id):
        """Retrieves template subscription data in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :param template_subscription_id: (int) ID of the template subscription
        :return: (bool) True is successful
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/templates/subscriptions/{r}'.format(
            i=str(vr_id), r=str(template_subscription_id))
        response = self.http_client.http_get(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        template_subscription_data = json.loads(result)
        return template_subscription_data

    def refresh_template_cache(self, vr_id):
        """Refreshes the template cache for the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (bool) True if successful
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/templates/registrations'.format(i=str(vr_id))
        response = self.http_client.http_put(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        is_success = json.loads(result)
        return is_success

    def list_unregistered_templates(self, vr_id):
        """Returns a list of unregistered templates in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :return: (list) of unregistered templates
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/templates/registrations/pending'.format(i=str(vr_id))
        response = self.http_client.http_get(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        unregistered_templates = json.loads(result)
        return unregistered_templates

    def create_template_registration(self, vr_id, template_data):
        """Retrieves template subscription data in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :param template_data: (dict) ID of the template data
        :return: (dict) of template registration data
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/templates/registrations'.format(i=str(vr_id))

        template_registration_content = {
            'templateData': template_data
        }

        # Create JSON content
        try:
            json_content = json.dumps(template_registration_content)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(template_registration_content))
            raise Cons3rtClientError(msg) from exc

        response = self.http_client.http_post(rest_user=self.user, target=target, content_data=json_content)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        template_registration_data = json.loads(result)
        return template_registration_data

    def update_template_registration(self, vr_id, template_registration_id, offline, registration_data=None):
        """Retrieves template subscription data in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :param template_registration_id: (int) ID of the template subscription
        :param offline: (bool) Set True to set the template to offline, False for online
        :param registration_data: (dict) Registration data
        :return: (dict) of template subscription data
        :raises: Cons3rtClientError
        """
        if offline:
            offline_str = 'true'
        else:
            offline_str = 'false'
        if registration_data:
            try:
                json_content = json.dumps(registration_data)
            except SyntaxError as exc:
                msg = 'There was a problem converting data to JSON: {d}'.format(d=str(registration_data))
                raise Cons3rtClientError(msg) from exc
        else:
            json_content = None
        target = 'virtualizationrealms/{i}/templates/registrations/{r}?offline={o}'.format(
            i=str(vr_id), r=str(template_registration_id), o=offline_str)
        response = self.http_client.http_put(rest_user=self.user, target=target, content_data=json_content)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        is_success = json.loads(result)
        return is_success

    def create_template_subscription(self, vr_id, template_registration_id):
        """Creates template subscription in the provided virtualization realm ID using the provided data

        :param vr_id: (int) ID of the virtualization realm
        :param template_registration_id: (int) ID of the template subscription
        :return: (dict) of template subscription data
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/templates/subscriptions?registration_id={r}'.format(
            i=str(vr_id), r=str(template_registration_id))
        response = self.http_client.http_post(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        is_success = json.loads(result)
        return is_success

    def update_template_subscription(self, vr_id, template_subscription_id, offline, subscription_data):
        """Updates template subscription data in the provided virtualization realm ID

        :param vr_id: (int) ID of the virtualization realm
        :param template_subscription_id: (int) ID of the template subscription
        :param offline: (bool) Set True to set the template to offline, False for online
        :param subscription_data: (dict) Subscription data
        :return: (dict) of template subscription data
        :raises: Cons3rtClientError
        """
        if offline:
            offline_str = 'true'
        else:
            offline_str = 'false'
        try:
            json_content = json.dumps(subscription_data)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(subscription_data))
            raise Cons3rtClientError(msg) from exc
        target = 'virtualizationrealms/{i}/templates/subscriptions/{r}?offline={o}'.format(
            i=str(vr_id), r=str(template_subscription_id), o=offline_str)
        response = self.http_client.http_put(rest_user=self.user, target=target, content_data=json_content)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        is_success = json.loads(result)
        return is_success

    def delete_template_registration(self, vr_id, template_registration_id):
        """Unregisters the template registration from the VR ID

        NOTE: This does not support removeSubscriptions=False nor special permissions

        :param vr_id: (int) ID of the virtualization realm
        :param template_registration_id: (int) ID of the template registration
        :return: bool
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{v}/templates/registrations/{t}'.format(
            v=str(vr_id), t=str(template_registration_id)
        )
        request_options = {
            'removeSubscriptions': True
        }
        # Create JSON content
        try:
            json_content = json.dumps(request_options)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(request_options))
            raise Cons3rtClientError(msg) from exc

        response = self.http_client.http_delete(rest_user=self.user, target=target, content=json_content)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return result

    def share_template(self, vr_id, template_registration_id, target_vr_ids):
        """Shares the provided template registration with this provided list
        of target virtualization realm IDs

        :param vr_id: (int) ID of the template provider virtualization realm
        :param template_registration_id: (int) ID of the template registration
        :param target_vr_ids: (list) of IDs (int) of virtualization realms to share with
        :return: bool
        :raises Cons3rtClientError
        """
        target = 'virtualizationrealms/{v}/templates/registrations/{r}/share?'.format(
            v=str(vr_id), r=str(template_registration_id))
        for target_vr_id in target_vr_ids:
            target += '&target_realm_ids={i}'.format(i=str(target_vr_id))
        response = self.http_client.http_post(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return result

    def update_virtualization_realm_reachability(self, vr_id):
        """Updates the virtualization realm's reachability

        :param vr_id: (int) ID of the virtualization realm
        :return: result
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/updatereachability'.format(i=str(vr_id))
        response = self.http_client.http_put(rest_user=self.user, target=target)
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return result

    def release_deployment_run(self, dr_id, force=True):

        # Determine the force option
        force_str = 'false'
        if force:
            force_str = 'true'

        response = self.http_client.http_put(
            rest_user=self.user,
            target='drs/' + str(dr_id) + '/release?force={f}'.format(f=force_str))
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return result

    def run_deployment(self, deployment_id, run_options):

        # Create JSON content
        try:
            json_content = json.dumps(run_options)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(run_options))
            raise Cons3rtClientError(msg) from exc

        response = self.http_client.http_post(
            rest_user=self.user,
            target='deployments/{i}/launch'.format(i=deployment_id),
            content_data=json_content)
        try:
            dr_info = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return dr_info

    def delete_deployment_run(self, dr_id):
        response = self.http_client.http_delete(rest_user=self.user, target='drs/' + str(dr_id))
        result = parse_response(response=response)
        return result

    def set_deployment_run_lock(self, dr_id, lock):
        response = self.http_client.http_put(
            rest_user=self.user,
            target='drs/{i}/setlock?lock={k}'.format(i=str(dr_id), k=str(lock).lower()))
        result = parse_response(response=response)
        return result

    def get_dependent_assets(self, asset_id):
        response = self.http_client.http_get(
            rest_user=self.user,
            target='assets/{i}/dependent'.format(i=str(asset_id))
        )
        result = parse_response(response=response)
        return result

    def delete_asset(self, asset_id, force=False):
        if force:
            force_str = 'true'
        else:
            force_str = 'false'
        response = self.http_client.http_delete(
            rest_user=self.user,
            target='assets/{i}?force={f}'.format(i=str(asset_id), f=force_str)
        )
        result = parse_response(response=response)
        return result

    def deallocate_virtualization_realm(self, cloud_id, vr_id):
        response = self.http_client.http_delete(
            rest_user=self.user,
            target='clouds/' + str(cloud_id) + '/virtualizationrealms/allocate?virtRealmId=' + str(vr_id),
            keep_alive=True
        )
        result = parse_response(response=response)
        return result

    def unregister_virtualization_realm(self, cloud_id, vr_id):
        target = 'clouds/{c}/virtualizationrealms?virtRealmId={v}'.format(c=str(cloud_id), v=str(vr_id))
        response = self.http_client.http_delete(rest_user=self.user, target=target, keep_alive=True)
        result = parse_response(response=response)
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
                target='assets/' + str(asset_id) + '/updatecontent/',
                content_file=asset_zip_file
            )
        except Cons3rtClientError as exc:
            msg = 'Unable to update asset ID {i} with asset zip file: {f}'.format(i=asset_id, f=asset_zip_file)
            raise Cons3rtClientError(msg) from exc
        try:
            parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc

    def update_asset_state(self, asset_id, state):
        """Updates the asset state for the provided asset ID

        :param asset_id: (int) asset ID to update
        :param state: (str) desired asset state
        :return: None
        :raises: Cons3rtClientError
        """
        try:
            response = self.http_client.http_put(
                rest_user=self.user,
                target='assets/{i}/updatestate?state={s}'.format(i=str(asset_id), s=state))
        except Cons3rtClientError as exc:
            msg = 'Unable to set asset state for asset ID: {i}'.format(i=str(asset_id))
            raise Cons3rtClientError(msg) from exc
        try:
            parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc

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
            parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc

    def update_asset_visibility(self, asset_id, visibility):
        """Updates the asset visibility for the provided asset ID

        :param asset_id: (int) asset ID to update
        :param visibility: (str) desired asset visibility
        :return: None
        :raises: Cons3rtClientError
        """
        try:
            response = self.http_client.http_put(
                rest_user=self.user,
                target='assets/{i}/updatevisibility?visibility={s}'.format(i=str(asset_id), s=visibility))
        except Cons3rtClientError as exc:
            msg = 'Unable to set asset visibility for asset ID: {i}'.format(i=str(asset_id))
            raise Cons3rtClientError(msg) from exc
        try:
            parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc

    def import_asset(self, asset_zip_file):
        """Imports a new asset from the asset zip file

        :param asset_zip_file: (str) path to the asset zip file
        :return: (int) software asset ID
        :raises: Cons3rtClientError
        """
        try:
            response = self.http_client.http_post_multipart(
                rest_user=self.user,
                target='import/',
                content_file=asset_zip_file,
            )
        except Cons3rtClientError as exc:
            msg = 'Unable to import asset from zip file: {f}'.format(f=asset_zip_file)
            raise Cons3rtClientError(msg) from exc
        try:
            asset_id = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        return asset_id

    def add_virtualization_realm_service(self, vr_id, service_content):
        """Add a virtualization realm service using the provided content

        :param vr_id: (int) Virtualization Realm ID
        :param service_content: (dict) Content for the new service
        :return:
        """
        target = 'virtualizationrealms/{i}/service'.format(i=str(vr_id))
        response = self.http_client.http_post(rest_user=self.user, target=target, content_data=service_content)
        content = parse_response(response=response)
        vr_service = json.loads(content)
        return vr_service

    def retrieve_virtualization_realm_service(self, vr_id, service_id):
        """Retrieves the virtualization realm service

        :param vr_id: (int) Virtualization Realm ID
        :param service_id: (int) Service ID
        :return: None
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/service/{s}'.format(i=str(vr_id), s=str(service_id))
        response = self.http_client.http_get(rest_user=self.user, target=target)
        content = parse_response(response=response)
        vr_service = json.loads(content)
        return vr_service

    def update_virtualization_realm_service(self, vr_id, service_id, service_content):
        """Add a virtualization realm service using the provided content

        :param vr_id: (int) Virtualization Realm ID
        :param service_id: (int) Service ID
        :param service_content: (dict) Content for the updated service
        :return:
        """
        target = 'virtualizationrealms/{i}/service/{s}'.format(i=str(vr_id), s=str(service_id))
        response = self.http_client.http_put(rest_user=self.user, target=target, content_data=service_content)
        content = parse_response(response=response)
        vr_service = json.loads(content)
        return vr_service

    def update_virtualization_realm_service_state(self, vr_id, service_id, state):
        """Updates the state of the virtualization realm service

        :param vr_id: (int) Virtualization Realm ID
        :param service_id: (int) Service ID
        :param state: (str) enable/disable
        :return: None
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/service/{s}/state?state={t}'.format(i=str(vr_id), s=str(service_id), t=state)
        response = self.http_client.http_put(rest_user=self.user, target=target)
        parse_response(response=response)

    def remove_virtualization_realm_service(self, vr_id, service_id):
        """Removes the service from the virtualization realm

        :param vr_id: (int) Virtualization Realm ID
        :param service_id: (int) Service ID
        :return: None
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}/service/{s}'.format(i=str(vr_id), s=str(service_id))
        response = self.http_client.http_delete(rest_user=self.user, target=target)
        parse_response(response=response)

    def update_virtualization_realm_access_point(self, vr_id, access_point_ip):
        """Updates the access point for a virtualization realm

        :param vr_id: (int) Virtualization Realm ID
        :param access_point_ip: (str) Access point IP address
        :return: None
        :raises: Cons3rtClientError
        """
        target = 'virtualizationrealms/{i}'.format(i=str(vr_id))
        content = {
            'accessPoint': access_point_ip,

        }
        response = self.http_client.http_put(rest_user=self.user, target=target, content_data=content)
        parse_response(response=response)

    def list_users(self, state=None, created_before=None, created_after=None, max_results=500):
        """Query CONS3RT to list site users

        :param state: (state) user state "REQUESTED" "ACTIVE" "INACTIVE"
        :param created_before: (int) Date (seconds since epoch) to filter on
        :param created_after: (int) Date (seconds since epoch) to filter on
        :param max_results: (int) maximum results to return per page
        :return: (list) Containing all site users
        :raises: Cons3rtClientError
        """
        users = []
        page_num = 0
        params = ''
        if state:
            if state not in ['REQUESTED', 'ACTIVE', 'INACTIVE']:
                msg = 'Invalid state, must be REQUESTED, ACTIVE, or INACTIVE: {s}'.format(s=state)
                raise Cons3rtClientError(msg)
            params += '&state={s}'.format(s=state)
        if created_before:
            params += '&createdbefore={t}'.format(t=str(created_before))
        if created_after:
            params += '&createdafter={t}'.format(t=str(created_after))
        params += '&maxresults={m}'.format(m=str(max_results))
        base_target = '/admin/users?' + params.lstrip('&')
        while True:
            print('Retrieving users: page {p}'.format(p=str(page_num)))
            target = base_target + '&page={p}'.format(p=str(page_num))
            try:
                response = self.http_client.http_get(
                    rest_user=self.user,
                    target=target
                )
            except Cons3rtClientError as exc:
                msg = 'The HTTP response contains a bad status code'
                raise Cons3rtClientError(msg) from exc
            result = parse_response(response=response)
            found_users = json.loads(result)
            users += found_users
            if len(found_users) < 100:
                break
            else:
                page_num += 1
            print('Found {n} users...'.format(n=str(len(users))))
        return users

    def list_all_users(self):
        """Query CONS3RT to retrieve all site users

        :return: (list) Containing all site users
        :raises: Cons3rtClientError
        """
        return self.list_users()

    def retrieve_all_users(self):
        """Query CONS3RT to retrieve all site users

        :return: (list) Containing all site users
        :raises: Cons3rtClientError
        """
        return self.list_users()

    def retrieve_container_asset(self, asset_id):
        """Retrieves details for the container asset

        :param asset_id: (int) asset ID
        :return: (dict) details about the container asset
        :raises: Cons3rtClientError
        """
        target = 'containers/{i}'.format(i=str(asset_id))
        try:
            response = self.http_client.http_get(
                rest_user=self.user,
                target=target
            )
        except Cons3rtClientError as exc:
            raise Cons3rtClientError('Problem retrieving container asset: {i}'.format(i=str(asset_id))) from exc
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        software_asset = json.loads(result)
        return software_asset

    def retrieve_software_asset(self, asset_id):
        """Retrieves details for the software asset

        :param asset_id: (int) asset ID
        :return: (dict) details about the software asset
        :raises: Cons3rtClientError
        """
        target = 'software/{i}'.format(i=str(asset_id))
        try:
            response = self.http_client.http_get(
                rest_user=self.user,
                target=target
            )
        except Cons3rtClientError as exc:
            raise Cons3rtClientError('Problem retrieving software asset: {i}'.format(i=str(asset_id))) from exc
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        software_asset = json.loads(result)
        return software_asset

    def retrieve_software_assets(self, software_asset_type=None, community=False, category_ids=None, expanded=False,
                                 max_results=40, page_num=0):
        """Get a list of software assets

        :param software_asset_type: (str) the software asset type, defaults to null
        :param community: (bool) the boolean to include community assets
        :param category_ids: (list) the list of categories to filter by
        :param expanded: (bool) whether to retrieve expanded info
        :param max_results: (int) the max number of results desired
        :param page_num: (int) the page number requested
        :return: List of software asset IDs
        """
        if expanded:
            target = 'software/expanded?'
        else:
            target = 'software?'
        target = get_asset_target(target=target, page_num=page_num, software_asset_type=software_asset_type,
                                  community=community, category_ids=category_ids, max_results=max_results)
        try:
            response = self.http_client.http_get(
                rest_user=self.user,
                target=target
            )
        except Cons3rtClientError as exc:
            raise Cons3rtClientError('Problem querying for software assets') from exc
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        software_assets = json.loads(result)
        return software_assets

    def retrieve_all_software_assets(self, software_asset_type=None, community=False, category_ids=None, expanded=False,
                                     max_results=None):
        """Get a list of software assets with expanded info

        :param software_asset_type: (str) the software asset type, defaults to null
        :param community: (bool) the boolean to include community assets
        :param category_ids: (list) the list of categories to filter by
        :param expanded: (bool) whether to retrieve expanded info
        :param max_results: (int) maximum number of results to return
        :return: List of software asset IDs
        :raises: Cons3rtClientError
        """
        software_assets = []
        page_num = 0
        max_results_per_page = 40
        while True:
            try:
                print('Retrieving software assets: page {p}'.format(p=str(page_num)))
                software_assets_page = self.retrieve_software_assets(
                    software_asset_type=software_asset_type,
                    community=community,
                    category_ids=category_ids,
                    expanded=expanded,
                    max_results=max_results_per_page,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'Problem querying software assets on page: {n}'.format(n=str(page_num))
                raise Cons3rtClientError(msg) from exc
            software_assets += software_assets_page
            if len(software_assets_page) < max_results_per_page:
                break
            if max_results:
                if len(software_assets) >= max_results:
                    break
            page_num += 1
            print('Found {n} software assets...'.format(n=str(len(software_assets))))
        if max_results:
            if len(software_assets) > max_results:
                software_assets = software_assets[:max_results]
        print('Retrieved a total of {n} software assets'.format(n=str(len(software_assets))))
        return software_assets

    def retrieve_test_asset(self, asset_id):
        """Retrieves details for the test asset

        :param asset_id: (int) asset ID
        :return: (dict) details about the test asset
        :raises: Cons3rtClientError
        """
        target = 'testassets/{i}'.format(i=str(asset_id))
        try:
            response = self.http_client.http_get(
                rest_user=self.user,
                target=target
            )
        except Cons3rtClientError as exc:
            raise Cons3rtClientError('Problem retrieving test asset: {i}'.format(i=str(asset_id))) from exc
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        test_asset = json.loads(result)
        return test_asset

    def retrieve_test_assets(self, test_asset_type=None, community=False, category_ids=None, expanded=False,
                             max_results=40, page_num=0):
        """Get a list of test assets

        :param test_asset_type: (str) the test asset type, defaults to null: "UNKNOWN" "NESSUS" "SCRIPT" "POWERSHELL" "MOCK"
        :param community: (bool) the boolean to include community assets
        :param category_ids: (list) the list of categories to filter by
        :param expanded: (bool) whether to retrieve expanded info
        :param max_results: (int) the max number of results desired
        :param page_num: (int) the page number requested
        :return: List of test asset IDs
        """
        if expanded:
            target = 'testassets/expanded?'
        else:
            target = 'testassets?'
        target = get_asset_target(target=target, test_asset_type=test_asset_type, page_num=page_num,
                                  community=community, category_ids=category_ids, max_results=max_results)

        try:
            response = self.http_client.http_get(
                rest_user=self.user,
                target=target
            )
        except Cons3rtClientError as exc:
            raise Cons3rtClientError('Problem querying for test assets') from exc
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        test_assets = json.loads(result)
        return test_assets

    def retrieve_all_test_assets(self, test_asset_type=None, community=False, category_ids=None, expanded=False,
                                 max_results=None):
        """Get a list of test assets with expanded info

        :param test_asset_type: (str) the test asset type, defaults to null
        :param community: (bool) the boolean to include community assets
        :param category_ids: (list) the list of categories to filter by
        :param expanded: (bool) whether to retrieve expanded info
        :param max_results: (int) maximum number of results to return
        :return: List of test asset IDs
        :raises: Cons3rtClientError
        """
        test_assets = []
        page_num = 0
        max_results_per_page = 40
        while True:
            try:
                print('Retrieving test assets: page {p}'.format(p=str(page_num)))
                test_assets_page = self.retrieve_test_assets(
                    test_asset_type=test_asset_type,
                    community=community,
                    category_ids=category_ids,
                    expanded=expanded,
                    max_results=max_results_per_page,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'Problem querying software assets on page: {n}'.format(n=str(page_num))
                raise Cons3rtClientError(msg) from exc
            test_assets += test_assets_page
            if len(test_assets_page) < max_results_per_page:
                break
            if max_results:
                if len(test_assets) >= max_results:
                    break
            page_num += 1
            print('Found {n} test assets...'.format(n=str(len(test_assets))))
        if max_results:
            if len(test_assets) > max_results:
                test_assets = test_assets[:max_results]
        print('Retrieved a total of {n} test assets'.format(n=str(len(test_assets))))
        return test_assets

    def retrieve_container_assets(self, community=False, category_ids=None, expanded=False, max_results=40, page_num=0):
        """Get a list of container assets

        :param community: (bool) the boolean to include community assets
        :param category_ids: (list) the list of categories to filter by
        :param expanded: (bool) whether to retrieve expanded info
        :param max_results: (int) the max number of results desired
        :param page_num: (int) the page number requested
        :return: List of container asset IDs
        :raises: Cons3rtClientError
        """
        if expanded:
            target = 'containers/expanded?'
        else:
            target = 'containers?'
        target = get_asset_target(
            target=target, page_num=page_num, community=community, category_ids=category_ids, max_results=max_results)
        try:
            response = self.http_client.http_get(
                rest_user=self.user,
                target=target
            )
        except Cons3rtClientError as exc:
            raise Cons3rtClientError('Problem querying for container assets') from exc
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        container_assets = json.loads(result)
        return container_assets

    def retrieve_all_container_assets(self, community=False, category_ids=None, expanded=False, max_results=None):
        """Get a list of container assets with expanded info

        :param community: (bool) the boolean to include community assets
        :param category_ids: (list) the list of categories to filter by
        :param expanded: (bool) whether to retrieve expanded info
        :param max_results: (int) maximum number of results to return
        :return: List of container asset IDs
        :raises: Cons3rtClientError
        """
        container_assets = []
        page_num = 0
        max_results_per_page = 40
        while True:
            try:
                print('Retrieving container assets: page {p}'.format(p=str(page_num)))
                container_asset_page = self.retrieve_container_assets(
                    community=community,
                    category_ids=category_ids,
                    expanded=expanded,
                    max_results=max_results_per_page,
                    page_num=page_num
                )
            except Cons3rtClientError as exc:
                msg = 'Problem querying container assets on page: {n}'.format(n=str(page_num))
                raise Cons3rtClientError(msg) from exc
            container_assets += container_asset_page
            if len(container_asset_page) < max_results_per_page:
                break
            if max_results:
                if len(container_assets) >= max_results:
                    break
            page_num += 1
            print('Found {n} container assets...'.format(n=str(len(container_assets))))
        if max_results:
            if len(container_assets) > max_results:
                container_assets = container_assets[:max_results]
        print('Retrieved a total of {n} container assets'.format(n=str(len(container_assets))))
        return container_assets

    def retrieve_asset_categories(self):
        """Retrieves a list of the asset categories in the site

        :return: (list) of asset categories
        """
        try:
            response = self.http_client.http_get(rest_user=self.user, target='categories')
        except Cons3rtClientError as exc:
            raise Cons3rtClientError('Problem retrieving a list of categories') from exc
        try:
            result = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        categories = json.loads(result)
        return categories

    def add_category_to_asset(self, asset_id, category_id):
        """Adds the category ID to the asset ID

        :param asset_id: (int) asset ID
        :param category_id: (int) category ID
        :return: None
        :raises: Cons3rtClientError
        """
        target = 'categories/{c}/asset/?assetid={a}'.format(c=str(category_id), a=str(asset_id))

        # Add the user to the project
        try:
            response = self.http_client.http_put(rest_user=self.user, target=target)
        except Cons3rtClientError as exc:
            msg = 'Unable to add category ID {c} to asset ID: {a}'.format(c=str(category_id), a=str(asset_id))
            raise Cons3rtClientError(msg) from exc

        # Check the response
        try:
            parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc

    def remove_category_from_asset(self, asset_id, category_id):
        """Removes the category ID from the asset ID

        :param asset_id: (int) asset ID
        :param category_id: (int) category ID
        :return: None
        :raises: Cons3rtClientError
        """
        target = 'categories/{c}/asset/?assetid={a}'.format(c=str(category_id), a=str(asset_id))

        # Add the user to the project
        try:
            response = self.http_client.http_delete(rest_user=self.user, target=target)
        except Cons3rtClientError as exc:
            msg = 'Unable to remove category ID {c} to asset ID: {a}'.format(c=str(category_id), a=str(asset_id))
            raise Cons3rtClientError(msg) from exc

        # Check the response
        try:
            parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc

    def download_asset(self, asset_id, download_file, background=False, overwrite=True, suppress_status=True):
        """Requests download of the asset ID

        :param asset_id: (int) asset ID
        :param download_file: (str) path to the destination file
        :param background: (bool) set True to download in the background and receive an email when ready
        :param overwrite (bool) set True to overwrite the existing file
        :param suppress_status: (bool) Set to True to suppress printing download status
        :return: (str) path to the downloaded asset zip
        :raises: Cons3rtClientError
        """
        target = 'assets/{i}/download'.format(i=str(asset_id))
        if background:
            target += '?background=true'
        else:
            target += '?background=false'
        try:
            asset_zip = self.http_client.http_download(rest_user=self.user, target=target, download_file=download_file,
                                                       overwrite=overwrite, suppress_status=suppress_status)
        except Cons3rtClientError as exc:
            msg = 'Problem downloading asset ID: {a}'.format(a=str(asset_id))
            raise Cons3rtClientError(msg) from exc
        return asset_zip

    def perform_host_action(self, dr_id, dr_host_id, action, cpu=None, ram=None):
        """Performs the provided host action on the host ID

        :param dr_id: (int) ID of the deployment run
        :param dr_host_id: (int) ID of the deployment run host
        :param action: (str) host action to perform
        :param cpu: (int) number of CPUs if the action, if the action is resize
        :param ram: (int) amount of ram in megabytes if the action is resize
        :return: None
        :raises Cons3rtClientError
        """
        target = 'drs/{i}/hostaction?deploymentrunhostid={r}&action={a}'.format(
            i=str(dr_id), r=dr_host_id, a=action)
        if action == 'RESIZE':
            if not cpu:
                raise Cons3rtClientError('Action RESIZE must include a value for cpu')
            if not ram:
                raise Cons3rtClientError('Action RESIZE must include a value for ram')
            target += '&cpu={c}&ram={r}'.format(c=str(cpu), r=str(ram))
        try:
            response = self.http_client.http_put(rest_user=self.user, target=target)
        except Cons3rtClientError as exc:
            msg = 'Problem performing host action {a} on DR {i} host {h}: {e}'.format(
                a=action, i=str(dr_id), h=str(dr_host_id), e=str(exc))
            raise Cons3rtClientError(msg) from exc
        # Check the response
        try:
            parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc

    def create_host_identity(self, dr_id, host_id, service_list):
        """Creates an identity on the provided DR host to the provided service

        :param dr_id: (str) deployment run ID
        :param host_id: (str) deployment run host ID
        :param service_list: (list) os services to connect to including:
                type: (str) type of service "BUCKET"
                name: (str) name of the service
                identifier: (str) ID of the service to connect to
        :return: (list) of identities (see: /reference/api/index.html#operation/createIdentity)
        :raises: Cons3rtClientError
        """
        target = 'drs/{d}/host/{h}/identity'.format(d=str(dr_id), h=str(host_id))

        # Create JSON content
        try:
            json_content = json.dumps(service_list)
        except SyntaxError as exc:
            msg = 'There was a problem converting data to JSON: {d}'.format(d=str(service_list))
            raise Cons3rtClientError(msg) from exc

        try:
            response = self.http_client.http_post(rest_user=self.user, target=target, content_data=json_content)
        except Cons3rtClientError as exc:
            msg = 'Problem generating an identity on deployment run [{d}] host [{h}]: {e}'.format(
                d=str(dr_id), h=str(host_id), e=str(exc))
            raise Cons3rtClientError(msg) from exc
        # Check the response
        try:
            content = parse_response(response=response)
        except Cons3rtClientError as exc:
            raise Cons3rtClientError(str(exc)) from exc
        identity = json.loads(content)
        return identity

    def download_rdp_file(self, dr_id, host_id, download_file, background=False, overwrite=True,
                               suppress_status=True):
        """Creates an identity on the provided DR host to the provided service

        :param dr_id: (str) ID of the deployment run
        :param host_id: (str) ID of the deployment run host
        :param download_file: (str) path to the destination file
        :param background: (bool) set True to download in the background and receive an email when ready
        :param overwrite (bool) set True to overwrite the existing file
        :param suppress_status: (bool) Set to True to suppress printing download status
        :return: (str) Downloaded file path
        :raises: Cons3rtClientError
        """
        target = 'drs/{d}/host/{h}/rdp'.format(d=str(dr_id), h=str(host_id))
        try:
            rdp_file_path = self.http_client.http_download(rest_user=self.user, target=target,
                                                           download_file=download_file, overwrite=overwrite,
                                                           suppress_status=suppress_status)
        except Cons3rtClientError as exc:
            msg = 'Problem downloading an RDP file for deployment run [{d}] host [{h}]: {e}'.format(
                d=str(dr_id), h=str(host_id), e=str(exc))
            raise Cons3rtClientError(msg) from exc
        return rdp_file_path


def get_asset_target(target, page_num, asset_type=None, software_asset_type=None, test_asset_type=None, community=None,
                     category_ids=None, max_results=100):
    """Given an asset target URL portion, append provided parameters

    :param target: (str) URL target base portion
    :param page_num: (int) page number for the query
    :param asset_type: (str) type of asset for systems
    :param software_asset_type: (str) type of software asset
    :param test_asset_type: (str) type of test asset
    :param community: (bool) set true to include community assets
    :param category_ids: (list) of (int) IDs for categories to include in the query
    :param max_results: (int) maximum number of results to return
    :return: (str) target string
    """
    if software_asset_type:
        target += 'softwareType={t}&'.format(t=software_asset_type)
    elif test_asset_type:
        target += 'testAssetType={t}&'.format(t=test_asset_type)
    elif asset_type:
        target += 'type={t}&'.format(t=asset_type)
    if community:
        target += 'community=true'
    else:
        target += 'community=false'
    if category_ids:
        for category_id in category_ids:
            target += '&categoryids={c}'.format(c=str(category_id))
    target += '&maxresults={m}&page={p}'.format(m=str(max_results), p=str(page_num))
    return target
