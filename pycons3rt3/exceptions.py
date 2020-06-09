# -*- coding: utf-8 -*-

"""
pycons3rt3.exceptions
~~~~~~~~~~~~~~~~~~~
This module contains the set of Requests' exceptions.
"""

"""
CONS3RT API level exceptions
"""


class Cons3rtApiError(Exception):
    """There was a problem executing a CON3RT API call"""


class HttpError(Exception):
    """There was a problem with an HTTP request"""


class Cons3rtClientError(Exception):
    """There was a problem setting up a CONS3RT client"""


class Cons3rtConfigError(Exception):
    """There was a problem configuring for CONS3RT API calls"""


class InvalidCloudError(Exception):
    """Invalid cloud data"""


class InvalidOperatingSystemTemplate(Exception):
    """Invalid OS template data"""


"""
CONS3RT command-line interface exceptions
"""


class Cons3rtCliError(Exception):
    """There was a problem with a CONS3RT CLI operation"""


"""
Deployment or asset-level exceptions
"""


class DeploymentError(Exception):
    """There was a problem gathering CONS3RT deployment information"""


class Cons3rtAssetStructureError(Exception):
    """There is a problem with the asset structure"""


class AssetZipCreationError(Exception):
    """Simple exception type for handling errors creating the asset zip file"""


class AssetError(Exception):
    """General exception for handling assets"""


class PyGitError(Exception):
    """There was a problem performing git operations"""


class AliasExistsError(Exception):
    """Error importing a root CA certificate because the alias exists"""


class AliasImportError(Exception):
    """General error when importing a root CA certificate fails"""


class Cons3rtSlackerError(Exception):
    """There was a problem with a slack operation"""


class SshConfigError(Exception):
    """Problem configuring SSH on a host"""

"""
Operating System level exceptions
"""


class CommandError(Exception):
    """There was a problem executing an OS-level command"""


class Pycons3rtWindowsCommandError(Exception):
    """Error encompassing problems that could be encountered while
    running commands on a Windows box.
    """
    pass


class SystemRebootError(Exception):
    """There was a problem executing a system reboot"""


class SystemRebootTimeoutError(Exception):
    """A call to reboot the system encountered a timeout"""


class NetworkRestartError(Exception):
    """There was a problem restarting network services"""


"""
AWS API exceptions
"""


class AWSMetaDataError(Exception):
    """There was a problem encountered with the AWS meta data service"""


class S3UtilError(Exception):
    """There was a problem with an AWS S3 operation"""


class EC2UtilError(Exception):
    """There was a problem with an AWS EC2 operation"""


class ImageUtilError(Exception):
    """There was a problem with an AWS AMI operation"""


class AWSAPIError(Exception):
    """Simple exception type for AWS API errors"""
