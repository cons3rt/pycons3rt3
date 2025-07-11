"""
cons3rtinfra.py

An object to describe a CONS3RT infrastructure

"""

class Cons3rtInfra(object):

    def __init__(self, web_gateway_ip, messaging_inbound_ip, webdav_inbound_ip, assetdb_inbound_ip,
                 sourcebuilder_inbound_ip, cons3rt_outbound_ip, venue_outbound_ip, elastic_logging_ip,
                 web_gateway_port=443, messaging_port=4443, webdav_port=7443, assetdb_port=8443,
                 sourcebuilder_port=5443, elastic_logging_port=443, elastic_fleet_server_fqdn=None,
                 ca_download_url=None):
        self.web_gateway_ip = web_gateway_ip
        self.messaging_inbound_ip = messaging_inbound_ip
        self.webdav_inbound_ip = webdav_inbound_ip
        self.assetdb_inbound_ip = assetdb_inbound_ip
        self.sourcebuilder_inbound_ip = sourcebuilder_inbound_ip
        self.cons3rt_outbound_ip = cons3rt_outbound_ip
        self.venue_outbound_ip = venue_outbound_ip
        self.elastic_logging_ip = elastic_logging_ip
        self.web_gateway_port = web_gateway_port
        self.messaging_port = messaging_port
        self.webdav_port = webdav_port
        self.assetdb_port = assetdb_port
        self.sourcebuilder_port = sourcebuilder_port
        self.elastic_logging_port = elastic_logging_port
        self.elastic_fleet_server_fqdn = elastic_fleet_server_fqdn
        self.ca_download_url = ca_download_url
