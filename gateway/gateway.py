"""Gateway de ambiente inteligente: discovery UDP multicast, UDP PB, TCP PB, gRPC, SQLite."""
import argparse
import logging
import math
import socket
import sqlite3
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import grpc
from common import ambiente_pb2 as pb
from common.net import (MCAST_GROUP, DISCOVERY_PORT, ANNOUNCE_PORT, TELEMETRY_PORT,
                        TCP_PORT, bind_udp, local_ip, recv_frame, send_frame)
from common.rpc import SourceControlStub

log = logging.getLogger('gateway')

class Gateway:
    def __init__(self, advertise_ip, db_path, multicast_interface='0.0.0.0',
                 tcp_port=TCP_PORT, telemetry_port=TELEMETRY_PORT,
                 announce_port=ANNOUNCE_PORT):
        self.ip = advertise_ip
        self.tcp_port = tcp_port
        self.telemetry_port = telemetry_port
        self.announce_port = announce_port
        self.mcast_interface = multicast_interface
        self.sources = {}
        self._discovery_count = 0
        self.lock = threading.RLock()
        self.running = threading.Event()
        self.running.set()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.execute('''CREATE TABLE IF NOT EXISTS readings(
            timestamp REAL NOT NULL, source_id TEXT NOT NULL,
            metric TEXT NOT NULL, value REAL NOT NULL, alert INTEGER NOT NULL DEFAULT 0)''')
        self.db.execute('CREATE INDEX IF NOT EXISTS idx_metric_ts ON readings(metric,timestamp)')
        self.db.commit()

    def register(self, msg, sender_ip):
        if not msg.source_id or not msg.kind:
            return
        now = time.time()
        with self.lock:
            is_new = msg.source_id not in self.sources
            source = self.sources.setdefault(msg.source_id, {
                'id': msg.source_id, 'kind': msg.kind, 'ip': sender_ip,
                'grpc_host': '', 'grpc_port': 0, 'controllable': False,
                'enabled': True, 'interval_ms': 15000, 'failure': False,
                'first_seen': now, 'last_seen': now, 'last_data': 0, 'temperature': 0.0, 'humidity': 0.0})
            old_state = (source['kind'], source['ip'], source['grpc_host'],
                         source['grpc_port'], source['enabled'], source['failure'],
                         source['interval_ms'])
            source['kind'] = msg.kind
            # O anunciante pode ser um proxy gRPC; seu campo ip e o IP do ESP.
            source['ip'] = msg.ip or sender_ip
            source['last_seen'] = now
            if msg.grpc_port and msg.grpc_host:
                source['grpc_host'] = msg.grpc_host
                source['grpc_port'] = msg.grpc_port
            source['controllable'] = source['controllable'] or msg.controllable
            # Uma reanunciacao do MCU pode sobrescrever o estado do proxy com valor novo.
            source['enabled'] = msg.enabled
            source['failure'] = msg.failure
            if msg.interval_ms:
                source['interval_ms'] = msg.interval_ms
            new_state = (source['kind'], source['ip'], source['grpc_host'],
                         source['grpc_port'], source['enabled'], source['failure'],
                         source['interval_ms'])
            endpoint = f"{source['grpc_host']}:{source['grpc_port']}" if source['grpc_port'] else '-'
        if is_new or new_state != old_state:
            log.info('Fonte %s: %-10s tipo=%s IP=%s gRPC=%s intervalo=%dms enabled=%s falha=%s',
                     'descoberta' if is_new else 'atualizada', msg.source_id,
                     new_state[0], new_state[1], endpoint, new_state[6],
                     new_state[4], new_state[5])

    def handle_telemetry(self, msg, sender_ip):
        if not msg.source_id:
            return
        now = time.time()
        with self.lock:
            src = self.sources.setdefault(msg.source_id, {
                'id': msg.source_id, 'kind': 'desconhecido', 'ip': sender_ip,
                'grpc_host': '', 'grpc_port': 0, 'controllable': False,
                'enabled': True, 'interval_ms': 15000, 'failure': False,
                'first_seen': now, 'last_seen': now, 'last_data': 0, 'temperature': 0., 'humidity': 0.})
            src['last_seen'] = now
            src['last_data'] = now
            src['temperature'] = msg.temperature_c
            src['humidity'] = msg.humidity_percent
        if msg.metric:
            values = [(msg.metric, msg.metric_value)]
        else:
            values = [('temperature', msg.temperature_c), ('humidity', msg.humidity_percent)]
        with self.lock:
            self.db.executemany('INSERT INTO readings(timestamp,source_id,metric,value,alert) VALUES(?,?,?,?,?)',
                                [(now, msg.source_id, kind, val, int(msg.alert))
                                 for kind, val in values if math.isfinite(val)])
            self.db.commit()
        log.info('UDP %-10s seq=%d %s alerta=%s', msg.source_id, msg.sequence,
                 ' '.join(f'{m}={v:.1f}' for m, v in values), bool(msg.alert))

    def do_discovery(self):
        request = pb.DiscoveryRequest(gateway_ip=self.ip,
                                       announce_port=self.announce_port,
                                       telemetry_port=self.telemetry_port)
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
        # Em PC com Ethernet, Wi-Fi, VPN/Hyper-V, direciona multicast pela LAN certa.
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF,
                        socket.inet_aton(self.mcast_interface if self.mcast_interface != '0.0.0.0' else self.ip))
        try:
            while self.running.is_set():
                sock.sendto(request.SerializeToString(), (MCAST_GROUP, DISCOVERY_PORT))
                self._discovery_count += 1
                if self._discovery_count == 1 or self._discovery_count % 12 == 0:
                    log.info('Multicast ativo: WHO_IS_THERE -> %s:%d (a cada 5s, #%d)',
                             MCAST_GROUP, DISCOVERY_PORT, self._discovery_count)
                for _ in range(50):
                    if not self.running.is_set():
                        break
                    time.sleep(.1)
        finally:
            sock.close()

    def periodic_summary(self):
        while self.running.is_set():
            time.sleep(60)
            if not self.running.is_set():
                break
            with self.lock:
                states = [self.source_info(src) for src in self.sources.values()]
            if not states:
                log.info('Resumo: 0 fontes descobertas')
            else:
                description = ', '.join(f'{s.source_id}={s.state}' for s in sorted(states, key=lambda x: x.source_id))
                log.info('Resumo: %d fonte(s) | %s', len(states), description)

    def listen_announcements(self):
        sock = bind_udp(self.announce_port)
        sock.settimeout(1)
        try:
            while self.running.is_set():
                try:
                    raw, addr = sock.recvfrom(4096)
                    msg = pb.SourceAnnouncement()
                    msg.ParseFromString(raw)
                    self.register(msg, addr[0])
                except socket.timeout:
                    pass
                except Exception as exc:
                    log.warning('Anuncio invalido: %s', exc)
        finally:
            sock.close()

    def listen_telemetry(self):
        sock = bind_udp(self.telemetry_port)
        sock.settimeout(1)
        try:
            while self.running.is_set():
                try:
                    raw, addr = sock.recvfrom(4096)
                    msg = pb.Telemetry()
                    msg.ParseFromString(raw)
                    self.handle_telemetry(msg, addr[0])
                except socket.timeout:
                    pass
                except Exception as exc:
                    log.warning('Telemetria invalida: %s', exc)
        finally:
            sock.close()

    def source_info(self, source):
        now = time.time()
        age_announcement = now - source['last_seen']
        age_data = now - (source['last_data'] or source['first_seen'])
        stale_data = source['enabled'] and age_data > max(45, 3 * source['interval_ms'] / 1000.)
        # Uma fonte desativada ou em falha simulada nao deve ser OFFLINE
        # apenas porque deixou de transmitir telemetria; basta anunciar vida.
        state = ('OFFLINE' if age_announcement > 45 else
                 'FAILURE' if source['failure'] else
                 'DISABLED' if not source['enabled'] else
                 'OFFLINE' if stale_data else 'ONLINE')
        return pb.SourceInfo(source_id=source['id'], kind=source['kind'],
                             ip=source['ip'], controllable=source['controllable'],
                             enabled=source['enabled'], interval_ms=source['interval_ms'],
                             state=state, last_seen_unix=int(source['last_seen']),
                             last_temperature_c=source['temperature'],
                             last_humidity_percent=source['humidity'],
                             grpc_host=source['grpc_host'], grpc_port=source['grpc_port'])

    def aggregate(self, request):
        metric = request.metric or 'temperature'
        op = request.aggregate or 'avg'
        if op not in ('avg', 'min', 'max', 'stddev'):
            return pb.ClientResponse(success=False, message='Agregacao invalida: avg|min|max|stddev')
        seconds = min(request.window_seconds or 3600, 30 * 24 * 3600)
        cutoff = time.time() - seconds
        query = 'SELECT value FROM readings WHERE metric=? AND timestamp>=?'
        params = [metric, cutoff]
        if request.source_id:
            query += ' AND source_id=?'
            params.append(request.source_id)
        with self.lock:
            vals = [r[0] for r in self.db.execute(query, params).fetchall()]
        if not vals:
            return pb.ClientResponse(success=False, message='Nenhuma amostra no periodo solicitado')
        result = {'avg': lambda x: statistics.mean(x),
                  'min': min, 'max': max,
                  'stddev': lambda x: statistics.pstdev(x)}[op](vals)
        return pb.ClientResponse(success=True,
                                 result=pb.AggregateResult(metric=metric, aggregate=op,
                                                           value=result, samples=len(vals),
                                                           source_id=request.source_id))

    def history(self, request):
        n = min(request.limit or 20, 200)
        sql = 'SELECT timestamp,source_id,metric,value,alert FROM readings WHERE 1=1'
        params = []
        if request.metric:
            sql += ' AND metric=?'
            params.append(request.metric)
        if request.source_id:
            sql += ' AND source_id=?'
            params.append(request.source_id)
        sql += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(n)
        with self.lock:
            rows = self.db.execute(sql, params).fetchall()
        resp = pb.ClientResponse(success=True, message=f'{len(rows)} registros')
        for timestamp, source_id, metric, value, alert in rows:
            resp.readings.add(timestamp=int(timestamp), source_id=source_id,
                              metric=metric, value=value, alert=bool(alert))
        return resp

    def control(self, request):
        with self.lock:
            source = self.sources.get(request.source_id)
            source = dict(source) if source else None
        if not source:
            return pb.ClientResponse(success=False, message='Fonte nao descoberta')
        if not source['controllable'] or not source['grpc_host'] or not source['grpc_port']:
            return pb.ClientResponse(success=False, message='Fonte sem endpoint gRPC descoberto')
        if request.command not in ('enabled', 'interval', 'threshold', 'failure'):
            return pb.ClientResponse(success=False, message='Comando desconhecido')
        command = pb.ControlRequest(source_id=request.source_id, command=request.command,
                                    enabled=request.enabled, interval_ms=request.interval_ms,
                                    threshold=request.threshold, failure=request.failure,
                                    request_id=int(time.monotonic()*1000) & 0xffffffff)
        target = f"{source['grpc_host']}:{source['grpc_port']}"
        try:
            with grpc.insecure_channel(target) as channel:
                reply = SourceControlStub(channel).Configure(command, timeout=4)
            with self.lock:
                src = self.sources.get(request.source_id)
                if src and reply.success:
                    src['enabled'] = reply.enabled
                    src['interval_ms'] = reply.interval_ms
                    src['failure'] = reply.failure
            return pb.ClientResponse(success=reply.success, message=f'{target}: {reply.message}')
        except grpc.RpcError as exc:
            return pb.ClientResponse(success=False, message=f'Falha gRPC {target}: {exc.code().name}')

    def process_request(self, request):
        if request.operation == 'list':
            reply = pb.ClientResponse(success=True, message='Fontes registradas')
            with self.lock:
                for source in sorted(self.sources.values(), key=lambda x: x['id']):
                    reply.sources.append(self.source_info(source))
            return reply
        if request.operation == 'aggregate':
            return self.aggregate(request)
        if request.operation == 'history':
            return self.history(request)
        if request.operation == 'control':
            return self.control(request)
        return pb.ClientResponse(success=False, message='Operacao invalida: list/control/aggregate/history')

    def client_session(self, conn, addr):
        with conn:
            conn.settimeout(10)
            try:
                while self.running.is_set():
                    try:
                        raw = recv_frame(conn)
                    except ConnectionError:
                        return
                    request = pb.ClientRequest.FromString(raw)
                    reply = self.process_request(request)
                    send_frame(conn, reply.SerializeToString())
            except (ConnectionError, OSError, ValueError) as exc:
                log.info('Cliente %s desconectou: %s', addr[0], exc)

    def listen_tcp(self):
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('0.0.0.0', self.tcp_port))
        server.listen(16)
        server.settimeout(1)
        log.info('Cliente TCP protobuf na porta %d', self.tcp_port)
        with ThreadPoolExecutor(max_workers=16) as pool:
            try:
                while self.running.is_set():
                    try:
                        conn, addr = server.accept()
                        pool.submit(self.client_session, conn, addr)
                    except socket.timeout:
                        pass
            finally:
                server.close()

    def serve(self):
        threads = [threading.Thread(target=fn, daemon=True) for fn in
                   (self.listen_announcements, self.listen_telemetry, self.do_discovery, self.periodic_summary)]
        for thread in threads:
            thread.start()
        log.info('Gateway IP anunciado=%s, telemetria UDP=%d, anuncios=%d',
                 self.ip, self.telemetry_port, self.announce_port)
        try:
            self.listen_tcp()
        except KeyboardInterrupt:
            pass
        finally:
            self.running.clear()
            self.db.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Gateway central do Trabalho 01')
    parser.add_argument('--advertise-ip', default=None, help='IP LAN do computador onde roda Gateway')
    parser.add_argument('--db', default='dados/telemetria.sqlite3')
    parser.add_argument('--multicast-interface', default=None, help='IP da interface para enviar multicast (padrao: advertise-ip)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(message)s', datefmt='%H:%M:%S')
    Gateway(args.advertise_ip or local_ip(), args.db, multicast_interface=args.multicast_interface or args.advertise_ip or local_ip()).serve()
