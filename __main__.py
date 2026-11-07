from types import ModuleType
from sqlalchemy import (
    create_engine, 
)
from sqlacodegen.generators import DataclassGenerator
from pathlib import Path

import importlib.util
import argparse

from Helpers import GeneralHelper, AuditableHelper
from utils import AuditableProtocol

def load_model_module(file_path: str) -> ModuleType:
    '''
    Importing module. As if::

        import module
    
    So now you can::
    
        module.function_class_variable
    '''
    path = Path(file_path).resolve()
    module_name = path.stem
    
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec is not None, "spec is None"
    assert spec.loader is not None, "spec.loader is None"
    module = importlib.util.module_from_spec(spec)
    assert module is not None, "module is None"
    spec.loader.exec_module(module)
    return module


def parse_module(path_to_module: str, path_to_db: str, path_to_new_module: str|None):
    module = load_model_module(path_to_module)
    base = GeneralHelper.get_base_class(module)
    tables_to_audit = AuditableHelper.find_tabels_to_audit(base) 
    tables, triggers, views, queries = AuditableHelper.make_audit_schema(tables_to_audit)
    engine = create_engine(path_to_db)
    
    base.metadata.create_all(engine)
    connecion = engine.connect()
    for trigger in triggers:
        connecion.execute(trigger)
    for view in views:
        connecion.execute(view)
    for file_name, query in queries.items():
        with open(file_name, 'w') as file:
            file.write(str(query))
    if path_to_new_module is not None:
        generator = DataclassGenerator(base.metadata, engine, [])
        with open(path_to_new_module, 'w') as file:
            file.write(generator.generate())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path_to_module', help="Путь к файлу модели базы данных на SQLAlchemy")
    parser.add_argument('path_to_db', help="URL для создания базы данных SQLite, например, sqlite:///path_to_db_file.db")
    parser.add_argument('path_to_new_module', nargs="?", default=None, help="Путь для создания файла дополненной модели базы данных на SQLAlchemy")
    args = parser.parse_args()

    parse_module(args.path_to_module, args.path_to_db, args.path_to_new_module)

if __name__ == '__main__':
    main()