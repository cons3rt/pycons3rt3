"""Module: awsutil

This module provides utilities for interacting with the AWS
API, common to other AWS utils in this project.

"""
import boto3
from botocore.client import ClientError

from .exceptions import AWSAPIError

__author__ = 'Joe Yennaco'


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


# Get the current timestamp and append to logfile name
TIMESTAMP=$(date "+%Y-%m-%d-%H%M")

######################### GLOBAL VARIABLES #########################
# DO NOT EDIT UNLESS YOU ALSO UPDATE THE CLOUDSPACE CREATE CODE

# Set to the IP address and port of the GUAC box from code
guacBoxIpAddress=CODE_REPLACE_ME_GUAC_SERVER_IP
guacBoxPort=CODE_REPLACE_ME_GUAC_SERVER_PORT
virtRealmType=CODE_REPLACE_ME_VIRT_TECH

# Array to maintain exit codes
resultSet=();

####################### END GLOBAL VARIABLES #######################

# Parameters:
# 1 - Command to execute
# Returns:
# Exit code of the command that was executed
function run_and_check_status() {
    "$@"
    local status=$?
    if [ ${status} -ne 0 ]
    then
        echo "Error executing: $@, exited with code: ${status}"
    else
        echo "$@ executed successfully and exited with code: ${status}"
    fi
    resultSet+=("${status}")
    return ${status}
}

#################################

# Test an IP address for validity
# Parameters:
# 1 - IP address to check
# Returns
# 0 - IP address is valid
# non-zero - IP address is invalid
function validateIpaddress() {
    local ip="$1"
    local stat=1
    if [[ $ip =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]
    then
        OIFS=$IFS
        IFS='.'
        ip=($ip)
        IFS=$OIFS
        [[ ${ip[0]} -le 255 && ${ip[1]} -le 255 \
        && ${ip[2]} -le 255 && ${ip[3]} -le 255 ]]
        stat=$?
    fi
    return $stat
}

#################################

function update_os() {
    echo "Updating os via yum"
    yum update -y
    echo "Yum update complete"
}

#################################

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
    echo "Use of this U.S. Government (USG)-interest computer system constitutes consent for authorized monitoring at all times." >> /etc/banner
    echo "" >> /etc/banner
    echo "This is a USG-interest computer system. This system and related equipment are intended for the communication, transmission, processing, and storage of official USG or other authorized information only. This USG-interest computer system is subject to monitoring at all times to ensure proper functioning of equipment and systems including security systems and devices, and to prevent, detect, and deter violations of statutes and security regulations and other unauthorized use of the system." >> /etc/banner
    echo "" >> /etc/banner
    echo "Communications using, or data stored on, this system are not private, are subject to routine monitoring, interception, and search, and may be disclosed or used for any authorized purpose." >> /etc/banner
    echo "" >> /etc/banner
    echo "If monitoring of this USG-interest computer system reveals possible evidence of violation of criminal statutes, this evidence and any other related information, including identification information about the user, may be provided to law enforcement officials. If monitoring of this USG-interest computer systems reveals violations of security regulations or other unauthorized use that information and other related information, including identification information about the user, may be used appropriate administrative or disciplinary action." >> /etc/banner
    echo "" >> /etc/banner
    echo "Use of this USG interest computer system constitutes consent to authorized monitoring at all times." >> /etc/banner
    echo "================================================================================" >> /etc/banner


    cat /etc/ssh/sshd_config | grep "^Banner" &> /dev/null
    if [ $? -eq 0 ]; then
        line=$(cat /etc/ssh/sshd_config | grep "^Banner")
        sed -i "s|$line|Banner /etc/banner|" /etc/ssh/sshd_config
    else
        echo "Banner /etc/banner" >> /etc/ssh/sshd_config
    fi

    echo "Restarting sshd"
    if [ ${amazon} -eq 1 ]; then
        /sbin/service sshd restart
    else
        case $os_ver in
            6 ) /sbin/service sshd restart ;;
            7 ) /sbin/systemctl restart sshd ;;
        esac
    fi
}

#################################

function openstack_resolve_external_ipaddress() {
    GUAC_A=`echo "${guacBoxIpAddress}" | awk -F. '{print $1}'`
    GUAC_B=`echo "${guacBoxIpAddress}" | awk -F. '{print $2}'`
    GUAC_C=`echo "${guacBoxIpAddress}" | awk -F. '{print $3}'`

    for candidate_ip in `hostname -I`
    do
        ipAddress=${candidate_ip}

        if [ "${GUAC_A}" == `echo ${ipAddress} | awk -F. '{print $1}'` ]
        then
            if [ "${GUAC_B}" == `echo ${ipAddress} | awk -F. '{print $2}'` ]
            then
                if [ "${GUAC_C}" == `echo ${ipAddress} | awk -F. '{print $3}'` ]
                then
                    echo "IP ${ipAddress} is in the same class C address space as GUAC IP ${guacBoxIpAddress}"
                    ipAddress=
                else
                    echo "Based on the third octet, IP ${ipAddress} is not in the same class C address space as GUAC IP ${guacBoxIpAddress}"
                fi
            else
                echo "Based on the second octet, IP ${ipAddress} is not in the same class C address space as GUAC IP ${guacBoxIpAddress}"
            fi
        else
            echo "Based on the first octet, IP ${ipAddress} is not in the same class C address space as GUAC IP ${guacBoxIpAddress}"
        fi

        if [ ! -z ${ipAddress} ]
        then
            break
        fi

    done

    if [ -z ${ipAddress} ]
    then
        echo "could not resolve a valid external IP for this NAT instance, exiting"
        return 4
    else
        echo "resolved a valid external IP for this NAT instance: ${ipAddress}"
    fi
}

#################################

function set_ip_forward() {
    echo 1 > /proc/sys/net/ipv4/ip_forward
    run_and_check_status sysctl -w net.ipv4.ip_forward=1
    run_and_check_status sed -i "s|net.ipv4.ip_forward = 0|net.ipv4.ip_forward = 1|g" /etc/sysctl.conf
    run_and_check_status sysctl -p
    run_and_check_status sysctl --system
    echo "enabled ip_forwarding"
}

#################################

function set_iptables_rules() {
    echo "Configuring nat rules (iptables) for remote access..."

    validateIpaddress ${guacBoxIpAddress}
    if [ $? -ne 0 ] ; then
        echo "ERROR: ${guacBoxIpAddress} must be a valid IP address"
        return 2
    else
        echo "Valid IP address: ${guacBoxIpAddress}"
    fi

    # Delete existing NAT rules

    echo "Deleting existing PREROUTING NAT rules..."
    rules=`iptables -L PREROUTING -t nat --line-numbers | grep DNAT`
    echo -e "Current PREROUTING rules:\n${rules}"
    while :
    do
        if [ -z "${rules}" ] ; then
            break
        fi
        run_and_check_status iptables -D PREROUTING 1 -t nat
        rules=`iptables -L PREROUTING -t nat --line-numbers | grep DNAT`
    done

    echo "Deleting existing POSTROUTING NAT rules..."
    rules=`iptables -L POSTROUTING -t nat --line-numbers | grep MASQUERADE`
    echo -e "Current POSTROUTING rules:\n${rules}"
    while :
    do
        if [ -z "${rules}" ] ; then
            break
        fi
        run_and_check_status iptables -D POSTROUTING 1 -t nat
        rules=`iptables -L POSTROUTING -t nat --line-numbers | grep MASQUERADE`
    done

    echo "Configuring nat rules..."
    CODE_ADD_IPTABLES_DNAT_RULES_HERE
    CODE_ADD_IPTABLES_SNAT_RULES_HERE

    # Default action
    run_and_check_status iptables -I FORWARD -i eth0 -j ACCEPT
    run_and_check_status iptables -I FORWARD -o eth0 -j ACCEPT

    echo "Saving iptables ..."
    run_and_check_status service iptables save

    # List NAT rules
    echo "Listing PREROUTING NAT rules ..."
    iptables -L PREROUTING -t nat --line-numbers

    echo "Listing POSTROUTING NAT rules ..."
    iptables -L POSTROUTING -t nat --line-numbers

    # Check the results of commands from this script, return error if an error is found
    for resultCheck in "${resultSet[@]}" ; do
        if [ ${resultCheck} -ne 0 ] ; then
            echo "ERROR: failed due to previous errors"
            return 3
        fi
    done

    if [ ${amazon} -eq 1 ]; then
      /sbin/service iptables start
      /sbin/chkconfig iptables on
    else
      case $os_ver in
        6 ) /sbin/service iptables start
            /sbin/chkconfig iptables on
            ;;
        7 ) systemctl stop iptables
            systemctl disable iptables
            ;;
      esac
    fi

    echo "Successfully configured NAT rules"
    return 0
}

#################################

function disable_services() {
    echo "Disabling unnecessary services"

    for svc in autofs cups netfs nfslock postfix rdma rpcbind rpcgssd sendmail x11vnc
    do
      if [ ${amazon} -eq 1 ]; then
        /sbin/service ${svc} stop
        /sbin/chkconfig ${svc} off
      else
        case $os_ver in
          6 ) /sbin/service ${svc} stop
              /sbin/chkconfig ${svc} off
              ;;
          7 ) systemctl start ${svc}
              systemctl enable ${svc}
              ;;
        esac
      fi
    done

    echo "Unnecessary services disabled"
}

#################################

function openstack_ensure_eth1_working() {
    eth1_config="/etc/sysconfig/network-scripts/ifcfg-eth1"
    if [ ! -e ${eth1_config} ]
    then
        echo "${eth1_config} is missing - attempting to repair"
        cp /etc/sysconfig/network-scripts/ifcfg-eth0 ${eth1_config}
        sed -i -e s/eth0/eth1/g ${eth1_config}
        ifup eth1
    fi
}

#################################

function main() {
    echo ${TIMESTAMP} " - Running NAT User Data script"

    # perform any system checks we need to run before continuing
    case "${virtRealmType}" in
      amazon)
        # AWS only has one interface on the NAT box, so we can safely grab the first IP
        # This value is used in the Firewall and NAT rules which are inserted (by code)
        ipAddress=`hostname -I | awk '{print $1}'`
        ;;
      azure)
        ;;
      openstack)
        # OpenStack has had issues in the past where eth1 doesn't get set up, make sure it is
        run_and_check_status openstack_ensure_eth1_working

        # OpenStack has TWO interfaces on the NAT box, so we can't just grab the first one (like we can in AWS)
        # We need to get the IP which isn't on the same subnet as the guac server
        # This value is used in the Firewall and NAT rules which are inserted (by code)
        run_and_check_status openstack_resolve_external_ipaddress
        ;;
    esac

    update_os
    set_ip_forward
    set_iptables_rules
    config_ssh
    disable_services

    return 0
}

#
# ====================================================================================
#

# init local variable setup
amazon=0
atomic=0
os_ver=0

# resolve local variables
if [ -e /etc/redhat-release ]; then
    cat /etc/redhat-release | grep Atomic &> /dev/null
    if [ $? -eq 0 ]; then
        os_ver=7
        atomic=1
    else
        cat /etc/redhat-release | grep "Red Hat" &> /dev/null
        if [ $? -eq 0 ]; then
            # RedHat uses this format for the release file
            os_ver=$(cat /etc/redhat-release | awk '{ print $7 }' | cut -d. -f1)
        fi

        cat /etc/redhat-release | grep "CentOs" &> /dev/null
        if [ $? -eq 0 ]; then
            # CentOS uses this format
            os_ver=$(cat /etc/redhat-release | awk '{ print $4 }' | cut -d. -f1)
        fi
    fi
elif [ -e /etc/issue ]; then
    cat /etc/issue | grep Amazon &> /dev/null
    if [ $? -eq 0 ]; then
        amazon=1
    fi
else
    os_ver=$(uname -m)
    if [ "$os_ver" == "armv7l" ]; then
        os_ver=99
    fi
    atomic=0
fi

main
result=$?

echo "Exiting with code ${result} ..."
exit ${result}

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
