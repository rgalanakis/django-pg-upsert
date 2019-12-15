__version__ = "0.1.0"


import django.db
from django.db import connection, connections
from django.db import models, router
from django.db.models.sql import InsertQuery
from django.db.models.sql.compiler import SQLInsertCompiler


class IgnoreConflictSuffix:
    _SQL = "ON CONFLICT {conflict_sql} DO NOTHING"

    def __init__(self, constraint=None):
        self._constraint = constraint

    def as_sql(self):
        return self._SQL.format(conflict_sql=self._conflict_sql)

    def has_conflict_target(self):
        return bool(self._constraint)

    @property
    def _conflict_sql(self) -> str:
        if self._constraint:
            return "ON CONSTRAINT " + self._constraint

        return ''


class SQLUpsertCompiler(django.db.models.sql.compiler.SQLInsertCompiler):
    _REWRITE_PART = 'ON CONFLICT DO NOTHING'

    ignore_conflicts_suffix = None

    def as_sql(self ):
        sql = super().as_sql()

        if self.ignore_conflicts_suffix.has_conflict_target():
            conflict_part = self.ignore_conflicts_suffix.as_sql()

            return [
                (self._rewrite_sql_statement(query, conflict_part), params)
                for query, params in sql
            ]
        else:
            return sql

    def _rewrite_sql_statement(self, query: str, new_conflict_part):
        return query.replace(self._REWRITE_PART, new_conflict_part)


class UpsertQuery(django.db.models.sql.InsertQuery):
    def get_compiler(self, using=None, connection=None):
        if using is None and connection is None:
            raise ValueError("Need either using or connection")
        if using:
            connection = connections[using]
        return SQLUpsertCompiler(self, connection, using)


class Upsert:
    def __init__(self, obj, db=None, constraint=None):
        self._obj = obj
        self._db = db
        self._ignore_conflicts = IgnoreConflictSuffix(constraint)

        if self._db is None:
            self._db = self._model._default_manager.db

    def as_sql(self):
        return self._get_compiled_query().as_sql()

    def execute(self):
        return self._get_compiled_query().execute_sql()

    def _get_compiled_query(self):
        fields = [f for f in self._meta.concrete_fields if not f.auto_created]

        query = UpsertQuery(self._model, ignore_conflicts=True)
        query.insert_values(fields, [self._obj], raw=True)

        compiler = query.get_compiler(self._db)
        compiler.ignore_conflicts_suffix = self._ignore_conflicts

        return compiler

    @property
    def _meta(self):
        return self._obj._meta

    @property
    def _model(self):
        return self._meta.model


class Manager(django.db.models.Manager):
    def insert_conflict(self, data, constraint=None):
        obj = self.model(**data)

        return Upsert(obj, self.db, constraint).execute()