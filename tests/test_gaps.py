import pytest

from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c


def pkg(device, seq, key):
    return {
        "device_id": device,
        "seq": seq,
        "idempotency_key": key,
        "measurements": [{"metric": "temperature", "value": 1.0, "unit": "C"}],
    }


def test_gaps_default_response_fields(client):
    client.post("/api/v1/packages", json=pkg("gap-a", 1, "gap-a-1"))
    client.post("/api/v1/packages", json=pkg("gap-a", 4, "gap-a-4"))
    body = client.get("/api/v1/devices/gap-a/gaps").json()
    assert body["committed_upto"] == 1
    assert body["next_expected"] == 2
    assert body["buffered_seqs"] == [4]
    assert body["gap_count"] == 2
    assert body["gaps"] == [2, 3]
    assert body["limit"] == 1000
    assert body["offset"] == 0


def test_gaps_huge_sparse_gap(client):
    # 先提交 seq=1，再缓冲 seq=100000000：缺口近一亿个，必须按区间计算
    client.post("/api/v1/packages", json=pkg("gap-b", 1, "gap-b-1"))
    client.post("/api/v1/packages", json=pkg("gap-b", 100000000, "gap-b-2"))
    body = client.get("/api/v1/devices/gap-b/gaps").json()
    assert body["buffered_seqs"] == [100000000]
    assert body["gap_count"] == 99999998
    assert body["gaps"] == list(range(2, 1002))  # 默认 limit=1000
    # 深翻页：直接落到缺口深处，不逐个遍历被跳过的缺口
    deep = client.get(
        "/api/v1/devices/gap-b/gaps",
        params={"limit": 5, "offset": 99999990},
    ).json()
    assert deep["gap_count"] == 99999998
    assert deep["gaps"] == [99999992, 99999993, 99999994, 99999995, 99999996]
    # 翻到末尾之外：本页为空，总数仍准确
    tail = client.get(
        "/api/v1/devices/gap-b/gaps",
        params={"limit": 10, "offset": 99999998},
    ).json()
    assert tail["gap_count"] == 99999998
    assert tail["gaps"] == []


def test_gaps_pagination_across_intervals(client):
    # 缓冲 4、6、9 -> 缺口区间 [2,3]、[5,5]、[7,8]，分页跨区间
    client.post("/api/v1/packages", json=pkg("gap-c", 1, "gap-c-1"))
    for seq in (4, 6, 9):
        client.post("/api/v1/packages", json=pkg("gap-c", seq, f"gap-c-{seq}"))
    body = client.get("/api/v1/devices/gap-c/gaps").json()
    assert body["buffered_seqs"] == [4, 6, 9]
    assert body["gap_count"] == 5
    assert body["gaps"] == [2, 3, 5, 7, 8]
    pages = [
        client.get(
            "/api/v1/devices/gap-c/gaps", params={"limit": 2, "offset": off}
        ).json()["gaps"]
        for off in (0, 2, 4, 6)
    ]
    assert pages == [[2, 3], [5, 7], [8], []]


def test_gaps_no_buffer(client):
    client.post("/api/v1/packages", json=pkg("gap-d", 1, "gap-d-1"))
    body = client.get("/api/v1/devices/gap-d/gaps").json()
    assert body["buffered_seqs"] == []
    assert body["gap_count"] == 0
    assert body["gaps"] == []


def test_gaps_unknown_device_404(client):
    assert client.get("/api/v1/devices/gap-nope/gaps").status_code == 404


def test_gaps_pagination_params_validated(client):
    client.post("/api/v1/packages", json=pkg("gap-e", 1, "gap-e-1"))
    assert (
        client.get("/api/v1/devices/gap-e/gaps", params={"limit": 0}).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/devices/gap-e/gaps", params={"limit": 10001}
        ).status_code
        == 422
    )
    assert (
        client.get("/api/v1/devices/gap-e/gaps", params={"offset": -1}).status_code
        == 422
    )
    assert (
        client.get(
            "/api/v1/devices/gap-e/gaps", params={"limit": 10000}
        ).status_code
        == 200
    )
