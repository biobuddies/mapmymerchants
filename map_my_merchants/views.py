from django.shortcuts import render

from .cash_flow import summarize_months
from .models import Place


def cash_flow_view(request):
    months = summarize_months()
    scale_usd = max((max(m['income_usd'], m['expense_usd']) for m in months), default=1) or 1
    return render(
        request,
        'cash_flow.html.dj',
        {
            'months': tuple(
                {
                    **month,
                    'expense_percent': round(100 * month['expense_usd'] / scale_usd),
                    'income_percent': round(100 * month['income_usd'] / scale_usd),
                }
                for month in months
            )
        },
    )


def map_view(request):
    return render(request, 'index.html.dj', {'places': Place.objects.as_tuples()})
