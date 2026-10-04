from __future__ import annotations

import hashlib
import json
import os
import random
import shutil
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable
from pathlib import Path

from mediasensei.domain.images import DatasetSample, ExportResult, LeakageIssue, SplitStrategy
from mediasensei.infrastructure.images import phash_distance
from mediasensei.infrastructure.storage import ContentAddressedStore

_ALLOWED_SPLITS = ("train", "validation", "test")


class DuplicateDetector:
    def groups(
        self,
        samples: Iterable[DatasetSample],
        *,
        perceptual_threshold: int = 8,
    ) -> list[dict[str, object]]:
        records = sorted(samples, key=lambda sample: sample.asset_id)
        groups: list[dict[str, object]] = []
        exact: dict[str, list[DatasetSample]] = defaultdict(list)
        for sample in records:
            exact[sample.sha256].append(sample)
        for sha256, members in sorted(exact.items()):
            if len(members) > 1:
                groups.append(
                    {
                        "method": "exact",
                        "key": sha256,
                        "asset_ids": [member.asset_id for member in members],
                        "canonical_asset_id": members[0].asset_id,
                        "maximum_distance": 0,
                    }
                )

        candidates = [sample for sample in records if sample.perceptual_hash]
        parent = {sample.asset_id: sample.asset_id for sample in candidates}
        maximum_distance: dict[tuple[str, str], int] = {}

        def find(asset_id: str) -> str:
            while parent[asset_id] != asset_id:
                parent[asset_id] = parent[parent[asset_id]]
                asset_id = parent[asset_id]
            return asset_id

        def union(left: str, right: str) -> None:
            left_root, right_root = find(left), find(right)
            if left_root != right_root:
                parent[max(left_root, right_root)] = min(left_root, right_root)

        for index, left in enumerate(candidates):
            for right in candidates[index + 1 :]:
                if left.sha256 == right.sha256:
                    continue
                distance = phash_distance(left.perceptual_hash or "", right.perceptual_hash or "")
                if distance <= perceptual_threshold:
                    union(left.asset_id, right.asset_id)
                    maximum_distance[(left.asset_id, right.asset_id)] = distance

        visual: dict[str, list[DatasetSample]] = defaultdict(list)
        for sample in candidates:
            visual[find(sample.asset_id)].append(sample)
        for members in sorted(visual.values(), key=lambda group: group[0].asset_id):
            if len(members) < 2:
                continue
            ids = [member.asset_id for member in sorted(members, key=lambda item: item.asset_id)]
            distances = [
                distance
                for (left, right), distance in maximum_distance.items()
                if left in ids and right in ids
            ]
            groups.append(
                {
                    "method": "perceptual",
                    "key": hashlib.sha256("|".join(ids).encode()).hexdigest(),
                    "asset_ids": ids,
                    "canonical_asset_id": ids[0],
                    "maximum_distance": max(distances, default=0),
                }
            )
        return groups


class DatasetSplitter:
    def assign(
        self,
        samples: Iterable[DatasetSample],
        *,
        strategy: SplitStrategy = SplitStrategy.RANDOM,
        seed: int = 42,
        ratios: dict[str, float] | None = None,
    ) -> list[DatasetSample]:
        records = sorted(samples, key=lambda sample: sample.asset_id)
        if not records:
            return []
        proportions = _validate_ratios(ratios or {"train": 0.8, "validation": 0.1, "test": 0.1})
        if strategy == SplitStrategy.MANUAL:
            invalid = [sample.asset_id for sample in records if sample.split not in proportions]
            if invalid:
                raise ValueError(f"Manual split is missing for {len(invalid)} samples")
            return records
        if strategy == SplitStrategy.STRATIFIED:
            buckets: dict[str, list[DatasetSample]] = defaultdict(list)
            for sample in records:
                buckets[sample.label].append(sample)
            assigned: list[DatasetSample] = []
            for label, bucket in sorted(buckets.items()):
                assigned.extend(self._random(bucket, proportions, _derived_seed(seed, label)))
            return sorted(assigned, key=lambda sample: sample.asset_id)
        if strategy in {SplitStrategy.GROUP_AWARE, SplitStrategy.SOURCE_AWARE}:
            key_name = "group" if strategy == SplitStrategy.GROUP_AWARE else "source"
            groups: dict[str, list[DatasetSample]] = defaultdict(list)
            for sample in records:
                group_key = sample.group_key if key_name == "group" else sample.source_key
                groups[group_key or f"asset:{sample.asset_id}"].append(sample)
            return self._grouped(groups, proportions, seed)
        return self._random(records, proportions, seed)

    @staticmethod
    def _random(
        records: list[DatasetSample], proportions: dict[str, float], seed: int
    ) -> list[DatasetSample]:
        shuffled = records.copy()
        random.Random(seed).shuffle(shuffled)
        counts = _split_counts(len(shuffled), proportions)
        result: list[DatasetSample] = []
        offset = 0
        for split, count in counts.items():
            result.extend(sample.assigned(split) for sample in shuffled[offset : offset + count])
            offset += count
        return result

    @staticmethod
    def _grouped(
        groups: dict[str, list[DatasetSample]], proportions: dict[str, float], seed: int
    ) -> list[DatasetSample]:
        keys = sorted(groups)
        random.Random(seed).shuffle(keys)
        targets = _split_counts(sum(len(groups[key]) for key in keys), proportions)
        assigned_counts = {split: 0 for split in proportions}
        result: list[DatasetSample] = []
        for key in keys:
            candidates = sorted(
                proportions,
                key=lambda split: (
                    assigned_counts[split] - targets[split],
                    assigned_counts[split] / max(proportions[split], 0.000001),
                    split,
                ),
            )
            split = candidates[0]
            result.extend(sample.assigned(split) for sample in groups[key])
            assigned_counts[split] += len(groups[key])
        return sorted(result, key=lambda sample: sample.asset_id)


class LeakageDetector:
    def detect(
        self,
        samples: Iterable[DatasetSample],
        *,
        perceptual_threshold: int = 8,
    ) -> list[LeakageIssue]:
        records = sorted(samples, key=lambda sample: sample.asset_id)
        issues: list[LeakageIssue] = []
        for index, left in enumerate(records):
            if left.split is None:
                continue
            for right in records[index + 1 :]:
                if right.split is None or left.split == right.split:
                    continue
                if left.sha256 == right.sha256:
                    issues.append(_issue(left, right, "exact", 0))
                    continue
                if left.perceptual_hash and right.perceptual_hash:
                    distance = phash_distance(left.perceptual_hash, right.perceptual_hash)
                    if distance <= perceptual_threshold:
                        issues.append(_issue(left, right, "perceptual", distance))
        return issues


class MediaParquetExporter:
    exporter_id = "media-parquet"

    def __init__(self, store: ContentAddressedStore) -> None:
        self.store = store

    def export(
        self,
        samples: Iterable[DatasetSample],
        destination: str | Path,
        *,
        project_name: str = "MediaSensei dataset",
        split_seed: int = 42,
    ) -> ExportResult:
        records = sorted(samples, key=lambda sample: (sample.split or "", sample.asset_id))
        if not records:
            raise ValueError("Cannot export an empty dataset")
        if any(sample.split not in _ALLOWED_SPLITS for sample in records):
            raise ValueError("Every exported sample requires a train, validation, or test split")
        destination_path = Path(destination).expanduser().resolve()
        if destination_path.exists():
            raise FileExistsError(f"Export destination already exists: {destination_path}")
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(
            tempfile.mkdtemp(prefix=f".{destination_path.name}-", dir=destination_path.parent)
        )
        rows: list[dict[str, object]] = []
        try:
            for sample in records:
                split = sample.split or "unassigned"
                media_dir = temporary / "media" / split
                media_dir.mkdir(parents=True, exist_ok=True)
                safe_name = f"{sample.asset_id[:8]}-{Path(sample.filename).name}"
                exported_path = media_dir / safe_name
                shutil.copy2(self.store.resolve(sample.object_key), exported_path)
                rows.append(
                    {
                        "asset_id": sample.asset_id,
                        "sha256": sample.sha256,
                        "filename": sample.filename,
                        "label": sample.label,
                        "split": split,
                        "source_key": sample.source_key,
                        "group_key": sample.group_key,
                        "perceptual_hash": sample.perceptual_hash,
                        "media_path": exported_path.relative_to(temporary).as_posix(),
                    }
                )
            manifest_json = json.dumps(rows, sort_keys=True, separators=(",", ":"))
            manifest_hash = hashlib.sha256(manifest_json.encode()).hexdigest()
            (temporary / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "project": project_name,
                        "split_seed": split_seed,
                        "manifest_hash": manifest_hash,
                        "samples": rows,
                    },
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            _write_parquet(rows, temporary / "metadata.parquet")
            split_counts = dict(sorted(Counter(str(row["split"]) for row in rows).items()))
            (temporary / "dataset_card.md").write_text(
                _dataset_card(project_name, len(rows), split_counts, split_seed, manifest_hash),
                encoding="utf-8",
            )
            os.replace(temporary, destination_path)
            return ExportResult(
                path=str(destination_path),
                manifest_hash=manifest_hash,
                sample_count=len(rows),
                split_counts=split_counts,
            )
        except Exception:
            resolved_temp = temporary.resolve()
            if resolved_temp.parent == destination_path.parent and resolved_temp.name.startswith(
                f".{destination_path.name}-"
            ):
                shutil.rmtree(resolved_temp, ignore_errors=True)
            raise


def _write_parquet(rows: list[dict[str, object]], destination: Path) -> None:
    try:
        import pyarrow as pa  # type: ignore[import-untyped]
        import pyarrow.parquet as pq  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover - installation guidance
        raise RuntimeError(
            "Parquet export requires the 'data' extra: pip install mediasensei[data]"
        ) from error
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, destination, compression="zstd")


def _dataset_card(
    project_name: str,
    sample_count: int,
    split_counts: dict[str, int],
    split_seed: int,
    manifest_hash: str,
) -> str:
    split_lines = "\n".join(f"- {name}: {count}" for name, count in split_counts.items())
    return (
        f"# {project_name}\n\n"
        "Generated by MediaSensei from immutable content-addressed source objects.\n\n"
        f"- Samples: {sample_count}\n"
        f"- Deterministic split seed: {split_seed}\n"
        f"- Manifest SHA-256: `{manifest_hash}`\n\n"
        "## Splits\n\n"
        f"{split_lines}\n\n"
        "The export contains processed media plus `metadata.parquet` and `manifest.json`.\n"
    )


def _issue(left: DatasetSample, right: DatasetSample, kind: str, distance: int) -> LeakageIssue:
    return LeakageIssue(
        left_asset_id=left.asset_id,
        right_asset_id=right.asset_id,
        left_split=left.split or "",
        right_split=right.split or "",
        kind=kind,
        distance=distance,
    )


def _derived_seed(seed: int, value: str) -> int:
    digest = hashlib.sha256(f"{seed}:{value}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _validate_ratios(ratios: dict[str, float]) -> dict[str, float]:
    unknown = set(ratios) - set(_ALLOWED_SPLITS)
    if unknown:
        raise ValueError(f"Unknown splits: {', '.join(sorted(unknown))}")
    if set(ratios) != set(_ALLOWED_SPLITS):
        raise ValueError("Ratios must include train, validation, and test")
    if any(value < 0 for value in ratios.values()) or sum(ratios.values()) <= 0:
        raise ValueError("Split ratios must be non-negative and have a positive total")
    total = sum(ratios.values())
    return {split: ratios[split] / total for split in _ALLOWED_SPLITS}


def _split_counts(size: int, ratios: dict[str, float]) -> dict[str, int]:
    exact = {split: size * ratio for split, ratio in ratios.items()}
    counts = {split: int(value) for split, value in exact.items()}
    remainder = size - sum(counts.values())
    order = sorted(ratios, key=lambda split: (-(exact[split] - counts[split]), split))
    for split in order[:remainder]:
        counts[split] += 1
    return counts
