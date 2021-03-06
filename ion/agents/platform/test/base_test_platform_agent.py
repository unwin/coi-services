#!/usr/bin/env python

"""
@package ion.agents.platform.test.base_test_platform_agent
@file    ion/agents/platform/test/base_test_platform_agent.py
@author  Carlos Rueda, Maurice Manning, Ian Katz
@brief   A base class for platform agent integration testing
"""

__author__ = 'Carlos Rueda, Maurice Manning, Ian Katz'


#
# The original test set-up in this file adapted pieces from various sources:
# - test_instrument_management_service_integration.py
# - test_driver_egg.py
# - test_oms_launch2.py  (now deprecated).
#
# The main class defined here serves as a base to specific platform agent
# integration tests:
# - ion/agents/platform/test/test_platform_agent.py
# - ion/services/sa/observatory/test/test_platform_launch.py
#
# Platform IDs used here for the various platform hierarchies should be
# defined in the simulated platform network (network.yml), which in turn
# is used by the RSN OMS simulator.
#
# In DEBUG logging level, the tests may generate files under logs/ like the
# following:
#   platform_CFG_generated_LJ01D.txt
#   platform_CFG_generated_Node1D_->_MJ01C.txt
#   platform_CFG_generated_Node1D_complete.txt
# containing the corresponding agent configurations as they are constructed.
#

from pyon.util.int_test import IonIntegrationTestCase
from pyon.public import RT, OT, PRED, CFG
from pyon.public import log
import logging
from pyon.public import IonObject
from pyon.core.exception import ServerError, Conflict


from pyon.event.event import EventSubscriber

from interface.services.coi.iresource_registry_service import ResourceRegistryServiceClient
from interface.services.sa.iinstrument_management_service import InstrumentManagementServiceClient
from interface.services.sa.idata_acquisition_management_service import DataAcquisitionManagementServiceClient
from interface.services.sa.idata_product_management_service import DataProductManagementServiceClient
from interface.services.cei.iprocess_dispatcher_service import ProcessDispatcherServiceClient
from interface.services.dm.ipubsub_management_service import PubsubManagementServiceClient
from interface.services.dm.idataset_management_service import DatasetManagementServiceClient
from interface.services.sa.iobservatory_management_service import ObservatoryManagementServiceClient
from pyon.core.governance import get_system_actor_header

from pyon.ion.stream import StandaloneStreamSubscriber

from pyon.util.context import LocalContextMixin

from nose.plugins.attrib import attr

from pyon.agent.agent import ResourceAgentClient
from pyon.agent.agent import ResourceAgentState
from pyon.agent.agent import ResourceAgentEvent

from interface.objects import AgentCommand, ProcessStateEnum
from interface.objects import StreamConfiguration
from interface.objects import StreamAlertType, AggregateStatusType
from interface.objects import PortTypeEnum

from ion.agents.port.port_agent_process import PortAgentProcessType, PortAgentType

from ion.agents.platform.platform_agent import PlatformAgentEvent


from gevent.event import AsyncResult

from ion.agents.platform.test.helper import HelperTestMixin

from ion.agents.platform.util.network_util import NetworkUtil

from ion.agents.platform.platform_agent import PlatformAgentState


import os
import time
import calendar
import copy
import pprint

from ion.util.enhanced_resource_registry_client import EnhancedResourceRegistryClient

from pyon.util.containers import DotDict

from interface.services.coi.iidentity_management_service import IdentityManagementServiceClient

from ion.services.sa.test.helpers import any_old, AgentProcessStateGate

from ion.agents.instrument.driver_int_test_support import DriverIntegrationTestSupport


###############################################################################
# oms_uri: This indicates the URI to connect to the RSN OMS server endpoint.
# By default, this value is "launchsimulator" meaning that the simulator is to
# be launched as an external process for each test. This default is appropriate
# in general, and in particular for the buildbots. For local testing, the OMS
# environment variable can be used to indicate a different RSN OMS server endpoint.
# TODO(OOIION-1352): This URI might eventually be gotten from PYON configuration
oms_uri = os.getenv('OMS', "launchsimulator")

# initialization of the driver configuration. See setUp for possible update
# of the 'oms_uri' entry related with the special value "launchsimulator".
DVR_CONFIG = {
    'oms_uri': oms_uri
}

DVR_MOD = 'ion.agents.platform.rsn.rsn_platform_driver'
DVR_CLS = 'RSNPlatformDriver'


# DATA_TIMEOUT: timeout for reception of data sample
DATA_TIMEOUT = 90

# EVENT_TIMEOUT: timeout for reception of event
EVENT_TIMEOUT = 25

# checking for "alarm_defs" now fails (3/22 pm). Is it now "aparam_alert_config" ?

required_config_keys = [
    'org_name',
    'device_type',
    'agent',
    'driver_config',
    'stream_config',
    'startup_config',
    'aparam_alert_config',   # 'alarm_defs',
    'children']


# for common parameters to launch instrument simulator instances
SBE37 = CFG.device.sbe37


# Instruments that can be used (see _create_instrument). Reflects available
# simulators on sbe37-simulator.oceanobservatories.org as of 2013/03/31.
# Note(2014-06-18): actually only the one on port 4001 can be used in tests,
# but this can be "instantiated" multiple times.
instruments_dict = {
    "SBE37_SIM_01": {
        'DEV_ADDR'  : SBE37.host,
        'DEV_PORT'  : SBE37.port,
        'DATA_PORT' : 5001,
        'CMD_PORT'  : 6001,
        'PA_BINARY' : SBE37.port_agent_binary,
        'alt_ids'   : ["PRE:SBE37_SIM_01"]
    },

    "SBE37_SIM_02": {
        'DEV_ADDR'  : SBE37.host,
        'DEV_PORT'  : SBE37.port,
        'DATA_PORT' : 5002,
        'CMD_PORT'  : 6002,
        'PA_BINARY' : SBE37.port_agent_binary,
        'alt_ids'   : ["PRE:SBE37_SIM_02"]
    },

    "SBE37_SIM_03": {
        'DEV_ADDR'  : SBE37.host,
        'DEV_PORT'  : SBE37.port,
        'DATA_PORT' : 5003,
        'CMD_PORT'  : 6003,
        'PA_BINARY' : SBE37.port_agent_binary,
        'alt_ids'   : ["PRE:SBE37_SIM_03"]
    },

    "SBE37_SIM_04": {
        'DEV_ADDR'  : SBE37.host,
        'DEV_PORT'  : SBE37.port,
        'DATA_PORT' : 5004,
        'CMD_PORT'  : 6004,
        'PA_BINARY' : SBE37.port_agent_binary,
        'alt_ids'   : ["PRE:SBE37_SIM_04"]
    },

    "SBE37_SIM_05": {
        'DEV_ADDR'  : SBE37.host,
        'DEV_PORT'  : SBE37.port,
        'DATA_PORT' : 5005,
        'CMD_PORT'  : 6005,
        'PA_BINARY' : SBE37.port_agent_binary,
        'alt_ids'   : ["PRE:SBE37_SIM_05"]
    },

    "SBE37_SIM_06": {
        'DEV_ADDR'  : SBE37.host,
        'DEV_PORT'  : SBE37.port,
        'DATA_PORT' : 5006,
        'CMD_PORT'  : 6006,
        'PA_BINARY' : SBE37.port_agent_binary,
        'alt_ids'   : ["PRE:SBE37_SIM_06"]
    },

    "SBE37_SIM_07": {
        'DEV_ADDR'  : SBE37.host,
        'DEV_PORT'  : SBE37.port,
        'DATA_PORT' : 5007,
        'CMD_PORT'  : 6007,
        'PA_BINARY' : SBE37.port_agent_binary,
        'alt_ids'   : ["PRE:SBE37_SIM_07"]
    },

    "SBE37_SIM_08": {
        'DEV_ADDR'  : SBE37.host,
        'DEV_PORT'  : SBE37.port,
        'DATA_PORT' : 5008,
        'CMD_PORT'  : 6008,
        'PA_BINARY' : SBE37.port_agent_binary,
        'alt_ids'   : ["PRE:SBE37_SIM_08"]
    },
}


class FakeProcess(LocalContextMixin):
    """
    A fake process used because the test case is not an ion process.
    """
    name = ''
    id=''
    process_type = ''


@attr('INT', group='sa')
class BaseIntTestPlatform(IonIntegrationTestCase, HelperTestMixin):
    """
    A base class with several conveniences supporting specific platform agent
    integration tests, see:
    - ion/agents/platform/test/test_platform_agent.py
    - ion/agents/platform/test/test_mission_manager.py
    - ion/services/sa/observatory/test/test_platform_status.py
    - ion/services/sa/observatory/test/test_platform_launch.py
    - ion/services/sa/observatory/test/test_platform_multilaunch.py

    The platform IDs used here are organized as follows:
      Node1D -> MJ01C -> LJ01D

    where -> goes from parent platform to child platform.

    This is a subset of the whole topology defined in the simulated platform
    network (network.yml), which in turn is used by the RSN OMS simulator.

    - 'LJ01D'  is the root platform used in test_single_platform
    - 'Node1D' is the root platform used in test_hierarchy

    Methods are provided to construct specific platform topologies, but
    subclasses decide which to use.
    """

    @classmethod
    def setUpClass(cls):
        HelperTestMixin.setUpClass()
        cls._pp = pprint.PrettyPrinter()

    def setUp(self):

        DVR_CONFIG['oms_uri'] = self._dispatch_simulator(oms_uri)
        log.debug("DVR_CONFIG['oms_uri'] = %s", DVR_CONFIG['oms_uri'])

        self._start_container()

        self.container.start_rel_from_url('res/deploy/r2deploy.yml')

        self.RR   = ResourceRegistryServiceClient(node=self.container.node)
        self.IMS  = InstrumentManagementServiceClient(node=self.container.node)
        self.OMS  = ObservatoryManagementServiceClient(node=self.container.node)
        self.DAMS = DataAcquisitionManagementServiceClient(node=self.container.node)
        self.DP   = DataProductManagementServiceClient(node=self.container.node)
        self.PSC  = PubsubManagementServiceClient(node=self.container.node)
        self.PDC  = ProcessDispatcherServiceClient(node=self.container.node)
        self.DSC  = DatasetManagementServiceClient()
        self.IDS  = IdentityManagementServiceClient(node=self.container.node)
        self.RR2  = EnhancedResourceRegistryClient(self.RR)

        self.org_id = self.RR2.create(any_old(RT.Org))
        log.debug("Org created: %s", self.org_id)

        self._actor_header = get_system_actor_header()

        # Create InstrumentModel
        # TODO create multiple models as needed; for the moment assuming all
        # used instruments are the same model here.
        instModel_obj = IonObject(RT.InstrumentModel,
                                  name='SBE37IMModel',
                                  description="SBE37IMModel")
        self.instModel_id = self.IMS.create_instrument_model(instModel_obj)
        log.debug('new InstrumentModel id = %s ', self.instModel_id)

        self._get_network_definition()

        self._async_data_result = AsyncResult()
        self._data_subscribers = []
        self._samples_received = []
        self.addCleanup(self._stop_data_subscribers)

        self._event_subscribers = []
        self.addCleanup(self._stop_event_subscribers)

        # platforms that have been set up: platform_id: p_obj
        self._setup_platforms = {}

        # instruments that have been set up: instr_key: i_obj
        self._setup_instruments = {}

        # see _set_additional_extra_fields_for_platform_configuration
        self._additional_extra_fields = {}

        # see _set_receive_timeout
        self._receive_timeout = 177

    def _get_network_definition(self):
        """
        Called by setUp to get the platform network definition to be used, which
        is loaded from the file indicated by self._get_network_definition_filename().
        """
        yaml_filename = self._get_network_definition_filename()
        log.debug("retrieving network definition from %s", yaml_filename)
        self._network_definition = NetworkUtil.deserialize_network_definition(file(yaml_filename))

        if log.isEnabledFor(logging.TRACE):
            log.trace("NetworkDefinition serialization:\n%s",
                      NetworkUtil.serialize_network_definition(self._network_definition))

        # set attributes for the platforms:
        self._platform_attributes = {}
        for platform_id in self._network_definition.pnodes:
            pnode = self._network_definition.pnodes[platform_id]
            dic = dict((attr.attr_id, attr.defn) for attr in pnode.attrs.itervalues())
            self._platform_attributes[platform_id] = dic
        log.trace("_platform_attributes: %s", self._platform_attributes)

        # set ports for the platforms:
        self._platform_ports = {}
        for platform_id in self._network_definition.pnodes:
            pnode = self._network_definition.pnodes[platform_id]
            dic = {}
            for port_id, port in pnode.ports.iteritems():
                dic[port_id] = dict(port_id=port_id, instrument_ids=port.instrument_ids)
            self._platform_ports[platform_id] = dic
        log.trace("_platform_ports: %s", self._pp.pformat(self._platform_ports))

    def _get_network_definition_filename(self):
        return 'ion/agents/platform/rsn/simulator/network.yml'

    def _set_receive_timeout(self):
        """
        Method introduced to help deal with weird behaviors related with the
        patching of CFG.endpoint.receive.timeout. Each concrete test
        should call call this method at the beginning of the test itself (not
        in setUp where the patch mechanism as an annotation to the test class
        does not yet take effect).
        This method captures the current value of CFG.endpoint.receive.timeout
        to be used in some operations provided by the class.
        """
        self._receive_timeout = CFG.endpoint.receive.timeout
        log.info("self._receive_timeout = %s", self._receive_timeout)

    #################################################################
    # data subscribers handling
    #################################################################

    def _start_data_subscriber(self, stream_name, stream_id):
        """
        Starts data subscriber for the given stream_name and stream_config
        """

        def consume_data(message, stream_route, stream_id):
            # A callback for processing subscribed-to data.
            log.debug('Subscriber received data message: %s. stream_name=%r stream_id=%r',
                      message, stream_name, stream_id)
            self._samples_received.append(message)
            self._async_data_result.set()
            #if len(self._samples_received) > 5:
            #    self._async_data_result.set()

        log.info('_start_data_subscriber stream_name=%r stream_id=%r',
                 stream_name, stream_id)

        # Create subscription for the stream
        exchange_name = '%s_queue' % stream_name
        self.container.ex_manager.create_xn_queue(exchange_name).purge()
        sub = StandaloneStreamSubscriber(exchange_name, consume_data)
        sub.start()
        self._data_subscribers.append(sub)
        sub_id = self.PSC.create_subscription(name=exchange_name, stream_ids=[stream_id])
        self.PSC.activate_subscription(sub_id)
        sub.subscription_id = sub_id

    def _stop_data_subscribers(self):
        """
        Stop the data subscribers on cleanup.
        """
        try:
            for sub in self._data_subscribers:
                if hasattr(sub, 'subscription_id'):
                    try:
                        self.PSC.deactivate_subscription(sub.subscription_id)
                    except Exception:
                        pass
                    self.PSC.delete_subscription(sub.subscription_id)
                sub.stop()
        finally:
            self._data_subscribers = []

    #################################################################
    # event subscribers handling
    #################################################################

    def _start_event_subscriber2(self, count, event_type, cb=None, **kwargs):
        """
        Starts an event subscriber to expect the given number of events of the
        given event_type.
        Note: only the events of exactly the given type are considered,
        *no* subclasses of that type (note that the subscriber callback is also
        called with subclasses of the given type).

        @param count       number of event that should be received
        @param event_type  desired event type
        @param cb          mainly for logging purposes for the caller
        @param kwargs      other arguments for EventSubscriber constructor

        @return (async_event_result, events_received)  Use these to wait
                until the expected number of events.
        """

        async_event_result, events_received = AsyncResult(), []

        def consume_event(evt, *args, **kwargs):
            # A callback for consuming events.
            if evt.type_ != event_type:
                return
            if cb:
                cb(evt, args, kwargs)
            log.info('Event subscriber received evt: %s.', str(evt))
            events_received.append(evt)
            if count == 0:
                async_event_result.set(evt)

            elif count == len(events_received):
                async_event_result.set()

        sub = EventSubscriber(event_type=event_type,
                              callback=consume_event,
                              **kwargs)

        sub.start()
        log.info("registered event subscriber: count=%d, event_type=%r, kwargs=%s",
                 count, event_type, kwargs)

        self._event_subscribers.append(sub)
        sub._ready_event.wait(timeout=EVENT_TIMEOUT)

        return async_event_result, events_received

    def _start_ResourceAgentLifecycleEvent_subscriber(self, origin, origin_type, sub_type, count=1):
        return self._start_event_subscriber2(
            count=count,
            event_type="ResourceAgentLifecycleEvent",
            origin_type=origin_type,
            sub_type=sub_type,
            origin=origin)

    def _stop_event_subscribers(self):
        """
        Stops the event subscribers on cleanup.
        """
        try:
            for sub in self._event_subscribers:
                if hasattr(sub, 'subscription_id'):
                    try:
                        self.PSC.deactivate_subscription(sub.subscription_id)
                    except Exception:
                        pass
                    self.PSC.delete_subscription(sub.subscription_id)
                try:
                    sub.stop()
                except Exception as ex:
                    log.warn("Exception stopping subscriber, perhaps already stopped: %s", ex)
        finally:
            self._event_subscribers = []

    #################################################################
    # config supporting methods
    #################################################################

    def _get_platform_stream_configs(self):
        """
        This method is an adaptation of get_streamConfigs in
        test_driver_egg.py
        """
        return [
            StreamConfiguration(stream_name='parsed',
                                parameter_dictionary_name='platform_eng_parsed')

            # TODO include a "raw" stream?
        ]

    def _get_instrument_stream_configs(self):
        """
        configs copied from test_activate_instrument.py
        """
        return [
            StreamConfiguration(stream_name='raw',
                                parameter_dictionary_name='ctd_raw_param_dict'),

            StreamConfiguration(stream_name='parsed',
                                parameter_dictionary_name='ctd_parsed_param_dict')
        ]

    def _verify_child_config(self, config, device_id, is_platform):
        for key in required_config_keys:
            self.assertIn(key, config)

        if is_platform:
            self.assertEqual(RT.PlatformDevice, config['device_type'])
            for key in DVR_CONFIG.iterkeys():
                self.assertIn(key, config['driver_config'])

            for key in ['startup_config']:
                self.assertEqual({}, config[key])
        else:
            self.assertEqual(RT.InstrumentDevice, config['device_type'])

            for key in ['children']:
                self.assertEqual({}, config[key])

        self.assertEqual({'resource_id': device_id}, config['agent'])
        self.assertIn('stream_config', config)

    def _verify_parent_config(self, config, parent_device_id,
                              child_device_id, is_platform):
        for key in required_config_keys:
            self.assertIn(key, config)
        self.assertEqual(RT.PlatformDevice, config['device_type'])
        for key in DVR_CONFIG.iterkeys():
            self.assertIn(key, config['driver_config'])
        self.assertEqual({'resource_id': parent_device_id}, config['agent'])
        self.assertIn('stream_config', config)
        for key in ['startup_config']:
            self.assertEqual({}, config[key])

        self.assertIn(child_device_id, config['children'])
        self._verify_child_config(config['children'][child_device_id],
                                  child_device_id, is_platform)

    def _set_additional_extra_fields_for_platform_configuration(self, platform_id,
                                                                extra_fields):
        """
        Allows to indicate extra fields (which are used only once) for the
        creation of the very next RT.PlatformAgentInstance corresponding to
        the given platform_id.

        (This convenience method was introduced to include testing for
        https://jira.oceanobservatories.org/tasks/browse/OOIION-1268.
        See test_alerts in test_platform_agent.py.)

        @param platform_id   The ID of the platform to which the
                             additional extra fields will be used.

        @param extra_fields  the extra fields.
        """
        self._additional_extra_fields[platform_id] = extra_fields

    def _create_platform_configuration(self, platform_id, parent_platform_id=None):
        """
        This method is an adaptation of test_agent_instance_config in
        test_instrument_management_service_integration.py

        @param platform_id
        @param parent_platform_id
        @return a DotDict with various of the constructed elements associated
                to the platform.
        """


        #
        # TODO will each platform have its own param dictionary?
        #
        param_dict_name = 'platform_eng_parsed'
        parsed_rpdict_id = self.DSC.read_parameter_dictionary_by_name(
            param_dict_name,
            id_only=True)
        self.parsed_stream_def_id = self.PSC.create_stream_definition(
            name='parsed',
            parameter_dictionary_id=parsed_rpdict_id)

        def _make_platform_agent_structure(agent_config=None):
            if None is agent_config: agent_config = {}

            driver_config = copy.deepcopy(DVR_CONFIG)
            driver_config['attributes'] = self._platform_attributes[platform_id]
            driver_config['ports']      = self._platform_ports[platform_id]
            log.debug("driver_config: %s", driver_config)

            # instance creation
            extra_fields = {'driver_config': driver_config}

            # any additional extra fields?
            if platform_id in self._additional_extra_fields:
                add_fields = self._additional_extra_fields[platform_id]
                log.debug("adding extra fields for platform_id=%r: %s", platform_id, add_fields)
                extra_fields.update(add_fields)
                del self._additional_extra_fields[platform_id]

            platform_agent_instance_obj = any_old(RT.PlatformAgentInstance, extra_fields)
            platform_agent_instance_obj.agent_config = agent_config
            platform_agent_instance_id = self.IMS.create_platform_agent_instance(platform_agent_instance_obj)

            # agent creation
            platform_agent_obj = any_old(RT.PlatformAgent, {
                "stream_configurations": self._get_platform_stream_configs(),
                'driver_module':         DVR_MOD,
                'driver_class':          DVR_CLS})
            platform_agent_id = self.IMS.create_platform_agent(platform_agent_obj)

            # device creation
            platform_device_id = self.IMS.create_platform_device(any_old(RT.PlatformDevice))

            # data product creation
            dp_obj = any_old(RT.DataProduct)
            parsed_config = StreamConfiguration(stream_name='parsed', parameter_dictionary_name='ctd_parsed_param_dict')
            dp_id = self.DP.create_data_product(data_product=dp_obj, stream_definition_id=self.parsed_stream_def_id, default_stream_configuration=parsed_config)
            self.DAMS.assign_data_product(input_resource_id=platform_device_id, data_product_id=dp_id)
            self.DP.activate_data_product_persistence(data_product_id=dp_id)
            self.addCleanup(self.DP.delete_data_product, dp_id)

            # assignments
            self.RR2.assign_platform_agent_instance_to_platform_device_with_has_agent_instance(platform_agent_instance_id, platform_device_id)
            self.RR2.assign_platform_agent_to_platform_agent_instance_with_has_agent_definition(platform_agent_id, platform_agent_instance_id)
            self.RR2.assign_platform_device_to_org_with_has_resource(platform_agent_instance_id, self.org_id)

            #######################################
            # dataset

            log.debug('data product = %s', dp_id)

            stream_ids, _ = self.RR.find_objects(dp_id, PRED.hasStream, None, True)
            log.debug('Data product stream_ids = %s', stream_ids)
            stream_id = stream_ids[0]

            # Retrieve the id of the OUTPUT stream from the out Data Product
            dataset_ids, _ = self.RR.find_objects(dp_id, PRED.hasDataset, RT.Dataset, True)
            log.debug('Data set for data_product_id1 = %s', dataset_ids[0])
            #######################################

            return platform_agent_instance_id, platform_agent_id, platform_device_id, stream_id

        log.debug("Making the structure for a platform agent")

        # TODO Note: the 'platform_config' entry is a mechanism that the
        # platform agent expects to know the platform_id and parent_platform_id.
        # Determine how to finally indicate this info.
        platform_config = {
            'platform_id':             platform_id,
            'parent_platform_id':      parent_platform_id,
        }

        child_agent_config = {
            'platform_config': platform_config
        }
        platform_agent_instance_child_id, _, platform_device_child_id, stream_id = \
            _make_platform_agent_structure(child_agent_config)

        platform_agent_instance_child_obj = self.RR2.read(platform_agent_instance_child_id)

        self.platform_device_parent_id = platform_device_child_id

        p_obj = DotDict()
        p_obj.platform_id = platform_id
        p_obj.parent_platform_id = parent_platform_id
        p_obj.platform_agent_instance_obj = platform_agent_instance_child_obj
        p_obj.platform_device_id = platform_device_child_id
        p_obj.platform_agent_instance_id = platform_agent_instance_child_id
        p_obj.stream_id = stream_id
        p_obj.pid = None  # known when process launched
        return p_obj

    def _create_platform_site_and_deployment(self, platform_device_id=None, ):


        log.debug('_create_platform_site_and_deployment  platform_device_id: %s', platform_device_id)

        site_object = IonObject(RT.PlatformSite, name='PlatformSite1')
        platform_site_id = self.OMS.create_platform_site(platform_site=site_object, parent_id='')
        log.debug('_create_platform_site_and_deployment  site id: %s', platform_site_id)

        #create supporting objects for the Deployment resource
        # 1. temporal constraint
        # find current deployment using time constraints
        current_time =  int( calendar.timegm(time.gmtime()) )
        # two years on either side of current time
        start = current_time - 63115200
        end = current_time + 63115200
        temporal_bounds = IonObject(OT.TemporalBounds, name='planned', start_datetime=str(start), end_datetime=str(end))
        # 2. PlatformPort object which defines device to port map
        platform_port_obj= IonObject(OT.PlatformPort, reference_designator = 'GA01SUMO-FI003-01-CTDMO0999',
                                                        port_type=PortTypeEnum.UPLINK,
                                                        ip_address='0')

        # now create the Deployment
        deployment_obj = IonObject(RT.Deployment,
                                   name='TestPlatformDeployment',
                                   description='some new deployment',
                                   context=IonObject(OT.CabledNodeDeploymentContext),
                                   constraint_list=[temporal_bounds],
                                   port_assignments={platform_device_id:platform_port_obj})

        platform_deployment_id = self.OMS.create_deployment(deployment=deployment_obj, site_id=platform_site_id, device_id=platform_device_id)
        log.debug('_create_platform_site_and_deployment  deployment_id: %s', platform_deployment_id)

        deploy_obj2 = self.OMS.read_deployment(platform_deployment_id)
        log.debug('_create_platform_site_and_deployment  deploy_obj2 : %s', deploy_obj2)
        return platform_site_id, platform_deployment_id


    def _create_instrument_site_and_deployment(self, platform_site_id=None, instrument_device_id=None):

        site_object = IonObject(RT.InstrumentSite, name='InstrumentSite1')
        instrument_site_id = self.OMS.create_instrument_site(instrument_site=site_object, parent_id=platform_site_id)
        log.debug('_create_instrument_site_and_deployment  site id: %s', instrument_site_id)


        #create supporting objects for the Deployment resource
        # 1. temporal constraint
        # find current deployment using time constraints
        current_time =  int( calendar.timegm(time.gmtime()) )
        # two years on either side of current time
        start = current_time - 63115200
        end = current_time + 63115200
        temporal_bounds = IonObject(OT.TemporalBounds, name='planned', start_datetime=str(start), end_datetime=str(end))
        # 2. PlatformPort object which defines device to port map
        platform_port_obj= IonObject(OT.PlatformPort, reference_designator = 'GA01SUMO-FI003-01-CTDMO0999',
                                                        port_type=PortTypeEnum.PAYLOAD,
                                                        ip_address='0')

        # now create the Deployment
        deployment_obj = IonObject(RT.Deployment,
                                   name='TestInstrumentDeployment',
                                   description='some new deployment',
                                   context=IonObject(OT.CabledInstrumentDeploymentContext),
                                   constraint_list=[temporal_bounds],
                                   port_assignments={instrument_device_id:platform_port_obj})

        instrument_deployment_id = self.OMS.create_deployment(deployment=deployment_obj, site_id=instrument_site_id, device_id=instrument_device_id)
        log.debug('_create_instrument_site_and_deployment  deployment_id: %s', instrument_deployment_id)

        deploy_obj2 = self.OMS.read_deployment(instrument_deployment_id)
        log.debug('_create_instrument_site_and_deployment  deploy_obj2 : %s', deploy_obj2)
        return instrument_site_id, instrument_deployment_id

    def _create_platform(self, platform_id, parent_platform_id=None):
        """
        The main method to create a platform configuration and do other
        preparations for a given platform.
        """
        p_obj = self._create_platform_configuration(platform_id, parent_platform_id)

        # start corresponding data subscriber:
        self._start_data_subscriber(p_obj.platform_agent_instance_id,
                                    p_obj.stream_id)

        self._setup_platforms[platform_id] = p_obj
        return p_obj

    def _get_platform(self, platform_id):
        """
        Gets the p_obj constructed by _create_platform(platform_id).
        """
        self.assertIn(platform_id, self._setup_platforms)
        p_obj = self._setup_platforms[platform_id]
        return p_obj

    #################################################################
    # platform child-parent linking
    #################################################################

    def _assign_child_to_parent(self, p_child, p_parent):

        log.debug("assigning child platform %r to parent %r",
                  p_child.platform_id, p_parent.platform_id)

        #create geospatial (hasDevice) link btwn child and parent
#        self.RR2.assign_platform_device_to_platform_device_with_has_device(p_child.platform_device_id,
#                                                                           p_parent.platform_device_id)
#        child_device_ids = self.RR2.find_platform_device_ids_of_device_using_has_device(p_parent.platform_device_id)
#        self.assertNotEqual(0, len(child_device_ids))

        #create hasNetworkLink between child and parent
        self.RR.create_association(subject=p_child.platform_device_id, predicate=PRED.hasNetworkParent, object=p_parent.platform_device_id)

    #################################################################
    # instrument
    #################################################################

    def _set_up_pre_environment_for_instrument(self, instr_info, start_port_agent=True):
        """
        Based on test_instrument_agent.py

        Basically, this method prepares and returns an instrument driver
        configuration taking care of first launching a port agent if so
        indicated.

        @param instr_info        A value in instruments_dict
        @param start_port_agent  Should the port agent be started?
                                 True by default.

        @return instrument_driver_config
        """

        import sys
        from ion.agents.instrument.driver_process import DriverProcessType

        DEV_ADDR  = instr_info['DEV_ADDR']
        DEV_PORT  = instr_info['DEV_PORT']
        CMD_PORT  = instr_info['CMD_PORT']
        DATA_PORT = instr_info['DATA_PORT']
        PA_BINARY = instr_info['PA_BINARY']

        instrument_driver_config = {
            'dvr_egg' : SBE37.dvr_egg,
            'dvr_mod' : SBE37.dvr_mod,
            'dvr_cls' : SBE37.dvr_cls,
            'workdir' : SBE37.workdir,
            'process_type' : (DriverProcessType.EGG,)
        }

        if start_port_agent:
            # Dynamically load the egg into the test path
            from ion.agents.instrument.driver_process import ZMQEggDriverProcess
            launcher = ZMQEggDriverProcess(instrument_driver_config)
            egg = launcher._get_egg(SBE37.dvr_egg)
            if not egg in sys.path: sys.path.insert(0, egg)

            support = DriverIntegrationTestSupport(None,
                                                   None,
                                                   DEV_ADDR,
                                                   DEV_PORT,
                                                   DATA_PORT,
                                                   CMD_PORT,
                                                   PA_BINARY,
                                                   SBE37.delim,
                                                   SBE37.workdir)

            # Start port agent, add stop to cleanup.
            port = support.start_pagent()
            log.info('Port agent started at port %i. device=%s:%s', port, DEV_ADDR, DEV_PORT)
            self.addCleanup(support.stop_pagent)

            # Configure instrument driver to use port agent port number.
            instrument_driver_config['comms_config'] = {
                'addr':     'localhost',
                'port':     port,
                'cmd_port': CMD_PORT
            }

        # else: do NOT include any 'comms_config' in instrument_driver_config
        # so IMS.start_instrument_agent_instance will start the port agent
        # for us (see call in _start_instrument).
        # NOTE: this depends on current "hacky" logic in that IMS method.

        return instrument_driver_config

    def _make_instrument_agent_structure(self, instr_key, org_obj, agent_config=None,
                                         start_port_agent=True):
        if None is agent_config: agent_config = {}

        instr_info = instruments_dict[instr_key]

        # initially adapted from test_activate_instrument:test_activateInstrumentSample

        # agent creation
        instrument_agent_obj = IonObject(RT.InstrumentAgent,
                                         name='agent007_%s' % instr_key,
                                         description="SBE37IMAgent_%s" % instr_key,
                                         driver_uri=SBE37.dvr_egg,
                                         stream_configurations=self._get_instrument_stream_configs())

        instrument_agent_id = self.IMS.create_instrument_agent(instrument_agent_obj)
        log.debug('new InstrumentAgent id = %s', instrument_agent_id)

        self.IMS.assign_instrument_model_to_instrument_agent(self.instModel_id, instrument_agent_id)

        # device creation
        instDevice_obj = IonObject(RT.InstrumentDevice,
                                   name='SBE37IMDevice_%s' % instr_key,
                                   description="SBE37IMDevice_%s" % instr_key,
                                   serial_number="12345")
        instrument_device_id = self.IMS.create_instrument_device(instrument_device=instDevice_obj)
        self.IMS.assign_instrument_model_to_instrument_device(self.instModel_id, instrument_device_id)
        log.debug("new InstrumentDevice id = %s ", instrument_device_id)

        #Create stream alarms


        temp_alert_def = {
            'name' : 'temperature_warning_interval',
            'stream_name' : 'parsed',
            'description' : 'Temperature is below the normal range of 50.0 and above.',
            'alert_type' : StreamAlertType.WARNING,
            'aggregate_type' : AggregateStatusType.AGGREGATE_DATA,
            'value_id' : 'temp',
            'lower_bound' : 50.0,
            'lower_rel_op' : '<',
            'alert_class' : 'IntervalAlert'
        }

        late_data_alert_def = {
            'name' : 'late_data_warning',
            'stream_name' : 'parsed',
            'description' : 'Expected data has not arrived.',
            'alert_type' : StreamAlertType.WARNING,
            'aggregate_type' : AggregateStatusType.AGGREGATE_COMMS,
            'value_id' : None,
            'time_delta' : 2,
            'alert_class' : 'LateDataAlert'
        }

        instrument_driver_config = self._set_up_pre_environment_for_instrument(
            instr_info, start_port_agent=start_port_agent)
        log.debug("_set_up_pre_environment_for_instrument: %s", instrument_driver_config)

        port_agent_config = {
            'device_addr':     instr_info['DEV_ADDR'],
            'device_port':     instr_info['DEV_PORT'],
            'data_port':       instr_info['DATA_PORT'],
            'command_port':    instr_info['CMD_PORT'],
            'binary_path':     instr_info['PA_BINARY'],
            'process_type':    PortAgentProcessType.UNIX,
            'port_agent_addr': 'localhost',
            'log_level':       5,
            'type':            PortAgentType.ETHERNET
        }

        # instance creation
        instrument_agent_instance_obj = IonObject(RT.InstrumentAgentInstance,
                                                  name='SBE37IMAgentInstance_%s' % instr_key,
                                                  description="SBE37IMAgentInstance_%s" % instr_key,
                                                  driver_config=instrument_driver_config,
                                                  port_agent_config=port_agent_config,
                                                  alerts=[temp_alert_def, late_data_alert_def])

        instrument_agent_instance_obj.agent_config = agent_config
        instrument_agent_instance_obj.alt_ids = instr_info.get('alt_ids', [])

        instrument_agent_instance_id = self.IMS.create_instrument_agent_instance(instrument_agent_instance_obj)

        # data products

        org_id = self.RR2.create(org_obj)

        # parsed:

        parsed_pdict_id = self.DSC.read_parameter_dictionary_by_name('ctd_parsed_param_dict', id_only=True)
        parsed_stream_def_id = self.PSC.create_stream_definition(
            name='ctd_parsed',
            parameter_dictionary_id=parsed_pdict_id)

        dp_obj = IonObject(RT.DataProduct,
                           name='the parsed data for %s' % instr_key,
                           description='ctd stream test')

        parsed_config = StreamConfiguration(stream_name='parsed', parameter_dictionary_name='ctd_parsed_param_dict')
        data_product_id1 = self.DP.create_data_product(data_product=dp_obj,
                                                       stream_definition_id=parsed_stream_def_id,
                                                       default_stream_configuration=parsed_config)
        self.DP.activate_data_product_persistence(data_product_id=data_product_id1)
        self.addCleanup(self.DP.delete_data_product, data_product_id1)

        self.DAMS.assign_data_product(input_resource_id=instrument_device_id,
                                      data_product_id=data_product_id1)

        # raw:

        raw_pdict_id = self.DSC.read_parameter_dictionary_by_name('ctd_raw_param_dict', id_only=True)
        raw_stream_def_id = self.PSC.create_stream_definition(
            name='ctd_raw',
            parameter_dictionary_id=raw_pdict_id)

        dp_obj = IonObject(RT.DataProduct,
                           name='the raw data for %s' % instr_key,
                           description='raw stream test')

        raw_config = StreamConfiguration(stream_name='raw', parameter_dictionary_name='ctd_raw_param_dict')
        data_product_id2 = self.DP.create_data_product(data_product=dp_obj,
                                                       stream_definition_id=raw_stream_def_id,
                                                       default_stream_configuration=raw_config)

        self.DP.activate_data_product_persistence(data_product_id=data_product_id2)
        self.addCleanup(self.DP.delete_data_product, data_product_id2)

        self.DAMS.assign_data_product(input_resource_id=instrument_device_id,
                                      data_product_id=data_product_id2)

        # assignments
        self.RR2.assign_instrument_agent_instance_to_instrument_device_with_has_agent_instance(instrument_agent_instance_id, instrument_device_id)
        self.RR2.assign_instrument_agent_to_instrument_agent_instance_with_has_agent_definition(instrument_agent_id, instrument_agent_instance_id)
        self.RR2.assign_instrument_device_to_org_with_has_resource(instrument_agent_instance_id, org_id)

        i_obj = DotDict()
        i_obj.instrument_agent_id = instrument_agent_id
        i_obj.instrument_device_id = instrument_device_id
        i_obj.instrument_agent_instance_id = instrument_agent_instance_id
        i_obj.org_obj = org_obj

        log.debug("KK CREATED I_obj: %s", i_obj)

        return i_obj

    def _create_instrument(self, instr_key, start_port_agent=True):
        """
        The main method to create an instrument configuration.

        @param instr_key         A key in instruments_dict
        @param start_port_agent  Should the port agent be started?
                                 True by default.

        @return instrument_driver_config
        """

        self.assertIn(instr_key, instruments_dict)
        self.assertNotIn(instr_key, self._setup_instruments)

        instr_info = instruments_dict[instr_key]

        log.debug("_create_instrument: creating instrument %r: %s, start_port_agent=%s",
                  instr_key, instr_info, start_port_agent)

        org_obj = any_old(RT.Org)

        log.debug("making the structure for an instrument agent")
        i_obj = self._make_instrument_agent_structure(instr_key, org_obj,
                                                      start_port_agent=start_port_agent)

        self._setup_instruments[instr_key] = i_obj

        log.debug("_create_instrument: created instrument %r", instr_key)

        return i_obj

    def _get_instrument(self, instr_key):
        """
        Gets the i_obj constructed by _create_instrument(instr_key).
        """
        self.assertIn(instr_key, self._setup_instruments)
        i_obj = self._setup_instruments[instr_key]
        return i_obj

    #################################################################
    # instrument-platform linking
    #################################################################

    def _assign_instrument_to_platform(self, i_obj, p_obj):

        log.debug("assigning instrument %r to platform %r",
                  i_obj.instrument_agent_instance_id, p_obj.platform_id)

        self.RR2.assign_instrument_device_to_platform_device_with_has_device(
            i_obj.instrument_device_id,
            p_obj.platform_device_id)

        child_device_ids = self.RR2.find_instrument_device_ids_of_device_using_has_device(p_obj.platform_device_id)
        self.assertNotEqual(0, len(child_device_ids))

    #################################################################
    # some platform topologies
    #################################################################

    def _create_single_platform(self):
        """
        Creates and prepares a platform corresponding to the
        platform ID 'LJ01D', which is a leaf in the simulated network.
        """
        p_root = self._create_platform('LJ01D')
        return p_root

    def _create_small_hierarchy(self):
        """
        Creates a small platform network consisting of 3 platforms as follows:
          Node1D -> MJ01C -> LJ01D
        where -> goes from parent to child.
        """

        p_root       = self._create_platform('Node1D')
        p_child      = self._create_platform('MJ01C', parent_platform_id='Node1D')
        p_grandchild = self._create_platform('LJ01D', parent_platform_id='MJ01C')

        self._assign_child_to_parent(p_child, p_root)
        self._assign_child_to_parent(p_grandchild, p_child)

        return p_root

    def _create_hierarchy(self, platform_id, p_objs, parent_obj=None):
        """
        Creates a hierarchy of platforms rooted at the given platform.

        @param platform_id  ID of the root platform at this level
        @param p_objs       dict to be updated with (platform_id: p_obj)
                            mappings
        @param parent_obj   platform object of the parent, if any

        @return platform object for the created root.
        """

        # create the object to be returned:
        p_obj = self._create_platform(platform_id)

        # update (platform_id: p_obj) dict:
        p_objs[platform_id] = p_obj

        # recursively create child platforms:
        pnode = self._network_definition.pnodes[platform_id]
        for sub_platform_id in pnode.subplatforms:
            self._create_hierarchy(sub_platform_id, p_objs, p_obj)

        if parent_obj:
            self._assign_child_to_parent(p_obj, parent_obj)

        return p_obj

    def _set_up_single_platform_with_some_instruments(self, instr_keys,
                                                      start_port_agent=True):
        """
        Sets up single platform with some instruments

        @param instr_keys  Keys of the instruments to be assigned.
                           Must be keys in instruments_dict in
                           base_test_platform_agent

        @param start_port_agent  Should the port agents be started?
                                 True by default.

        @return p_root for subsequent termination
        """

        for instr_key in instr_keys:
            self.assertIn(instr_key, instruments_dict)

        p_root = self._create_single_platform()

        # create and assign instruments:
        for instr_key in instr_keys:
            # create only if not already created:
            if instr_key in self._setup_instruments:
                i_obj = self._setup_instruments[instr_key]
            else:
                i_obj = self._create_instrument(instr_key, start_port_agent=start_port_agent)
            self._assign_instrument_to_platform(i_obj, p_root)

        return p_root

    def _set_up_small_hierarchy_with_some_instruments(self, instr_keys,
                                                      start_port_agent=True):
        """
        Creates a small platform network consisting of 3 platforms as follows:
          Node1D -> MJ01C -> LJ01D
        and the given instruments, which are all assigned to the leaf platform
        LJ01D.
        """
        for instr_key in instr_keys:
            self.assertIn(instr_key, instruments_dict)

        #####################################
        # create platform hierarchy
        #####################################
        log.info("will create platform hierarchy ...")
        p_root       = self._create_platform('Node1D')
        p_child      = self._create_platform('MJ01C', parent_platform_id='Node1D')
        p_grandchild = self._create_platform('LJ01D', parent_platform_id='MJ01C')

        self._assign_child_to_parent(p_child, p_root)
        self._assign_child_to_parent(p_grandchild, p_child)

        #####################################
        # create the indicated instruments
        #####################################
        log.info("will create %d instruments: %s", len(instr_keys), instr_keys)

        created = 0
        for instr_key in instr_keys:
            # create only if not already created:
            if instr_key in self._setup_instruments:
                i_obj = self._setup_instruments[instr_key]
                log.debug("instrument was already created = %r (%s)",
                          i_obj.instrument_agent_instance_id, instr_key)
            else:
                i_obj = self._create_instrument(instr_key, start_port_agent=start_port_agent)
                log.debug("instrument created = %r (%s)",
                          i_obj.instrument_agent_instance_id, instr_key)
                created += 1

        log.info("%d instruments created.", created)

        #####################################
        # assign the instruments
        #####################################
        log.info("will assign %d instruments to the leaf platform...", len(instr_keys))
        for instr_key in instr_keys:
            i_obj = self._setup_instruments[instr_key]
            self._assign_instrument_to_platform(i_obj, p_grandchild)
            log.debug("instrument %r (%s) assigned to leaf platform",
                      i_obj.instrument_agent_instance_id,
                      instr_key)

        log.info("%d instruments assigned.", len(instr_keys))

        return p_root

    def _set_up_platform_hierarchy_with_some_instruments(self, instr_keys,
                                                         start_port_agent=True):
        """
        Sets up a multiple-level platform hierarchy with instruments associated
        to some of the platforms.

        The platform hierarchy corresponds to the sub-network in the
        simulated topology rooted at 'Node1B', which at time of writing
        looks like this:

        Node1B
            Node1C
                Node1D
                    MJ01C
                        LJ01D
                LV01C
                    PC01B
                        SC01B
                            SF01B
                    LJ01C
            LV01B
                LJ01B
                MJ01B

        In DEBUG logging level for the platform agent, files like the following
        are generated under logs/:
           platform_CFG_received_Node1B.txt
           platform_CFG_received_MJ01C.txt
           platform_CFG_received_LJ01D.txt

        @param instr_keys  Keys of the instruments to be assigned.
                           Must be keys in instruments_dict in
                           base_test_platform_agent

        @param start_port_agent  Should the port agents be started?
                                 True by default.

        @return p_root for subsequent termination
        """

        for instr_key in instr_keys:
            self.assertIn(instr_key, instruments_dict)

        #####################################
        # create platform hierarchy
        #####################################
        log.info("will create platform hierarchy ...")
        start_time = time.time()

        root_platform_id = 'Node1B'
        p_objs = {}
        p_root = self._create_hierarchy(root_platform_id, p_objs)

        log.info("platform hierarchy built. Took %.3f secs. "
                  "Root platform=%r, number of platforms=%d: %s",
                  time.time() - start_time,
                  root_platform_id, len(p_objs), p_objs.keys())

        self.assertIn(root_platform_id, p_objs)
        self.assertEquals(13, len(p_objs))

        #####################################
        # create the indicated instruments
        #####################################
        log.info("will create %d instruments: %s", len(instr_keys), instr_keys)
        start_time = time.time()

        i_objs = []
        created = 0
        for instr_key in instr_keys:
            # create only if not already created:
            if instr_key in self._setup_instruments:
                i_obj = self._setup_instruments[instr_key]
                i_objs.append(i_obj)
                log.debug("instrument was already created = %r (%s)",
                          i_obj.instrument_agent_instance_id, instr_key)
            else:
                i_obj = self._create_instrument(instr_key, start_port_agent=start_port_agent)
                i_objs.append(i_obj)
                log.debug("instrument created = %r (%s)",
                          i_obj.instrument_agent_instance_id, instr_key)
                created += 1

        log.info("%d instruments created. Took %.3f secs.", created, time.time() - start_time)

        #####################################
        # assign the instruments
        #####################################
        log.info("will assign instruments ...")
        start_time = time.time()

        plats_to_assign_instrs = [
            'LJ01D', 'SF01B', 'LJ01B', 'MJ01B',     # leaves
            'MJ01C', 'Node1D', 'LV01B', 'Node1C'    # intermediate
        ]

        # assign one available instrument to a platform;
        # the assignments are arbitrary.
        num_assigns = min(len(instr_keys), len(plats_to_assign_instrs))

        for ii in range(num_assigns):
            platform_id = plats_to_assign_instrs[ii]
            self.assertIn(platform_id, p_objs)
            p_obj = p_objs[platform_id]
            i_obj = i_objs[ii]
            self._assign_instrument_to_platform(i_obj, p_obj)
            log.debug("instrument %r (%s) assigned to platform %r",
                      i_obj.instrument_agent_instance_id,
                      instr_keys[ii],
                      platform_id)

        log.info("%d instruments assigned. Took %.3f secs.",
                 num_assigns, time.time() - start_time)

        return p_root

    #################################################################
    # start / stop platform
    #################################################################

    def _start_platform(self, p_obj):
        """
        Starts the given platform waiting for it to transition to the
        UNINITIALIZED state (note that the agent starts in the LAUNCHING state).

        More in concrete the sequence of steps here are:
        - prepares subscriber to receive the UNINITIALIZED state transition
        - launches the platform process
        - waits for the start of the process
        - waits for the transition to the UNINITIALIZED state
        """
        self._pa_client = self._start_a_platform(p_obj)

    def _start_a_platform(self, p_obj):
        """
        As described for _start_platform but here returning the ResourceAgentClient object instead of
        assigning it to self._pa_client, so we can use this method in a more flexible way.
        """
        ##############################################################
        # prepare to receive the UNINITIALIZED state transition:
        async_res = AsyncResult()

        def consume_event(evt, *args, **kwargs):
            log.debug("Got ResourceAgentStateEvent %s from origin %r", evt.state, evt.origin)
            if evt.state == PlatformAgentState.UNINITIALIZED:
                async_res.set(evt)

        # start subscriber:
        sub = EventSubscriber(event_type="ResourceAgentStateEvent",
                              origin=p_obj.platform_device_id,
                              callback=consume_event)
        sub.start()
        log.info("registered event subscriber to wait for state=%r from origin %r",
                 PlatformAgentState.UNINITIALIZED, p_obj.platform_device_id)
        self._event_subscribers.append(sub)
        sub._ready_event.wait(timeout=EVENT_TIMEOUT)

        ##############################################################
        # now start the platform:
        agent_instance_id = p_obj.platform_agent_instance_id
        log.debug("about to call start_platform_agent_instance with id=%s", agent_instance_id)
        p_obj.pid = self.IMS.start_platform_agent_instance(platform_agent_instance_id=agent_instance_id,
                                                           headers=self._actor_header)
        log.debug("start_platform_agent_instance returned pid=%s", p_obj.pid)

        #wait for start
        gate = AgentProcessStateGate(self.PDC.read_process,
                                     p_obj.platform_device_id,
                                     ProcessStateEnum.RUNNING)
        self.assertTrue(gate.await(90), "The platform agent instance did not spawn in 90 seconds")

        # Start a resource agent client to talk with the agent.
        pa_client = ResourceAgentClient(p_obj.platform_device_id,
                                        name=gate.process_id,
                                        process=FakeProcess())
        log.debug("got platform agent client %s", pa_client)

        ##############################################################
        # wait for the UNINITIALIZED event:
        async_res.get(timeout=self._receive_timeout)
        return pa_client

    def _stop_platform(self, p_obj):
        try:
            self.IMS.stop_platform_agent_instance(p_obj.platform_agent_instance_id)
        except Exception:
            if log.isEnabledFor(logging.TRACE):
                log.exception(
                    "platform_id=%r: Exception in IMS.stop_platform_agent_instance with "
                    "platform_agent_instance_id = %r",
                    p_obj.platform_id, p_obj.platform_agent_instance_id)
            else:
                log.warn(
                    "platform_id=%r: Exception in IMS.stop_platform_agent_instance with "
                    "platform_agent_instance_id = %r. Perhaps already dead.",
                    p_obj.platform_id, p_obj.platform_agent_instance_id)

    #################################################################
    # start / stop instrument
    #################################################################

    def IMS_start_instrument_agent_instance(self, instrument_agent_instance_id):
        """
        Like IMS.start_instrument_agent_instance but with no launching of the
        port agent and with *many* hacks to make it work! :(
        """

        instrument_agent_instance_obj = self.IMS.read_instrument_agent_instance(instrument_agent_instance_id)

        from interface.services.sa.iinstrument_management_service import InstrumentManagementServiceDependentClients
        process = FakeProcess()
        process.container = self.container
        clients = InstrumentManagementServiceDependentClients(process=process)
        from ion.services.sa.instrument.agent_configuration_builder import InstrumentAgentConfigurationBuilder
        config_builder = InstrumentAgentConfigurationBuilder(clients)
        from ion.util.agent_launcher import AgentLauncher
        launcher = AgentLauncher(clients.process_dispatcher)
        try:
            config_builder.set_agent_instance_object(instrument_agent_instance_obj)
            config = config_builder.prepare()
        except Exception:
            log.error('failed to launch', exc_info=True)
            raise ServerError('failed to launch')

        process_id = launcher.launch(config, config_builder._get_process_definition()._id)
        if not process_id:
            raise ServerError("Launched instrument agent instance but no process_id")
        config_builder.record_launch_parameters(config)

        launcher.await_launch(timeout=90)
        log.debug("IMS_start_instrument_agent_instance, "
                  "launched! process_id=%r", process_id)

        return process_id

    def _start_instrument(self, i_obj, use_ims=True):
        """
        Starts the given instrument waiting for it to transition to the
        UNINITIALIZED state.

        More in concrete the sequence of steps here are:
        - prepares subscriber to receive the UNINITIALIZED state transition
        - launches the instrument process
        - waits for the start of the process
        - waits for the transition to the UNINITIALIZED state

        @param i_obj     instrument
        @param use_ims   True (the default) to use IMS.start_instrument_agent_instance
                         (which also starts port agent;
                         False to use a simplified version of that IMS method
                        but with *no* launching any port agent.
        @return ResourceAgentClient object
        """
        ##############################################################
        # prepare to receive the UNINITIALIZED state transition:
        async_res = AsyncResult()

        def consume_event(evt, *args, **kwargs):
            log.debug("Got ResourceAgentStateEvent %s from origin %r", evt.state, evt.origin)
            if evt.state == ResourceAgentState.UNINITIALIZED:
                async_res.set(evt)

        # start subscriber:
        sub = EventSubscriber(event_type="ResourceAgentStateEvent",
                              origin=i_obj.instrument_device_id,
                              callback=consume_event)
        sub.start()
        log.info("registered event subscriber to wait for state=%r from origin %r",
                 ResourceAgentState.UNINITIALIZED, i_obj.instrument_device_id)
        self._event_subscribers.append(sub)
        sub._ready_event.wait(timeout=EVENT_TIMEOUT)

        ##############################################################
        # now start the instrument:

        agent_instance_id = i_obj.instrument_agent_instance_id
        if use_ims:
            log.debug("calling IMS.start_instrument_agent_instance with id=%s", agent_instance_id)
            i_obj.pid = self.IMS.start_instrument_agent_instance(instrument_agent_instance_id=agent_instance_id,
                                                                 headers=self._actor_header)

        else:
            log.debug("calling IMS_start_instrument_agent_instance with id=%s", agent_instance_id)
            i_obj.pid = self.IMS_start_instrument_agent_instance(instrument_agent_instance_id=agent_instance_id)

        log.debug("[,]start_instrument_agent_instance returned pid=%s for instrument_agent_instance_id=%s",
                  i_obj.pid, agent_instance_id)

        agent_instance_obj = self.IMS.read_instrument_agent_instance(agent_instance_id)
        agent_process_id = ResourceAgentClient._get_agent_process_id(i_obj.instrument_device_id)
        log.debug("[,]agent_process_id=%s",
                  agent_process_id)

        # so, here, i_obj.pid must be equal to agent_process_id.

        # Start a resource agent client to talk with the agent.
        ia_client = ResourceAgentClient(i_obj.instrument_device_id,
                                        name=agent_process_id,
                                        process=FakeProcess())
        log.debug("got instrument agent client %s", str(ia_client))

        ##############################################################
        # wait for the UNINITIALIZED event:
        evt = async_res.get(timeout=self._receive_timeout)
        log.debug("[,]Got UNINITIALIZED event from %r", evt.origin)

        return ia_client

    def _stop_instrument(self, i_obj, use_ims=True):
        """
        Stops the given instrument.

        If IMS.stop_instrument_agent_instance is used, any exception there is
        logged out simply at the DUBUG level because, in general, the most
        probably cause is that the instrument would have already been
        terminated by its parent platform.

        (Note that IMS.stop_instrument_agent_instance stops the associated
        port agent even if the termination of the instrument agent itself
        fails for any reason.)

        @param i_obj     instrument
        @param use_ims   True (the default) to use IMS.stop_instrument_agent_instance;
                         False to get the pid using
                         ResourceAgentClient._get_agent_process_id
                         and call PDC's cancel_process
        """
        if use_ims:
            try:
                self.IMS.stop_instrument_agent_instance(i_obj.instrument_agent_instance_id)
            except Exception as e:
                log.debug("Exception in IMS.stop_instrument_agent_instance with "
                          "instrument_agent_instance_id = %r (the instrument "
                          "agent instance has probably already been terminated by its "
                          "parent platform): %s",
                          i_obj.instrument_agent_instance_id, e)

        else:
            try:
                pid = ResourceAgentClient._get_agent_process_id(i_obj.instrument_device_id)
                if pid is not None:
                    log.debug("cancel_process: canceling pid=%r", pid)
                    self.PDC.cancel_process(pid)
                else:
                    log.debug("_get_agent_process_id returned None; process already dead?")
            except Exception as ex:
                log.warn("error getting agent process id of %r, or while "
                         "canceling process, probably already dead?: %s",
                         i_obj.instrument_device_id, ex)

    #################################################################
    # misc convenience methods
    #################################################################

    def _create_resource_agent_client(self, resource_id):
        client = ResourceAgentClient(resource_id, process=FakeProcess())
        return client

    def _get_state(self, pa_client=None):
        pa_client = pa_client or self._pa_client
        state = pa_client.get_agent_state()
        return state

    def _assert_state(self, state, pa_client=None):
        pa_client = pa_client or self._pa_client
        self.assertEquals(self._get_state(pa_client), state)

    def _assert_agent_client_state(self, a_client, state):
        self.assertEqual(state, a_client.get_agent_state())

    def _execute_agent(self, cmd, pa_client=None):
        pa_client = pa_client or self._pa_client
        log.info("_execute_agent: cmd=%r kwargs=%r; timeout=%s ...",
                 cmd.command, cmd.kwargs, self._receive_timeout)
        time_start = time.time()
        retval = pa_client.execute_agent(cmd, timeout=self._receive_timeout)
        elapsed_time = time.time() - time_start
        log.info("_execute_agent: timing cmd=%r elapsed_time=%s, retval = %s",
                 cmd.command, elapsed_time, str(retval))
        return retval

    #################################################################
    # commands that concrete tests can call
    #################################################################

    def _ping_agent(self, pa_client=None):
        pa_client = pa_client or self._pa_client
        retval = pa_client.ping_agent()
        self.assertIsInstance(retval, str)

    def _ping_resource(self, pa_client=None):
        pa_client = pa_client or self._pa_client
        cmd = AgentCommand(command=PlatformAgentEvent.PING_RESOURCE)
        if self._get_state(pa_client) == PlatformAgentState.UNINITIALIZED:
            # should get ServerError: "Command not handled in current state"
            with self.assertRaises(ServerError):
                pa_client.execute_agent(cmd)
        else:
            # In all other states the command should be accepted:
            retval = self._execute_agent(cmd, pa_client)
            self.assertEquals("PONG", retval.result)

    def _execute_resource(self, cmd, pa_client=None, *args, **kwargs):
        pa_client = pa_client or self._pa_client
        cmd = AgentCommand(command=cmd, args=args, kwargs=kwargs)
        retval = pa_client.execute_resource(cmd)
        log.debug("_execute_resource: cmd=%s: retval=%s", cmd, retval)
        self.assertTrue(retval.result)
        return retval.result

    def _get_metadata(self, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(metadata=None)
        cmd = AgentCommand(command=PlatformAgentEvent.GET_RESOURCE, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        md = retval.result
        self.assertIsInstance(md, dict)
        # TODO verify possible subset of required entries in the dict.
        log.info("_get_metadata = %s", md)
        return md

    def _get_ports(self, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(ports=None)
        cmd = AgentCommand(command=PlatformAgentEvent.GET_RESOURCE, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        ports = retval.result
        log.info("_get_ports = %s", ports)
        self.assertIsInstance(ports, dict)
        for port_id, info in ports.iteritems():
            self.assertIsInstance(info, dict)
            self.assertIn('state', info)
        return ports

    def _initialize(self, recursion=True, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        self._assert_state(PlatformAgentState.UNINITIALIZED, pa_client)
        cmd = AgentCommand(command=PlatformAgentEvent.INITIALIZE, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.INACTIVE, pa_client)

    def _go_active(self, recursion=True, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        cmd = AgentCommand(command=PlatformAgentEvent.GO_ACTIVE, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.IDLE, pa_client)

    def _run(self, recursion=True, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        cmd = AgentCommand(command=PlatformAgentEvent.RUN, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.COMMAND, pa_client)

    def _start_resource_monitoring(self, recursion=3, pa_client=None):
        """
        @param recursion by default 3 to propagate to both sub-platforms and instruments
        """
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        cmd = AgentCommand(command=PlatformAgentEvent.START_MONITORING, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.MONITORING, pa_client)

    def _wait_for_a_data_sample(self):
        log.info("waiting for reception of a data sample...")
        # just wait for at least one -- see consume_data
        self._async_data_result.get(timeout=DATA_TIMEOUT)
        self.assertTrue(len(self._samples_received) >= 1)
        log.info("Received samples: %s", len(self._samples_received))

    def _stop_resource_monitoring(self, recursion=3, pa_client=None):
        """
        @param recursion by default 3 to propagate to both sub-platforms and instruments
        """
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        cmd = AgentCommand(command=PlatformAgentEvent.STOP_MONITORING, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.COMMAND, pa_client)

    def _pause(self, recursion=True, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        cmd = AgentCommand(command=PlatformAgentEvent.PAUSE, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.STOPPED, pa_client)

    def _resume(self, recursion=True, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        cmd = AgentCommand(command=PlatformAgentEvent.RESUME, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.COMMAND, pa_client)

    def _clear(self, recursion=True, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        cmd = AgentCommand(command=PlatformAgentEvent.CLEAR, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.IDLE, pa_client)

    def _go_inactive(self, recursion=True, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        cmd = AgentCommand(command=PlatformAgentEvent.GO_INACTIVE, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.INACTIVE, pa_client)

    def _reset(self, recursion=True, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        cmd = AgentCommand(command=PlatformAgentEvent.RESET, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.UNINITIALIZED, pa_client)

    def _shutdown(self, recursion=True, pa_client=None):
        pa_client = pa_client or self._pa_client
        kwargs = dict(recursion=recursion)
        cmd = AgentCommand(command=PlatformAgentEvent.SHUTDOWN, kwargs=kwargs)
        retval = self._execute_agent(cmd, pa_client)
        self._assert_state(PlatformAgentState.UNINITIALIZED, pa_client)

    def _stream_instruments(self):
        from mi.instrument.seabird.sbe37smb.ooicore.driver import SBE37ProtocolEvent

        for instrument in  self._setup_instruments.itervalues():
            # instruments that have been set up: instr_key: i_obj

            # Start a resource agent client to talk with the instrument agent.
            _ia_client = self._create_resource_agent_client(instrument.instrument_device_id)

            cmd = AgentCommand(command=SBE37ProtocolEvent.START_AUTOSAMPLE)
            retval = _ia_client.execute_resource(cmd)
            log.debug('_stream_instruments retval: %s', retval)

        return

    def _idle_instruments(self):
        from mi.instrument.seabird.sbe37smb.ooicore.driver import SBE37ProtocolEvent

        for instrument in  self._setup_instruments.itervalues():
            # instruments that have been set up: instr_key: i_obj

            # Start a resource agent client to talk with the instrument agent.
            _ia_client = self._create_resource_agent_client(instrument.instrument_device_id)

            cmd = AgentCommand(command=SBE37ProtocolEvent.STOP_AUTOSAMPLE)
            retval = _ia_client.execute_resource(cmd)

            cmd = AgentCommand(command=ResourceAgentEvent.RESET)
            retval = _ia_client.execute_agent(cmd)
            state = _ia_client.get_agent_state()
            self.assertEqual(state, ResourceAgentState.UNINITIALIZED)

        return
