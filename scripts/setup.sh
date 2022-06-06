#!/bin/bash

defaultVenvLocation="${HOME}"
workingDir=$(pwd)

# Ensure the script is running from the pycons3rt3 directory
if [ ! -f ${workingDir}/pycons3rt3/VERSION.txt ]; then
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

echo "Installing virtualenv..."
python3 -m pip install virtualenv
if [ $? -ne 0 ]; then echo "Problem installing the virtualenv package from pip"; exit 2; fi

echo "Creating a virtual environment..."
read -p "Type path to parent directory for the virtual environment venv directory [default: ${HOME}]" userSpecifiedVenvLocation

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
python3 -m virtualenv venv
if [ $? -ne 0 ]; then echo "Problem creating venv in directory: ${parentDir}"; exit 4; fi

# Activate the virtual environment
echo "Activating the virtual environment..."
. ./venv/bin/activate
if [ $? -ne 0 ]; then echo "Problem activating the virtual environment in: ${parentDir}/venv"; exit 5; fi

# Print the python3 in use
echo "Using python3: "
which python3

# Print the version
echo "Using python3 version: "
python3 --version

# upgrade pip in the venv
echo "Upgrading pip in the virtual environment..."
python3 -m pip install pip --upgrade
if [ $? -ne 0 ]; then echo "Problem upgrading pip in the virtual environment: ${parentDir}/venv"; exit 6; fi

# Install prereqs
cd ${workingDir}/
echo "Installing prerequisites..."
python3 -m pip install -r ./cfg/requirements.txt
if [ $? -ne 0 ]; then echo "Problem installing prerequisite packages from cfg/requirements.txt"; exit 7; fi

# Install pycons3rt3
echo "Installing pycons3rt3..."
python3 setup.py install
if [ $? -ne 0 ]; then echo "Problem installing pycons3rt3"; exit 8; fi

echo "Completed installation of pycons3rt3 into virtual environment: ${parentDir}/venv"
exit 0
