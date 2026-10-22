"""Prompt -> kitchen plan operations, using Gemini structured output.

The model only translates intent. It never computes geometry: the app's layout
engine applies these operations and enforces every fit / overlap rule.
"""
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List

log = logging.getLogger("kitchen_ai")

MODELS = [m.strip() for m in os.getenv(
    "GEMINI_MODELS", "gemini-3.5-flash-lite,gemini-3.5-flash,gemini-3.1-flash-lite"
).split(",") if m.strip()]
# Photos need the stronger model: flash-lite reads colours but misses windows and walls.
IMAGE_MODELS = [m.strip() for m in os.getenv(
    "GEMINI_IMAGE_MODELS", "gemini-3.5-flash,gemini-3.5-flash-lite"
).split(",") if m.strip()]

OPS = [
    "set_room", "auto_design", "add_module", "update_module", "update_modules", "move_module",
    "replace_module", "remove_module", "remove_modules", "duplicate_module", "fill_gaps",
    "add_opening", "update_opening", "remove_opening", "set_finishes", "set_options", "set_corner",
    "add_floor_item", "update_floor_item",
]
MODULE_TYPES = [
    "base_door", "base_drawer", "sink", "hob", "pullout", "wicker", "filler", "wall_door", "wall_glass",
    "chimney", "rolling_shutter", "loft", "tall_pantry", "tall_oven",
    "fridge", "dishwasher", "microwave", "water_purifier", "open_shelf", "crockery_unit", "wine_rack",
    "custom_base", "custom_counter", "custom_wall", "custom_tall",
]
FLOOR_TYPES = ["island", "dining_table", "bar_stool", "custom_floor"]
SHAPES = ["STRAIGHT", "L_SHAPE", "U_SHAPE", "PARALLEL"]
WALLS = ["A", "B", "C"]
SHUTTERS = ["white_gloss", "charcoal_matte", "warm_oak", "emerald_green", "royal_navy", "cashmere_greige"]
COUNTERTOPS = ["white_quartz", "black_granite", "concrete_grey"]
BACKSPLASHES = ["subway_tiles", "white_marble", "bronze_mirror"]
HANDLES = ["black", "chrome", "gold"]


def _enum(values):
    return {"type": "STRING", "enum": values}


_NUM = {"type": "NUMBER"}
_INT = {"type": "INTEGER"}
_BOOL = {"type": "BOOLEAN"}
_STR = {"type": "STRING"}
_WALL_LENGTHS = {"type": "OBJECT", "properties": {"A": _NUM, "B": _NUM, "C": _NUM}}

OP_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "op": _enum(OPS),
        "id": _STR,
        "type": _enum(MODULE_TYPES),
        "wall": _enum(WALLS),
        "width": _NUM,
        "offset": _NUM,
        "placement": {
            "type": "OBJECT",
            "properties": {"at": _enum(["start", "end", "center", "offset", "near"]), "offset": _NUM, "anchor": _STR},
        },
        "patch": {
            "type": "OBJECT",
            "properties": {
                "width": _NUM, "height": _NUM, "depth": _NUM, "elevation": _NUM,
                "doors": _INT, "drawers": _INT, "hinge": _enum(["left", "right"]),
                "shutter": _STR, "handle": _STR, "locked": _BOOL, "label": _STR, "color": _STR,
            },
        },
        "filter": {
            "type": "OBJECT",
            "properties": {
                "ids": {"type": "ARRAY", "items": _STR},
                "types": {"type": "ARRAY", "items": _enum(MODULE_TYPES)},
                "zone": _enum(["base", "counter", "wall", "loft"]),
                "wall": _enum(WALLS),
            },
        },
        "shape": _enum(SHAPES),
        "walls": _WALL_LENGTHS,
        "brief": {
            "type": "OBJECT",
            "properties": {
                "shape": _enum(SHAPES), "walls": _WALL_LENGTHS,
                "sinkWall": _enum(WALLS), "hobWall": _enum(WALLS),
                "wallCabinets": _BOOL, "loft": _BOOL, "tallPantry": _BOOL, "ovenTower": _BOOL,
                "wicker": _INT, "pullout": _BOOL, "drawerUnits": _INT, "glassWallUnits": _INT,
                "rollingShutter": _BOOL, "cornerMechanism": _enum(["blind", "magic"]),
            },
        },
        "kind": _enum(["window", "door", "gas", "water"]),
        "finishes": {
            "type": "OBJECT",
            "properties": {
                "carcass": _enum(["PLYWOOD", "PVC"]), "shutter": _STR, "wallPaint": _STR, "floor": _STR,
                "countertop": _STR, "backsplash": _STR, "handle": _STR,
            },
        },
        "options": {
            "type": "OBJECT",
            "properties": {
                "countertop": _BOOL, "backsplash": _BOOL, "skirting": _BOOL, "ledLighting": _BOOL,
                "softClose": _BOOL, "ceilingHeight": _NUM,
                "autoFill": {"type": "OBJECT", "properties": {"base": _BOOL, "wall": _BOOL, "loft": _BOOL}},
            },
        },
        "corner": {"type": "ARRAY", "items": _enum(WALLS)},
        "mechanism": _enum(["blind", "magic"]),
        "hasWallUnit": _BOOL,
    },
    "required": ["op"],
}

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "summary": _STR,
        "operations": {"type": "ARRAY", "items": OP_SCHEMA},
    },
    "required": ["summary", "operations"],
}


def _direction_notes(shape: str) -> str:
    """Which way 'left' / 'right' goes on each wall, as seen by someone facing that wall."""
    larger_left = {"L_SHAPE": ["A"], "U_SHAPE": ["A"], "PARALLEL": ["B"]}.get(shape, [])
    walls = {"STRAIGHT": ["A"], "L_SHAPE": ["A", "B"], "PARALLEL": ["A", "B"], "U_SHAPE": ["A", "B", "C"]}.get(shape, ["A"])
    lines = []
    for w in walls:
        side = "LEFT" if w in larger_left else "RIGHT"
        lines.append(f"- Wall {w}: a larger offset is further to the {side} for a person facing the wall.")
    return "\n".join(lines)


SYSTEM_PROMPT = """You are the design assistant inside DecorMatrix, an Indian modular kitchen quotation app.
The user writes in English, Hindi or Hinglish (often with typos). You translate the request into
OPERATIONS on the kitchen plan. A deterministic layout engine applies them, so you never need to
compute exact positions for neighbouring cabinets: it shrinks, shifts and refills standard
cabinets automatically and refuses anything that does not fit.

UNITS: every length is in millimetres. Convert: 1 ft = 304.8 mm, 1 inch = 25.4 mm, round to 10 mm.
"10x8 L-shape" means wall A = 3050, wall B = 2440.

WALLS & OFFSETS:
- STRAIGHT has wall A. L_SHAPE has A (left arm) and B (back). U_SHAPE has A (left), B (back), C (right).
  PARALLEL has A (back run) and B (opposite run).
- Wall lengths are the cabinet run excluding the 600 mm corner block.
- A module's offset is measured from the corner end of its wall (the start). offset + width <= wall length.
{directions}

WHEN TO USE WHAT:
- A whole new kitchen, or "redesign / bana do / design karo": ONE auto_design op with a brief
  (shape, walls, sinkWall, hobWall, wallCabinets, loft, tallPantry, ovenTower, wicker count, pullout,
  drawerUnits, glassWallUnits, rollingShutter, cornerMechanism). Put windows / gas / water points
  BEFORE it with add_opening so the sink goes under the window and the hob at the gas point.
  Add set_finishes after it if colours are mentioned.
- Small edits: add_module / move_module / update_module / replace_module / remove_module, using module
  ids from CURRENT PLAN. For "next to the hob / sink" use placement {{at:"near", anchor:"hob"}} (or a
  module id). For "left of X" / "right of X" compute offset from X's offset and width using the
  direction notes above and use placement {{at:"offset", offset}} or move_module offset.
- Many modules at once ("saare wall cabinets", "all shutters"): update_modules / remove_modules with a filter.
- Kitchen-wide colours: set_finishes. A single cabinet's colour: update_module patch.shutter (see COLOURS).
- Turning wall cabinets or loft on/off for the whole kitchen: set_options options.autoFill.wall / .loft.
- Corner mechanism: set_corner with corner ["A","B"] (or ["B","C"]) and mechanism.
- Appliances in a run: fridge, dishwasher, microwave (sits on the counter), water_purifier, open_shelf,
  crockery_unit, wine_rack -> add_module.
- ANY other item the user names (coffee station, tandoor, pooja unit, OTG shelf, spice tray...): add_module
  with a custom_* type that matches where it goes (custom_base below the counter, custom_counter on it,
  custom_wall on the wall, custom_tall floor-to-top) and patch {{label:"<their name>", width, height, depth, color:"#rrggbb"}}.
- Free-standing things anywhere on the floor (island, dining table, bar stools, or a custom one) -> add_floor_item
  {{type, x?, z?, patch:{{width?, depth?, height?, rotation?, label?, color?}}}}. Omit x / z to centre it on the open
  floor. x grows to the right, z grows towards the front (away from wall B / wall A of a straight kitchen),
  in mm from the back-left corner. Change them later with update_floor_item {{id, patch}}; delete / duplicate
  floor items with remove_module / duplicate_module using their id from floorItems.
- The 3D design is for visualisation only: nothing you do changes the customer's quotation.
- NEVER change or remove modules with "locked": true.
- NEVER invent module ids. Use ids from CURRENT PLAN, or "$last" for the module created by an earlier
  operation in your own list. To put a NEW module next to something, give add_module a placement
  {{at:"near", anchor:...}} directly instead of adding and then moving it.
- Every feature the user mentions must appear in the brief (e.g. "tall pantry" -> tallPantry: true,
  "2 wicker baskets" -> wicker: 2, "loft" -> loft: true). Omit features they did not mention.
- Openings: give offset when the user says where (from the corner end); for "in the middle" you may
  omit offset and the engine centres it. Default widths: window 1200, door 900.
- Only include fields the operation needs. If the request is unclear or impossible, return no
  operations and say why in the summary.

EXAMPLES (shape L_SHAPE):
"8x10 L kitchen, khidki B wall ke beech mein, gas point A wall pe, pantry aur 2 tokri" ->
[{{op:"add_opening",kind:"window",wall:"B"}}, {{op:"add_opening",kind:"gas",wall:"A",offset:1500}},
 {{op:"auto_design",brief:{{shape:"L_SHAPE",walls:{{A:2440,B:3050}},tallPantry:true,wicker:2}}}}]
"hob ke right mein bottle pullout" (hob on wall B) ->
[{{op:"add_module",type:"pullout",wall:"B",placement:{{at:"near",anchor:"hob"}}}}]

VOCABULARY:
- hata do / nikal do / hatao / delete / remove -> remove. lagao / daalo / add karo / chahiye -> add.
- khiskao / shift / move / sarkao -> move. bada / chauda -> wider. chhota -> narrower.
- almari / cabinet / box / unit -> cabinet. neeche wala / base -> base zone. upar wala / wall / overhead -> wall zone.
- drawer / daraaz / दराज / tandem -> base_drawer. tokri / basket / wicker -> wicker. bottle / masala / spice pullout -> pullout.
- pantry / tall unit -> tall_pantry. oven / microwave / OTG tower -> tall_oven. chimney / hood -> chimney.
COLOURS (any colour works — never refuse or substitute a different colour):
- Use the user's EXACT colour as "#rrggbb": "olive green" -> "#708238", "peach" -> "#ffcba4", "light blue" -> "#a7c7e7",
  "maroon" -> "#7b1e2b", "lal" -> "#c0392b", "neela" -> "#2563eb", "hara" -> "#2e8b57", "gulabi" -> "#ec8fb0",
  "#ff8800" stays "#ff8800". Respect light / dark ("halka", "gehra").
- Use a preset name only when the user asks for that material/look: wooden / lakdi / oak -> warm_oak shutters,
  granite -> black_granite, quartz / marble -> white_quartz / white_marble, subway tiles -> subway_tiles,
  mirror -> bronze_mirror, chrome / steel handles -> chrome.
- Targets: shutters (all cabinets) -> set_finishes.shutter; countertop / platform / slab -> set_finishes.countertop;
  backsplash / dado / tiles behind the counter -> set_finishes.backsplash; handles -> set_finishes.handle;
  room walls / deewar / paint -> set_finishes.wallPaint; floor / farsh -> set_finishes.floor.
- Only some cabinets ("upar wale", "wall cabinets", "drawers", "island"): update_modules with a filter and
  patch.shutter, or update_module / update_floor_item for one item. Appliances, custom items and floor items
  (island, table…) use patch.color, always as "#rrggbb" (never a preset name).
  Two-tone kitchens are common: e.g. base cabinets one colour (filter zone "base") and wall cabinets another (zone "wall").

OUTPUT: only JSON, exactly {{"summary": "...", "operations": [ ... ]}}. Operation formats:
{{op:"set_room", shape?, walls?:{{A?,B?,C?}}}}
{{op:"auto_design", brief:{{shape?, walls?, sinkWall?, hobWall?, wallCabinets?, loft?, tallPantry?, ovenTower?,
   wicker?:int, pullout?, drawerUnits?:int, glassWallUnits?:int, rollingShutter?, cornerMechanism?:"blind"|"magic"}}}}
{{op:"add_module", type, wall?, width?, placement?:{{at:"start"|"end"|"center"}} | {{at:"offset",offset}} | {{at:"near",anchor}}, patch?}}
{{op:"update_module", id, patch:{{width?, height?, depth?, elevation?, doors?:1|2, drawers?, hinge?:"left"|"right", shutter?, handle?, locked?, label?, color?}}}}
{{op:"add_floor_item", type:{floor_types}, x?, z?, patch?:{{width?, depth?, height?, rotation?, label?, color?}}}}
{{op:"update_floor_item", id, patch:{{x?, z?, rotation?, width?, depth?, height?, label?, color?, locked?}}}}
{{op:"update_modules", filter:{{ids?, types?, zone?:"base"|"counter"|"wall"|"loft", wall?}}, patch}}
{{op:"move_module", id, wall?, offset?}}  or  {{op:"move_module", id, placement}}
{{op:"replace_module", id, type}}   {{op:"remove_module", id}}   {{op:"remove_modules", filter}}
{{op:"duplicate_module", id}}   {{op:"fill_gaps", wall?, zone?}}
{{op:"add_opening", kind:"window"|"door"|"gas"|"water", wall, offset?, width?}}
{{op:"update_opening", id, wall?, offset?, width?}}   {{op:"remove_opening", id}}
{{op:"set_finishes", finishes:{{carcass?:"PLYWOOD"|"PVC", shutter?, countertop?, backsplash?, handle?, wallPaint?, floor?}}}}
  (each colour field: a preset name below or "#rrggbb"; wallPaint / floor: "#rrggbb")
{{op:"set_options", options:{{countertop?, backsplash?, skirting?, ledLighting?, softClose?, ceilingHeight?, autoFill?:{{wall?, loft?}}}}}}
{{op:"set_corner", corner:["A","B"], mechanism?, hasWallUnit?}}
Module types: {module_types}.
Shutters: {shutters}. Countertops: {countertops}. Backsplashes: {backsplashes}. Handles: {handles}.

SUMMARY: one short sentence in the user's language describing what you changed."""


_DROP = object()


def _clean(value: Any) -> Any:
    """Drop nulls, empty objects and absurd numbers (models sometimes emit 2e+99)."""
    if isinstance(value, dict):
        out = {k: _clean(v) for k, v in value.items() if v is not None}
        return {k: v for k, v in out.items() if v is not _DROP and v != {} and v != []}
    if isinstance(value, list):
        return [c for c in (_clean(v) for v in value if v is not None) if c is not _DROP]
    if isinstance(value, float):
        if value != value or abs(value) > 100_000:  # NaN or out of any real kitchen range
            return _DROP
        return int(round(value)) if abs(value - round(value)) < 1e-6 else round(value, 1)
    if isinstance(value, int) and not isinstance(value, bool) and abs(value) > 100_000:
        return _DROP
    return value


# Preset colours (same as DecorMatrix/src/kitchen/catalog.ts). The model sometimes puts a preset
# from one table into another field (e.g. shutter "bronze_mirror"); the engine only accepts a
# field's own presets, so such a value is swapped for that preset's colour.
PRESET_HEX = {
    "white_gloss": "#ffffff", "charcoal_matte": "#22272e", "warm_oak": "#b47846",
    "emerald_green": "#0f4c3a", "royal_navy": "#142850", "cashmere_greige": "#d6cbbd",
    "white_quartz": "#f1f5f9", "black_granite": "#111115", "concrete_grey": "#88929e",
    "subway_tiles": "#e2e8f0", "white_marble": "#f8fafc", "bronze_mirror": "#3d3126",
    "black": "#111111", "chrome": "#dddddd", "gold": "#d4af37",
}
FIELD_PRESETS = {"shutter": SHUTTERS, "countertop": COUNTERTOPS, "backsplash": BACKSPLASHES, "handle": HANDLES}


def _fix_presets(values: Any, fields) -> None:
    if not isinstance(values, dict):
        return
    for field in fields:
        v = values.get(field)
        if isinstance(v, str) and v in PRESET_HEX and v not in FIELD_PRESETS.get(field, ()):
            values[field] = PRESET_HEX[v]


def normalise_operations(raw_ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ops = []
    for raw in raw_ops or []:
        if not isinstance(raw, dict) or raw.get("op") not in OPS:
            continue
        op = _clean(raw)
        _fix_presets(op.get("finishes"), FIELD_PRESETS)
        # Per-module colour is any colour, so wallPaint / floor / color presets become hex too.
        _fix_presets(op.get("patch"), ("shutter", "handle", "color"))
        _fix_presets(op.get("finishes"), ("wallPaint", "floor"))
        if op["op"] == "set_corner":
            op["walls"] = op.pop("corner", None) or ["A", "B"]
        else:
            op.pop("corner", None)
        placement = op.get("placement")
        if isinstance(placement, dict) and placement.get("at") != "offset":
            placement.pop("offset", None)
        if isinstance(placement, dict) and placement.get("at") != "near":
            placement.pop("anchor", None)
        ops.append(op)
    return ops


def _call_gemini(model: str, api_key: str, payload: Dict[str, Any], timeout: float) -> Dict[str, Any]:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    with urllib.request.urlopen(req, timeout=timeout) as res:
        data = json.loads(res.read().decode("utf-8"))
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def _system_prompt(shape: str) -> str:
    return SYSTEM_PROMPT.format(
        directions=_direction_notes(shape),
        module_types=", ".join(MODULE_TYPES),
        floor_types="|".join(f'"{t}"' for t in FLOOR_TYPES),
        shutters=", ".join(SHUTTERS),
        countertops=", ".join(COUNTERTOPS),
        backsplashes=", ".join(BACKSPLASHES),
        handles=", ".join(HANDLES),
    )


def _generate(system: str, parts: List[Dict[str, Any]], timeout: float, models: List[str]) -> Dict[str, Any]:
    """Runs the request through MODELS in order and returns the first usable answer."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY is not set on the server")

    base_payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    # Constrained decoding with RESPONSE_SCHEMA made the flash models drop optional booleans
    # (e.g. tallPantry) in testing, so plain JSON mode is the default; set GEMINI_STRUCTURED=1 to try it.
    payloads = [base_payload]
    if os.getenv("GEMINI_STRUCTURED") == "1":
        with_schema = json.loads(json.dumps(base_payload))
        with_schema["generationConfig"]["responseSchema"] = RESPONSE_SCHEMA
        payloads.insert(0, with_schema)

    last_error = None
    for model in models:
        for payload in payloads:
            try:
                result = _call_gemini(model, api_key, payload, timeout)
                if isinstance(result, list):  # model returned the operations array on its own
                    result = {"operations": result, "summary": ""}
                return {
                    "operations": normalise_operations(result.get("operations", [])),
                    "summary": str(result.get("summary", "")),
                    "model": model,
                }
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", "ignore")[:300]
                last_error = f"{model}: HTTP {e.code} {body}"
                log.warning("Gemini %s", last_error)
                # 400 may be the schema being rejected -> retry the same model without it.
                if e.code != 400:
                    break
            except Exception as e:  # network, bad JSON, empty candidates
                last_error = f"{model}: {e}"
                log.warning("Gemini %s", last_error)
                break
    raise RuntimeError(f"All Gemini models failed. Last error: {last_error}")


def prompt_to_operations(prompt: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    system = _system_prompt(str(plan.get("shape") or "L_SHAPE"))
    user = f"CURRENT PLAN:\n{json.dumps(plan, separators=(',', ':'))}\n\nUSER REQUEST:\n{prompt}"
    return _generate(system, [{"text": user}], float(os.getenv("GEMINI_TIMEOUT_SECONDS", "15")), MODELS)


# --- Reference photo -> arrangement + finishes ----------------------------------------------------
# The user has already fixed the shape, the wall lengths and every item with its size (the quotation).
# A photo may only rearrange those modules and restyle them, so anything that adds, removes or
# resizes is dropped here, whatever the model returns.
IMAGE_OPS = {"move_module", "update_module", "update_modules", "set_finishes", "set_options", "add_opening", "update_opening"}
SIZE_FIELDS = ("width", "height", "depth", "elevation")
IMAGE_OPTIONS = ("countertop", "backsplash", "skirting", "ledLighting")

IMAGE_PROMPT = """

REFERENCE PHOTO MODE:
The user attached a photo of a kitchen they like. Recreate its LOOK and ARRANGEMENT on CURRENT PLAN.
The shape, the wall lengths and every module with its width are the customer's quotation and are FIXED:
- NEVER add, remove, replace, duplicate or resize modules, never use auto_design / set_room / set_corner /
  add_floor_item, and never put width / height / depth / elevation in a patch.
- Allowed: move_module (put the existing sink, hob, pantry, drawers, appliances in the same order and
  on the same walls as the photo), update_module / update_modules (shutter colour, handle, doors,
  drawers, hinge), set_finishes (shutters, countertop, backsplash, handles, wallPaint, floor),
  set_options (countertop, backsplash, skirting, ledLighting) and add_opening for windows / gas
  points clearly visible in the photo when the plan has none on that wall: one add_opening per
  window you see (two windows -> two ops, spread along the wall, e.g. offsets near 1/4 and 3/4).
- Map the photo to walls: STRAIGHT -> the one run is A. L_SHAPE -> the run on the left of the photo is A,
  the back run is B (if only two runs are visible, the longer back run is B). U_SHAPE -> left A, back B,
  right C. PARALLEL -> the run the photo faces is A, the opposite one B. If the photo shows fewer walls
  than the plan, arrange what is visible and leave the rest.
- If the photo has items the plan does not have, ignore them and mention them in the summary as
  suggestions ("photo mein tall unit bhi hai"). If the plan has items the photo does not show, keep them.
- Colours: measure each colour from the photo itself and write it as "#rrggbb". Do NOT reuse the example
  codes from the COLOURS list above (e.g. a sage / muted green is NOT "#708238"; pick the shade you see,
  allowing for sunlight and shadow). Use a preset name only when it clearly matches, e.g. a wooden oak
  look -> warm_oak, black granite -> black_granite.
- Cabinet rows are separate zones and each gets its own colour when the photo differs:
  zone "base" = below the counter, zone "wall" = the upper cabinets above the backsplash,
  zone "loft" = a second, higher row up to the ceiling. If the photo shows two rows of upper cabinets,
  the top row is the loft. Use set_finishes.shutter for the most common colour, then update_modules with
  filter zone for the rows that differ. Glass or mirror shutters: use the glass colour (e.g. tinted black
  glass -> a near-black "#rrggbb"). Handleless / profile (gola) handles: use handle "black" when the
  profile is dark, "chrome" when it is steel.
- Move each module at most once, with an explicit offset that keeps it inside its wall. Order the
  moves from the corner end outwards.
- If the photo is not a kitchen, return no operations and say so in the summary.
"""


def _image_safe(ops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for op in ops:
        if op["op"] not in IMAGE_OPS:
            continue
        if isinstance(op.get("patch"), dict):
            for k in SIZE_FIELDS:
                op["patch"].pop(k, None)
            if not op["patch"]:
                continue
        if op["op"] == "set_options":
            op["options"] = {k: v for k, v in (op.get("options") or {}).items() if k in IMAGE_OPTIONS}
            if not op["options"]:
                continue
        if op["op"] == "add_opening" and op.get("kind") == "door":
            continue
        out.append(op)
    return out


def image_to_operations(image_b64: str, mime_type: str, note: str, plan: Dict[str, Any]) -> Dict[str, Any]:
    system = _system_prompt(str(plan.get("shape") or "L_SHAPE")) + IMAGE_PROMPT
    user = (
        f"CURRENT PLAN:\n{json.dumps(plan, separators=(',', ':'))}\n\n"
        f"USER REQUEST:\n{note or 'Make my kitchen look and be arranged like this photo.'}"
    )
    parts = [{"inline_data": {"mime_type": mime_type, "data": image_b64}}, {"text": user}]
    result = _generate(system, parts, float(os.getenv("GEMINI_IMAGE_TIMEOUT_SECONDS", "40")), IMAGE_MODELS)
    result["operations"] = _image_safe(result["operations"])
    return result
