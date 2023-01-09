from discord import Guild, TextChannel, RawReactionActionEvent, utils, Message, File, Interaction, Embed, Colour, Thread
from discord.errors import NotFound, Forbidden, HTTPException, InvalidData
from discord.ext import commands

import config
from helpers import db
from helpers.component_globals import ComponentBase
from main import MadiBot


class StarboardView(ComponentBase):
    def __init__(self, msg: Message):
        super().__init__(timeout=None)

        # Add our link to the original message
        self.add_link_button("Message", msg.jump_url)


class Starboard(commands.Cog, name="Starboard"):
    def __init__(self, bot):
        self.bot: MadiBot = bot
        self.guild: Guild | None = None
        self.starboard_channel: TextChannel | None = None
        self.starboarded_messages: list = []
        self.starboard_msg_ids: list = []

    @commands.Cog.listener()
    async def on_ready(self):
        self.guild: Guild = self.bot.get_guild(config.guild_id)
        self.starboard_channel: TextChannel = self.guild.get_channel(config.starboard_channel)

        if starboard_db := db.get_starboard_db():
            self.starboarded_messages = starboard_db["message_ids"]
            if "starboard_msg_ids" in starboard_db:
                self.starboard_msg_ids = starboard_db["starboard_msg_ids"]
        else:
            db.create_starboard_db()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: RawReactionActionEvent):
        print(payload.emoji.name)
        try:
            channel: TextChannel | Thread = await self.guild.fetch_channel(payload.channel_id)
            if (getattr(channel, "id", 0) not in config.starboard_allowed_channels) and (
                getattr(channel, "category_id", 0) not in config.starboard_allowed_channels
            ):
                print("channel not allowed, returning")
                return
            msg: Message = await channel.fetch_message(payload.message_id)
        except (NotFound, Forbidden, HTTPException, InvalidData):
            print("channel/msg not found, returning")
            return
        for reaction in msg.reactions:
            if reaction.emoji == '⭐' and hasattr(reaction, "count"):
                if reaction.count >= config.starboard_required_reactions and msg.id not in self.starboarded_messages:
                    await self.post_starboard_msg(msg)
                    self.starboarded_messages.append(msg.id)
                    return db.update_starboard_db("message_ids", self.starboarded_messages)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload):
        if payload.message_id not in [msg[0] for msg in self.starboard_msg_ids]:
            return
        starboard_msg = await self.find_starboard_msg(payload.message_id)
        original_channel = self.bot.get_channel(payload.channel_id)
        original_msg = await original_channel.fetch_message(payload.message_id)
        if starboard_msg:
            await self.edit_starboard_msg(starboard_msg, original_msg)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        starboarded_msg_ids = [id_pair[0] for id_pair in self.starboard_msg_ids]
        if payload.message_id not in starboarded_msg_ids:
            return
        msg = await self.starboard_channel.fetch_message(self.starboard_msg_ids[starboarded_msg_ids.index(payload.message_id)][1])
        await msg.delete()

    @staticmethod
    async def starboard_file(msg):
        if len(msg.attachments) > 0:
            if msg.attachments[0].content_type.startswith("video/"):
                attachment_file: File = await msg.attachments[0].to_file()
                return attachment_file

    @commands.Cog.listener()
    async def on_interaction(self, interaction: Interaction):
        if "custom_id" not in interaction.data:
            return
        if not interaction.data["custom_id"].startswith("sb"):
            return
        interaction_type, channel_id, msg_id, edited_msg_id = interaction.data["custom_id"].split('_')
        await interaction.response.defer()
        msg = await interaction.guild.get_channel(int(channel_id)).fetch_message(int(msg_id))
        starboard_msg = None
        if int(edited_msg_id):
            starboard_msg = await self.starboard_channel.fetch_message(int(edited_msg_id))
        if interaction_type == "sbapproved":
            # We're approving it, but first we need to do things differently whether or not we're editing a message!
            if starboard_msg:
                await self.edit_starboard_msg(starboard_msg, msg)
            else:
                await self.post_starboard_msg(msg)

    async def find_starboard_msg(self, msg_id: int):
        msg_tuple = utils.find(lambda msg: msg[0] == msg_id, self.starboard_msg_ids)
        try:
            starboard_msg = await self.starboard_channel.fetch_message(msg_tuple[1])
        except NotFound:
            self.starboard_msg_ids.remove(msg_tuple)
            return db.update_starboard_db("starboard_msg_ids", self.starboard_msg_ids)
        return starboard_msg

    async def post_starboard_msg(self, msg):
        sb_msg = await self.starboard_channel.send(
            embed=self.create_starboard_embed(msg),
            file=await self.starboard_file(msg),
            view=StarboardView(msg))
        self.starboard_msg_ids.append((msg.id, sb_msg.id))
        db.update_starboard_db("starboard_msg_ids", self.starboard_msg_ids)

    async def edit_starboard_msg(self, starboard_msg, msg):
        await starboard_msg.edit(
            embed=self.create_starboard_embed(msg),
            view=StarboardView(msg))

    @staticmethod
    def create_starboard_embed(msg: Message, edited: bool = False):
        embed = Embed(title="Edited Message!" if edited else "", description=msg.content[:1000],
                      colour=Colour.blue() if edited else Colour.gold(), )
        embed.set_author(name=msg.author.display_name, icon_url=str(msg.author.display_avatar.url).replace(".webp", ".png"))
        embed.set_footer(text=f"#{msg.channel.name} - Message shortened to 1000 characters.")
        if len(msg.attachments) > 0:
            embed.set_image(url=msg.attachments[0].url)
        return embed


async def setup(client):
    await client.add_cog(Starboard(client))
