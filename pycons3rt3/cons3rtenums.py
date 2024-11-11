"""
cons3rtenums.py

A module for commonly used CONS3RT emails

"""

cons3rt_asset_types = ['CONTAINER', 'SOFTWARE', 'TEST']

cons3rt_deployment_run_status = [
    'CANCELED', 'COMPLETED', 'HOSTS_PROVISIONED', 'PROVISIONING_HOSTS', 'REDEPLOYING_HOSTS', 'RELEASE_REQUESTED',
    'RELEASING', 'RESERVED', 'SCHEDULED', 'SUBMITTED', 'TESTED', 'TESTING', 'UNKNOWN'
]


cons3rt_deployment_run_status_active = [
    'SUBMITTED', 'PROVISIONING_HOSTS', 'HOSTS_PROVISIONED', 'RESERVED', 'TESTING', 'TESTED'
]


cons3rt_fap_status = [
    'AGENT_CHECK_IN_ERROR', 'AGENT_CHECK_IN_SUCCESS', 'AWAITING_AGENT_CHECK_IN', 'BUILDING_HOSTSET',
    'BUILDING_HOSTSET_ERROR', 'BUILDING_SCENARIO', 'BUILDING_SCENARIO_ERROR', 'BUILDING_SOURCE',
    'BUILDING_SOURCE_ERROR', 'BUILDING_SYSTEMS', 'BUILDING_SYSTEMS_ERROR', 'CANCELED', 'COMPLETE',
    'FAP_SERVICE_COMMUNICATIONS_ERROR', 'HOSTSET_BUILT_POWERED_OFF', 'INVALID_REQUEST_ERROR', 'INVALID_STATE_ERROR',
    'POWERED_ON', 'POWERING_ON', 'POWERING_ON_ERROR', 'REBOOTING', 'REBOOTING_ERROR', 'REDEPLOYING_HOSTS',
    'REDEPLOYING_HOSTS_ERROR', 'RELEASE_REQUESTED', 'RELEASING', 'RELEASING_SCENARIO_ERROR', 'REQUESTED', 'RESERVED',
    'SCENARIO_BUILT', 'SOURCE_BUILT', 'SYSTEMS_BUILT', 'UNKNOWN'
]

cons3rt_software_asset_types = ['APPLICATION', 'TEST_TOOL']

cons3rt_system_types = ['APPLIANCE', 'DEVICE', 'PHYSICAL_HOST', 'VIRTUAL_HOST', 'INVALID']

cons3rt_test_asset_types = ['MOCK', 'NESSUS', 'POWERSHELL', 'SCRIPT', 'UNKNOWN']

interval_units = [
    'NANOS', 'MICROS', 'MILLIS', 'SECONDS', 'MINUTES', 'HOURS', 'HALFDAYS', 'DAYS', 'WEEKS', 'MONTHS', 'YEARS',
    'DECADES', 'CENTURIES', 'MILLENNIA', 'ERAS', 'FOREVER'
]

k8s_types = ['GENERIC', 'RKE2']

remote_access_sizes = ['SMALL', 'MEDIUM', 'LARGE']

service_types = [
    'AtlassianBitbucket', 'AtlassianConfluence', 'AtlassianJira', 'AtlassianJiraAssetManagement',
    'AtlassianJiraServiceManagement', 'GitlabPremium', 'GitlabUltimate', 'Mattermost', 'ProvisioningUser'
]

valid_search_type = [
    'SEARCH_ACTIVE', 'SEARCH_ALL', 'SEARCH_AVAILABLE', 'SEARCH_COMPOSING', 'SEARCH_DECOMPOSING', 'SEARCH_INACTIVE',
    'SEARCH_PROCESSING', 'SEARCH_SCHEDULED', 'SEARCH_TESTING', 'SEARCH_SCHEDULED_AND_ACTIVE'
]

vr_service_status = [
    'DISABLED', 'DISABLING', 'ENABLED', 'ENABLING', 'ERROR'
]

vr_service_types = [
    'KubernetesPaasVirtualizationRealmServiceRequest',
    'RemoteAccessVirtualizationRealmServiceRequest'
]