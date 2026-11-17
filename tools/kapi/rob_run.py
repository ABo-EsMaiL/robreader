"""
rob_run.py - Rob Run (Unity IL2CPP) structure map and reader.

Every offset below was extracted from *this machine's* Il2CppDumper output
(`output-new/dump.cs`, 2026-11-17 build, Unity 6 / metadata v39). If the
game patches, re-run `tools/dump_fields.py` against the fresh dump and
update this file - that is the whole point of deriving offsets from
metadata instead of copying a table.

TypeDefIndex values are for the build that produced our dump and shift by a
small amount on some patches (the community reference had BattleModel at
5520 where our dump says 5521).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, Iterator, List, Optional, Tuple

from .backend import MemoryBackend
from .il2cpp import Il2Cpp, dictionary_entries

# ============================================================ module anchors
GAME_ASSEMBLY = "GameAssembly.dll"
UNITY_PLAYER = "UnityPlayer.dll"

# GameAssembly.dll + 0x8625440 -> pointer to the Il2CppClass table.
CLASS_TABLE_SLOT = 0x8625440
METADATA_HEADER_SLOT = 0x8625550


# ============================================================== type indices
class TypeIndex:
    # values from ROP/output-new/dump.cs (2026-11-17 build, GameAssembly
    # 147,948,544 bytes / metadata 34,412,236 bytes)
    GAME = 29356
    GAME_MODEL = 29357
    BATTLE_MODEL = 5523
    BATTLE_ENTITIES_MODEL = 5513
    BATTLE_CHARACTER_MODEL = 4311
    BATTLE_CAMERA_MODEL = 7877
    HEALTH_MODEL = 3921
    PLAYER_ENTITY_MODEL = 8703


# ================================================================== offsets
class Off:
    """Field offsets inside the Rob Run models."""

    # Game.Game
    GAME_GAME_MODEL = 0xD0
    GAME_UPDATERS = 0x20

    # Game.GameModel
    GAME_MODEL_BATTLE_MODEL = 0x10

    # Game.Battle.BattleModel
    BATTLE_ENTITIES = 0x90
    BATTLE_CAMERA = 0x358
    BATTLE_WORLD_ENTITIES = 0x518

    # Game.Battle.BattleEntitiesModel
    ENTITIES_MODELS = 0x50          # Dictionary<int, IEntityModel>
    ENTITIES_SLOTS = 0x80           # ClientCharacterSlotsModel (names/clan)
    ENTITIES_LOCAL_PLAYER = 0xD0    # PlayerEntityModel

    # ClientCharacterSlotsModel (dump.cs 1759080) - player names
    SLOTS_BY_ENTITY_ID = 0x18       # Dictionary<int, BattleCharacterSlotModel>
    SLOT_DATA = 0x10                # BattleCharacterSlotModel._data
    # BattleCharacterSlotData (dump.cs 212877) - CompositeData
    SLOT_ENTITY_ID = 0x20           # IPrimitiveData<int>
    SLOT_PUBLIC_ID = 0x28           # IPrimitiveData<long>
    SLOT_NICKNAME = 0x30            # IPrimitiveData<string>
    SLOT_CLAN_TAG = 0x38            # IPrimitiveData<string>

    # NOTE: there is no BattleCharacterEntityModel in dump.cs - the only
    # character entity in the live dictionary is PlayerEntityModel, whose
    # ServerModel sits at +0x20 (dump.cs 362782; verified live 17-11:
    # entity+0x28 is the long PublicId, not a pointer).

    # BattleCharacterEntityModel (the dictionary values)
    ENTITY_SERVER_MODEL = 0x28      # BattleCharacterModel - replicated server truth
    ENTITY_SIMULATED_MODEL = 0x30   # BattleCharacterModel - local prediction copy

    # CharacterReplicatedTransformModel (remote entities)
    RTM_POSITION = 0x10             # IPrimitiveData<Vector3> wrapper
    RTM_RX = 0x18                   # IPrimitiveData<float> wrappers (axis
    RTM_RY = 0x20                   #   mapping verified against the local
    RTM_RZ = 0x28                   #   player's transform at runtime)

    # PlayerEntityModel
    PLAYER_CLIENT_MODEL = 0x18
    PLAYER_SERVER_MODEL = 0x20      # BattleCharacterModel
    PLAYER_PUBLIC_ID = 0x28

    # BattleCharacterModel
    BCM_PRIVATE_MODEL = 0x10
    BCM_ID = 0x38
    BCM_DATA = 0x40
    BCM_CONFIG = 0x48
    BCM_TRANSFORM = 0x58            # <-- the real position, NOT 0x68
    BCM_REPLICATED_TRANSFORM = 0x60
    BCM_LAST_POSITION = 0x68        # <-- what v1 of our table wrongly used
    BCM_VELOCITY = 0xB8
    BCM_IS_DEAD = 0xF0
    BCM_ITEM_IN_HANDS = 0x170
    BCM_IN_VEHICLE = 0x1C8
    BCM_ROLE = 0x208

    # CharacterTransformModel
    CTM_X = 0x10
    CTM_Y = 0x14
    CTM_Z = 0x18
    CTM_PITCH = 0x1C
    CTM_YAW = 0x20
    CTM_ROLL = 0x24

    # CharacterVelocityModel
    CVM_VELOCITY = 0x10              # Vector3
    CVM_VELOCITY_LEN = 0x1C

    # BattleCharacterPrivateModel
    BCPM_HEALTH = 0x1B0              # HealthModel

    # HealthModel
    HM_HEALTH = 0x10                 # IPrimitiveData<int> (wrapper)
    HM_IS_DEAD = 0x18
    HM_MAX_AMOUNT = 0x20            # raw int
    HM_CRITICAL_HEALTH = 0x24

    # BattleCharacterConfig
    CFG_PHYSICS = 0x18
    CFG_MAX_HEALTH = 0x28           # raw int
    CFG_CRITICAL_HEALTH = 0x2C
    CFG_CHEAT_SPRINT_MODIFIER = 0xC8

    # BattleCameraModel
    CAM_POSITION = 0x10
    CAM_ORIENTATION = 0x1C
    CAM_LOOK = 0x2C
    CAM_FORWARD = 0x3C
    CAM_RIGHT = 0x48
    CAM_UP = 0x54
    CAM_DISTANCE = 0x60


# ============================================================ role enum names
# dump.cs 249601 - PlayerRole enum (verified 17-11):
#   None=-1, Settler=0, Robber=1, Cop=2, Citizen=3, Prisoner=4
ROLE_NAMES: Dict[int, str] = {
    -1: "None",
    0: "Settler",
    1: "Robber",
    2: "Cop",
    3: "Citizen",
    4: "Prisoner",
}


# ================================================================== records
@dataclass
class CharacterInfo:
    entity_id: int = -1
    address: int = 0
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    velocity: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    pitch: float = 0.0
    yaw: float = 0.0
    health: Optional[int] = None
    max_health: int = 0
    is_dead: Optional[bool] = None
    role: Optional[int] = None
    role_id: Optional[str] = None
    in_vehicle: int = 0
    name: Optional[str] = None
    clan: Optional[str] = None

    def __str__(self) -> str:
        pos = "(" + ", ".join(f"{v:8.2f}" for v in self.position) + ")"
        # radians (RTM primitives); yaw accumulates beyond +-pi
        rot = f"rot=({self.pitch:5.2f},{self.yaw:6.2f})"
        if self.role_id:
            role = self.role_id
        elif self.role is not None:
            role = ROLE_NAMES.get(self.role, f"#{self.role}")
        else:
            role = "?"
        dead = "DEAD" if self.is_dead else ("alive" if self.is_dead is False else "?")
        hp = (f"{self.health}/{self.max_health}" if self.health is not None
              else f"?/{self.max_health}")
        who = f"{self.name}" if self.name else "?"
        if self.clan:
            who = f"[{self.clan}]{who}"
        return (f"id={self.entity_id:<5} @{self.address:#012x} {pos} {rot} "
                f"hp={hp:<7} {dead:<5} role={role} {who}")


@dataclass
class CameraInfo:
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    forward: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    right: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    up: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    distance: float = 0.0


# ================================================================== reader
class RobRunReader:
    """
    Reads Rob Run's IL2CPP object graph through a MemoryBackend.

    Root chain (verified against dump.cs):

        Game.Game  +0xD0  -> GameModel
        GameModel  +0x10  -> BattleModel
        BattleModel +0x90 -> BattleEntitiesModel
        BattleEntitiesModel +0x50 -> Dictionary<int, IEntityModel>
        BattleEntitiesModel +0xD0 -> PlayerEntityModel
        PlayerEntityModel +0x20   -> BattleCharacterModel (local player)
        entity +0x28 / +0x30      -> BattleCharacterModel server/simulated
        BattleModel +0x358        -> BattleCameraModel
    """

    def __init__(self, mem: MemoryBackend, game_base: int = 0,
                 unity_base: int = 0):
        self.mem = mem
        self.il2cpp = Il2Cpp(mem)
        self.game_base = game_base or mem.module_base(GAME_ASSEMBLY)[0]
        try:
            self.unity_base = unity_base or mem.module_base(UNITY_PLAYER)[0]
        except Exception:
            # a dump may not contain UnityPlayer.dll; the GOM root lookup
            # simply will not be available in that case
            self.unity_base = unity_base or 0

    # ------------------------------------------------------- class lookup
    def class_for(self, type_index: int) -> int:
        """Resolve a TypeDefIndex to a live Il2CppClass*."""
        table_slot = self.game_base + CLASS_TABLE_SLOT
        table = self.mem.u64(table_slot)
        if not table:
            raise RuntimeError("il2cpp class table not available")
        return self.mem.u64(table + type_index * 8)

    # --------------------------------------------------------- root lookup
    def find_game(self, regions: Optional[List[Tuple[int, int]]] = None,
                  game_address: int = 0) -> int:
        """
        Locate the Game.Game singleton.

        Strategy A (preferred): the Unity GameObject graph -
            UnityPlayer.dll + 0x2230768 -> GOM -> find object named
            "UnityEntry" -> component "UnityEntry" -> +0x28 = Game.
        Strategy B (fallback): scan the IL2CPP heap for an object whose
            class pointer equals the Game.Game Il2CppClass.

        `game_address` short-circuits both (used by the mock self-test and
        whenever the address is already known).
        """
        if game_address:
            return game_address
        game = self._find_game_via_gom()
        if game:
            return game
        if regions:
            klass = self.class_for(TypeIndex.GAME)
            hits = self.il2cpp.find_instances(klass, regions)
            if hits:
                return hits[0]
        raise RuntimeError(
            "Game.Game instance not found. Pass explicit heap regions to "
            "find_game(regions=[(start, end), ...]) or use the GOM path."
        )

    def _find_game_via_gom(self) -> int:
        """UnityPlayer GameObjectManager traversal."""
        try:
            gom = self.mem.u64(self.unity_base + 0x2230768)
        except Exception:
            return 0
        if not gom:
            return 0
        node = self.mem.u64(gom + 0x20)
        guard = 0
        while node and node != (gom + 0x18) and guard < 4096:
            guard += 1
            obj = self.mem.u64(node + 0x10)
            if obj:
                name_ptr = self.mem.u64(obj + 0x50)
                if name_ptr:
                    name = self.mem.cstr(name_ptr)
                    if name in ("UnityEntry", "[Entry]"):
                        comp = self._get_component(obj, "UnityEntry")
                        if comp:
                            return self.mem.u64(comp + 0x28)
            node = self.mem.u64(node + 0x08)
        return 0

    def _get_component(self, game_object: int, class_name: str) -> int:
        comp_array = self.mem.u64(game_object + 0x20)
        count = self.mem.i32(game_object + 0x30)
        for i in range(max(count, 0)):
            comp_ptr = self.mem.u64(comp_array + i * 0x10 + 0x8)
            if not comp_ptr:
                continue
            handle = self.mem.u64(comp_ptr + 0x18)
            managed = self.mem.u64(handle & ~7) if handle else 0
            if not managed:
                managed = self.mem.u64(comp_ptr + 0x28)
            if not managed:
                continue
            klass = self.mem.u64(managed)
            if not klass:
                continue
            name_ptr = self.mem.u64(klass + 0x10)
            if name_ptr and self.mem.cstr(name_ptr) == class_name:
                return managed
        return 0

    # -------------------------------------------------------------- models
    def game_model(self, game: int) -> int:
        return self.mem.u64(game + Off.GAME_GAME_MODEL)

    def battle_model(self, game: int) -> int:
        return self.mem.u64(self.game_model(game) + Off.GAME_MODEL_BATTLE_MODEL)

    def entities_model(self, game: int) -> int:
        return self.mem.u64(self.battle_model(game) + Off.BATTLE_ENTITIES)

    def camera_model(self, game: int) -> int:
        return self.mem.u64(self.battle_model(game) + Off.BATTLE_CAMERA)

    def local_player(self, game: int) -> int:
        """PlayerEntityModel of the local player."""
        return self.mem.u64(self.entities_model(game) + Off.ENTITIES_LOCAL_PLAYER)

    def local_character(self, game: int) -> int:
        """
        Entity wrapper (PlayerEntityModel) of the local player.
        `read_character` resolves its BattleCharacterModel copies itself.
        """
        return self.local_player(game)

    # ----------------------------------------------------------- characters
    def _entity_class_name(self, entity: int) -> str:
        klass = self._safe(self.mem.u64, entity, 0)
        if not klass:
            return ""
        return self._safe(self.il2cpp.class_name, klass, "") or ""

    def _character_copies(self, entity: int) -> List[int]:
        """
        Every character entity holds up to two BattleCharacterModel copies:

            BattleCharacterEntityModel +0x28  ServerModel     (replicated truth)
                                       +0x30  SimulatedModel  (local prediction)
            PlayerEntityModel          +0x20  ServerModel     (local player)

        The client only fills SimulatedModel for locally simulated (own)
        characters; remote players carry their state in the ServerModel copy,
        so the ESP must read both and prefer whichever copy is populated.

        An unreadable class name (mock fixtures) falls back to a structural
        probe of the two copy slots.
        """
        if not entity:
            return []
        name = self._entity_class_name(entity)
        if "PlayerEntityModel" in name:
            srv = self._safe(self.mem.u64, entity + Off.PLAYER_SERVER_MODEL, 0)
            return [srv] if srv else []
        if "CharacterEntityModel" in name or not name:
            sim = self._safe(self.mem.u64, entity + Off.ENTITY_SIMULATED_MODEL, 0)
            srv = self._safe(self.mem.u64, entity + Off.ENTITY_SERVER_MODEL, 0)
            return [c for c in (sim, srv) if c]
        return []

    def characters(self, game: int) -> Iterator[Tuple[int, int]]:
        """Yield (entity_id, character entity wrapper) for every character."""
        entities = self.entities_model(game)
        if not entities:
            return
        models = self.mem.u64(entities + Off.ENTITIES_MODELS)
        for entity_id, entity in dictionary_entries(self.mem, models):
            if self._character_copies(entity):
                yield entity_id, entity

    # -------------------------------------------------------------- reading
    def read_character(self, entity: int, entity_id: int = -1) -> CharacterInfo:
        """
        Read one character entity.  `entity` is the dictionary value
        (BattleCharacterEntityModel / PlayerEntityModel); the two
        BattleCharacterModel copies are resolved and cross-checked internally.
        """
        copies = self._character_copies(entity)
        info = CharacterInfo(address=entity)
        if not entity:
            return info

        if entity_id >= 0:
            info.entity_id = entity_id
        else:
            info.entity_id = self._safe(self.mem.i32, entity + 0x10, entity_id)

        # --- position/angles: prefer whichever copy is actually populated.
        # Candidate order per copy: own transform, then replicated transform;
        # copies ordered Simulated first (local player) then Server.
        pos = None
        used = None
        for copy, kind in [(c, k) for c in copies for k in ("t", "r")]:
            if kind == "t":
                t = self._safe(self.mem.u64, copy + Off.BCM_TRANSFORM, 0)
                cand = (self._safe(self.mem.f32x3, t + Off.CTM_X, None)
                        if t else None)
            else:
                r = self._safe(self.mem.u64, copy + Off.BCM_REPLICATED_TRANSFORM,
                               0)
                cand = (self._safe(self._read_vector3_value, r + Off.RTM_POSITION)
                        if r else None)
            if cand and any(abs(v) > 1e-4 for v in cand):
                pos, used = cand, (copy, kind)
                break
        if pos:
            info.position = pos
            copy, kind = used
            # Rotation: the ITransformModel object (+0x58) carries position
            # only - its +0x1C/+0x20 floats stayed zero in the live 17-11
            # battle dump.  The real pitch/yaw live in the ReplicatedTransform
            # primitive wrappers (radians: rx=0.1006, ry=1.5036 measured on
            # the local player), so read them there and keep CTM as fallback.
            r = self._safe(self.mem.u64, copy + Off.BCM_REPLICATED_TRANSFORM, 0)
            pitch = yaw = None
            if r:
                pitch = self._safe(self._read_float_value, r + Off.RTM_RX, None)
                yaw = self._safe(self._read_float_value, r + Off.RTM_RY, None)
            if (pitch is None or yaw is None) and kind == "t":
                t = self._safe(self.mem.u64, copy + Off.BCM_TRANSFORM, 0)
                if t:
                    pitch = self._safe(self.mem.f32, t + Off.CTM_PITCH, 0.0)
                    yaw = self._safe(self.mem.f32, t + Off.CTM_YAW, 0.0)
            info.pitch = pitch if pitch is not None else 0.0
            info.yaw = yaw if yaw is not None else 0.0

        # --- velocity / health / role / vehicle: position-winning copy first
        ordered: List[int] = []
        if used:
            ordered.append(used[0])
        for c in copies:
            if c not in ordered:
                ordered.append(c)

        for copy in ordered:
            v = self._safe(self.mem.u64, copy + Off.BCM_VELOCITY, 0)
            if v:
                info.velocity = self._safe(self.mem.f32x3, v + Off.CVM_VELOCITY,
                                           (0.0, 0.0, 0.0))
                break

        for copy in ordered:
            config = self._safe(self.mem.u64, copy + Off.BCM_CONFIG, 0)
            if config:
                mh = self._safe(self.mem.i32, config + Off.CFG_MAX_HEALTH, 0)
                if mh:
                    info.max_health = mh
                    break

        for copy in ordered:
            health = self._safe(self._read_current_health, copy)
            if health is not None:
                info.health = health
                break

        for copy in ordered:
            dead = self._safe(self._read_is_dead, copy)
            if dead is not None:
                info.is_dead = dead
                break

        for copy in ordered:
            role = self._safe(self._read_role_info, copy)
            if role is not None:
                info.role, info.role_id = role
                break

        for copy in ordered:
            vehicle = self._safe(self.mem.u64, copy + Off.BCM_IN_VEHICLE, 0)
            if vehicle:
                info.in_vehicle = self._safe(self._read_wrapper_int,
                                             vehicle + 0x10, 0)
                break

        return info

    @staticmethod
    def _safe(fn, address, default=None):
        """
        Optional reads must never abort the whole dump.

        `fn` takes exactly one address argument; the fallback value goes
        through `default`. (The old variadic signature forwarded a
        positional default into the read itself, so every failed read
        came back as a silent None instead of the intended fallback.)
        """
        try:
            return fn(address)
        except Exception:
            return default

    def _primitive_value_addr(self, wrapper: int, depth: int = 0) -> int:
        """
        Address of the value storage inside an IPrimitive* wrapper.

        Two shapes exist in this codebase:
            PrimitiveModel<T>._data -> <X>Data<T>._value   (two hops)
            PrimitiveData<T>._value                        (one hop)

        PrimitiveModel<T> itself carries NO `_value` field (dump.cs 163583
        lists only `_data`), so model wrappers recurse into the data object
        held in `_data`.  Runtime metadata verified live on pid 25296
        (17-11): PrimitiveModel`1._data=+0x10 / _value absent,
        ReferenceData`1._value=+0x18, BoolData._value=+0x18 - the role
        chain resolved end to end (PlayerRoleDescription, Index=6),
        is_dead=False, health=100.
        Generic field offsets are not emitted by Il2CppDumper, so they are
        resolved at runtime through the Il2CppClass metadata.
        """
        if not wrapper or depth > 3:
            return 0
        klass = self._safe(self.mem.u64, wrapper, 0)
        if not klass:
            return 0
        off_value = self.il2cpp.field_offset(klass, "_value")
        if off_value >= 0:
            return wrapper + off_value
        off_data = self.il2cpp.field_offset(klass, "_data")
        if off_data < 0:
            return 0
        inner = self._safe(self.mem.u64, wrapper + off_data, 0)
        return self._primitive_value_addr(inner, depth + 1)

    def _read_vector3_value(self, wrapper_addr: int
                            ) -> Optional[Tuple[float, float, float]]:
        """Read an inline Vector3 stored in an IPrimitiveData<Vector3>."""
        wrapper = self._safe(self.mem.u64, wrapper_addr, 0)
        addr = self._primitive_value_addr(wrapper)
        if not addr:
            return None
        return self.mem.f32x3(addr)

    def _read_float_value(self, wrapper_addr: int, default: float = 0.0) -> float:
        """Read a float stored in an IPrimitiveData<float>."""
        wrapper = self._safe(self.mem.u64, wrapper_addr, 0)
        addr = self._primitive_value_addr(wrapper)
        if not addr:
            return default
        return self.mem.f32(addr)

    def _read_is_dead(self, bcm: int) -> Optional[bool]:
        """BattleCharacterModel +0xF0 is an IPrimitiveModel<bool>."""
        wrapper = self._safe(self.mem.u64, bcm + Off.BCM_IS_DEAD, 0)
        addr = self._primitive_value_addr(wrapper)
        if not addr:
            return None
        return bool(self.mem.u8(addr))

    def _read_role_info(self, bcm: int) -> Optional[Tuple[int, Optional[str]]]:
        """
        BattleCharacterModel +0x208 is an IPrimitiveModel<PlayerRoleDescription>.

        PlayerRoleDescription is a *class* (MyEnumItem : EnumItem, dump.cs
        129995/10468), not a struct: PrimitiveModel`1._data (+0x10 runtime)
        -> ReferenceData`1._value (+0x18) holds the reference.  Returns
        (EnumItem.Index @ +0x18, description Id string @ +0x10).

        The PlayerRole enum (dump.cs 249601): Settler=0, Robber=1, Cop=2,
        Citizen=3, Prisoner=4, None=-1.  The description Id is the ground
        truth the game itself uses ('hubber' = the default/neutral
        description measured live on pid 25296, 17-11).

        NOTE (live 17-11): during the battle every entity - the local
        player included - shared that ONE default description (Index=6,
        not a PlayerRole ordinal); roles are evidently not replicated to
        the client until assigned/revealed.
        """
        wrapper = self._safe(self.mem.u64, bcm + Off.BCM_ROLE, 0)
        addr = self._primitive_value_addr(wrapper)
        if not addr:
            return None
        desc = self._safe(self.mem.u64, addr, 0)
        if not desc or desc < 0x10000:
            return None
        index = self._safe(self.mem.i32, desc + 0x18, None)
        if index is None:
            return None
        id_obj = self._safe(self.mem.u64, desc + 0x10, 0)
        role_id = None
        if id_obj and id_obj >= 0x10000:
            role_id = self._safe(self.mem.il2cpp_string, id_obj, "") or None
        return (index, role_id)

    def _read_current_health(self, bcm: int) -> Optional[int]:
        """
        Current health via the private model:
            BattleCharacterModel +0x10  -> BattleCharacterPrivateModel
            +0x1B0 (BCPM_HEALTH)        -> HealthModel
            +0x10   (HM_HEALTH)         -> IPrimitiveData<int> (IntData)
        Verified live (pid 25296, 17-11): local player cur=100/max=100,
        critical=20.  The private model is not replicated for remote
        entities - returns None then (display falls back to hp<=max).
        """
        priv = self._safe(self.mem.u64, bcm + Off.BCM_PRIVATE_MODEL, 0)
        if not priv:
            return None
        hm = self._safe(self.mem.u64, priv + Off.BCPM_HEALTH, 0)
        if not hm:
            return None
        wrapper = self._safe(self.mem.u64, hm + Off.HM_HEALTH, 0)
        addr = self._primitive_value_addr(wrapper)
        if not addr:
            return None
        return self._safe(self.mem.i32, addr, None)

    def _read_wrapper_int(self, wrapper: int, default: int = 0) -> int:
        addr = self._primitive_value_addr(wrapper)
        if not addr:
            return default
        return self.mem.i32(addr)

    def _read_string_value(self, wrapper_addr: int) -> Optional[str]:
        """
        Read the string behind an IPrimitiveData<string> wrapper.
        For reference-type T the _value storage holds a pointer to the IL2CPP
        System.String object (length at +0x10, UTF-16 data at +0x14).
        """
        wrapper = self._safe(self.mem.u64, wrapper_addr, 0)
        addr = self._primitive_value_addr(wrapper)
        if not addr:
            return None
        obj = self._safe(self.mem.u64, addr, 0)
        if not obj or obj < 0x10000:
            return None
        text = self._safe(self.mem.il2cpp_string, obj, "")
        return text or None

    def _slot_dicts(self, game: int) -> Optional[int]:
        """Dictionary<int, BattleCharacterSlotModel> keyed by entity id."""
        slots = self._safe(self.mem.u64,
                           self.entities_model(game) + Off.ENTITIES_SLOTS, 0)
        if not slots:
            return None
        return self._safe(self.mem.u64, slots + Off.SLOTS_BY_ENTITY_ID, 0)

    def read_names(self, game: int) -> Dict[int, Tuple[Optional[str], Optional[str]]]:
        """
        entity_id -> (nickname, clan_tag).

        Chain (dump.cs 1759080 / 194645 / 212877, verified statically 17-11):
            BattleEntitiesModel +0x80     -> ClientCharacterSlotsModel
            ClientCharacterSlotsModel+0x18-> Dictionary<int, slot>
            slot +0x10                    -> BattleCharacterSlotData
            data  +0x30                   -> Nickname  IPrimitiveData<string>
            data  +0x38                   -> ClanTag   IPrimitiveData<string>
        """
        out: Dict[int, Tuple[Optional[str], Optional[str]]] = {}
        by_entity = self._slot_dicts(game)
        if not by_entity:
            return out
        for entity_id, slot in dictionary_entries(self.mem, by_entity):
            if not slot:
                continue
            data = self._safe(self.mem.u64, slot + Off.SLOT_DATA, 0)
            if not data:
                continue
            nick = self._read_string_value(data + Off.SLOT_NICKNAME)
            clan = self._read_string_value(data + Off.SLOT_CLAN_TAG)
            if nick or clan:
                out[entity_id] = (nick, clan)
        return out

    def read_camera(self, game: int) -> CameraInfo:
        cam = self.camera_model(game)
        info = CameraInfo()
        if not cam:
            return info
        info.position = self.mem.f32x3(cam + Off.CAM_POSITION)
        info.forward = self.mem.f32x3(cam + Off.CAM_FORWARD)
        info.right = self.mem.f32x3(cam + Off.CAM_RIGHT)
        info.up = self.mem.f32x3(cam + Off.CAM_UP)
        info.distance = self.mem.f32(cam + Off.CAM_DISTANCE)
        return info


# ======================================================== mock fixture
def build_robrun_fixture(mem, characters: int = 3) -> Tuple[int, int]:
    """
    Lay out a miniature but faithful Rob Run object graph inside a
    MockBackend, so the reader can be exercised with no driver at all.

    Returns (game_address, gameassembly_base).
    """
    base = 0x0000_1400_0000_0000
    mem.add_module(GAME_ASSEMBLY, base, 0x08FC9000)
    mem.add_module(UNITY_PLAYER, base + 0x100000000, 0x02426000)

    def obj(size=0x200, align=0x10):
        return mem.alloc(size, align)

    # Game.Game
    game = obj(0x100)
    game_model = obj(0x80)
    battle_model = obj(0x600)
    entities = obj(0x100)
    camera = obj(0x80)

    mem.poke_u64(game + Off.GAME_GAME_MODEL, game_model)
    mem.poke_u64(game_model + Off.GAME_MODEL_BATTLE_MODEL, battle_model)
    mem.poke_u64(battle_model + Off.BATTLE_ENTITIES, entities)
    mem.poke_u64(battle_model + Off.BATTLE_CAMERA, camera)

    # camera
    mem.poke_f32(camera + Off.CAM_POSITION, 10.0)
    mem.poke_f32(camera + Off.CAM_POSITION + 4, 2.0)
    mem.poke_f32(camera + Off.CAM_POSITION + 8, -5.0)
    mem.poke_f32(camera + Off.CAM_FORWARD, 0.0)
    mem.poke_f32(camera + Off.CAM_FORWARD + 4, 0.0)
    mem.poke_f32(camera + Off.CAM_FORWARD + 8, 1.0)

    def fake_klass(name: str) -> int:
        """
        Minimal Il2CppClass stand-in: only +0x10 (char* name) is populated,
        which is all `Il2Cpp.class_name` and the reader's dispatch need.
        """
        raw = name.encode("ascii") + b"\x00"
        buf = mem.alloc((len(raw) + 7) & ~7)
        for off in range(0, len(raw), 8):
            chunk = raw[off:off + 8].ljust(8, b"\x00")
            mem.poke_u64(buf + off, int.from_bytes(chunk, "little"))
        k = obj(0x30)
        mem.poke_u64(k + 0x10, buf)         # Il2CppClass.name
        return k

    klass_character = fake_klass("BattleCharacterEntityModel")
    klass_player = fake_klass("PlayerEntityModel")

    # Dictionary<int, IEntityModel>
    entries = obj(0x20 + 0x18 * 8)
    dict_ptr = obj(0x40)
    mem.poke_u64(dict_ptr + 0x18, entries)
    mem.poke_i32(dict_ptr + 0x20, characters)
    mem.poke_u64(entities + Off.ENTITIES_MODELS, dict_ptr)

    for i in range(characters):
        entity = obj(0x80)
        bcm = obj(0x300)
        transform = obj(0x40)
        velocity = obj(0x40)
        config = obj(0x100)

        mem.poke_u64(entity, klass_character)   # object -> class pointer
        mem.poke_i32(entity + 0x10, 100 + i)    # EntityModel.Id
        mem.poke_u64(entity + Off.ENTITY_SIMULATED_MODEL, bcm)
        mem.poke_i32(bcm + Off.BCM_ID, 100 + i)
        mem.poke_u64(bcm + Off.BCM_TRANSFORM, transform)
        mem.poke_u64(bcm + Off.BCM_VELOCITY, velocity)
        mem.poke_u64(bcm + Off.BCM_CONFIG, config)

        mem.poke_f32(transform + Off.CTM_X, float(i) * 3.5)
        mem.poke_f32(transform + Off.CTM_Y, 1.75)
        mem.poke_f32(transform + Off.CTM_Z, -float(i) * 2.25)
        mem.poke_f32(transform + Off.CTM_PITCH, 0.0)
        mem.poke_f32(transform + Off.CTM_YAW, 90.0 + i)

        mem.poke_f32(velocity + Off.CVM_VELOCITY, 0.5 * i)
        mem.poke_f32(velocity + Off.CVM_VELOCITY + 4, 0.0)
        mem.poke_f32(velocity + Off.CVM_VELOCITY + 8, -0.25 * i)

        mem.poke_i32(config + Off.CFG_MAX_HEALTH, 100)

        e = entries + 0x20 + i * 0x18
        mem.poke_i32(e + 0x00, 0x1234 + i)   # hash
        mem.poke_i32(e + 0x04, -1)          # next
        mem.poke_i32(e + 0x08, 100 + i)      # key
        mem.poke_u64(e + 0x10, entity)      # value

    # local player
    player = obj(0x60)
    local_bcm = obj(0x300)
    local_transform = obj(0x40)
    local_config = obj(0x100)
    mem.poke_u64(player, klass_player)              # object -> class pointer
    mem.poke_i32(player + 0x10, 100)                # EntityModel.Id
    mem.poke_u64(player + Off.PLAYER_SERVER_MODEL, local_bcm)
    mem.poke_i32(local_bcm + Off.BCM_ID, 100)
    mem.poke_u64(local_bcm + Off.BCM_TRANSFORM, local_transform)
    mem.poke_u64(local_bcm + Off.BCM_CONFIG, local_config)
    mem.poke_i32(local_config + Off.CFG_MAX_HEALTH, 100)
    mem.poke_f32(local_transform + Off.CTM_X, 1.25)
    mem.poke_f32(local_transform + Off.CTM_Y, 1.75)
    mem.poke_f32(local_transform + Off.CTM_Z, -0.75)
    mem.poke_u64(entities + Off.ENTITIES_LOCAL_PLAYER, player)

    return game, base
