import copy
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Dict,
    Generator,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
    Union,
)

import sqlalchemy

from edgy.conf import settings
from edgy.core.db.fields import CharField, TextField
from edgy.core.db.fields.foreign_keys import BaseForeignKeyField
from edgy.core.db.fields.one_to_one_keys import BaseOneToOneKeyField
from edgy.core.db.querysets.mixins import QuerySetPropsMixin
from edgy.core.db.querysets.protocols import AwaitableQuery
from edgy.core.utils.models import DateParser, ModelParser
from edgy.exceptions import MultipleObjectsReturned, ObjectNotFound
from edgy.protocols.queryset import QuerySetProtocol

if TYPE_CHECKING:  # pragma: no cover
    from edgy.core.db.models import Model, ReflectModel


_EdgyModel = TypeVar("_EdgyModel", bound="Model")
ReflectEdgyModel = TypeVar("ReflectEdgyModel", bound="ReflectModel")

EdgyModel = Union[_EdgyModel, ReflectEdgyModel]


class BaseQuerySet(QuerySetPropsMixin, DateParser, ModelParser, AwaitableQuery[EdgyModel]):
    ESCAPE_CHARACTERS = ["%", "_"]

    def __init__(
        self,
        model_class: Any = None,
        filter_clauses: Any = None,
        select_related: Any = None,
        limit_count: Any = None,
        limit_offset: Any = None,
        order_by: Any = None,
        group_by: Any = None,
        distinct_on: Any = None,
        m2m_related: Any = None,
    ) -> None:
        super().__init__(model_class=model_class)
        self.model_class = model_class
        self.filter_clauses = [] if filter_clauses is None else filter_clauses
        self.limit_count = limit_count
        self._select_related = [] if select_related is None else select_related
        self._offset = limit_offset
        self._order_by = [] if order_by is None else order_by
        self._group_by = [] if group_by is None else group_by
        self.distinct_on = [] if distinct_on is None else distinct_on
        self._expression = None
        self._cache = None
        self._m2m_related = m2m_related

        if self.is_m2m and not self._m2m_related:
            self._m2m_related = self.model_class.meta.multi_related[0]

    def build_order_by_expression(self, order_by: Any, expression: Any) -> Any:
        """Builds the order by expression"""
        order_by = list(map(self.prepare_order_by, order_by))
        expression = expression.order_by(*order_by)
        return expression

    def build_group_by_expression(self, group_by: Any, expression: Any) -> Any:
        """Builds the group by expression"""
        group_by = list(map(self.prepare_group_by, group_by))
        expression = expression.group_by(*group_by)
        return expression

    def build_filter_clauses_expression(self, filter_clauses: Any, expression: Any) -> Any:
        """Builds the filter clauses expression"""
        if len(filter_clauses) == 1:
            clause = filter_clauses[0]
        else:
            clause = sqlalchemy.sql.and_(*filter_clauses)
        expression = expression.where(clause)
        return expression

    def build_select_distinct(self, distinct_on: Any, expression: Any) -> Any:
        """Filters selects only specific fields"""
        distinct_on = list(map(self.prepare_fields_for_distinct, distinct_on))
        expression = expression.distinct(*distinct_on)
        return expression

    def is_multiple_foreign_key(
        self, model_class: Union[Type["Model"], Type["ReflectModel"]]
    ) -> Tuple[bool, List[Tuple[str, str, str]]]:
        """
        Checks if the table has multiple foreign keys to the same table.
        Iterates through all fields of type ForeignKey and OneToOneField and checks if there are
        multiple FKs to the same destination table.

        Returns a tuple of bool, list of tuples
        """
        fields = model_class.fields
        foreign_keys = []
        has_many = False

        counter = 0

        for key, value in fields.items():
            tablename = None

            if counter > 1:
                has_many = True

            if isinstance(value, (BaseForeignKeyField, BaseOneToOneKeyField)):
                tablename = value.to if isinstance(value.to, str) else value.to.__name__

                if tablename not in foreign_keys:
                    foreign_keys.append((key, tablename, value.related_name))
                    counter += 1
                else:
                    counter += 1

        return has_many, foreign_keys

    def build_tables_select_from_relationship(self) -> Any:
        """
        Builds the tables relationships and joins.
        When a table contains more than one foreign key pointing to the same
        destination table, a lookup for the related field is made to understand
        from which foreign key the table is looked up from.
        """
        tables = [self.table]
        select_from = self.table

        has_many_fk_same_table = False

        for item in self._select_related:
            # For m2m relationships
            model_class = self.model_class
            select_from = self.table

            for part in item.split("__"):
                try:
                    model_class = model_class.fields[part].target
                except KeyError:
                    # Check related fields
                    model_class = getattr(model_class, part).related_from
                    has_many_fk_same_table, keys = self.is_multiple_foreign_key(model_class)

                table = model_class.table

                # If there is multiple FKs to the same table
                if not has_many_fk_same_table:
                    select_from = sqlalchemy.sql.join(select_from, table)
                else:
                    lookup_field = None

                    # Extract the table field from the related
                    # Assign to a lookup_field
                    for values in keys:
                        field, _, related_name = values
                        if related_name == part:
                            lookup_field = field
                            break

                    select_from = sqlalchemy.sql.join(
                        select_from,
                        table,
                        select_from.c.id == getattr(table.c, lookup_field),
                    )

                tables.append(table)

        return tables, select_from

    def build_select(self) -> Any:
        """
        Builds the query select based on the given parameters and filters.
        """
        tables, select_from = self.build_tables_select_from_relationship()
        expression = sqlalchemy.sql.select(*tables)
        expression = expression.select_from(select_from)

        if self.filter_clauses:
            expression = self.build_filter_clauses_expression(
                self.filter_clauses, expression=expression
            )

        if self._order_by:
            expression = self.build_order_by_expression(self._order_by, expression=expression)

        if self.limit_count:
            expression = expression.limit(self.limit_count)

        if self._offset:
            expression = expression.offset(self._offset)

        if self._group_by:
            expression = self.build_group_by_expression(self._group_by, expression=expression)

        if self.distinct_on:
            expression = self.build_select_distinct(self.distinct_on, expression=expression)

        self._expression = expression
        return expression

    def filter_query(self, exclude: bool = False, **kwargs: Any) -> Any:
        from edgy.core.db.models import Model

        clauses = []
        filter_clauses = self.filter_clauses
        select_related = list(self._select_related)

        if kwargs.get("pk"):
            pk_name = self.model_class.pkname
            kwargs[pk_name] = kwargs.pop("pk")

        for key, value in kwargs.items():
            if "__" in key:
                parts = key.split("__")

                # Determine if we should treat the final part as a
                # filter operator or as a related field.
                if parts[-1] in settings.filter_operators:
                    op = parts[-1]
                    field_name = parts[-2]
                    related_parts = parts[:-2]
                else:
                    op = "exact"
                    field_name = parts[-1]
                    related_parts = parts[:-1]

                model_class = self.model_class
                if related_parts:
                    # Add any implied select_related
                    related_str = "__".join(related_parts)
                    if related_str not in select_related:
                        select_related.append(related_str)

                    # Walk the relationships to the actual model class
                    # against which the comparison is being made.
                    for part in related_parts:
                        try:
                            model_class = model_class.fields[part].target
                        except KeyError:
                            model_class = getattr(model_class, part).related_from

                column = model_class.table.columns[field_name]

            else:
                op = "exact"
                try:
                    column = self.table.columns[key]
                except KeyError as error:
                    # Check for related fields
                    # if an Attribute error is raised, we need to make sure
                    # It raises the KeyError from the previous check
                    try:
                        model_class = getattr(self.model_class, key).related_to
                        column = model_class.table.columns[settings.default_related_lookup_field]
                    except AttributeError:
                        raise KeyError(str(error)) from error

            # Map the operation code onto SQLAlchemy's ColumnElement
            # https://docs.sqlalchemy.org/en/latest/core/sqlelement.html#sqlalchemy.sql.expression.ColumnElement
            op_attr = settings.filter_operators[op]
            has_escaped_character = False

            if op in ["contains", "icontains"]:
                has_escaped_character = any(c for c in self.ESCAPE_CHARACTERS if c in value)
                if has_escaped_character:
                    # enable escape modifier
                    for char in self.ESCAPE_CHARACTERS:
                        value = value.replace(char, f"\\{char}")
                value = f"%{value}%"

            if isinstance(value, Model):
                value = value.pk

            clause = getattr(column, op_attr)(value)
            clause.modifiers["escape"] = "\\" if has_escaped_character else None

            clauses.append(clause)

        if exclude:
            filter_clauses.append(sqlalchemy.not_(sqlalchemy.sql.and_(*clauses)))
        else:
            filter_clauses += clauses

        return self.__class__(
            model_class=self.model_class,
            filter_clauses=filter_clauses,
            select_related=select_related,
            limit_count=self.limit_count,
            limit_offset=self._offset,
            order_by=self._order_by,
            m2m_related=self.m2m_related,
        )

    def validate_kwargs(self, **kwargs: Any) -> Any:
        return self.extract_values_from_field(kwargs, model_class=self.model_class)

    def prepare_order_by(self, order_by: str) -> Any:
        reverse = order_by.startswith("-")
        order_by = order_by.lstrip("-")
        order_col = self.table.columns[order_by]
        return order_col.desc() if reverse else order_col

    def prepare_group_by(self, group_by: str) -> Any:
        group_by = group_by.lstrip("-")
        group_col = self.table.columns[group_by]
        return group_col

    def prepare_fields_for_distinct(self, distinct_on: str) -> Any:
        distinct_on = self.table.columns[distinct_on]
        return distinct_on

    def clone(self) -> Any:
        """
        Return a copy of the current QuerySet that's ready for another
        operation.
        """
        queryset = self.__class__.__new__(self.__class__)
        queryset.model_class = self.model_class
        queryset.filter_clauses = copy.copy(self.filter_clauses)
        queryset.limit_count = self.limit_count
        queryset._select_related = copy.copy(self._select_related)
        queryset._offset = self._offset
        queryset._order_by = copy.copy(self._order_by)
        queryset._group_by = copy.copy(self._group_by)
        queryset.distinct_on = copy.copy(self.distinct_on)
        queryset._expression = self._expression
        queryset._cache = self._cache
        queryset._m2m_related = self._m2m_related
        return queryset


class QuerySet(BaseQuerySet, QuerySetProtocol):
    """
    QuerySet object used for query retrieving.
    """

    def __get__(self, instance: Any, owner: Any) -> Any:
        return self.__class__(model_class=owner)

    @property
    def sql(self) -> str:
        return str(self._expression)

    @sql.setter
    def sql(self, value: Any) -> None:
        self._expression = value

    async def __aiter__(self) -> AsyncIterator[EdgyModel]:
        for value in await self:  # type: ignore
            yield value

    def set_query_expression(self, expression: Any) -> None:
        """
        Sets the value of the sql property to the expression used.
        """
        self.sql = expression
        self.model_class.raw_query = self.sql

    def filter_or_exclude(
        self,
        clause: Optional[sqlalchemy.sql.expression.BinaryExpression] = None,
        exclude: bool = False,
        **kwargs: Any,
    ) -> Any:
        """
        Filters or excludes a given clause for a specific QuerySet.
        """
        queryset: "QuerySet" = self.clone()
        if clause is None:
            if not exclude:
                return queryset.filter_query(**kwargs)
            return queryset.filter_query(exclude=exclude, **kwargs)

        queryset.filter_clauses.append(clause)
        return queryset

    def filter(
        self,
        clause: Optional[sqlalchemy.sql.expression.BinaryExpression] = None,
        **kwargs: Any,
    ) -> "QuerySet":
        """
        Filters the QuerySet by the given kwargs and clause.
        """
        return self.filter_or_exclude(clause=clause, **kwargs)

    def exclude(
        self,
        clause: Optional[sqlalchemy.sql.expression.BinaryExpression] = None,
        **kwargs: Any,
    ) -> "QuerySet":
        """
        Exactly the same as the filter but for the exclude.
        """
        return self.filter_or_exclude(clause=clause, exclude=True, **kwargs)

    def lookup(self, term: Any) -> "QuerySet":
        """
        Broader way of searching for a given term
        """
        queryset: "QuerySet" = self.clone()
        if not term:
            return queryset

        filter_clauses = list(queryset.filter_clauses)
        value = f"%{term}%"

        search_fields = [
            name
            for name, field in queryset.model_class.fields.items()
            if isinstance(field, (CharField, TextField))
        ]
        search_clauses = [queryset.table.columns[name].ilike(value) for name in search_fields]

        if len(search_clauses) > 1:
            filter_clauses.append(sqlalchemy.sql.or_(*search_clauses))
        else:
            filter_clauses.extend(search_clauses)

        return queryset

    def order_by(self, *order_by: str) -> "QuerySet":
        """
        Returns a QuerySet ordered by the given fields.
        """
        queryset: "QuerySet" = self.clone()
        queryset._order_by = order_by
        return queryset

    def limit(self, limit_count: int) -> "QuerySet":
        """
        Returns a QuerySet limited by.
        """
        queryset: "QuerySet" = self.clone()
        queryset.limit_count = limit_count
        return queryset

    def offset(self, offset: int) -> "QuerySet":
        """
        Returns a Queryset limited by the offset.
        """
        queryset: "QuerySet" = self.clone()
        queryset._offset = offset
        return queryset

    def group_by(self, *group_by: str) -> "QuerySet":
        """
        Returns the values grouped by the given fields.
        """
        queryset: "QuerySet" = self.clone()
        queryset._group_by = group_by
        return queryset

    def distinct(self, *distinct_on: str) -> "QuerySet":
        """
        Returns a queryset with distinct results.
        """
        queryset: "QuerySet" = self.clone()
        queryset.distinct_on = distinct_on
        return queryset

    def select_related(self, related: Any) -> "QuerySet":
        """
        Returns a QuerySet that will “follow” foreign-key relationships, selecting additional
        related-object data when it executes its query.

        This is a performance booster which results in a single more complex query but means

        later use of foreign-key relationships won’t require database queries.
        """
        queryset: "QuerySet" = self.clone()
        if not isinstance(related, (list, tuple)):
            related = [related]

        related = list(self._select_related) + related
        queryset._select_related = related
        return queryset

    async def exists(self) -> bool:
        """
        Returns a boolean indicating if a record exists or not.
        """
        expression = self.build_select()
        expression = sqlalchemy.exists(expression).select()
        self.set_query_expression(expression)
        return await self.database.fetch_val(expression)

    async def count(self) -> int:
        """
        Returns an indicating the total records.
        """
        expression = self.build_select().alias("subquery_for_count")
        expression = sqlalchemy.func.count().select().select_from(expression)
        self.set_query_expression(expression)
        return await self.database.fetch_val(expression)

    async def get_or_none(self, **kwargs: Any) -> Union[EdgyModel, None]:
        """
        Fetch one object matching the parameters or returns None.
        """
        queryset: "QuerySet" = self.filter(**kwargs)
        expression = queryset.build_select().limit(2)
        self.set_query_expression(expression)
        rows = await self.database.fetch_all(expression)

        if not rows:
            return None
        if len(rows) > 1:
            raise MultipleObjectsReturned()
        return self.model_class.from_sqla_row(rows[0], select_related=self._select_related)

    async def all(self, **kwargs: Any) -> List[EdgyModel]:
        """
        Returns the queryset records based on specific filters
        """
        queryset: "QuerySet" = self.clone()
        if self.is_m2m:
            queryset.distinct_on = [self.m2m_related]

        if kwargs:
            return await queryset.filter(**kwargs).all()

        expression = queryset.build_select()
        self.set_query_expression(expression)

        rows = await queryset.database.fetch_all(expression)

        # Attach the raw query to the object
        queryset.model_class.raw_query = self.sql

        results = [
            queryset.model_class.from_sqla_row(row, select_related=self._select_related)
            for row in rows
        ]

        if not self.is_m2m:
            return results

        return [getattr(result, self.m2m_related) for result in results]

    async def get(self, **kwargs: Any) -> EdgyModel:
        """
        Returns a single record based on the given kwargs.
        """
        if kwargs:
            return await self.filter(**kwargs).get()

        expression = self.build_select().limit(2)
        rows = await self.database.fetch_all(expression)
        self.set_query_expression(expression)

        if not rows:
            raise ObjectNotFound()
        if len(rows) > 1:
            raise MultipleObjectsReturned()
        return self.model_class.from_sqla_row(rows[0], select_related=self._select_related)

    async def first(self, **kwargs: Any) -> EdgyModel:
        """
        Returns the first record of a given queryset.
        """
        queryset: "QuerySet" = self.clone()
        if kwargs:
            return await queryset.filter(**kwargs).order_by("id").get()

        rows = await queryset.limit(1).order_by("id").all()
        if rows:
            return rows[0]

    async def last(self, **kwargs: Any) -> EdgyModel:
        """
        Returns the last record of a given queryset.
        """
        queryset: "QuerySet" = self.clone()
        if kwargs:
            return await queryset.filter(**kwargs).order_by("-id").get()

        rows = await queryset.order_by("-id").all()
        if rows:
            return rows[0]

    async def create(self, **kwargs: Any) -> EdgyModel:
        """
        Creates a record in a specific table.
        """
        kwargs = self.validate_kwargs(**kwargs)

        instance = self.model_class(**kwargs)
        instance = await instance.save(force_save=True, values=kwargs)
        return instance

    async def bulk_create(self, objs: List[Dict]) -> None:
        """
        Bulk creates records in a table
        """
        new_objs = [self.validate_kwargs(**obj) for obj in objs]

        expression = self.table.insert().values(new_objs)
        self.set_query_expression(expression)
        await self.database.execute(expression)

    async def bulk_update(self, objs: List[EdgyModel], fields: List[str]) -> None:
        """
        Bulk updates records in a table.

        A similar solution was suggested here: https://github.com/encode/orm/pull/148

        It is thought to be a clean approach to a simple problem so it was added here and
        refactored to be compatible with Saffier.
        """

        new_objs = []
        for obj in objs:
            new_obj = {}
            for key, value in obj.__dict__.items():
                if key in fields:
                    new_obj[key] = self.resolve_value(value)
            new_objs.append(new_obj)

        new_objs = [self.extract_values_from_field(obj, self.model_class) for obj in new_objs]

        pk = getattr(self.table.c, self.pkname)
        expression = self.table.update().where(pk == sqlalchemy.bindparam(self.pkname))
        kwargs = {field: sqlalchemy.bindparam(field) for obj in new_objs for field in obj.keys()}
        pks = [{self.pkname: getattr(obj, self.pkname)} for obj in objs]

        query_list = []
        for pk, value in zip(pks, new_objs):  # noqa
            query_list.append({**pk, **value})

        expression = expression.values(kwargs)
        self.set_query_expression(expression)
        await self.database.execute_many(str(expression), query_list)

    async def delete(self) -> None:
        expression = self.table.delete()
        for filter_clause in self.filter_clauses:
            expression = expression.where(filter_clause)

        self.set_query_expression(expression)
        await self.database.execute(expression)

    async def update(self, **kwargs: Any) -> int:
        """
        Updates a record in a specific table with the given kwargs.
        """
        extracted_fields = self.extract_values_from_field(kwargs, model_class=self.model_class)
        kwargs = self.update_auto_now_fields(extracted_fields, self.model_class.fields)
        expression = self.table.update().values(**kwargs)

        for filter_clause in self.filter_clauses:
            expression = expression.where(filter_clause)

        self.set_query_expression(expression)
        await self.database.execute(expression)

    async def get_or_create(
        self, defaults: Dict[str, Any], **kwargs: Any
    ) -> Tuple[EdgyModel, bool]:
        """
        Creates a record in a specific table or updates if already exists.
        """
        try:
            instance = await self.get(**kwargs)
            return instance, False
        except ObjectNotFound:
            kwargs.update(defaults)
            instance = await self.create(**kwargs)
            return instance, True

    async def update_or_create(
        self, defaults: Dict[str, Any], **kwargs: Any
    ) -> Tuple[EdgyModel, bool]:
        """
        Updates a record in a specific table or creates a new one.
        """
        try:
            instance = await self.get(**kwargs)
            await instance.update(**defaults)
            return instance, False
        except ObjectNotFound:
            kwargs.update(defaults)
            instance = await self.create(**kwargs)
            return instance, True

    async def contains(self, instance: EdgyModel) -> bool:
        """Returns true if the QuerySet contains the provided object.
        False if otherwise.
        """
        if getattr(instance, "pk", None) is None:
            raise ValueError("'obj' must be a model or reflect model instance.")
        return await self.filter(pk=instance.pk).exists()

    async def execute(self) -> Any:
        return await self.all()

    def __await__(
        self,
    ) -> Generator[Any, None, List[EdgyModel]]:
        return self.execute().__await__()

    def __class_getitem__(cls, *args: Any, **kwargs: Any) -> Any:
        return cls

    def __deepcopy__(self, memo: Any) -> Any:
        """Don't populate the QuerySet's cache."""
        obj = self.__class__()
        for k, v in self.__dict__.items():
            if k == "_cache":
                obj.__dict__[k] = None
            else:
                obj.__dict__[k] = copy.deepcopy(v, memo)
        return obj