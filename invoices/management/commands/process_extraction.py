from django.core.management.base import BaseCommand, CommandError

from invoices.extraction import process_pending_run, process_run


class Command(BaseCommand):
    help = "Process one review-only LayoutLM v1 extraction."

    def add_arguments(self, parser):
        parser.add_argument("run_id", type=int, nargs="?")
        parser.add_argument("--pending", type=int)

    def handle(self, *args, **options):
        if options["pending"]:
            process_pending_run(options["pending"])
        elif options["run_id"]:
            process_run(options["run_id"])
        else:
            raise CommandError("Provide an extraction run ID or --pending ID.")
