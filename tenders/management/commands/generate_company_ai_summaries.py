import os

from django.core.management.base import BaseCommand

from tenders.models import CompanySuspicionAnalysis
from tenders.services.gemini_summary import generate_company_summary
from tenders.services.risk_scoring import analyze_all_companies


class Command(BaseCommand):
    help = 'Generate Uzbek Gemini summaries for high-risk company suspicion analyses.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reanalyze',
            action='store_true',
            help='Recalculate company risk analyses before generating summaries.',
        )

    def handle(self, *args, **options):
        if not os.getenv('GEMINI_API_KEY'):
            self.stdout.write(self.style.WARNING('GEMINI_API_KEY is not configured. No summaries generated.'))
            return

        if options['reanalyze']:
            analyze_all_companies()

        analyses = (
            CompanySuspicionAnalysis.objects.filter(suspicion_level=CompanySuspicionAnalysis.SuspicionLevel.HIGH)
            .select_related('company')
            .prefetch_related('reasons')
            .order_by('-total_score', 'company__name')
        )

        generated = 0
        skipped = 0
        for analysis in analyses:
            try:
                summary = generate_company_summary(
                    company=analysis.company,
                    analysis=analysis,
                    raise_errors=True,
                )
            except Exception as exc:
                self.stdout.write(
                    self.style.WARNING(
                        f'Gemini summary failed for {analysis.company.name}: {exc.__class__.__name__}: {exc}'
                    )
                )
                skipped += 1
                continue

            if not summary:
                skipped += 1
                continue

            analysis.ai_summary = summary
            analysis.save(update_fields=['ai_summary', 'analyzed_at'])
            generated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f'Generated Uzbek AI summaries for {generated} high-risk companies. Skipped: {skipped}.'
            )
        )
