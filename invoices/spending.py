"""Read-only, business-scoped spending aggregation. Decimal money until chart display."""
from datetime import date, timedelta
from decimal import Decimal
from django.db.models import Sum, Count, Min, Max, Q
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncQuarter, TruncYear, Lower, Trim
from .models import Invoice

TRUNC = {'day': TruncDay, 'week': TruncWeek, 'month': TruncMonth, 'quarter': TruncQuarter, 'year': TruncYear}


def period_start(value, unit):
    if unit == 'day': return value
    if unit == 'week': return value - timedelta(days=value.weekday())
    if unit == 'year': return date(value.year, 1, 1)
    return date(value.year, ((value.month - 1) // 3 * 3 + 1) if unit == 'quarter' else value.month, 1)


def next_period(value, unit):
    if unit in ('day', 'week'): return value + timedelta(days=1 if unit == 'day' else 7)
    months = {'month': 1, 'quarter': 3, 'year': 12}[unit]
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def build_spending(business, filters):
    records = Invoice.objects.filter(business=business)
    status = filters['status']
    if status == 'submitted_approved': records = records.filter(status__in=['submitted', 'approved'])
    elif status != 'all': records = records.filter(status=status)
    if filters.get('supplier'): records = records.filter(supplier__icontains=filters['supplier'].strip())
    records = records.filter(currency=filters['currency'])
    # Count undated records separately: they cannot be attributed to an invoice-date range.
    undated = records.filter(invoice_date__isnull=True).count()
    if filters.get('date_from'): records = records.filter(invoice_date__gte=filters['date_from'])
    if filters.get('date_to'): records = records.filter(invoice_date__lte=filters['date_to'])
    incomplete = records.filter(Q(invoice_date__isnull=True) | Q(total__isnull=True)).count()
    records = records.filter(invoice_date__isnull=False, total__isnull=False)
    summary = records.aggregate(total=Sum('total'), count=Count('pk'), first=Min('invoice_date'), last=Max('invoice_date'))
    total = summary['total'] or Decimal('0')
    unit = filters['granularity']
    points = []
    if summary['count']:
        start = period_start(filters.get('date_from') or summary['first'], unit)
        end = period_start(filters.get('date_to') or summary['last'], unit)
        buckets = {row['period']: row for row in records.order_by().annotate(period=TRUNC[unit]('invoice_date')).values('period').annotate(total=Sum('total'), count=Count('pk'))}
        current = start
        while current <= end:
            if len(points) >= 1000:
                raise ValueError('This range has more than 1,000 periods. Choose a shorter range or a coarser granularity.')
            row = buckets.get(current, {})
            label = (f'{current.year} Q{(current.month-1)//3+1}' if unit == 'quarter' else
                     str(current.year) if unit == 'year' else current.strftime('%b %Y') if unit == 'month' else current.isoformat())
            points.append({'label': label, 'total': str(row.get('total', Decimal('0'))), 'count': row.get('count', 0)})
            if current == end: break
            current = next_period(current, unit)
    suppliers = list(records.order_by().annotate(key=Lower(Trim('supplier'))).values('key').annotate(
        label=Min('supplier'), total=Sum('total'), count=Count('pk')).order_by('-total', 'key'))
    for supplier in suppliers:
        supplier['label'] = supplier['label'].strip() or 'Not entered'
        supplier['total'] = str(supplier['total'])
    return {'total': total, 'invoice_count': summary['count'], 'average': total / summary['count'] if summary['count'] else Decimal('0'),
            'undated': undated, 'incomplete': incomplete, 'periods': points, 'suppliers': suppliers,
            'chart_data': {'currency': filters['currency'], 'periods': points, 'suppliers': suppliers},
            'records': records}
