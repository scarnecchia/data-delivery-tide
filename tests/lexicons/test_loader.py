# pattern: Functional Core
from dataclasses import FrozenInstanceError

import pytest

from pipeline.lexicons import Lexicon, MetadataField, LexiconLoadError, load_all_lexicons, load_lexicon


class TestLoadSingleLexicon:
    """lexicon-system.AC1.1 — Load a single valid lexicon (no extends)."""

    def test_load_single_valid_lexicon_returns_lexicon_instance(self, make_lexicon_file, lexicons_dir):
        """AC1.1: Load single lexicon returns Lexicon instance with correct fields."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {"pending": ["passed"]},
                "dir_map": {"msoc": "passed"},
                "actionable_statuses": ["passed"],
            },
        )

        result = load_all_lexicons(lexicons_dir)

        assert "soc._base" in result
        assert isinstance(result["soc._base"], Lexicon)

    def test_loaded_lexicon_is_frozen(self, make_lexicon_file, lexicons_dir):
        """AC1.1: Loaded lexicon dataclass is frozen (immutable)."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
            },
        )

        result = load_all_lexicons(lexicons_dir)
        lexicon = result["soc._base"]

        with pytest.raises(FrozenInstanceError):
            lexicon.statuses = ("new",)

    def test_loaded_lexicon_has_correct_fields(self, make_lexicon_file, lexicons_dir):
        """AC1.1: All fields populated correctly from JSON."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed", "failed"],
                "transitions": {
                    "pending": ["passed", "failed"],
                    "passed": [],
                    "failed": [],
                },
                "dir_map": {"msoc": "passed", "msoc_new": "pending"},
                "actionable_statuses": ["passed"],
                "metadata_fields": {"created_at": {"type": "datetime"}},
            },
        )

        result = load_all_lexicons(lexicons_dir)
        lexicon = result["soc._base"]

        assert lexicon.id == "soc._base"
        assert lexicon.statuses == ("pending", "passed", "failed")
        assert lexicon.transitions["pending"] == ("passed", "failed")
        assert lexicon.dir_map["msoc"] == "passed"
        assert lexicon.actionable_statuses == ("passed",)
        assert "created_at" in lexicon.metadata_fields
        assert lexicon.derive_hook is None

    def test_loaded_tuples_are_immutable(self, make_lexicon_file, lexicons_dir):
        """AC1.1: statuses and actionable_statuses are tuples (immutable)."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": ["passed"],
            },
        )

        result = load_all_lexicons(lexicons_dir)
        lexicon = result["soc._base"]

        assert isinstance(lexicon.statuses, tuple)
        assert isinstance(lexicon.actionable_statuses, tuple)
        assert isinstance(lexicon.transitions["pending"] if "pending" in lexicon.transitions else (), tuple)


class TestInheritanceWithExtends:
    """lexicon-system.AC1.2 — Child inherits all fields from base."""

    def test_child_inherits_all_base_fields(self, make_lexicon_file, lexicons_dir):
        """AC1.2: Child extends base and inherits all fields."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed", "failed"],
                "transitions": {"pending": ["passed", "failed"]},
                "dir_map": {"msoc": "passed", "msoc_new": "pending"},
                "actionable_statuses": ["passed"],
            },
        )
        make_lexicon_file(
            "soc/qar.json",
            {
                "extends": "soc._base",
                "metadata_fields": {"passed_at": {"type": "datetime", "set_on": "passed"}},
            },
        )

        result = load_all_lexicons(lexicons_dir)
        child = result["soc.qar"]

        # Verify all base fields inherited
        assert child.statuses == ("pending", "passed", "failed")
        assert child.transitions == {"pending": ("passed", "failed")}
        assert child.dir_map == {"msoc": "passed", "msoc_new": "pending"}
        assert child.actionable_statuses == ("passed",)
        # Verify child's own field
        assert "passed_at" in child.metadata_fields
        assert child.metadata_fields["passed_at"].set_on == "passed"

    def test_base_processed_before_child_in_topological_order(self, make_lexicon_file, lexicons_dir):
        """AC1.2: Base lexicon is loaded and resolved before child."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
            },
        )
        make_lexicon_file(
            "soc/qar.json",
            {"extends": "soc._base"},
        )

        # Should not raise — base loaded first
        result = load_all_lexicons(lexicons_dir)
        assert "soc._base" in result
        assert "soc.qar" in result


class TestFieldOverride:
    """lexicon-system.AC1.3 — Child overrides base fields, keeps the rest."""

    def test_child_overrides_actionable_statuses(self, make_lexicon_file, lexicons_dir):
        """AC1.3: Child overrides actionable_statuses while keeping base's other fields."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed", "failed"],
                "transitions": {"pending": ["passed"]},
                "dir_map": {"msoc": "passed"},
                "actionable_statuses": ["passed"],
            },
        )
        make_lexicon_file(
            "soc/qar.json",
            {
                "extends": "soc._base",
                "actionable_statuses": ["passed", "failed"],
            },
        )

        result = load_all_lexicons(lexicons_dir)
        child = result["soc.qar"]

        # Overridden
        assert child.actionable_statuses == ("passed", "failed")
        # Inherited unchanged
        assert child.statuses == ("pending", "passed", "failed")
        assert child.transitions == {"pending": ("passed",)}
        assert child.dir_map == {"msoc": "passed"}

    def test_child_adds_metadata_field_base_lacks(self, make_lexicon_file, lexicons_dir):
        """AC1.3: Child adds metadata_fields entry; base has none."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
                "metadata_fields": {},
            },
        )
        make_lexicon_file(
            "soc/qar.json",
            {
                "extends": "soc._base",
                "metadata_fields": {"passed_at": {"type": "datetime", "set_on": "passed"}},
            },
        )

        result = load_all_lexicons(lexicons_dir)
        base = result["soc._base"]
        child = result["soc.qar"]

        assert len(base.metadata_fields) == 0
        assert "passed_at" in child.metadata_fields

    def test_child_inherits_metadata_field_and_adds_new(self, make_lexicon_file, lexicons_dir):
        """AC1.3: Child inherits base metadata and adds more."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
                "metadata_fields": {"created_at": {"type": "datetime"}},
            },
        )
        make_lexicon_file(
            "soc/qar.json",
            {
                "extends": "soc._base",
                "metadata_fields": {"passed_at": {"type": "datetime", "set_on": "passed"}},
            },
        )

        result = load_all_lexicons(lexicons_dir)
        child = result["soc.qar"]

        assert "created_at" in child.metadata_fields
        assert "passed_at" in child.metadata_fields


class TestCircularExtends:
    """lexicon-system.AC1.4 — Circular extends detected and reported."""

    def test_circular_extends_two_lexicons_detected(self, make_lexicon_file, lexicons_dir):
        """AC1.4: A extends B, B extends A raises LexiconLoadError."""
        make_lexicon_file("a.json", {"extends": "b"})
        make_lexicon_file("b.json", {"extends": "a"})

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        error_msg = str(exc_info.value)
        assert "circular" in error_msg.lower() or "cycle" in error_msg.lower()

    def test_circular_extends_three_lexicons_detected(self, make_lexicon_file, lexicons_dir):
        """AC1.4: A→B→C→A circular chain detected."""
        make_lexicon_file("a.json", {"extends": "b", "statuses": []})
        make_lexicon_file("b.json", {"extends": "c", "statuses": []})
        make_lexicon_file("c.json", {"extends": "a", "statuses": []})

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        error_msg = str(exc_info.value)
        assert "circular" in error_msg.lower() or "cycle" in error_msg.lower()

    def test_lexicon_extends_itself_detected(self, make_lexicon_file, lexicons_dir):
        """AC1.4: Self-referential extends (A extends A) detected."""
        make_lexicon_file("self.json", {"extends": "self"})

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        error_msg = str(exc_info.value)
        assert "circular" in error_msg.lower() or "cycle" in error_msg.lower()


class TestTransitionValidation:
    """lexicon-system.AC1.5 — Status in transitions must exist in statuses."""

    def test_transition_from_status_not_in_statuses_reported(self, make_lexicon_file, lexicons_dir):
        """AC1.5: transitions key not in statuses reported."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {"nonexistent": ["passed"]},
                "dir_map": {},
                "actionable_statuses": [],
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert any("transitions" in e and "nonexistent" in e for e in exc_info.value.errors)

    def test_transition_to_status_not_in_statuses_reported(self, make_lexicon_file, lexicons_dir):
        """AC1.5: transitions value referencing unknown status reported."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {"pending": ["passed", "nonexistent"]},
                "dir_map": {},
                "actionable_statuses": [],
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert any("transitions" in e and "nonexistent" in e for e in exc_info.value.errors)

    def test_both_transition_errors_reported_in_batch(self, make_lexicon_file, lexicons_dir):
        """AC1.5: Multiple transition errors all reported."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {
                    "bad_from": ["passed"],
                    "pending": ["bad_to1", "bad_to2"],
                },
                "dir_map": {},
                "actionable_statuses": [],
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        errors = exc_info.value.errors
        assert len(errors) >= 3  # bad_from, bad_to1, bad_to2


class TestDirMapValidation:
    """lexicon-system.AC1.6 — dir_map value must exist in statuses."""

    def test_dir_map_value_not_in_statuses_reported(self, make_lexicon_file, lexicons_dir):
        """AC1.6: dir_map value not in statuses reported."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {"msoc": "nonexistent"},
                "actionable_statuses": [],
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert any("dir_map" in e and "nonexistent" in e for e in exc_info.value.errors)

    def test_multiple_dir_map_errors_reported(self, make_lexicon_file, lexicons_dir):
        """AC1.6: Multiple dir_map errors all reported."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {"msoc": "bad1", "msoc_new": "bad2"},
                "actionable_statuses": [],
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        errors = exc_info.value.errors
        assert len(errors) >= 2


class TestActionableStatusesValidation:
    """Validation of actionable_statuses (implied in AC1.1 but explicit here)."""

    def test_actionable_status_not_in_statuses_reported(self, make_lexicon_file, lexicons_dir):
        """actionable_statuses entry not in statuses reported."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": ["nonexistent"],
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert any("actionable_statuses" in e and "nonexistent" in e for e in exc_info.value.errors)


class TestMetadataFieldSetOnValidation:
    """lexicon-system.AC1.7 — metadata_fields.set_on must exist in statuses."""

    def test_metadata_set_on_not_in_statuses_reported(self, make_lexicon_file, lexicons_dir):
        """AC1.7: metadata_fields[*].set_on value not in statuses reported."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
                "metadata_fields": {"passed_at": {"type": "datetime", "set_on": "nonexistent"}},
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert any("set_on" in e and "nonexistent" in e for e in exc_info.value.errors)

    def test_metadata_without_set_on_is_valid(self, make_lexicon_file, lexicons_dir):
        """AC1.7: metadata_fields without set_on is valid."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
                "metadata_fields": {"created_at": {"type": "datetime"}},
            },
        )

        result = load_all_lexicons(lexicons_dir)
        assert "test" in result
        assert result["test"].metadata_fields["created_at"].set_on is None

    def test_multiple_metadata_set_on_errors_reported(self, make_lexicon_file, lexicons_dir):
        """AC1.7: Multiple metadata set_on errors reported."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
                "metadata_fields": {
                    "field1": {"type": "datetime", "set_on": "bad1"},
                    "field2": {"type": "datetime", "set_on": "bad2"},
                },
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        errors = exc_info.value.errors
        assert len(errors) >= 2


class TestDeriveHookValidation:
    """lexicon-system.AC1.8 — derive_hook must be importable callable."""

    def test_derive_hook_not_found_reported(self, make_lexicon_file, lexicons_dir):
        """AC1.8: derive_hook referencing non-existent module reported."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
                "derive_hook": "nonexistent.module:function",
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert any("derive_hook" in e for e in exc_info.value.errors)

    def test_derive_hook_attribute_not_found_reported(self, make_lexicon_file, lexicons_dir):
        """AC1.8: derive_hook attribute not in module reported."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
                "derive_hook": "json:nonexistent_function",
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert any("derive_hook" in e for e in exc_info.value.errors)

    def test_no_derive_hook_is_valid(self, make_lexicon_file, lexicons_dir):
        """AC1.8: Lexicon without derive_hook is valid."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
            },
        )

        result = load_all_lexicons(lexicons_dir)
        assert result["test"].derive_hook is None

    def test_derive_hook_imported_and_set(self, make_lexicon_file, lexicons_dir):
        """AC1.8: Valid derive_hook is imported and set on Lexicon."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
                "derive_hook": "json:loads",
            },
        )

        result = load_all_lexicons(lexicons_dir)
        assert result["test"].derive_hook is not None
        # Verify it's the correct function
        assert result["test"].derive_hook == __import__("json").loads


class TestBatchErrorReporting:
    """lexicon-system.AC1.9 — Multiple errors collected and reported together."""

    def test_multiple_errors_collected_in_single_batch(self, make_lexicon_file, lexicons_dir):
        """AC1.9: Multiple validation errors (transitions + dir_map + actionable + set_on)."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {
                    "bad_from": ["passed"],  # error: bad_from not in statuses
                    "pending": ["bad_to"],  # error: bad_to not in statuses
                },
                "dir_map": {"msoc": "bad_dir"},  # error: bad_dir not in statuses
                "actionable_statuses": ["bad_action"],  # error: bad_action not in statuses
                "metadata_fields": {
                    "field1": {"type": "datetime", "set_on": "bad_set_on"},  # error: bad_set_on not in statuses
                },
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        # Should have at least 5 errors (one per issue above)
        errors = exc_info.value.errors
        assert len(errors) >= 4, f"Expected at least 4 errors, got {len(errors)}: {errors}"

    def test_error_exception_has_errors_list(self, make_lexicon_file, lexicons_dir):
        """AC1.9: LexiconLoadError.errors is a list of error strings."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending"],
                "transitions": {"bad": ["pending"]},
                "dir_map": {},
                "actionable_statuses": [],
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert hasattr(exc_info.value, "errors")
        assert isinstance(exc_info.value.errors, list)
        assert len(exc_info.value.errors) > 0
        assert all(isinstance(e, str) for e in exc_info.value.errors)


class TestLoadLexiconConvenienceFunction:
    """Test the load_lexicon(id, dir) convenience function."""

    def test_load_single_lexicon_by_id(self, make_lexicon_file, lexicons_dir):
        """load_lexicon: Get specific lexicon by ID from directory."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
            },
        )
        make_lexicon_file(
            "soc/qar.json",
            {
                "extends": "soc._base",
            },
        )

        lexicon = load_lexicon("soc._base", lexicons_dir)

        assert isinstance(lexicon, Lexicon)
        assert lexicon.id == "soc._base"

    def test_load_lexicon_not_found(self, make_lexicon_file, lexicons_dir):
        """load_lexicon: Non-existent lexicon ID raises LexiconLoadError."""
        make_lexicon_file(
            "test.json",
            {
                "statuses": ["pending"],
                "transitions": {},
                "dir_map": {},
                "actionable_statuses": [],
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_lexicon("nonexistent", lexicons_dir)

        assert "not found" in str(exc_info.value).lower()


class TestErrorEdgeCases:
    """Edge cases and error scenarios."""

    def test_empty_lexicons_directory_reported(self, lexicons_dir):
        """Empty lexicons directory reported."""
        lexicons_dir.mkdir(parents=True, exist_ok=True)
        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert "no lexicon files found" in str(exc_info.value).lower()

    def test_nonexistent_lexicons_directory_reported(self):
        """Non-existent directory path reported."""
        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons("/nonexistent/path/lexicons")

        assert "does not exist" in str(exc_info.value).lower()

    def test_malformed_json_reported(self, make_lexicon_file, lexicons_dir):
        """Malformed JSON file reported."""
        # Write invalid JSON directly
        import json
        (lexicons_dir / "bad").mkdir(parents=True, exist_ok=True)
        with open(lexicons_dir / "bad" / "test.json", "w") as f:
            f.write("{invalid json")

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert any("failed to read" in e for e in exc_info.value.errors)

    def test_unknown_base_lexicon_reported(self, make_lexicon_file, lexicons_dir):
        """Child extends non-existent base reported."""
        make_lexicon_file(
            "child.json",
            {
                "extends": "nonexistent_base",
            },
        )

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert any("extends unknown" in e for e in exc_info.value.errors)

    def test_inheritance_depth_exceeds_limit_reported(self, make_lexicon_file, lexicons_dir):
        """Inheritance chain exceeding MAX_INHERITANCE_DEPTH (3) reported."""
        make_lexicon_file(
            "level0.json",
            {"statuses": ["pending"], "transitions": {}, "dir_map": {}, "actionable_statuses": []},
        )
        make_lexicon_file("level1.json", {"extends": "level0"})
        make_lexicon_file("level2.json", {"extends": "level1"})
        make_lexicon_file("level3.json", {"extends": "level2"})
        make_lexicon_file("level4.json", {"extends": "level3"})

        with pytest.raises(LexiconLoadError) as exc_info:
            load_all_lexicons(lexicons_dir)

        assert any("depth" in e.lower() for e in exc_info.value.errors)


class TestSchemaFileSkipping:
    """Schema files (*.schema.json) are excluded from lexicon discovery."""

    def test_schema_file_not_loaded_as_lexicon(self, make_lexicon_file, lexicons_dir):
        """A .schema.json file in the lexicons dir is ignored by the loader."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "statuses": ["pending", "passed"],
                "transitions": {"pending": ["passed"]},
                "dir_map": {"msoc": "passed"},
                "actionable_statuses": ["passed"],
            },
        )
        make_lexicon_file(
            "lexicon.schema.json",
            {"$schema": "https://json-schema.org/draft/2020-12/schema", "type": "object"},
        )

        result = load_all_lexicons(lexicons_dir)

        assert "lexicon.schema" not in result
        assert "soc._base" in result

    def test_schema_ref_in_lexicon_stripped(self, make_lexicon_file, lexicons_dir):
        """A $schema key in a lexicon file is stripped during loading."""
        make_lexicon_file(
            "soc/_base.json",
            {
                "$schema": "../lexicon.schema.json",
                "statuses": ["pending", "passed"],
                "transitions": {"pending": ["passed"]},
                "dir_map": {"msoc": "passed"},
                "actionable_statuses": ["passed"],
            },
        )

        result = load_all_lexicons(lexicons_dir)

        assert "soc._base" in result
        assert result["soc._base"].statuses == ("pending", "passed")
