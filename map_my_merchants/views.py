from django.shortcuts import render

from .models import Place


def map_view(request):
    return render(request, 'index.html.dj', {'places': Place.objects.as_tuples()})
