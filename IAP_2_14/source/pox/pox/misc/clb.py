"""
Author Haichen Shen

Module to perform round-robin load balancing.
"""

from pox.core import core
import pox.openflow.libopenflow_01 as of
from pox.lib.revent import *
from pox.lib.util import dpidToStr
from pox.lib.packet.ethernet import ethernet
from pox.lib.packet.arp import arp
from pox.lib.addresses import IPAddr, EthAddr
import time

log = core.getLogger()

IDLE_TIMEOUT = 60 # in seconds
HARD_TIMEOUT = 0 # infinity

# LOAD_BALANCER_IP = IPAddr('10.0.0.2')
# LOAD_BALANCER_MAC = EthAddr('9a:bc:f6:be:3d:41')
ARP_MAPPING={}
ARP_MAPPING[IPAddr('10.0.0.2')]=EthAddr('9a:bc:f6:be:3d:41')
ARP_MAPPING[IPAddr('10.0.0.1')]=EthAddr('1e:7a:13:29:df:4c')

class LoadBalancer (EventMixin):
  # What to do when switch receives ARP request from client side
  def handle_arp (self, packet, in_port):
    print "ARP Packet Arrived"

    # Get the ARP request from packet
    arp_req = packet.next

    # Create ARP reply
    arp_rep = arp()
    arp_rep.opcode = arp.REPLY

    # Show the client that it's actually the "main" server
    arp_rep.hwsrc = LOAD_BALANCER_MAC
    arp_rep.hwdst = arp_req.hwsrc
    arp_rep.protosrc = LOAD_BALANCER_IP
    arp_rep.protodst = arp_req.protosrc

    # Create the Ethernet packet
    eth = ethernet()
    eth.type = ethernet.ARP_TYPE
    eth.dst = packet.src
    eth.src = LOAD_BALANCER_MAC
    eth.set_payload(arp_rep)

    # Send the ARP reply to client
    # msg is the "packet out" message. Now giving this packet special properties
    msg = of.ofp_packet_out()
    msg.data = eth.pack()
    msg.actions.append(of.ofp_action_output(port = of.OFPP_IN_PORT))
    msg.in_port = in_port
    self.connection.send(msg)

  # What do to when I(Load balancer) got a request from a client
  # Logically, I must create a new packet and send it to one of the replica server
  # The replica server, when it gets a request, it must send a reply to the load balancer
  # The load balancer will take this reply and create a new reply out of this packet
  # And send it to the client
  # To the client, all this will happen transparently
  def handle_request (self, packet, event):

    # Get the next server to handle the request
    #server = self.get_next_server()

    "First install the reverse rule from server to client"
    msg = of.ofp_flow_mod()
    msg.idle_timeout = IDLE_TIMEOUT
    msg.hard_timeout = HARD_TIMEOUT
    msg.buffer_id = None

    # Set packet matching
    # Match (in_port, src MAC, dst MAC, src IP, dst IP)
    msg.match.in_port = server.port
    msg.match.dl_src = server.mac
    msg.match.dl_dst = packet.src
    msg.match.dl_type = ethernet.IP_TYPE
    msg.match.nw_src = server.ip
    msg.match.nw_dst = packet.next.srcip

    # Append actions
    # Set the src IP and MAC to load balancer's
    # Forward the packet to client's port
    msg.actions.append(of.ofp_action_nw_addr.set_src(LOAD_BALANCER_IP))
    msg.actions.append(of.ofp_action_dl_addr.set_src(LOAD_BALANCER_MAC))
    msg.actions.append(of.ofp_action_output(port = event.port))

    self.connection.send(msg)

    "Second install the forward rule from client to server"
    msg = of.ofp_flow_mod()
    msg.idle_timeout = IDLE_TIMEOUT
    msg.hard_timeout = HARD_TIMEOUT
    msg.buffer_id = None
    msg.data = event.ofp # Forward the incoming packet

    # Set packet matching
    # Match (in_port, MAC src, MAC dst, IP src, IP dst)
    msg.match.in_port = event.port
    msg.match.dl_src = packet.src
    msg.match.dl_dst = LOAD_BALANCER_MAC
    msg.match.dl_type = ethernet.IP_TYPE
    msg.match.nw_src = packet.next.srcip
    msg.match.nw_dst = LOAD_BALANCER_IP
    
    # Append actions
    # Set the dst IP and MAC to load balancer's
    # Forward the packet to server's port
    msg.actions.append(of.ofp_action_nw_addr.set_dst(server.ip))
    msg.actions.append(of.ofp_action_dl_addr.set_dst(server.mac))
    msg.actions.append(of.ofp_action_output(port = server.port))

    self.connection.send(msg)

    log.info("Installing %s <-> %s" % (packet.next.srcip, server.ip))

  def _handle_PacketIn (self, event):
    print "packet Arrived"
    packet = event.parse()

    if packet.type == packet.LLDP_TYPE or packet.type == packet.IPV6_TYPE:
      # Drop LLDP packets 
      # Drop IPv6 packets
      # send of command without actions

      msg = of.ofp_packet_out()
      msg.buffer_id = event.ofp.buffer_id
      msg.in_port = event.port
      self.connection.send(msg)

    elif packet.type == packet.ARP_TYPE:
      print "ARP Packet Yes"
      # Handle ARP request for load balancer

      # Only accept ARP request for load balancer
      #if packet.next.protodst != LOAD_BALANCER_IP:
      #  return

      log.debug("Receive an ARP request")
      self.handle_arp(packet, event.port)

    elif packet.type == packet.IP_TYPE:
      # Handle client's request

      # Only accept ARP request for load balancer
      if packet.next.dstip != LOAD_BALANCER_IP:
        return

      log.debug("Receive an IPv4 packet from %s" % packet.next.srcip)
      self.handle_request(packet, event)


class load_balancer (EventMixin):

  def __init__ (self):
    self.listenTo(core.openflow)

  def _handle_ConnectionUp (self, event):
    log.debug("Connection %s" % event.connection)
    LoadBalancer(event.connection)


def launch ():
  # Start load balancer
  core.registerNew(load_balancer)
