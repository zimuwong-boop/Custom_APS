from django.urls import re_path

from aps.api import api, index

urlpatterns = [re_path(r"^api/v1/(?P<path>.*)$", api), re_path(r"^.*$", index)]
