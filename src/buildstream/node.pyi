from typing import overload, Generic, List, Mapping, Optional, Sequence, TypeVar, Type, Dict, Any

from ._project import Project

TNode = TypeVar("TNode", bound="Node")
TValidNodeValue = TypeVar("TValidNodeValue", int, str, bool, Mapping, Sequence)

class ProvenanceInformation: ...

class Node:
    def clone(self) -> "Node": ...
    def get_provenance(self) -> ProvenanceInformation: ...
    def strip_node_info(self) -> Dict[str, Any]: ...

class MappingNode(Node, Generic[TNode]):
    def __init__(self, file_index: int, line: int, column: int, value: Mapping[str, TValidNodeValue]) -> None: ...
    def clone(self) -> MappingNode[TNode]: ...
    def validate_keys(self, valid_keys: List[str]): ...
    def get_bool(self, key: str, default: bool) -> bool: ...
    @overload
    def get_str_list(self, key: str) -> List[str]: ...
    @overload
    def get_str_list(self, key: str, default: List[str]) -> List[str]: ...
    @overload
    def get_str_list(self, key: str, default: Optional[List[str]]) -> Optional[List[str]]: ...
    @overload
    def get_str(self, key: str) -> str: ...
    @overload
    def get_str(self, key: str, default: str) -> str: ...
    @overload
    def get_str(self, key: str, default: Optional[str]) -> Optional[str]: ...
    @overload
    def get_int(self, key: str) -> int: ...
    @overload
    def get_int(self, key: str, default: int) -> int: ...
    @overload
    def get_int(self, key: str, default: Optional[int]) -> Optional[int]: ...
    @overload
    def get_enum(self, key: str, constraint: object) -> object: ...
    @overload
    def get_enum(self, key: str, constraint: object, default: Optional[object]) -> Optional[object]: ...
    @overload
    def get_mapping(self, key: str) -> "MappingNode": ...
    @overload
    def get_mapping(self, key: str, default: "MappingNode") -> "MappingNode": ...
    @overload
    def get_mapping(self, key: str, default: Optional["MappingNode"]) -> Optional["MappingNode"]: ...
    @overload
    def get_node(self, key: str) -> Node: ...
    @overload
    def get_node(self, key: str, allowed_types: Optional[List[Type[Node]]]) -> Node: ...
    @overload
    def get_node(self, key: str, allowed_types: Optional[List[Type[Node]]], allow_none: bool) -> Optional[Node]: ...

class ScalarNode(Node):
    def as_str(self) -> str: ...
    def clone(self) -> "ScalarNode": ...

class SequenceNode(Node, Generic[TNode]):
    def as_str_list(self) -> List[str]: ...
    def clone(self) -> "SequenceNode[TNode]": ...

def _assert_symbol_name(
    symbol_name: str, purpose: str, *, ref_node: Optional[Node], allow_dashes: bool = True
) -> None: ...
def _new_synthetic_file(filename: str, project: Optional[Project]) -> MappingNode[TNode]: ...
