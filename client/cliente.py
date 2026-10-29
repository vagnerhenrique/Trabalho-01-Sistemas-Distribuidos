"""Cliente TCP/Protocol Buffers (sem frameworks HTTP)."""
import argparse
import socket
import shlex
from datetime import datetime

from common import ambiente_pb2 as pb
from common.net import TCP_PORT, recv_frame, send_frame

HELP = '''Comandos:
  list
  avg temperature 3600 [FONTE_C]
  min humidity 3600 [FONTE_C]
  max co2 3600 [FONTE_B]
  stddev temperature 86400 [FONTE_C]
  history [temperature|humidity|co2|noise] [FONTE_C] [limite]
  on FONTE_A / off FONTE_A
  interval FONTE_A 5000
  threshold FONTE_A 30
  failure FONTE_A on / failure FONTE_A off
  help / exit
'''

def build_request(args):
    if not args:
        return None
    cmd = args[0].lower()
    if cmd == 'list':
        return pb.ClientRequest(operation='list')
    if cmd in ('avg', 'min', 'max', 'stddev'):
        if len(args) < 2:
            raise ValueError('Uso: avg|min|max|stddev metric [segundos] [fonte]')
        return pb.ClientRequest(operation='aggregate', aggregate=cmd, metric=args[1],
                                window_seconds=int(args[2]) if len(args)>2 else 3600,
                                source_id=args[3] if len(args)>3 else '')
    if cmd == 'history':
        return pb.ClientRequest(operation='history', metric=args[1] if len(args)>1 else '',
                                source_id=args[2] if len(args)>2 else '',
                                limit=int(args[3]) if len(args)>3 else 20)
    if cmd in ('on', 'off'):
        return pb.ClientRequest(operation='control', source_id=args[1],
                                command='enabled', enabled=(cmd=='on'))
    if cmd == 'interval':
        return pb.ClientRequest(operation='control', source_id=args[1],
                                command='interval', interval_ms=int(args[2]))
    if cmd == 'threshold':
        return pb.ClientRequest(operation='control', source_id=args[1],
                                command='threshold', threshold=float(args[2]))
    if cmd == 'failure':
        return pb.ClientRequest(operation='control', source_id=args[1],
                                command='failure', failure=args[2].lower() == 'on')
    raise ValueError('Comando desconhecido; digite help')

def present(reply):
    if not reply.success:
        print('ERRO:', reply.message)
        return
    if reply.sources:
        print(f'{"ID":12} {"TIPO":20} {"ESTADO":10} {"IP":16} {"gRPC":22} {"T(°C)":>7} {"UR(%)":>7}')
        for s in reply.sources:
            print(f'{s.source_id:12} {s.kind[:20]:20} {s.state:10} {s.ip:16} '
                  f'{(s.grpc_host+":"+str(s.grpc_port) if s.grpc_port else "-"):22} '
                  f'{s.last_temperature_c:7.1f} {s.last_humidity_percent:7.1f}')
    elif reply.HasField('result'):
        r = reply.result
        print(f'{r.aggregate}({r.metric})={r.value:.3f} | amostras={r.samples} | fonte={r.source_id or "todas"}')
    elif reply.readings:
        for r in reply.readings:
            print(f'{datetime.fromtimestamp(r.timestamp):%Y-%m-%d %H:%M:%S} '
                  f'{r.source_id:10} {r.metric:12} {r.value:8.2f} alerta={r.alert}')
    else:
        print(reply.message)

def request_once(host, port, request):
    with socket.create_connection((host, port), timeout=6) as sock:
        sock.settimeout(7)
        send_frame(sock, request.SerializeToString())
        return pb.ClientResponse.FromString(recv_frame(sock))

def main():
    parser = argparse.ArgumentParser(description='Cliente TCP com protobuf')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=TCP_PORT)
    parser.add_argument('--command', nargs='+', help='Opcional: comando nao interativo; ex.: --command list')
    args = parser.parse_args()
    print(f'Cliente TCP conectado a {args.host}:{args.port}')
    if not args.command:
        print(HELP)
    while True:
        try:
            tokens = args.command or shlex.split(input('cliente> ').strip())
            if not tokens:
                if args.command:
                    return
                continue
            if tokens[0] in ('exit', 'quit', 'sair'):
                return
            if tokens[0] == 'help':
                print(HELP)
            else:
                req = build_request(tokens)
                present(request_once(args.host, args.port, req))
        except (ValueError, IndexError) as exc:
            print('Uso incorreto:', exc)
        except (OSError, ConnectionError) as exc:
            print('Gateway indisponivel:', exc)
        if args.command:
            return

if __name__ == '__main__':
    main()
