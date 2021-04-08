"""Module: stsutil

This module provides utilities for interacting AWS STS

"""
import logging
import os
import shutil
import time

from botocore.client import ClientError

from .awsutil import get_boto3_client
from .exceptions import StsUtilError
from .logify import Logify


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.stsutil'

# Supported gov regions
gov_regions = [
    'us-gov-east-1',
    'us-gov-west-1'
]


# Supported commercial regions
commercial_regions = [
    'us-east-1',
    'us-east-2',
    'us-west-2'
]

# Default gov region
default_gov_region = 'us-gov-west-1'

# Default commercial region
default_commercial_region = 'us-east-2'

# Default output format
default_output_format = 'text'

# AWS config file locations
aws_dir = os.path.join(os.path.expanduser('~'), '.aws')
credentials_file = os.path.join(aws_dir, 'credentials')
config_file = os.path.join(aws_dir, 'config')


class AwsOrganizationAccount(object):
    """Defines an AWS organization (either in AWS Commercial/Standard or AWS GovCloud by:

    master_account_id: (str) Owner account ID of the organization
    child_account_list: (list) of (dict) child accounts in format:
        {
            'customer': 'CUSTOMER_NAME',
            'account_id': 'ACCOUNT_ID',
            'active': True | False
        }
    gov: (bool) Set True for AWS GovCloud account/org management, Commercial/Standard otherwise.
    output_format: (str) Desired output formatL text, json, or table

    Whether or not this is GovCloud determines:

    arn_str: (str) ARN string used to determine AWS ARNs
    region: (list) of supported region IDs (e.g. us-east-1)
    default_region: (str)Default region for configuration
    description: (str) Description of the organization environment (commercial or govcloud)

    Also the following members:

    master_credentials_file: (str) Path of the master credentials file for the master account
    customer_list: (list) of customer names generated from

    This requires master credentials to be stored in the following locations:

        ~/.aws/credentials.commercial
        ~/.aws/credentials.govcloud
    
    

    """
    def __init__(self, master_account_id, child_account_list, gov=False, output_format=default_output_format):
        self.master_account_id = master_account_id
        self.child_account_list = child_account_list
        self.gov = gov
        self.output_format = output_format
        if self.gov:
            self.arn_str = 'aws-us-gov'
            self.regions = gov_regions
            self.default_region = default_gov_region
            self.description = 'govcloud'
        else:
            self.arn_str = 'aws'
            self.regions = commercial_regions
            self.default_region = default_commercial_region
            self.description = 'commercial'
        self.master_credentials_file = os.path.join(aws_dir, 'credentials.' + self.description)
        self.customer_list = [x['customer'] for x in self.child_account_list]

    def reset_master_account_credentials(self, region=None):
        """Resets the master account credentials

        :region: (str) Name of the region to reset the master account credentials to
        :return: None
        :raises: OSError
        """
        if not os.path.isfile(self.master_credentials_file):
            msg = 'Master credential file not found, please create it with your master account credentials: {f}'.format(
                f=self.master_credentials_file)
            raise OSError(msg)
        if os.path.isfile(credentials_file):
            os.remove(credentials_file)
        if os.path.isfile(config_file):
            os.remove(config_file)
        shutil.copy2(self.master_credentials_file, credentials_file)
        if not region:
            region = self.default_region
        config_content = '[default]\nregion = {r}\noutput = {f}\n\n'.format(r=region, f=self.output_format)
        with open(config_file, 'w') as f:
            f.write(config_content)

    def set_credentials(self, access_key_id, secret_access_key, session_token=None, region=None):
        """Set the credentials file to the provided credentials

        :param access_key_id: (str) access key ID
        :param secret_access_key: (str) secret access key
        :param session_token: (str) long session token
        :param region: (str) region
        :return: None
        :raises: OSError
        """
        # If region was provided, update the config file
        if region:
            if region not in self.regions:
                msg = 'Invalid region [{r}], must be one of: [{s}]'.format(r=region, s=','.join(self.regions))
                raise OSError(msg)
            if os.path.isfile(config_file):
                os.remove(config_file)
            config_content = '[default]\nregion = {r}\noutput = {f}\n\n'.format(r=region, f=self.output_format)
            with open(config_file, 'w') as f:
                f.write(config_content)

        # Update the credentials file
        if os.path.isfile(credentials_file):
            os.remove(credentials_file)

        credentials_content = '[default]\n'
        credentials_content += 'aws_access_key_id = {a}\n'.format(a=access_key_id)
        credentials_content += 'aws_secret_access_key = {k}\n'.format(k=secret_access_key)
        if session_token:
            credentials_content += 'aws_session_token = {s}\n'.format(s=session_token)
        credentials_content += '\n'
        with open(credentials_file, 'w') as f:
            f.write(credentials_content)

    def get_master_account_credentials(self):
        """Reads and returns the master account credentials

        :return: (tuple) access key ID and secret access key
        :raises OSError
        """
        with open(self.master_credentials_file, 'r') as f:
            lines = f.readlines()
        access_key_id = None
        secret_access_key = None
        for line in lines:
            if line.startswith('aws_access_key_id'):
                access_key_id = line.split('=')[1].strip()
            if line.startswith('aws_secret_access_key'):
                secret_access_key = line.split('=')[1].strip()
        if not all([access_key_id, secret_access_key]):
            raise OSError('master account credentials not found')
        return access_key_id, secret_access_key


def assume_role(client, role_arn, session_name, duration_sec=3600, mfa_device=None, mfa_totp=None):
    """Assume role with or without MFA

    :param client: boto3.client object
    :param role_arn: (str) ARN of the role to assume
    :param session_name: (str) name of the session
    :param duration_sec: (int) length of the session
    :param mfa_device: (str) ARN of the MFA device
    :param mfa_totp: (str) MFA token code
    :return: (dict) credentials (see boto3 docs)
    :raises: StsUtilError
    """
    log = logging.getLogger(mod_logger + '.assume_role')
    log.info('Attempting to generate a sessions token for session [{s}] as role: {r}'.format(
        s=session_name, r=role_arn))

    # Generate the session access token with MFA
    if mfa_device and mfa_totp:
        log.info('Generating session token using MFA device: {d}'.format(d=mfa_device))
        try:
            response = client.assume_role(
                RoleArn=role_arn,
                RoleSessionName=session_name,
                DurationSeconds=duration_sec,
                SerialNumber=mfa_device,
                TokenCode=mfa_totp,
            )
        except Exception as exc:
            msg = 'Problem generating session token by assuming role [{r}], using MFA device [{m}]'. \
                format(r=role_arn, m=mfa_device)
            raise StsUtilError(msg) from exc
    else:
        try:
            response = client.assume_role(
                RoleArn=role_arn,
                RoleSessionName=session_name,
                DurationSeconds=duration_sec
            )
        except Exception as exc:
            msg = 'Problem generating session token by assuming role [{r}], using MFA device [{m}]'. \
                format(r=role_arn, m=mfa_device)
            raise StsUtilError(msg) from exc
    if 'Credentials' not in response:
        msg = 'Credentials not found in response: {r}'.format(r=str(response))
        raise StsUtilError(msg)
    return response['Credentials']


def get_caller_identity(client=None):
    """Gets the identity of the calling client

    :param client: boto3.client (see boto3 docs)
    :return: (dict) caller identity or None
    """
    log = logging.getLogger(mod_logger + '.get_caller_identity')
    if not client:
        client = get_sts_client()
    try:
        response = client.get_caller_identity()
    except ClientError as exc:
        log.warning('Problem getting caller identity\n{e}'.format(e=str(exc)))
        return
    return response


def get_current_id(sts):
    """Returns ID data for the currently logged in user

    :param sts: boto3 client
    :return: (dict) see boto3 docs
    :raises: StsUtilError
    """
    try:
        current_id = sts.get_caller_identity()
    except Exception as exc:
        msg = 'Problem getting the current user ID, please ensure AWS credentials are configured'
        raise StsUtilError(msg) from exc
    if 'Arn' not in current_id.keys():
        msg = 'Arn not found in current user ID data: {d}'.format(d=current_id)
        raise StsUtilError(msg)
    if 'Account' not in current_id.keys():
        msg = 'Account not found in current user ID data: {d}'.format(d=current_id)
        raise StsUtilError(msg)
    return current_id


def get_sts_client(region_name=None, aws_access_key_id=None, aws_secret_access_key=None, aws_session_token=None):
    """Gets an STS client

    :return: boto3.client object
    :raises: AWSAPIError
    """
    return get_boto3_client(service='sts', region_name=region_name, aws_access_key_id=aws_access_key_id,
                            aws_secret_access_key=aws_secret_access_key, aws_session_token=aws_session_token)


def login_as_role(aws_account, account_id_to_switch_to, session_name, role_name='OrganizationAccountAccessRole',
                  duration_sec=3600, region=None, set_credentials_file=False, use_mfa=False, mfa_totp=None,
                  print_token_info=False):
    """Switches roles into the provided account ID

    :param aws_account: (AwsOrganizationAccount) account info
    :param account_id_to_switch_to: (str) ID of the account to switch to
    :param session_name: (str) Name of the session
    :param role_name: (str) name of the role to switch to
    :param duration_sec: (int) Requested duration of the STS token in seconds
    :param region: (str) AWS region
    :param set_credentials_file: (bool) Set True to modify credentials files before returning
    :param use_mfa: (bool) Set True to prompt the user for MFA token code
    :param mfa_totp: (str) MFA TOTP code
    :param print_token_info: (bool) Set True to have the token info printed to STDOUT
    :return: (tuple) access key ID, secret access key, session token, region
    :raises: StsUtilError
    """
    if not region:
        region = aws_account.default_region

    aws_access_key_id, aws_secret_access_key = aws_account.get_master_account_credentials()
    sts = get_sts_client(
        region_name=aws_account.default_region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key
    )

    # Get the current account ID and compare to the master, restore master credentials if needed
    current_id = get_current_id(sts)
    if current_id['Account'] != aws_account.master_account_id:
        print('Resetting master account credentials...')
        aws_account.reset_master_account_credentials()
        time.sleep(2)
        current_id = get_current_id(sts)

    # Get the current username
    username = current_id['Arn'].split('/')[-1]
    print('Running as user [{u}] in account: {i}'.format(u=username, i=current_id['Account']))

    # Compute the role ARN and the MFA device ID
    role_arn = 'arn:{a}:iam::{i}:role/{r}'.format(a=aws_account.arn_str, i=account_id_to_switch_to, r=role_name)
    mfa_device = None

    # Print info
    print('--------------------------')
    print('Attempting to switch to session [{s}] as role: {r}'.format(s=session_name, r=role_arn))

    if use_mfa:
        mfa_device = 'arn:{a}:iam::{m}:mfa/{u}'.format(
            a=aws_account.arn_str, m=aws_account.master_account_id, u=username)
        print('Using MFA device: {m}'.format(m=mfa_device))

        # Collect the TOTP device code from the user
        if not mfa_totp:
            mfa_totp = input('Enter your MFA code for [{e}]: '.format(e=aws_account.description))
        else:
            print('Using provided TOTP code')
    else:
        print('Not using MFA')
    print('--------------------------')

    # Generate credentials
    credentials = assume_role(client=sts, role_arn=role_arn, session_name=session_name, duration_sec=duration_sec,
                              mfa_device=mfa_device, mfa_totp=mfa_totp)

    # Parse the output
    try:
        expiration = credentials['Expiration']
        expiration_str = expiration.strftime("%A, %d. %B %Y %I:%M%p")
        access_key_id = credentials['AccessKeyId']
        secret_access_key = credentials['SecretAccessKey']
        session_token = credentials['SessionToken']
    except KeyError as exc:
        msg = 'Problem retrieving data from credentials: {r}'.format(r=str(credentials))
        raise StsUtilError(msg) from exc

    if print_token_info:
        print('\n--------------------------')
        print('Generated STS token with: ')
        print('  Access Key ID: {i}'.format(i=access_key_id))
        print('  Secret Access Key: {i}'.format(i=secret_access_key))
        print('  Session Token: {i}'.format(i=session_token))
        print('  Token Expiration: {e}'.format(e=expiration_str))
        print('--------------------------')

    if set_credentials_file:
        # Set credentials to the new token
        aws_account.set_credentials(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            session_token=session_token,
            region=region
        )
    return access_key_id, secret_access_key, session_token, region, mfa_device
