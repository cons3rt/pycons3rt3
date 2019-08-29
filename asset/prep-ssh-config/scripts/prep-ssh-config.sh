#!/bin/bash

# Source the environment
if [ -f /etc/bashrc ] ; then
    . /etc/bashrc
fi
if [ -f /etc/profile ] ; then
    . /etc/profile
fi

# Establish a log file and log tag
logTag="prep-for-ssh-config"
logDir="/opt/cons3rt-agent/log"
logFile="${logDir}/${logTag}-$(date "+%Y%m%d-%H%M%S").log"

######################### GLOBAL VARIABLES #########################

# Deployment properties
deploymentHome=
deploymentPropertiesFile=

# The linux distro
distroId=
distroVersion=
distroFamily=

# Marker file to indicate this host is ready for configuration over SSH
markerFile="/root/SSH_READY"

####################### END GLOBAL VARIABLES #######################

# Logging functions
function timestamp() { date "+%F %T"; }
function logInfo() { echo -e "$(timestamp) ${logTag} [INFO]: ${1}" >> ${logFile}; }
function logWarn() { echo -e "$(timestamp) ${logTag} [WARN]: ${1}" >> ${logFile}; }
function logErr() { echo -e "$(timestamp) ${logTag} [ERROR]: ${1}" >> ${logFile}; }

function set_deployment_home() {
    # Ensure DEPLOYMENT_HOME exists
    if [ -z "${DEPLOYMENT_HOME}" ] ; then
        logWarn "DEPLOYMENT_HOME is not set, attempting to determine..."
        deploymentDirCount=$(ls /opt/cons3rt-agent/run | grep Deployment | wc -l)
        # Ensure only 1 deployment directory was found
        if [ ${deploymentDirCount} -ne 1 ] ; then
            logErr "Could not determine DEPLOYMENT_HOME"
            return 1
        fi
        # Get the full path to deployment home
        deploymentDir=$(ls /opt/cons3rt-agent/run | grep "Deployment")
        deploymentHome="/opt/cons3rt-agent/run/${deploymentDir}"
        export DEPLOYMENT_HOME="${deploymentHome}"
    else
        deploymentHome="${DEPLOYMENT_HOME}"
    fi
}

function read_deployment_properties() {
    local deploymentPropertiesFile="${DEPLOYMENT_HOME}/deployment-properties.sh"
    if [ ! -f ${deploymentPropertiesFile} ] ; then
        logErr "Deployment properties file not found: ${deploymentPropertiesFile}"
        return 1
    fi
    . ${deploymentPropertiesFile}
    return $?
}

function get_distro() {
    if [ -f /etc/os-release ] ; then
        . /etc/os-release
        if [ -z "${ID}" ] ; then logErr "Linux distro ID not found"; return 1;
        else distroId="${ID}"; fi;
        if [ -z "${VERSION_ID}" ] ; then logErr "Linux distro version ID not found"; return 2
        else distroVersion=$(echo "${VERSION_ID}" | awk -F . '{print $1}'); fi;
        if [ -z "${ID_LIKE}" ] ; then logErr "Linux distro family not found"; return 3
        else distroFamily="${ID_LIKE}"; fi;
    elif [ -f /etc/centos-release ] ; then
        distroId="centos"
        distroVersion=$(cat /etc/centos-release | sed "s|Linux||" | awk '{print $3}' | awk -F . '{print $1}')
        distroFamily="rhel fedora"
    elif [ -f /etc/redhat-release ] ; then
        distroId="redhat"
        distroVersion=$(cat /etc/redhat-release | awk '{print $7}' | awk -F . '{print $1}')
        distroFamily="rhel fedora"
    else logErr "Unable to determine the Linux distro or version"; return 4; fi;
    if [[ ${distroId} == "rhel" ]] ; then
        logInfo "Found distroId: rhel, setting to redhat..."
        distroId="redhat"
    fi
    logInfo "Detected Linux Distro ID: ${distroId}"
    logInfo "Detected Linux Version ID: ${distroVersion}"
    logInfo "Detected Linux Family: ${distroFamily}"
    return 0
}

function open_firewall() {
    logInfo "Opening the firewall for SSH..."
    which firewall-cmd >> ${logFile} 2>&1
    if [ $? -eq 0 ]; then
        logInfo "firewalld found..."
        firewall-cmd --add-service ssh >> ${logFile} 2>&1
        if [ $? -ne 0 ]; then logErr "There was a problem configuring firewalld"; return 1; fi
    else
        logInfo "firewalld not found using iptables..."
        iptables -F >> ${logFile} 2>&1
        if [ $? -ne 0 ]; then logErr "There was a problem configuring iptables"; return 2; fi
    fi
    logInfo "Completed firewall configuration"
    return 0
}

function allow_passwordless_ssh() {
    logInfo "Updating sshd config to allow passwordless SSH..."

    logInfo "Updating /etc/ssh/sshd_config..."
    sed -i "/^PermitRootLogin=.*$/d" /etc/ssh/sshd_config
    sed -i "/^PasswordAuthentication=.*$/d" /etc/ssh/sshd_config
    sed -i "/^PermitEmptyPasswords=.*$/d" /etc/ssh/sshd_config
    sed -i "/^RSAAuthentication=.*$/d" /etc/ssh/sshd_config
    sed -i "/^PubkeyAuthentication=.*$/d" /etc/ssh/sshd_config
    echo "PermitRootLogin=yes" >> /etc/ssh/sshd_config
    echo "PasswordAuthentication=yes" >> /etc/ssh/sshd_config
    echo "PermitEmptyPasswords=yes" >> /etc/ssh/sshd_config
    echo "RSAAuthentication=yes" >> /etc/ssh/sshd_config
    echo "PubkeyAuthentication=yes" >> /etc/ssh/sshd_config

    logInfo "Restarting sshd..."
    restartComplete=0
    which systemctl >> ${logFile} 2>&1
    if [ $? -eq 0 ]; then
        logInfo "Running systemctl restart sshd"
        systemctl restart sshd >> ${logFile} 2>&1
        if [ $? -ne 0 ]; then logErr "There was a problem restarting sshd with systemctl"; return 1; fi
        restartComplete=1
    fi
    if [ ${restartComplete} -eq 1 ]; then return 0; fi
    which service >> ${logFile} 2>&1
    if [ $? -eq 0 ]; then
        logInfo "Running service sshd restart"
        service sshd restart >> ${logFile} 2>&1
        if [ $? -ne 0 ]; then logErr "There was a problem restarting sshd with service command"; return 2; fi
        restartComplete=1
    fi
    if [ ${restartComplete} -eq 0 ]; then
        logErr "Could not determine method to restart sshd"
        return 3
    fi
    return 0
}

function remove_root_user_password() {
    logInfo "Removing the root user password..."
    passwd -d root >> ${logFile} 2>&1
    return $?
}

function stage_marker_file() {
    logInfo "Staging the marker file: ${markerFile}"
    touch ${markerFile} >> ${logFile} 2>&1
    return $?
}

function main() {
    set_asset_dir
    set_deployment_home
    read_deployment_properties
    get_distro
    open_firewall
    if [ $? -ne 0 ]; then logErr "Problem configuring firewall"; return 1; fi
    allow_passwordless_ssh
    if [ $? -ne 0 ]; then logErr "Problem configuring ssh"; return 2; fi
    remove_root_user_password
    if [ $? -ne 0 ]; then logErr "Problem removing the root user password"; return 3; fi
    stage_marker_file
    if [ $? -ne 0 ]; then logErr "Problem staging the marker file"; return 4; fi
    logInfo "Successfully completed: ${logTag}"
    return 0
}

# Set up the log file
mkdir -p ${logDir}
chmod 700 ${logDir}
touch ${logFile}
chmod 644 ${logFile}

main
result=$?
cat ${logFile}

logInfo "Exiting with code ${result} ..."
exit ${result}
