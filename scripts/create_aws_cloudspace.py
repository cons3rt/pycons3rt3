#!/usr/bin/env python3
"""
Sample script to create a CONS3RT-compliant cloudspace in AWS.  These cloudspaces can be registered
to CONS3RT.

Usage:
* Log in to the AWS CLI in your terminal window
* Import or create an AWS KeyPair and note the name, this will be used to SSH to the NAT box if needed


"""
import sys
import traceback

from pycons3rt3.ec2util import Cons3rtInfra
from pycons3rt3.ec2util import EC2Util
from pycons3rt3.exceptions import EC2UtilError

# Availability zone

# EC2 Util
e = EC2Util()

#################################################################################################
# UPDATE SETTINGS BELOW
#################################################################################################

cloudspace_name = 'Your-Cloudspace-Name'  # No spaces please
cloudspace_cidr_block = '172.16.0.0/16'
common_net_cidr_block = '172.16.1.0/24'
cons3rt_net_cidr_block = '172.16.10.0/24'
user_net_cidr_block = '172.16.14.0/24'
availability_zone = 'us-east-1b'
fleet_agent_version = 'REPLACE_ELASTIC_FLEET_AGENT_VERSION'
fleet_token = 'REPLACE_ELASTIC_FLEET_TOKEN_HERE'
nat_key_pair_name = 'REPLACE_KEYPAIR_NAME'
nat_ami_id = 'REPLACE_RED_HAT_8_AMI_ID_HERE'
nat_instance_type = 'c5a.xlarge'
nat_root_volume_location = '/dev/sda1'
nat_root_volume_size_gib = 100

# CONS3RT infra object for the parent CONS3RT environment that you plan to register this to
cons3rt_infra = Cons3rtInfra(
    web_gateway_ip='52.247.166.112',
    messaging_inbound_ip='52.247.166.112',
    webdav_inbound_ip='52.247.166.112',
    assetdb_inbound_ip='52.247.166.112',
    sourcebuilder_inbound_ip='52.247.166.112',
    cons3rt_outbound_ip='52.247.166.112',
    venue_outbound_ip='52.247.166.112',
    elastic_logging_ip='52.247.166.112',
    elastic_fleet_server_fqdn='fleet.arcus-cloud.io',
    ca_download_url='https://aaa-nat-gc.s3.amazonaws.com/cons3rtRoot.pem'
)

"""
Networks to allocate
  1 - Always list the NAT "common" subnet first, since it is required for routable networks, these are created in order
  2 - Elastic IPs will be allocated for routable networks, but specify them below to attach pre-existing IPs
      for example: 'elastic_ip_address': '52.52.52.52'
"""
networks = [
    {
        'name': 'common-net',
        'cidr': common_net_cidr_block,
        'availability_zone': availability_zone,
        'routable': False,
        'is_nat_subnet': True,
        'is_cons3rt_net': False,
        'elastic_ip_address': None
    },
    {
        'name': 'cons3rt-net',
        'cidr': cons3rt_net_cidr_block,
        'availability_zone': availability_zone,
        'routable': True,
        'is_nat_subnet': False,
        'is_cons3rt_net': True,
        'elastic_ip_address': None
    },
    {
        'name': 'user-net',
        'cidr': user_net_cidr_block,
        'availability_zone': availability_zone,
        'routable': True,
        'is_nat_subnet': False,
        'is_cons3rt_net': False,
        'elastic_ip_address': None
    },
]

#################################################################################################
# END UPDATE SECTION
#################################################################################################

# Create the VPC
print('Creating the VPC...')
try:
    vpc_id, internet_gateway_id = e.create_usable_vpc(vpc_name=cloudspace_name, cidr_block=cloudspace_cidr_block)
except EC2UtilError as exc:
    print('ERROR: Creating VPC [{v}] with CIDR block [{c}]\n{e}'.format(
        v=cloudspace_name, c=cloudspace_cidr_block, e=str(exc)))
    traceback.print_exc()
    sys.exit(1)


# create the subnets, route tables, network ACLs, and associate them
print('Creating the networks...')
try:
    created_networks = e.allocate_networks_for_cons3rt(
        cloudspace_name=cloudspace_name,
        cons3rt_infra=cons3rt_infra,
        vpc_id=vpc_id,
        nat_key_pair_name=nat_key_pair_name,
        internet_gateway_id=internet_gateway_id,
        networks=networks,
        fleet_agent_version=fleet_agent_version,
        fleet_token=fleet_token,
        nat_ami_id=nat_ami_id,
        remote_access_internal_ip_last_octet='253',
        remote_access_external_port=9443,
        remote_access_internal_port=9443,
        nat_instance_type=nat_instance_type,
        nat_root_volume_location=nat_root_volume_location,
        nat_root_volume_size_gib=nat_root_volume_size_gib
    )
except EC2UtilError as exc:
    print('ERROR: Creating networks\n{e}'.format(e=str(exc)))
    traceback.print_exc()
    sys.exit(1)

for created_network in created_networks:
    print('INFO: Created network [{n}] with CIDR: [{c}]'.format(n=created_network.network_name, c=created_network.cidr))

print('INFO: exiting...')
sys.exit(0)
