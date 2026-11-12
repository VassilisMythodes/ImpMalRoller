"""Private, guided Discord forms for preparing a roll."""

from dataclasses import replace
import logging
import random
from typing import Optional

import discord

from rolls import Participant, build_opposed_result, build_test_result, resolve_test


log = logging.getLogger(__name__)
SETUP_TIMEOUT = 600
MAX_ADVANTAGE = 10


def log_expired_interaction(interaction: discord.Interaction, error: Exception) -> bool:
    if not isinstance(error, discord.NotFound) or error.code != 10062:
        return False
    age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
    log.warning(
        "Discord rejected interaction %s (10062; age %.2fs, gateway latency %.0fms). "
        "It may have expired or already been handled. If the form opened, check for "
        "another bot instance; otherwise retry the command or button.",
        interaction.id, age, interaction.client.latency * 1000,
    )
    # A rejected initial response cannot be repaired by replying to the same token.
    return True


def result_message(output: str) -> dict:
    # Long names and comments can push a result past Discord's 2000-character message limit.
    return {"content": output} if len(output) <= 2000 else {"embed": discord.Embed(description=output)}


def parse_integer(value: str, label: str, *, default: Optional[int] = None) -> Optional[int]:
    value = value.strip()
    if not value:
        return default
    try:
        # Avoid accepting Python-specific spellings such as 1_000.
        if not value.lstrip("+-").isdecimal():
            raise ValueError
        number = int(value)
    except ValueError:
        raise ValueError(f"{label} must be a whole number, such as 65 or -10.") from None
    if abs(number) > 2**53 - 1:
        raise ValueError(f"{label} is too large. Please enter a smaller whole number.")
    return number


def parse_roll(value: str, label: str) -> Optional[int]:
    number = parse_integer(value, label)
    if number is not None and not 1 <= number <= 100:
        raise ValueError(f"{label} must be between 1 and 100, or blank for a random roll.")
    return number


class SetupModal(discord.ui.Modal):
    def __init__(self, setup: "RollSetupView", title: str):
        super().__init__(title=title, timeout=SETUP_TIMEOUT)
        self.setup = setup

    def field(self, label: str, component, description: Optional[str] = None):
        self.add_item(discord.ui.Label(text=label, description=description, component=component))
        return component

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await self.setup.interaction_check(interaction)

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        await self.setup.on_error(interaction, error, None)


class ParticipantModal(SetupModal):
    def __init__(self, setup: "RollSetupView", opponent: bool = False):
        super().__init__(setup, "Opponent details" if opponent else "Your test details")
        self.opponent = opponent
        participant = setup.opponent if opponent else setup.your
        self.draft_key = "opponent" if opponent else "your"
        draft = setup.drafts.get(self.draft_key, {})
        self.name_input = self.field(
            "Character name",
            discord.ui.TextInput(
                default=draft.get("name", participant.name), required=False, max_length=100,
                placeholder="Leave blank to use the default name",
            ),
        )
        self.skill_input = self.field(
            "Skill",
            discord.ui.TextInput(
                default=draft.get("skill", "" if participant.skill is None else str(participant.skill)),
                max_length=3, placeholder="1 to 999, e.g. 65",
            ),
            "Your opponent's skill before adjustments." if opponent else "Your skill before adjustments.",
        )
        self.skill_name_input = self.field(
            "Skill name (optional)",
            discord.ui.TextInput(
                default=draft.get("skill_name", participant.skill_name), required=False,
                max_length=100, placeholder="e.g. Awareness or Melee",
            ),
        )
        self.test_adjustment_input = self.field(
            "Test adjustment (optional)",
            discord.ui.TextInput(
                default=draft.get("test_adjustment", str(participant.test_adjustment)), required=False,
                max_length=18, placeholder="e.g. +20 or -10; blank means 0",
            ),
            "Added to the skill before rolling.",
        )
        self.sl_adjustment_input = self.field(
            "SL adjustment (optional)",
            discord.ui.TextInput(
                default=draft.get("sl_adjustment", str(participant.sl_adjustment)), required=False,
                max_length=18, placeholder="e.g. +1 or -2; blank means 0",
            ),
            "Added to the SL after rolling.",
        )

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.setup.interaction_check(interaction):
            return
        participant = self.setup.opponent if self.opponent else self.setup.your
        draft = {
            "name": self.name_input.value.strip(),
            "skill": self.skill_input.value.strip(),
            "skill_name": self.skill_name_input.value.strip(),
            "test_adjustment": self.test_adjustment_input.value.strip(),
            "sl_adjustment": self.sl_adjustment_input.value.strip(),
        }
        self.setup.drafts[self.draft_key] = draft
        try:
            if not draft["skill"].isdecimal() or not 1 <= int(draft["skill"]) <= 999:
                raise ValueError("Skill must be a whole number from 1 to 999.")
            skill = int(draft["skill"])
            test_adjustment = parse_integer(draft["test_adjustment"], "Test adjustment", default=0)
            sl_adjustment = parse_integer(draft["sl_adjustment"], "SL adjustment", default=0)
        except ValueError as error:
            button = "Opponent details" if self.opponent else "Your details"
            await self.setup.show_panel(
                interaction, error=f"{error} Click **{button}** to correct it; your entries are saved."
            )
            return

        participant.name = draft["name"] or self.setup.default_names[self.draft_key]
        participant.skill = skill
        participant.skill_name = draft["skill_name"]
        participant.test_adjustment = test_adjustment
        participant.sl_adjustment = sl_adjustment
        del self.setup.drafts[self.draft_key]
        await self.setup.show_panel(interaction)


class AdvantageModal(SetupModal):
    def __init__(self, setup: "RollSetupView"):
        super().__init__(setup, "Advantage and Disadvantage")
        help_text = {
            "advantage": "Reverse the dice if better. Each one after the first adds 10 to the skill.",
            "disadvantage": "Reverse the dice if worse. Each one after the first takes 10 off the skill.",
        }
        self.selects = []
        for owner, participant in (("Your", setup.your), ("Opponent's", setup.opponent)):
            if participant is None:
                continue
            for kind in ("advantage", "disadvantage"):
                current = getattr(participant, kind)
                select = self.field(
                    f"{owner} {kind.title()}",
                    discord.ui.Select(options=[
                        discord.SelectOption(label=str(count), value=str(count), default=count == current)
                        for count in range(MAX_ADVANTAGE + 1)
                    ]),
                    help_text[kind],
                )
                self.selects.append((participant, kind, select))

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.setup.interaction_check(interaction):
            return
        for participant, kind, select in self.selects:
            if select.values:
                setattr(participant, kind, int(select.values[0]))
        await self.setup.show_panel(interaction)


class AdvancedModal(SetupModal):
    def __init__(self, setup: "RollSetupView"):
        super().__init__(setup, "Advanced options")
        draft = setup.drafts.get("advanced", {})
        self.comment_input = self.field(
            "What is this test for? (optional)",
            discord.ui.TextInput(
                default=draft.get("comment", setup.comment), required=False,
                max_length=1000, style=discord.TextStyle.paragraph,
                placeholder="e.g. Sneaking past the guards",
            ),
        )
        self.your_roll_input = self.field(
            "Your manual roll (optional)",
            discord.ui.TextInput(
                default=draft.get("your_roll", "" if setup.your.roll is None else str(setup.your.roll)),
                required=False, max_length=18, placeholder="1 to 100; blank means roll randomly",
            ),
            "Use this only to enter an already-rolled result.",
        )
        self.opponent_roll_input = None
        if setup.opponent is not None:
            self.opponent_roll_input = self.field(
                "Opponent's manual roll (optional)",
                discord.ui.TextInput(
                    default=draft.get("opponent_roll", "" if setup.opponent.roll is None else str(setup.opponent.roll)),
                    required=False, max_length=18, placeholder="1 to 100; blank means roll randomly",
                ),
            )

    async def on_submit(self, interaction: discord.Interaction):
        if not await self.setup.interaction_check(interaction):
            return
        draft = {
            "comment": self.comment_input.value.strip(),
            "your_roll": self.your_roll_input.value.strip(),
            "opponent_roll": self.opponent_roll_input.value.strip() if self.opponent_roll_input else "",
        }
        self.setup.drafts["advanced"] = draft
        try:
            your_roll = parse_roll(draft["your_roll"], "Your manual roll")
            opponent_roll = parse_roll(draft["opponent_roll"], "Opponent's manual roll")
        except ValueError as error:
            await self.setup.show_panel(
                interaction, error=f"{error} Click **Advanced options** to correct it; your entries are saved."
            )
            return
        self.setup.comment = draft["comment"]
        self.setup.your.roll = your_roll
        if self.setup.opponent is not None:
            self.setup.opponent.roll = opponent_roll
        del self.setup.drafts["advanced"]
        await self.setup.show_panel(interaction)


class RollSetupView(discord.ui.View):
    def __init__(
        self, owner_id: int, your: Participant, opponent: Optional[Participant] = None,
        comment: str = "",
    ):
        super().__init__(timeout=SETUP_TIMEOUT)
        self.owner_id = owner_id
        self.your = your
        self.opponent = opponent
        self.comment = comment
        self.default_names = {"your": your.name, "opponent": opponent.name if opponent else "Your opponent"}
        self.drafts = {}
        self.message = None
        self.finished = False
        if opponent is None:
            self.remove_item(self.edit_opponent)
            self.remove_item(self.opponent_fate)
        self.roll_button.disabled = not self.ready

    @property
    def command_name(self) -> str:
        return "im_opposed" if self.opponent is not None else "im_test"

    @property
    def ready(self) -> bool:
        participants = [self.your] if self.opponent is None else [self.your, self.opponent]
        return not self.drafts and all(participant.skill is not None for participant in participants)

    async def start(self, interaction: discord.Interaction):
        if self.opponent is None:
            await interaction.response.send_modal(ParticipantModal(self))
        else:
            await self.show_panel(interaction)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Start your own test to edit its details.", ephemeral=True)
            return False
        if self.finished or self.is_finished():
            await interaction.response.send_message(
                f"This setup has closed. Run `/{self.command_name}` to start another test.", ephemeral=True
            )
            return False
        return True

    def participant_summary(self, participant: Participant, *, opponent: bool = False) -> str:
        if participant.skill is None:
            return (
                "Click **Opponent details** to enter their skill." if opponent
                else "Click **Your details** to enter your skill."
            )
        lines = [f"**{discord.utils.escape_markdown(participant.name)}**"]
        if participant.skill_name:
            lines[0] += f" — {discord.utils.escape_markdown(participant.skill_name)}"
        lines.append(
            f"Skill: **{participant.skill}** | Test adjustment: **{participant.test_adjustment:+d}** | "
            f"SL adjustment: **{participant.sl_adjustment:+d}**"
        )
        lines.append(
            f"Advantage: **{participant.advantage}** | Disadvantage: **{participant.disadvantage}** | "
            f"Target: **{participant.target}**"
        )
        if participant.fate_advantage:
            lines.append("Spending Fate to gain Advantage")
        lines.append("Roll: random d100" if participant.roll is None else f"Manual roll: **{participant.roll}**")
        return "\n".join(lines)

    def summary(self) -> discord.Embed:
        embed = discord.Embed(
            title="Opposed Test" if self.opponent is not None else "Test",
            description="Check your details, then press **Roll** to share the result in this channel.",
            colour=discord.Colour.blurple(),
        )
        embed.add_field(name="Your details", value=self.participant_summary(self.your), inline=False)
        if self.opponent is not None:
            embed.add_field(
                name="Opponent details", value=self.participant_summary(self.opponent, opponent=True), inline=False
            )
        if self.comment:
            # Embed fields have a 1024-character limit; escaping can double the length.
            comment = discord.utils.escape_markdown(self.comment)
            embed.description += f"\n\n**Test:** {comment}"
        if self.drafts:
            labels = {"your": "Your details", "opponent": "Opponent details", "advanced": "Advanced options"}
            pending = ", ".join(labels[key] for key in self.drafts)
            embed.description += f"\n\nCorrect the saved entries in **{pending}** before rolling."
        embed.set_footer(text="Only you can see this setup. It closes after 10 minutes of inactivity.")
        return embed

    async def show_panel(self, interaction: discord.Interaction, error: Optional[str] = None):
        self.roll_button.disabled = not self.ready
        kwargs = dict(content=error, embed=self.summary(), view=self, allowed_mentions=discord.AllowedMentions.none())
        if self.message is None:
            await interaction.response.send_message(**kwargs, ephemeral=True)
        else:
            await interaction.response.edit_message(**kwargs)
        self.message = await interaction.original_response()

    @discord.ui.button(label="Your details", style=discord.ButtonStyle.primary, row=0)
    async def edit_your(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ParticipantModal(self))

    @discord.ui.button(label="Opponent details", style=discord.ButtonStyle.primary, row=0)
    async def edit_opponent(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ParticipantModal(self, opponent=True))

    @discord.ui.button(label="Advantage", style=discord.ButtonStyle.secondary, row=0)
    async def edit_advantage(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AdvantageModal(self))

    @discord.ui.button(label="Advanced options", style=discord.ButtonStyle.secondary, row=0)
    async def edit_advanced(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AdvancedModal(self))

    # Fate's Advantage must be spent before rolling; green while spent, press again to take it back.
    @discord.ui.button(label="Your Fate: Advantage", style=discord.ButtonStyle.secondary, row=1)
    async def your_fate(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.your.fate_advantage = not self.your.fate_advantage
        button.style = discord.ButtonStyle.success if self.your.fate_advantage else discord.ButtonStyle.secondary
        await self.show_panel(interaction)

    @discord.ui.button(label="Opponent Fate: Advantage", style=discord.ButtonStyle.secondary, row=1)
    async def opponent_fate(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.opponent.fate_advantage = not self.opponent.fate_advantage
        button.style = discord.ButtonStyle.success if self.opponent.fate_advantage else discord.ButtonStyle.secondary
        await self.show_panel(interaction)

    @discord.ui.button(label="Roll", style=discord.ButtonStyle.success, row=2)
    async def roll_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.submit_roll(interaction)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=2)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.finished = True
        self.stop()
        await interaction.response.edit_message(content="Test cancelled.", embed=None, view=None)

    async def submit_roll(self, interaction: discord.Interaction):
        if not await self.interaction_check(interaction):
            return
        if not self.ready:
            await interaction.response.send_message("Complete or correct the details before rolling.", ephemeral=True)
            return
        # Set before the first await so double clicks cannot publish two rolls.
        self.finished = True
        try:
            await FateView(self.owner_id, self.your, self.opponent, self.comment).send(interaction)
        except Exception:
            self.finished = False
            raise
        self.stop()
        if self.message is not None:
            try:
                await self.message.edit(content="Result posted to the channel.", embed=None, view=None)
            except discord.HTTPException:
                log.warning("Could not close the setup message after posting a roll.", exc_info=True)

    async def on_timeout(self):
        self.finished = True
        if self.message is not None:
            try:
                await self.message.edit(
                    content=f"This setup expired. Run `/{self.command_name}` to start again.", embed=None, view=None
                )
            except discord.HTTPException:
                pass  # The ephemeral message may have been dismissed or its token expired.

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        if log_expired_interaction(interaction, error):
            return
        log.error("Guided roll failed", exc_info=(type(error), error, error.__traceback__))
        message = f"I couldn't complete that action. Try again, or run `/{self.command_name}` for a new setup."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.NotFound as response_error:
            if not log_expired_interaction(interaction, response_error):
                raise


class FateButton(discord.ui.Button):
    def __init__(self, participant: Participant, reroll: bool, row: int):
        # Labels are capped at 80 characters.
        super().__init__(label=f"{participant.name[:60]}: Fate {'reroll' if reroll else '+1 SL'}", row=row)
        self.participant = participant
        self.reroll = reroll

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Anyone may be playing the opponent, so only the roller's own side is locked to them.
        if self.participant is self.view.your and interaction.user.id != self.view.owner_id:
            name = discord.utils.escape_markdown(self.participant.name)
            await interaction.response.send_message(f"Only the person who rolled can spend Fate for {name}.", ephemeral=True)
            return False
        return True

    async def callback(self, interaction: discord.Interaction):
        participant = self.participant
        before = participant.roll, participant.rerolls, participant.fate_sl
        if self.reroll:
            participant.rerolls += (participant.roll,)
            participant.roll = random.randint(1, 100)
        else:
            participant.fate_sl += 1
        try:
            await interaction.response.edit_message(**self.view.refresh())
        except Exception:
            # Nobody saw this spend, so take it back.
            participant.roll, participant.rerolls, participant.fate_sl = before
            self.view.refresh()
            raise
        self.view.interaction = interaction


class FateView(discord.ui.View):
    """A posted result with buttons to Spend Fate on each Test after it is rolled."""

    def __init__(
        self, owner_id: int, your: Participant, opponent: Optional[Participant] = None,
        comment: Optional[str] = None,
    ):
        # Under Discord's 15-minute limit for editing a reply, so the buttons can be removed.
        super().__init__(timeout=SETUP_TIMEOUT)
        self.owner_id = owner_id
        # Keep the dice so +1 SL adjusts this roll; copies leave the setup as it was if posting fails.
        self.your = replace(your, roll=your.roll or random.randint(1, 100))
        self.opponent = None if opponent is None else replace(opponent, roll=opponent.roll or random.randint(1, 100))
        self.comment = comment
        self.interaction = None
        for row, participant in enumerate(p for p in (self.your, self.opponent) if p is not None):
            self.add_item(FateButton(participant, True, row)).add_item(FateButton(participant, False, row))

    def refresh(self) -> dict:
        """Match the buttons to the current results and return the message to show."""
        for button in self.children:
            # Only a failed Test can be rerolled.
            button.disabled = button.reroll and resolve_test(button.participant)["success"]
        if self.opponent is None:
            output = build_test_result(self.your, self.comment)
        else:
            output = build_opposed_result(self.your, self.opponent, self.comment)
        # Clear whichever of content or embed an earlier, shorter or longer, version used.
        return {
            "content": None, "embed": None, **result_message(output), "view": self,
            "allowed_mentions": discord.AllowedMentions.none(),
        }

    async def send(self, interaction: discord.Interaction):
        await interaction.response.send_message(**self.refresh())
        self.interaction = interaction

    async def on_timeout(self):
        try:
            await self.interaction.edit_original_response(view=None)
        except discord.HTTPException:
            pass  # The result may have been deleted.

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        if not log_expired_interaction(interaction, error):
            await super().on_error(interaction, error, item)
