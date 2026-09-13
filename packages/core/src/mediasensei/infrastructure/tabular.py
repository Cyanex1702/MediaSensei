from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mediasensei.domain.jobs import ProcessorSpec, ResourceHints, ResourceLevel, WorkItem
from mediasensei.domain.tabular import (
    ColumnProfile,
    FilterOperator,
    TabularAnalysis,
    TabularExportResult,
    TabularFormat,
    TabularProfile,
    TabularQuery,
)
from mediasensei.infrastructure.storage import ContentAddressedStore

if TYPE_CHECKING:
    from mediasensei.infrastructure.catalog import Catalog
    from mediasensei.infrastructure.worker import ProcessorRegistry

duckdb: Any
pd: Any
pa: Any
pq: Any
_DATA_IMPORT_ERROR: ImportError | None
try:
    import duckdb as _duckdb
    import pandas as _pd  # type: ignore[import-untyped]
    import pyarrow as _pa  # type: ignore[import-untyped]
    import pyarrow.parquet as _pq  # type: ignore[import-untyped]

    duckdb, pd, pa, pq = _duckdb, _pd, _pa, _pq
    _DATA_IMPORT_ERROR = None
except ImportError as error:  # pragma: no cover - optional capability boundary
    duckdb = pd = pa = pq = None
    _DATA_IMPORT_ERROR = error


class TabularEngine:
    """DuckDB/Arrow engine for immutable imports and validated analytical queries."""

    def __init__(self, store: ContentAddressedStore) -> None:
        if _DATA_IMPORT_ERROR is not None:
            raise RuntimeError(
                "Tabular support requires the 'data' optional dependencies"
            ) from _DATA_IMPORT_ERROR
        self.store = store

    @staticmethod
    def analysis_key(
        source_sha256: str, source_format: TabularFormat, options: dict[str, Any] | None = None
    ) -> str:
        payload = json.dumps(
            {"sha256": source_sha256, "format": source_format.value, "options": options or {}},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    def inspect(
        self,
        source: str | Path,
        *,
        source_sha256: str,
        source_format: TabularFormat,
        options: dict[str, Any] | None = None,
    ) -> TabularAnalysis:
        clean_options = self._validated_options(options or {})
        table = self._read(Path(source), source_format, clean_options)
        if not table.column_names:
            raise ValueError("The imported table has no columns")
        normalized = self._store_parquet(table)
        profile = self._profile(table)
        return TabularAnalysis(
            analysis_key=self.analysis_key(source_sha256, source_format, clean_options),
            source_sha256=source_sha256,
            source_format=source_format,
            normalized_sha256=normalized.sha256,
            normalized_object_key=normalized.object_key,
            profile=profile,
            options=clean_options,
        )

    def query(
        self, normalized_object_key: str, query: TabularQuery | None = None
    ) -> dict[str, Any]:
        request = query or TabularQuery()
        if not 1 <= request.limit <= 1000:
            raise ValueError("Query limit must be between 1 and 1000")
        if request.offset < 0:
            raise ValueError("Query offset cannot be negative")
        path = self.store.resolve(normalized_object_key)
        with closing(duckdb.connect()) as connection:
            schema = connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
            columns = [str(row[0]) for row in schema]
            selected = list(request.visible_columns) or columns
            self._validate_columns(selected, columns)
            clauses, values = self._where(request, columns)
            select_sql = ", ".join(self._identifier(column) for column in selected)
            order_sql = ""
            if request.sort_by:
                self._validate_columns([request.sort_by], columns)
                order_sql = (
                    f" ORDER BY {self._identifier(request.sort_by)} "
                    f"{'DESC' if request.descending else 'ASC'} NULLS LAST"
                )
            where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            source_sql = "read_parquet(?)"
            parameters = [str(path), *values]
            total = int(
                _required_row(
                    connection.execute(
                        f"SELECT COUNT(*) FROM {source_sql}{where_sql}", parameters
                    ).fetchone()
                )[0]
            )
            rows = (
                connection.execute(
                    f"SELECT {select_sql} FROM {source_sql}{where_sql}{order_sql} LIMIT ? OFFSET ?",
                    [*parameters, request.limit, request.offset],
                )
                .to_arrow_table()
                .to_pylist()
            )
        return {
            "columns": selected,
            "rows": [_json_safe(row) for row in rows],
            "total": total,
            "limit": request.limit,
            "offset": request.offset,
        }

    def frequency(
        self, normalized_object_key: str, column: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 100:
            raise ValueError("Frequency limit must be between 1 and 100")
        path = self.store.resolve(normalized_object_key)
        with closing(duckdb.connect()) as connection:
            columns = [
                str(row[0])
                for row in connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
                ).fetchall()
            ]
            self._validate_columns([column], columns)
            quoted = self._identifier(column)
            rows = connection.execute(
                f"SELECT {quoted} AS value, COUNT(*) AS count "
                "FROM read_parquet(?) GROUP BY 1 ORDER BY count DESC, value NULLS LAST LIMIT ?",
                [str(path), limit],
            ).fetchall()
        return [{"value": _json_scalar(value), "count": int(count)} for value, count in rows]

    def to_pandas(self, normalized_object_key: str, query: TabularQuery | None = None):
        result = self.query(normalized_object_key, query or TabularQuery(limit=1000))
        return pd.DataFrame(result["rows"], columns=result["columns"])

    def export(
        self,
        normalized_object_key: str,
        destination: str | Path,
        export_format: TabularFormat,
        *,
        query: TabularQuery | None = None,
    ) -> TabularExportResult:
        target = Path(destination).expanduser().resolve()
        if target.exists():
            raise FileExistsError(f"Export destination already exists: {target}")
        target.parent.mkdir(parents=True, exist_ok=True)
        source = self.store.resolve(normalized_object_key)
        table = self._query_table(source, query)
        fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
        os.close(fd)
        temporary = Path(temp_name)
        try:
            self._write(table, temporary, export_format)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return TabularExportResult(
            format=export_format,
            path=str(target),
            sha256=_sha256(target),
            row_count=table.num_rows,
            column_count=table.num_columns,
        )

    def _query_table(self, source: Path, query: TabularQuery | None):
        if query is None:
            return pq.read_table(source)
        request = TabularQuery(
            filters=query.filters,
            search=query.search,
            sort_by=query.sort_by,
            descending=query.descending,
            visible_columns=query.visible_columns,
            limit=min(max(1, query.limit), 1_000_000),
            offset=query.offset,
        )
        # Exports intentionally use the same validated query compiler, with a larger bounded page.
        with closing(duckdb.connect()) as connection:
            columns = [
                str(row[0])
                for row in connection.execute(
                    "DESCRIBE SELECT * FROM read_parquet(?)", [str(source)]
                ).fetchall()
            ]
            selected = list(request.visible_columns) or columns
            self._validate_columns(selected, columns)
            clauses, values = self._where(request, columns)
            where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            order_sql = ""
            if request.sort_by:
                self._validate_columns([request.sort_by], columns)
                order_sql = f" ORDER BY {self._identifier(request.sort_by)} {'DESC' if request.descending else 'ASC'} NULLS LAST"
            selected_sql = ", ".join(self._identifier(item) for item in selected)
            return connection.execute(
                f"SELECT {selected_sql} FROM read_parquet(?){where_sql}{order_sql} LIMIT ? OFFSET ?",
                [str(source), *values, request.limit, request.offset],
            ).to_arrow_table()

    def _read(self, path: Path, source_format: TabularFormat, options: dict[str, Any]):
        if source_format == TabularFormat.XLSX:
            frame = pd.read_excel(path, sheet_name=options.get("sheet", 0))
            return pa.Table.from_pandas(frame, preserve_index=False)
        if source_format in {TabularFormat.SQLITE, TabularFormat.DUCKDB}:
            table_name = options.get("table") or self._first_table(path, source_format)
            if not isinstance(table_name, str) or not table_name:
                raise ValueError("A valid source table is required")
            if source_format == TabularFormat.SQLITE:
                with closing(sqlite3.connect(path)) as connection:
                    names = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        )
                    }
                    if table_name not in names:
                        raise ValueError(f"Unknown SQLite table: {table_name}")
                    return pa.Table.from_pandas(
                        pd.read_sql_query(
                            f"SELECT * FROM {self._identifier(table_name)}", connection
                        ),
                        preserve_index=False,
                    )
            with closing(duckdb.connect(str(path), read_only=True)) as connection:
                names = {row[0] for row in connection.execute("SHOW TABLES").fetchall()}
                if table_name not in names:
                    raise ValueError(f"Unknown DuckDB table: {table_name}")
                return connection.execute(
                    f"SELECT * FROM {self._identifier(table_name)}"
                ).to_arrow_table()
        readers: dict[TabularFormat, tuple[str, list[object]]] = {
            TabularFormat.CSV: ("read_csv_auto(?, header=true)", []),
            TabularFormat.TSV: ("read_csv_auto(?, header=true, delim='\\t')", []),
            TabularFormat.JSON: ("read_json_auto(?, format='array')", []),
            TabularFormat.JSONL: ("read_json_auto(?, format='newline_delimited')", []),
            TabularFormat.PARQUET: ("read_parquet(?)", []),
        }
        try:
            source_sql, extra = readers[source_format]
        except KeyError as error:
            raise ValueError(f"Unsupported tabular format: {source_format}") from error
        with closing(duckdb.connect()) as connection:
            return connection.execute(
                f"SELECT * FROM {source_sql}", [str(path), *extra]
            ).to_arrow_table()

    @staticmethod
    def _first_table(path: Path, source_format: TabularFormat) -> str:
        if source_format == TabularFormat.SQLITE:
            with closing(sqlite3.connect(path)) as connection:
                row = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name LIMIT 1"
                ).fetchone()
        else:
            with closing(duckdb.connect(str(path), read_only=True)) as connection:
                row = connection.execute("SHOW TABLES").fetchone()
        if row is None:
            raise ValueError("The database contains no importable tables")
        return str(row[0])

    def _store_parquet(self, table):
        fd, name = tempfile.mkstemp(suffix=".parquet", dir=self.store.temp_root)
        os.close(fd)
        path = Path(name)
        try:
            pq.write_table(table, path, compression="zstd", use_dictionary=True)
            return self.store.import_file(path)
        finally:
            path.unlink(missing_ok=True)

    def _profile(self, table) -> TabularProfile:
        with closing(duckdb.connect()) as connection:
            connection.register("source_table", table)
            columns: list[ColumnProfile] = []
            for field in table.schema:
                quoted = self._identifier(field.name)
                null_count, distinct_count = _required_row(
                    connection.execute(
                        f"SELECT COUNT(*) FILTER (WHERE {quoted} IS NULL), COUNT(DISTINCT {quoted}) FROM source_table"
                    ).fetchone()
                )
                minimum = maximum = mean = None
                try:
                    minimum, maximum = _required_row(
                        connection.execute(
                            f"SELECT MIN({quoted}), MAX({quoted}) FROM source_table"
                        ).fetchone()
                    )
                except duckdb.Error:
                    pass
                if (
                    pa.types.is_integer(field.type)
                    or pa.types.is_floating(field.type)
                    or pa.types.is_decimal(field.type)
                ):
                    mean = _required_row(
                        connection.execute(f"SELECT AVG({quoted}) FROM source_table").fetchone()
                    )[0]
                frequencies: tuple[dict[str, Any], ...] = ()
                if int(distinct_count) <= 100:
                    rows = connection.execute(
                        f"SELECT {quoted}, COUNT(*) AS count FROM source_table GROUP BY 1 ORDER BY count DESC, 1 NULLS LAST LIMIT 10"
                    ).fetchall()
                    frequencies = tuple(
                        {"value": _json_scalar(value), "count": int(count)} for value, count in rows
                    )
                columns.append(
                    ColumnProfile(
                        name=field.name,
                        arrow_type=str(field.type),
                        null_count=int(null_count),
                        distinct_count=int(distinct_count),
                        minimum=_json_scalar(minimum),
                        maximum=_json_scalar(maximum),
                        mean=float(mean) if mean is not None else None,
                        frequencies=frequencies,
                    )
                )
            sample = tuple(_json_safe(row) for row in table.slice(0, 20).to_pylist())
        return TabularProfile(table.num_rows, table.num_columns, tuple(columns), sample)

    @classmethod
    def _where(cls, query: TabularQuery, columns: list[str]) -> tuple[list[str], list[Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        operators = {
            FilterOperator.EQ: "=",
            FilterOperator.NE: "!=",
            FilterOperator.LT: "<",
            FilterOperator.LTE: "<=",
            FilterOperator.GT: ">",
            FilterOperator.GTE: ">=",
        }
        for item in query.filters:
            cls._validate_columns([item.column], columns)
            quoted = cls._identifier(item.column)
            if item.operator in operators:
                clauses.append(f"{quoted} {operators[item.operator]} ?")
                parameters.append(item.value)
            elif item.operator == FilterOperator.CONTAINS:
                clauses.append(f"CAST({quoted} AS VARCHAR) ILIKE ?")
                parameters.append(f"%{item.value}%")
            elif item.operator == FilterOperator.IN:
                values = list(item.value) if isinstance(item.value, (list, tuple)) else [item.value]
                if not values or len(values) > 1000:
                    raise ValueError("The 'in' filter requires 1 to 1000 values")
                clauses.append(f"{quoted} IN ({', '.join('?' for _ in values)})")
                parameters.extend(values)
            elif item.operator == FilterOperator.IS_NULL:
                clauses.append(f"{quoted} IS NULL")
            elif item.operator == FilterOperator.NOT_NULL:
                clauses.append(f"{quoted} IS NOT NULL")
            else:  # pragma: no cover - enum guards this
                raise ValueError(f"Unsupported filter operator: {item.operator}")
        if query.search:
            searchable = [
                f"CAST({cls._identifier(column)} AS VARCHAR) ILIKE ?" for column in columns
            ]
            clauses.append(f"({' OR '.join(searchable)})")
            parameters.extend([f"%{query.search}%"] * len(columns))
        return clauses, parameters

    @staticmethod
    def _validate_columns(requested: list[str], available: list[str]) -> None:
        unknown = [column for column in requested if column not in available]
        if unknown:
            raise ValueError(f"Unknown column(s): {', '.join(unknown)}")

    @staticmethod
    def _identifier(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    @staticmethod
    def _validated_options(options: dict[str, Any]) -> dict[str, Any]:
        unknown = set(options) - {"sheet", "table"}
        if unknown:
            raise ValueError(f"Unsupported import option(s): {', '.join(sorted(unknown))}")
        clean: dict[str, Any] = {}
        if "sheet" in options and options["sheet"] is not None:
            sheet = options["sheet"]
            if not isinstance(sheet, (str, int)):
                raise ValueError("XLSX sheet must be a name or zero-based index")
            clean["sheet"] = sheet
        if "table" in options and options["table"] is not None:
            table = options["table"]
            if not isinstance(table, str) or not table or len(table) > 200:
                raise ValueError("Database table must be a non-empty name")
            clean["table"] = table
        return clean

    @staticmethod
    def _write(table, path: Path, export_format: TabularFormat) -> None:
        if export_format in {TabularFormat.SQLITE, TabularFormat.DUCKDB}:
            path.unlink(missing_ok=True)
        if export_format == TabularFormat.PARQUET:
            pq.write_table(table, path, compression="zstd", use_dictionary=True)
            return
        frame = table.to_pandas()
        if export_format == TabularFormat.CSV:
            frame.to_csv(path, index=False, lineterminator="\n")
        elif export_format == TabularFormat.TSV:
            frame.to_csv(path, index=False, sep="\t", lineterminator="\n")
        elif export_format == TabularFormat.XLSX:
            frame.to_excel(path, index=False, engine="openpyxl")
        elif export_format == TabularFormat.JSON:
            frame.to_json(path, orient="records", date_format="iso", indent=2, force_ascii=False)
        elif export_format == TabularFormat.JSONL:
            frame.to_json(path, orient="records", lines=True, date_format="iso", force_ascii=False)
        elif export_format == TabularFormat.SQLITE:
            with closing(sqlite3.connect(path)) as connection:
                frame.to_sql("data", connection, index=False)
        elif export_format == TabularFormat.DUCKDB:
            with closing(duckdb.connect(str(path))) as connection:
                connection.register("export_data", table)
                connection.execute("CREATE TABLE data AS SELECT * FROM export_data")
        else:
            raise ValueError(f"Unsupported export format: {export_format}")


def analysis_to_dict(analysis: TabularAnalysis) -> dict[str, Any]:
    return _json_safe(asdict(analysis))


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return _json_scalar(value)


def _json_scalar(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.hex()
    return value


def _required_row(row: tuple[Any, ...] | None) -> tuple[Any, ...]:
    if row is None:
        raise RuntimeError("DuckDB returned no result row")
    return row


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def register_tabular_processors(registry: ProcessorRegistry, catalog: Catalog) -> None:
    engine = TabularEngine(ContentAddressedStore(catalog.workspace))

    def inspect_processor(item: WorkItem, parameters: dict[str, Any]) -> dict[str, Any]:
        source_format = TabularFormat(str(parameters["source_format"]))
        options = {
            key: parameters[key] for key in ("sheet", "table") if parameters.get(key) is not None
        }
        analysis = engine.inspect(
            engine.store.resolve(item.input_ref),
            source_sha256=item.input_hash,
            source_format=source_format,
            options=options,
        )
        catalog.upsert_tabular_analysis(analysis)
        dataset_id = None
        if parameters.get("project_id") and parameters.get("asset_id"):
            dataset_id = catalog.record_tabular_dataset(
                project_id=str(parameters["project_id"]),
                asset_id=str(parameters["asset_id"]),
                analysis_key=analysis.analysis_key,
                name=str(parameters.get("name") or "Untitled table"),
            )
        output = analysis_to_dict(analysis)
        output["dataset_id"] = dataset_id
        return output

    registry.register("tabular.inspect", inspect_processor)


def tabular_processor_spec() -> ProcessorSpec:
    return ProcessorSpec(
        id="tabular.inspect",
        version="1.0.0",
        deterministic=True,
        cacheable=True,
        resource_hints=ResourceHints(
            cpu=ResourceLevel.MEDIUM,
            memory=ResourceLevel.MEDIUM,
            disk=ResourceLevel.MEDIUM,
        ),
    )
