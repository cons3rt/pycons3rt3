"""Module: awsutil

This module provides utilities for interacting with the AWS
API, common to other AWS utils in this project.

"""
import boto3
import logging
import os
from botocore.client import ClientError

from .exceptions import AWSAPIError
from .logify import Logify


__author__ = 'Joe Yennaco'

# Set up logger name for this module
mod_logger = Logify.get_name() + '.awsutil'


# Global list of all AWS regions divided into useful lists
foreign_regions = ['af-south-1', 'ap-east-1', 'ap-northeast-1', 'ap-northeast-2', 'ap-northeast-3', 'ap-south-1',
                   'ap-southeast-1', 'ap-southeast-2', 'ca-central-1', 'eu-central-1', 'eu-north-1', 'eu-south-1',
                   'eu-west-1', 'eu-west-2', 'eu-west-3', 'me-south-1', 'sa-east-1']
us_regions = ['us-east-1', 'us-east-2', 'us-west-1', 'us-west-2']
gov_regions = ['us-gov-east-1', 'us-gov-west-1']
global_regions = foreign_regions + us_regions
all_regions = global_regions + gov_regions

linux_migration_user_data_script_contents = '''#!/bin/bash
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
#
# aws_cons3rt_bootstrap.sh
#
# Download and execute this scrip from AWS user-data in order to allow passwords in sshd_config
#
# Usage:
#     curl -O https://raw.githubusercontent.com/jyennaco/bashcons3rt/master/media/aws_cons3rt_bootstrap.sh
#     chmod +x ./aws_cons3rt_bootstrap.sh
#
#     Setup and start the service:
#     ./aws_cons3rt_bootstrap.sh setup
#
#     Start the service manually:
#     systemctl start aws_cons3rt_bootstrap.service
#
#     Run (outside of the service):
#     ./aws_cons3rt_bootstrap.sh run
#
#     Cleanup:
#     ./aws_cons3rt_bootstrap.sh cleanup
#
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =

# 1st arg ACTION, set to "setup" to tell the script to set itself up as a service (default), "run" to execute, or "cleanup"
ACTION="${1}"

# Source the environment
if [ -f /etc/bashrc ] ; then
    . /etc/bashrc
fi
if [ -f /etc/profile ] ; then
    . /etc/profile
fi

# Times to wait and maximum checks
seconds_between_checks=5
maximum_checks=240

# Path to systemctl service
bootstrapServiceFile='/usr/lib/systemd/system/aws_cons3rt_bootstrap.service'

# Path to the script to execute
scriptPath='/usr/local/bin/aws_cons3rt_bootstrap.sh'

# Parent Directory where this script lives
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
SCRIPT_NAME=$(basename "$0")
SCRIPT_PATH="${SCRIPT_DIR}/${SCRIPT_NAME}"

# Timestamp functions for convenience
function timestamp() { date "+%F %T"; }

# Log file location and tag
logTag='aws_cons3rt_bootstrap'
logFile="/var/log/cons3rt/aws_cons3rt_bootstrap_service.log"

# Logging function
function logInfo() { echo -e "$(timestamp) ${logTag} [INFO]: ${1}"; echo -e "$(timestamp) ${logTag} [INFO]: ${1}" >> ${logFile}; }
function logErr() { echo -e "$(timestamp) ${logTag} [ERROR]: ${1}"; echo -e "$(timestamp) ${logTag} [ERROR]: ${1}" >> ${logFile}; }
function logWarn() { echo -e "$(timestamp) ${logTag} [WARN]: ${1}"; echo -e "$(timestamp) ${logTag} [WARN]: ${1}" >> ${logFile}; }

function cleanup() {
    # Cleans up this service, script, when completed.  Leaves the log file.
    logInfo "Cleaning up the aws_cons3rt_bootstrap service..."

    # Delete the service file
    logInfo "Deleting service file: ${bootstrapServiceFile}"
    rm -f ${bootstrapServiceFile} >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logWarn "Problem bootstrapServiceFile: ${scriptPath}"; fi

    # Delete the script path
    logInfo "Deleting script: ${scriptPath}"
    rm -f ${scriptPath} >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logWarn "Problem removing: ${scriptPath}"; fi

    logInfo "Disabling the aws_cons3rt_bootstrap.service service..."
    systemctl disable aws_cons3rt_bootstrap.service
    if [ $? -ne 0 ]; then logWarn "Problem disabling the aws_cons3rt_bootstrap service"; fi

    # Daemon reload to pick up the service change
    logInfo "Running [systemctl daemon-reload] to remove the service..."
    systemctl daemon-reload >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logWarn "Problem running [systemctl daemon-reload]"; fi
    
    # Stop and disable the service
    logInfo "Stopping the aws_cons3rt_bootstrap.service service..."
    systemctl stop aws_cons3rt_bootstrap.service >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logWarn "Problem stopping the aws_cons3rt_bootstrap service"; fi
    
    logInfo "Completed cleaning up the aws_cons3rt_bootstrap service."
    return 0
}

function config_sshd() {
    # Configure sshd to allow root login, password authentication, and pubkey authentication
    logInfo "Configuring /etc/ssh/sshd_config to allow public key authentication, password authentication, and root login..."
    sed -i '/PubkeyAuthentication/d' /etc/ssh/sshd_config
    sed -i '/PermitRootLogin/d' /etc/ssh/sshd_config
    sed -i '/PasswordAuthentication/d' /etc/ssh/sshd_config
    echo -e "PubkeyAuthentication yes\n" >> /etc/ssh/sshd_config
    echo -e "PermitRootLogin yes\n" >> /etc/ssh/sshd_config
    echo -e "PasswordAuthentication yes\n" >> /etc/ssh/sshd_config

    logInfo "Restarting sshd..."
    systemctl restart sshd.service >> ${logFile} 2>&1
    restartRes=$?
    logInfo "Command [systemctl restart sshd.service] exited with code: ${restartRes}"
    return ${restartRes}
}

function run() {
    # Run the ssh configuration for user-data to complete
    logInfo "Checking the PasswordAuthentication value in /etc/ssh/sshd_config..."
    check_num=1
    while :; do
        if [ ${check_num} -gt ${maximum_checks} ]; then
            logInfo "Maximum number of checks reached ${check_num}, exiting..."
            return 0
        fi
        logInfo "Check number [${check_num} of ${maximum_checks}]"
        passAuthValue=$(cat /etc/ssh/sshd_config | grep "^PasswordAuthentication.*$" | awk '{print $2}')
        if [ -z "${passAuthValue}" ]; then
            logInfo "PasswordAuthentication value not found in /etc/ssh/sshd_config, configuring sshd..."
            config_sshd
        else
            logInfo "Found PasswordAuthentication value in /etc/ssh/sshd_config set to: ${passAuthValue}"
            if [[ "${passAuthValue}" == "no" ]]; then
                logInfo "PasswordAuthentication set to no, configuring sshd..."
                config_sshd
            elif [[ "${passAuthValue}" == "yes" ]]; then
                logInfo "PasswordAuthentication set to yes, nothing to do..."
            else
                logInfo "PasswordAuthentication set to ${passAuthValue}, configuring sshd..."
                config_sshd
                if [ $? -ne 0 ]; then logErr "Problem detected configuring sshd"; fi
            fi
        fi
        logInfo "Waiting ${seconds_between_checks} seconds to re-check..."
        sleep ${seconds_between_checks}s
        ((check_num++))
    done
    return 0
}

function setup() {
    # Configures the aws_cons3rt_bootstrap.service in systemd
    # Return 0 if setup completed with success
    # Return 1 if a problem was detected

    logInfo "Staging this script to: ${scriptPath}"

    # Ensure this script exists
    if [ ! -f ${SCRIPT_PATH} ]; then
        logErr "This script was not found! ${SCRIPT_PATH}"
        return 1
    fi

    # Stage the script
    cp -f ${SCRIPT_PATH} ${scriptPath} >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logErr "Problem staging script from ${SCRIPT_PATH} to: ${scriptPath}"; return 1; fi

    # Set permissions
    logInfo "Setting permissions on: ${scriptPath}"
    chown root:root ${scriptPath} >> ${logFile} 2>&1
    chmod 700 ${scriptPath} >> ${logFile} 2>&1

    logInfo "Staging the aws_cons3rt_bootstrap service file: ${bootstrapServiceFile}"

cat << EOF > ${bootstrapServiceFile}
##aws_cons3rt_bootstrap.service
[Unit]
Description=Configures sshd
After=network.target
DefaultDependencies=no
[Service]
Type=simple
ExecStart=/bin/bash ${scriptPath} run
User=root
Group=wheel
TimeoutStartSec=0
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF

    # Daemon reload to pick up the service change
    logInfo "Running [systemctl daemon-reload] to pick up the new service..."
    systemctl daemon-reload >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logErr "Problem running [systemctl daemon-reload]"; return 1; fi

    # Enable the service
    logInfo "Enabling the aws_cons3rt_bootstrap.service..."
    systemctl enable aws_cons3rt_bootstrap.service >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logErr "Problem enabling the aws_cons3rt_bootstrap.service"; return 1; fi

    # Start the service
    logInfo "Starting the aws_cons3rt_bootstrap.service..."
    systemctl start aws_cons3rt_bootstrap.service >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logErr "Problem starting the aws_cons3rt_bootstrap.service"; return 1; fi

    logInfo "Started aws_cons3rt_bootstrap successfully"
    return 0
}

function main() {
    logInfo "Running: ${SCRIPT_PATH}"
    logInfo "See log file: ${logFile}"

    # Set doSetup, doRun, doCleanup based on the provided arg, default is setup
    doCleanup=0
    doRun=0
    doSetup=1
    if [ -z "${ACTION}" ]; then
        doCleanup=0
        doRun=0
        doSetup=1
    else
        if [[ "${ACTION}" == "setup" ]]; then
            doCleanup=0
            doRun=0
            doSetup=1
        elif [[ "${ACTION}" == "run" ]]; then
            doCleanup=0
            doRun=1
            doSetup=0
        elif [[ "${ACTION}" == "clean" ]]; then
            doCleanup=1
            doRun=0
            doSetup=0
        elif [[ "${ACTION}" == "cleanup" ]]; then
            doCleanup=1
            doRun=0
            doSetup=0
        else
            logErr "Unknown arg provided: ${ACTION}. Expected run, setup, or blank."
            return 1
        fi
    fi

    # Cleanup, setup, or run
    if [ ${doCleanup} -eq 1 ]; then
        logInfo "Running cleanup..."
        cleanup
        if [ $? -ne 0 ]; then logErr "Problem running cleanup"; return 2; fi
        logInfo "Completed running cleanup."
    fi

    if [ ${doRun} -eq 1 ]; then
        logInfo "Running the aws bootstrap service..."
        run
        if [ $? -ne 0 ]; then logErr "Problem running the aws_cons3rt_bootstrap service"; return 3; fi
        logInfo "Completed running the AWS bootstrap service."
        cleanup
    fi

    if [ ${doSetup} -eq 1 ]; then
        logInfo "Running setup..."
        setup
        if [ $? -ne 0 ]; then logErr "Problem setting up the aws_cons3rt_bootstrap service"; return 4; fi
        logInfo "Completed running setup."
    fi

    logInfo "Completed: ${SCRIPT_PATH}"
    logInfo "See log file: ${logFile}"
    return 0
}

# Run the main function
main
res=$?
logInfo "Exiting with code: ${res}"
exit ${res}

'''


linux_nat_config_user_data_script_contents = '''#!/bin/bash
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
#
# linux-nat-config.sh
#
# This is an unofficial NAT config script for building a CONS3RT cloudspace outside of CONS3RT.  The 
# 
# IMPORTANT: NAT config script must have REPLACE_ME modifications before executing.
#
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =

TIMESTAMP=$(date "+%Y-%m-%d-%H%M%s")
##### GLOBAL VARIABLES #####
guacBoxIpAddress=CODE_REPLACE_ME_GUAC_SERVER_IP
guacBoxPort=CODE_REPLACE_ME_GUAC_SERVER_PORT
hostname=CODE_REPLACE_ME_HOSTNAME
subnetCidr=CODE_REPLACE_ME_SUBNET_CIDR_BLOCK
virtRealmType=CODE_REPLACE_ME_VIRT_TECH
fleetAgentVersion=CODE_REPLACE_ME_FLEET_AGENT_VERSION
fleetServerFqdn=CODE_REPLACE_ME_FLEET_SERVER_FQDN
fleetManagerPort=CODE_REPLACE_ME_FLEET_MANAGER_PORT
fleetToken=CODE_REPLACE_ME_FLEET_TOKEN
cons3rtRootCaUrl=CODE_REPLACE_ME_CONS3RT_ROOT_CA_DOWNLOAD_URL
# Array to maintain exit codes
resultSet=();
##### END GLOBAL VARIABLES #####
SYS_CTL="/bin/systemctl"
##### LOGGING CONFIG #####
logTag="nat-guest-customization"
logDir="/var/log"
if [ ! -d ${logDir} ]
then
 mkdir -p ${logDir}
 chmod 700 ${logDir}
fi
logFile="${logDir}/${logTag}-$(date "+%Y%m%d-%H%M%S").log"
touch ${logFile}
chmod 644 ${logFile}
echo $SHELL > ${logFile}
function timestamp() { date "+%F %T"; }
function logInfo() { echo -e "$(timestamp) ${logTag} [INFO]: ${1}" 2>&1 | tee -a ${logFile}; }
function logWarn() { echo -e "$(timestamp) ${logTag} [WARN]: ${1}" 2>&1 | tee -a ${logFile}; }
function logErr() { echo -e "$(timestamp) ${logTag} [ERROR]: ${1}" 2>&1 | tee -a ${logFile}; }
##### END LOGGING CONFIG #####
# Parameters:
# 1 - Command to execute
# Returns:
# Exit code of the command that was executed
function run_and_check_status() {
 "$@"
 local status=$?
 if [ ${status} -ne 0 ]
 then
  logErr "Error executing: $@, exited with code: ${status}"
 else
  logInfo "$@ executed successfully and exited with code: ${status}"
 fi
 resultSet+=("${status}")
 return ${status}
}
#####
function update_os() {
 logInfo "Updating os via yum..."
 yum update -y
 logInfo "...yum update complete"
}
#####
function update_os_cron() {
 cron_file=/etc/cron.weekly/yumupdate.cron
 echo "#!/bin/bash" > ${cron_file}
 echo "/usr/bin/yum update -y" >> ${cron_file}
 echo "needs-restarting -r" >> ${cron_file}
 echo "if [ $? -gt 0 ]; then /usr/sbin/init 6; fi" >> ${cron_file}
}
#####
function set_ip_forward() {
  echo 1 > /proc/sys/net/ipv4/ip_forward
  run_and_check_status sysctl -w net.ipv4.ip_forward=1
  run_and_check_status sed -i "s|net.ipv4.ip_forward = 0|net.ipv4.ip_forward = 1|g" /etc/sysctl.conf
  run_and_check_status sysctl -p
  run_and_check_status sysctl --system
  logInfo "enabled ip_forwarding"
}
#####
function config_ssh() {
 local cf="/etc/ssh/sshd_config"
 local hn=$(hostname -s | cut -d. -f1)
 set_string() {
  local setting="$1"
  local value="$2"
  cat $cf | grep "^$setting" &> /dev/null
  if [ $? -eq 0 ]; then
   sed -i "/^$setting/d" $cf
  fi
  cat $cf | grep "^$#setting" &> /dev/null
  if [ $? -eq 0 ]; then
   sed -i "/^#$setting/d" $cf
  fi
  echo "$setting $value" >> $cf
 }
 set_string PermitRootLogin no
 set_string PasswordAuthentication yes
 set_string LogLevel VERBOSE
 set_string GatewayPorts no
 set_string PermitTunnel no
 set_string IgnoreRhosts yes
 set_string PermitEmptyPasswords no
 set_string RhostsRSAAuthentication no
 set_string HostbasedAuthentication no
 set_string Ciphers "aes128-ctr,aes192-ctr,aes256-ctr"
 set_string MACs "hmac-sha2-256,hmac-sha2-512"
 set_string KexAlgorithms "ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521,diffie-hellman-group-exchange-sha256"
 touch /etc/banner
 echo "================================================================================" >> /etc/banner
 echo "Use of this U.S. Government (USG)-interest computer system, Standard conditions apply including consent for authorized monitoring at all times." >> /etc/banner
 echo "================================================================================" >> /etc/banner
 cat /etc/ssh/sshd_config | grep "^Banner" &> /dev/null
 if [ $? -eq 0 ]; then
  line=$(cat /etc/ssh/sshd_config | grep "^Banner")
  sed -i "s|$line|Banner /etc/banner|" /etc/ssh/sshd_config
 else
  echo "Banner /etc/banner" >> /etc/ssh/sshd_config
 fi
 echo "Restarting sshd"
 ${SYS_CTL} restart sshd
}
#####
function set_firewalld_rules() {
 logInfo "Using firewalld to configure the firewall..."
 # this is in place to work around an selinux bug
 setenforce permissive

 firewall-cmd --set-default-zone public
 logInfo "  default zone set to public"
 firewall-cmd --permanent --set-target=ACCEPT

 CODE_ADD_FIREWALLD_DNAT_RULES_HERE
 logInfo "  firewall rules added"

 firewall-cmd --permanent --add-masquerade
 logInfo "  call to set up masquerading returned $?"
 
 # create the internal zone which we'll use for traffic originating from the inside of the virt realm
 internalName="internal_subnet"
 firewall-cmd --new-zone=${internalName} --permanent
 firewall-cmd --reload
 firewall-cmd --zone=${internalName} --permanent --add-source=${subnetCidr}
 firewall-cmd --zone=${internalName} --permanent --set-target=ACCEPT
 logInfo "  internal zone set to ${internalName}"

 sed -i "s|^AllowZoneDrifting.*$|AllowZoneDrifting=no|" /etc/firewalld/firewalld.conf
 firewall-cmd --reload
 setenforce enforcing
 systemctl restart NetworkManager
 logInfo "...successfully configured NAT rules"
 return 0
}
#####
function disable_services() {
 logInfo "Disabling unnecessary services..."
 for svc in autofs cups netfs nfslock postfix rdma rpcbind rpcgssd sendmail x11vnc
 do
  logInfo "  Disabling ${svc}"
  ${SYS_CTL} disable ${svc}
 done
 logInfo "Unnecessary services disabled"
}
#####
function install_elastic_agent() {
 EA="elastic-agent-${fleetAgentVersion}-linux-x86_64"
 logInfo "installing ${EA}..."
 owd=$(pwd)
 yum -y install wget
 cd /opt
 wget https://artifacts.elastic.co/downloads/beats/elastic-agent/${EA}.tar.gz
 dl=$(echo ${?})
 if [ ${dl} -eq 0 ]
 then 
   logInfo "agent download successful"
 else 
   logInfo "wget command returned ${dl}, agent download failed"
   exit 6
 fi
 tar xzf ${EA}.tar.gz
 cd ${EA}
 fs1=${fleetServerFqdn}:${fleetManagerPort}
 fleetCaCert="/root/fleet_server.pem"
 openssl s_client -connect ${fs1} 2>/dev/null </dev/null | sed -ne '/-BEGIN CERTIFICATE-/,/-END CERTIFICATE-/p' > ${fleetCaCert}
 r1=$(echo ${?})
 if [ ${r1} -eq 0 ]
 then 
  logInfo "Fleet Manager ${fs1} is reachable"
  rootCaCert="/etc/pki/ca-trust/source/anchors/cons3rtRoot.pem"
  wget ${cons3rtRootCaUrl} -O ${rootCaCert}
  update-ca-trust
  ./elastic-agent install --url=https://${fs1} --certificate-authorities=/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem --enrollment-token=${fleetToken} --force
  logInfo "...${EA} installation complete"
 else 
  logInfo "Fleet Manager ${fs1} is NOT reachable"
  exit 6
 fi

 cd ${owd}
}
#####
function main() {
 logInfo ${TIMESTAMP} " - Running NAT User Data script"
 externalDev="$(/usr/bin/nmcli -t -f DEVICE con show --active)"
 logInfo "Determined external network device to be ${externalDev}"
 update_os
 update_os_cron
 set_ip_forward
 config_ssh
 disable_services
 set_firewalld_rules
 
 hostname ${hostname}
 echo ${hostname} > /etc/hostname
 #install_elastic_agent
 return 0
}
#
# ===
#
export PATH=$PATH:/sbin:/bin:/root/bin

yum install firewalld NetworkManager -y

${SYS_CTL} is-active --quiet NetworkManager
if [[ $? -gt 0 ]]
then
 ${SYS_CTL} enable NetworkManager
 ${SYS_CTL} start NetworkManager
fi
# log the NM config before we make any changes
logInfo "NetworkManager connections before cleanup"
logInfo "$(/usr/bin/nmcli connection show)"
${SYS_CTL} is-active --quiet firewalld
if [[ $? -gt 0 ]]
then
 logInfo "Starting firewalld:"
 ${SYS_CTL} enable firewalld
 ${SYS_CTL} start firewalld
fi

main
result=$?
logInfo "Exiting with code ${result} ..."
exit ${result}

'''

# AWS credentials file content template
aws_credentials_file_content_template = '''[default]
aws_access_key_id = REPLACE_ACCESS_KEY_ID
aws_secret_access_key = REPLACE_SECRET_ACCESS_KEY
aws_session_token = REPLACE_SESSION_TOKEN

'''

# AWS config file content template
aws_config_file_content_template = '''[default]
region = REPLACE_REGION
output = text

'''


def get_boto3_client(service, region_name=None, aws_access_key_id=None, aws_secret_access_key=None,
                     aws_session_token=None):
    """Gets an EC2 client

    :param service: (str) name of the service to configure
    :param region_name: (str) name of the region
    :param aws_access_key_id: (str) AWS Access Key ID
    :param aws_secret_access_key: (str) AWS Secret Access Key
    :param aws_session_token: (str) AWS Session Token
    :return: boto3.client object
    :raises: AWSAPIError
    """
    try:
        client = boto3.client(
            service,
            region_name=region_name,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token
        )
    except ClientError as exc:
        msg = 'Problem creating a boto3 client, ensure credentials and region are set appropriately.'
        raise AWSAPIError(msg) from exc
    return client


def get_linux_migration_user_data_script_contents():
    """Returns the user-data script content of the migration script

    :return: (str) Content of the user data script
    """
    return linux_migration_user_data_script_contents


def get_linux_nat_config_user_data_script_contents():
    """Returns the user-data script content for the NAT config script

    :return: (str) Content of the user data script
    """
    return linux_nat_config_user_data_script_contents


def read_service_config(service_config_file):
    """Reads the AWS service config properties file

    This method reads the config properties file and returns a dict

    :param service_config_file: (str) path to the AWS service config file
    :return: (dict) key-value pairs from the properties file
    """
    log = logging.getLogger(mod_logger + '.read_service_config')
    properties = {}

    # Ensure the RDS config props file exists
    if not os.path.isfile(service_config_file):
        log.error('RDS config file not found: {f}'.format(f=service_config_file))
        return properties

    log.info('Reading RDS config properties file: {r}'.format(r=service_config_file))
    with open(service_config_file, 'r') as f:
        for line in f:
            if line.startswith('#'):
                continue
            elif '=' in line:
                split_line = line.strip().split('=', 1)
                if len(split_line) == 2:
                    prop_name = split_line[0].strip()
                    prop_value = split_line[1].strip()
                    if prop_name is None or not prop_name or prop_value is None or not prop_value:
                        log.info('Property name <{n}> or value <v> is none or blank, not including it'.format(
                            n=prop_name, v=prop_value))
                    else:
                        log.debug('Adding property {n} with value {v}...'.format(n=prop_name, v=prop_value))
                        unescaped_prop_value = prop_value.replace('\\', '')
                        properties[prop_name] = unescaped_prop_value
                else:
                    log.warning('Skipping line that did not split into 2 part on an equal sign...')
    log.info('Successfully read in RDS config properties, verifying required props...')
    return properties
