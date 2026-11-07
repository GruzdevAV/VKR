from typing import Literal

from sqlalchemy import (
    Boolean,
    Integer,
    Table, 
    Column,
    DDL
)
from Helpers import GeneralHelper
from utils import (
    AuditableMixin,
    AuditableProtocol,
    AUDIT_TIMESTAMP_NAME,
    AUDIT_TIMESTAMP_NEW
)
from sqlalchemy.orm import DeclarativeBase, InstrumentedAttribute

TIMESTAMP_SQL_PARAMETER = ":timestamp"

def make_audit_schema(audited_tables: list[type[AuditableProtocol]]) -> tuple[list[Table], list[DDL], list[DDL], dict[str, DDL]]:
    """
    Make tables for audit and triggers to insert data into them.
    """
    tables: list[Table] = []
    triggers: list[DDL] = []
    views: list[DDL] = []
    queries: dict[str, DDL] = {}
    for table in audited_tables:
        validate_auditable_table(table)
        tables += make_audit_tables(table)
        triggers += make_triggers(table)
        # views += [AuditableHelper.make_views(table)]
        queries |= make_queries(table)
    
    return tables, triggers, views, queries

def validate_auditable_table(table: type[AuditableProtocol]):
    """
    Assert `table` **does** have fields and keys and `AuditableMixin` is correctly used.
    """
    assert hasattr(table, '__audit_key__')
    assert hasattr(table, '__audit_observed_fields__')
    assert hasattr(table, '__audit_observed_groups__')
    assert hasattr(table, '__audit_is_deletable__')
    assert table.__audit_is_deletable__ or len(table.__audit_observed_fields__)>0, "Auditable table must have at least one observed field or be marked as deletable."

    for pk_name in table.__audit_key__:
        pk = GeneralHelper.get_field(table, pk_name)
        assert pk.primary_key, f"Field {pk_name} is not a PRIMARY KEY"
    for observed_field_name in table.__audit_observed_fields__:
        field = GeneralHelper.get_field(table, observed_field_name)
        assert not field.primary_key, f"Field {observed_field_name} is a PRIMARY KEY"
        # assert not field.nullable, f"Field {observed_field_name} is a NULLABLE"
    fields_in_groups = set[str]()
    for fields in table.__audit_observed_groups__.values():
        for field in fields:
            fields_in_groups.add(field)
    assert set(table.__audit_observed_fields__) == fields_in_groups

def find_tabels_to_audit(base: type[DeclarativeBase]) -> list[type[AuditableProtocol]]:
    """
    Searches for classes that are subclasses of `AuditableMixin`.
    """

    return [
        cls for cls in GeneralHelper.all_subclasses(base)
        if issubclass(cls, AuditableMixin)
    ]

def get_audit_table_name_for_group(table_name: str, group_name: str) -> str:
    name = f'audit_{table_name}_{group_name}'
    GeneralHelper.validate_name_length(name)
    return name

def get_audit_table_name_for_existance(table_name: str) -> str:
    name = f'audit_{table_name}_existance'
    GeneralHelper.validate_name_length(name)
    return name

def get_trigger_name(table_name: str, operation: str) -> str:
    name = f'trgr_{operation}_{table_name}'
    GeneralHelper.validate_name_length(name)
    return name

def get_audit_timestamp_column():
    return Column(AUDIT_TIMESTAMP_NAME, Integer, primary_key=True, nullable=False)

def get_audit_is_deleted_column():
    return Column("is_deleted", Boolean, primary_key=False, nullable=False)

def _make_audit_table_for_group(
    auditable_table: type[AuditableProtocol], 
    pks: list[InstrumentedAttribute], 
    group_name: str,
    fields: list[InstrumentedAttribute]
) -> Table:
    table_name = get_audit_table_name_for_group(auditable_table.__tablename__, group_name)
    pk_columns = list(
        Column(GeneralHelper.get_log_field_name(pk.name), pk.type, primary_key=True, nullable=False)
        for pk in pks
    )
    field_columns = list(
        Column(GeneralHelper.get_log_field_name(field.name), field.type, nullable=False, index=True)
        for field in fields
    )
    return Table(
        table_name,
        auditable_table.metadata,
        get_audit_timestamp_column(),
        *pk_columns,
        *field_columns
    )

def _make_audit_table_for_existance(
    auditable_table: type[AuditableProtocol], 
    pks: list[InstrumentedAttribute], 
):
    table_name = get_audit_table_name_for_existance(auditable_table.__tablename__)
    pk_columns = list(
        Column(GeneralHelper.get_log_field_name(pk.name), pk.type, primary_key=True, nullable=False)
        for pk in pks
    )
    return Table(
        table_name,
        auditable_table.metadata,
        get_audit_timestamp_column(),
        *pk_columns,
        get_audit_is_deleted_column()
    )
    

def make_audit_tables(auditable_table: type[AuditableProtocol]) -> list[Table]:
    """
    Makes tables for each auditable group and if `auditable_table.__audit_is_deletable__` for existance
    """
    pk_names = auditable_table.__audit_key__
    pks = list(
        GeneralHelper.get_field(auditable_table, pk_name)
        for pk_name in pk_names
    )
    tables = list[Table]()
    if auditable_table.__audit_is_deletable__:
        tables.append(_make_audit_table_for_existance(auditable_table, pks))
    for group_name, field_names in auditable_table.__audit_observed_groups__.items():
        fields = list(
            GeneralHelper.get_field(auditable_table, field_name)
            for field_name in field_names
        )
        table = _make_audit_table_for_group(auditable_table, pks, group_name, fields)
        tables.append(table)
    return tables

def _make_trigger(
        auditable_table: type[AuditableProtocol], 
        log_pk_names: list[str], 
        log_field_groups: dict[str, list[str]],
        operation: Literal['INSERT', 'UPDATE', 'DELETE']
    ) -> DDL:
    trigger_name = get_trigger_name(auditable_table.__tablename__, operation)

    inserts = list[str]()
    if operation in ('INSERT', 'UPDATE'):
        for group_name, field_names in auditable_table.__audit_observed_groups__.items():

            audit_table_name = get_audit_table_name_for_group(auditable_table.__tablename__, group_name)
            # Inserts into each audit table
            insert = f'''
    INSERT INTO {audit_table_name} ( 
        {AUDIT_TIMESTAMP_NAME},
        {', '.join(log_pk_names)},
        {', '.join(log_field_groups[group_name])}
    )
    SELECT 
        {AUDIT_TIMESTAMP_NEW},
        {', '.join(
            f'new.{pk_name}' for pk_name in auditable_table.__audit_key__
        )},
        {', '.join(
            f'new.{field_name}' for field_name in field_names
        )}
            ''' + (f'''
    WHERE ({" OR ".join( # if UPDATE then insert only if a field in group got updated
        f"NEW.{field_name} IS NOT OLD.{field_name}"
        for field_name in field_names
    )});
            ''' if operation == 'UPDATE' else ';')
            inserts.append(insert)
            # end for
    if operation in ('INSERT', 'DELETE') and auditable_table.__audit_is_deletable__:
        TABLE = 'NEW' if operation == 'INSERT' else 'OLD'
        audit_table_name = get_audit_table_name_for_existance(auditable_table.__tablename__)
        insert = f'''
    INSERT INTO {audit_table_name} (
        {AUDIT_TIMESTAMP_NAME},
        {', '.join(log_pk_names)},
        is_deleted
    )
    VALUES (
        {AUDIT_TIMESTAMP_NEW},
        {', '.join(
            f'{TABLE}.{pk_name}' 
            for pk_name in auditable_table.__audit_key__
        )},
        {int(operation == "DELETE")}
    );
        '''
        inserts.append(insert)

    trigger_expression = f'''
CREATE TRIGGER {trigger_name}
    AFTER {operation} ON {auditable_table.__tablename__}
BEGIN
{'\n'.join(inserts)}
END
    '''
    # TODO Add updating of last_changed_timestamp in any of observed fields changed
    return DDL(trigger_expression)
    
def make_triggers(auditable_table: type[AuditableProtocol]) -> list[DDL]:
    """
    Makes DDLs of INSERT, UPDATE, and if `auditable_table.__audit_is_deletable__` DELETE triggers.
    """
    triggers = list[DDL]()
    pk_names = auditable_table.__audit_key__
    log_pk_names = list(
        GeneralHelper.get_log_field_name(pk_name)
        for pk_name in pk_names
    )
    log_field_groups = {
        group_name: list(
            GeneralHelper.get_log_field_name(field_name)
            for field_name in field_names
        ) for group_name, field_names in auditable_table.__audit_observed_groups__.items()
    }
    triggers.append(_make_trigger(auditable_table, log_pk_names, log_field_groups, 'INSERT'))
    if len(log_field_groups)>0:
        triggers.append(_make_trigger(auditable_table, log_pk_names, log_field_groups, 'UPDATE'))
    if auditable_table.__audit_is_deletable__:
        triggers.append(_make_trigger(auditable_table, log_pk_names, log_field_groups, 'DELETE'))
    return triggers

def make_views(auditable_table: type[AuditableProtocol]):
    """
    Makes views
    """
    raise Exception("Not implemented")

def _make_existance_query(auditable_table: type[AuditableProtocol]):
    query = f'''
WITH T AS (
    SELECT *,
        ROW_NUMBER() OVER (PARTITION BY {', '.join(
            GeneralHelper.get_log_field_name(pk_name)
            for pk_name in auditable_table.__audit_key__
        )} ORDER BY {AUDIT_TIMESTAMP_NAME} DESC) AS RN
    FROM {get_audit_table_name_for_existance(auditable_table.__tablename__)}
    WHERE {AUDIT_TIMESTAMP_NAME} <= {TIMESTAMP_SQL_PARAMETER}
)
SELECT {AUDIT_TIMESTAMP_NAME},
       {', '.join(auditable_table.__audit_key__)}
  FROM T
 WHERE T.RN = 1 AND
       T.is_deleted = 0
 ORDER BY {AUDIT_TIMESTAMP_NAME} DESC
    '''
    return DDL(query)

def _make_query_to_groups(auditable_table: type[AuditableProtocol]):
    log_pk_names = list(
        GeneralHelper.get_log_field_name(pk_name)
        for pk_name in auditable_table.__audit_key__
    )
    log_groups = {
        group_name: list(
            GeneralHelper.get_log_field_name(field_name)
            for field_name in field_names
        ) 
        for group_name, field_names in auditable_table.__audit_observed_groups__.items()
    }
    with_expressions = list[str]()
    selection_expression = list[str]()
    from_expression = f'{auditable_table.__tablename__} MAIN_T'
    for group_name in auditable_table.__audit_observed_groups__:
        audit_table_name = get_audit_table_name_for_group(auditable_table.__tablename__, group_name)
        with_expressions.append(f'''
    T_{group_name} AS (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY {', '.join(log_pk_names)} ORDER BY {AUDIT_TIMESTAMP_NAME} DESC) AS RN
      FROM {audit_table_name}
     WHERE {AUDIT_TIMESTAMP_NAME} <= {TIMESTAMP_SQL_PARAMETER}
)''')
        selection_expression.extend(
            f"{audit_table_name}.{log_field_name}" 
            for log_field_name in log_groups[group_name]
        )
        ON = " AND ".join(
            f"MAIN_T.{pk_name} = T_{group_name}.{log_pk_name}"
            for pk_name, log_pk_name in zip(auditable_table.__audit_key__, log_pk_names)
        )
        from_expression += f" LEFT JOIN T_{group_name} ON {ON} AND T_{group_name}.RN = 1"
    result_expression = f'''
WITH {', '.join(with_expressions)}
SELECT {', '.join(selection_expression)}
FROM {from_expression}
ORDER BY {', '.join(auditable_table.__audit_key__)}, timestamp DESC
    '''
    return DDL(result_expression)

def make_queries(auditable_table: type[AuditableProtocol]) -> dict[str, DDL]:
    """
    Makes queries for auditable tables.

    If `auditable_table.__audit_is_deletable__`
    then make query to existance table with a parameter of timestamp
    to get all non-deleted primary keys relevant at the timestamp.

    Make query to all auditable tables with a parameter of timestamp
    to get every observed field relevant at the timestamp.
    """
    views = dict[str, DDL]()

    if auditable_table.__audit_is_deletable__:
        views[f'EXISTANCE QUERY {auditable_table.__tablename__}.sql'] = _make_existance_query(auditable_table)
    views[f'FIELDS QUERY {auditable_table.__tablename__}.sql'] = _make_query_to_groups(auditable_table)

    return views
