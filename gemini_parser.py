import os
import json
import urllib.request
from dotenv import load_dotenv
from schemas import UserPromptRequest, DeltaIntentResponse, DeltaAction, RoomDimensions

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY is not set (add it to decormatrix-backend/.env)")

MODELS_LIST = [
    "gemini-3.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3-flash-preview"
]

SYSTEM_PROMPT = """You are an expert Modular Kitchen CAD State Architect.
You will receive:
1. The User's natural language Prompt.
2. The CURRENT 3D Kitchen State (list of existing cabinets with their IDs, types, names, and current finish).

Your mission is INCREMENTAL DELTA EDITING: DO NOT delete or regenerate the entire kitchen unless explicitly asked to rebuild or restructure!
Output a list of atomic OPERATIONS to mutate the current kitchen state.

Supported Actions and Parameter Schemas:
1. 'insert_module':
   - 'type': one of ['wicker_basket', 'base_3drawer', 'base_2door', 'sink_unit', 'hob_unit', 'pullout', 'tall_pantry', 'wall_unit', 'wall_liftup']
   - 'name': human-readable name (e.g. 'Wicker Vegetable Baskets Unit (Viki)')
   - 'anchor_id': optional existing module ID to place relative to (e.g. the sink ID or hob ID)
   - 'side': 'LEFT' or 'RIGHT' (default 'RIGHT')
   - 'wall': 'A' or 'B' (default 'A')
   - 'width_feet': float (e.g. 1.5, 2.0, 3.0)

2. 'remove_module':
   - 'module_id': ID of the module to remove, OR
   - 'type': type of module to remove if ID is unknown (e.g. 'tall_pantry')

3. 'modify_finish':
   - 'target': 'ALL_SHUTTERS', 'COUNTERTOP', or 'SPECIFIC_MODULE'
   - 'color_hex': e.g. '#1E3A8A' (Navy Blue), '#FFFFFF' (White), '#475569' (Charcoal Grey), '#65A30D' (Sage Green)
   - 'material_name': 'ACRYLIC', 'LAMINATE', 'PU_PAINT', 'VENEER'

4. 'replace_module':
   - 'target_type': e.g. 'base_2door'
   - 'new_type': e.g. 'wicker_basket' or 'base_3drawer'

5. 'restructure_layout':
   - 'shape': 'STRAIGHT', 'L_SHAPE', 'PARALLEL', 'U_SHAPE'

NOTE:
- 'viki', 'vicker', 'basket', 'sabzi basket' ALWAYS maps to type: 'wicker_basket'.
- 'tandem', 'drawer', '3 drawer' ALWAYS maps to type: 'base_3drawer'.
- 'pantry', 'tall unit', '7ft' ALWAYS maps to type: 'tall_pantry'.

Output ONLY valid JSON matching:
{
  "operations": [
    {
      "action": "insert_module",
      "params": {
        "type": "wicker_basket",
        "name": "Wicker Vegetable Baskets Unit (Viki)",
        "anchor_id": "optional_id",
        "side": "RIGHT",
        "wall": "A",
        "width_feet": 1.5
      }
    }
  ],
  "ai_summary": "Added a 450mm Wicker Basket (Viki) next to the unit."
}
"""

def parse_user_prompt_to_delta(req: UserPromptRequest) -> DeltaIntentResponse:
    current_scene = req.current_scene
    modules_summary = []
    if current_scene and current_scene.modules:
        for m in current_scene.modules:
            modules_summary.append({
                "id": m.id,
                "name": m.name,
                "type": m.type,
                "wall": m.wall or "A",
                "width_feet": m.width_feet or 2.0,
                "color": m.color or "#FFFFFF"
            })

    context_str = f"""User Prompt: "{req.prompt}"

CURRENT KITCHEN STATE:
- Room Shape: {current_scene.shape if current_scene else 'L_SHAPE'}
- Wall A: {current_scene.dimensions.sideA if (current_scene and current_scene.dimensions) else 12.0} ft
- Wall B: {current_scene.dimensions.sideB if (current_scene and current_scene.dimensions) else 10.0} ft
- Active Finish: {current_scene.material if current_scene else 'ACRYLIC'}, Color: {current_scene.primary_color if current_scene else '#FFFFFF'}
- Existing Cabinets ({len(modules_summary)} items currently in room):
{json.dumps(modules_summary, indent=2)}
"""

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": SYSTEM_PROMPT + "\n\n" + context_str}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }
    body = json.dumps(payload).encode("utf-8")

    for model_name in MODELS_LIST:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        try:
            http_req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
            res = urllib.request.urlopen(http_req, timeout=12)
            res_data = json.loads(res.read().decode("utf-8"))
            raw_text = res_data["candidates"][0]["content"]["parts"][0]["text"].strip()
            if raw_text.startswith("```"):
                lines = raw_text.splitlines()
                raw_text = "\n".join([l for l in lines if not l.startswith("```")])
            data = json.loads(raw_text)
            print(f"[SUCCESS] Parsed delta operations with model: {model_name}")
            return DeltaIntentResponse(**data)
        except Exception as e:
            print(f"Warning: Model {model_name} failed: {e}. Trying next...")

    # Heuristic Fallback
    p_lower = req.prompt.lower()
    ops = []
    summary = "Updated kitchen design."

    # Check for color/finish
    if "navy" in p_lower or "blue" in p_lower:
        ops.append(DeltaAction(action="modify_finish", params={"target": "ALL_SHUTTERS", "color_hex": "#1E3A8A", "material_name": "ACRYLIC"}))
        summary = "Changed cabinet finish to Navy Blue."
    elif "charcoal" in p_lower or "grey" in p_lower or "gray" in p_lower:
        ops.append(DeltaAction(action="modify_finish", params={"target": "ALL_SHUTTERS", "color_hex": "#475569", "material_name": "ACRYLIC"}))
        summary = "Changed cabinet finish to Slate Grey."

    # Check for wicker basket / viki
    if "viki" in p_lower or "wicker" in p_lower or "basket" in p_lower:
        ops.append(DeltaAction(action="insert_module", params={
            "type": "wicker_basket",
            "name": "Wicker Vegetable Baskets Unit (Viki)",
            "side": "RIGHT",
            "wall": "A",
            "width_feet": 1.5
        }))
        summary += " Added Wicker Basket (Viki) unit."

    # Check for tall pantry
    if "tall" in p_lower or "pantry" in p_lower:
        ops.append(DeltaAction(action="insert_module", params={
            "type": "tall_pantry",
            "name": "Pantry Tall Unit 7ft",
            "side": "LEFT",
            "wall": "A",
            "width_feet": 2.0
        }))
        summary += " Added 7ft Tall Pantry unit on left."

    # Check for 3-drawer
    if "drawer" in p_lower or "tandem" in p_lower:
        ops.append(DeltaAction(action="insert_module", params={
            "type": "base_3drawer",
            "name": "3-Drawer Tandem Unit",
            "side": "RIGHT",
            "wall": "A",
            "width_feet": 2.0
        }))
        summary += " Added 3-Drawer Tandem unit."

    return DeltaIntentResponse(operations=ops, ai_summary=summary)
