import gemini_parser, schemas
req = schemas.UserPromptRequest(prompt='left side se ek wall bainet heta do A side wala')
res = gemini_parser.parse_user_prompt_to_delta(req)
print('OPERATIONS:', res.operations)
print('AI SUMMARY:', res.ai_summary)
