"""Fonte virtual com dados UDP protobuf, discovery multicast e servidor gRPC opcional.

Exemplos:
  python -m simuladores.fonte_virtual --id FONTE_A --kind temperature --control --grpc-port 50051
  python -m simuladores.fonte_virtual --id FONTE_B --kind co2
  python -m simuladores.fonte_virtual --id FONTE_D --kind noise
"""
import argparse
import logging
import math
import random
import socket
import threading
import time
from concurrent import futures

import grpc
from common import ambiente_pb2 as pb
from common.net import (MCAST_GROUP, DISCOVERY_PORT, ANNOUNCE_PORT, TELEMETRY_PORT,
                        bind_udp, local_ip)
from common.rpc import SourceControlServicer, add_SourceControlServicer_to_server

log = logging.getLogger('fonte')
TYPES = {'temperature': 'termohigrometro_ctrl',
         'co2': 'sensor_co2', 'noise': 'sensor_ruido'}

class VirtualSource(SourceControlServicer):
    def __init__(self, ident, kind, controllable, interval, threshold, grpc_port, advertise_ip):
        self.ident = ident
        self.kind = kind
        self.controlled = controllable
        self.grpc_port = grpc_port
        self.ip = advertise_ip
        self.lock = threading.RLock()
        self.enabled = True
        self.failure = False
        self.interval = interval
        self.threshold = threshold
        self.previous_value = None
        self.gateway_ip = None
        self.gateway_udp_port = TELEMETRY_PORT
        self.gateway_announce_port = ANNOUNCE_PORT
        self.seq = 0
        self.start = time.monotonic()
        self.rng = random.Random(42 + sum(map(ord, ident)))
        self.running = True
        self.grpc_server = None

    def announce(self):
        with self.lock:
            gateway = self.gateway_ip
            if not gateway or self.failure:
                return
            message = pb.SourceAnnouncement(
                source_id=self.ident, kind=TYPES[self.kind], ip=self.ip,
                controllable=self.controlled, grpc_port=self.grpc_port if self.controlled else 0,
                grpc_host=self.ip if self.controlled else '',
                enabled=self.enabled, interval_ms=self.interval,
                threshold=self.threshold, failure=self.failure)
            port = self.gateway_announce_port
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(message.SerializeToString(), (gateway, port))
        finally:
            sock.close()

    def discovery_listener(self):
        sock = bind_udp(DISCOVERY_PORT, multicast=True)
        sock.settimeout(.7)
        try:
            while self.running:
                try:
                    data, sender = sock.recvfrom(2048)
                    request = pb.DiscoveryRequest.FromString(data)
                    if not request.gateway_ip:
                        continue
                    with self.lock:
                        self.gateway_ip = request.gateway_ip
                        self.gateway_udp_port = request.telemetry_port or TELEMETRY_PORT
                        self.gateway_announce_port = request.announce_port or ANNOUNCE_PORT
                    self.announce()
                except socket.timeout:
                    pass
                except Exception as exc:
                    log.warning('Multicast invalido: %s', exc)
        finally:
            sock.close()

    def _reading(self):
        t = time.monotonic() - self.start
        if self.kind == 'temperature':
            temp = 25 + 3 * math.sin(t / 25) + self.rng.uniform(-.4, .4)
            hum = 55 + 10 * math.sin(t / 40) + self.rng.uniform(-.7, .7)
            return temp, hum, '', 0., temp
        if self.kind == 'co2':
            val = 600 + 250 * math.sin(t / 25) + self.rng.uniform(-20,20)
            return 0., 0., 'co2', val, val
        val = 50 + 20 * math.sin(t / 16) + self.rng.uniform(-3, 3)
        return 0., 0., 'noise', val, val

    def telemetry_loop(self):
        next_send = time.monotonic() + 1
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            while self.running:
                with self.lock:
                    enabled = self.enabled and not self.failure
                    gateway = self.gateway_ip
                    interval = self.interval / 1000
                    threshold = self.threshold
                    port = self.gateway_udp_port
                now = time.monotonic()
                if gateway and enabled and now >= next_send:
                    temp, hum, metric, val, sample = self._reading()
                    crossed = (self.previous_value is not None and self.previous_value < threshold <= sample)
                    self.previous_value = sample
                    self.seq += 1
                    message = pb.Telemetry(source_id=self.ident, sequence=self.seq,
                                           temperature_c=temp, humidity_percent=hum,
                                           uptime_ms=int((now-self.start)*1000),
                                           alert=bool(crossed), metric=metric, metric_value=val)
                    sock.sendto(message.SerializeToString(), (gateway, port))
                    log.info('%s seq=%d leitura=%.2f alerta=%s', self.ident, self.seq, sample, crossed)
                    next_send = now + max(2, interval)
                if not enabled:
                    next_send = now + max(2, interval)
                time.sleep(.1)
        finally:
            sock.close()

    def event_loop(self):
        while self.running:
            self.announce()
            time.sleep(10)

    def _response(self, request, ok, message):
        with self.lock:
            return pb.ControlResponse(success=ok, message=message,
                                      enabled=self.enabled, interval_ms=self.interval,
                                      threshold=self.threshold, failure=self.failure,
                                      request_id=request.request_id)

    def Configure(self, request, context):
        if not self.controlled:
            return self._response(request, False, 'Fonte nao controlavel')
        if request.source_id and request.source_id != self.ident:
            return self._response(request, False, 'Identificador incorreto')
        with self.lock:
            if request.command == 'enabled':
                self.enabled = request.enabled
            elif request.command == 'interval':
                if not (2000 <= request.interval_ms <= 3600000):
                    return self._response(request, False, 'Intervalo valido: 2000..3600000 ms')
                self.interval = request.interval_ms
            elif request.command == 'threshold':
                self.threshold = request.threshold
            elif request.command == 'failure':
                self.failure = request.failure
            else:
                return self._response(request, False, 'Comando invalido')
        self.announce()
        return self._response(request, True, 'Configuracao aplicada na fonte virtual')

    def GetState(self, request, context):
        return self._response(request, True, 'Estado atual')

    def serve(self):
        if self.controlled:
            self.grpc_server = grpc.server(futures.ThreadPoolExecutor(max_workers=4))
            add_SourceControlServicer_to_server(self, self.grpc_server)
            self.grpc_server.add_insecure_port(f'0.0.0.0:{self.grpc_port}')
            self.grpc_server.start()
            log.info('gRPC: %s:%d', self.ip, self.grpc_port)
        threading.Thread(target=self.discovery_listener, daemon=True).start()
        threading.Thread(target=self.telemetry_loop, daemon=True).start()
        threading.Thread(target=self.event_loop, daemon=True).start()
        log.info('%s pronta. Aguardando descoberta multicast.', self.ident)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.running = False
            if self.grpc_server:
                self.grpc_server.stop(grace=1)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--id', required=True)
    parser.add_argument('--kind', choices=TYPES, required=True)
    parser.add_argument('--control', action='store_true')
    parser.add_argument('--grpc-port', type=int, default=50051)
    parser.add_argument('--interval', type=int, default=15000)
    parser.add_argument('--threshold', type=float, default=28.0)
    parser.add_argument('--advertise-ip', default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', datefmt='%H:%M:%S')
    VirtualSource(args.id, args.kind, args.control, args.interval,
                  args.threshold, args.grpc_port, args.advertise_ip or local_ip()).serve()
