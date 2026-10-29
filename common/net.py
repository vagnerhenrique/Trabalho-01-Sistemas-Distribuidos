"""Parametros e transporte usados por todos os processos."""
import socket
import struct

MCAST_GROUP = '239.255.42.99'
DISCOVERY_PORT = 50000
ANNOUNCE_PORT = 50001
TELEMETRY_PORT = 50002
TCP_PORT = 50010
MAX_FRAME = 1024 * 1024

def bind_udp(port, multicast=False, interface='0.0.0.0'):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if multicast:
        sock.bind(('', port))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP,
                        socket.inet_aton(MCAST_GROUP) + socket.inet_aton(interface))
    else:
        sock.bind(('0.0.0.0', port))
    return sock

def local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(('8.8.8.8', 80))  # apenas detecta a interface; nao envia pacote
        return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())
    finally:
        sock.close()

def recv_exact(sock, n):
    out = bytearray()
    while len(out) < n:
        part = sock.recv(n - len(out))
        if not part:
            raise ConnectionError('Conexao TCP encerrada')
        out.extend(part)
    return bytes(out)

def recv_frame(sock):
    size = struct.unpack('!I', recv_exact(sock, 4))[0]
    if size < 1 or size > MAX_FRAME:
        raise ValueError(f'Tamanho de frame TCP invalido: {size}')
    return recv_exact(sock, size)

def send_frame(sock, data):
    if not data or len(data) > MAX_FRAME:
        raise ValueError('Mensagem Protobuf fora do tamanho permitido')
    sock.sendall(struct.pack('!I', len(data)) + data)
