import json
import threading
import time
from concurrent import futures
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import socket

import grpc
import pytest

from client.gui import build_control, handler_factory
from common import ambiente_pb2 as pb
from common.rpc import add_SourceControlServicer_to_server
from gateway.gateway import Gateway
from simuladores.fonte_virtual import VirtualSource


def port_free():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


@pytest.fixture
def stack(tmp_path):
    gateway_port = port_free()
    g = Gateway('127.0.0.1', str(tmp_path/'test.db'), tcp_port=gateway_port)
    gateway_thread = threading.Thread(target=g.listen_tcp, daemon=True)
    gateway_thread.start()
    grpc_serv = grpc.server(futures.ThreadPoolExecutor(max_workers=2))
    source = VirtualSource('FONTE_A', 'temperature', True, 15000, 30., 50051, '127.0.0.1')
    add_SourceControlServicer_to_server(source, grpc_serv)
    grpc_port = grpc_serv.add_insecure_port('127.0.0.1:0')
    grpc_serv.start()
    g.register(pb.SourceAnnouncement(source_id='FONTE_A',kind='termohigrometro_ctrl', ip='127.0.0.1',
              controllable=True,grpc_host='127.0.0.1',grpc_port=grpc_port,enabled=True,interval_ms=15000), '127.0.0.1')
    for i in range(4):
        g.handle_telemetry(pb.Telemetry(source_id='FONTE_A',sequence=i,temperature_c=25+i,humidity_percent=44+i),'127.0.0.1')
    http=ThreadingHTTPServer(('127.0.0.1',0),handler_factory('127.0.0.1',gateway_port))
    thread=threading.Thread(target=http.serve_forever,daemon=True)
    thread.start()
    root=f'http://127.0.0.1:{http.server_port}'
    try:
        yield root,source,g
    finally:
        http.shutdown();http.server_close();thread.join(timeout=2)
        grpc_serv.stop(0).wait()
        g.running.clear();gateway_thread.join(timeout=2);g.db.close()


def get(root,route):
    with urlopen(root+route,timeout=3) as resp:
        return json.load(resp)


def test_dashboard_assets(stack):
    root,_,_=stack
    with urlopen(root+'/',timeout=3) as resp:
        page=resp.read().decode('utf-8')
        assert 'Controle remoto' in page and 'history-canvas' in page
    for path in ('/dashboard.js','/dashboard.css'):
        with urlopen(root+path,timeout=3) as resp:
            assert len(resp.read()) > 2000


def test_dashboard_api_sources_analytics_history(stack):
    root,_,_=stack
    sources=get(root,'/api/sources')['sources']
    assert sources[0]['id']=='FONTE_A'
    assert sources[0]['control_available']
    assert sources[0]['temperature']==28
    result=get(root,'/api/aggregate?metric=temperature&operation=avg&seconds=3600&source_id=FONTE_A')
    assert result['aggregate']['samples']==4
    assert result['aggregate']['value']==26.5
    records=get(root,'/api/history?source_id=FONTE_A&metric=humidity&limit=3')
    assert len(records['readings'])==3


def test_dashboard_controle_grpc_end_to_end(stack):
    root,source,g=stack
    payload=json.dumps({'source_id':'FONTE_A','command':'interval','value':5000}).encode()
    request=Request(root+'/api/control',payload,headers={'Content-Type':'application/json'},method='POST')
    with urlopen(request,timeout=4) as resp:
        reply=json.load(resp)
    assert reply['success'], reply
    assert source.interval==5000
    assert get(root,'/api/sources')['sources'][0]['interval_ms']==5000


def test_gateway_retains_grpc_from_bridge_after_firmware_announcement(stack):
    root,source,g=stack
    # NodeMCU reanuncia sem campos grpc; Gateway nao pode perder endpoint do bridge.
    g.register(pb.SourceAnnouncement(source_id='FONTE_A',kind='termohigrometro_ctrl',ip='127.0.0.1',
               controllable=True,enabled=True,interval_ms=15000),'127.0.0.1')
    assert get(root,'/api/sources')['sources'][0]['control_available']


def test_dashboard_rejects_invalid_control(stack):
    root,_,_=stack
    payload=json.dumps({'source_id':'FONTE_A','command':'interval','value':100}).encode()
    req=Request(root+'/api/control',payload,headers={'Content-Type':'application/json'},method='POST')
    with pytest.raises(HTTPError) as error:
        urlopen(req,timeout=3)
    assert error.value.code==400


def test_control_requires_boolean():
    with pytest.raises(ValueError):
        build_control({'source_id':'FONTE_A','command':'enabled','value':'false'})
