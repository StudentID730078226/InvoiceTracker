#!/usr/bin/env python
import os
import sys

def main():
    """Select the project settings and run the requested Django command."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    from django.core.management import execute_from_command_line
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
