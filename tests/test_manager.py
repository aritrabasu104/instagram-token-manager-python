import json
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

from helpers import LIFETIME, NEW, NOW, OLD, Fixture

from instagram_tokens import (
    GrantRejected,
    RefreshRequired,
    RenewalState,
    TokenGrant,
    TransientError,
    ValidationError,
    map_accounts,
)
from instagram_tokens.state import cached_health, invalidate_health, retain_health


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.fixture = Fixture(self.temp.name)

    def test_ten_simultaneous_refreshes_share_one_grant(self):
        f = self.fixture
        barrier = threading.Barrier(10)

        def work(_):
            barrier.wait()
            return f.manager.refresh(now=NOW)

        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(work, range(10)))
        self.assertEqual(f.calls, 1)
        self.assertEqual(sum(r.refreshed for r in results), 1)
        self.assertTrue(all(r.access_token == NEW for r in results))
        self.assertEqual(len(f.vault.items), 1)

    def test_lost_response_never_dispatches_another_grant(self):
        f = self.fixture
        calls = []

        def lost(_):
            calls.append(1)
            raise TimeoutError(OLD)

        f.manager.refresher = lost
        for _ in range(2):
            with self.assertRaises(TransientError) as caught:
                f.manager.refresh(now=NOW)
            self.assertNotIn(OLD, str(caught.exception))
        self.assertEqual(len(calls), 1)
        self.assertEqual(RenewalState(f.identity, f.store).value["status"], "unknown")

    def test_returned_candidate_survives_validation_outage(self):
        f = self.fixture
        f.fail_validation = True
        with self.assertRaises(TransientError):
            f.manager.refresh(now=NOW)
        self.assertIn(NEW, f.vault.items.values())
        f.fail_validation = False
        result = f.manager.refresh(now=NOW + timedelta(minutes=3))
        self.assertEqual(f.calls, 1)
        self.assertEqual(result.expires_at, (NOW + timedelta(seconds=LIFETIME)).isoformat())

    def test_metadata_failure_rolls_back_then_resumes(self):
        f = self.fixture
        f.fail_write = True
        with self.assertRaises(ValidationError):
            f.manager.refresh(now=NOW)
        self.assertEqual(f.vault.items[(f.identity.target.service, f.identity.target.account)], OLD)
        f.fail_write = False
        self.assertEqual(f.manager.refresh(now=NOW).access_token, NEW)
        self.assertEqual(f.calls, 1)

    def test_missing_metadata_reuses_the_exact_retained_receipt(self):
        f = self.fixture
        first = f.manager.refresh(now=NOW)
        f.metadata = None
        result = f.manager.refresh(now=NOW + timedelta(minutes=3), repair_metadata=True)
        self.assertEqual(first.expires_at, result.expires_at)
        self.assertEqual(f.calls, 1)

    def test_unknown_grant_rejects_changed_identity(self):
        f = self.fixture

        def lost(_):
            raise TimeoutError()

        f.manager.refresher = lost
        with self.assertRaises(TransientError):
            f.manager.refresh(now=NOW)
        with self.assertRaises(ValueError):
            RenewalState(replace(f.identity, binding="different"), f.store)

    def test_rate_limit_cooldown_and_retry_count_survive_new_managers(self):
        f = self.fixture
        calls = []

        def rejected(_):
            calls.append(1)
            raise GrantRejected(retryable=True)

        f.manager.refresher = rejected
        for offset in (0, 1, 61, 62, 122, 183):
            with self.assertRaises(TransientError):
                f.manager.refresh(now=NOW + timedelta(seconds=offset))
        state = RenewalState(f.identity, f.store).value
        self.assertEqual(len(calls), 3)
        self.assertEqual(state["dispatch_count"], 3)

    def test_state_and_safe_output_never_contain_credentials(self):
        f = self.fixture
        result = f.manager.refresh(now=NOW)
        text = (
            json.dumps(RenewalState(f.identity, f.store).value)
            + repr(result)
            + json.dumps(result.safe_dict())
        )
        self.assertNotIn(OLD, text)
        self.assertNotIn(NEW, text)

    def test_ensure_refreshes_near_expiry_and_reuses_session(self):
        f = self.fixture
        self.assertEqual(f.manager.ensure(now=NOW).access_token, NEW)
        self.assertEqual(f.manager.ensure(now=NOW).access_token, NEW)
        self.assertEqual(f.calls, 1)

    def test_rejected_current_authorization_is_typed_and_never_dispatched_for_refresh(self):
        f = self.fixture
        f.metadata["expires_at"] = (NOW + timedelta(days=50)).isoformat()
        f.manager.validator = lambda *args, **kwargs: f.health(
            "regeneration_required", "provider_rejected_token")
        with self.assertRaises(RefreshRequired) as caught:
            f.manager.ensure(now=NOW)
        self.assertEqual(caught.exception.health.recovery_action, "reauthorize")
        self.assertEqual(f.calls, 0)
        self.assertEqual(f.vault.items[(f.identity.target.service, f.identity.target.account)], OLD)
        self.assertFalse(RenewalState(f.identity, f.store).value)

    def test_permission_and_transport_failures_do_not_request_new_authorization(self):
        f = self.fixture
        f.metadata["expires_at"] = (NOW + timedelta(days=50)).isoformat()
        for state, reason, action, error in [
            ("configuration_error", "publishing_permission_rejected", "repair_configuration", ValidationError),
            ("transient_failure", "provider_temporarily_unavailable", "retry_validation", TransientError),
        ]:
            health = f.health(state, reason)
            f.manager.validator = lambda *args, **kwargs: health
            with self.assertRaises(error) as caught:
                f.manager.ensure(now=NOW)
            self.assertNotIsInstance(caught.exception, RefreshRequired)
            self.assertEqual(health.safe_dict()["recovery_action"], action)
        self.assertEqual(f.calls, 0)

    def test_validation_cache_binds_metadata_and_fresh_refusals(self):
        f = self.fixture
        health = f.health().__dict__
        retain_health(f.store, f.identity, OLD, health, now=1, metadata={"revision": 1})
        self.assertEqual(
            cached_health(f.store, f.identity, OLD, now=2, metadata={"revision": 1}), health
        )
        self.assertIsNone(cached_health(f.store, f.identity, OLD, now=2, metadata={"revision": 2}))
        invalidate_health(f.store, f.identity, OLD)
        self.assertIsNone(cached_health(f.store, f.identity, OLD, now=2, metadata={"revision": 1}))

    def test_manager_exposes_exact_credential_cache_invalidation(self):
        fixture = self.fixture
        retain_health(fixture.store, fixture.identity, OLD, fixture.health().__dict__, now=1)
        fixture.manager.invalidate(OLD)
        self.assertIsNone(cached_health(fixture.store, fixture.identity, OLD, now=2))

    def test_ten_accounts_can_progress_together(self):
        barrier = threading.Barrier(10)

        def operation(value):
            barrier.wait(timeout=5)
            return value

        self.assertEqual(map_accounts(operation, list(range(10))), list(range(10)))
        with self.assertRaises(ValueError):
            map_accounts(operation, [], max_workers=11)

    def test_independent_accounts_are_not_serialized(self):
        one = self.fixture
        two = Fixture(self.temp.name + "/second", "second")
        barrier = threading.Barrier(2)

        def refresh(_):
            barrier.wait(timeout=5)
            return TokenGrant(NEW, LIFETIME)

        one.manager.refresher = refresh
        two.manager.refresher = refresh
        results = map_accounts(
            lambda manager: manager.refresh(now=NOW), [one.manager, two.manager], max_workers=2
        )
        self.assertTrue(all(r.refreshed for r in results))


def _unknown_refresh_worker(directory, events):
    fixture = Fixture(directory)

    def lost_response(_):
        events.put("dispatched")
        raise TimeoutError()

    fixture.manager.refresher = lost_response
    try:
        fixture.manager.refresh(now=NOW)
    except TransientError:
        return
    raise AssertionError("The lost response must remain unknown")


class ProcessTests(unittest.TestCase):
    def test_unknown_grant_fence_is_shared_across_fresh_processes(self):
        import multiprocessing
        from queue import Empty

        with tempfile.TemporaryDirectory() as directory:
            context = multiprocessing.get_context("spawn")
            events = context.Queue()
            workers = [
                context.Process(target=_unknown_refresh_worker, args=(directory, events))
                for _ in range(3)
            ]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(15)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(events.get(timeout=1), "dispatched")
            with self.assertRaises(Empty):
                events.get(timeout=0.1)
