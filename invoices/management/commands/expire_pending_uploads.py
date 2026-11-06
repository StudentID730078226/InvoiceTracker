from django.core.management.base import BaseCommand
from invoices.pending import expire_uploads


class Command(BaseCommand):
    help = 'Remove temporary uploads older than 24 hours; confirmed invoice files are retained.'

    def handle(self, *args, **options):
        expire_uploads()
