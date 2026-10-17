from pydantic import BaseModel, Field
from typing import List, Optional, Literal, Dict, Any

class RoomDimensions(BaseModel):
    sideA: float = Field(default=12.0, description="Length of Wall A in feet")
    sideB: float = Field(default=10.0, description="Length of Wall B in feet")
    sideC: Optional[float] = Field(default=0.0, description="Length of Wall C in feet")

class ExistingModuleInfo(BaseModel):
    id: str
    name: str
    type: str  # 'base', 'wall', 'drawers', 'tall', 'wicker', 'sink', 'hob', etc.
    category: Optional[str] = None
    wall: Optional[str] = "A"
    width_feet: Optional[float] = 2.0
    color: Optional[str] = "#FFFFFF"
    position_x: Optional[float] = 0.0
    position_y: Optional[float] = 0.0
    position_z: Optional[float] = 0.0

class CurrentSceneState(BaseModel):
    shape: Optional[str] = "L_SHAPE"
    dimensions: Optional[RoomDimensions] = None
    material: Optional[str] = "ACRYLIC"
    primary_color: Optional[str] = "#FFFFFF"
    secondary_color: Optional[str] = "#1E293B"
    countertop_material: Optional[str] = "CALACATTA_QUARTZ"
    modules: Optional[List[ExistingModuleInfo]] = Field(default_factory=list)

class UserPromptRequest(BaseModel):
    prompt: str = Field(..., description="Natural language prompt from user")
    current_scene: Optional[CurrentSceneState] = None

class DeltaAction(BaseModel):
    action: Literal["insert_module", "remove_module", "modify_finish", "replace_module", "restructure_layout"]
    params: Dict[str, Any] = Field(default_factory=dict)

class DeltaIntentResponse(BaseModel):
    operations: List[DeltaAction]
    ai_summary: str

class Position3D(BaseModel):
    x: float
    y: float
    z: float

class Dimensions3D(BaseModel):
    width: float
    depth: float
    height: float

class Calculated3DModule(BaseModel):
    id: str
    name: str
    type: str
    category: str
    position: Position3D
    dimensions: Dimensions3D
    rotation_y: float
    color: str
    product_name: str
    unit_price: float

class SceneOutput(BaseModel):
    shape: str
    dimensions: RoomDimensions
    material: str
    primary_color: str
    countertop_material: str
    modules: List[Calculated3DModule]
    ai_summary: str
    total_estimated_price: float
    operations: Optional[List[DeltaAction]] = Field(default_factory=list)
