import asyncio
import csv
import datetime
import json
import sys
from pathlib import Path

import discord
from discord import app_commands, Embed
from discord.ext import commands, tasks


TZ = datetime.timezone(datetime.timedelta(hours=8))
DEFAULT_ALLOWED_COUNTRIES = [
    "美國",
    "英國",
    "歐洲",
    "德國",
    "澳洲",
    "加拿大",
    "紐西蘭",
    "日本",
]
CONFIG_DEFAULTS = {
    "discord_bot_token": "",
    "Guild": 0,
    "Thread": 0,
    "allowed_countries": DEFAULT_ALLOWED_COUNTRIES,
    "reminder_minutes": 10,
}


class Reminder:
    def __init__(self, bot, target_datetime, event_datetime, event_info):
        self.bot = bot
        self.target_datetime = target_datetime
        self.event_datetime = event_datetime
        self.event_info = event_info
        self.task = None

    def start(self):
        self.task = asyncio.create_task(self.run())

    def cancel(self):
        if self.task and not self.task.done():
            self.task.cancel()

    async def run(self):
        seconds_until_target = (
            self.target_datetime - datetime.datetime.now(TZ)
        ).total_seconds()
        if seconds_until_target > 0:
            await asyncio.sleep(seconds_until_target)
        await self.bot.send_event_alert(self.event_datetime, self.target_datetime, self.event_info)


class MarketAlertBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

        self.base_dir = Path(__file__).resolve().parent
        self.config_path = self.base_dir / "config.json"
        self.data_path = self.base_dir / "data" / "calendar.csv"
        self.config = self.load_config()
        self.reminders = []
        self.ready_once = False

    def load_config(self):
        with self.config_path.open(encoding="utf8") as config_file:
            raw_config = json.load(config_file)

        config = CONFIG_DEFAULTS.copy()
        config.update(raw_config)
        config["allowed_countries"] = [
            country.strip()
            for country in config.get("allowed_countries", DEFAULT_ALLOWED_COUNTRIES)
            if country and country.strip()
        ]
        config["reminder_minutes"] = int(config.get("reminder_minutes", 10))
        return config

    def save_config(self):
        with self.config_path.open("w", encoding="utf8") as config_file:
            json.dump(self.config, config_file, ensure_ascii=False, indent=4)

    async def setup_hook(self):
        await self.add_cog(AdminCommands(self))
        await self.sync_commands()

        if not self.daily_refresh.is_running():
            self.daily_refresh.start()

    async def sync_commands(self):
        guild_id = int(self.config.get("Guild", 0) or 0)
        if guild_id:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"[Info] Synced slash commands to guild {guild_id}")
        else:
            await self.tree.sync()
            print("[Info] Synced global slash commands")

    async def on_ready(self):
        print(f"[Info] Logged in as {self.user}")
        game = discord.Game("MarketAlert")
        await self.change_presence(status=discord.Status.online, activity=game)

        if not self.ready_once:
            self.ready_once = True
            try:
                await self.reload_reminders(notify=True, reason="Bot started")
            except Exception as exc:
                print(f"[Error] Failed to load reminders on startup: {exc}")

    @tasks.loop(time=datetime.time(hour=0, minute=0, tzinfo=TZ))
    async def daily_refresh(self):
        try:
            await self.reload_reminders(notify=True, reason="Daily refresh")
        except Exception as exc:
            print(f"[Error] Daily refresh failed: {exc}")

    @daily_refresh.before_loop
    async def before_daily_refresh(self):
        await self.wait_until_ready()

    async def run_market_worm(self):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(self.base_dir / "MarketWorm.py"),
            cwd=str(self.base_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        stdout_text = stdout.decode("utf8", errors="ignore").strip()
        stderr_text = stderr.decode("utf8", errors="ignore").strip()

        if process.returncode != 0 or "ERROR:" in stdout_text:
            raise RuntimeError(stderr_text or stdout_text or "MarketWorm failed")

    def cancel_reminders(self):
        for reminder in self.reminders:
            reminder.cancel()
        self.reminders.clear()

    def parse_event_datetime(self, row):
        event_date = row.get("date", "").strip()
        event_time = row.get("time", "").strip()
        if not event_date:
            return None

        if event_time == "Tentative":
            event_time = "00:00"

        try:
            parsed = datetime.datetime.strptime(
                f"{event_date}{event_time}", "%d/%m/%Y%H:%M"
            )
        except ValueError:
            return None
        return parsed.replace(tzinfo=TZ)

    def event_country(self, row):
        for key in ("zone", "country", "region"):
            value = row.get(key)
            if value:
                return value.strip()
        return ""

    def should_alert(self, row):
        allowed_countries = set(self.config.get("allowed_countries", []))
        event_country = self.event_country(row)
        return bool(event_country and event_country in allowed_countries)

    async def reload_reminders(self, notify=False, reason="Manual reload"):
        self.cancel_reminders()
        await self.run_market_worm()

        if not self.data_path.exists():
            raise FileNotFoundError(f"Calendar file not found: {self.data_path}")

        with self.data_path.open("r", encoding="utf8") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                if not self.should_alert(row):
                    continue

                event_datetime = self.parse_event_datetime(row)
                if event_datetime is None:
                    continue

                target_datetime = event_datetime - datetime.timedelta(
                    minutes=self.config["reminder_minutes"]
                )

                if event_datetime <= datetime.datetime.now(TZ):
                    continue

                reminder = Reminder(self, target_datetime, event_datetime, row)
                self.reminders.append(reminder)

        for reminder in self.reminders:
            reminder.start()

        if notify:
            await self.send_status_message(
                (
                    f"已重新載入提醒資料。\n"
                    f"原因：{reason}\n"
                    f"提醒數量：{len(self.reminders)}\n"
                    f"提醒前分鐘數：{self.config['reminder_minutes']}"
                )
            )

    async def get_alert_channel(self):
        channel_id = int(self.config.get("Thread", 0) or 0)
        if not channel_id:
            return None

        channel = self.get_channel(channel_id)
        if channel is not None:
            return channel

        try:
            return await self.fetch_channel(channel_id)
        except (discord.Forbidden, discord.HTTPException, discord.NotFound):
            return None

    async def send_status_message(self, message):
        channel = await self.get_alert_channel()
        if channel is not None:
            await channel.send(message)

    async def send_event_alert(self, event_datetime, target_datetime, event_info):
        channel = await self.get_alert_channel()
        if channel is None:
            return

        embed = Embed(
            title="MarketAlert",
            description=f"事件名稱: {event_info.get('event', 'Unknown')}",
        )
        embed.add_field(
            name="現在時間",
            value=str(datetime.datetime.now(TZ).replace(second=0, microsecond=0)),
            inline=False,
        )
        embed.add_field(name="提醒時間", value=str(target_datetime), inline=False)
        embed.add_field(name="公佈時間", value=str(event_datetime), inline=False)
        embed.add_field(name="地區", value=self.event_country(event_info) or "Unknown", inline=False)
        embed.add_field(name="貨幣", value=event_info.get("currency", "N/A"), inline=False)
        embed.add_field(name="重要度", value=event_info.get("importance", "N/A"), inline=False)
        embed.add_field(name="公佈數據", value=event_info.get("actual", "N/A"), inline=False)
        embed.add_field(name="預期數據", value=event_info.get("forecast", "N/A"), inline=False)
        embed.add_field(name="前次數據", value=event_info.get("previous", "N/A"), inline=False)
        await channel.send(embed=embed)


class AdminCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def reload_after_config_change(self, interaction, success_message):
        try:
            await self.bot.reload_reminders(
                notify=True,
                reason=f"Config updated by {interaction.user}",
            )
        except Exception as exc:
            await interaction.followup.send(
                f"{success_message}\nBut reload failed: `{exc}`",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"{success_message}\nActive reminders: `{len(self.bot.reminders)}`",
            ephemeral=True,
        )

    @app_commands.command(name="setup_here", description="Set the current channel or thread as the alert target")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup_here(self, interaction: discord.Interaction):
        if interaction.guild_id is None or interaction.channel_id is None:
            await interaction.response.send_message("This command must be used inside a server channel.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        self.bot.config["Guild"] = interaction.guild_id
        self.bot.config["Thread"] = interaction.channel_id
        self.bot.save_config()
        await self.bot.sync_commands()
        await self.reload_after_config_change(
            interaction,
            f"Alert target updated to <#{interaction.channel_id}>.",
        )

    @app_commands.command(name="settings", description="Show the current bot settings")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def settings(self, interaction: discord.Interaction):
        channel_id = self.bot.config.get("Thread", 0)
        target = f"<#{channel_id}>" if channel_id else "Not configured"
        allowed_countries = ", ".join(self.bot.config.get("allowed_countries", [])) or "None"
        message = (
            f"Guild: `{self.bot.config.get('Guild', 0)}`\n"
            f"Target: {target}\n"
            f"Reminder minutes: `{self.bot.config.get('reminder_minutes', 10)}`\n"
            f"Allowed countries: {allowed_countries}"
        )
        await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="countries", description="List the current allowed countries")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def countries(self, interaction: discord.Interaction):
        allowed_countries = self.bot.config.get("allowed_countries", [])
        await interaction.response.send_message(
            "Allowed countries: " + (", ".join(allowed_countries) or "None"),
            ephemeral=True,
        )

    @app_commands.command(name="country_add", description="Add a country or region to the alert whitelist")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def country_add(self, interaction: discord.Interaction, country: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        country = country.strip()
        allowed_countries = self.bot.config.setdefault("allowed_countries", [])
        if country not in allowed_countries:
            allowed_countries.append(country)
            self.bot.save_config()

        await self.reload_after_config_change(
            interaction,
            f"Added `{country}` to the allowed country list.",
        )

    @app_commands.command(name="country_remove", description="Remove a country or region from the alert whitelist")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def country_remove(self, interaction: discord.Interaction, country: str):
        await interaction.response.defer(ephemeral=True, thinking=True)
        country = country.strip()
        allowed_countries = self.bot.config.setdefault("allowed_countries", [])
        if country in allowed_countries:
            allowed_countries.remove(country)
            self.bot.save_config()
            message = f"Removed `{country}` from the allowed country list."
        else:
            message = f"`{country}` is not in the allowed country list."

        await self.reload_after_config_change(interaction, message)

    @app_commands.command(name="reload_alerts", description="Reload calendar data and rebuild reminder tasks")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def reload_alerts(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await self.bot.reload_reminders(notify=True, reason=f"Reloaded by {interaction.user}")
        except Exception as exc:
            await interaction.followup.send(f"Reload failed: `{exc}`", ephemeral=True)
            return

        await interaction.followup.send(
            f"Reload complete. Active reminders: `{len(self.bot.reminders)}`",
            ephemeral=True,
        )

    @app_commands.command(name="set_reminder_minutes", description="Set how many minutes before the event the bot should alert")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_reminder_minutes(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 240]):
        await interaction.response.defer(ephemeral=True, thinking=True)
        self.bot.config["reminder_minutes"] = int(minutes)
        self.bot.save_config()
        await self.reload_after_config_change(
            interaction,
            f"Reminder timing updated to `{minutes}` minutes before each event.",
        )

    @setup_here.error
    @settings.error
    @countries.error
    @country_add.error
    @country_remove.error
    @reload_alerts.error
    @set_reminder_minutes.error
    async def admin_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.errors.MissingPermissions):
            message = "You need `Manage Server` permission to use this command."
        elif isinstance(error, app_commands.errors.CheckFailure):
            message = "You are not allowed to use this command."
        else:
            message = f"Command failed: `{error}`"

        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


if __name__ == "__main__":
    print("[Info] Running...")
    bot = MarketAlertBot()
    bot.run(bot.config["discord_bot_token"])
