"""Painel web local do Cliente TCP/Protocol Buffers.

Browser -> HTTP loopback -> este processo -> socket TCP + Protobuf -> Gateway.
Nao modifica o protocolo TCP exigido pela especificacao.
"""
import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from common import ambiente_pb2 as pb
from common.net import TCP_PORT
from client.cliente import request_once

PAGE = Path(__file__).with_name('dashboard.html')
METRICS = {'temperature', 'humidity', 'co2', 'noise'}
OPS = {'avg', 'min', 'max', 'stddev'}
CONTROLS = {'enabled', 'interval', 'threshold', 'failure'}


def translate_reply(response):
    result = {'success': response.success, 'message': response.message}
    if response.sources:
        result['sources'] = [
            dict(id=s.source_id, kind=s.kind, ip=s.ip, status=s.state,
                 controllable=s.controllable, enabled=s.enabled,
                 interval_ms=s.interval_ms, last_seen=s.last_seen_unix,
                 temperature=s.last_temperature_c, humidity=s.last_humidity_percent,
                 grpc_host=s.grpc_host, grpc_port=s.grpc_port,
                 control_available=bool(s.controllable and s.grpc_host and s.grpc_port))
            for s in response.sources]
    if response.HasField('result'):
        r = response.result
        result['aggregate'] = dict(metric=r.metric, operation=r.aggregate,
                                   value=r.value, samples=r.samples, source=r.source_id)
    if response.readings:
        result['readings'] = [dict(timestamp=r.timestamp, source=r.source_id,
                                   metric=r.metric, value=r.value, alert=r.alert)
                              for r in response.readings]
    return result


def parse_number(raw, field, integer=False, minimum=None, maximum=None):
    try:
        value = int(raw) if integer else float(raw)
    except (ValueError, TypeError):
        raise ValueError(f'{field} deve ser numero valido') from None
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ValueError(f'{field} deve estar entre {minimum} e {maximum}')
    if not integer and (value != value or abs(value) == float('inf')):
        raise ValueError(f'{field} deve ser finito')
    return value


def build_get_request(route, query):
    def arg(name, default=''):
        return query.get(name, [default])[0]

    source = arg('source_id')[:80]
    if route == '/api/sources':
        return pb.ClientRequest(operation='list')
    if route == '/api/history':
        metric = arg('metric')
        if metric and metric not in METRICS:
            raise ValueError('Metrica invalida')
        return pb.ClientRequest(operation='history', source_id=source,
                                metric=metric,
                                limit=parse_number(arg('limit', '80'), 'limite', True, 1, 200))
    if route == '/api/aggregate':
        metric, operation = arg('metric'), arg('operation', 'avg')
        if metric not in METRICS or operation not in OPS:
            raise ValueError('Metrica ou agregacao invalida')
        return pb.ClientRequest(operation='aggregate', source_id=source,
                                metric=metric, aggregate=operation,
                                window_seconds=parse_number(arg('seconds', '3600'), 'segundos', True, 1, 2592000))
    return None


def build_control(data):
    source = data.get('source_id', '')
    cmd = data.get('command', '')
    if not isinstance(source, str) or not 1 <= len(source) <= 80 or not source.replace('_', '').replace('-', '').isalnum():
        raise ValueError('Identificador de fonte invalido')
    if cmd not in CONTROLS:
        raise ValueError('Comando invalido')
    request = pb.ClientRequest(operation='control', source_id=source, command=cmd)
    if cmd in ('enabled', 'failure'):
        value = data.get('value')
        if not isinstance(value, bool):
            raise ValueError('O valor deve ser true/false')
        setattr(request, cmd, value)
    elif cmd == 'interval':
        request.interval_ms = parse_number(data.get('value'), 'intervalo', True, 2000, 3600000)
    elif cmd == 'threshold':
        request.threshold = parse_number(data.get('value'), 'limiar', False, -40, 80)
    return request


def handler_factory(gateway_host, gateway_port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            logging.getLogger('painel').info('%s - %s', self.address_string(), fmt % args)

        def send_json(self, data, status=200):
            raw = json.dumps(data, ensure_ascii=False, allow_nan=False).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def exchange(self, request):
            return translate_reply(request_once(gateway_host, gateway_port, request))

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path in ('/', '/dashboard.html'):
                page = PAGE.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; img-src 'self' data:")
                self.send_header('Content-Length', str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            if parsed.path == '/dashboard.css':
                self.send_asset('dashboard.css', 'text/css; charset=utf-8')
                return
            if parsed.path == '/dashboard.js':
                self.send_asset('dashboard.js', 'application/javascript; charset=utf-8')
                return
            try:
                req = build_get_request(parsed.path, parse_qs(parsed.query))
                if req is None:
                    self.send_json({'success': False, 'message': 'Nao encontrado'}, 404)
                else:
                    self.send_json(self.exchange(req))
            except ValueError as exc:
                self.send_json({'success': False, 'message': str(exc)}, 400)
            except (ConnectionError, OSError) as exc:
                self.send_json({'success': False, 'message': f'Gateway indisponivel: {exc}'}, 503)

        def send_asset(self, name, mime):
            raw = Path(__file__).with_name(name).read_bytes()
            self.send_response(200)
            self.send_header('Content-Type', mime)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            if self.path != '/api/control':
                return self.send_json({'success': False, 'message': 'Nao encontrado'}, 404)
            if self.headers.get('Content-Type', '').split(';')[0].strip() != 'application/json':
                return self.send_json({'success': False, 'message': 'Use application/json'}, 415)
            if not self.headers.get('Origin', '') in ('', f'http://{self.headers.get("Host", "")}'):
                return self.send_json({'success': False, 'message': 'Origem nao permitida'}, 403)
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 1 <= size <= 4096:
                    raise ValueError('Tamanho de corpo invalido')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError('Objeto JSON esperado')
                self.send_json(self.exchange(build_control(body)))
            except (ValueError, json.JSONDecodeError) as exc:
                self.send_json({'success': False, 'message': str(exc)}, 400)
            except (ConnectionError, OSError) as exc:
                self.send_json({'success': False, 'message': f'Gateway indisponivel: {exc}'}, 503)
    return Handler


def main():
    parser = argparse.ArgumentParser(description='Painel Web local do Cliente TCP + Protobuf')
    parser.add_argument('--host', default='127.0.0.1', help='IP do Gateway')
    parser.add_argument('--port', type=int, default=TCP_PORT, help='Porta TCP do Gateway')
    parser.add_argument('--web-port', type=int, default=8080, help='Porta HTTP local do painel')
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format='%(asctime)s %(message)s')
    server = ThreadingHTTPServer(('127.0.0.1', args.web_port), handler_factory(args.host, args.port))
    print(f'Painel aberto em http://127.0.0.1:{args.web_port}')
    print(f'Gateway via TCP/Protobuf: {args.host}:{args.port}')
    print('Abra o link no navegador. Ctrl+C encerra o painel.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
