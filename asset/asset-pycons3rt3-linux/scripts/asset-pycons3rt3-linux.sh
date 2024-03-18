#!/bin/bash

# Source the environment
if [ -f /etc/bashrc ] ; then
    . /etc/bashrc
fi
if [ -f /etc/profile ] ; then
    . /etc/profile
fi

# Establish a log file and log tag
logTag="pycons3rt3-linux"
logDir="/opt/cons3rt-agent/log"
logFile="${logDir}/${logTag}-$(date "+%Y%m%d-%H%M%S").log"

######################### GLOBAL VARIABLES #########################

gitRepoUrl="https://github.com/cons3rt/pycons3rt3"
branch="master"
destinationDir="/root"

# List of prereq packages to install before pip
prereqPackages="gcc git"

# python3 and pip3 executables
python3Exe=
pip3Exe=

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

function install_prerequisites() {
    # Install pycons3rt prerequisites including boto3 and pip
    logInfo "Installing prerequisite packages..."

    # Install gcc and python-dev as required
    packageManagerCommand="yum -y install"
    which dnf >> ${logFile} 2>&1
    if [ $? -eq 0 ] ; then
    logInfo "Detected dnf on this system, dnf will be used to install packages"
        packageManagerCommand="dnf --assumeyes install"
    fi

    which apt-get >> ${logFile} 2>&1
    if [ $? -eq 0 ] ; then
        logInfo "Detected apt-get on this system, apt-get will be used to install packages"
        packageManagerCommand="apt-get -y install"
    fi

    installCommand="${packageManagerCommand} ${prereqPackages}"
    logInfo "Using package manager command: ${installCommand}"
    ${installCommand} >> ${logFile} 2>&1
    if [ $? -ne 0 ] ; then
        logErr "Unable to install prerequisites for the AWS CLI and python packages"
        return 2
    else
        logInfo "Successfully installed prerequisites"
    fi

    logInfo "Successfully installed the pycons3rt prerequisites"
    return 0
}

function main() {
    set_deployment_home
    read_deployment_properties
    install_prerequisites
    if [ $? -ne 0 ]; then logErr "There was a problem installing prerequisites"; return 1; fi
    which git
    if [ $? -ne 0 ]; then logErr "git not found"; return 2; fi

    # Determine python3 and pip
    python3Exe=$(which python3)
    if [ $? -ne 0 ]; then
        logInfo "python3 not found, checking for installed version..."
        python3Exe="/usr/local/python3/bin/python3.8"
    fi
    pip3Exe=$(which pip3)
    if [ $? -ne 0 ]; then
        logInfo "pip3 not found, checking for installed version..."
        pip3Exe="/usr/local/python3/bin/pip3.8"
    fi

    # Ensure python and pip exist
    if [ ! -f ${python3Exe} ]; then
        logErr "python3 executable not found: ${python3Exe}"
        return 3
    fi
    if [ ! -f ${pip3Exe} ]; then
        logErr "pip executable not found: ${pip3Exe}"
        return 4
    fi

    if [ -z "${PYCONS3RT3_BRANCH}" ]; then
        logInfo "PYCONS3RT3_BRANCH custom property not found, using default branch: ${branch}"
    else
        branch="${PYCONS3RT3_BRANCH}"
        logInfo "Found custom property PYCONS3RT3_BRANCH, using branch: ${branch}"
    fi

    if [ ! -d ${destinationDir} ]; then
        mkdir -p ${destinationDir}
    fi

    logInfo "Changing to dir: ${destinationDir}"
    cd ${destinationDir}/
    logInfo "Cloning git repo: ${gitRepoUrl}"
    git clone -b ${branch} ${gitRepoUrl} >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logErr "Problem cloning git repo: ${gitRepoUrl}"; return 5; fi

    logInfo "Changing to ${destinationDir}/pycons3rt3..."
    cd ${destinationDir}/pycons3rt3/

    logInfo "Installing prerequisites..."
    ${pip3Exe} install build >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logErr "Installing prerequisites"; return 6; fi

    logInfo "Installing pycons3rt3..."
    ${python3Exe} -m build >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logErr "Problem installing pycons3rt3"; return 7; fi

    # Exit successfully
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
