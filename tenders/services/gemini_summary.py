import os


def generate_company_summary(*, company, analysis, raise_errors: bool = False) -> str:
    if analysis.suspicion_level != 'high':
        return ''

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
        ) or '- Xavf sabablari topilmadi.'

        prompt = (
            'Siz Oʻzbekistondagi davlat xaridlari bo‘yicha korrupsiyaga qarshi tahlilchiga '
            'yordam berayotgan assistantsiz. Quyidagi dalillar asosida kompaniya nega yuqori '
            'xavfli yoki shubhali ko‘rinishini oddiy inson tushunadigan Oʻzbek tilida, lotin '
            'yozuvida tushuntiring. Javob 3-4 gapdan oshmasin. Faqat berilgan statistika va '
            'sabablarni ishlating, yangi fakt o‘ylab topmang. Matn rasmiy, aniq va tushunarli '
            'bo‘lsin.\n'
            f'Kompaniya nomi: {company.name}\n'
            f'Jami ishtiroklar: {company.total_participations}\n'
            f'Jami g‘alabalar: {company.total_wins}\n'
            f'Muvaffaqiyatli yakunlangan loyihalar: {company.completed_projects}\n'
            f'Bajarilmagan yoki muvaffaqiyatsiz loyihalar: {company.failed_projects}\n'
            f'Umumiy xavf bali: {analysis.total_score}\n'
            f'Xavf darajasi: {analysis.suspicion_level}\n'
            f'Sabablar:\n{reasons}'
        )
        response = client.models.generate_content(model=model_name, contents=prompt)
        return (getattr(response, 'text', '') or '').strip()
    except Exception:
        if raise_errors:
            raise
        return ''
