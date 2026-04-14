import pytest

from backend.app.models.enums import StrategyStatus, validate_transition, VALID_TRANSITIONS


class TestStrategyStatus:
    def test_all_states_present(self):
        assert len(StrategyStatus) == 13

    def test_terminal_states(self):
        terminals = StrategyStatus.terminal_states()
        assert terminals == frozenset({
            StrategyStatus.SKEPTIC_FAILED,
            StrategyStatus.PAPER_FAILED,
            StrategyStatus.KILLED,
            StrategyStatus.RETIRED,
        })

    def test_terminal_states_have_no_outgoing_transitions(self):
        for state in StrategyStatus.terminal_states():
            assert VALID_TRANSITIONS[state] == frozenset(), (
                f"Terminal state {state} has outgoing transitions"
            )

    def test_kill_switch_states(self):
        assert StrategyStatus.kill_switch_states() == frozenset({
            StrategyStatus.LIVE,
            StrategyStatus.PAPER_TRADING,
            StrategyStatus.HALTED,
        })

    def test_valid_forward_transitions(self):
        valid_cases = [
            (StrategyStatus.GENERATED, StrategyStatus.BACKTESTING),
            (StrategyStatus.BACKTESTING, StrategyStatus.BACKTESTED),
            (StrategyStatus.BACKTESTED, StrategyStatus.SKEPTIC_PENDING),
            (StrategyStatus.SKEPTIC_PENDING, StrategyStatus.SKEPTIC_PASSED),
            (StrategyStatus.SKEPTIC_PENDING, StrategyStatus.SKEPTIC_FAILED),
            (StrategyStatus.SKEPTIC_PASSED, StrategyStatus.PAPER_TRADING),
            (StrategyStatus.PAPER_TRADING, StrategyStatus.PAPER_PASSED),
            (StrategyStatus.PAPER_TRADING, StrategyStatus.PAPER_FAILED),
            (StrategyStatus.PAPER_PASSED, StrategyStatus.LIVE),
            (StrategyStatus.LIVE, StrategyStatus.HALTED),
            (StrategyStatus.HALTED, StrategyStatus.LIVE),
            (StrategyStatus.LIVE, StrategyStatus.KILLED),
            (StrategyStatus.PAPER_TRADING, StrategyStatus.KILLED),
            (StrategyStatus.HALTED, StrategyStatus.KILLED),
        ]
        for current, target in valid_cases:
            assert validate_transition(current, target), (
                f"Expected valid: {current.value} → {target.value}"
            )

    def test_invalid_transitions_rejected(self):
        invalid_cases = [
            (StrategyStatus.GENERATED, StrategyStatus.LIVE),
            (StrategyStatus.GENERATED, StrategyStatus.PAPER_TRADING),
            (StrategyStatus.BACKTESTED, StrategyStatus.LIVE),
            (StrategyStatus.SKEPTIC_FAILED, StrategyStatus.SKEPTIC_PASSED),
            (StrategyStatus.PAPER_FAILED, StrategyStatus.PAPER_TRADING),
            (StrategyStatus.KILLED, StrategyStatus.LIVE),
            (StrategyStatus.RETIRED, StrategyStatus.GENERATED),
            (StrategyStatus.PAPER_PASSED, StrategyStatus.BACKTESTING),
        ]
        for current, target in invalid_cases:
            assert not validate_transition(current, target), (
                f"Expected invalid: {current.value} → {target.value}"
            )

    def test_retire_from_non_terminal(self):
        non_terminal = [
            s for s in StrategyStatus if s not in StrategyStatus.terminal_states()
        ]
        for state in non_terminal:
            assert validate_transition(state, StrategyStatus.RETIRED), (
                f"Should be able to retire from {state.value}"
            )

    def test_all_states_in_transition_table(self):
        for state in StrategyStatus:
            assert state in VALID_TRANSITIONS, (
                f"{state.value} missing from transition table"
            )

    def test_enum_values_are_strings(self):
        for state in StrategyStatus:
            assert isinstance(state.value, str)
            assert state.value == state.value.lower()
