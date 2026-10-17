import math
import uuid
from typing import List, Dict, Any
from schemas import (
    CurrentSceneState, DeltaIntentResponse, SceneOutput,
    Calculated3DModule, Position3D, Dimensions3D, RoomDimensions
)

BASE_H = 2.80
BASE_D = 2.00
WALL_H = 2.30
WALL_D = 1.20
WALL_BOTTOM = 4.70
TALL_H = 7.00
COUNTERTOP_THICK = 0.13

PRICE_CATALOG = {
    "base_2door": 7500.0,
    "base_3drawer": 9200.0,
    "sink_unit": 9800.0,
    "hob_unit": 10500.0,
    "corner_l": 14000.0,
    "pullout": 4500.0,
    "wicker_basket": 8500.0,
    "wall_unit": 6200.0,
    "wall_liftup": 7800.0,
    "tall_pantry": 18500.0,
    "countertop": 850.0
}

def apply_delta_operations_to_scene(
    current_scene: CurrentSceneState,
    delta: DeltaIntentResponse
) -> SceneOutput:
    """
    PRO SOLUTION: State-preserving CAD Math Engine
    Applies atomic operations (insert, remove, modify_finish, replace) to existing modules.
    Never wipes out state unless restructure_layout is called.
    """
    dims = current_scene.dimensions or RoomDimensions(sideA=12.0, sideB=10.0, sideC=0.0)
    sideA = max(6.0, dims.sideA)
    sideB = max(6.0, dims.sideB)
    shape = current_scene.shape or "L_SHAPE"
    primary_color = current_scene.primary_color or "#FFFFFF"
    material = current_scene.material or "ACRYLIC"
    countertop_mat = current_scene.countertop_material or "CALACATTA_QUARTZ"

    # Convert existing modules to working state
    working_modules = []
    if current_scene.modules:
        for m in current_scene.modules:
            working_modules.append({
                "id": m.id,
                "name": m.name,
                "type": m.type,
                "category": m.category or ("wall" if "wall" in m.type else ("tall" if "tall" in m.type else "base")),
                "wall": m.wall or "A",
                "width_feet": m.width_feet or 2.0,
                "color": m.color or primary_color
            })
    else:
        # Default starting modules if scene was empty
        working_modules = [
            {"id": "mod_sink_1", "name": "Sink Cabinet with Bowl", "type": "sink_unit", "category": "base", "wall": "A", "width_feet": 3.0, "color": primary_color},
            {"id": "mod_draw_1", "name": "3-Drawer Tandem Unit", "type": "base_3drawer", "category": "base", "wall": "A", "width_feet": 2.0, "color": primary_color},
            {"id": "mod_hob_1", "name": "4-Burner Hob Cabinet", "type": "hob_unit", "category": "base", "wall": "A", "width_feet": 3.0, "color": primary_color},
            {"id": "mod_wall_1", "name": "Wall Storage Unit", "type": "wall_unit", "category": "wall", "wall": "A", "width_feet": 3.0, "color": primary_color}
        ]

    # APPLY EACH OPERATION IN ORDER
    for op in delta.operations:
        action = op.action
        params = op.params

        # 1. MODIFY FINISH
        if action == "modify_finish":
            target = params.get("target", "ALL_SHUTTERS")
            new_color = params.get("color_hex", primary_color)
            new_mat = params.get("material_name", material)
            material = new_mat

            if target in ["ALL_SHUTTERS", "ALL"]:
                primary_color = new_color
                for m in working_modules:
                    if m["type"] != "countertop":
                        m["color"] = new_color
            elif target == "COUNTERTOP":
                countertop_mat = params.get("countertop_material", "CALACATTA_QUARTZ")

        # 2. INSERT MODULE
        elif action == "insert_module":
            m_type = params.get("type", "base_2door")
            # Map vernacular viki
            if "viki" in m_type or "wicker" in m_type or "basket" in m_type:
                m_type = "wicker_basket"

            m_name = params.get("name") or ("Wicker Vegetable Baskets Unit (Viki)" if m_type == "wicker_basket" else "Modular Cabinet")
            m_wall = params.get("wall", "A")
            m_width = float(params.get("width_feet", 1.5 if m_type in ["wicker_basket", "pullout"] else 2.0))
            anchor_id = params.get("anchor_id")
            side = params.get("side", "RIGHT")

            new_item = {
                "id": f"mod_{m_type}_{uuid.uuid4().hex[:6]}",
                "name": m_name,
                "type": m_type,
                "category": "tall" if "tall" in m_type else ("wall" if "wall" in m_type else "base"),
                "wall": m_wall,
                "width_feet": m_width,
                "color": primary_color
            }

            # Find anchor position
            anchor_idx = -1
            if anchor_id:
                for idx, m in enumerate(working_modules):
                    if m["id"] == anchor_id or anchor_id in m["id"] or anchor_id in m["name"].lower():
                        anchor_idx = idx
                        break

            if anchor_idx != -1:
                insert_pos = anchor_idx + 1 if side == "RIGHT" else anchor_idx
                working_modules.insert(insert_pos, new_item)
            else:
                if "tall" in m_type:
                    working_modules.insert(0, new_item) # Tall units anchor at start
                else:
                    working_modules.append(new_item)

        # 3. REMOVE MODULE
        elif action == "remove_module":
            target_id = params.get("module_id")
            target_type = params.get("type")
            working_modules = [
                m for m in working_modules
                if (not target_id or m["id"] != target_id) and (not target_type or m["type"] != target_type)
            ]

        # 4. REPLACE MODULE
        elif action == "replace_module":
            target_type = params.get("target_type")
            new_type = params.get("new_type")
            for m in working_modules:
                if m["type"] == target_type:
                    m["type"] = new_type
                    m["name"] = "Wicker Vegetable Baskets Unit (Viki)" if new_type == "wicker_basket" else f"Replaced Unit ({new_type})"
                    break

        # 5. RESTRUCTURE LAYOUT
        elif action == "restructure_layout":
            shape = params.get("shape", shape)

    # NOW CALCULATE EXACT COLLISION-FREE 3D GEOMETRY FROM WORKING MODULES
    calculated_modules: List[Calculated3DModule] = []
    total_price = 0.0

    # Separate base, wall, and tall modules
    tall_units = [m for m in working_modules if m["category"] == "tall"]
    base_units_a = [m for m in working_modules if m["category"] in ["base", "wicker_basket"] and m.get("wall") != "B"]
    base_units_b = [m for m in working_modules if m["category"] in ["base", "wicker_basket"] and m.get("wall") == "B"]
    wall_units = [m for m in working_modules if m["category"] == "wall"]

    # 1. Place Tall Units at start of Wall A
    cursor_x = 0.0
    for t in tall_units:
        w = t.get("width_feet", 2.0)
        p = PRICE_CATALOG.get(t["type"], 18500.0)
        total_price += p
        calculated_modules.append(Calculated3DModule(
            id=t["id"],
            name=t["name"],
            type="tall",
            category="tall",
            position=Position3D(x=round(cursor_x + w / 2, 3), y=round(TALL_H / 2, 3), z=round(BASE_D / 2, 3)),
            dimensions=Dimensions3D(width=w, depth=BASE_D, height=TALL_H),
            rotation_y=0.0,
            color=t.get("color") or "#334155",
            product_name="7ft Modular Tall Pantry Unit",
            unit_price=p
        ))
        cursor_x += w

    # 2. Place Base Units along Wall A
    has_corner = shape in ["L_SHAPE", "U_SHAPE"]
    corner_size = 3.0
    avail_a = sideA - cursor_x - (corner_size if has_corner else 0.0)

    for b in base_units_a:
        w = b.get("width_feet", 2.0)
        if cursor_x + w > (sideA - (corner_size if has_corner else 0.0)):
            w = max(1.0, sideA - cursor_x - (corner_size if has_corner else 0.0))
        if w < 0.6:
            break

        p = PRICE_CATALOG.get(b["type"], 7500.0)
        total_price += p
        calculated_modules.append(Calculated3DModule(
            id=b["id"],
            name=b["name"],
            type="wicker_basket" if b["type"] == "wicker_basket" else "base",
            category=b["type"],
            position=Position3D(x=round(cursor_x + w / 2, 3), y=round(BASE_H / 2, 3), z=round(BASE_D / 2, 3)),
            dimensions=Dimensions3D(width=round(w, 2), depth=BASE_D, height=BASE_H),
            rotation_y=0.0,
            color="#D97706" if b["type"] == "wicker_basket" else (b.get("color") or primary_color),
            product_name=b["name"],
            unit_price=p
        ))
        cursor_x += w

    # 3. Corner L Unit
    if has_corner:
        c_price = PRICE_CATALOG["corner_l"]
        total_price += c_price
        calculated_modules.append(Calculated3DModule(
            id=f"mod_corner_{uuid.uuid4().hex[:6]}",
            name="Corner L-Shape Carcass (900x900)",
            type="base",
            category="corner_l",
            position=Position3D(x=round(sideA - corner_size / 2, 3), y=round(BASE_H / 2, 3), z=round(corner_size / 2, 3)),
            dimensions=Dimensions3D(width=corner_size, depth=corner_size, height=BASE_H),
            rotation_y=0.0,
            color=primary_color,
            product_name="Modular Magic Corner Unit",
            unit_price=c_price
        ))

        # Base Units along Wall B
        cursor_z = corner_size
        if not base_units_b:
            base_units_b = [
                {"id": f"mod_b_{uuid.uuid4().hex[:6]}", "name": "Base Storage 2-Door 900mm", "type": "base_2door", "width_feet": 3.0, "color": primary_color}
            ]
        for b in base_units_b:
            w = b.get("width_feet", 2.5)
            if cursor_z + w > sideB:
                w = max(1.0, sideB - cursor_z)
            if w < 0.6:
                break
            p = PRICE_CATALOG.get(b["type"], 7500.0)
            total_price += p
            calculated_modules.append(Calculated3DModule(
                id=b["id"],
                name=b["name"],
                type="base",
                category=b["type"],
                position=Position3D(x=round(sideA - BASE_D / 2, 3), y=round(BASE_H / 2, 3), z=round(cursor_z + w / 2, 3)),
                dimensions=Dimensions3D(width=BASE_D, depth=round(w, 2), height=BASE_H),
                rotation_y=round(math.pi / 2, 3),
                color=b.get("color") or primary_color,
                product_name=b["name"],
                unit_price=p
            ))
            cursor_z += w

    # 4. Countertop
    top_price = round(sideA * PRICE_CATALOG["countertop"], 2)
    total_price += top_price
    calculated_modules.append(Calculated3DModule(
        id=f"top_a_{uuid.uuid4().hex[:6]}",
        name=f"Quartz Countertop Wall A",
        type="countertop",
        category="countertop",
        position=Position3D(x=round(sideA / 2, 3), y=round(BASE_H + COUNTERTOP_THICK / 2, 3), z=round(BASE_D / 2 + 0.05, 3)),
        dimensions=Dimensions3D(width=round(sideA, 2), depth=round(BASE_D + 0.1, 2), height=COUNTERTOP_THICK),
        rotation_y=0.0,
        color="#F8FAFC",
        product_name=f"20mm {countertop_mat.replace('_', ' ').title()}",
        unit_price=top_price
    ))

    # 5. Wall Units
    curr_wall_x = 0.5
    for w_mod in wall_units:
        w = w_mod.get("width_feet", 2.5)
        if curr_wall_x + w > (sideA - (1.5 if has_corner else 0.5)):
            break
        p = PRICE_CATALOG.get(w_mod["type"], 6200.0)
        total_price += p
        calculated_modules.append(Calculated3DModule(
            id=w_mod["id"],
            name=w_mod["name"],
            type="wall",
            category=w_mod["type"],
            position=Position3D(x=round(curr_wall_x + w / 2, 3), y=round(WALL_BOTTOM + WALL_H / 2, 3), z=round(WALL_D / 2, 3)),
            dimensions=Dimensions3D(width=round(w, 2), depth=WALL_D, height=WALL_H),
            rotation_y=0.0,
            color=w_mod.get("color") or primary_color,
            product_name=w_mod["name"],
            unit_price=p
        ))
        curr_wall_x += w

    return SceneOutput(
        shape=shape,
        dimensions=dims,
        material=material,
        primary_color=primary_color,
        countertop_material=countertop_mat,
        modules=calculated_modules,
        ai_summary=delta.ai_summary,
        total_estimated_price=round(total_price, 2)
    )
