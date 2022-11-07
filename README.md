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

If you have Python 3.5+ installed, you can run:

`pip install pycons3rt3`

#### Install from source

~~~
git clone https://github.com/cons3rt/pycons3rt3
cd pycons3rt3
pip install -r cfg/requirements.txt
python setup.py install
~~~

When installed, pycons3rt determines and creates a system directory (`pycons3rt_system_home`) and 
a local user directory (`pycons3rt_user_home`).  

Set the `PYCONS3RT_HOME` environment variable to point pycons3rt3 to a desired
directory.  If set, `PYCONS3RT_HOME` is used for `pycons3rt_system_home` and 
`pycons3rt_user_home`.

The `pycons3rt_system_home` directory is located on your system here:

* Linux: `~/.cons3rt`
* MacOS: `~/.cons3rt`
* Windows: `C:\cons3rt`

The `pycons3rt_user_home` is always: `~/.cons3rt` on all OS types.

The following directories are also created:

* System pycons3rt config dir: `pycons3rt_system_home/conf/`
* User log dir (default): `pycons3rt_user_home/log/`
* Pycons3rt source dir: `pycons3rt_user_home/src/`

The asset clones the pycons3rt source code here for installation:

* `pycons3rt_user_home/src/pycons3rt`

The logging configuration file is installed here:

* `pycons3rt_system_home/conf/pycons3rt-logging.conf`

By default, pycons3rt log files will output here:

* `pycons3rt_user_home/log/pycons3rt-info.log`
* `pycons3rt_user_home/log/pycons3rt-warn.log`
* `pycons3rt_user_home/log/pycons3rt-debug.log`

## CONS3RT ReST API and CLI

pycons3rt3 provides a python3 SDK for using the CONS3RT ReST API.  

> There is an official verison coming soon with full support.  This
version does not support all API calls, email support@cons3rt.com to 
request a call added.

To access the ReST API you will need:

* An active account on HmC or cons3rt.com
* Access to a project
* A ReST API token ([click here for instructions](https://kb.cons3rt.com/kb/accounts/api-tokens))
* For sites that require **Certificate Authentication** you will require an 
[ECA certificate](https://kb.cons3rt.com/kb/accounts/obtain-an-eca-certificate) or a machine 
certificate.  Contact [support@cons3rt.com](mailto:support@cons3rt.com) to request a machine 
certificate.

> pycons3rt3 does **not** support CAC authentication at this time

If you have a certificate in p12 or pfx format, convert it to a passwordless pem file:

`openssl pkcs12 -in certfile.pfx -out certfile.pem -nodes`

## Configuration

To configure pycons3rt3 for the CONS3RT ReST API type:

`cons3rt config`

After entering your info, a config file is created here:

`pycons3rt_user_home/conf/config.json`

This configuration will automatically loaded for ReST API calls.

# asset CLI

The asset CLI command helps you automatically create and import assets:

Validate your asset directory, and check for errors:

`asset validate --asset_dir=/path/to/asset`

Validate and create an asset zip file for import in your Downloads directory (default):

`asset create --asset_dir=/path/to/asset`

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

Configure the API authentication info:

`cons3rt config`

## cons3rt cloudspace CLI

> Cloudspace CLI calls require the caller to have the **Team Manager** role in CONS3RT.

The `--id=1` or `--ids=1,2,3` args can be used to indicate which cloudspace IDs.

List active runs in a cloudspace:

`cons3rt cloudspace --list_active_runs --id=123`

Release active runs from multiple cloudspaces:

`cons3rt cloudspace --release_active_runs --ids=123,124`

Delete inactive runs from your cloudspace

`cons3rt cloudspace --delete_inactive_runs --id=123`


# Use pycons3rt3 in python3

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

~~~
from pycons3rt3 import nexus

nexus.get_artifact(
    username=nexus_username,
    password=nexus_password,
    suppress_status=True,
    nexus_url=nexus_url,
    timeout_sec=45,
    overwrite=False,
    group_id='com.cons3rt',
    artifact_id='cons3rt-backend-install',
    version=`18.11.1`,
    packaging='zip',
    classifier='package-otto',
    destination_dir=dest_dir)
~~~

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