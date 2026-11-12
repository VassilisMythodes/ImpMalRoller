from typing import Optional
from constants import BOT_TOKEN

import discord
from discord import app_commands

from rolls import Participant
from roll_ui import MAX_ADVANTAGE, FateView, RollSetupView, log_expired_interaction


class MyClient(discord.Client):
    # Suppress error on the User attribute being None since it fills up later
    user: discord.ClientUser

    def __init__(self, *, intents: discord.Intents):
        # Names and comments are user-typed, so replies must never ping anyone.
        super().__init__(intents=intents, allowed_mentions=discord.AllowedMentions.none())
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


intents = discord.Intents.default()
client = MyClient(intents=intents)


@client.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    original = error.original if isinstance(error, app_commands.CommandInvokeError) else error
    if log_expired_interaction(interaction, original):
        return
    await app_commands.CommandTree.on_error(client.tree, interaction, error)


# The im_ prefix keeps these apart from the Servitor bot's /tiered and /opposed.
@client.tree.command(description="Imperium Maledictum d100 Test with SL; leave skill blank for guided setup.")
@app_commands.describe(
    skill='Your skill value, 1 to 999 (leave blank for guided setup)',
    test_adjustment='Added to your skill before rolling, e.g. 20 or -10',
    sl_adjustment='Added to your SL after rolling, e.g. 1 or -2',
    advantage='Reverse the dice if better; each Advantage after the first adds 10 to your skill',
    disadvantage='Reverse the dice if worse; each Disadvantage after the first takes 10 off your skill',
    roll='Force a specific roll',
    your_name='Your name for this test (defaults to your Discord display name)',
    skill_name='The skill you are testing (display only)',
    comment='What this test is for')
async def im_test(
    interaction: discord.Interaction,
    skill: Optional[app_commands.Range[int, 1, 999]] = None,
    test_adjustment: int = 0,
    sl_adjustment: int = 0,
    advantage: app_commands.Range[int, 0, MAX_ADVANTAGE] = 0,
    disadvantage: app_commands.Range[int, 0, MAX_ADVANTAGE] = 0,
    roll: Optional[app_commands.Range[int, 1, 100]] = None,
    your_name: Optional[app_commands.Range[str, 1, 100]] = None,
    comment: Optional[app_commands.Range[str, 1, 1000]] = None,
    skill_name: Optional[app_commands.Range[str, 1, 100]] = None):
    your = Participant(
        name=your_name or interaction.user.display_name,
        skill=skill,
        test_adjustment=test_adjustment,
        sl_adjustment=sl_adjustment,
        advantage=advantage,
        disadvantage=disadvantage,
        roll=roll,
        skill_name=skill_name or "",
    )
    if skill is None:
        view = RollSetupView(owner_id=interaction.user.id, your=your, comment=comment or "")
        await view.start(interaction)
        return

    await FateView(interaction.user.id, your, comment=comment).send(interaction)

@client.tree.command(description="Imperium Maledictum Opposed Test, highest SL wins; leave a skill blank for guided setup.")
@app_commands.describe(
    your_skill='Your skill value, 1 to 999 (leave blank for guided setup)',
    your_test_adjustment='Added to your skill before rolling, e.g. 20 or -10',
    your_sl_adjustment='Added to your SL after rolling, e.g. 1 or -2',
    your_advantage='Reverse the dice if better; each Advantage after the first adds 10 to your skill',
    your_disadvantage='Reverse the dice if worse; each Disadvantage after the first takes 10 off your skill',
    your_roll='Force a specific roll',
    opponent_skill='Opponent\'s skill value, 1 to 999 (leave blank for guided setup)',
    opponent_test_adjustment='Added to your opponent\'s skill before rolling',
    opponent_sl_adjustment='Added to your opponent\'s SL after rolling',
    opponent_advantage='Your opponent\'s Advantage',
    opponent_disadvantage='Your opponent\'s Disadvantage',
    opponent_roll='Force a specific roll',
    your_name='Your name for this test (defaults to your Discord display name)',
    opponent_name='Your opponent\'s name for this test',
    your_skill_name='The skill you are testing (display only)',
    opponent_skill_name='The skill your opponent is testing (display only)',
    comment='What this test is for')
async def im_opposed(
    interaction: discord.Interaction,
    your_skill: Optional[app_commands.Range[int, 1, 999]] = None,
    your_test_adjustment: int = 0,
    your_sl_adjustment: int = 0,
    your_advantage: app_commands.Range[int, 0, MAX_ADVANTAGE] = 0,
    your_disadvantage: app_commands.Range[int, 0, MAX_ADVANTAGE] = 0,
    your_roll: Optional[app_commands.Range[int, 1, 100]] = None,
    opponent_skill: Optional[app_commands.Range[int, 1, 999]] = None,
    opponent_test_adjustment: int = 0,
    opponent_sl_adjustment: int = 0,
    opponent_advantage: app_commands.Range[int, 0, MAX_ADVANTAGE] = 0,
    opponent_disadvantage: app_commands.Range[int, 0, MAX_ADVANTAGE] = 0,
    opponent_roll: Optional[app_commands.Range[int, 1, 100]] = None,
    your_name: Optional[app_commands.Range[str, 1, 100]] = None,
    opponent_name: Optional[app_commands.Range[str, 1, 100]] = None,
    comment: Optional[app_commands.Range[str, 1, 1000]] = None,
    your_skill_name: Optional[app_commands.Range[str, 1, 100]] = None,
    opponent_skill_name: Optional[app_commands.Range[str, 1, 100]] = None):
    your = Participant(
        name=your_name or interaction.user.display_name,
        skill=your_skill,
        test_adjustment=your_test_adjustment,
        sl_adjustment=your_sl_adjustment,
        advantage=your_advantage,
        disadvantage=your_disadvantage,
        roll=your_roll,
        skill_name=your_skill_name or "",
    )
    opponent = Participant(
        name=opponent_name or "Your opponent",
        skill=opponent_skill,
        test_adjustment=opponent_test_adjustment,
        sl_adjustment=opponent_sl_adjustment,
        advantage=opponent_advantage,
        disadvantage=opponent_disadvantage,
        roll=opponent_roll,
        skill_name=opponent_skill_name or "",
    )
    if your_skill is None or opponent_skill is None:
        view = RollSetupView(owner_id=interaction.user.id, your=your, opponent=opponent, comment=comment or "")
        await view.start(interaction)
        return

    await FateView(interaction.user.id, your, opponent, comment).send(interaction)


if __name__ == '__main__':
    client.run(BOT_TOKEN)
