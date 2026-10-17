import gemini_parser, geometric_engine, schemas
scene = schemas.CurrentSceneState(
    shape='L_SHAPE',
    dimensions=schemas.RoomDimensions(sideA=12.0, sideB=10.0),
    material='ACRYLIC',
    primary_color='#FFFFFF',
    countertop_material='CALACATTA_QUARTZ',
    modules=[
        schemas.ExistingModuleInfo(id='mod_base_1', name='Base 2-Door Unit', type='base', wall='A', width_feet=3.0, color='#FFFFFF'),
        schemas.ExistingModuleInfo(id='mod_base_2', name='Hob Cabinet', type='base', wall='A', width_feet=3.0, color='#FFFFFF'),
        schemas.ExistingModuleInfo(id='mod_wall_1', name='Wall Overhead Cabinet Left', type='wall', wall='A', width_feet=2.5, color='#FFFFFF'),
        schemas.ExistingModuleInfo(id='mod_wall_2', name='Wall Overhead Cabinet Right', type='wall', wall='A', width_feet=2.5, color='#FFFFFF')
    ]
)
delta = schemas.DeltaIntentResponse(
    operations=[schemas.DeltaAction(action='remove_module', params={'module_id': 'mod_wall_1'})],
    ai_summary='Removed left wall cabinet'
)
out = geometric_engine.apply_delta_operations_to_scene(scene, delta)
print('NUMBER OF MODULES RETURNED:', len(out.modules))
for m in out.modules:
    print(f'- {m.id} | {m.name} | type={m.type} | pos=({m.position.x}, {m.position.y}, {m.position.z}) | dim=({m.dimensions.width}, {m.dimensions.depth}, {m.dimensions.height}) | rot={m.rotation_y}')
