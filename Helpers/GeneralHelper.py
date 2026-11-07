from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Generator
from utils import (
    AuditableMixin,
    AuditableProtocol,
    HiderProtocol,
    HidingMixin,
    HiddenMixin,
    HidingProtocol,
    HiddenProtocol,
)
from sqlalchemy.orm import DeclarativeBase, InstrumentedAttribute


def validate_name_length(name: str, max_length: int = 63) -> None:
    """
    SQLite has a length limit for names.

    This function checks if name lenght is within bounds.
    """
    assert name.count('.') == 0, f"Name has {name.count('.')} dots ('.'). Must be 0."
    length = len(name.encode('utf-8'))
    assert length <= max_length, f"Length of name '{name}' = {length}, which exceeds {max_length} bytes"

def validate_hider_table(table: type[HidingProtocol | HiddenProtocol]):
    assert len(list(table.__table__.primary_key)) == 1
    if issubclass(table, HidingMixin):
        assert hasattr(table, 'hiding_hierarchy')

def get_schema(base: type[DeclarativeBase]) -> dict:
    """
    Returns schema of marked database.
    """

    @dataclass
    class SchematicTable:
        table_name: str
        # name, type
        pk_names: list[tuple[str, Any]] # = field(default_factory=list)
        has_hidden_mixin: bool = field(default=False)
        has_hiding_mixin: bool = field(default=False)
        has_auditable_mixin: bool = field(default=False)
        audit_keys: list[str] = field(default_factory=list)
        #                               name, type
        observed_groups: dict[str, list[tuple[str, Any]]] = field(default_factory=dict)
        # pk_name, fk_name, junction_name
        refs_in_junctions: list[tuple[str, str, str]] = field(default_factory=list)
        # table_pk_name, table_name
        fks: list[tuple[str, str]] = field(default_factory=list)

    res = dict[str, SchematicTable]()
    def set_default(cls: type[DeclarativeBase]):
        nonlocal res
        res.setdefault(
            cls.__tablename__,
            SchematicTable(
                cls.__tablename__,
                list((pk.name, pk.type) for pk in cls.__table__.primary_key)
            )
        )
    def get(cls: type[DeclarativeBase]):
        nonlocal res
        return res[cls.__tablename__]
    
    for cls in all_subclasses(base):
        set_default(cls)
        is_junction = len(cls.__table__.primary_key)>1 # type: ignore
        get(cls).has_hidden_mixin = issubclass(cls, HiddenMixin)
        get(cls).has_hiding_mixin = issubclass(cls, HidingMixin)
        if issubclass(cls, AuditableMixin):
            get(cls).has_auditable_mixin = True
            get(cls).audit_keys = cls.__audit_key__
            get(cls).observed_groups = {
                group_name: list((field, cls.__table__.columns[field].type) for field in fields)
                for group_name, fields in cls.__audit_observed_groups__.items()
            }
        if is_junction:
            for fk in cls.__table__.foreign_keys:
                target_table_name, target_field_name = fk.target_fullname.split('.')
                column_with_fk = fk.parent
        else: 
            for fk in cls.__table__.foreign_keys:
                table_name, field_name = fk.target_fullname.split('.')
                get(cls).fks.append((field_name, table_name))
    return res

def all_subclasses[T](cls: type[T]) -> Generator[type[T]]:
    """
    Returns all subclasses recursively
    """
    for subcls in cls.__subclasses__():
        yield subcls
        yield from all_subclasses(subcls)

def get_field(table: type[DeclarativeBase|AuditableProtocol], field_name: str) -> InstrumentedAttribute:
    """
    Returns field named `field_name` from table `table`.
    
    Asserts the field indeed exists and is database field.
    """
    assert hasattr(table, field_name), f"Table {table.__tablename__} has no field '{field_name}'"
    field = getattr(table, field_name)
    assert isinstance(field, InstrumentedAttribute), f"'{field_name}' is not 'InstrumentedAttribute'"
    return field

def get_base_class(module: ModuleType) -> type[DeclarativeBase]:
    """
    Searches for `Base` class.
    """
    base = getattr(module, 'Base', None)
    assert base is not None and issubclass(base, DeclarativeBase), "Base not found."
    return base

def get_log_field_name(field_name: str) -> str:
    log_field_name = f'log_{field_name}'
    validate_name_length(log_field_name)
    return log_field_name
