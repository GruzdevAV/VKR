from dataclasses import dataclass, field

from sqlalchemy.orm import DeclarativeBase
from Helpers import GeneralHelper
from utils import (
    HiddenMixin,
    HiderProtocol,
    HidingMixin,
    HidingProtocol,
    HiddenProtocol
)

@dataclass
class HiderFinder:
    @dataclass 
    class FkToHiding:
        entity_foreign_key: str
        connected_primary_key: str
        connected_entity: type[HidingProtocol]
    @dataclass 
    class PkInHiding:
        connected_foreign_key: str
        connected_entity: type[HidingProtocol]
    @dataclass 
    class InJoins:
        entity_primary_key: str
        connected_primary_key: str
        junction: type[DeclarativeBase]
        connected_entity: type[HidingProtocol]
    entity: type[DeclarativeBase|HiddenProtocol]
    fks_to_hidings: list[FkToHiding] = field(default_factory=list[FkToHiding])
    pk_in_hidings: list[PkInHiding] = field(default_factory=list[PkInHiding])
    in_join_with_hidings: list[InJoins] = field(default_factory=list[InJoins])

def find_hidermixin_tables(base: type[DeclarativeBase]) -> tuple[dict[str, type[HiddenProtocol]], dict[str, type[HidingProtocol]], dict[str, type[HiderProtocol]]]:
    """
    Searches for classes that are subclasses of `HideMixin`.
    """
    hidden_tables = dict[str, type[HiddenProtocol]]()
    hiding_tables = dict[str, type[HidingProtocol]]()
    hider_tables = dict[str, type[HiderProtocol]]()
    for cls in GeneralHelper.all_subclasses(base):
        hidden = issubclass(cls, HiddenMixin)
        hiding = issubclass(cls, HidingMixin)
        if hiding and hidden:
            hider_tables[cls.__tablename__] = cls
        elif hiding:
            hiding_tables[cls.__tablename__] = cls
        elif hidden:
            hidden_tables[cls.__tablename__] = cls
    return hidden_tables, hiding_tables, hider_tables

def find_hider_schema(base: type[DeclarativeBase]):
    hidden_tables, hiding_tables, hider_tables = find_hidermixin_tables(base)
    found = dict[str, HiderFinder]()
    for cls in GeneralHelper.all_subclasses(base):

        if cls.__tablename__ in hidden_tables.keys() | hider_tables.keys():
            # cls has HiddenMixin
            found.setdefault(cls.__tablename__, HiderFinder(cls))

        is_junction = len(cls.__table__.primary_key)>1 # type: ignore
        if is_junction:
            # cls is a junction
            t: list[tuple[str, str, str]] = list(
                (fk.name, )+fk.target_fullname.split('.')
                for fk in cls.__table__.foreign_keys
            )
            ...
        else:
            for fk in cls.__table__.foreign_keys:
                # for every foreign key of cls
                table_name, field_name = fk.target_fullname.split('.')
                if table_name in hiding_tables.keys() | hider_tables.keys():
                    # if FK references a HidingMixin
                    # cls has a FK with a table with HidingMixin
                    found.setdefault(cls.__tablename__, HiderFinder(cls))
                    connected = hiding_tables.get(table_name) or hider_tables.get(table_name)
                    assert connected is not None
                    found[cls.__tablename__].fks_to_hidings.append(
                        HiderFinder.FkToHiding(
                            field_name,
                            list(connected.__table__.primary_key)[0].name,
                            connected
                        )
                    )
                    ...

def make_view(
    entity: type[DeclarativeBase|HiddenProtocol], 
    *args: tuple[type[DeclarativeBase], type[HidingProtocol]]
):
    """
    Creates view to return non-hidden primary keys of entity.

    Parameters:

        entity - table for which to make view

        args - pairs of juncion table and another hider entity that might hide main entity
    """
    pk = list(entity.__table__.primary_key)[0]
    selections = list[str]()
    if issubclass(entity, HiddenMixin):
        selections.append(f"""
SELECT {pk.name},
       is_hidden AS hide
  FROM {entity.__tablename__}
        """)
    for junction, hiding in args:
        selection = f"""
SELECT {entity.__tablename__}.{pk.name},
       {hiding.__tablename__}.is_hiding AS hide
  FROM {entity.__tablename__} INNER JOIN {junction.__tablename__} ON {entity.__tablename__}.{pk.name} = {junction.__tablename__}.{junction.__table__.foreign_keys}
    """
