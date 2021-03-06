# Copyright 2013-2014 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Amazon Software License (the "License"). You may not use this file except in compliance with the
# License. A copy of the License is located at
#
# http://aws.amazon.com/asl/
#
# or in the "LICENSE.txt" file accompanying this file. This file is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES
# OR CONDITIONS OF ANY KIND, express or implied. See the License for the specific language governing permissions and
# limitations under the License.

import ConfigParser
import os
import sys
import inspect
import pkg_resources
import logging
import json
import urllib2
import config_sanity

class CfnClusterConfig:

    def __init__(self, args):
        self.args = args
        self.parameters = []
        self.version = pkg_resources.get_distribution("cfncluster").version
        self.__DEFAULT_CONFIG = False

        # Determine config file name based on args or default
        if args.config_file is not None:
            self.__config_file = args.config_file
        else:
            self.__config_file = os.path.expanduser(os.path.join('~', '.cfncluster', 'config'))
            self.__DEFAULT_CONFIG = True
        if os.path.isfile(self.__config_file):
            pass
        else:
            if self.__DEFAULT_CONFIG:
                print('Default config %s not found' % self.__config_file)
                print('You can copy a template from here: %s%sexamples%sconfig' %
                      (os.path.dirname(os.path.abspath(inspect.getfile(inspect.currentframe()))),
                       os.path.sep, os.path.sep))
                sys.exit(1)
            else:
                print('Config file %s not found' % self.__config_file)
                sys.exit(1)


        __config = ConfigParser.ConfigParser()
        __config.read(self.__config_file)

        # Determine which cluster template will be used
        try:
            if args.cluster_template is not None:
                self.__cluster_template = args.cluster_template
            else:
                self.__cluster_template = __config.get('global', 'cluster_template')
        except AttributeError:
            self.__cluster_template = __config.get('global', 'cluster_template')
        self.__cluster_section = ('cluster %s' % self.__cluster_template)

        # Check if package updates should be checked
        try:
            self.__update_check = __config.getboolean('global', 'update_check')
        except ConfigParser.NoOptionError:
            self.__update_check = True

        if self.__update_check == True:
            try:
                __latest = json.loads(urllib2.urlopen("http://pypi.python.org/pypi/cfncluster/json").read())['info']['version']
                if self.version < __latest:
                    print('warning: There is a newer version %s of cfncluster available.' % __latest)
            except Exception:
                pass

        # Check if config sanity should be run
        try:
            self.__sanity_check = __config.getboolean('global', 'sanity_check')
        except ConfigParser.NoOptionError:
            self.__sanity_check = False

        # Determine the EC2 region to used used or default to us-east-1
        # Order is 1) CLI arg 2) AWS_DEFAULT_REGION env 3) Config file 4) us-east-1
        if args.region:
            self.region = args.region
        else:
            if os.environ.get('AWS_DEFAULT_REGION'):
                self.region = os.environ.get('AWS_DEFAULT_REGION')
            else:
                try:
                    self.region = __config.get('aws', 'aws_region_name')
                except ConfigParser.NoOptionError:
                    self.region = 'us-east-1'

        # Check if credentials have been provided in config
        try:
            self.aws_access_key_id = __config.get('aws', 'aws_access_key_id')
        except ConfigParser.NoOptionError:
            self.aws_access_key_id=None
        try:
            self.aws_secret_access_key = __config.get('aws', 'aws_secret_access_key')
        except ConfigParser.NoOptionError:
            self.aws_secret_access_key=None

        # Get the EC2 keypair name to be used, exit if not set
        try:
            self.key_name = __config.get(self.__cluster_section, 'key_name')
            if not self.key_name:
                raise Exception
            if self.__sanity_check:
                config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                             'EC2KeyPair', self.key_name)
        except ConfigParser.NoOptionError:
            raise Exception
        self.parameters.append(('KeyName', self.key_name))

        # Determine the CloudFormation URL to be used
        # Order is 1) CLI arg 2) Config file 3) default for version + region
        try:
            if args.template_url is not None:
                self.template_url = args.template_url
            try:
                self.template_url = __config.get(self.__cluster_section,
                                                 'template_url')
                if not self.template_url:
                    raise Exception
                if self.__sanity_check:
                    config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                             'URL', self.template_url)
            except ConfigParser.NoOptionError:
                self.template_url = ('https://s3.amazonaws.com/cfncluster-%s/templates/cfncluster-%s.cfn.json' % (self.region, self.version))
        except AttributeError:
            pass

        # Determine which vpc settings section will be used
        self.__vpc_settings = __config.get(self.__cluster_section, 'vpc_settings')
        self.__vpc_section = ('vpc %s' % self.__vpc_settings)

        # Dictionary list of all VPC options
        self.__vpc_options = dict(vpc_id=('VPCId','VPC'), master_subnet_id=('MasterSubnetId', 'VPCSubnet'),
                                  compute_subnet_cidr=('ComputeSubnetCidr',None),
                                  compute_subnet_id=('ComputeSubnetId', 'VPCSubnet'), use_public_ips=('UsePublicIps', None),
                                  ssh_from=('SSHFrom', None))

        # Loop over all VPC options and add define to parameters, raise Exception is defined but null
        for key in self.__vpc_options:
            try:
                __temp__ = __config.get(self.__vpc_section, key)
                if not __temp__:
                    raise Exception
                if self.__sanity_check and self.__vpc_options.get(key)[1] is not None:
                    config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                                self.__vpc_options.get(key)[1],__temp__)
                self.parameters.append((self.__vpc_options.get(key)[0],__temp__))
            except ConfigParser.NoOptionError:
                pass

        # Dictionary list of all cluster section options
        self.__cluster_options = dict(cluster_user=('ClusterUser', None), compute_instance_type=('ComputeInstanceType',None),
                                      master_instance_type=('MasterInstanceType', None), initial_queue_size=('InitialQueueSize',None),
                                      max_queue_size=('MaxQueueSize',None), maintain_initial_size=('MaintainInitialSize',None),
                                      scheduler=('Scheduler',None), cluster_type=('ClusterType',None), ephemeral_dir=('EphemeralDir',None),
                                      spot_price=('SpotPrice',None), custom_ami=('CustomAMI','EC2Ami'), pre_install=('PreInstallScript','URL'),
                                      post_install=('PostInstallScript','URL'), proxy_server=('ProxyServer',None),
                                      placement=('Placement',None), placement_group=('PlacementGroup','EC2PlacementGroup'),
                                      encrypted_ephemeral=('EncryptedEphemeral',None),pre_install_args=('PreInstallArgs',None),
                                      post_install_args=('PostInstallArgs',None), s3_read_resource=('S3ReadResource',None),
                                      s3_read_write_resource=('S3ReadWriteResource',None))

        # Loop over all the cluster options and add define to parameters, raise Exception if defined but null
        for key in self.__cluster_options:
            try:
                __temp__ = __config.get(self.__cluster_section, key)
                if not __temp__:
                    raise Exception
                if self.__sanity_check and self.__cluster_options.get(key)[1] is not None:
                    config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                                self.__cluster_options.get(key)[1],__temp__)
                self.parameters.append((self.__cluster_options.get(key)[0],__temp__))
            except ConfigParser.NoOptionError:
                pass

        # Determine if EBS settings are defined and set section
        try:
            self.__ebs_settings = __config.get(self.__cluster_section, 'ebs_settings')
            if not self.__ebs_settings:
                raise Exception
            self.__ebs_section = ('ebs %s' % self.__ebs_settings)
        except ConfigParser.NoOptionError:
            pass

        # Dictionary list of all EBS options
        self.__ebs_options = dict(ebs_snapshot_id=('EBSSnapshotId','EC2Snapshot'), volume_type=('VolumeType',None),
                                  volume_size=('VolumeSize',None),
                                  volume_iops=('VolumeIOPS',None), encrypted=('EBSEncryption',None))

        try:
            if self.__ebs_section:
                for key in self.__ebs_options:
                    try:
                        __temp__ = __config.get(self.__ebs_section, key)
                        if not __temp__:
                            raise Exception
                        if self.__sanity_check and self.__ebs_options.get(key)[1] is not None:
                            config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                                self.__ebs_options.get(key)[1],__temp__)
                        self.parameters.append((self.__ebs_options.get(key)[0],__temp__))
                    except ConfigParser.NoOptionError:
                        pass
        except AttributeError:
            pass

        # Determine if scaling settings are defined and set section
        try:
            self.__scaling_settings = __config.get(self.__cluster_section, 'scaling_settings')
            if not self.__scaling_settings:
                raise Exception
            self.__scaling_section = ('scaling %s' % self.__scaling_settings)
        except ConfigParser.NoOptionError:
            pass

        # Dictionary list of all scaling options
        self.__scaling_options = dict(scaling_threshold=('ScalingThreshold',None), scaling_period=('ScalingPeriod',None),
                                      scaling_evaluation_periods=('ScalingEvaluationPeriods',None),
                                      scaling_adjustment=('ScalingAdjustment',None),scaling_adjustment2=('ScalingAdjustment2',None),
                                      scaling_cooldonw=('ScalingCooldown',None),scaling_threshold2=('ScalingThreshold2',None))

        try:
            if self.__scaling_section:
                for key in self.__scaling_options:
                    try:
                        __temp__ = __config.get(self.__scaling_section, key)
                        if not __temp__:
                            raise Exception
                        if self.__sanity_check and self.__scaling_options.get(key)[1] is not None:
                            config_sanity.check_resource(self.region,self.aws_access_key_id, self.aws_secret_access_key,
                                                self.__scaling_options.get(key)[1],__temp__)
                        self.parameters.append((self.__scaling_options.get(key)[0],__temp__))
                    except ConfigParser.NoOptionError:
                        pass
        except AttributeError:
            pass

