import shutil
from pathlib import Path

import pytest

from lambdas.ingest import handler as h

SAMPLE = Path("sample-data/2026-11-07_14-53-58.csv")
KEY = "raw/vehicle_id=mazda6/date=2026-11-07/trip.csv"


class FakeS3:
    def __init__(self, src=SAMPLE):
        self.src = src

    def download_file(self, bucket, key, dest):
        shutil.copy(self.src, dest)


class FakeTable:
    def __init__(self):
        self.items = {}

    def get_item(self, Key):
        it = self.items.get((Key["PK"], Key["SK"]))
        return {"Item": it} if it else {}

    def batch_writer(self, overwrite_by_pkeys=None):
        t = self

        class W:
            def __enter__(s): return s
            def __exit__(s, *a): return False
            def put_item(s, Item): t.items[(Item["PK"], Item["SK"])] = Item
        return W()

    def put_item(self, Item, ConditionExpression=None):
        k = (Item["PK"], Item["SK"])
        if k in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[k] = Item


def test_ingest_writes_summaries_and_trip(tmp_path):
    t = FakeTable()
    res = h.ingest_object("b", KEY, s3=FakeS3(), table=t, tmp_dir=str(tmp_path))
    assert res["status"] == "ingested"
    sks = [sk for _, sk in t.items]
    assert sum(s.startswith("TRIP#") for s in sks) == 1
    assert sum(s.startswith("SUM#") for s in sks) == res["params"] > 5
    assert not list(tmp_path.iterdir())  # temp file cleaned up


def test_duplicate_upload_is_noop(tmp_path):
    t = FakeTable()
    h.ingest_object("b", KEY, s3=FakeS3(), table=t, tmp_dir=str(tmp_path))
    n = len(t.items)
    res = h.ingest_object("b", KEY, s3=FakeS3(), table=t, tmp_dir=str(tmp_path))
    assert res["status"] == "duplicate" and len(t.items) == n


def test_bad_key_rejected(tmp_path):
    with pytest.raises(h.BadKey):
        h.ingest_object("b", "raw/oops.csv", s3=FakeS3(), table=FakeTable(), tmp_dir=str(tmp_path))


def test_non_car_scanner_rejected(tmp_path):
    a30m = Path("sample-data/a30m_accessory_mode_2026-10-31.csv")
    with pytest.raises(h.UnsupportedSource):
        h.ingest_object("b", KEY, s3=FakeS3(a30m), table=FakeTable(), tmp_dir=str(tmp_path))


def test_lambda_handler_decodes_s3_event_key(monkeypatch):
    monkeypatch.setattr(h, "ingest_object", lambda bucket, key: {"key": key})
    ev = {"Records": [{"s3": {"bucket": {"name": "b"},
                              "object": {"key": "raw/vehicle_id=my+car/date=2026-11-07/t%3D1.csv"}}}]}
    assert h.handler(ev) == [{"key": "raw/vehicle_id=my car/date=2026-11-07/t=1.csv"}]
