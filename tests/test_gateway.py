import socket
import sqlite3
import threading
import time
from concurrent import futures

import grpc
import pytest

from common import ambiente_pb2 as pb
from common.net import recv_frame, send_frame
from common.rpc import SourceControlStub, add_SourceControlServicer_to_server
from gateway.gateway import Gateway
from simuladores.fonte_virtual import VirtualSource

@pytest.fixture
def gateway(tmp_path):
    g = Gateway('127.0.0.1', str(tmp_path/'telemetria.db'), tcp_port=0)
    yield g
    g.db.close()

def test_serializacao_pb_roundtrip():
    req = pb.DiscoveryRequest(gateway_ip='192.168.0.3', announce_port=50001,
                               telemetry_port=50002)
    assert pb.DiscoveryRequest.FromString(req.SerializeToString()).gateway_ip == '192.168.0.3'
    t = pb.Telemetry(source_id='FONTE_C', sequence=12, temperature_c=31.2,
                     humidity_percent=50.5, alert=True)
    assert pb.Telemetry.FromString(t.SerializeToString()).alert

def test_gateway_registro_udp_e_analiticas(gateway):
    gateway.register(pb.SourceAnnouncement(source_id='FONTE_C', kind='termohigrometro_cont',
                            ip='192.168.0.4', enabled=True, interval_ms=15000), '192.168.0.4')
    for seq, temp in enumerate([20., 30., 40.]):
        gateway.handle_telemetry(pb.Telemetry(source_id='FONTE_C', sequence=seq,
                                              temperature_c=temp, humidity_percent=50+seq),
                                 '192.168.0.4')
    assert gateway.process_request(pb.ClientRequest(operation='list')).sources[0].source_id == 'FONTE_C'
    for op, value in [('avg',30),('min',20),('max',40),('stddev',8.1649658)]:
        resp = gateway.process_request(pb.ClientRequest(operation='aggregate',metric='temperature',aggregate=op))
        assert resp.success and resp.result.samples == 3
        assert resp.result.value == pytest.approx(value, rel=1e-4)
    assert gateway.process_request(pb.ClientRequest(operation='history',limit=2)).readings


def test_tcp_frame_gateway(gateway):
    a,b = socket.socketpair()
    gateway.register(pb.SourceAnnouncement(source_id='FONTE_B',kind='sensor_co2',ip='127.0.0.1'), '127.0.0.1')
    thread = threading.Thread(target=gateway.client_session,args=(a,('localhost',123)),daemon=True)
    thread.start()
    send_frame(b, pb.ClientRequest(operation='list').SerializeToString())
    reply = pb.ClientResponse.FromString(recv_frame(b))
    assert reply.success and reply.sources[0].source_id == 'FONTE_B'
    b.close()
    thread.join(2)


def test_grpc_controle_gateway(gateway):
    src = VirtualSource('FONTE_A','temperature',True,15000,30.,50051,'127.0.0.1')
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    add_SourceControlServicer_to_server(src, server)
    port = server.add_insecure_port('127.0.0.1:0')
    server.start()
    try:
        gateway.register(pb.SourceAnnouncement(source_id='FONTE_A',kind='termohigrometro_ctrl',
                          ip='127.0.0.1',controllable=True, grpc_port=port,
                          grpc_host='127.0.0.1', enabled=True,interval_ms=15000), '127.0.0.1')
        r = gateway.process_request(pb.ClientRequest(operation='control',source_id='FONTE_A',
                                                      command='interval',interval_ms=5000))
        assert r.success, r.message
        assert src.interval == 5000
        with grpc.insecure_channel(f'127.0.0.1:{port}') as channel:
            status = SourceControlStub(channel).GetState(pb.ControlRequest(source_id='FONTE_A'), timeout=2)
            assert status.interval_ms == 5000
    finally:
        server.stop(grace=0).wait()


def test_bridge_grpc_udp_protobuf(tmp_path):
    from fonte_a_bridge.bridge import EspBridge
    stop = threading.Event()
    # Porta aleatoria para mock UDP do firmware; responde em protobuf puro.
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_socket.bind(('127.0.0.1', 0))
    server_socket.settimeout(1)
    node_port = server_socket.getsockname()[1]
    def fake_esp():
        try:
            raw, addr = server_socket.recvfrom(2048)
            req = pb.ControlRequest.FromString(raw)
            assert req.command == 'interval'
            reply = pb.ControlResponse(success=True, message='OK',enabled=True,
                                       interval_ms=req.interval_ms,threshold=30,
                                       request_id=req.request_id)
            server_socket.sendto(reply.SerializeToString(), addr)
        finally:
            stop.set()
            server_socket.close()
    thread = threading.Thread(target=fake_esp, daemon=True)
    thread.start()
    bridge = EspBridge('127.0.0.1', 'FONTE_A', 50051, '127.0.0.1', node_port)
    result = bridge.Configure(pb.ControlRequest(source_id='FONTE_A',
                               command='interval',interval_ms=5000,request_id=123), None)
    assert result.success and result.interval_ms == 5000
    assert stop.wait(2)
    thread.join(2)
