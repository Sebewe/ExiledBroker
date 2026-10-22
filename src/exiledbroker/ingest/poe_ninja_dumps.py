"""poe.ninja historical economy dumps (CC BY-SA; see https://poe.ninja/poe1/data).

One zip per league, each holding daily `<League>.items.csv` / `<League>.currency.csv`
files (semicolon separated) for that league plus Standard, Hardcore and private leagues.
We keep the challenge league's own files, optionally its hardcore twin, and convert
them to one Parquet file per league and kind.
"""

import io
import os
import shutil
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import quote

import polars as pl

from exiledbroker.config import Settings
from exiledbroker.ingest.files import read_json, tmp_path_for, write_json_atomic
from exiledbroker.ingest.http import PoliteClient, ProgressFn, download, is_complete, meta_path_for
from exiledbroker.normalize.leagues import LeagueWindow, classify_league, league_id, slugify

GAME = "poe1"
# Bump when the Parquet output changes so existing files are rebuilt.
PARSER_VERSION = 2
KINDS = ("items", "currency")

ITEM_SCHEMA = {
    "league": pl.String,
    "date": pl.Date,
    "ninja_id": pl.Int64,
    "type": pl.String,
    "name": pl.String,
    "base_type": pl.String,
    "variant": pl.String,
    "links": pl.String,
    "chaos_value": pl.Float64,
    "confidence": pl.String,
}
CURRENCY_SCHEMA = {
    "league": pl.String,
    "date": pl.Date,
    "get": pl.String,
    "pay": pl.String,
    "value": pl.Float64,
    "confidence": pl.String,
}
SCHEMAS = {"items": ITEM_SCHEMA, "currency": CURRENCY_SCHEMA}
# Raw headers as published; columns are read by position, so check these first.
HEADERS = {
    "items": "League;Date;Id;Type;Name;BaseType;Variant;Links;Value;Confidence",
    "currency": "League;Date;Get;Pay;Value;Confidence",
}


@dataclass(frozen=True)
class DumpInfo:
    league_name: str
    zip_name: str
    min_date: date
    max_date: date | None  # None for a league still running (no dump yet)
    kind: str

    @property
    def league_id(self) -> str:
        return league_id(GAME, self.league_name)

    @property
    def slug(self) -> str:
        return slugify(self.league_name)


def index_url(settings: Settings) -> str:
    return f"{settings.poe_ninja_base_url}/poe1/api/data/dumps"


def dump_url(settings: Settings, league_name: str) -> str:
    return f"{settings.poe_ninja_base_url}/poe1/api/data/dumps/dump?name={quote(league_name)}"


def parse_index(raw: list[dict]) -> list[DumpInfo]:
    windows = [
        LeagueWindow(
            d["leagueName"],
            date.fromisoformat(d["minDate"][:10]),
            date.fromisoformat(d["maxDate"][:10]),
        )
        for d in raw
    ]
    return [
        DumpInfo(w.name, d["zipName"], w.start, w.end, classify_league(w, windows))
        for w, d in zip(windows, raw)
    ]


def fetch_index(client: PoliteClient, settings: Settings) -> list[DumpInfo]:
    """Fetch the dump listing (one small request) and keep a raw copy."""
    raw = client.get_json(index_url(settings))
    write_json_atomic(settings.dumps_raw_dir / "index.json", raw)
    return parse_index(raw)


def cached_index(settings: Settings) -> list[DumpInfo] | None:
    raw = read_json(settings.dumps_raw_dir / "index.json")
    return parse_index(raw) if raw else None


def zip_path(settings: Settings, dump: DumpInfo) -> Path:
    return settings.dumps_raw_dir / dump.zip_name


def parquet_path(settings: Settings, dump: DumpInfo, kind: str) -> Path:
    return settings.dumps_processed_dir / kind / f"{dump.slug}.parquet"


def verify_zip(path: Path) -> None:
    with zipfile.ZipFile(path) as zf:
        bad = zf.testzip()
    if bad is not None:
        raise zipfile.BadZipFile(f"{path.name}: corrupt member {bad}")


def download_dump(
    client: PoliteClient, settings: Settings, dump: DumpInfo, progress: ProgressFn | None = None
):
    return download(
        client,
        dump_url(settings, dump.league_name),
        zip_path(settings, dump),
        verify=verify_zip,
        progress=progress,
    )


def member_names(dump: DumpInfo, kind: str, include_hardcore: bool) -> list[str]:
    names = [f"{dump.league_name}.{kind}.csv"]
    if include_hardcore:
        names += [f"Hardcore {dump.league_name}.{kind}.csv", f"HC {dump.league_name}.{kind}.csv"]
    return names


def copy_clean_csv(fin, fout, member: str, kind: str) -> int:
    """Copy one CSV member, keeping only well-formed rows. Returns rows dropped.

    poe.ninja doesn't quote fields, so an item name containing a line break (e.g.
    Necropolis coffins) spills one record over several lines. A row is kept only if it
    starts with the member's league name and has the right number of fields.
    """
    text = io.TextIOWrapper(fin, encoding="utf-8-sig", newline="")
    header = text.readline().rstrip("\r\n")
    if header != HEADERS[kind]:
        raise ValueError(f"{member}: unexpected header {header!r}")
    league = member.rsplit(f".{kind}.csv", 1)[0]
    prefix = f"{league};"
    separators = HEADERS[kind].count(";")
    dropped = 0
    fout.write(header + "\n")
    for line in text:
        line = line.rstrip("\r\n")
        if line.startswith(prefix) and line.count(";") == separators:
            fout.write(line + "\n")
        elif line:
            dropped += 1
    return dropped


def extract_dump(settings: Settings, dump: DumpInfo, include_hardcore: bool = False) -> list[Path]:
    """Convert a downloaded dump zip to Parquet. Skips outputs already built from this zip."""
    src = zip_path(settings, dump)
    if not is_complete(src):
        raise FileNotFoundError(f"{src} is not downloaded yet")
    # Identify the zip by its upstream identity, not local mtime, so re-downloading
    # the same file does not trigger a rebuild.
    source = read_json(meta_path_for(src)) or {}
    written = []

    with zipfile.ZipFile(src) as zf:
        available = set(zf.namelist())
        for kind in KINDS:
            members = [m for m in member_names(dump, kind, include_hardcore) if m in available]
            if f"{dump.league_name}.{kind}.csv" not in members:
                raise ValueError(f"{src.name} has no {dump.league_name}.{kind}.csv")

            out = parquet_path(settings, dump, kind)
            fingerprint = {
                "parser_version": PARSER_VERSION,
                "zip_size": source.get("size"),
                "zip_etag": source.get("etag"),
                "zip_last_modified": source.get("last_modified"),
                "members": members,
            }
            sidecar = out.with_name(out.name + ".meta.json")
            if out.exists() and read_json(sidecar) == fingerprint:
                continue

            # Stream members to disk first so large CSVs never sit fully in memory.
            work = settings.data_dir / "tmp" / f"{dump.slug}-{kind}"
            tmp = tmp_path_for(out)
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            try:
                frames = []
                dropped = 0
                for m in members:
                    csv = work / m
                    with zf.open(m) as fin, open(csv, "w", encoding="utf-8") as fout:
                        try:
                            dropped += copy_clean_csv(fin, fout, m, kind)
                        except ValueError as e:
                            raise ValueError(f"{src.name}/{e}") from None
                    lf = pl.scan_csv(
                        csv, separator=";", has_header=False, skip_rows=1, schema=SCHEMAS[kind]
                    )
                    frames.append(
                        lf.with_columns(
                            pl.lit(dump.league_id).alias("league_id"),
                            (pl.col("league") != dump.league_name).alias("hardcore"),
                        )
                    )
                out.parent.mkdir(parents=True, exist_ok=True)
                pl.concat(frames).sink_parquet(tmp)
                os.replace(tmp, out)
                # Malformed rows are recorded next to the output, not part of the fingerprint.
                write_json_atomic(sidecar, fingerprint)
                write_json_atomic(out.with_name(out.name + ".dropped.json"), {"rows": dropped})
                written.append(out)
            finally:
                shutil.rmtree(work, ignore_errors=True)
                tmp.unlink(missing_ok=True)
    return written


def is_extracted(settings: Settings, dump: DumpInfo) -> bool:
    return all(parquet_path(settings, dump, k).exists() for k in KINDS)
