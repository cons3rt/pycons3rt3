# pycons3rt3

Python3 integration for CONS3RT

## Features

* Logging framework
* Python3 SDK for the CONS3RT API
* Gather CONS3RT deployment info and properties
* Run Linux commands from python
* Configure networking
* Integrate with AWS S3 and EC2
* Nexus Artifact Repository downloads
* Post to Slack

## Installation

#### Install from pip

If you have Python 3.6+ installed, you can run one of the following:

`pip3 install pycons3rt3`
`python3 -m pip install pycons3rt3`

#### Install from source

~~~
git clone https://github.com/cons3rt/pycons3rt3
cd pycons3rt3
python3 -m venv venv
source venv/bin/activate
python3 -m pip install build
python3 -m pip install .
~~~

## Directories

When installed, pycons3rt determines and creates a system directory (`pycons3rt_system_home`) and 
a local user directory (`pycons3rt_user_home`).

The default locations for `pycons3rt_system_home` are here:

* Linux: `~/.cons3rt`
* MacOS: `~/.cons3rt`
* Windows: `C:\cons3rt`

The default locations for `pycons3rt_user_home` is: `~/.cons3rt` on all OS types.

### PYCONS3RT_HOME environment variable

To change the location of `pycons3rt_system_home` and `pycons3rt_user_home`, set the environment variable  
`PYCONS3RT_HOME` to an existing directory.  This directory will be used for both system and user home directories.

To do this on Linux or macOS, add the following to `~/.bash_profile`:

```
export PYCONS3RT_HOME="/path/to/desired/directory"
```

On Windows, add the `PYCONS3RT_HOME` environment variable to the system settings.

The following directories are also created:

* Config: `pycons3rt_system_home/conf/`
* Logs: `pycons3rt_user_home/log/`
* Source: `pycons3rt_user_home/src/`

If installed from source via asset, the asset clones the pycons3rt source code here for installation:

* `pycons3rt_user_home/src/pycons3rt`

The logging configuration file is installed here:

* `pycons3rt_system_home/conf/pycons3rt-logging.conf`

By default, pycons3rt log files will output here:

* `pycons3rt_user_home/log/pycons3rt-info.log`
* `pycons3rt_user_home/log/pycons3rt-warn.log`
* `pycons3rt_user_home/log/pycons3rt-debug.log`

## CONS3RT ReST API and CLI

pycons3rt3 provides a python3 SDK for using the CONS3RT ReST API.

To access the ReST API you will need:

* An active CONS3RT Account
* Access to a project
* A CONS3RT project-based ReST API token
* For sites that require Client Certificate Authentication you will need a valid PKI certificate (ECA) 

> pycons3rt3 does **not** support CAC authentication at this time

If you have an ECA certificate in p12 or pfx format, convert it to a password-less pem file:

`openssl pkcs12 -in certfile.pfx -out certfile.pem -nodes`

## Configuration

To configure pycons3rt3 for the CONS3RT ReST API type:

`cons3rt config`

After entering your info, a config file is created here:

`pycons3rt_user_home/conf/config.json`

This configuration will automatically load for ReST API calls.

# asset CLI

The asset CLI command helps you automatically create and import assets:

```
# Validate an asset structure
asset validate --asset_dir=/path/to/asset

# Create a valid asset zip file
asset create --asset_dir=/path/to/asset
```

* Creates an asset zip file `AssetName.zip` in your Downloads directory

Specify the destination directory:

`asset create --asset_dir=/path/to/asset --dest_dir=/path/to/directory`

* Creates an asset zip file `AssetName.zip` in the specified directory

Import an asset into CONS3RT:

`asset import --asset_dir=/path/to/asset`

* Creates an asset zip, and imports the zip file into CONS3RT
* Adds an `asset.yml` file to the asset directory with the site info and asset ID

Import an asset and set the visibility to the project-level:

`asset import --asset_dir=/path/to/asset --visibility=OWNING_PROJECT`

Update an existing asset in CONS3RT:

`asset update --asset_dir=/path/to/asset`

* Uses the asset ID in the asset.yml file
* Creates an asset zip, and updates the asset ID

Update an asset and set the visibility to the community-level:

`asset update --asset_dir=/path/to/asset --visibility=COMMUNITY`

Query for software assets:

`asset query --asset_type=software`

Query for the latest community container asset containing "nginx":

`asset query --asset_type=containers --asset_subtype=DOCKER --expanded --community --name nginx --latest`

Use the `queryids` command to query for just the latest asset ID for asset with name "nginx":

`asset queryids --asset_type=containers --latest --name=nginx`

# cons3rt CLI

Usage:

`cons3rt <command> <subcommands> <args>`

Interactive command to create a `config.json` file:

`cons3rt config`

> This creates a config file at the default location: `~/.cons3rt/conf/config.json`

> If `PYCONS3RT_HOME` environment variable is defined, config file location: `${PYCONS3RT_HOME}/conf/config.json`

Specify a config file location:

`cons3rt --config /path/to/config.json <command> <subcommands> <args>`

## cons3rt cloud CLI

Permissions:
* **Team Manager** role

The `--id=1` or `--ids=1,2,3` args indicate cloud IDs

```
# Delete a cloud
cons3rt cloud delete --id=1

# List clouds
cons3rt cloud list

# Retrieve cloud details
cons3rt cloud retrieve --id=1

# Share a template from the cloud template provider to all other cloudspaces in the cloud
cons3rt cloud template --id=1 --share --name 'cons3rt-redhat-8'

# Share all templates from the cloud template provider to all other cloudspaces in the cloud
cons3rt cloud template --id=1 --share --all

# List deployment runs in the cloud(s)
cons3rt cloud run list --id=1 
cons3rt cloud run list --ids=1,2,3,4,5

# list deployment run hosts in the cloud(s)
cons3rt cloud run hosts --id=1 
cons3rt cloud run hosts --ids=1,2,3,4,5

# Added CLI command to list GPU usage in the cloud(s)
cons3rt cloud run gpus --id=1
cons3rt cloud run gpus --ids=1,2,3,4,5

# Use the `--load` flag to load deployment run host details saved from prior commands, this works in these commands:
cons3rt cloud run hosts --id=1 --load
cons3rt cloud run gpus --id=1 --load

```

## cons3rt cloudspace CLI

Permissions:
* **Team Manager** role

The `--id=1` or `--ids=1,2,3` args can be used to indicate which cloudspace IDs.

```
# Release active runs from multiple cloudspaces:
cons3rt cloudspace --release_active_runs --ids=123,124

# Delete inactive runs from your cloudspace
cons3rt cloudspace --delete_inactive_runs --id=123

# Deallocate a cloudspace
cons3rt cloudspace deallocate --id 123

# List cloudspaces
cons3rt cloudspace list

# List active runs in a cloudspace:
cons3rt cloudspace --list_active_runs --id=123

# Delete a specific template
cons3rt cloudspace template delete --id=1 --name 'cons3rt-redhat-8'

# Delete all templates in a cloudspace
cons3rt cloudspace template delete --id=1 --all

# List templates in a cloudspace
cons3rt cloudspace template list --id=1

# Register template in a cloudspace
cons3rt cloudspace template register --id=1 --name 'cons3rt-redhat-8'

# Register multiple templates
cons3rt cloudspace template register --id=1 --names 'cons3rt-redhat-8,cons3rt-redhat-9'

# Register all unregistered templates
cons3rt cloudspace template register --all

# Retrieve cloudpace details
cons3rt cloudspace retrieve --id=16

# Share a specific template from one cloudspace to another
cons3rt cloudspace template share --provider_id=1 --ids=2,3,4,5,6 --name 'cons3rt-redhat-8'

# Share multiple templates from one cloudspace to another
cons3rt cloudspace template share --provider_id=1 --ids=2,3,4,5,6 --names 'cons3rt-redhat-8,cons3rt-redhat-9'

# Share all templates from one cloudspace to another
cons3rt cloudspace template share --provider_id=1 --ids=2,3,4,5,6 --all

# Unregister a cloudspace
cons3rt cloudspace unregister --id 123
```

## cons3rt user CLI

Permissions:
* **Site Admin** role

```
# Get a list of active users
cons3rt user list --state=ACTIVE
```

## cons3rt team CLI

Permissions:
* **Team Manager** role

The `--id=1` or `--ids=1,2,3` args can be used to indicate which team IDs.

```
# Get a list of teams (site admins only)
cons3rt team list

# Get a count of ACTIVE users using various collabd tools like Jira
cons3rt team collabtools users --id=2

# Get a unique list of ACTIVE users in collab tools projects for a team or list of teams
cons3rt team collabtools users --ids=2,5 --unique

# Get a unique list of ACTIVE + BLOCKED users in collab tools projects for a team or list of teams
cons3rt team collabtools users --ids=2,5 --unique --blocked

# Get a list of active team members, printed by project
cons3rt team members list --id=11

# Get a list of active and blocked team members, printed by project
cons3rt team members list --id=11 --blocked

# Get a unique list of team members for a list of teams
cons3rt team members list --ids=1,2,3,4,5 --unique

# Get a unique list of team members managed by a particular user
cons3rt team members list --username=USERNAME --unique

# Get a list of active team managers
cons3rt team managers

# Get a list of team managers for specific teams
cons3rt team managers --ids=2,5

# Get a list of teams managed by a specific user
cons3rt team managers --username=johndoe

# Get a CSV report of runs in the team
cons3rt team report runs --id=3

# Get a CSV asset report for the team
cons3rt team report assets --id=3

# List runs in team-owned projects
cons3rt team run list --id=3

# Create snapshots for all team runs
cons3rt team run snapshot create --id=3

# Restore snapshots for all team runs
cons3rt team run snapshot restore --id=3

# Delete snapshots for all team runs
cons3rt team run snapshot delete --id=3

# Skip run IDs for any of the snapshot commands with --skip
cons3rt team run snapshot create --id=3 --skip=12345,12346,12347
```


## cons3rt project CLI

Permissions:
* **Team Manager** role
* **Project Owner** or **Project Manager** role

The `--id=1` or `--ids=1,2,3` args can be used to indicate which project IDs.

```
# List projects
cons3rt project list

# Print project details
cons3rt project get --id=3

# List project members
cons3rt project members list --id=3

# List runs in projects
cons3rt project run list --ids=3,6,9

# Create snapshots for all project runs
cons3rt project run snapshot create --id=3

# Restore snapshots for all project runs
cons3rt project run snapshot restore --id=3

# Delete snapshots for all project runs
cons3rt project run snapshot delete --id=3

# Skip run IDs for any of the snapshot commands with --skip
cons3rt project run snapshot create --id=3 --skip=12345,12346,12347

# Power runs off/on in the project
cons3rt project run on --id=3
cons3rt project run off --id=3

# Delete runs in projects
cons3rt project run delete --ids=3,4,5

# Release runs in projects, note this will prompt for confirmation due to the destructive nature
cons3rt project run release --id=3
```

## ractl command -- Controls and queries remote access across the CONS3RT site

Permissions:
* **Site Admin** role

```
# Create a csv file with remote access info for a specific cloudspace
ractl print cloudspace --id=116

# Create a csv file with remote access info for the CONS3RT site
ractl print site
```


# Use pycons3rt3 in python

## Logify

With the default configuration log files go to: `pycons3rt_user_home/log/`, and INFO 
level is printed to stdout.  To customize pycons3rt logging, modify the 
logging configuration file.

Logging example:

~~~
import logging
from pycons3rt3.logify import Logify

mod_logger = Logify.get_name() + '.your_module'
    
    # Then use in a function or class:
    
    class MyClass(object):
        def __init__(self, dep=None):
            self.cls_logger = mod_logger + '.MyCLass'
    	def class_method(self):
    		log = logging.getLogger(self.cls_logger + '.class_method')
    		log.info('Class Method Logging')
    
    def main():
        log = logging.getLogger(mod_logger + '.main')
        log.debug('DEBUG')
    	log.info('INFO')
    	log.warn('WARN')
    	log.error('ERROR')
~~~

## Deployment

This module provides a set of useful utilities for accessing 
deployment related info on deployment run hosts.

~~~
from pycons3rt3.deployment import Deployment
    
# Create a new Deployment object
dep = new Deployment()
    
# Deployment name
print(dep.deployment_name)
    
# Get the role name
print(dep.cons3rt_role_name)
    
# Deployment properties
print(dep.properties)
    
# Get a specific deployment property value by name
my_value = dep.get_value('cons3rt.user')
    
# Scenario network info
print(dep.scenario_network_info)

# ASSET_DIR
print(dep.asset_dir)
~~~

## Slack

This module provides an interface for posting anything to Slack!

~~~
from pycons3rt3.slack import SlackMessage
from pycons3rt3.slack import SlackAttachments

# Create a message
slack_msg = SlackMessage(
                my_webhook_url, 
                channel='#DevOps', 
                icon_url='http://cool-icon-url',
                text='This is a Slack message',
                user='@sender_username')

# Create and add an attachment
slack_attachment = SlackAttachment(
                       fallback='This is the fallback text', 
                       color='green', 
                       pretext='Pretext', 
                       text='Moar text!')

slack_msg.add_attachment(slack_attachment)

# Send a message
slack_msg.send()
~~~

## Nexus

This module provides simple method of fetching artifacts from a nexus
repository.

```
from pycons3rt3 import nexus

nexus.get_artifact_nexus(
    base_url='https://nexus.example.com',
    repository='releases|snapshots|etc',
    group_id='groupId',
    artifact_id='artifactId',
    packaging='zip|jar|etc',
    destination_dir='/path/to/dest/dir',
    version='x.y.z',
    classifier='classifier',
    suppress_status=True|False,
    overwrite=True|False,
    username='your_username',
    password='your_password'
)

search_results = search_nexus_assets(
    base_url='https://nexus.example.com',
    repository='releases|snapshots|etc',
    group='groupId',
    name='artifactId',
    extension='zip|jar|etc',
    sort_type='version',
    direction='asc|desc',
    version='x.y.z',
    classifier='classifier',
    username='your_username',
    password='your_password'
)

result = search_latest(
    base_url='https://nexus.example.com',
    repository='releases|snapshots|etc',
    group='groupId',
    name='artifactId',
    extension='zip|jar|etc',
    username='your_username',
    password='your_password'
)
```

### nexus cli

The `nexus` CLI command is an easy way to search for and retrieve artifacts from Nexus v3 using its rest API.

Authentication options:

* Provide both `--username` and `--password` args in the CLI call
* Configure a `~/.netrc` file, and specify the `--netrc` arg in the CLI call

Specify a version or latest:

* To get a specific version, use `--version x.y.z`
* To get the latest, use `--latest`

For targeting, use: `--group`, `--artifactId`, `--repo`, `--classifier`, `--packaging`.

Additional options: `--overwrite`, `--suppress`

```
# Search for a latest release
nexus search --group 'com.cons3rt' --artifactId 'cons3rt-pyotto' --packaging zip --repo releases --netrc --url 'https://nexus.jackpinetech.com' --latest

# Get a latest release
nexus get --group 'com.cons3rt' --artifactId 'cons3rt-pyotto' --repo releases --packaging zip --netrc --url 'https://nexus.jackpinetech.com' --latest

# Get a latest snapshot
nexus get --group 'com.cons3rt' --artifactId 'cons3rt-package' --repo snapshots --packaging zip --netrc --url 'https://nexus.jackpinetech.com' --latest

# Get a specific version
nexus get --group 'com.cons3rt' --artifactId 'cons3rt-pyotto' --repo releases --packaging zip --netrc --url 'https://nexus.jackpinetech.com' --version 24.7.0
```

## Bash (Linux only)

Executes commands on a Linux system.  See the source code for specific available
commands but the most commonly used `run_command` is shown below.

### run_command(command, timeout_sec=3600.0, output=True)

Parameters

* command: List containing the command and any additional args
* timeout_sec: (optional) Float specifying how long to wait before 
terminating the command.  Default is 3600.0.
* output: (boolean) True collects the output of the command.  In some cases
suppressing the command output improves stability.

Returns:

* A dictionary containing "code", the numeric exit code from the command, and 
"output" which captures the stdout/strerrif output was set `True`. Sample output:

Raises: `CommandError` when there is a problem running the command.

~~~
{
    "code": "0",
    "output": "stdout/stderr from the command"
}
~~~

Example Usage:

~~~
from pycons3rt3.bash import run_command
from pycons3rt3.bash import CommandError
command = ['ls', '/root']
try:
    result = run_command(command, timeout_sec=60.0)
    code = result['code']
    output = result['output']
except CommandError:
    raise
if code == 0:
    log.info('Successfully executed command {c}'.format(s=command))
else:
    msg = 'There was a problem running command returned code {c} and produced output: {o}'.format(
                    c=code, o=output)
            log.error(msg)
            raise CommandError(msg)
~~~

More to come....