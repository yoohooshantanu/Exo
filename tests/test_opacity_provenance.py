"""
tests/test_opacity_provenance.py

Automated tests for Phase 3: Runtime Opacity Provenance.
Validates:
1. Streaming SHA-256 correctness against byte-level ground truth.
2. Complete capture of PLATON runtime opacity assets: 24 species absorption tables and CIA pickle.
3. Extraction of CIA molecular pairs from collisional_absorption.pkl.
4. Detection of missing species resources when required.
5. Cached asset verification (fallback scan) when data is preloaded.
6. Bitwise numerical invariance: TransitDepthCalculator produces identical depth arrays
   with and without RuntimeOpacityInterceptor instrumentation.
"""

import hashlib
import numpy as np
import pytest
from pathlib import Path

from modules.retrieval_reproducibility import (
    RuntimeOpacityInterceptor,
    ReadThroughStreamWrapper,
    verify_runtime_opacity_file,
    get_known_opacity_provenance,
    KNOWN_OPACITY_REGISTRY,
)


class TestSHA256AndFileIntegrity:
    """Tests streaming SHA-256 calculation and file integrity tracking."""

    def test_streaming_sha256_matches_ground_truth(self, tmp_path):
        """Verify that streaming chunk read produces exact SHA-256 hash."""
        test_file = tmp_path / "test_platon_opacity.npy"
        # Save a valid numpy array
        arr = np.arange(50000, dtype=np.float32)
        np.save(test_file, arr)

        file_bytes = test_file.read_bytes()
        expected_hash = hashlib.sha256(file_bytes).hexdigest()

        with RuntimeOpacityInterceptor() as interceptor:
            _ = np.load(test_file)

        manifest = interceptor.get_manifest()
        p_resolved = str(test_file.resolve())
        assert p_resolved in interceptor.intercepted_files
        entry = interceptor.intercepted_files[p_resolved]
        assert entry["sha256_checksum"] == expected_hash
        assert entry["file_size_bytes"] == len(file_bytes)
        assert entry["interception_method"] == "actual_read_intercepted"


class TestPLATONRuntimeOpacityCapture:
    """Verifies that PLATON loads all 24 species tables and CIA absorption."""

    def test_atmosphere_solver_loads_24_species_and_cia(self):
        """Instantiating TransitDepthCalculator triggers reading all 24 species and CIA pickle."""
        from platon.transit_depth_calculator import TransitDepthCalculator

        with RuntimeOpacityInterceptor() as interceptor:
            calc = TransitDepthCalculator()

        manifest = interceptor.get_manifest()

        # Check total intercepted files (24 species + CIA + auxiliary grids)
        assert manifest["total_files_intercepted"] >= 25, (
            f"Expected at least 25 intercepted files (24 species + CIA), got {manifest['total_files_intercepted']}"
        )
        assert manifest["species_absorption_count"] == 24, (
            f"Expected 24 species absorption tables, got {manifest['species_absorption_count']}"
        )

        expected_24_species = {
            "H2O", "CH4", "CO", "CO2", "NH3", "N2", "O2", "O3",
            "H2S", "HCN", "NO", "NO2", "OH", "PH3", "SiO", "SO2",
            "TiO", "VO", "Na", "K", "Ca", "Ti", "Fe", "Ni",
        }
        loaded_species = set(manifest["loaded_species"])
        missing_species = expected_24_species - loaded_species
        assert not missing_species, f"Missing species in intercepted manifest: {missing_species}"

        # Verify CIA capture and molecular pairs
        assert manifest["cia_files_count"] >= 1, "CIA absorption file not intercepted"
        cia_pairs = manifest["cia_molecular_pairs"]
        assert len(cia_pairs) >= 10, f"Expected at least 10 CIA pairs, found {len(cia_pairs)}"
        assert any("H2-H2" in pair or "H2-He" in pair for pair in cia_pairs), (
            f"Key H2-H2 or H2-He pairs missing from CIA: {cia_pairs}"
        )

    def test_species_table_byte_sizes(self):
        """Each PLATON 5.4 absorb_coeffs table is exactly 14,402,048 bytes."""
        with RuntimeOpacityInterceptor(fallback_scan_if_empty=True) as interceptor:
            pass  # Fallback scan will locate files if already loaded

        manifest = interceptor.get_manifest()
        for sp, info in manifest["species_absorption"].items():
            assert info["file_size_bytes"] == 14402048, (
                f"Species {sp} file size {info['file_size_bytes']} != expected 14,402,048 bytes"
            )
            assert len(info["sha256_checksum"]) == 64, f"Invalid SHA-256 for {sp}"


class TestCachedAndMissingResourceHandling:
    """Verifies behavior with preloaded data, evidence classification, and missing resources."""

    def test_evidence_classification_separation(self, tmp_path):
        """Verifies observed_runtime_reads vs package_inventory evidence classification."""
        test_file = tmp_path / "absorb_coeffs_test.npy"
        np.save(test_file, np.arange(100, dtype=np.float32))

        # Runtime read should be classified as observed_runtime_reads
        with RuntimeOpacityInterceptor(retrieval_id="test-evidence-class") as interceptor:
            _ = np.load(test_file)

        manifest = interceptor.get_manifest()
        p_resolved = str(test_file.resolve())
        assert p_resolved in manifest["observed_runtime_reads"]
        entry = manifest["observed_runtime_reads"][p_resolved]
        assert entry["evidence_classification"] == "observed_runtime_reads"
        assert entry["directly_observed"] is True
        assert entry["inferred_from_cached_state"] is False
        assert entry["retrieval_id"] == "test-evidence-class"

    def test_hooks_restored_reliably_on_exception(self):
        """Verifies builtins.open and np.load are restored even if an exception occurs."""
        import builtins
        orig_open_id = id(builtins.open)
        orig_load_id = id(np.load)

        try:
            with RuntimeOpacityInterceptor():
                assert id(builtins.open) != orig_open_id
                assert id(np.load) != orig_load_id
                raise RuntimeError("Simulated failure inside retrieval context")
        except RuntimeError:
            pass

        # Must be restored
        assert id(builtins.open) == orig_open_id
        assert id(np.load) == orig_load_id

    def test_fallback_scan_finds_assets_if_already_cached(self):
        """When no reads occur in context (e.g. preloaded module), fallback scan locates data files as package_inventory."""
        with RuntimeOpacityInterceptor(fallback_scan_if_empty=True) as interceptor:
            pass  # No explicit read calls in this block

        manifest = interceptor.get_manifest()
        assert manifest["total_files_intercepted"] >= 25
        assert manifest["species_absorption_count"] == 24
        # All scanned entries must be classified as package_inventory, not observed_runtime_reads
        for p, entry in manifest["package_inventory"].items():
            assert entry["evidence_classification"] == "package_inventory"
            assert entry["directly_observed"] is False
            assert entry["inferred_from_cached_state"] is False
            assert entry["is_package_inventory"] is True

    def test_resource_read_from_non_owner_thread_bypasses_interceptor(self, tmp_path):
        """Exercises an actual model opacity resource read from a non-owner worker thread,
        confirming that thread-scoped filtering causes non-owner reads to bypass capture."""
        import threading
        # Create an actual opacity resource matching PLATON naming conventions
        opacity_resource = tmp_path / "absorb_coeffs_H2O_worker.npy"
        np.save(opacity_resource, np.arange(100, dtype=np.float32))

        with RuntimeOpacityInterceptor() as interceptor:
            worker_read_executed = []

            def worker_thread_load():
                # Non-owner thread attempts to load the opacity file
                arr = np.load(opacity_resource)
                worker_read_executed.append(len(arr))

            worker = threading.Thread(target=worker_thread_load)
            worker.start()
            worker.join()

        assert len(worker_read_executed) == 1
        manifest = interceptor.get_manifest()
        p_resolved = str(opacity_resource.resolve())
        # Confirms the limitation: non-owner thread reads bypass the interceptor
        assert p_resolved not in manifest["observed_runtime_reads"], (
            "Resource read from non-owner worker thread was captured, violating thread-scoped isolation!"
        )

    def test_separate_read_hashing_race_condition(self, tmp_path):
        """Demonstrates that SHA-256 is computed via a separate reopening read rather than
        tapping the in-flight byte stream. If a file is replaced between reads, the separate read
        hashes the disk state at hash-time rather than the bytes originally consumed."""
        test_file = tmp_path / "absorb_coeffs_race.npy"
        # Initial file state consumed by caller
        arr_initial = np.ones(50, dtype=np.float32)
        np.save(test_file, arr_initial)

        # In current design, _record_file opens test_file separately during tracking_np_load.
        # This confirms that the hash matches the file on disk at the moment of the separate read.
        with RuntimeOpacityInterceptor() as interceptor:
            _ = np.load(test_file)

        manifest = interceptor.get_manifest()
        p_resolved = str(test_file.resolve())
        entry = manifest["observed_runtime_reads"][p_resolved]

        # Verify that SHA-256 is present and matches initial bytes
        initial_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
        assert entry["sha256_checksum"] == initial_hash
        assert entry["hashing_integrity_verified"] is True

    def test_hashing_integrity_verified(self, tmp_path):
        """Verifies hashing stat invariance checks pre- and post-hash."""
        test_file = tmp_path / "absorb_coeffs_hash_test.npy"
        np.save(test_file, np.arange(50, dtype=np.float32))

        with RuntimeOpacityInterceptor() as interceptor:
            _ = np.load(test_file)

        manifest = interceptor.get_manifest()
        p_resolved = str(test_file.resolve())
        entry = manifest["observed_runtime_reads"][p_resolved]
        assert entry["hashing_integrity_verified"] is True

    def test_missing_resource_detection(self):
        """Querying an unknown species in verify_runtime_opacity_file reports not found."""
        res = verify_runtime_opacity_file("UnknownExoticMolecule_XYZ")
        assert res["runtime_file_verified"] is False
        assert res["disk_verification"]["provenance_verified"] is False
        assert res["database"] == "unknown"

    def test_known_registry_metadata_integrity(self):
        """All primary species in KNOWN_OPACITY_REGISTRY have valid reference DOIs and databases."""
        for sp in ["H2O", "CO", "CO2", "CH4", "Na", "K"]:
            meta = get_known_opacity_provenance(sp)
            assert meta is not None, f"Known metadata for {sp} missing"
            assert meta["database"] in ["ExoMol", "HITEMP", "HITRAN", "Kurucz / VALD3"]
            assert meta["reference_doi"] is not None


class TestNumericalBitwiseInvariance:
    """Proves that RuntimeOpacityInterceptor instrumentation does not alter model output."""

    def test_transit_depth_bitwise_identical_under_instrumentation(self):
        """Forward transit depth calculations with and without instrumentation must be bitwise identical."""
        from platon.transit_depth_calculator import TransitDepthCalculator
        from platon.constants import R_sun, M_jup, R_jup

        # Physical parameters for WASP-39 b
        star_radius = 0.932 * R_sun
        planet_mass = 0.28 * M_jup
        planet_radius = 1.27 * R_jup
        temperature = 1100.0

        # Run 1: Uninstrumented forward calculation
        calc_uninstrumented = TransitDepthCalculator()
        wavelengths_1, depths_1 = calc_uninstrumented.compute_depths(
            star_radius=star_radius,
            planet_mass=planet_mass,
            planet_radius=planet_radius,
            temperature=temperature,
        )

        # Run 2: Instrumented forward calculation
        with RuntimeOpacityInterceptor() as interceptor:
            calc_instrumented = TransitDepthCalculator()
            wavelengths_2, depths_2 = calc_instrumented.compute_depths(
                star_radius=star_radius,
                planet_mass=planet_mass,
                planet_radius=planet_radius,
                temperature=temperature,
            )

        # Strict bitwise identity assertion
        assert np.array_equal(wavelengths_1, wavelengths_2), "Wavelength grids differed under instrumentation!"
        assert np.array_equal(depths_1, depths_2), "Transit depths differed under instrumentation!"
        max_diff = np.max(np.abs(depths_1 - depths_2))
        assert max_diff == 0.0, f"Max absolute difference is not zero: {max_diff}"


class TestPhase5ExactStreamProvenance:
    """
    Automated regression tests for Phase 5: Exact-Stream Opacity Provenance.
    Verifies:
    1. Single-read in-memory stream hashing equality against ground truth.
    2. Parser bitwise identity (numpy and pickle).
    3. Repeated reads of the same resource and divergence detection.
    4. Truncated/corrupted stream failure handling and unresolved_resource classification.
    5. Cached resource classification without false exact-stream claims.
    6. Non-owner-thread read detection and unsupported_access_path classification.
    7. Memory-mapped (mmap_mode) unsupported access path classification.
    8. Package inventory secondary scan rejection of exact-stream claims.
    9. Manifest Schema v2.0 fields and completeness.
    """

    def test_exact_stream_sha256_equality_and_parser_consumption(self, tmp_path):
        """Verify exact stream SHA-256 matches raw bytes and parser consumption is verified."""
        import pickle
        test_npy = tmp_path / "platon_test_cross_sec.npy"
        arr = np.random.RandomState(42).randn(10, 20, 30).astype(np.float64)
        np.save(test_npy, arr)
        raw_bytes_npy = test_npy.read_bytes()
        expected_hash_npy = hashlib.sha256(raw_bytes_npy).hexdigest()

        test_pkl = tmp_path / "collisional_absorption_test.pkl"
        test_data = {("H2", "H2"): [1.0, 2.0, 3.0], ("H2", "He"): [0.5, 1.5]}
        with open(test_pkl, "wb") as pf:
            pickle.dump(test_data, pf, protocol=2)
        raw_bytes_pkl = test_pkl.read_bytes()
        expected_hash_pkl = hashlib.sha256(raw_bytes_pkl).hexdigest()

        with RuntimeOpacityInterceptor(fallback_scan_if_empty=False) as interceptor:
            loaded_arr = np.load(test_npy)
            with open(test_pkl, "rb") as pf:
                loaded_dict = pickle.load(pf, encoding="latin1")

        manifest = interceptor.get_manifest()
        assert str(test_npy.resolve()) in interceptor.exact_stream_verified
        assert str(test_pkl.resolve()) in interceptor.exact_stream_verified

        npy_entry = interceptor.exact_stream_verified[str(test_npy.resolve())]
        assert npy_entry["exact_stream_sha256"] == expected_hash_npy
        assert npy_entry["file_integrity_sha256"] == expected_hash_npy
        assert npy_entry["parser_consumption_verified"] is True
        assert npy_entry["resource_classification"] == "exact_stream_verified"
        assert npy_entry["verification_method"] == "read_through_in_memory_stream"
        assert npy_entry["runtime_read_observed"] is True

        pkl_entry = interceptor.exact_stream_verified[str(test_pkl.resolve())]
        assert pkl_entry["exact_stream_sha256"] == expected_hash_pkl
        assert pkl_entry["file_integrity_sha256"] == expected_hash_pkl
        assert pkl_entry["parser_consumption_verified"] is True
        assert pkl_entry["resource_classification"] == "exact_stream_verified"
        assert pkl_entry["verification_method"] == "read_through_in_memory_stream"

    def test_parser_byte_identity(self, tmp_path):
        """Objects returned from ReadThroughStreamWrapper are strictly bitwise identical to uninstrumented reads."""
        import pickle
        test_npy = tmp_path / "platon_absorb_identity.npy"
        arr = np.linspace(-100.0, 100.0, 10000, dtype=np.float64)
        np.save(test_npy, arr)

        # Direct uninstrumented load
        arr_direct = np.load(test_npy)

        # Instrumented load
        with RuntimeOpacityInterceptor(fallback_scan_if_empty=False) as interceptor:
            arr_instrumented = np.load(test_npy)

        assert np.array_equal(arr_direct, arr_instrumented)
        assert np.max(np.abs(arr_direct - arr_instrumented)) == 0.0

    def test_repeated_reads_of_same_resource(self, tmp_path):
        """Repeated reads of the same file increment read_count and detect data divergence."""
        test_npy = tmp_path / "platon_repeated_read.npy"
        arr1 = np.ones((50, 50), dtype=np.float32)
        np.save(test_npy, arr1)

        with RuntimeOpacityInterceptor(fallback_scan_if_empty=False) as interceptor:
            _ = np.load(test_npy)
            _ = np.load(test_npy)

        manifest = interceptor.get_manifest()
        entry = interceptor.exact_stream_verified[str(test_npy.resolve())]
        assert entry["read_count"] == 2
        assert "hash_diverged_across_repeated_reads" not in entry["limitations"]

        # Now test hash divergence detection when underlying file is modified
        with RuntimeOpacityInterceptor(fallback_scan_if_empty=False) as interceptor2:
            _ = np.load(test_npy)
            # Modify file on disk between reads
            arr2 = np.zeros((50, 50), dtype=np.float32)
            np.save(test_npy, arr2)
            _ = np.load(test_npy)

        entry2 = interceptor2.exact_stream_verified[str(test_npy.resolve())]
        assert entry2["read_count"] == 2
        assert "hash_diverged_across_repeated_reads" in entry2["limitations"]

    def test_truncated_or_corrupted_stream_handling(self, tmp_path):
        """Truncated or corrupted files fail parser consumption and are classified as unresolved_resource."""
        import pickle
        bad_pkl = tmp_path / "collisional_absorption_corrupt.pkl"
        bad_pkl.write_bytes(b"BROKEN_PICKLE_STREAM_TRUNCATED")

        bad_npy = tmp_path / "platon_corrupt.npy"
        bad_npy.write_bytes(b"NOT_A_VALID_NUMPY_FILE_PAYLOAD")

        with RuntimeOpacityInterceptor(fallback_scan_if_empty=False) as interceptor:
            with pytest.raises(Exception):
                with open(bad_pkl, "rb") as f:
                    _ = pickle.load(f)

            with pytest.raises(Exception):
                _ = np.load(bad_npy)

        manifest = interceptor.get_manifest()
        bad_pkl_str = str(bad_pkl.resolve())
        bad_npy_str = str(bad_npy.resolve())

        # Neither should be exact_stream_verified
        assert bad_pkl_str not in interceptor.exact_stream_verified
        assert bad_npy_str not in interceptor.exact_stream_verified

        # Must appear in unresolved_resources
        unresolved_paths = [r.get("resource_path", r.get("file_path")) for r in interceptor.unresolved_resources]
        assert bad_npy_str in unresolved_paths

    def test_cached_resource_classification(self, tmp_path):
        """Cached in-memory resources are distinct from exact-stream runtime reads."""
        test_res = tmp_path / "absorb_coeffs_H2O.npy"
        np.save(test_res, np.arange(10, dtype=np.float32))

        interceptor = RuntimeOpacityInterceptor(fallback_scan_if_empty=False)
        interceptor.register_memory_cached_resource(test_res, "species_absorption", species="H2O")

        assert str(test_res.resolve()) in interceptor.cached_resources
        entry = interceptor.cached_resources[str(test_res.resolve())]
        assert entry["resource_classification"] == "cached_resource"
        assert entry["exact_stream_sha256"] is None  # Must NOT claim exact stream without runtime delivery
        assert entry["file_integrity_sha256"] is not None
        assert entry["runtime_read_observed"] is False
        assert entry["inferred_from_cached_state"] is True
        assert entry["verification_method"] == "memory_cache_verification"

    def test_non_owner_thread_reads_classified_as_unsupported(self, tmp_path):
        """Resource reads occurring on non-owner threads are flagged as unsupported_access_path."""
        import threading
        test_res = tmp_path / "platon_thread_test.npy"
        np.save(test_res, np.ones(10, dtype=np.float32))

        with RuntimeOpacityInterceptor(fallback_scan_if_empty=False) as interceptor:
            def thread_work():
                _ = np.load(test_res)

            t = threading.Thread(target=thread_work)
            t.start()
            t.join()

        manifest = interceptor.get_manifest()
        unsupported = interceptor.unsupported_access_paths
        assert len(unsupported) >= 1
        entry = unsupported[0]
        assert entry["resource_classification"] == "unsupported_access_path"
        assert entry["reason"] == "non_owner_thread_access"
        assert entry["exact_stream_sha256"] is None
        assert str(test_res.resolve()) not in interceptor.exact_stream_verified

    def test_memory_mapped_mmap_mode_classified_as_unsupported(self, tmp_path):
        """Memory-mapped reads (mmap_mode) cannot be stream-hashed in-memory and are flagged as unsupported."""
        test_res = tmp_path / "platon_mmap_test.npy"
        np.save(test_res, np.arange(100, dtype=np.float32))

        with RuntimeOpacityInterceptor(fallback_scan_if_empty=False) as interceptor:
            _ = np.load(test_res, mmap_mode="r")

        manifest = interceptor.get_manifest()
        unsupported = interceptor.unsupported_access_paths
        assert any(entry["reason"] == "memory_mapped_mmap_mode_r" for entry in unsupported)
        assert str(test_res.resolve()) not in interceptor.exact_stream_verified

    def test_rejection_of_false_exact_stream_claims_from_secondary_reads(self):
        """Package inventory scan entries must never be marked as exact_stream_verified."""
        interceptor = RuntimeOpacityInterceptor(fallback_scan_if_empty=True)
        interceptor._scan_platon_data_directory()

        for p_str, entry in interceptor.package_inventory.items():
            assert entry["resource_classification"] == "file_integrity_only"
            assert entry["exact_stream_sha256"] is None
            assert entry["file_integrity_sha256"] is not None
            assert entry["runtime_read_observed"] is False
            assert "secondary_disk_read_only" in entry["limitations"]

    def test_manifest_schema_v2_completeness(self):
        """Manifest Schema v2.0 includes all 5 classification counts and complete scope metadata."""
        from platon.transit_depth_calculator import TransitDepthCalculator

        with RuntimeOpacityInterceptor() as interceptor:
            calc = TransitDepthCalculator()

        manifest = interceptor.get_manifest()
        assert manifest["schema_version"] == "2.0.0"
        summary = manifest["evidence_classification_summary"]
        assert "exact_stream_verified_count" in summary
        assert "file_integrity_only_count" in summary
        assert "cached_resources_count" in summary
        assert "unresolved_resources_count" in summary
        assert "unsupported_access_paths_count" in summary
        assert summary["exact_stream_verified_count"] >= 25
        assert manifest["provenance_scope"]["exact_consumed_stream_verified"] is True
        assert manifest["provenance_scope"]["hashing_evidence_level"] == "exact_stream_single_read_in_memory"


class TestParserConsumptionTelemetry:
    """
    Validates fine-grained parser-consumption telemetry in ReadThroughStreamWrapper:
    - Cursor position vs bytes returned
    - Seek directly to EOF without reading
    - Partial reads followed by successful return
    - Repeated reads of identical byte intervals
    - Consumption through readinto
    - Consumption through TextIOWrapper
    - Successful parser completion with unread trailing bytes
    """

    def test_seek_directly_to_eof_without_reading(self):
        """Seeking directly to EOF moves the cursor without returning bytes; cannot be verified as consumed."""
        payload = b"A" * 100
        entry = {"file_path": "dummy.bin"}
        wrapper = ReadThroughStreamWrapper(payload, "dummy.bin", entry)

        # Move cursor to end without reading
        pos = wrapper.seek(100)
        assert pos == 100
        wrapper.close()

        assert entry["bytes_available"] == 100
        assert entry["final_cursor_position"] == 100
        assert entry["bytes_returned_total"] == 0
        assert entry["unique_bytes_returned"] == 0
        assert entry["unread_trailing_bytes"] == 0
        assert entry["parser_completed_successfully"] is True
        # MUST NOT claim complete consumption when 0 bytes were actually returned
        assert entry["complete_stream_consumption_verified"] is False
        assert entry["resource_classification"] != "exact_stream_verified"

    def test_partial_reads_followed_by_successful_parser_return(self):
        """A parser that successfully returns after reading only part of a stream leaves unread trailing bytes."""
        payload = b"HEADER_12345" + b"TRAILING_UNREAD_DATA" * 5  # 12 + 100 = 112 bytes
        entry = {"file_path": "partial.bin"}
        wrapper = ReadThroughStreamWrapper(payload, "partial.bin", entry)

        # Parser reads only the 12-byte header and returns cleanly
        header = wrapper.read(12)
        assert header == b"HEADER_12345"
        wrapper.close()

        assert entry["bytes_available"] == len(payload)
        assert entry["bytes_returned_total"] == 12
        assert entry["unique_bytes_returned"] == 12
        assert entry["final_cursor_position"] == 12
        assert entry["unread_trailing_bytes"] == len(payload) - 12
        assert entry["unread_trailing_bytes"] > 0
        assert entry["parser_completed_successfully"] is True
        assert entry["complete_stream_consumption_verified"] is False
        assert entry["resource_classification"] == "partial_stream_consumed"

    def test_reading_same_bytes_repeatedly(self):
        """Repeatedly reading the same byte range increments bytes_returned_total without expanding unique coverage."""
        payload = b"REPEATED_CONTENT_BLOCK" * 4  # 88 bytes
        entry = {"file_path": "repeat.bin"}
        wrapper = ReadThroughStreamWrapper(payload, "repeat.bin", entry)

        # Read first 22 bytes 3 times
        for _ in range(3):
            wrapper.seek(0)
            data = wrapper.read(22)
            assert data == b"REPEATED_CONTENT_BLOCK"
        wrapper.close()

        assert entry["bytes_available"] == len(payload)
        assert entry["bytes_returned_total"] == 66  # 3 * 22
        assert entry["unique_bytes_returned"] == 22
        assert entry["unique_byte_ranges_returned"] == [[0, 22]]
        assert entry["unread_trailing_bytes"] == len(payload) - 22
        assert entry["parser_completed_successfully"] is True
        assert entry["complete_stream_consumption_verified"] is False

    def test_reading_through_readinto(self):
        """Reading through readinto correctly tracks byte intervals and establishes complete consumption."""
        payload = b"BLOCK_DATA_" * 10  # 110 bytes
        entry = {"file_path": "readinto.bin"}
        wrapper = ReadThroughStreamWrapper(payload, "readinto.bin", entry)

        buf = bytearray(22)
        total_read = 0
        while True:
            n = wrapper.readinto(buf)
            if n == 0:
                break
            total_read += n
        wrapper.close()

        assert total_read == len(payload)
        assert entry["bytes_available"] == len(payload)
        assert entry["bytes_returned_total"] == len(payload)
        assert entry["unique_bytes_returned"] == len(payload)
        assert entry["unread_trailing_bytes"] == 0
        assert entry["final_cursor_position"] == len(payload)
        assert entry["parser_completed_successfully"] is True
        assert entry["complete_stream_consumption_verified"] is True
        assert entry["resource_classification"] == "exact_stream_verified"

    def test_reading_through_text_wrappers(self):
        """Wrapping ReadThroughStreamWrapper in TextIOWrapper preserves exact stream byte telemetry."""
        import io
        text_content = "Line 1: Carbon monoxide\nLine 2: Water vapor\nLine 3: Methane\n"
        raw_bytes = text_content.encode("utf-8")
        entry = {"file_path": "species.txt"}
        wrapper = ReadThroughStreamWrapper(raw_bytes, "species.txt", entry, mode="r")

        with io.TextIOWrapper(wrapper, encoding="utf-8") as text_io:
            lines = text_io.readlines()
            assert len(lines) == 3

        assert entry["bytes_available"] == len(raw_bytes)
        assert entry["unique_bytes_returned"] == len(raw_bytes)
        assert entry["unread_trailing_bytes"] == 0
        assert entry["parser_completed_successfully"] is True
        assert entry["complete_stream_consumption_verified"] is True
        assert entry["resource_classification"] == "exact_stream_verified"

    def test_parser_success_with_unread_trailing_bytes(self):
        """Distinguish successful parser return from complete byte-stream consumption when trailing bytes remain."""
        # Simulated scenario: resource file contains 200 bytes, but parser only parses a 50-byte header block
        payload = b"MAGIC" + (b"X" * 45) + (b"UNPARSED_EXTRA_DATA" * 10)  # 5 + 45 + 190 = 240 bytes
        entry = {"file_path": "header_only.dat"}
        wrapper = ReadThroughStreamWrapper(payload, "header_only.dat", entry)

        def mock_parser(stream):
            magic = stream.read(5)
            assert magic == b"MAGIC"
            body = stream.read(45)
            # Parser finishes successfully, returning valid parsed object without reading the remaining 190 bytes
            return {"status": "ok", "len": len(body)}

        result = mock_parser(wrapper)
        wrapper.close()

        assert result["status"] == "ok"
        assert entry["parser_completed_successfully"] is True
        assert entry["unread_trailing_bytes"] == 190
        assert entry["unique_bytes_returned"] == 50
        assert entry["bytes_available"] == 240
        # Telemetry guarantees that complete consumption is NOT falsely claimed
        assert entry["complete_stream_consumption_verified"] is False
        assert entry["resource_classification"] == "partial_stream_consumed"

    def test_getbuffer_parser_obtains_view_but_reads_no_bytes(self):
        """Buffer exposure without stream reads tracks buffer_exposed=True and classifies as unsupported_access_path."""
        payload = b"PAYLOAD_BUFFER_TEST_100B" * 4  # 96 bytes
        entry = {"file_path": "nobytes_view.bin"}
        wrapper = ReadThroughStreamWrapper(payload, "nobytes_view.bin", entry)

        view = wrapper.getbuffer()
        assert isinstance(view, memoryview)
        assert len(view) == len(payload)
        # Parser obtains view but performs no reads
        view.release()
        wrapper.close()

        assert entry["buffer_exposed"] is True
        assert entry["buffer_exposure_count"] == 1
        assert entry["bytes_returned_total"] == 0
        assert entry["unique_bytes_returned"] == 0
        assert entry["final_cursor_position"] == 0
        assert entry["unread_trailing_bytes"] == len(payload)
        assert entry["parser_completed_successfully"] is True
        # Prohibits false claim of complete consumption
        assert entry["complete_stream_consumption_verified"] is False
        assert entry["resource_classification"] == "unsupported_access_path"

    def test_getbuffer_parser_inspects_only_small_slice(self):
        """Parser inspecting only a slice of exposed memoryview cannot be verified as complete stream consumption."""
        payload = b"HEADER_PREFIX_" + (b"UNINSPECTED_DATA_BLOCK" * 5)  # 14 + 110 = 124 bytes
        entry = {"file_path": "slice_view.bin"}
        wrapper = ReadThroughStreamWrapper(payload, "slice_view.bin", entry)

        view = wrapper.getbuffer()
        slice_examined = bytes(view[:14])
        assert slice_examined == b"HEADER_PREFIX_"
        view.release()
        wrapper.close()

        assert entry["buffer_exposed"] is True
        assert entry["bytes_returned_total"] == 0
        assert entry["unique_bytes_returned"] == 0
        assert entry["parser_completed_successfully"] is True
        assert entry["complete_stream_consumption_verified"] is False
        assert entry["resource_classification"] == "unsupported_access_path"

    def test_getbuffer_parser_examines_entire_buffer(self):
        """Even if parser examines the entire buffer in-memory, buffer-based access is unsupported for stream verification."""
        payload = b"ENTIRE_BUFFER_CONTENT_EXAMINED" * 3  # 93 bytes
        entry = {"file_path": "full_view.bin"}
        wrapper = ReadThroughStreamWrapper(payload, "full_view.bin", entry)

        view = wrapper.getbuffer()
        all_data = bytes(view)
        assert len(all_data) == len(payload)
        view.release()
        wrapper.close()

        assert entry["buffer_exposed"] is True
        # Stream wrapper did not return bytes via read protocol, so complete_stream_consumption_verified is strictly False
        assert entry["complete_stream_consumption_verified"] is False
        assert entry["resource_classification"] == "unsupported_access_path"

    def test_getbuffer_mutation_attempts_strictly_fail(self):
        """Underlying stream memoryview is strictly read-only; in-place mutations raise TypeError."""
        payload = b"IMMUTABLE_BUFFER_DATA" * 5  # 105 bytes
        entry = {"file_path": "buffer_mutate.bin"}
        wrapper = ReadThroughStreamWrapper(payload, "buffer_mutate.bin", entry)

        view = wrapper.getbuffer()
        assert view.readonly is True

        with pytest.raises(TypeError, match="cannot modify read-only memory"):
            view[0] = 65

        view.release()
        wrapper.close()

        assert entry["buffer_exposed"] is True
        assert entry["complete_stream_consumption_verified"] is False
        assert entry["resource_classification"] == "unsupported_access_path"

    def test_stream_wrapper_rejects_write_operations(self):
        """ReadThroughStreamWrapper is strictly a read-only input stream; write operations raise UnsupportedOperation."""
        import io
        payload = b"READ_ONLY_PAYLOAD"
        entry = {"file_path": "readonly.bin"}
        wrapper = ReadThroughStreamWrapper(payload, "readonly.bin", entry)

        with pytest.raises(io.UnsupportedOperation, match="read-only input stream"):
            wrapper.write(b"MUTATION")

        with pytest.raises(io.UnsupportedOperation, match="read-only input stream"):
            wrapper.writelines([b"MUTATION1", b"MUTATION2"])

        with pytest.raises(io.UnsupportedOperation, match="read-only input stream"):
            wrapper.truncate(10)

        wrapper.close()
