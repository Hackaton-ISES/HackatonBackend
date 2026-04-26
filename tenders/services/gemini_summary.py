import os


def generate_company_summary(*, company, analysis) -> str:
    api_key = os.getenv('GEMINI_API_KEY')
    if not api_key:
        return ''

    try:
        from google import genai
    except ImportError:
        return ''

    try:
        model_name = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash')
        client = genai.Client(api_key=api_key)
        reasons = '\n'.join(
            f'- {reason.title}: {reason.description}'
            for reason in analysis.reasons.all()
        ) or '- No risk reasons triggered.'

        prompt = (
            'You are assisting an anti-corruption analyst. '
            'Write a concise, evidence-based summary of why this company may be suspicious in 4 sentences or less. '
            'Use only the provided reasons and statistics. Do not invent facts.\n'
            f'Company name: {company.name}\n'
            f'Total participations: {company.total_participations}\n'
            f'Total wins: {company.total_wins}\n'
            f'Completed projects: {company.completed_projects}\n'
            f'Failed projects: {company.failed_projects}\n'
            f'Total score: {analysis.total_score}\n'
            f'Suspicion level: {analysis.suspicion_level}\n'
            f'Reasons:\n{reasons}'
        )
        response = client.models.generate_content(model=model_name, contents=prompt)
        return getattr(response, 'text', '') or ''
    except Exception:
        return ''
