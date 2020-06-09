#!/usr/bin/env python

from .exceptions import InvalidCloudError


class Cloud(object):

    def __init__(self, **kwargs):
        """Validates and stores cloud data

        > Note: Does not handle at this time:
          * cloud network templates
          * templateVirtualizationRealm

        :param name: (str) Cloud name
        :param owning_team_id: (int) Owning team ID
        :param subtype: (str) "awsCloud" "azureCloud" "openStackCloud" "vCloudCloud" "vCloudRestCloud"
        :param description: (str) description
        :param max_impact_level: (str) "NONE" "FEDRAMP_LOW" "FEDRAMP_MODERATE_DOD_LEVEL_2" "FEDRAMP_HIGH_DOD_LEVEL_4"
                "DOD_LEVEL_5" "DOD_LEVEL_6"
        :param external_ip_source: (str) "ON_DEMAND" "POOL"
        :param external_ip_address_list: (list) of IP addresses
        :param allocation_capable: (bool) Set True if this cloud is able to allocate cloudspaces
        :param de_allocation_capable: (bool) Set True if this cloud is able to de-allocate cloudspaces
        :param linux_repo_url: (str) URL of a Linux YUM repository for the cloud
        :param state: (str) "ACTIVE" "ENTERING_MAINTENANCE" "MAINTENANCE"
        :param aws_secret_key: (str) AWS secret access key
        :param aws_region: (str) AWS region
        :param aws_owner_id: (str) AWS owner/account ID
        :param aws_access_key: (str) AWS access key ID
        :param azure_container_url: (str) Azure storage container URL
        :param azure_tenant: (str) Azure Tenant ID
        :param azure_subscription: (str) Azure subscription ID
        :param azure_secret_key: (str) Azure service principal secret key
        :param azure_region: (str) "US_EAST" "DOD_US_CENTRAL" "DOD_US_EAST" "GOV_US_VIRGINIA" "GOV_US_TEXAS"
        :param azure_environment: (str) "AZURE" "AZURE_US_GOVERNMENT"
        :param azure_client_id: (str) Azure application registration / service principal object ID
        :param openstack_tenant_id: (str) Openstack tenant ID
        :param openstack_tenant: (str) Openstack tenant
        :param openstack_nat_instance_type: (str) Openstack NAT instance type
        :param openstack_nat_image_id: (str) Openstack NAT image ID
        :param openstack_keystone_username: (str) Openstack Keystone username
        :param openstack_keystone_version: (str) Openstack Keystone version
        :param openstack_keystone_protocol: (str) Openstack Keystone protocol
        :param openstack_keystone_port: (int) Openstack Keystone port
        :param openstack_keystone_password: (str) Openstack Keystone password
        :param openstack_keystone_hostname: (str) Openstack Keystone hostname
        :param openstack_domain_name: (str) Openstack domain name
        :param vcloud_username: (str) vCloud account username
        :param vcloud_remote_access_port: (int) vCloud remote access port
        :param vcloud_remote_access_internal_ip: (str) vCloud remote access internal cloudspace IP address
        :param vcloud_protocol: (str) vCloud protocol
        :param vcloud_port: (int) vCloud port
        :param vcloud_password: (str) vCloud account password
        :param vcloud_hostname: (str) vCloud hostname
        """
        # Handle kwargs
        if 'name' not in kwargs.keys():
            raise InvalidCloudError('name data required')
        if 'owning_team_id' not in kwargs.keys():
            raise InvalidCloudError('owning_team_id data required')
        if 'subtype' not in kwargs.keys():
            raise InvalidCloudError('subtype data required')
        name = kwargs.get('name')
        owning_team_id = kwargs.get('owning_team_id')
        subtype = kwargs.get('subtype')
        description = kwargs.get('description', None)
        max_impact_level = kwargs.get('max_impact_level', 'NONE')
        external_ip_source = kwargs.get('external_ip_source', 'ON_DEMAND')
        external_ip_address_list = kwargs.get('external_ip_address_list', None)
        allocation_capable = kwargs.get('allocation_capable', True)
        de_allocation_capable = kwargs.get('de_allocation_capable', True)
        linux_repo_url = kwargs.get('linux_repo_url', None)
        state = kwargs.get('state', 'Active')

        # AWS credentials
        aws_access_key = kwargs.get('aws_access_key', None)
        aws_owner_id = kwargs.get('aws_owner_id', None)
        aws_region = kwargs.get('aws_region', None)
        aws_secret_key = kwargs.get('aws_secret_key', None)

        # Azure credentials
        azure_client_id = kwargs.get('azure_client_id', None)
        azure_environment = kwargs.get('azure_environment', None)
        azure_region = kwargs.get('azure_region', None)
        azure_secret_key = kwargs.get('azure_secret_key', None)
        azure_subscription = kwargs.get('azure_subscription', None)
        azure_tenant = kwargs.get('azure_tenant', None)
        azure_container_url = kwargs.get('azure_container_url', None)

        # Openstack credentials
        openstack_domain_name = kwargs.get('openstack_domain_name', None)
        openstack_keystone_hostname = kwargs.get('openstack_keystone_hostname', None)
        openstack_keystone_password = kwargs.get('openstack_keystone_password', None)
        openstack_keystone_port = kwargs.get('openstack_keystone_port', 443)
        openstack_keystone_protocol = kwargs.get('openstack_keystone_protocol', None)
        openstack_keystone_username = kwargs.get('openstack_keystone_username', None)
        openstack_keystone_version = kwargs.get('openstack_keystone_version', None)
        openstack_nat_image_id = kwargs.get('openstack_nat_image_id', None)
        openstack_nat_instance_type = kwargs.get('openstack_nat_instance_type', None)
        openstack_tenant = kwargs.get('openstack_tenant', None)
        openstack_tenant_id = kwargs.get('openstack_tenant_id', None)

        # vCloud credentials
        vcloud_hostname = kwargs.get('vcloud_hostname', None)
        vcloud_password = kwargs.get('vcloud_password', None)
        vcloud_port = kwargs.get('vcloud_port', 443)
        vcloud_protocol = kwargs.get('vcloud_protocol', None)
        vcloud_remote_access_internal_ip = kwargs.get('vcloud_remote_access_internal_ip', '172.16.10.253')
        vcloud_remote_access_port = kwargs.get('vcloud_remote_access_port', 9443)
        vcloud_username = kwargs.get('vcloud_username', None)

        # Build and validate cloud data
        self.cloud_data = {}

        # Ensure the owning_team_id is an int
        if not isinstance(owning_team_id, int):
            try:
                owning_team_id = int(kwargs['owning_team_id'])
            except ValueError as exc:
                raise InvalidCloudError('The owning_team_id arg must be an int') from exc

        # Build cloud data to provide
        self.cloud_data['name'] = name

        # Check the subtype
        if 'aws' in subtype.lower():
            if not all([aws_access_key, aws_secret_key, aws_region, aws_owner_id]):
                msg = 'AWS credentials required: aws_secret_key, aws_secret_key, aws_region, aws_owner_id'
                raise InvalidCloudError(msg)
            self.cloud_data['subtype'] = 'awsCloud'
            self.cloud_data['accessKey'] = aws_access_key
            self.cloud_data['ownerId'] = aws_owner_id
            self.cloud_data['regionName'] = aws_region
            self.cloud_data['secretAccessKey'] = aws_secret_key
        elif 'azure' in subtype.lower():
            if not all([azure_region, azure_tenant, azure_environment, azure_secret_key, azure_subscription,
                        azure_client_id]):
                msg = 'Azure credentials required: azure_region, azure_tenant, azure_environment, azure_secret_key, ' \
                      'azure_subscription, azure_client_id'
                raise InvalidCloudError(msg)
            self.cloud_data['subtype'] = 'azureCloud'
            self.cloud_data['clientId'] = azure_client_id
            self.cloud_data['environment'] = azure_environment
            self.cloud_data['regionName'] = azure_region
            self.cloud_data['secretAccessKey'] = azure_secret_key
            self.cloud_data['subscriptionId'] = azure_subscription
            self.cloud_data['tenant'] = azure_tenant
            if azure_container_url:
                self.cloud_data['publicContainerUrl'] = azure_container_url
        elif 'openstack' in subtype.lower():
            if not all([openstack_domain_name, openstack_keystone_hostname, openstack_keystone_password,
                        openstack_keystone_port, openstack_keystone_protocol, openstack_keystone_username,
                        openstack_keystone_version, openstack_nat_image_id, openstack_nat_instance_type,
                        openstack_tenant, openstack_tenant_id]):
                msg = 'Openstack credentials required: openstack_domain_name, openstack_keystone_hostname, ' \
                      'openstack_keystone_password, openstack_keystone_port, openstack_keystone_protocol, ' \
                      'openstack_keystone_username, openstack_keystone_version, openstack_nat_image_id, ' \
                      'openstack_nat_instance_type, openstack_tenant, openstack_tenant_id'
                raise InvalidCloudError(msg)
            self.cloud_data['subtype'] = 'openStackCloud'
            self.cloud_data['domainName'] = openstack_domain_name
            self.cloud_data['keystoneHostname'] = openstack_keystone_hostname
            self.cloud_data['keystonePassword'] = openstack_keystone_password
            self.cloud_data['keystonePort'] = openstack_keystone_port
            self.cloud_data['keystoneProtocol'] = openstack_keystone_protocol
            self.cloud_data['keystoneUsername'] = openstack_keystone_username
            self.cloud_data['keystoneVersion'] = openstack_keystone_version
            self.cloud_data['natImageId'] = openstack_nat_image_id
            self.cloud_data['natInstanceType'] = openstack_nat_instance_type
            self.cloud_data['tenant'] = openstack_tenant
            self.cloud_data['tenantId'] = openstack_tenant_id
        elif 'vcloud' in subtype.lower():
            if not all([vcloud_hostname, vcloud_password, vcloud_port, vcloud_protocol,
                        vcloud_remote_access_internal_ip, vcloud_remote_access_port, vcloud_username]):
                msg = 'vCloud credentials required: vcloud_hostname, vcloud_password, vcloud_port, vcloud_protocol, ' \
                      'vcloud_remote_access_internal_ip, vcloud_remote_access_port, vcloud_username'
                raise InvalidCloudError(msg)
            self.cloud_data['subtype'] = 'vCloudCloud'
            self.cloud_data['hostname'] = vcloud_hostname
            self.cloud_data['password'] = vcloud_password
            self.cloud_data['port'] = vcloud_port
            self.cloud_data['protocol'] = vcloud_protocol
            self.cloud_data['remoteAccessInternalIp'] = vcloud_remote_access_internal_ip
            self.cloud_data['remoteAccessPort'] = vcloud_remote_access_port
            self.cloud_data['username'] = vcloud_username
        else:
            msg = 'Unsupported subtype: {t}'.format(t=subtype)
            raise InvalidCloudError(msg)

        if description:
            self.cloud_data['description'] = description
        else:
            self.cloud_data['description'] = 'This is an {t} called: {n}'.format(t=subtype, n=name)

        # Check the external IP address set to pool
        if external_ip_source == 'POOL':
            if not external_ip_address_list:
                external_ip_address_list = []
            else:
                if not isinstance(external_ip_address_list, list):
                    msg = 'external_ip_address_list must be a list'
                    raise InvalidCloudError(msg)
            self.cloud_data['externalIpAddresses'] = external_ip_address_list
        elif external_ip_source == 'ON_DEMAND':
            pass
        else:
            msg = 'Unsupported external_ip_source, should be POOL or ON_DEMAND, found: {s}'.format(s=external_ip_source)
            raise InvalidCloudError(msg)
        self.cloud_data['externalIpSource'] = external_ip_source

        # Add the features
        self.cloud_data['features'] = {}
        self.cloud_data['features']['allocationCapable'] = allocation_capable
        self.cloud_data['features']['deallocationCapable'] = de_allocation_capable

        # Add the linux repository URL if provided
        if linux_repo_url:
            self.cloud_data['linuxRepositoryUrl'] = linux_repo_url

        # Add the impact level
        self.cloud_data['maximumImpactLevel'] = max_impact_level

        # Add the owning team ID
        self.cloud_data['owningTeam'] = {}
        self.cloud_data['owningTeam']['id'] = owning_team_id

        # Add the state
        if state:
            self.cloud_data['state'] = state
