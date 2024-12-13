
0.0.26a0
========

* Skip updating asset_data.yml asset ID when running an update FROM the asset data

0.0.25
======

* Fixed asset CLI command to better handle importing from zip file with the `--zip` option
* Removed a redundant function from cons3rtclient.py
* Added instance types to the AWS dedicated host script
* By default keep asset zip files imported with `asset --zip`
* Finally added multi-site config file support, and multi-site automated asset update using `asset_data.yml` 

0.0.24
======

* Added methods and CLI commands to power on/off and restart
* Updated api calls related to remote access to use the new virt realm service endpoints
* Added the --unlock arg to all power and snapshot actions for run, project, and team CLI commands

0.0.23
======

* Added a methods to s3util for handling: object version deletion, disabling versioning in all buckets, and removing 
non-latest versions from the bucket.
* Fixed handling asset_type and asset_subtype in the asset module, fixed querying assets, fixed setting asset_data.yml
entries for new asset imports
* Added --loglevel arg to the asset command
* General code inspection cleanup
* Updated the cons3rt team report to include GPU data
* Updated the cons3rt team report to reflect API changes in return legacy deployment properties

0.0.22
======

* Added API calls to get project and team host metrics
* Added API calls to get project and team resource usage
* Added the /api/users/ API call and a method to create a single user using a public cert
* Added the get users in team services calls and added to CLI

0.0.21
======

* Added a method to get the latest S3 object in a bucket given a prefix
* Changed the build method from setup.py to pypa - python3 -m build
* Added method list_deployment_runs for listing runs in the user context
* Added logging for the openssl decrypt method
* Moved the /api/users endpoint to /api/admin/users
* Modernized the nexus.py module, added a CLI command for it
* Consolidated duplicated code in httpclient.py
* Added a method to list services for a team

0.0.20
======

* Added the ability to specify ports and protocol for generated hostname based IpPermissions rules
* Added methods to clean up and delete S3 buckets, organized and refactored S3Util to utilize newer module methods
* Redacted ReST API token from DEBUG logging
* Added methods to set S3 bucket lifecycle rules, including a method to set lifecycle deletion rules
* Added sample scripts for import assets from a directory and setting project asset visibilities
* Added a method to get the first listed nameserver on Linux
* Added snapshot info including snapshot storage to the team run report

0.0.19
======

* Added a method to create an identity for a storage bucket and added a sample script
* Added a method to automatically create AWS config and credentials file from an identity
* Added methods and CLI commands to list team members and list team members by team manager

0.0.18
======

* Added CLI commands to create, restore, and delete snapshots across one or more teams:
  * cons3rt team run snapshot create --id=123
  * cons3rt team run snapshot restore --id=123
  * cons3rt team run snapshot delete --id=123
* Added a --skip arg to provide a list of deployment run IDs to skip
  * cons3rt team run snapshot create --id=3 --skip 12345
* Added a CLI command to list runs in a team:
  * cons3rt team run list --id=1
* Added project CLI commands for snapshots that behave like the team ones, allow you to manage snapshots across one or more projects:
  * cons3rt project run snapshot create --id=123
  * cons3rt project run snapshot restore --id=123
  * cons3rt project run snapshot delete --id=123
* Updated the error handling for parsing http responses
* Updated the error messages reported in host action results

0.0.17
======

* Added the "cons3rt run cancel" and "cons3rt run release" CLI commands
* Added the "cons3rt cloudspace project list", "cons3rt cloudspace user list", and "cons3rt user list" CLI commands
* Greatly enhanced CLI output formatting!!!!
* Added a create_user() method for easy creation of users over rest api
* Added user counts to the `ractl print` command
* Added methods to counts the list collab tools and count collab tool users for a team
* Added the `team collabtools` subcommand for the team CLI
* Added a `--blocked` arg to include blocked users in output
* Added a `--cpu` arg to specify the max number of CPU when subscribing to a template
* Added a methods to list the deployment runs and deployment run hosts in a cloud
* Added a method to list the deployment run hosts in a cloud that are using GPUs
* Added CLI command `cons3rt cloud run list --id=1` to list deployment runs in the cloud(s)
* Added CLI command `cons3rt cloud run hosts --id=1` to list deployment run hosts in the cloud(s)
* Added CLI command `cons3rt cloud run gpus --id=1` to list GPU usage in the cloud(s)
* Added the ability to save cons3rt data to a local PYCONS3RT_HOME/data directory to be loaded with the `--load`
arg on future commands

0.0.16
======

* Added CLI commands cons3rt project run off, on, snapshot, and restore to manage runs at the project level
* Expanded the methods for listing site users via a new method list_users which take more options like user state and creation dates,
and added the ability to set max_results, and set the default to 500, which should significant speed up this query
* Improved releasing all active runs from a cloudspace, will now monitor each DR to reach COMPLETED or CANCELLED status
* Added a "RunWaiter" class for monitoring deployment runs reaching one of a list of desired states

0.0.15
======

* Added the capability to terminate a service runner process by converting from a threading.Thread to a multiprocessing.Process
* Cleaned up duplicate code fragments

0.0.14
======

* Added cloudwatchutil.py module for handling AWS cloudwatch

0.0.13
======

* Added a CLI command and method to delete cloudspaces for a cloud, and added returns for release runs in a cloudspace, and deleting runs in a cloudspace
* Added a method to retrieve details of a test asset
* Fixed running team reports from the CLI while providing the --config arg
* Added methods for assigning and unassigning project roles
* Added helpful methods for quickly assigning roles for project managers, asset developers, and express users in a project
* Added support for setting PYCONS3RT_HOME environment variable to keep the config, logs, etc. in a desired location
* Added support for AWS CLI environment variables AWS_CONFIG_FILE and AWS_SHARED_CREDENTIALS_FILE when performing login_as_role and setting the credentials files
* Added methods for retrieving expires, active, inactive, and non-expired teams; and printing team manager emails
* Added the --expired and --unexpired for listing teams via CLI, and also incorporated the --active when listing teams in the CLI.  Added the state and expiration date to the team listing output.
* Added the --config arg for the asset CLI command to specify a config file
* Added methods for deleting subnets, deleting internet gateways, deleting VPCs, and deleting the default VPC
* Added methods for getting a list of cons3rt bucket source IPs, and adding IPs to the list
* Added methods for creating and managing reverse lookup zones in AWS Route53
* Added a module for integrating with the Azure metadata service

0.0.12
======

* Added methods for listing unattached EBS volumes
* Added methods for deleting EBS volumes and snapshots
* Added methods for stopping and terminating instances
* Added methods for waiting for instances to be in various target states
* Added a method to wait for an AMI to become available after creation
* Added a method to create a network interface
* Added a method to launch a VM onto a dedicated host
* Added a setup script
* Added the migrate CLI command, and a method to check capacity of a specific instance type on a dedicated host
* Added kmsutil.py to integrate with AWS KMS
* Added functionality to the S3Util to handle encryping objects in place in a bucket with the provided KMS key
* Updated host migration methods to use OS type and run a user-data script to configure sshd
* Added the ability to migrate a deployment run to a dedicated host
* Codified Linux user-data scripts for bringing a NAT instance online, and for migrating a Linux VM
* Added a script for asset export / re-import
* Added methods to get IPs and permissions for RHUI1 and RHUI2 AWS Red Hat server IPs
* Added re-try logic acount http multipart uploads to better handle asset imports
* Updated setting asset state to the newer versions 

0.0.11
=======

* Added queries for listing test assets
* Added a query for getting dependent assets
* Added ec2util functions for getting a list of IpPermission objects from domain names
* Added network.py and new function for getting IPs froma list of hostnames

0.0.10
=======

* Fixed a bug reporting errors with servicerunner
* Added a method to power on multiple runs
* Optimized queries to retrieve DR details from the multiple run host action workflow
* Significantly power action delay times, these are handled on the server side
* Added the --config CLI arg to specify which config file to use
* Added the --assets CLI arg to generate team reports for assets used by active DRs
* Added the "cons3rt team managers" and optionally "--id=ID" to generate a list of team managers
* Added remoteaccesscontroller.py and a new ractl CLI command for easy execution
* Added an export/import script to help migrate assets between CONS3RT sites
* Improved the asset import/update CLI logic, and added the "asset updateonly" subcommand
* Added the option to pass --id to the "asset update" command (e.g. asset update --id=12345)
* Added CLI command to get project members: cons3rt project members list --id=123
* Added CLI commands to create cloud and register a cloudspace
* Updated the template registration auto-discovery
* Added force delete for assets

0.0.9
=====

* Removed GPU from template registraiton/subscription to react to CONS3Rt changes
* Added the s3organizer CLI command and tool for helping organize, move, and delete items in S3 buckets
* Added logic for finding and deleting orphan snapshots in AWS accounts
* Added the ability to create and update IAM roles and policies
* Added the ability to generate STS login tokens with or without MFA when assuming roles in other accounts
* Added the deployment subcommand: cons3rt deployment list, or cons3rt deployment run list/delete/release
* Added a module for encryption/decrption with ansible-vault
* Added the `asset download --id=ASSET_ID` command to easily download assets from the CLI

0.0.8
=====

* Added CLI calls to power on/off runs, and corresponding methods
* Added an option to keep the asset zip files after import/update
* Added ssh.scp_file method for getting and putting files over SSH using paramiko and scp
* Added route53 util for creating public/private hosted zones and adding/deleting DNS records
* Added a --keep flag for the asset command, to keep the asset zip after import, and added project to the asset_data.yml that gets saved on import/update into a site
* Added methods to the Deployment class to return a boolean if the deployment is in AWS, Azure, Openstack, or VCloud
* Added StsUtil and StsUtilError classes, to get informationa about the AWS caller
* Added red-hat as a possible name for Red Hat templates when auto-configuring
* Added the beginning of a multi-site config file for Cons3rtApi

0.0.7
=====

* Added the "cons3rt run" CLI command, and added options for snapshotting all hosts in a run, or restoring
 all hosts in a run from snapshots
* Updated the SSH generation methods to allow various key types, and added a method to ECDSA keys
* Added new methods of encryption/decryption for openssl smime
* Added Arcus site configurations, and removed old site configurations

0.0.1
=====

* Initial python3 port of pycons3rt and pycons3rtapi
