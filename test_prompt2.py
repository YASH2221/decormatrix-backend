import gemini_parser, schemas
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
req = schemas.UserPromptRequest(prompt='left side se ek wall bainet heta do A side wala', current_scene=scene)
res = gemini_parser.parse_user_prompt_to_delta(req)
print('OPERATIONS:', res.operations)
print('AI SUMMARY:', res.ai_summary)
