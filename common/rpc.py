"""Bindings gRPC com contratos do ambiente.proto (grpcio); compativeis com stubs protoc.

O _pb2.py e gerado por protoc. Este arquivo e a adaptacao minima equivalente ao
_pb2_grpc.py (o gerador do plugin grpcio-tools nao esta exigido na execucao).
"""
import grpc
from common import ambiente_pb2 as pb

SERVICE = 'ambiente.SourceControl'

class SourceControlStub:
    def __init__(self, channel):
        self.Configure = channel.unary_unary(
            f'/{SERVICE}/Configure',
            request_serializer=pb.ControlRequest.SerializeToString,
            response_deserializer=pb.ControlResponse.FromString)
        self.GetState = channel.unary_unary(
            f'/{SERVICE}/GetState',
            request_serializer=pb.ControlRequest.SerializeToString,
            response_deserializer=pb.ControlResponse.FromString)

class SourceControlServicer:
    def Configure(self, request, context):
        context.abort(grpc.StatusCode.UNIMPLEMENTED, 'Configure nao implementado')
    def GetState(self, request, context):
        context.abort(grpc.StatusCode.UNIMPLEMENTED, 'GetState nao implementado')

def add_SourceControlServicer_to_server(servicer, server):
    handlers = {
        'Configure': grpc.unary_unary_rpc_method_handler(
            servicer.Configure,
            request_deserializer=pb.ControlRequest.FromString,
            response_serializer=pb.ControlResponse.SerializeToString),
        'GetState': grpc.unary_unary_rpc_method_handler(
            servicer.GetState,
            request_deserializer=pb.ControlRequest.FromString,
            response_serializer=pb.ControlResponse.SerializeToString)
    }
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(SERVICE, handlers),))
