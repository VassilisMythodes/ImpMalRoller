"""Imperium Maledictum d100 Tests: Success Levels, Advantage, criticals and Opposed Tests."""

from dataclasses import dataclass
import random
from typing import Optional


@dataclass
class Participant:
    name: str
    skill: Optional[int] = None
    test_adjustment: int = 0
    sl_adjustment: int = 0
    advantage: int = 0
    disadvantage: int = 0
    roll: Optional[int] = None
    skill_name: str = ""
    # Fate spent: Advantage before rolling, then rerolls (the rolls they replaced) and +1 SL each.
    fate_advantage: bool = False
    rerolls: tuple[int, ...] = ()
    fate_sl: int = 0

    @property
    def net_advantage(self) -> int:
        """Advantage (one may come from Fate) and Disadvantage cancel each other out 1:1; below 0 means Disadvantage."""
        return self.advantage + self.fate_advantage - self.disadvantage

    @property
    def target(self) -> int:
        """Skill plus test adjustment, then 10 more (or less) per net Advantage (or Disadvantage) after the first."""
        extra = 10 * max(abs(self.net_advantage) - 1, 0)
        return self.skill + self.test_adjustment + (extra if self.net_advantage > 0 else -extra)


def resolve_test(participant: Participant) -> dict:
    """Roll d100 against the participant's target, then apply any SL adjustment to the result."""
    rolled = random.randint(1, 100) if participant.roll is None else participant.roll
    # 100 is 00 on the tens die and 0 on the units die.
    tens_die, units_die = rolled // 10 % 10, rolled % 10
    roll = rolled
    if participant.net_advantage:
        reversed_roll = units_die * 10 + tens_die or 100
        # Lower is never worse: Advantage may reverse the dice if better, Disadvantage must if worse.
        roll = min(rolled, reversed_roll) if participant.net_advantage > 0 else max(rolled, reversed_roll)

    target = participant.target
    # Tens values: a target of 72 gives 7, 150 gives 15, and a roll of 100 gives 10.
    sl = target // 10 - roll // 10
    success = roll <= target
    # Not summed first: an adjustment of -1 and +1 from Fate still land on 0, which is never -0.
    if participant.sl_adjustment or participant.fate_sl:
        sl += participant.sl_adjustment + participant.fate_sl
        # Adjustments can flip the result, and one that lands on 0 is a Marginal Success (+0).
        success = sl >= 0
    # Doubles read the same reversed; a successful one is a critical and a failed one a fumble.
    return {"rolled": rolled, "roll": roll, "target": target, "sl": sl, "success": success,
            "double": tens_die == units_die}


def format_sl(sl: int, success: bool) -> str:
    """Name an SL from the Outcomes Table, e.g. '**Impressive Success** (+3 SL)'."""
    size = abs(sl)
    degree = "Astounding " if size >= 5 else "Impressive " if size >= 3 else "" if size >= 1 else "Marginal "
    # Successes never have a negative SL nor failures a positive one, so this also tells +0 from -0.
    sign, outcome = ("+", "Success") if success else ("-", "Failure")
    return f"**{degree}{outcome}** ({sign}{size} SL)"


def format_test_result(participant: Participant, results: dict) -> str:
    net = participant.net_advantage
    bonus = results["target"] - participant.skill - participant.test_adjustment
    details = []
    if participant.test_adjustment or bonus:
        details.append(f"skill: **{participant.skill}**")
    if participant.test_adjustment:
        details.append(f"test adjustment: **{participant.test_adjustment:+d}**")
    if net:
        details.append(("Advantage" if net > 0 else "Disadvantage") + (f" ×{abs(net)}: **{bonus:+d}**" if bonus else ""))
    if participant.sl_adjustment:
        details.append(f"SL adjustment: **{participant.sl_adjustment:+d}**")
    details_suffix = f" ({', '.join(details)})" if details else ""
    reversal = f", reversed to **{results['roll']}**," if results["roll"] != results["rolled"] else ""
    skill_suffix = f" on **{participant.skill_name}**" if participant.skill_name else ""
    double = (" **Critical!**" if results["success"] else " **Fumble!**") if results["double"] else ""
    fate = (["Advantage"] if participant.fate_advantage else []) + [
        f"rerolled **{roll}**" for roll in participant.rerolls
    ] + ["+1 SL"] * participant.fate_sl
    fate_suffix = f"\nFate spent: **{len(fate)}** ({', '.join(fate)})" if fate else ""
    return (
        f"\n**{participant.name}** rolled: **{results['rolled']}**{reversal} with a target of "
        f"**{results['target']}**{details_suffix}"
        f"\n{format_sl(results['sl'], results['success'])}{skill_suffix}!{double}{fate_suffix}"
    )


def build_test_result(your: Participant, comment: Optional[str] = None) -> str:
    """Resolve a single Test and return its public result message."""
    results_str = format_test_result(your, resolve_test(your))
    if comment:
        results_str = f"**Test:** {comment}\n{results_str}"
    return results_str


def build_opposed_result(your: Participant, opponent: Participant, comment: Optional[str] = None) -> str:
    """Resolve both Tests; the highest SL wins, and the difference in SL is the winner's final SL."""
    yours, theirs = resolve_test(your), resolve_test(opponent)

    # At equal SL a Marginal Success (+0) still beats a Marginal Failure (-0).
    your_rank, their_rank = (yours["sl"], yours["success"]), (theirs["sl"], theirs["success"])
    if your_rank == their_rank:
        # The Opposed Test rules give no tiebreak, so the GM settles it.
        winner_str = f"**{your.name}** and **{opponent.name}** are tied."
    else:
        winner = your if your_rank > their_rank else opponent
        winner_str = f"**{winner.name}** wins the Opposed Test: {format_sl(abs(yours['sl'] - theirs['sl']), True)}!"

    final_output = format_test_result(your, yours) + "\n" + format_test_result(opponent, theirs) + "\n\n" + winner_str
    if comment:
        final_output = f"**Test:** {comment}\n{final_output}"

    return final_output
