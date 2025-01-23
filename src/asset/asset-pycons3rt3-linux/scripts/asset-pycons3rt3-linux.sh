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

# List of prereq packages to install before pip
prereqPackages="gcc git python3-pip"

# Git repo info
gitRepoUrl="https://github.com/cons3rt/pycons3rt3"
defaultGitBranch="master"
branch=

# Destination directory to clone into and clone directory
destinationDir=
cloneDir=

# Executables
python3Exe=
gitExe=

# The username of the cons3rt-created user
CONS3RT_CREATED_USER=

####################### END GLOBAL VARIABLES #######################

# Logging functions
function timestamp() { date "+%F %T"; }
function logInfo() { echo -e "$(timestamp) ${logTag} [INFO]: ${1}" >> ${logFile}; }
function logWarn() { echo -e "$(timestamp) ${logTag} [WARN]: ${1}" >> ${logFile}; }
function logErr() { echo -e "$(timestamp) ${logTag} [ERROR]: ${1}" >> ${logFile}; }

function clone_git() {
    logInfo "Cloning the source code form GitHub..."

    logInfo "Cloning branch [${branch}] git repo from URL [${gitRepoUrl}] to directory [${cloneDir}] as user [${CONS3RT_CREATED_USER}]..."
    runuser -l ${CONS3RT_CREATED_USER} -c "cd ${destinationDir}; git clone -b ${branch} ${gitRepoUrl}" >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logErr "Cloning branch [${branch}] git repo from URL [${gitRepoUrl}] to directory [${cloneDir}] as user [${CONS3RT_CREATED_USER}]"; return 1; fi

    logInfo "Completed cloning the source code from GitHub"
    return 0
}

function create_destination_dir() {
    logInfo "Creating the destination directory to clone into..."

    # Create the directory if it does not exist
    if [ ! -d ${destinationDir} ]; then
        logInfo "Creating destination directory: [${destinationDir}]..."
        mkdir -p ${destinationDir} >> ${logFile} 2>&1
        if [ $? -ne 0 ]; then logErr "Creating destination directory: [${destinationDir}]"; return 1; fi
    else
        # Delete existing clone directory
        if [ -d ${cloneDir} ]; then
            logInfo "Deleting existing clone directory: [${cloneDir}]..."
            rm -Rf ${cloneDir} >> ${logFile} 2>&1
            if [ $? -ne 0 ]; then logErr "Deleting existing clone directory: [${cloneDir}]"; return 1; fi
        else
            logInfo "Found existing directory [${destinationDir}], but no clone directory [${cloneDir}]"
        fi
    fi

    # Set ownership to the cons3rt-created user
    logInfo "Setting ownership of [${destinationDir}] to the cons3rt-created user [${CONS3RT_CREATED_USER}]..."
    chown -R ${CONS3RT_CREATED_USER}:${CONS3RT_CREATED_USER} ${destinationDir} >> ${logFile} 2>&1
    if [ $? -ne 0 ]; then logErr "Setting ownership of [${destinationDir}] to the cons3rt-created user [${CONS3RT_CREATED_USER}]"; return 1; fi

    logInfo "Completed creating the destination directory to clone into"
    return 0
}

function determine_git_branch() {
    logInfo "Determining the git branch to install from source..."

    if [ -z "${PYCONS3RT3_BRANCH}" ]; then
        logInfo "PYCONS3RT3_BRANCH custom property not found, using default branch: ${defaultGitBranch}"
        branch="${defaultGitBranch}"
    else
        branch="${PYCONS3RT3_BRANCH}"
        logInfo "Found custom property PYCONS3RT3_BRANCH, using branch: ${branch}"
    fi

    logInfo "Completed determining the git branch to install from source"
    return 0
}

function install_prerequisites() {
    logInfo "Installing the prerequisite packages..."

    # Install gcc and python-dev as required
    packageManagerCommand="yum -y install"
    which dnf >> ${logFile} 2>&1
    if [ $? -eq 0 ] ; then
        logInfo "Detected dnf on this system, dnf will be used to install packages"
        packageManagerCommand="dnf -y install"
    fi

    which apt-get >> ${logFile} 2>&1
    if [ $? -eq 0 ] ; then
        logInfo "Detected apt-get on this system, apt-get will be used to install packages"
        packageManagerCommand="apt-get -y install"
    fi

    # Determine the full install command
    installCommand="${packageManagerCommand} ${prereqPackages}"
    logInfo "Running command: [${installCommand}]..."
    ${installCommand} >> ${logFile} 2>&1
    if [ $? -ne 0 ] ; then logErr "Running command: [${installCommand}]"; return 1; fi

    logInfo "Successfully installed the prerequisites packages"
    return 0
}

function install_pycons3rt3() {
    logInfo "Installing pycons3rt3 and requirements from source..."

    # Upgrade pip for the user
    logInfo "Upgrading pip for user: [${CONS3RT_CREATED_USER}]..."
    runuser -l ${CONS3RT_CREATED_USER} -c "python3 -m pip install --user pip --upgrade" >> ${logFile} 2>&1
    if [ $? -ne 0 ] ; then logErr "Upgrading pip for user: [${CONS3RT_CREATED_USER}]"; return 1; fi

    # Install pyopenssl and upgrade to the latest to avoid
    # AttributeError: module 'lib' has no attribute 'X509_V_FLAG_CB_ISSUER_CHECK'
    logInfo "Upgrading pyopenssl for user: [${CONS3RT_CREATED_USER}]..."
    runuser -l ${CONS3RT_CREATED_USER} -c "python3 -m pip install --user pyopenssl --upgrade" >> ${logFile} 2>&1
    if [ $? -ne 0 ] ; then logErr "Upgrading pyopenssl for user: [${CONS3RT_CREATED_USER}]"; return 1; fi

    # Install the requirements
    logInfo "Installing prerequisites into python3 for user: [${CONS3RT_CREATED_USER}]..."
    runuser -l ${CONS3RT_CREATED_USER} -c "cd ${cloneDir}; python3 -m pip install --user -r requirements.txt" >> ${logFile} 2>&1
    if [ $? -ne 0 ] ; then logErr "Installing prerequisites into python3 for user: [${CONS3RT_CREATED_USER}]"; return 1; fi

    # Install pycons3rt3 from source
    logInfo "Installing pycons3rt3 into python3 for user: [${CONS3RT_CREATED_USER}]..."
    runuser -l ${CONS3RT_CREATED_USER} -c "cd ${cloneDir}; python3 -m pip install --user ." >> ${logFile} 2>&1
    if [ $? -ne 0 ] ; then logErr "Installing pycons3rt3 into python3 for user: [${CONS3RT_CREATED_USER}]"; return 1; fi

    logInfo "Installing pycons3rt3 and requirements from source"
    return 0
}

function set_deployment_home() {
    # Ensure DEPLOYMENT_HOME exists
    if [ -z "${DEPLOYMENT_HOME}" ] ; then
        local deploymentDirCount=$(ls /opt/cons3rt-agent/run | grep Deployment | wc -l)

        # Ensure only 1 deployment directory was found
        if [ ${deploymentDirCount} -ne 1 ] ; then
            logErr "Could not determine DEPLOYMENT_HOME"
            return 1
        fi

        # Get the full path to deployment home
        local deploymentDir=$(ls /opt/cons3rt-agent/run | grep "Deployment")
        local deploymentHome="/opt/cons3rt-agent/run/${deploymentDir}"
        export DEPLOYMENT_HOME="${deploymentHome}"
    else
        local deploymentHome="${DEPLOYMENT_HOME}"
    fi

    # Set the environment file if not already
    if [ ! -f /etc/profile.d/cons3rt_deployment_home.sh ]; then
        if [[ "$(whoami)" == "root" ]]; then
            echo "Creating file: /etc/profile.d/cons3rt_deployment_home.sh"
            echo "export DEPLOYMENT_HOME=\"${deploymentHome}\"" > /etc/profile.d/cons3rt_deployment_home.sh
            chmod 644 /etc/profile.d/cons3rt_deployment_home.sh
        fi
    fi
    return 0
}

function set_deployment_run_home() {
    # Set DEPLOYMENT_HOME if not already
    set_deployment_home

    # Ensure DEPLOYMENT_RUN_HOME exists
    if [ -z "${DEPLOYMENT_RUN_HOME}" ] ; then
        local deploymentRunDir="${DEPLOYMENT_HOME}/run"
        if [ ! -d ${deploymentRunDir} ]; then logErr "Deployment run directory not found: ${deploymentRunDir}"; return 1; fi
        local deploymentRunDirCount=$(ls ${deploymentRunDir}/ | wc -l)

        # Ensure only 1 deployment directory was found
        if [ ${deploymentRunDirCount} -ne 1 ] ; then
            logErr "Could not determine DEPLOYMENT_RUN_HOME"
            return 1
        fi

        # Get the deployment run ID
        local deploymentRunId=$(ls ${deploymentRunDir}/)
        if [ -z "${deploymentRunId}" ]; then logErr "Problem finding the deployment run ID directory in directory: ${deploymentRunDir}"; return 1; fi

        # Set the deployment run home
        local deploymentRunHome="${deploymentRunDir}/${deploymentRunId}"
        export DEPLOYMENT_RUN_HOME="${deploymentRunHome}"
        if [ ! -d ${deploymentRunHome} ]; then logErr "Deployment run home not found: ${deploymentRunHome}"; return 1; fi
    else
        local deploymentRunHome="${DEPLOYMENT_RUN_HOME}"
    fi

    # Set the environment file if not already
    if [ ! -f /etc/profile.d/cons3rt_deployment_run_home.sh ]; then
        if [[ "$(whoami)" == "root" ]]; then
            echo "Creating file: /etc/profile.d/cons3rt_deployment_run_home.sh"
            echo "export DEPLOYMENT_RUN_HOME=\"${deploymentRunHome}\"" > /etc/profile.d/cons3rt_deployment_run_home.sh
            chmod 644 /etc/profile.d/cons3rt_deployment_run_home.sh
        fi
    fi
    return 0
}

function read_deployment_run_properties() {
    if [ -z "${DEPLOYMENT_RUN_HOME}" ]; then set_deployment_run_home; fi
    if [ -z "${DEPLOYMENT_RUN_HOME}" ]; then logErr "Problem setting DEPLOYMENT_RUN_HOME, unable to read deployment run properties files"; return 1; fi
    local deploymentRunPropertiesFile="${DEPLOYMENT_RUN_HOME}/deployment-properties.sh"
    if [ ! -f ${deploymentRunPropertiesFile} ] ; then
        logErr "Deployment run properties file not found: ${deploymentRunPropertiesFile}"
        return 1
    fi
    logInfo "Reading properties file: ${deploymentRunPropertiesFile}"
    . ${deploymentRunPropertiesFile}
    return $?
}

function verify_prerequisites() {
    logInfo "Verifying prerequisites..."

    # Verify python3 is installed
    python3Exe=$(which python3)
    if [ $? -ne 0 ]; then logErr "Problem finding the python3 executable"; return 1; fi
    if [ ! -f ${python3Exe} ]; then logErr "python3 executable not found: ${python3Exe}"; return 1; fi
    logInfo "Using python3: [${python3Exe}]"

    # Verify git is installed
    gitExe=$(which git)
    if [ $? -ne 0 ]; then logErr "Problem finding the git executable"; return 1; fi
    if [ ! -f ${gitExe} ]; then logErr "python3 executable not found: ${python3Exe}"; return 1; fi
    logInfo "Using git: [${gitExe}]"

    # Ensure the cons3rt-created user is found
    if [ -z "${cons3rt_user}" ]; then logErr "Required deployment run property not found: [cons3rt_user]"; return 1; fi
    CONS3RT_CREATED_USER="${cons3rt_user}"
    logInfo "Using CONS3RT_CREATED_USER: [${CONS3RT_CREATED_USER}]"

    # Set the destination directory
    destinationDir="/home/${CONS3RT_CREATED_USER}/src"
    logInfo "Using destination directory: [${destinationDir}]"

    # Set the clone directory
    cloneDir="${destinationDir}/pycons3rt3"
    logInfo "Using clone directory: [${cloneDir}]"

    logInfo "Completed verifying prerequisites"
    return 0
}

function main() {
    logInfo "Running installation: [${logTag}]..."
    read_deployment_run_properties
    if [ $? -ne 0 ]; then logErr "Problem reading the deployment run properties"; return 1; fi
    install_prerequisites
    if [ $? -ne 0 ]; then logErr "Problem installing prerequisites"; return 2; fi
    verify_prerequisites
    if [ $? -ne 0 ]; then logErr "Problem verifying prerequisites"; return 3; fi
    determine_git_branch
    if [ $? -ne 0 ]; then logErr "Problem determining the git branch to clone"; return 4; fi
    create_destination_dir
    if [ $? -ne 0 ]; then logErr "Problem creating the destination directory to clone into"; return 5; fi
    clone_git
    if [ $? -ne 0 ]; then logErr "Problem cloning source from GitHub"; return 6; fi
    install_pycons3rt3
    if [ $? -ne 0 ]; then logErr "Problem installing pycons3rt3"; return 7; fi
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
