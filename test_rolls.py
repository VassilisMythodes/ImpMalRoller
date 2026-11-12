"""Results must match the Success Levels, Outcomes Table, Advantage, double and Opposed Test rules."""

import unittest

from rolls import Participant, build_opposed_result, build_test_result, format_sl, resolve_test


class SuccessLevelTests(unittest.TestCase):
    def check(self, cases, *keys):
        for fields, expected in cases:
            results = resolve_test(Participant("You", **fields))
            self.assertEqual(tuple(results[key] for key in keys), expected, fields)

    def test_success_levels(self):
        self.check([
            (dict(skill=72, roll=26), (5, True)),     # Rulebook example
            (dict(skill=54, roll=94), (-4, False)),   # Rulebook example
            (dict(skill=54, roll=52), (0, True)),     # +0
            (dict(skill=54, roll=57), (0, False)),    # -0
            (dict(skill=150, roll=26), (13, True)),   # Skills over 100 keep every tens value
            (dict(skill=999, roll=100), (89, True)),  # A roll of 100 has a tens value of 10
            (dict(skill=54, test_adjustment=20, roll=26), (5, True)),
            (dict(skill=54, sl_adjustment=1, roll=57), (1, True)),     # SL adjustments can turn a failure into a success...
            (dict(skill=54, sl_adjustment=-1, roll=52), (-1, False)),  # ...or a success into a failure
            (dict(skill=54, sl_adjustment=2, roll=74), (0, True)),     # Adjusting to 0 gives a Marginal Success
        ], "sl", "success")

    def test_advantage(self):
        self.check([
            (dict(skill=54, advantage=1, roll=62), (26, 54)),       # Advantage reverses the dice if better...
            (dict(skill=54, advantage=1, roll=26), (26, 54)),       # ...but never if worse
            (dict(skill=54, disadvantage=1, roll=26), (62, 54)),    # Disadvantage must reverse them if worse...
            (dict(skill=54, disadvantage=1, roll=62), (62, 54)),    # ...but never if better
            (dict(skill=54, advantage=2, disadvantage=2, roll=62), (62, 54)),  # They cancel 1:1
            (dict(skill=54, advantage=3, roll=62), (26, 74)),       # Each Advantage after the first adds 10
            (dict(skill=54, advantage=1, disadvantage=4, roll=26), (62, 34)),  # Each extra Disadvantage takes 10
            (dict(skill=54, advantage=1, roll=10), (1, 54)),        # 10 reverses to 01...
            (dict(skill=54, disadvantage=1, roll=1), (10, 54)),     # ...and 01 to 10
            (dict(skill=54, disadvantage=1, roll=100), (100, 54)),  # 00 + 0 stays 100
        ], "roll", "target")

    def test_doubles(self):
        self.check([
            (dict(skill=54, roll=44), (True, True)),     # Critical
            (dict(skill=54, roll=55), (True, False)),    # Fumble
            (dict(skill=54, roll=100), (True, False)),   # 00 + 0 is a double too
            (dict(skill=150, roll=100), (True, True)),
            (dict(skill=54, roll=45), (False, True)),
            (dict(skill=54, roll=10), (False, True)),
            (dict(skill=54, sl_adjustment=1, roll=55), (True, True)),  # Adjusted into a success, so a critical
        ], "double", "success")

    def test_outcomes_table(self):
        rows = {
            (6, True): "**Astounding Success** (+6 SL)",
            (5, True): "**Astounding Success** (+5 SL)",
            (4, True): "**Impressive Success** (+4 SL)",
            (3, True): "**Impressive Success** (+3 SL)",
            (2, True): "**Success** (+2 SL)",
            (1, True): "**Success** (+1 SL)",
            (0, True): "**Marginal Success** (+0 SL)",
            (0, False): "**Marginal Failure** (-0 SL)",
            (-1, False): "**Failure** (-1 SL)",
            (-2, False): "**Failure** (-2 SL)",
            (-3, False): "**Impressive Failure** (-3 SL)",
            (-4, False): "**Impressive Failure** (-4 SL)",
            (-5, False): "**Astounding Failure** (-5 SL)",
            (-6, False): "**Astounding Failure** (-6 SL)",
        }
        for (sl, success), text in rows.items():
            self.assertEqual(format_sl(sl, success), text)

    def test_test_message(self):
        message = build_test_result(
            Participant("Ana", 54, test_adjustment=20, sl_adjustment=-1, advantage=2, roll=62, skill_name="Stealth"),
            comment="Sneaking past the guards",
        )
        self.assertEqual(message, (
            "**Test:** Sneaking past the guards\n"
            "\n**Ana** rolled: **62**, reversed to **26**, with a target of **84** (skill: **54**, "
            "test adjustment: **+20**, Advantage ×2: **+10**, SL adjustment: **-1**)"
            "\n**Astounding Success** (+5 SL) on **Stealth**!"
        ))
        self.assertTrue(build_test_result(Participant("Ana", 54, roll=44)).endswith("! **Critical!**"))
        self.assertTrue(build_test_result(Participant("Ana", 54, roll=55)).endswith("! **Fumble!**"))

    def test_fate(self):
        self.check([
            (dict(skill=54, fate_advantage=True, roll=62), (26, 54)),                # Fate's Advantage reverses the dice...
            (dict(skill=54, advantage=1, fate_advantage=True, roll=62), (26, 64)),   # ...and stacks with other Advantage
        ], "roll", "target")
        self.check([
            (dict(skill=54, fate_sl=1, roll=57), (1, True)),                     # +1 SL can turn -0 into a success
            (dict(skill=54, sl_adjustment=-1, fate_sl=1, roll=57), (0, True)),   # -0, -1, then +1 lands on 0
        ], "sl", "success")
        message = build_test_result(Participant("Ana", 54, roll=62, fate_advantage=True, rerolls=(88,), fate_sl=1))
        self.assertTrue(message.endswith("\nFate spent: **3** (Advantage, rerolled **88**, +1 SL)"), message)

    def test_opposed_verdicts(self):
        cases = [
            # Rulebook example: -1 SL beats -3 SL by 2 SL, though both Tests fail.
            (dict(roll=61), dict(roll=83), "**You** wins the Opposed Test: **Success** (+2 SL)!"),
            (dict(roll=52), dict(roll=57), "**You** wins the Opposed Test: **Marginal Success** (+0 SL)!"),
            (dict(roll=52), dict(roll=52), "**You** and **Your opponent** are tied."),
            # Each side's modifiers only change its own Test: -0 - 1 = -1 SL against +6 + 1 = +7 SL.
            (dict(roll=57, sl_adjustment=-1), dict(roll=26, test_adjustment=30, sl_adjustment=1),
             "**Your opponent** wins the Opposed Test: **Astounding Success** (+8 SL)!"),
        ]
        for yours, theirs, verdict in cases:
            result = build_opposed_result(Participant("You", 54, **yours), Participant("Your opponent", 54, **theirs))
            self.assertTrue(result.endswith("\n\n" + verdict), result)


if __name__ == "__main__":
    unittest.main()
