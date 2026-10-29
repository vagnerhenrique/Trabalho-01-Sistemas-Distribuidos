"""Bridge: recebe comando gRPC real e encaminha Protobuf em UDP ao ESP8266.

Nao confundir com gRPC nativo no microcontrolador. Atende a integracao fisica sem
HTTP/2 no ESP8266; precisa ser explicitado como adaptacao arquitetural.
"""
import argparse
import logging
import socket
import threading
import time
from concurrent import futures

import grpc
from common import ambiente_pb2 as pb
from common.net import (DISCOVERY_PORT, ANNOUNCE_PORT, MCAST_GROUP,
                        bind_udp, local_ip)
from common.rpc import SourceControlServicer, add_SourceControlServicer_to_server

log = logging.getLogger('bridge')

class EspBridge(SourceControlServicer):
    def __init__(self, node_ip, source_id, grpc_port, advertise_ip, node_control_port=50031, gateway_ip=None):
        self.node_ip = node_ip
        self.source_id = source_id
        self.grpc_port = grpc_port
        self.ip = advertise_ip
        self.node_control_port = node_control_port
        self.gateway_ip = gateway_ip
        self.announcement_port = ANNOUNCE_PORT
        self.lock = threading.Lock()
        self.enabled = True
        self.interval = 15000
        self.threshold = 30
        self.failure = False

    def announce(self):
        if not self.gateway_ip:
            return
        msg = pb.SourceAnnouncement(source_id=self.source_id,
                                    kind='termohigrometro_ctrl', ip=self.node_ip,
                                    controllable=True, grpc_port=self.grpc_port,
                                    grpc_host=self.ip, enabled=self.enabled,
                                    interval_ms=self.interval, failure=self.failure,
                                    threshold=self.threshold)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.sendto(msg.SerializeToString(), (self.gateway_ip, self.announcement_port))

    def multicast_listener(self):
        sock = bind_udp(DISCOVERY_PORT, multicast=True)
        sock.settimeout(1)
        while True:
            try:
                data, remote = sock.recvfrom(2048)
                req = pb.DiscoveryRequest.FromString(data)
                if not req.gateway_ip:
                    continue
                self.gateway_ip = req.gateway_ip
                self.announcement_port = req.announce_port or ANNOUNCE_PORT
                self.announce()
            except socket.timeout:
                pass
            except Exception as exc:
                log.warning('Descoberta bridge: %s', exc)

    def announce_loop(self):
        while True:
            self.announce()
            time.sleep(10)

    def _send_udp(self, request):
        with self.lock:  # serializa acesso ao socket por multiplos clientes gRPC
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.settimeout(1.5)
                for attempt in range(3):
                    sock.sendto(request.SerializeToString(),
                                (self.node_ip, self.node_control_port))
                    try:
                        data, _ = sock.recvfrom(2048)
                        reply = pb.ControlResponse.FromString(data)
                        if reply.request_id != request.request_id:
                            continue
                        self.enabled, self.interval = reply.enabled, reply.interval_ms
                        self.threshold, self.failure = reply.threshold, reply.failure
                        self.announce()
                        return reply
                    except socket.timeout:
                        log.warning('Sem ACK do ESP: tentativa %d/3', attempt+1)
        return pb.ControlResponse(success=False, message='ESP nao respondeu ao controle UDP',
                                  request_id=request.request_id)

    def Configure(self, request, context):
        if request.source_id != self.source_id:
            return pb.ControlResponse(success=False, message='Fonte desconhecida',
                                      request_id=request.request_id)
        return self._send_udp(request)

    def GetState(self, request, context):
        check = pb.ControlRequest(source_id=self.source_id, command='status',
                                  request_id=request.request_id or int(time.time()) & 0xffffffff)
        return self._send_udp(check)

    def serve(self):
        server = grpc.server(futures.ThreadPoolExecutor(max_workers=8))
        add_SourceControlServicer_to_server(self, server)
        bound = server.add_insecure_port(f'0.0.0.0:{self.grpc_port}')
        if not bound:
            raise RuntimeError(f'Nao foi possivel abrir porta gRPC {self.grpc_port}')
        server.start()
        threading.Thread(target=self.multicast_listener, daemon=True).start()
        threading.Thread(target=self.announce_loop, daemon=True).start()
        log.info('Bridge Fonte A: gRPC=%s:%d => UDP=%s:%d',
                 self.ip, self.grpc_port, self.node_ip, self.node_control_port)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            server.stop(grace=1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--node-ip', required=True,
                        help='IP atual da NodeMCU exibido no Monitor Serial')
    parser.add_argument('--source-id', default='FONTE_A')
    parser.add_argument('--grpc-port', type=int, default=50051)
    parser.add_argument('--gateway-ip', default=None, help='IP do Gateway para anuncio direto (recomendado quando o bridge roda no mesmo PC)')
    parser.add_argument('--advertise-ip', default=None, help='IP LAN do PC (para descoberta)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    EspBridge(args.node_ip, args.source_id, args.grpc_port,
              args.advertise_ip or local_ip(), gateway_ip=args.gateway_ip).serve()
