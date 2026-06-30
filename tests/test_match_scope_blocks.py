"""Unit tests for _match_scope_blocks in build_review.py."""

import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
from scripts.build_review import _match_scope_blocks


def make_block(name, kind, start, end, changed_lines=None):
    """Build a minimal scope block dict."""
    code = []
    for ln in range(start, end + 1):
        line_type = 'context'
        if changed_lines and ln in changed_lines:
            line_type = changed_lines[ln]
        code.append({'line': ln, 'text': f'line {ln}', 'type': line_type})
    return {
        'scope_name': name,
        'scope_kind': kind,
        'scope_start': start,
        'scope_end': end,
        'code': code,
    }


def make_hunk_index(mappings):
    """Build a hunk_index from a list of (old_start, new_start) pairs."""
    return {old: {'old_start': old, 'new_start': new} for old, new in mappings}


class TestNoLinesReturnsAll(unittest.TestCase):
    """When section has no 'lines', return all blocks unchanged."""

    def test_no_lines_key(self):
        before = [make_block('foo', 'fn', 10, 30)]
        after = [make_block('foo', 'fn', 10, 30)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        b, a = _match_scope_blocks(scope_entry, {'file': 'x.rs'}, {})
        self.assertIs(b, before)
        self.assertIs(a, after)

    def test_empty_lines(self):
        before = [make_block('foo', 'fn', 10, 30)]
        after = [make_block('foo', 'fn', 10, 30)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        b, a = _match_scope_blocks(scope_entry, {'file': 'x.rs', 'lines': []}, {})
        self.assertIs(b, before)
        self.assertIs(a, after)


class TestCoordinateMatching(unittest.TestCase):
    """Both sides match by line-number overlap when coordinates align."""

    def test_single_scope_both_sides(self):
        before = [make_block('handle', 'fn', 50, 80)]
        after = [make_block('handle', 'fn', 50, 80)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [55]}
        hunk_index = make_hunk_index([(55, 55)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]['scope_name'], 'handle')
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]['scope_name'], 'handle')

    def test_two_scopes_coordinates_align(self):
        """Two functions, coordinates match on both sides."""
        before = [
            make_block('get_dashboard', 'fn', 30, 180),
            make_block('get_statistics', 'fn', 185, 400),
        ]
        after = [
            make_block('get_dashboard', 'fn', 30, 200),
            make_block('get_statistics', 'fn', 205, 420),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [50, 190]}
        hunk_index = make_hunk_index([(50, 50), (190, 210)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 2)
        self.assertEqual(len(a), 2)
        names = {bl['scope_name'] for bl in a}
        self.assertEqual(names, {'get_dashboard', 'get_statistics'})

    def test_unmatched_line_skipped(self):
        """old_start not in hunk_index -> no after translation, block missed."""
        before = [make_block('foo', 'fn', 10, 30)]
        after = [make_block('foo', 'fn', 10, 30)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [15]}
        hunk_index = {}  # no hunks at all

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 1)
        # after_line_set is empty, but name fallback should catch it
        self.assertEqual(len(a), 1)


class TestNameFallback(unittest.TestCase):
    """After-side coordinate matching fails, name fallback picks up the scope."""

    def test_shifted_function(self):
        """get_statistics shifted 30 lines; new_start outside the scope range."""
        before = [
            make_block('get_dashboard', 'fn', 30, 180),
            make_block('get_statistics', 'fn', 185, 400),
        ]
        after = [
            make_block('get_dashboard', 'fn', 30, 205),
            make_block('get_statistics', 'fn', 250, 450),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        # old_start=190 -> new_start=210, but get_statistics now starts at 250
        section = {'file': 'x.rs', 'lines': [50, 190]}
        hunk_index = make_hunk_index([(50, 50), (190, 210)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 2)
        self.assertEqual(len(a), 2)
        self.assertEqual(a[0]['scope_name'], 'get_dashboard')
        self.assertEqual(a[1]['scope_name'], 'get_statistics')

    def test_fallback_single_candidate(self):
        """Only one after block with the matching name -> use it directly."""
        before = [make_block('process', 'fn', 100, 200)]
        after = [make_block('process', 'fn', 500, 600)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [120]}
        hunk_index = make_hunk_index([(120, 130)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]['scope_name'], 'process')
        self.assertEqual(a[0]['scope_start'], 500)

    def test_partial_coordinate_match_fills_missing(self):
        """After matches one scope by coordinates, name fallback fills the other."""
        before = [
            make_block('init', 'fn', 10, 50),
            make_block('run', 'fn', 55, 120),
        ]
        after = [
            make_block('init', 'fn', 10, 60),
            make_block('run', 'fn', 200, 280),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        # old_start=15 in init (matches both sides), old_start=60 in run (new_start=65, outside run's new range 200-280)
        section = {'file': 'x.rs', 'lines': [15, 60]}
        hunk_index = make_hunk_index([(15, 15), (60, 65)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 2)
        self.assertEqual(len(a), 2)
        after_names = {bl['scope_name'] for bl in a}
        self.assertEqual(after_names, {'init', 'run'})


class TestDuplicateScopeNames(unittest.TestCase):
    """Multiple scopes with the same (name, kind) — e.g. fn new() in two impl blocks."""

    def test_picks_closest_by_position(self):
        """Two fn new() at lines 50 and 200; before matched the one at 200."""
        before = [make_block('new', 'fn', 200, 220)]
        after_candidates = [
            make_block('new', 'fn', 55, 75),
            make_block('new', 'fn', 230, 250),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after_candidates}
        section = {'file': 'x.rs', 'lines': [205]}
        hunk_index = make_hunk_index([(205, 240)])
        # new_start=240 is inside after block at 230-250, so coordinates should match.
        # But let's force a miss by setting new_start outside both.
        hunk_index = make_hunk_index([(205, 300)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 1)
        self.assertEqual(len(a), 1)
        # Should pick the one at 230 (closest to before's 200), not the one at 55
        self.assertEqual(a[0]['scope_start'], 230)

    def test_picks_closest_for_low_position(self):
        """Before matched fn new() at line 50; should pick after at 55, not 230."""
        before = [make_block('new', 'fn', 50, 70)]
        after_candidates = [
            make_block('new', 'fn', 55, 75),
            make_block('new', 'fn', 230, 250),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after_candidates}
        section = {'file': 'x.rs', 'lines': [55]}
        hunk_index = make_hunk_index([(55, 300)])  # miss both after blocks

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]['scope_start'], 55)

    def test_coordinate_match_takes_priority(self):
        """If coordinates match one fn new(), don't add duplicates via fallback."""
        before = [make_block('new', 'fn', 200, 220)]
        after_blocks = [
            make_block('new', 'fn', 55, 75),
            make_block('new', 'fn', 210, 230),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after_blocks}
        section = {'file': 'x.rs', 'lines': [205]}
        hunk_index = make_hunk_index([(205, 215)])  # 215 is inside after block 210-230

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(a), 1)
        # Matched by coordinates, fallback shouldn't fire
        self.assertEqual(a[0]['scope_start'], 210)


class TestDeletedFunction(unittest.TestCase):
    """Function exists on before side but was deleted in after."""

    def test_no_after_block_exists(self):
        before = [make_block('old_helper', 'fn', 100, 150)]
        scope_entry = {'before_blocks': before, 'after_blocks': []}
        section = {'file': 'x.rs', 'lines': [110]}
        hunk_index = make_hunk_index([(110, 110)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]['scope_name'], 'old_helper')
        self.assertEqual(len(a), 0)

    def test_deleted_among_surviving(self):
        """One function deleted, another survives."""
        before = [
            make_block('keep', 'fn', 10, 40),
            make_block('remove', 'fn', 50, 90),
        ]
        after = [make_block('keep', 'fn', 10, 40)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [15, 60]}
        hunk_index = make_hunk_index([(15, 15), (60, 60)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 2)
        # After: 'keep' matched by coordinates, 'remove' not found -> only 1
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]['scope_name'], 'keep')


class TestNewFunction(unittest.TestCase):
    """Function only exists on the after side (pure addition)."""

    def test_new_fn_no_before_block(self):
        """Before has no blocks, after has the new function. Section references it."""
        after = [make_block('new_helper', 'fn', 100, 130)]
        scope_entry = {'before_blocks': [], 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [100]}
        hunk_index = make_hunk_index([(100, 100)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 0)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]['scope_name'], 'new_helper')


class TestRenamedFunction(unittest.TestCase):
    """Function renamed between before and after."""

    def test_name_mismatch_no_fallback(self):
        before = [make_block('old_name', 'fn', 100, 150)]
        after = [make_block('new_name', 'fn', 100, 160)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [110]}
        hunk_index = make_hunk_index([(110, 110)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 1)
        self.assertEqual(b[0]['scope_name'], 'old_name')
        # Coordinate match should still catch the after block at 100-160
        # since new_start=110 is inside 100-160
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]['scope_name'], 'new_name')

    def test_renamed_and_shifted_falls_through(self):
        """Renamed AND shifted -> neither coordinates nor name match."""
        before = [make_block('old_name', 'fn', 100, 150)]
        after = [make_block('new_name', 'fn', 300, 360)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [110]}
        hunk_index = make_hunk_index([(110, 110)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 1)
        # After: coordinates miss (110 not in 300-360), name miss ('old_name' != 'new_name')
        self.assertEqual(len(a), 0)


class TestChangedLineMatching(unittest.TestCase):
    """Match via changed lines in the block's code array (secondary check)."""

    def test_match_by_changed_lines(self):
        """Line number outside scope range but a changed line in the block matches."""
        changed = {25: 'added'}
        after = [make_block('foo', 'fn', 20, 40, changed_lines=changed)]
        scope_entry = {'before_blocks': [], 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [25]}
        hunk_index = make_hunk_index([(25, 25)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]['scope_name'], 'foo')


class TestSortOrder(unittest.TestCase):
    """After blocks are returned sorted by scope_start."""

    def test_fallback_results_sorted(self):
        before = [
            make_block('beta', 'fn', 200, 250),
            make_block('alpha', 'fn', 10, 50),
        ]
        after = [
            make_block('alpha', 'fn', 15, 55),
            make_block('beta', 'fn', 500, 550),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [20, 210]}
        # Both miss after by coordinates
        hunk_index = make_hunk_index([(20, 900), (210, 900)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(a), 2)
        self.assertLess(a[0]['scope_start'], a[1]['scope_start'])
        self.assertEqual(a[0]['scope_name'], 'alpha')
        self.assertEqual(a[1]['scope_name'], 'beta')


class TestMixedScopeKinds(unittest.TestCase):
    """Scopes of different kinds (fn, struct, impl) in the same file."""

    def test_fn_and_struct(self):
        before = [
            make_block('Config', 'struct', 5, 20),
            make_block('run', 'fn', 25, 80),
        ]
        after = [
            make_block('Config', 'struct', 5, 25),
            make_block('run', 'fn', 30, 90),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [10, 30]}
        hunk_index = make_hunk_index([(10, 10), (30, 35)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 2)
        self.assertEqual(len(a), 2)
        after_pairs = {(bl['scope_name'], bl['scope_kind']) for bl in a}
        self.assertEqual(after_pairs, {('Config', 'struct'), ('run', 'fn')})

    def test_same_name_different_kind(self):
        """A struct 'Token' and fn 'Token' — treated as different scopes."""
        before = [
            make_block('Token', 'struct', 10, 30),
            make_block('Token', 'fn', 50, 70),
        ]
        after = [
            make_block('Token', 'struct', 10, 35),
            make_block('Token', 'fn', 200, 220),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [15, 55]}
        hunk_index = make_hunk_index([(15, 15), (55, 300)])  # fn Token misses by coords

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 2)
        self.assertEqual(len(a), 2)
        # struct Token matched by coords (15 in 10-35), fn Token by name fallback
        fn_block = next(bl for bl in a if bl['scope_kind'] == 'fn')
        self.assertEqual(fn_block['scope_start'], 200)


class TestOrphanBlocks(unittest.TestCase):
    """Module-level (orphan) scope blocks."""

    def test_orphan_matched_by_coordinates(self):
        before = [make_block('(module level)', 'module', 3, 7)]
        after = [make_block('(module level)', 'module', 3, 7)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [5]}
        hunk_index = make_hunk_index([(5, 5)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 1)
        self.assertEqual(len(a), 1)

    def test_orphan_fallback(self):
        """Orphan on before side, shifted on after side."""
        before = [make_block('(module level)', 'module', 3, 7)]
        after = [make_block('(module level)', 'module', 10, 14)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [5]}
        hunk_index = make_hunk_index([(5, 8)])  # 8 not in 10-14

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 1)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]['scope_start'], 10)


class TestMultipleHunksInOneScope(unittest.TestCase):
    """Several hunks all inside the same scope."""

    def test_deduplicates_scope(self):
        """Three hunks in the same fn -> still just one scope block per side."""
        before = [make_block('big_fn', 'fn', 10, 200)]
        after = [make_block('big_fn', 'fn', 10, 220)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}
        section = {'file': 'x.rs', 'lines': [20, 80, 150]}
        hunk_index = make_hunk_index([(20, 20), (80, 85), (150, 160)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        # All three old_start values fall within the same scope — should match once
        self.assertEqual(len(b), 1)
        self.assertEqual(len(a), 1)
        self.assertEqual(b[0]['scope_name'], 'big_fn')
        self.assertEqual(a[0]['scope_name'], 'big_fn')


class TestStatisticsScenario(unittest.TestCase):
    """Mirrors the real statistics.rs case: get_dashboard_data + get_statistics
    in one section, many hunks in get_statistics all miss on the after side
    because get_dashboard_data grew and pushed get_statistics down."""

    def _build_scenario(self):
        # Before: get_dashboard_data at 30-182, get_statistics at 185-592
        before = [
            make_block('get_dashboard_data', 'fn', 30, 182,
                       changed_lines={33: 'removed', 50: 'removed', 143: 'removed'}),
            make_block('get_statistics', 'fn', 185, 592,
                       changed_lines={
                           189: 'removed', 190: 'removed', 194: 'removed',
                           206: 'removed', 212: 'removed', 220: 'removed',
                           228: 'removed', 255: 'removed', 260: 'removed',
                           283: 'removed', 288: 'removed', 341: 'removed',
                       }),
        ]
        # After: get_dashboard_data grew to 205 (+23 lines from additions),
        # get_statistics pushed down to 210-580
        after = [
            make_block('get_dashboard_data', 'fn', 30, 205,
                       changed_lines={33: 'added', 51: 'added', 54: 'added',
                                      66: 'added', 145: 'added', 163: 'added'}),
            make_block('get_statistics', 'fn', 210, 580,
                       changed_lines={213: 'added', 215: 'added'}),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after}

        # Section covers hunks from BOTH functions
        lines = [33, 50, 143, 189, 206, 228, 255, 283, 341]
        # Hunk translations: dashboard hunks stay close, statistics hunks
        # translate to new_start values that land BETWEEN the two functions
        # (in the gap or before get_statistics starts at 210)
        hunk_index = make_hunk_index([
            (33, 33), (50, 51), (143, 145),       # dashboard hunks — land in dashboard
            (189, 195), (206, 200), (228, 205),    # statistics hunks — land BEFORE 210
            (255, 207), (283, 208), (341, 209),    # more statistics hunks — still before 210
        ])
        section = {'file': 'src/server/statistics.rs', 'lines': lines}
        return scope_entry, section, hunk_index

    def test_both_functions_present_on_after_side(self):
        """The core bug: after side must include get_statistics even when
        all its translated new_start values fall outside the after scope."""
        scope_entry, section, hunk_index = self._build_scenario()
        b, a = _match_scope_blocks(scope_entry, section, hunk_index)

        self.assertEqual(len(b), 2)
        self.assertEqual(len(a), 2)
        after_names = [bl['scope_name'] for bl in a]
        self.assertIn('get_dashboard_data', after_names)
        self.assertIn('get_statistics', after_names)

    def test_after_blocks_in_order(self):
        """get_dashboard_data (line 30) before get_statistics (line 210)."""
        scope_entry, section, hunk_index = self._build_scenario()
        _, a = _match_scope_blocks(scope_entry, section, hunk_index)

        self.assertEqual(a[0]['scope_name'], 'get_dashboard_data')
        self.assertEqual(a[1]['scope_name'], 'get_statistics')
        self.assertLess(a[0]['scope_start'], a[1]['scope_start'])

    def test_correct_after_scope_boundaries(self):
        """After-side blocks have the NEW file's line numbers, not the old."""
        scope_entry, section, hunk_index = self._build_scenario()
        _, a = _match_scope_blocks(scope_entry, section, hunk_index)

        dashboard = next(bl for bl in a if bl['scope_name'] == 'get_dashboard_data')
        stats = next(bl for bl in a if bl['scope_name'] == 'get_statistics')
        self.assertEqual(dashboard['scope_end'], 205)
        self.assertEqual(stats['scope_start'], 210)
        self.assertEqual(stats['scope_end'], 580)


class TestManyPureDeletionHunks(unittest.TestCase):
    """When a function is refactored by removing many scattered blocks,
    the after-side hunks have only context lines (no changed lines).
    The secondary changed_in_block check also fails."""

    def test_pure_deletion_hunks_after_still_matched(self):
        before = [make_block('compute', 'fn', 100, 400,
                             changed_lines={
                                 110: 'removed', 150: 'removed',
                                 200: 'removed', 250: 'removed',
                                 300: 'removed', 350: 'removed',
                             })]
        # After: the function is shorter (deletions removed lines),
        # and shifted to start at 130 due to additions above
        after = [make_block('compute', 'fn', 130, 380)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}

        # 6 hunks, all pure deletions; new_start values land OUTSIDE 130-380
        section = {'file': 'x.rs', 'lines': [110, 150, 200, 250, 300, 350]}
        hunk_index = make_hunk_index([
            (110, 105), (150, 120), (200, 125),
            (250, 126), (300, 128), (350, 129),
        ])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 1)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]['scope_name'], 'compute')
        self.assertEqual(a[0]['scope_start'], 130)

    def test_context_only_after_blocks_no_changed_line_match(self):
        """After block has zero changed lines — secondary check must also fail,
        so only the name fallback can save it."""
        before = [make_block('cleanup', 'fn', 50, 90,
                             changed_lines={60: 'removed', 70: 'removed'})]
        # After block: no changed lines at all (pure context)
        after = [make_block('cleanup', 'fn', 200, 240)]
        scope_entry = {'before_blocks': before, 'after_blocks': after}

        section = {'file': 'x.rs', 'lines': [60]}
        hunk_index = make_hunk_index([(60, 65)])  # 65 not in 200-240

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 1)
        self.assertEqual(len(a), 1)
        self.assertEqual(a[0]['scope_start'], 200)


class TestSectionWithOrphanAndFunction(unittest.TestCase):
    """Section covers both module-level imports (orphan) and a function,
    like the ticket_detail.rs case with use statements + download handler."""

    def test_orphan_plus_function(self):
        before = [
            make_block('(module level)', 'module', 12, 17,
                       changed_lines={15: 'removed'}),
            make_block('TicketDetailPage', 'fn', 19, 700,
                       changed_lines={25: 'removed', 677: 'removed', 680: 'removed'}),
        ]
        after = [
            make_block('(module level)', 'module', 12, 17,
                       changed_lines={15: 'added'}),
            make_block('TicketDetailPage', 'fn', 19, 710,
                       changed_lines={25: 'added', 677: 'added', 680: 'added',
                                      681: 'added', 682: 'added', 689: 'added'}),
        ]
        scope_entry = {'before_blocks': before, 'after_blocks': after}

        section = {'file': 'src/pages/ticket_detail.rs', 'lines': [15, 25, 674]}
        hunk_index = make_hunk_index([(15, 15), (25, 25), (674, 674)])

        b, a = _match_scope_blocks(scope_entry, section, hunk_index)
        self.assertEqual(len(b), 2)
        self.assertEqual(len(a), 2)
        after_names = {bl['scope_name'] for bl in a}
        self.assertEqual(after_names, {'(module level)', 'TicketDetailPage'})


if __name__ == '__main__':
    unittest.main()
