from typing import (
    Any,
    ClassVar,
    Protocol
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
)
from sqlalchemy import (
    Boolean,
    BLOB,
    Column,
    ForeignKey,
    FromClause,
    MetaData,
    Table,
    TypeDecorator,
    Integer,
    text,
)


AUDIT_TIMESTAMP_NAME = "audit_timestamp"

AUDIT_TIMESTAMP_NEW = "(CAST(unixepoch('subsec')*1000 AS INTEGER))"

class PKTypeInteger(TypeDecorator):
    """
    Type base for integer primary keys.
    """
    impl = Integer
    cache_ok = True

class PKTypeBlob(TypeDecorator):
    """
    Type base for blob primary keys.
    """
    impl = BLOB
    cache_ok = True

class ImageKey(PKTypeBlob): ...
class StringKey(PKTypeBlob): ...

class AuditableMixin:
    """
    Mixin for audit capabilities.

    `last_changed_timestamp` is for when auditable table's `__audit_observed_fields__` are changed
    """
    __audit_key__: ClassVar[list[str]]
    __audit_observed_fields__: ClassVar[list[str]]
    __audit_observed_groups__: ClassVar[dict[str, list[str]]]
    __audit_is_deletable__: ClassVar[bool]

    last_changed_timestamp: Mapped[Integer] = mapped_column(Integer, nullable=False, server_default=text(AUDIT_TIMESTAMP_NEW))

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        assert type(cls.__audit_observed_fields__) in (dict, list)
        assert issubclass(cls, DeclarativeBase)
        # if has `__audit_observed_fields__` create `__audit_observed_groups__`
        if hasattr(cls,'__audit_observed_fields__'):
            assert type(cls.__audit_observed_fields__) is list
            field_names = list[str]()
            groups: dict[str, list[str]] = dict()
            for i, item in enumerate(cls.__audit_observed_fields__, 1):
                if type(item) is str:
                    groups[item] = [item]
                elif type(item) is list:
                    assert all(map(lambda x: type(x) is str, item)), f"If item of `__audit_observed_fields__` is a list, it must be a list of `str`. Actually: {item}"
                    groups[f"group_{i}"] = sorted(item)
                else:
                    raise ValueError(f"An element of `__audit_observed_fields__` should be either a string or a sequence. Actually: {type(item)}")
                field_names.extend(groups[item])
            cls.__audit_observed_groups__ = groups
            cls.__audit_observed_fields__ = sorted(field_names)
        # if has `__audit_observed_groups__` create `__audit_observed_fields__`
        elif hasattr(cls,'__audit_observed_groups__'):
            assert type(cls.__audit_observed_groups__) is dict
            fields_in_groups = set[str]()
            for fields in cls.__audit_observed_groups__.values():
                for field in fields:
                    fields_in_groups.add(field)
            cls.__audit_observed_fields__ = sorted(fields_in_groups)
        # GeneralHelper.validate_auditable_table(cls)

class DeclarativeBaseProtocol(Protocol):
    __tablename__: Any
    __table__: ClassVar[FromClause]
    metadata: ClassVar[MetaData]

class AuditableProtocol(DeclarativeBaseProtocol, Protocol):
    """
    Hint for linter. Matches necessary parts of a class like::

        class _(DeclarativeBase, AuditableMixin):
            ...

    """
    # AuditableMixin
    __audit_key__: ClassVar[list[str]]
    __audit_observed_fields__: ClassVar[list[str]]
    __audit_observed_groups__: ClassVar[dict[str, list[str]]]
    __audit_is_deletable__: ClassVar[bool]
    last_changed_timestamp: Mapped[Integer]


class HidingMixin:
    """
    Mixin to indicate if this entity hides connected entities.

    Entity can hide entities with equal or less hierarch number.
    """
    hiding_hierarchy: ClassVar[int]
    is_hiding: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('0'))

class HiddenMixin:
    """
    Mixin to indicate if this entity is hidden.
    """
    is_hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text('0'))

class HidingProtocol(DeclarativeBaseProtocol, Protocol):
    """
    Hint for linter. Matches necessary parts of a class like::

        class _(DeclarativeBase, HidingMixin):
            ...

    """
    # HidingMixin
    hiding_hierarchy: ClassVar[int]
    is_hiding: Mapped[bool]

class HiddenProtocol(DeclarativeBaseProtocol, Protocol):
    """
    Hint for linter. Matches necessary parts of a class like::

        class _(DeclarativeBase, HiddenMixin):
            ...

    """
    # HiddenMixin
    is_hidden: Mapped[bool]

class HiderProtocol(HidingProtocol, HiddenProtocol, Protocol):
    """
    Hint for linter. Matches necessary parts of a class like::

        class _(DeclarativeBase, HiddenMixin, HidingMixin):
            ...

    """

def makeStoredStringClass(base: type[DeclarativeBase]) -> Table:
    """
    Returns table to store large strings.

    Has overhead of about `[CALCULATE]` bytes and computaion needed to extract data.
    
    If string is large or has muliple similar strings, it's better to use this table to store it.

    Relies on out of SQLite help to compress and decompress strings.

    It's better to store strings here if there is a chance they are very long and especially if there are multiple strings with similar content.
    
    - `stored_string_hash_id` - hash SHA-2 256 of full uncompressed string that is also Primary Key
    - `is_zipped` - `True` if `stored_string_change` is compressed
    - `base_stored_string_id` - `NULL` if `stored_string_change` is the root string else `NOT NULL` if delta
        - `position` - where to paste change into root string
        - `length` - how many characters of root string should be replaced 
    """
    return Table(
        'StoredStrings',
        base.metadata,
        Column('stored_string_hash_id', StringKey, primary_key=True, nullable=False, unique=True, index=True),
        Column('stored_string_change', BLOB, nullable=False),
        Column('is_zipped', Boolean, nullable=False),
        Column('position', Integer, nullable=False),
        Column('length', Integer, nullable=False),
        Column('base_stored_string_id', StringKey, ForeignKey("StoredStrings.stored_string_id"), nullable=True),
    )

def makeStoredImageClass(base: type[DeclarativeBase]) -> Table:
    """
    Returns table to store images.

    - `stored_image_hash_id` - hash SHA-2 256 of `stored_image_data` that is also Primary Key
    - `stored_image_phash` - Perceptual Hash (**not implemented**; should find a way to compute phash consistently on different platforms)
    """
    return Table(
        'StoredImages',
        base.metadata,
        Column('stored_image_hash_id', ImageKey, primary_key=True, nullable=False, unique=True, index=True),
        Column('stored_image_data', BLOB, nullable=False, unique=True),
        Column('stored_image_height', Integer, nullable=False),
        Column('stored_image_width', Integer, nullable=False),
        # Column('stored_image_phash', BLOB, nullable=False, index=True),
    )
