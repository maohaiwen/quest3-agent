"""Tests for Werewolf sandbox with sub-phase flow and shared agents."""
import asyncio
import pytest
from app.sandboxes.werewolf import (
    WerewolfSandbox, WEREWOLF, SEER, WITCH, GUARD, VILLAGER, HUNTER,
    NIGHT_WEREWOLF, NIGHT_SEER, NIGHT_WITCH, NIGHT_GUARD, DAY_VOTE, GAME_OVER,
)


def _make_agents(n: int, same_agent: bool = False):
    """Create test agent info list."""
    agent_id = "shared_agent" if same_agent else None
    return [
        {"agent_id": agent_id or f"agent_{i}", "role": f"participant_{i}"}
        for i in range(n)
    ]


@pytest.fixture
def sandbox_6():
    """6-player werewolf sandbox with shared agent."""
    s = WerewolfSandbox()
    s.on_task_start(_make_agents(6, same_agent=True))
    return s


def _find_by_role(sandbox, game_role):
    """Find a player by game role."""
    for p in sandbox.players.values():
        if p.game_role == game_role:
            return p
    return None


def _find_wolves(sandbox):
    """Find all werewolf players."""
    return [p for p in sandbox.players.values() if p.is_werewolf]


@pytest.mark.asyncio
async def test_shared_agent_players_unique(sandbox_6):
    """All 6 participants should be stored even with the same agent_id."""
    assert len(sandbox_6.players) == 6


@pytest.mark.asyncio
async def test_active_participants_werewolf_phase(sandbox_6):
    """Only werewolves should be active during NIGHT_WEREWOLF."""
    active = sandbox_6.get_active_participants()
    wolves = _find_wolves(sandbox_6)
    assert len(active) == len(wolves)
    active_roles = {a[0] for a in active}
    wolf_roles = {w.indexed_role for w in wolves}
    assert active_roles == wolf_roles


@pytest.mark.asyncio
async def test_active_participants_seer_phase(sandbox_6):
    """Only seer should be active during NIGHT_SEER."""
    # Advance to seer phase by having all wolves vote
    wolves = _find_wolves(sandbox_6)
    for w in wolves:
        target = next(p for p in sandbox_6.players.values()
                      if p.alive and not p.is_werewolf)
        await sandbox_6.handle_action("shared_agent", w.indexed_role, "night_action",
                                      target=str(target.seat))
    assert sandbox_6.phase == NIGHT_SEER

    active = sandbox_6.get_active_participants()
    seer = _find_by_role(sandbox_6, SEER)
    assert len(active) == 1
    assert active[0][0] == seer.indexed_role


async def _complete_night(sandbox):
    """Helper: complete one full night cycle."""
    wolves = _find_wolves(sandbox)
    # Pick a non-wolf target for wolves (not a wolf)
    non_wolf = next(p for p in sandbox.players.values()
                    if p.alive and not p.is_werewolf)
    for w in wolves:
        await sandbox.handle_action("shared_agent", w.indexed_role, "night_action",
                                    target=str(non_wolf.seat))

    # Seer checks someone (not themselves)
    seer = _find_by_role(sandbox, SEER)
    seer_target = next(p for p in sandbox.players.values()
                       if p.alive and p.indexed_role != seer.indexed_role)
    await sandbox.handle_action("shared_agent", seer.indexed_role, "night_action",
                                target=str(seer_target.seat))

    # Witch skips
    witch = _find_by_role(sandbox, WITCH)
    await sandbox.handle_action("shared_agent", witch.indexed_role, "night_action",
                                witch_action="skip")

    # Guard protects someone
    guard = _find_by_role(sandbox, GUARD)
    guard_target = next(p for p in sandbox.players.values()
                        if p.alive and p.indexed_role != guard.indexed_role)
    await sandbox.handle_action("shared_agent", guard.indexed_role, "night_action",
                                target=str(guard_target.seat))


@pytest.mark.asyncio
async def test_full_night_cycle_6_players(sandbox_6):
    """Complete a full night cycle with 6 players."""
    await _complete_night(sandbox_6)
    # Should have transitioned to day
    assert sandbox_6.phase == DAY_VOTE


@pytest.mark.asyncio
async def test_day_vote_advances_round(sandbox_6):
    """After all votes, round number should increment."""
    await _complete_night(sandbox_6)

    assert sandbox_6.phase == DAY_VOTE
    initial_round = sandbox_6.round_num

    # All alive players vote for a non-wolf target
    non_wolf = next(p for p in sandbox_6.players.values()
                    if not p.is_werewolf)
    target_seat = str(non_wolf.seat)
    for p in sandbox_6.players.values():
        if p.alive:
            await sandbox_6.handle_action("shared_agent", p.indexed_role, "vote",
                                          target=target_seat)

    # Round should have advanced
    assert sandbox_6.round_num > initial_round or sandbox_6.phase == GAME_OVER


@pytest.mark.asyncio
async def test_sub_phase_support():
    """WerewolfSandbox should support sub-phases."""
    s = WerewolfSandbox()
    assert s.supports_sub_phases is True


@pytest.mark.asyncio
async def test_html_visualization(sandbox_6):
    """get_display_state should return valid HTML."""
    state = sandbox_6.get_display_state()
    assert "html" in state
    assert "1号" in state["html"]
    assert "6号" in state["html"]


@pytest.mark.asyncio
async def test_state_view_per_role(sandbox_6):
    """get_state_view should show different info per role."""
    wolf = _find_wolves(sandbox_6)[0]
    seer = _find_by_role(sandbox_6, SEER)

    wolf_view = sandbox_6.get_state_view("shared_agent", wolf.indexed_role)
    seer_view = sandbox_6.get_state_view("shared_agent", seer.indexed_role)

    assert "狼人" in wolf_view
    assert "狼队友" in wolf_view
    assert "预言家" in seer_view


@pytest.mark.asyncio
async def test_8_player_with_hunter():
    """8-player game should include hunter."""
    s = WerewolfSandbox()
    s.on_task_start(_make_agents(8))
    hunter = _find_by_role(s, HUNTER)
    assert hunter is not None
    assert len(s.players) == 8


def test_anonymize_identities():
    """Sandbox should provide seat-based anonymous identity."""
    s = WerewolfSandbox()
    s.on_task_start(_make_agents(6))
    assert s.anonymize_identities is True
    # First player should be seat 1
    first_role = "participant_0"
    identity = s.get_anonymous_identity(first_role)
    assert identity["agent_id"] == "seat_1"
    assert identity["display_name"] == "1号玩家"
    assert identity["role"] == "seat_1"
