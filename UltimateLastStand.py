"""Ultimate Last Stand: Made by Cross Joy"""
# ba_meta require api 7
# (see https://ballistica.net/wiki/meta-tag-system)

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import TYPE_CHECKING

import ba
import _ba
import bastd
from ba import _math
from bastd.actor.playerspaz import PlayerSpaz
from bastd.actor.bomb import TNTSpawner
from bastd.actor.onscreentimer import OnScreenTimer
from ba._messages import StandMessage
from bastd.actor.spaz import PickupMessage
from ba._coopsession import CoopSession
from bastd.actor.spazfactory import SpazFactory
from bastd.actor.spazbot import (SpazBot, SpazBotSet, BomberBot,
                                 BomberBotPro, BomberBotProShielded,
                                 BrawlerBot, BrawlerBotPro,
                                 BrawlerBotProShielded, TriggerBot,
                                 TriggerBotPro, TriggerBotProShielded,
                                 ChargerBot, StickyBot, ExplodeyBot)

if TYPE_CHECKING:
    from typing import Any, Sequence
    from bastd.actor.spazbot import SpazBot


class IceBot(SpazBot):
    """A slow moving bot with ice bombs.

    category: Bot Classes
    """
    character = 'Pascal'
    punchiness = 0.9
    throwiness = 1
    charge_speed_min = 1
    charge_speed_max = 1
    throw_dist_min = 5.0
    throw_dist_max = 20
    run = True
    charge_dist_min = 10.0
    charge_dist_max = 11.0
    default_bomb_type = 'ice'
    default_bomb_count = 1
    points_mult = 3


# Disable players killing each other.
class NewPlayerSpaz(PlayerSpaz):
    def handlemessage(self, m: Any) -> Any:
        # Freezing Players disabled
        if isinstance(m, ba.FreezeMessage):
            # print(self.getplayer(Player))
            # picked_up_by = self.node.source_player
            # if picked_up_by:
            #     self.last_player_attacked_by = picked_up_by

            if self.last_player_attacked_by:
                super().handlemessage(m)

        elif isinstance(m, ba.HitMessage):
            # Hitting Players disabled
            if m._source_player is not None and m._source_player != self.getplayer(
                Player):
                try:
                    name = m._source_player.getname(True, False)
                    if name is not None:
                        return
                except:
                    super().handlemessage(m)
            else:
                super().handlemessage(m)

        elif isinstance(m, PickupMessage):
            # Pickup Players disabled.
            if not self.node:
                return None

            try:
                collision = ba.getcollision()
                opposingnode = collision.opposingnode
                opposingbody = collision.opposingbody
            except ba.NotFoundError:
                return True

            try:
                if opposingnode.invincible:
                    return True
            except Exception:
                pass

            try:
                if opposingnode.source_player is not None:
                    return True
            except Exception:
                pass

            if (opposingnode.getnodetype() == 'spaz'
                and not opposingnode.shattered and opposingbody == 4):
                opposingbody = 1

            held = self.node.hold_node
            if held and held.getnodetype() == 'flag':
                return True

            self.node.hold_body = opposingbody
            self.node.hold_node = opposingnode
        else:
            return super().handlemessage(m)
        ba.screenmessage("test")
        return None


@dataclass
class SpawnInfo:
    """Spawning info for a particular bot type."""
    spawnrate: float
    increase: float
    dincrease: float


class Player(ba.Player['Team']):
    """Our player type for this game."""

    def __init__(self) -> None:
        super().__init__()
        self.death_time: float | None = None


class Team(ba.Team[Player]):
    """Our team type for this game."""


# ba_meta export game
class UltimateLastStand(ba.TeamGameActivity[Player, Team]):
    """Minigame involving dodging falling bombs."""

    name = 'Ultimate Last Stand'
    description = 'Only the Strong will stand at the end.'
    available_settings = [ba.BoolSetting('Epic Mode', default=False)]
    scoreconfig = ba.ScoreConfig(label='Survived',
                                 scoretype=ba.ScoreType.MILLISECONDS,
                                 version='B')

    # Print messages when players die (since its meaningful in this game).
    announce_player_deaths = True

    # Don't allow joining after we start
    # (would enable leave/rejoin tomfoolery).
    allow_mid_activity_joins = False

    # We're currently hard-coded for one map.
    @classmethod
    def get_supported_maps(cls, sessiontype: type[ba.Session]) -> list[str]:
        return ['Rampage']

    # We support teams, free-for-all, and co-op sessions.
    @classmethod
    def supports_session_type(cls, sessiontype: type[ba.Session]) -> bool:
        return (issubclass(sessiontype, ba.DualTeamSession)
                or issubclass(sessiontype, ba.FreeForAllSession)
                or issubclass(sessiontype, ba.CoopSession))

    def __init__(self, settings: dict):
        super().__init__(settings)

        self._epic_mode = settings.get('Epic Mode', True)
        self._last_player_death_time: float | None = None
        self._timer: OnScreenTimer | None = None
        self._tntspawner: TNTSpawner | None = None
        self._new_wave_sound = ba.getsound('scoreHit01')
        self._bots = SpazBotSet()
        self._tntspawnpos = (0, 5.5, -6)
        self.spazList = []

        # For each bot type: [spawnrate, increase, d_increase]
        self._bot_spawn_types = {
            BomberBot: SpawnInfo(1.00, 0.00, 0.000),
            BomberBotPro: SpawnInfo(0.00, 0.05, 0.001),
            BomberBotProShielded: SpawnInfo(0.00, 0.02, 0.002),
            BrawlerBot: SpawnInfo(1.00, 0.00, 0.000),
            BrawlerBotPro: SpawnInfo(0.00, 0.05, 0.001),
            BrawlerBotProShielded: SpawnInfo(0.00, 0.02, 0.002),
            TriggerBot: SpawnInfo(0.30, 0.00, 0.000),
            TriggerBotPro: SpawnInfo(0.00, 0.05, 0.001),
            TriggerBotProShielded: SpawnInfo(0.00, 0.02, 0.002),
            ChargerBot: SpawnInfo(0.30, 0.05, 0.000),
            StickyBot: SpawnInfo(0.10, 0.03, 0.001),
            # IceBot: SpawnInfo(0.10, 0.03, 0.001),
            ExplodeyBot: SpawnInfo(0.05, 0.02, 0.002)
        }  # yapf: disable

        # Some base class overrides:
        self.default_music = (ba.MusicType.EPIC
                              if self._epic_mode else ba.MusicType.SURVIVAL)
        if self._epic_mode:
            self.slow_motion = True

    def on_transition_in(self) -> None:
        super().on_transition_in()
        ba.timer(1.3, ba.Call(ba.playsound, self._new_wave_sound))

    def on_begin(self) -> None:
        super().on_begin()

        ba.timer(0.001, ba.WeakCall(self._start_bot_updates))
        self._tntspawner = TNTSpawner(position=self._tntspawnpos,
                                      respawn_time=10.0)

        self._timer = OnScreenTimer()
        self._timer.start()
        self.setup_standard_powerup_drops()

        # Check for immediate end (if we've only got 1 player, etc).
        ba.timer(5.0, self._check_end_game)

    def on_player_leave(self, player: Player) -> None:
        # Augment default behavior.
        super().on_player_leave(player)

        # A departing player may trigger game-over.
        self._check_end_game()

    # overriding the default character spawning..
    def spawn_player(self, player: Player) -> ba.Actor:
        spaz = self.spawn_player_spaz(player)

        # Let's reconnect this player's controls to this
        # spaz but *without* the ability to attack or pick stuff up.
        spaz.connect_controls_to_player()

        # Also lets have them make some noise when they die.
        spaz.play_big_death_sound = True
        return spaz

    def spawn_player_spaz(self,
                          player: PlayerType,
                          position: Sequence[float] = (0, 0, 0),
                          angle: float = None) -> PlayerSpaz:
        """Create and wire up a ba.PlayerSpaz for the provided ba.Player."""
        # pylint: disable=too-many-locals
        # pylint: disable=cyclic-import
        position = self.map.get_ffa_start_position(self.players)
        angle = 20
        name = player.getname()

        light_color = _math.normalized_color(player.color)
        display_color = _ba.safecolor(player.color, target_intensity=0.75)
        spaz = NewPlayerSpaz(color=player.color,
                             highlight=player.highlight,
                             character=player.character,
                             player=player)
        player.actor = spaz
        assert spaz.node
        self.spazList.append(spaz)

        if isinstance(self.session, CoopSession) and self.map.getname() in [
            'Courtyard', 'Tower D'
        ]:
            mat = self.map.preloaddata['collide_with_wall_material']
            assert isinstance(spaz.node.materials, tuple)
            assert isinstance(spaz.node.roller_materials, tuple)
            spaz.node.materials += (mat,)
            spaz.node.roller_materials += (mat,)

        spaz.node.name = name
        spaz.node.name_color = display_color
        spaz.connect_controls_to_player()
        factory = SpazFactory()

        # Move to the stand position and add a flash of light.
        spaz.handlemessage(
            StandMessage(
                position,
                angle if angle is not None else random.uniform(0, 360)))
        _ba.playsound(self._spawn_sound, 1, position=spaz.node.position)
        light = _ba.newnode('light', attrs={'color': light_color})
        spaz.node.connectattr('position', light, 'position')
        ba.animate(light, 'intensity', {0: 0, 0.25: 1, 0.5: 0})
        _ba.timer(0.5, light.delete)
        return spaz

    def _start_bot_updates(self) -> None:
        self._bot_update_interval = 3.3 - 0.3 * (len(self.players))
        self._update_bots()
        self._update_bots()
        if len(self.players) > 2:
            self._update_bots()
        if len(self.players) > 3:
            self._update_bots()
        self._bot_update_timer = ba.Timer(self._bot_update_interval,
                                          ba.WeakCall(self._update_bots))

    def _update_bots(self) -> None:
        assert self._bot_update_interval is not None
        self._bot_update_interval = max(0.5, self._bot_update_interval * 0.98)
        self._bot_update_timer = ba.Timer(self._bot_update_interval,
                                          ba.WeakCall(self._update_bots))
        botspawnpts: list[Sequence[float]] = [[-5.0, 5.5, -4.14],
                                              [0.0, 5.5, -4.14],
                                              [5.0, 5.5, -4.14]]
        dists = [0.0, 0.0, 0.0]
        playerpts: list[Sequence[float]] = []
        for player in self.players:
            try:
                if player.is_alive():
                    assert isinstance(player.actor, PlayerSpaz)
                    assert player.actor.node
                    playerpts.append(player.actor.node.position)
            except Exception:
                ba.print_exception('Error updating bots.')
        for i in range(3):
            for playerpt in playerpts:
                dists[i] += abs(playerpt[0] - botspawnpts[i][0])
            dists[i] += random.random() * 5.0  # Minor random variation.
        if dists[0] > dists[1] and dists[0] > dists[2]:
            spawnpt = botspawnpts[0]
        elif dists[1] > dists[2]:
            spawnpt = botspawnpts[1]
        else:
            spawnpt = botspawnpts[2]

        spawnpt = (spawnpt[0] + 3.0 * (random.random() - 0.5), spawnpt[1],
                   2.0 * (random.random() - 0.5) + spawnpt[2])

        # Normalize our bot type total and find a random number within that.
        total = 0.0
        for spawninfo in self._bot_spawn_types.values():
            total += spawninfo.spawnrate
        randval = random.random() * total

        # Now go back through and see where this value falls.
        total = 0
        bottype: type[SpazBot] | None = None
        for spawntype, spawninfo in self._bot_spawn_types.items():
            total += spawninfo.spawnrate
            if randval <= total:
                bottype = spawntype
                break
        spawn_time = 1.0
        assert bottype is not None
        self._bots.spawn_bot(bottype, pos=spawnpt, spawn_time=spawn_time)

        # After every spawn we adjust our ratios slightly to get more
        # difficult.
        for spawninfo in self._bot_spawn_types.values():
            spawninfo.spawnrate += spawninfo.increase
            spawninfo.increase += spawninfo.dincrease

    # Various high-level game events come through this method.
    def handlemessage(self, msg: Any) -> Any:
        if isinstance(msg, ba.PlayerDiedMessage):

            # Augment standard behavior.
            super().handlemessage(msg)

            curtime = ba.time()

            # Record the player's moment of death.
            # assert isinstance(msg.spaz.player
            msg.getplayer(Player).death_time = curtime

            # In co-op mode, end the game the instant everyone dies
            # (more accurate looking).
            # In teams/ffa, allow a one-second fudge-factor so we can
            # get more draws if players die basically at the same time.
            if isinstance(self.session, ba.CoopSession):
                # Teams will still show up if we check now.. check in
                # the next cycle.
                ba.pushcall(self._check_end_game)

                # Also record this for a final setting of the clock.
                self._last_player_death_time = curtime
            else:
                ba.timer(1.0, self._check_end_game)

        else:
            # Default handler:
            return super().handlemessage(msg)
        return None

    def _check_end_game(self) -> None:
        living_team_count = 0
        for team in self.teams:
            for player in team.players:
                if player.is_alive():
                    living_team_count += 1
                    break

        # In co-op, we go till everyone is dead.. otherwise we go
        # until one team remains.
        if isinstance(self.session, ba.CoopSession):
            if living_team_count <= 0:
                self.end_game()
        else:
            if living_team_count <= 1:
                self.end_game()

    def end_game(self) -> None:
        cur_time = ba.time()
        assert self._timer is not None
        start_time = self._timer.getstarttime()

        # Mark death-time as now for any still-living players
        # and award players points for how long they lasted.
        # (these per-player scores are only meaningful in team-games)
        for team in self.teams:
            for player in team.players:
                survived = False

                # Throw an extra fudge factor in so teams that
                # didn't die come out ahead of teams that did.
                if player.death_time is None:
                    survived = True
                    player.death_time = cur_time + 1

                # Award a per-player score depending on how many seconds
                # they lasted (per-player scores only affect teams mode;
                # everywhere else just looks at the per-team score).
                score = int(player.death_time - self._timer.getstarttime())
                if survived:
                    score += 50  # A bit extra for survivors.
                self.stats.player_scored(player, score, screenmessage=False)

        # Stop updating our time text, and set the final time to match
        # exactly when our last guy died.
        self._timer.stop(endtime=self._last_player_death_time)

        # Ok now calc game results: set a score for each team and then tell
        # the game to end.
        results = ba.GameResults()

        # Remember that 'free-for-all' mode is simply a special form
        # of 'teams' mode where each player gets their own team, so we can
        # just always deal in teams and have all cases covered.
        for team in self.teams:

            # Set the team score to the max time survived by any player on
            # that team.
            longest_life = 0.0
            for player in team.players:
                assert player.death_time is not None
                longest_life = max(longest_life,
                                   player.death_time - start_time)

            # Submit the score value in milliseconds.
            results.set_team_score(team, int(1000.0 * longest_life))

        self.end(results=results)
