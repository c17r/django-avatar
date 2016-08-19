from django.conf.urls import include, url
from django.core.urlresolvers import reverse_lazy
from avatar import views
from django.views import generic


urlpatterns = [
    url(r'^avatar/', include('avatar.urls')),

    url(r'^landing_page/$', generic.TemplateView.as_view(template_name='dummy/success.html'), name='landing_page'),

    url(r'^success_url/add/$', views.Add.as_view(success_url=reverse_lazy('landing_page')), name='success_url_add'),
]
