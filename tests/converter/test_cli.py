# pattern: test file

import pytest
import hashlib

from pipeline.converter.cli import _build_parser, _parse_shard, _in_shard


class TestParseShard:
    def test_none_returns_none(self):
        assert _parse_shard(None) is None

    def test_valid_zero_of_one(self):
        assert _parse_shard("0/1") == (0, 1)

    def test_valid_three_of_four(self):
        assert _parse_shard("3/4") == (3, 4)

    @pytest.mark.parametrize("bad", ["", "/", "0", "1/2/3", "a/b", "-1/4", "4/4", "5/4", "0/0", "0/-1"])
    def test_malformed_raises(self, bad):
        with pytest.raises(ValueError):
            _parse_shard(bad)


class TestInShard:
    def test_no_shard_always_true(self):
        assert _in_shard("abc123" + "0" * 58, None) is True

    def test_deterministic_bucket_assignment(self):
        # Two different delivery_ids; each goes to one and only one shard out of N.
        d1 = "00000000" + "0" * 56  # bucket 0 mod any N
        d2 = "ffffffff" + "0" * 56  # bucket (2**32 - 1) mod N

        n = 4
        shards_hit_d1 = [i for i in range(n) if _in_shard(d1, (i, n))]
        shards_hit_d2 = [i for i in range(n) if _in_shard(d2, (i, n))]

        assert len(shards_hit_d1) == 1
        assert len(shards_hit_d2) == 1

    def test_distribution_across_shards(self):
        # 100 random-ish delivery_ids distributed across 4 shards -> each shard sees some.
        ids = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(100)]
        counts = [sum(1 for d in ids if _in_shard(d, (i, 4))) for i in range(4)]
        # Each of the 4 shards gets at least one id; total = 100.
        assert sum(counts) == 100
        assert all(c > 0 for c in counts)


class TestBuildParser:
    def test_defaults(self):
        parser = _build_parser()
        args = parser.parse_args([])
        assert args.limit is None
        assert args.shard is None
        assert args.include_failed is False

    def test_all_flags(self):
        parser = _build_parser()
        args = parser.parse_args(["--limit", "10", "--shard", "1/2", "--include-failed"])
        assert args.limit == 10
        assert args.shard == "1/2"
        assert args.include_failed is True
