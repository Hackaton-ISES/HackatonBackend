import os


def generate_risk_summary(*, tender, analysis) -> str:
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        return ''

    try:
        from google import genai
    except ImportError:
        return ''

    model_name = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
    client = genai.Client(api_key=api_key)
    reasons = '\n'.join(
        f'- {reason.title}: {reason.description}'
        for reason in analysis.reasons.all()
    ) or '- No risk reasons triggered.'

    prompt = (
        'You are assisting an anti-corruption analyst. '
        'Write a concise, plain-English summary of this tender risk assessment in 4 sentences or less.\n'
        f'Tender title: {tender.title}\n'
        f'Organization: {tender.organization}\n'
        f'Category: {tender.category}\n'
        f'Total score: {analysis.total_score}\n'
        f'Risk level: {analysis.risk_level}\n'
        f'Reasons:\n{reasons}'
    )
    response = client.models.generate_content(model=model_name, contents=prompt)
    return getattr(response, 'text', '') or ''
