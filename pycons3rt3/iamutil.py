"""Module: iamutil

This module provides utilities for interacting AWS IAM

"""
import json
import logging
import os
from datetime import datetime

from botocore.client import ClientError

from .awsutil import get_boto3_client
from .exceptions import IamUtilError
from .logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.iamutil'


############################################################################
# Methods for attaching policies
############################################################################


def attach_policy_to_group(client, group_name, policy_arn):
    """Attach the policy to the group

    :param client: boto3.client object
    :param group_name: (str) name of the role
    :param policy_arn: (str) ARN of the policy
    :return: None
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.attach_policy_to_group')
    log.info('Attaching policy [{p}] to group: [{r}]'.format(p=policy_arn, r=group_name))
    try:
        client.attach_group_policy(
            GroupName=group_name,
            PolicyArn=policy_arn
        )
    except ClientError as exc:
        msg = 'Problem attaching policy [{p}] to group [{r}]'.format(p=policy_arn, r=group_name)
        raise IamUtilError(msg) from exc


def attach_policy_to_role(client, role_name, policy_arn):
    """Attach the policy to the role

    :param client: boto3.client object
    :param role_name: (str) name of the role
    :param policy_arn: (str) ARN of the policy
    :return: None
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.attach_policy_to_role')
    log.info('Attaching policy [{p}] to role: [{r}]'.format(p=policy_arn, r=role_name))
    try:
        client.attach_role_policy(
            RoleName=role_name,
            PolicyArn=policy_arn
        )
    except ClientError as exc:
        msg = 'Problem attaching policy [{p}] to role [{r}]'.format(p=policy_arn, r=role_name)
        raise IamUtilError(msg) from exc


############################################################################
# Methods for creating groups
############################################################################


def create_group(client, group_name, path='/'):
    """Creates the specified group, if it already exists returns it

    :param client: boto3.client object
    :param group_name: (str) group name
    :param path: (str) path to the group
    :return: (dict) group data (specified in boto3)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.create_group')
    log.info('Attempting to create group [{n}]'.format(n=group_name))

    # Checking for existing group
    group_data = None
    existing_groups = list_groups(client=client, path_prefix=path)
    for existing_group in existing_groups:
        if 'GroupName' not in existing_group.keys():
            log.warning('GroupName not found in group: {r}'.format(r=str(existing_group)))
            continue
        if 'Path' not in existing_group.keys():
            log.warning('Path not found in group: {r}'.format(r=str(existing_group)))
            continue
        if 'Arn' not in existing_group.keys():
            log.warning('Arn not found in group: {r}'.format(r=str(existing_group)))
            continue
        if group_name == existing_group['GroupName'] and path == existing_group['Path']:
            group_data = existing_group

    if group_data:
        log.info('Found existing group name [{n}] at path [{p}]'.format(n=group_name, p=path))
        return group_data
    log.info('Attempting to create group [{n}]'.format(n=group_name))
    try:
        response = client.create_group(
            GroupName=group_name,
            Path=path
        )
    except ClientError as exc:
        msg = 'Problem creating group [{n}]'.format(n=group_name)
        raise IamUtilError(msg) from exc
    if 'Group' not in response.keys():
        msg = 'Group not found in response: {d}'.format(d=str(response))
        raise IamUtilError(msg)
    log.info('Created new group: [{n}]'.format(n=group_name))
    return response['Group']


############################################################################
# Methods for creating policies
############################################################################


def create_default_policy_version(client, policy_arn, json_policy_data):
    """Creates a policy version and sets it as the default

    :param client: boto3.client object
    :param policy_arn: (str) ARN of the policy
    :param json_policy_data: URL-encoded JSON string policy document
    :return: (dict) policy version data (see boto3 docs)
    :raises: IamUtilError
    """
    try:
        response = client.create_policy_version(
            PolicyArn=policy_arn,
            PolicyDocument=json_policy_data,
            SetAsDefault=True
        )
    except ClientError as exc:
        msg = 'Problem creating default policy for [{p}]'.format(p=policy_arn)
        raise IamUtilError(msg) from exc
    if 'PolicyVersion' not in response.keys():
        msg = 'PolicyVersion not found in response: {r}'.format(r=str(response))
        raise IamUtilError(msg)
    return response['PolicyVersion']


def create_or_update_policy(client, policy_name, policy_document, path='/', description=''):
    """
    Creates the specified policy, if it already exists updates it with a new version

    Permissions boundary ARN not supported yet.

    :param client: boto3.client object
    :param policy_name: (str) policy name
    :param policy_document: (str) path to JSON policy file
    :param path: (str) path to the policy
    :param description: (str) description of the policy
    :return: (dict) role data (specified in boto3)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.create_or_update_policy')
    log.info('Attempting to create/update policy [{n}] with policy document: {p}'.format(
        n=policy_name, p=policy_document))

    # Ensure the file exists
    if not os.path.isfile(policy_document):
        raise IamUtilError('Policy document not found: {f}'.format(f=policy_document))
    try:
        with open(policy_document, 'r') as f:
            policy_document_data = json.load(f)
    except(OSError, IOError) as exc:
        raise IamUtilError('Unable to read policy file: {f}'.format(f=policy_document)) from exc
    log.info('Loading policy from file: {f}'.format(f=policy_document))
    json_policy_data = json.dumps(policy_document_data)

    # Checking for existing policy
    policy_data = None
    existing_policies = list_policies(client=client, path_prefix=path)
    for existing_policy in existing_policies:
        if 'PolicyName' not in existing_policy.keys():
            log.warning('PolicyName not found in policy: {r}'.format(r=str(existing_policy)))
            continue
        if 'Path' not in existing_policy.keys():
            log.warning('Path not found in policy: {r}'.format(r=str(existing_policy)))
            continue
        if 'Arn' not in existing_policy.keys():
            log.warning('Arn not found in policy: {r}'.format(r=str(existing_policy)))
            continue
        if policy_name == existing_policy['PolicyName'] and path == existing_policy['Path']:
            policy_data = existing_policy

    if policy_data:
        log.info('Found existing policy name [{n}] at path [{p}]'.format(n=policy_name, p=path))
        log.info('Updating policy with a new version...')
        delete_oldest_policy_version(client=client, policy_arn=policy_data['Arn'])
        create_default_policy_version(client=client, policy_arn=policy_data['Arn'], json_policy_data=json_policy_data)
        log.info('Completed updating existing policy: [{n}]'.format(n=policy_name))
        return policy_data
    log.info('Attempting to create policy [{n}] with policy document: {p}'.format(n=policy_name, p=policy_document))
    try:
        response = client.create_policy(
            PolicyName=policy_name,
            Path=path,
            PolicyDocument=json_policy_data,
            Description=description
        )
    except ClientError as exc:
        msg = 'Problem creating policy [{n}] with policy document: {p}'.format(n=policy_name, p=policy_document)
        raise IamUtilError(msg) from exc
    if 'Policy' not in response.keys():
        msg = 'Policy not found in response: {d}'.format(d=str(response))
        raise IamUtilError(msg)
    log.info('Created new policy: [{n}]'.format(n=policy_name))
    return response['Policy']


def create_policy(client, policy_name, policy_document, path='/', description=''):
    """
    Creates the specified policy, if it already exists updates it with a new version

    Permissions boundary ARN not supported yet.

    :param client: boto3.client object
    :param policy_name: (str) policy name
    :param policy_document: (str) path to JSON policy file
    :param path: (str) path to the policy
    :param description: (str) description of the policy
    :return: (dict) role data (specified in boto3)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.create_policy')
    log.info('Attempting to create policy [{n}] with policy document: {p}'.format(
        n=policy_name, p=policy_document))
    return create_or_update_policy(client=client, policy_name=policy_name, policy_document=policy_document, path=path,
                                   description=description)


############################################################################
# Methods for creating roles
############################################################################


def create_role(client, role_name, role_policy, path='/', description='', max_session_duration_sec=43200):
    """
    Creates the specified role, if it already exists updates it

    Permissions boundary ARN not supported yet.

    :param client: boto3.client object
    :param role_name: (str) role name
    :param role_policy: (str) path to JSON policy file
    :param path: (str) path to the role
    :param description: (str) description of the role
    :param max_session_duration_sec: (int) Number of seconds each session is valid for
    :return: (dict) role data (specified in boto3)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.create_role')
    log.info('Attempting to create role [{n}] with policy: {p}'.format(n=role_name, p=role_policy))
    return create_or_update_role(client=client, role_name=role_name, role_policy=role_policy, path=path,
                                 description=description, max_session_duration_sec=max_session_duration_sec)


def create_or_update_role(client, role_name, role_policy, path='/', description='', max_session_duration_sec=43200):
    """
    Creates the specified role, if it already exists updates it

    Permissions boundary ARN not supported yet.

    :param client: boto3.client object
    :param role_name: (str) role name
    :param role_policy: (str) path to JSON policy file
    :param path: (str) path to the role
    :param description: (str) description of the role
    :param max_session_duration_sec: (int) Number of seconds each session is valid for
    :return: (dict) role data (specified in boto3)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.create_or_update_role')
    log.info('Attempting to create role [{n}] with policy: {p}'.format(n=role_name, p=role_policy))

    # Ensure the file_path file exists
    if not os.path.isfile(role_policy):
        raise IamUtilError('Role policy file not found: {f}'.format(f=role_policy))
    try:
        with open(role_policy, 'r') as f:
            role_policy_data = json.load(f)
    except(OSError, IOError) as exc:
        raise IamUtilError('Unable to read policy file: {f}'.format(f=role_policy)) from exc
    log.info('Loading policy from file: {f}'.format(f=role_policy))
    json_role_policy_data = json.dumps(role_policy_data)

    # Checking for existing role
    role_data = None
    existing_roles = list_roles(client=client, path_prefix=path)
    for existing_role in existing_roles:
        if 'RoleName' not in existing_role.keys():
            log.warning('RoleName not found in role: {r}'.format(r=str(existing_role)))
            continue
        if 'Path' not in existing_role.keys():
            log.warning('Path not found in role: {r}'.format(r=str(existing_role)))
            continue
        if role_name == existing_role['RoleName'] and path == existing_role['Path']:
            role_data = existing_role

    if role_data:
        log.info('Found existing role name [{n}] at path [{p}]'.format(n=role_name, p=path))
        log.info('Updating role policy...')
        update_role_trust_policy(client=client, role_name=role_name, role_policy=role_policy)
        update_role_description_and_session(client=client, role_name=role_name, description=description,
                                            max_session_duration_sec=max_session_duration_sec)
        return role_data
    log.info('Attempting to create role [{n}] with policy: {p}'.format(n=role_name, p=role_policy))
    try:
        response = client.create_role(
            AssumeRolePolicyDocument=json_role_policy_data,
            Path=path,
            RoleName=role_name,
            Description=description,
            MaxSessionDuration=max_session_duration_sec
        )
    except ClientError as exc:
        msg = 'Problem creating role [{n}] with policy: {p}'.format(n=role_name, p=role_policy)
        raise IamUtilError(msg) from exc
    if 'Role' not in response.keys():
        msg = 'Role not found in response: {d}'.format(d=str(response))
        raise IamUtilError(msg)
    return response['Role']


############################################################################
# Delete policies
############################################################################


def delete_oldest_policy_version(client, policy_arn):
    """Finds and deletes the oldest policy version if there are 5

    :param client: boto3.client object
    :param policy_arn: (str) ARN of the policy to update
    :return: None
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.delete_oldest_policy_version')

    # List policy versions
    policy_versions = list_policy_versions(client=client, policy_arn=policy_arn)

    # Exit if less than 5 policy versions exist
    if len(policy_versions) < 5:
        log.info('Less that 5 policy versions found, nothing needs to be deleted')
        return

    # Find the oldest policy
    oldest_policy_date = None
    oldest_version_id = None
    for policy_version in policy_versions:
        if 'VersionId' not in policy_version:
            log.warning('VersionId not found in policy version: {v}'.format(v=str(policy_version)))
            continue
        if 'CreateDate' not in policy_version:
            log.warning('CreateDate not found in policy version: {v}'.format(v=str(policy_version)))
            continue
        if not oldest_policy_date:
            oldest_policy_date = policy_version['CreateDate']
        elif policy_version['CreateDate'] < oldest_policy_date:
            oldest_policy_date = policy_version['CreateDate']
            oldest_version_id = policy_version['VersionId']

    # Raise an error if the oldest policy ID was not found
    if not oldest_version_id:
        msg = 'Unable to determine the version ID of the oldest policy for: [{p}]'.format(p=policy_arn)
        raise IamUtilError(msg)

    log.info('Deleting oldest policy version ID [{v}] from policy [{p}]'.format(v=oldest_version_id, p=policy_arn))
    try:
        client.delete_policy_version(
            PolicyArn=policy_arn,
            VersionId=oldest_version_id
        )
    except ClientError as exc:
        msg = 'Problem deleting policy verison [{v}] from policy: [{p}]'.format(v=oldest_version_id, p=policy_arn)
        raise IamUtilError(msg) from exc


############################################################################
# Getting a boto3 client object for IAM
############################################################################


def get_iam_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
    """Gets an IAM client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    return get_boto3_client(service='iam', region_name=region_name, aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)


############################################################################
# Methods for listing groups
############################################################################


def list_groups_with_marker(client, path_prefix='/', marker=None, max_results=100):
    """Returns a list of IAM groups using the provided marker

    :param client: boto3.client object
    :param path_prefix: (str) IAM group path prefix
    :param max_results: (int) max results to query on
    :param marker: (str) token to query on
    :return: (dict) response object containing response data
    """
    if marker:
        return client.list_groups(
            PathPrefix=path_prefix,
            Marker=marker,
            MaxItems=max_results
        )
    else:
        return client.list_groups(
            PathPrefix=path_prefix,
            MaxItems=max_results
        )


def list_groups(client, path_prefix='/'):
    """Lists groups in IAM

    :param client: boto3.client object
    :param path_prefix: (str) IAM group path prefix
    :return: (list) of groups (dict)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.list_groups')
    marker = None
    next_query = True
    group_list = []
    log.info('Attempting to list IAM groups...')
    while True:
        if not next_query:
            break
        response = list_groups_with_marker(client=client, path_prefix=path_prefix, marker=marker)
        if 'IsTruncated' not in response.keys():
            log.warning('IsTruncated not found in response: {r}'.format(r=str(response)))
            return group_list
        if 'Groups' not in response.keys():
            log.warning('Groups not found in response: {r}'.format(r=str(response)))
            return group_list
        next_query = response['IsTruncated']
        group_list += response['Groups']
        if 'Marker' not in response.keys():
            next_query = False
        else:
            marker = response['Marker']
    log.info('Found {n} IAM groups'.format(n=str(len(group_list))))
    return group_list


############################################################################
# Methods for listing policies
############################################################################


def list_policies_with_marker(client, scope='Local', only_attached=False, path_prefix='/',
                              policy_usage_filter='PermissionsPolicy', marker=None, max_results=100):
    """Returns a list of IAM policies using the provided marker

    :param client: boto3.client object
    :param scope: (str) All | AWS | Local
    :param only_attached: (bool) Set True to return only attached policies
    :param path_prefix: (str) IAM policy path prefix
    :param policy_usage_filter: (str) PermissionsPolicy | PermissionsBoundary
    :param max_results: (int) max results to query on
    :param marker: (str) token to query on
    :return: (dict) response object containing response data
    """
    if marker:
        return client.list_policies(
            Scope=scope,
            OnlyAttached=only_attached,
            PathPrefix=path_prefix,
            PolicyUsageFilter=policy_usage_filter,
            Marker=marker,
            MaxItems=max_results
        )
    else:
        return client.list_policies(
            Scope=scope,
            OnlyAttached=only_attached,
            PathPrefix=path_prefix,
            PolicyUsageFilter=policy_usage_filter,
            MaxItems=max_results
        )


def list_policies(client, scope='Local', only_attached=False, path_prefix='/',
                  policy_usage_filter='PermissionsPolicy'):
    """Lists policies in IAM

    :param client: boto3.client object
    :param scope: (str) All | AWS | Local
    :param only_attached: (bool) Set True to return only attached policies
    :param path_prefix: (str) IAM policy path prefix
    :param policy_usage_filter: (str) PermissionsPolicy | PermissionsBoundary
    :return: (list) of policies (dict)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.list_policies')
    marker = None
    next_query = True
    policy_list = []
    log.info('Attempting to list IAM policies...')
    while True:
        if not next_query:
            break
        response = list_policies_with_marker(client=client, scope=scope, only_attached=only_attached,
                                             path_prefix=path_prefix, policy_usage_filter=policy_usage_filter,
                                             marker=marker)
        if 'IsTruncated' not in response.keys():
            log.warning('IsTruncated not found in response: {r}'.format(r=str(response)))
            return policy_list
        if 'Policies' not in response.keys():
            log.warning('Policies not found in response: {r}'.format(r=str(response)))
            return policy_list
        next_query = response['IsTruncated']
        policy_list += response['Policies']
        if 'Marker' not in response.keys():
            next_query = False
        else:
            marker = response['Marker']
    log.info('Found {n} IAM policies'.format(n=str(len(policy_list))))
    return policy_list


def list_policy_versions_with_marker(client, policy_arn, marker=None, max_results=100):
    """Returns a list of IAM roles using the provided marker

    :param client: boto3.client object
    :param policy_arn: (str) ARN of the policy
    :param max_results: (int) max results to query on
    :param marker: (str) token to query on
    :return: (dict) response object containing response data
    """
    if marker:
        return client.list_policy_versions(
            PolicyArn=policy_arn,
            Marker=marker,
            MaxItems=max_results
        )
    else:
        return client.list_policy_versions(
            PolicyArn=policy_arn,
            MaxItems=max_results
        )


def list_policy_versions(client, policy_arn):
    """Lists policies in IAM

    :param client: boto3.client object
    :param policy_arn: (str) ARN of the policy
    :return: (list) of policies (dict)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.list_policy_versions')
    marker = None
    next_query = True
    policy_version_list = []
    log.info('Attempting to list IAM policy version for [{p}]'.format(p=policy_arn))
    while True:
        if not next_query:
            break
        response = list_policy_versions_with_marker(client=client, policy_arn=policy_arn, marker=marker)
        if 'IsTruncated' not in response.keys():
            log.warning('IsTruncated not found in response: {r}'.format(r=str(response)))
            return policy_version_list
        if 'Versions' not in response.keys():
            log.warning('Versions not found in response: {r}'.format(r=str(response)))
            return policy_version_list
        next_query = response['IsTruncated']
        policy_version_list += response['Versions']
        if 'Marker' not in response.keys():
            next_query = False
        else:
            marker = response['Marker']
    log.info('Found {n} IAM policy versions'.format(n=str(len(policy_version_list))))
    return policy_version_list


############################################################################
# Methods for listing roles
############################################################################


def list_roles_with_marker(client, path_prefix='/', marker=None, max_results=100):
    """Returns a list of IAM roles using the provided marker

    :param client: boto3.client object
    :param path_prefix: (str) IAM role path prefix
    :param max_results: (int) max results to query on
    :param marker: (str) token to query on
    :return: (dict) response object containing response data
    """
    if marker:
        return client.list_roles(
            PathPrefix=path_prefix,
            Marker=marker,
            MaxItems=max_results
        )
    else:
        return client.list_roles(
            PathPrefix=path_prefix,
            MaxItems=max_results
        )


def list_roles(client, path_prefix='/'):
    """Lists roles in IAM

    :param client: boto3.client object
    :param path_prefix: (str) IAM role prefix
    :return:
    """
    log = logging.getLogger(mod_logger + '.list_roles')
    marker = None
    next_query = True
    role_list = []
    log.info('Attempting to list IAM roles...')
    while True:
        if not next_query:
            break
        response = list_roles_with_marker(client=client, marker=marker, path_prefix=path_prefix)
        if 'IsTruncated' not in response.keys():
            log.warning('IsTruncated not found in response: {r}'.format(r=str(response)))
            return role_list
        if 'Roles' not in response.keys():
            log.warning('Roles not found in response: {r}'.format(r=str(response)))
            return role_list
        next_query = response['IsTruncated']
        role_list += response['Roles']
        if 'Marker' not in response.keys():
            next_query = False
        else:
            marker = response['Marker']
    log.info('Found {n} IAM roles'.format(n=str(len(role_list))))
    return role_list


############################################################################
# Update the account password policy
############################################################################


def update_account_password_policy(client, min_password_len=14, symbols=True, numbers=True, uppers=True, lowers=True,
                                   allow_change=True, max_age=90, previous_password_prevention=24, hard_expiry=False):
    """

    :param client: boto3.client object
    :param min_password_len: (int) minimum number of characters
    :param symbols: (bool) require symbols
    :param numbers: (bool) require numbers
    :param uppers: (bool) require uppers
    :param lowers: (bool) require lowers
    :param allow_change: (bool) allow self-password reset
    :param max_age: (int) maximum age before password expires in days
    :param previous_password_prevention: (int) number of historical passwords to prevent reuse
    :param hard_expiry: (bool) disallow users from reset when expired
    :return: None
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.update_account_password_policy')
    log_msg = 'Updating account password policy: '
    msg = '[Minimum Length: ' + str(min_password_len)
    if symbols:
        msg += ', symbols required'
    if numbers:
        msg += ', numbers required'
    if uppers:
        msg += ', uppers required'
    if lowers:
        msg += ', lowers required'
    if allow_change:
        msg += ', allow self-reset'
    else:
        msg += ', NOT allow self-reset'
    msg += ', maximum age: ' + str(max_age)
    msg += ', previous password reuse prevention: ' + str(previous_password_prevention)
    if hard_expiry:
        msg += ', self-reset NOT allowed after expiration]'
    else:
        msg += ', self-reset allowed after expiration]'
    log.info(log_msg + msg)
    try:
        client.update_account_password_policy(
            MinimumPasswordLength=min_password_len,
            RequireSymbols=symbols,
            RequireNumbers=numbers,
            RequireUppercaseCharacters=uppers,
            RequireLowercaseCharacters=lowers,
            AllowUsersToChangePassword=allow_change,
            MaxPasswordAge=max_age,
            PasswordReusePrevention=previous_password_prevention,
            HardExpiry=hard_expiry
        )
    except ClientError as exc:
        msg = 'Problem setting password policy: [{m}]'.format(m=msg)
        raise IamUtilError(msg) from exc


############################################################################
# Update an existing role
############################################################################


def update_policy(client, policy_name, policy_document, path='/', description=''):
    """
    Updates the specified policy, create new if it does not exist

    Permissions boundary ARN not supported yet.

    :param client: boto3.client object
    :param policy_name: (str) policy name
    :param policy_document: (str) path to JSON policy file
    :param path: (str) path to the role
    :param description: (str) description of the role
    :return: (dict) role data (specified in boto3)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.update_policy')
    log.info('Attempting to update policy [{n}] with policy document: {p}'.format(
        n=policy_name, p=policy_document))
    return create_or_update_policy(client=client, policy_name=policy_name, policy_document=policy_document, path=path,
                                   description=description)


############################################################################
# Update an existing role
############################################################################


def update_role(client, role_name, role_policy, path='/', description='', max_session_duration_sec=43200):
    """
    Updates the specified role, or creates it if it does not exist

    Permissions boundary ARN not supported yet.

    :param client: boto3.client object
    :param role_name: (str) role name
    :param role_policy: (str) path to JSON policy file
    :param path: (str) path to the role
    :param description: (str) description of the role
    :param max_session_duration_sec: (int) Number of seconds each session is valid for
    :return: (dict) role data (specified in boto3)
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.update_role')
    log.info('Attempting to update role [{n}] with policy: {p}'.format(n=role_name, p=role_policy))
    return create_or_update_role(client=client, role_name=role_name, role_policy=role_policy, path=path,
                                 description=description, max_session_duration_sec=max_session_duration_sec)


def update_role_description_and_session(client, role_name, description='', max_session_duration_sec=43200):
    """Updates the role name with the provided description and session duration

    :param client: boto3.client object
    :param role_name: (str) name of the role to update
    :param description: (str) Description for the role
    :param max_session_duration_sec: (int) Maximum session duration in seconds
    :return:
    """
    log = logging.getLogger(mod_logger + '.update_role_description_and_session')
    log.info('Updating role [{n}] with description [{d}] and maximum session duration [{s}]'.format(
        n=role_name, d=description, s=str(max_session_duration_sec)))
    try:
        client.update_role(
            RoleName=role_name,
            Description=description,
            MaxSessionDuration=max_session_duration_sec
        )
    except ClientError as exc:
        msg = 'Problem updating role: {n}'.format(n=role_name)
        raise IamUtilError(msg) from exc


def update_role_trust_policy(client, role_name, role_policy):
    """Updates the role name with the provided policy

    :param client: boto3.client object
    :param role_name: (str) role name
    :param role_policy: (str) path to JSON policy file
    :return: None
    :raises: IamUtilError
    """
    log = logging.getLogger(mod_logger + '.update_role_trust_policy')
    log.info('Attempting to update role [{n}] with trust policy: {p}'.format(n=role_name, p=role_policy))

    # Ensure the file_path file exists
    if not os.path.isfile(role_policy):
        raise IamUtilError('Role policy file not found: {f}'.format(f=role_policy))
    try:
        with open(role_policy, 'r') as f:
            role_policy_data = json.load(f)
    except(OSError, IOError) as exc:
        raise IamUtilError('Unable to read policy file: {f}'.format(f=role_policy)) from exc
    log.info('Loading policy from file: {f}'.format(f=role_policy))
    json_role_policy_data = json.dumps(role_policy_data)
    try:
        client.update_assume_role_policy(
            RoleName=role_name,
            PolicyDocument=json_role_policy_data
        )
    except ClientError as exc:
        msg = 'Problem updating the trust policy to [{p}] for role [{n}] with\n{d}'.format(
            p=role_policy, n=role_name, d=str(json_role_policy_data))
        raise IamUtilError(msg) from exc
