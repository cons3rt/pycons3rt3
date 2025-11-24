#!/bin/bash
#
# setup.sh
#
# Use this script to setup pycons3rt3
#
# Usage:
#     ./scripts/setup.sh [ARGS]
#
# Args:
#     1 - Path for the parent directory of the virtual environment called "venv" (DEFAULT = $HOME)
#
#
#

# Ensure running from the repo
repoDir=$(git rev-parse --show-toplevel)
if [ $? -ne 0 ]; then echo "ERROR: Run this command from the homer git repo"; exit 1; fi
cd ${repoDir}/

# Arg for venv location
defaultVenvLocation="${HOME}"
userSpecifiedVenvLocation="${1}"

# Ensure the script is running from the pycons3rt3 directory
if [ ! -f ${repoDir}/pycons3rt3/VERSION.txt ]; then
    echo "ERROR: Please run this script from the top-level driectory of the pycons3rt3 git repo"
    exit 1
fi

echo "Setting up pycons3rt3..."

# Ensure python3 exists
python3Exe=$(which python3)
if [ $? -ne 0 ]; then
    echo "python3 not detected, please install python3 to continue"
    exit 1
fi

if [ -z "${userSpecifiedVenvLocation}" ]; then
    read -p "Type path to parent directory for the virtual environment venv directory [default: ${HOME}]" userSpecifiedVenvLocation
else
    echo "Using the provided arg for userSpecifiedVenvLocation: ${userSpecifiedVenvLocation}"
fi

echo "Creating a virtual environment..."
parentDir="${defaultVenvLocation}"
if [ -z "${userSpecifiedVenvLocation}" ]; then
    echo "Using default parent directory for venv: ${parentDir}"
else
    parentDir="${userSpecifiedVenvLocation}"
    if [ ! -d ${userSpecifiedVenvLocation} ]; then
        echo "ERROR: User-specified parent-directory for venv not found: ${parentDir}"
        exit 3
    fi
    echo "Using user-provided parent directory for venv: ${parentDir}"
fi

# Create the virtual environment
cd ${parentDir}/
echo "Creating venv..."
python3 -m venv venv
if [ $? -ne 0 ]; then echo "Problem creating venv in directory: ${parentDir}"; exit 4; fi

# Activate the virtual environment
echo "Activating the virtual environment..."
. ${parentDir}/venv/bin/activate
if [ $? -ne 0 ]; then echo "Problem activating the virtual environment in: ${parentDir}/venv"; exit 5; fi

# upgrade pip in the venv
echo "Upgrading pip in the virtual environment..."
python3 -m pip install pip --upgrade
if [ $? -ne 0 ]; then echo "Problem upgrading pip in the virtual environment: ${parentDir}/venv"; exit 6; fi

# Install prereqs
cd ${repoDir}/
echo "Installing prerequisites..."
python3 -m pip install -r ./requirements.txt
if [ $? -ne 0 ]; then echo "Problem installing prerequisite packages from requirements.txt"; exit 7; fi

# Install pycons3rt3
echo "Installing pycons3rt3..."
python3 -m pip install .
if [ $? -ne 0 ]; then echo "Problem installing pycons3rt3"; exit 8; fi

echo "Completed installation of pycons3rt3 into virtual environment: ${parentDir}/venv"
exit 0
