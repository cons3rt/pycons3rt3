#!/usr/bin/env python

"""Module: images

This module provides utilities for managing CONS3RT OS templates in AWS.

"""
import logging
import time

from botocore.client import ClientError

from .logify import Logify
from .ec2util import get_ec2_client
from .exceptions import AWSAPIError, ImageUtilError


__author__ = 'Joe Yennaco'


# Set up logger name for this module
mod_logger = Logify.get_name() + '.images'

default_image_tags = [
    {
        'Key': 'cons3rtenabled',
        'Value': 'true'
    }
]


class ImageUtil(object):

    def __init__(self, account_id, region_name=None, aws_access_key_id=None, aws_secret_access_key=None,
                 aws_session_token=None):
        self.cls_logger = mod_logger + '.ImageUtil'
        if not isinstance(account_id, str):
            self.account_id = None
        else:
            self.account_id = account_id
        try:
            self.ec2 = get_ec2_client(
                region_name=region_name,
                aws_access_key_id=aws_access_key_id,
                aws_secret_access_key=aws_secret_access_key,
                aws_session_token=aws_session_token
            )
        except AWSAPIError:
            raise

    def get_image(self, ami_id):
        """Returns detailed info about the AMI ID

        :param ami_id: (str) ID of the AMI to retrieve
        :return: (dict) data about the AMI (see boto3 docs)
        :raises: AWSAPIError
        """
        log = logging.getLogger(self.cls_logger + '.update_image')
        log.info('Describing AMI ID: {i}'.format(i=ami_id))
        try:
            response = self.ec2.describe_images(DryRun=False, ImageIds=[ami_id])
        except ClientError as exc:
            msg = 'Unable to describe image ID: {a}'.format(a=ami_id)
            raise AWSAPIError(msg) from exc
        if 'Images' not in response:
            msg = 'Images not found in response: {r}'.format(r=str(response))
            raise AWSAPIError(msg)
        if len(response['Images']) != 1:
            msg = 'Expected to find 1 image, found {n} in response: {r}'.format(
                n=str(len(response['Images'])), r=str(response))
            raise AWSAPIError(msg)
        return response['Images'][0]

    def get_image_by_name(self, image_name):
        """Returns data for the AMI matching the provided AMI name, or None if not found

        :param image_name: (str) Name of the image
        :return: (dict) data about the AMI (see boto3 docs)
        """
        log = logging.getLogger(self.cls_logger + '.get_image_by_name')
        log.info('Retrieving image with name: {n}'.format(n=image_name))
        images = self.get_all_images()
        for image in images:
            if image['Name'] == image_name:
                log.info('Found matching image with name [{n}] and ID: {i}'.format(n=image_name, i=image['ImageId']))
                return image
        log.info('Image not found matching name: {n}'.format(n=image_name))

    def get_all_images(self):
        """Returns details about all images in this AWS account

        :return: (list) containing (dict) data about the AMIs (see boto3 docs)
        :raises: AWSAPIError
        """
        log = logging.getLogger(self.cls_logger + '.update_image')
        log.info('Describing AMIs...')
        try:
            response = self.ec2.describe_images(DryRun=False, Owners=[self.account_id])
        except ClientError as exc:
            msg = 'Problem describing images in account ID: {i}'.format(i=self.account_id)
            raise AWSAPIError(msg) from exc
        if 'Images' not in response:
            msg = 'Images not found in response: {r}'.format(r=str(response))
            raise AWSAPIError(msg)
        return response['Images']

    def delete_image(self, ami_id):
        """De-registers the AMI, deletes the underlying snapshot(s), and returns the
        image tags and description for the deleted image

        :param ami_id: (str) ID of the AMI to delete
        :return: (tuple) name, description, image tags of the deleted image
        :raises: ImageUtilError
        """
        log = logging.getLogger(self.cls_logger + '.delete_image')
        ami_info = self.get_image(ami_id=ami_id)
        image_name = None

        # Grab the Image description
        try:
            image_name = ami_info['Name']
            image_description = ami_info['Description']
            image_tags = ami_info['Tags']
        except KeyError as exc:
            log.warning('Name, Description, or Tags not found AMI ID {a}\n{e}'.format(a=ami_id, e=str(exc)))
            image_description = 'CONS3RT OS Template'
            image_tags = []
        log.info('Using description of the current image: {d}'.format(d=image_description))

        for image_tag in image_tags:
            if image_tag['Key'] == 'cons3rtuuid':
                cons3rt_uuid = image_tag['Value']
                log.info('Found existing image cons3rtuuid: {u}'.format(u=cons3rt_uuid))

        # Grab the Snapshot ID
        snapshot_ids = []
        for block_device_mapping in ami_info['BlockDeviceMappings']:
            try:
                snapshot_id = block_device_mapping['Ebs']['SnapshotId']
            except KeyError as exc:
                msg = 'Unable to determine Snapshot ID for AMI ID {a}'.format(a=ami_id)
                raise ImageUtilError(msg) from exc
            log.info('Found Snapshot ID of the current image: {s}'.format(s=snapshot_id))
            snapshot_ids.append(snapshot_id)

        # Deregister the image
        log.debug('De-registering image ID: {a}...'.format(a=ami_id))
        try:
            self.ec2.deregister_image(DryRun=False, ImageId=ami_id)
        except ClientError as exc:
            msg = 'Unable to de-register AMI ID: {a}'.format(a=ami_id)
            raise ImageUtilError(msg) from exc
        log.info('De-registered image ID: {a}'.format(a=ami_id))

        # Wait 20 seconds
        log.info('Waiting 20 seconds for the image to de-register...')
        time.sleep(20)

        # Delete the underlying snapshots
        for snapshot_id in snapshot_ids:
            log.info('Deleting snapshot for the old image with ID: {s}'.format(s=snapshot_id))
            try:
                self.ec2.delete_snapshot(DryRun=False, SnapshotId=snapshot_id)
            except ClientError as exc:
                log.warning('Unable to delete snapshot ID: {s}\n{e}'.format(s=snapshot_id, e=str(exc)))
        return image_name, image_description, image_tags

    def update_image(self, ami_id, instance_id):
        """Replaces an existing AMI ID with an image created from the provided
        instance ID
        
        :param ami_id: (str) ID of the AMI to delete and replace 
        :param instance_id: (str) ID of the instance ID to create an image from
        :return: (str) ID of the new AMI
        :raises: ImageUtilError
        """
        log = logging.getLogger(self.cls_logger + '.update_image')
        if not isinstance(ami_id, str):
            msg = 'Arg ami_id must be of type str, found: {t}'.format(t=ami_id.__class__.__name__)
            raise ImageUtilError(msg)
        if not isinstance(instance_id, str):
            msg = 'Arg instance_id must be of type str, found: {t}'.format(t=instance_id.__class__.__name__)
            raise ImageUtilError(msg)
        if ami_id is None or instance_id is None:
            raise ImageUtilError('The provided args ami_id and instance_id must not be None')

        log.info('Removing AMI ID: {a}, and replacing with an image for Instance ID: {i}'.format(
            a=ami_id, i=instance_id))

        image_name, image_description, image_tags = self.delete_image(ami_id=ami_id)

        # Create the new image
        log.info('Creating new image from instance ID: {i}'.format(i=instance_id))
        try:
            create_res = self.ec2.create_image(
                DryRun=False,
                InstanceId=instance_id,
                Name=image_name,
                Description=image_description,
                NoReboot=False
            )
        except ClientError as exc:
            msg = 'There was a problem creating an image named [{m}] for image ID: {i}'.format(
                m=image_name, i=instance_id)
            raise ImageUtilError(msg) from exc

        # Get the new Image ID
        try:
            new_ami_id = create_res['ImageId']
        except KeyError as exc:
            msg = 'Image ID not found in the image creation response for instance ID: {i}'.format(
                i=instance_id)
            raise ImageUtilError(msg) from exc
        log.info('Created new image ID: {w}'.format(w=new_ami_id))

        # Wait 20 seconds
        log.info('Waiting 20 seconds for the image ID {w} to become available...'.format(w=new_ami_id))
        time.sleep(20)

        # Add tags to the new AMI
        if len(image_tags) > 0:
            try:
                self.ec2.create_tags(DryRun=False, Resources=[new_ami_id], Tags=image_tags)
            except ClientError as exc:
                msg = 'There was a problem adding tags to the new image ID: {i}\n\nTags: {t}'.format(
                    i=new_ami_id, t=image_tags)
                raise ImageUtilError(msg) from exc
            log.info('Added tags to the new image ID: {w}\nTags: {t}'.format(w=new_ami_id, t=image_tags))
        else:
            log.info('No tags to add to new image ID: {i}'.format(i=new_ami_id))
        return new_ami_id

    def create_cons3rt_template(self, instance_id, name, description='CONS3RT OS template'):
        """Created a new CONS3RT-ready template from an instance ID
        
        :param instance_id: (str) Instance ID to create the image from
        :param name: (str) Name of the new image
        :param description: (str) Description of the new image
        :return: (str) ID of the new AMI
        :raises: ImageUtilError
        """
        log = logging.getLogger(self.cls_logger + '.create_cons3rt_template')
        if not isinstance(instance_id, str):
            msg = 'Arg instance_id must be of type str, found: {t}'.format(t=instance_id.__class__.__name__)
            raise ImageUtilError(msg)
        if not isinstance(name, str):
            msg = 'Arg name must be of type str, found: {t}'.format(t=instance_id.__class__.__name__)
            raise ImageUtilError(msg)
        if instance_id is None or name is None:
            raise ImageUtilError('The provided args instance_id or name must not be None')

        # Create the new image
        log.info('Creating new image from instance ID: {i}'.format(i=instance_id))
        try:
            create_res = self.ec2.create_image(
                DryRun=False,
                InstanceId=instance_id,
                Name=name,
                Description=description,
                NoReboot=False
            )
        except ClientError as exc:
            msg = 'There was a problem creating an image named [{m}] for image ID: {i}'.format(
                m=name, i=instance_id)
            raise ImageUtilError(msg) from exc

        # Get the new Image ID
        try:
            new_ami_id = create_res['ImageId']
        except KeyError as exc:
            msg = 'Image ID not found in the image creation response for instance ID: {i}'.format(
                i=instance_id)
            raise ImageUtilError(msg) from exc
        log.info('Created new image ID: {w}'.format(w=new_ami_id))

        # Wait 20 seconds
        log.info('Waiting 20 seconds for the image ID {w} to become available...'.format(w=new_ami_id))
        time.sleep(20)

        # Add tags to the new AMI
        try:
            self.ec2.create_tags(DryRun=False, Resources=[new_ami_id], Tags=default_image_tags)
        except ClientError as exc:
            msg = 'There was a problem adding tags to the new image ID: {i}\n\nTags: {t}'.format(
                i=new_ami_id, t=default_image_tags)
            raise ImageUtilError(msg) from exc
        log.info('Successfully added tags to the new image ID: {w}\nTags: {t}'.format(
            w=new_ami_id, t=default_image_tags))
        return new_ami_id

    def set_cons3rt_enabled(self, ami_id, value=True):
        """Sets the cons3rtenabled tag on an AMI to true or false

        :param ami_id: (str) ID of the AMI to tag
        :param value: (bool) Set True to set the value of the tag true, False otherwise
        :return: None
        :raises: ImageUtilError
        """
        log = logging.getLogger(self.cls_logger + '.set_cons3rt_enabled')
        log.info('Setting cons3rtenabled [{v}] on AMI ID: {i}'.format(v=str(value), i=ami_id))
        cons3rt_enabled_tag = {
            'Key': 'cons3rtenabled',
            'Value': 'true'
        }
        if not value:
            cons3rt_enabled_tag['Value'] = 'false'
        try:
            self.ec2.create_tags(DryRun=False, Resources=[ami_id], Tags=[cons3rt_enabled_tag])
        except ClientError as exc:
            msg = 'There was a problem adding tags to AMI ID: {i}\n\nTags: {t}'.format(
                i=ami_id, t=cons3rt_enabled_tag)
            raise ImageUtilError(msg) from exc

    def set_cons3rt_uuid(self, ami_id, uuid):
        """Sets the cons3rtuuid tag on an AMI to true or false

        :param ami_id: (str) ID of the AMI to tag
        :param uuid: (str) cons3rtuuid tag value
        :return: None
        :raises: ImageUtilError
        """
        log = logging.getLogger(self.cls_logger + '.set_cons3rt_enabled')
        log.info('Setting cons3rtuuid tag [{u}] on AMI ID: {i}'.format(u=uuid, i=ami_id))
        cons3rt_uuid_tag = {
            'Key': 'cons3rtuuid',
            'Value': uuid
        }
        try:
            self.ec2.create_tags(DryRun=False, Resources=[ami_id], Tags=[cons3rt_uuid_tag])
        except ClientError as exc:
            msg = 'There was a problem adding tags to AMI ID: {i}\n\nTags: {t}'.format(
                i=ami_id, t=cons3rt_uuid_tag)
            raise ImageUtilError(msg) from exc

    def make_image_public(self, ami_id):
        """Sets permissions for the AMI ID to public

        :param ami_id: (str) ID of the AMI to make public
        :return: None
        :raises: ImageUtilError
        """
        log = logging.getLogger(self.cls_logger + '.make_image_public')
        log.info('Setting AMI to public: {i}'.format(i=ami_id))
        try:
            self.ec2.modify_image_attribute(
                ImageId=ami_id,
                LaunchPermission={
                    'Add': [
                        {
                            'Group': 'all',
                        },
                    ],
                },
            )
        except ClientError as exc:
            msg = 'Problem setting AMI to public: {i}'.format(i=ami_id)
            raise ImageUtilError(msg) from exc

    def copy_cons3rt_template(self, ami_id, image_name, source_region, description='CONS3RT OS template'):
        """Copy a template to another region, includes replacing the existing image of the same name
        and retaining the cons3rtuuid tag

        Note: The EC2 util must be configured for the DESTINATION region of the copy for this call
        
        :param ami_id: (str) ID of the AMI
        :param image_name: (str) Name of the AMI being copied
        :param source_region: (str) region ID for the copy destination
        :param description: (str) image description for the new image
        :return: (str) new copied AMI ID
        :raises: ImageUtilError
        """
        log = logging.getLogger(self.cls_logger + '.copy_cons3rt_template')

        # Check for an existing image of the same name and get its tags and description
        existing_ami = self.get_image_by_name(image_name=image_name)
        image_description = description
        if existing_ami:
            _, image_description, image_tags = self.delete_image(ami_id=ami_id)
            for image_tag in image_tags:
                if image_tag['Key'] == 'cons3rtuuid':
                    cons3rt_uuid = image_tag['Value']
                    log.info('Found existing image cons3rtuuid: {u}'.format(u=cons3rt_uuid))
        else:
            log.info('No existing image found with name: {n}'.format(n=image_name))
            image_tags = default_image_tags

        # Copy the image
        log.info('Coping image [{n}] with ID [{i}] from source region: {r}'.format(
            n=image_name, i=ami_id, r=source_region))
        try:
            response = self.ec2.copy_image(
                Description=image_description,
                Encrypted=False,
                Name=image_name,
                SourceImageId=ami_id,
                SourceRegion=source_region,
                DryRun=False
            )
        except ClientError as exc:
            msg = 'Problem copying AMI {i} from region {r}'.format(i=ami_id, r=source_region)
            raise ImageUtilError(msg) from exc
        if 'ImageId' not in response.keys():
            msg = 'ImageId not found in response: {r}'.format(r=str(response))
            raise ImageUtilError(msg)
        new_ami_id = response['ImageId']
        log.info('Copied to new image ID: {i}'.format(i=new_ami_id))

        # Wait 20 seconds
        log.info('Waiting 20 seconds for the image ID {w} to become available...'.format(w=new_ami_id))
        time.sleep(20)

        # Add tags to the new AMI
        try:
            self.ec2.create_tags(DryRun=False, Resources=[new_ami_id], Tags=image_tags)
        except ClientError as exc:
            msg = 'There was a problem adding tags to the new image ID: {i}\n\nTags: {t}'.format(
                i=new_ami_id, t=default_image_tags)
            raise ImageUtilError(msg) from exc
        log.info('Successfully added tags to the new image ID: {w}\nTags: {t}'.format(
            w=new_ami_id, t=default_image_tags))
        return new_ami_id


def main():
    """Sample usage for this python module

    This main method simply illustrates sample usage for this python
    module.

    :return: None
    """
    log = logging.getLogger(mod_logger + '.main')
    log.info('Main!')


if __name__ == '__main__':
    main()
