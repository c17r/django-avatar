from django.shortcuts import render, redirect
from django.utils import six
from django.utils.translation import ugettext as _

from django.contrib import messages
from django.contrib.auth.decorators import login_required

from django.contrib.auth import mixins
from django.views import generic
from django.utils.encoding import force_text

from avatar.conf import settings
from avatar.forms import PrimaryAvatarForm, DeleteAvatarForm, UploadAvatarForm
from avatar.models import Avatar
from avatar.signals import avatar_updated
from avatar.utils import (get_primary_avatar, get_default_avatar_url,
                          invalidate_cache)


class Base(mixins.LoginRequiredMixin, generic.FormView):
    def get_avatars(self):
        if hasattr(self, '_get_avatars'):
            return self._get_avatars

        avatars = self.request.user.avatar_set.all()
        avatar = None

        primary_avatar = avatars.order_by('-primary')[:1]
        if primary_avatar:
            avatar = primary_avatar[0]

        if settings.AVATAR_MAX_AVATARS_PER_USER == 1:
            avatars = primary_avatar
        else:
            avatars = avatars[:settings.AVATAR_MAX_AVATARS_PER_USER]

        self._get_avatars = (avatar, avatars)
        return self._get_avatars

    def get_context_data(self, **kwargs):
        avatar, avatars = self.get_avatars()
        context = super(Base, self).get_context_data(**kwargs)
        context.update({
            'avatar': avatar,
            'avatars': avatars
        })
        return context

    def get_form_kwargs(self):
        kwargs = super(Base, self).get_form_kwargs()
        kwargs['user'] = self.request.user
        return kwargs

    def get_success_url(self):
        if self.success_url:
            return force_text(self.success_url)

        url = self.request.POST.get('next')
        if not url:
            url = self.request.GET.get('next')
        if not url:
            url = self.request.META.get('HTTP_REFERER')
        if not url:
            url = self.request.path
        if url:
            return url

    def add_avatar(self, form):
        avatar = Avatar(user=self.request.user, primary=True)
        image_file = self.request.FILES['avatar']
        avatar.avatar.save(image_file.name, image_file)
        avatar.save()
        messages.success(self.request, _("Successfully uploaded a new avatar."))
        avatar_updated.send(sender=Avatar, user=self.request.user, avatar=avatar)


def _get_next(request):
    """
    The part that's the least straightforward about views in this module is
    how they determine their redirects after they have finished computation.

    In short, they will try and determine the next place to go in the
    following order:

    1. If there is a variable named ``next`` in the *POST* parameters, the
       view will redirect to that variable's value.
    2. If there is a variable named ``next`` in the *GET* parameters,
       the view will redirect to that variable's value.
    3. If Django can determine the previous page from the HTTP headers,
       the view will redirect to that previous page.
    """
    next = request.POST.get('next', request.GET.get('next',
                            request.META.get('HTTP_REFERER', None)))
    if not next:
        next = request.path
    return next


def _get_avatars(user):
    # Default set. Needs to be sliced, but that's it. Keep the natural order.
    avatars = user.avatar_set.all()

    # Current avatar
    primary_avatar = avatars.order_by('-primary')[:1]
    if primary_avatar:
        avatar = primary_avatar[0]
    else:
        avatar = None

    if settings.AVATAR_MAX_AVATARS_PER_USER == 1:
        avatars = primary_avatar
    else:
        # Slice the default set now that we used
        # the queryset for the primary avatar
        avatars = avatars[:settings.AVATAR_MAX_AVATARS_PER_USER]
    return (avatar, avatars)


class Add(Base):
    template_name = 'avatar/add.html'
    form_class = UploadAvatarForm

    def form_valid(self, form):
        self.add_avatar(form)
        return super(Add, self).form_valid(form)


@login_required
def change(request, extra_context=None, next_override=None,
           upload_form=UploadAvatarForm, primary_form=PrimaryAvatarForm,
           *args, **kwargs):
    if extra_context is None:
        extra_context = {}
    avatar, avatars = _get_avatars(request.user)
    if avatar:
        kwargs = {'initial': {'choice': avatar.id}}
    else:
        kwargs = {}
    upload_avatar_form = upload_form(user=request.user, **kwargs)
    primary_avatar_form = primary_form(request.POST or None,
                                       user=request.user,
                                       avatars=avatars, **kwargs)
    if request.method == "POST":
        updated = False
        if 'choice' in request.POST and primary_avatar_form.is_valid():
            avatar = Avatar.objects.get(
                id=primary_avatar_form.cleaned_data['choice'])
            avatar.primary = True
            avatar.save()
            updated = True
            invalidate_cache(request.user)
            messages.success(request, _("Successfully updated your avatar."))
        if updated:
            avatar_updated.send(sender=Avatar, user=request.user, avatar=avatar)
        return redirect(next_override or _get_next(request))

    context = {
        'avatar': avatar,
        'avatars': avatars,
        'upload_avatar_form': upload_avatar_form,
        'primary_avatar_form': primary_avatar_form,
        'next': next_override or _get_next(request)
    }
    context.update(extra_context)
    return render(request, 'avatar/change.html', context)


class Delete(Base):
    template_name = 'avatar/confirm_delete.html'
    form_class = DeleteAvatarForm

    def get_form_kwargs(self):
        _, avatars = self.get_avatars()
        kwargs = super(Delete, self).get_form_kwargs()
        kwargs['avatars'] = avatars
        return kwargs

    def form_valid(self, form):
        avatar, avatars = self.get_avatars()
        ids = form.cleaned_data['choices']
        if six.text_type(avatar.id) in ids and avatars.count() > len(ids):
            for a in avatars:
                if six.text_type(a.id) not in ids:
                    a.primary = True
                    a.save()
                    avatar_updated.send(sender=Avatar, user=self.request.user,
                                        avatar=avatar)
                    break
        Avatar.objects.filter(id__in=ids).delete()
        messages.success(self.request,
                        _("Successfully deleted the requested avatars."))
        return super(Delete, self).form_valid(form)


class RenderPrimary(generic.RedirectView):
    def get_redirect_url(self, *args, **kwargs):
        size = int(self.kwargs.get('size', settings.AVATAR_DEFAULT_SIZE))
        user = self.kwargs.get('user')

        avatar = get_primary_avatar(user, size=size)
        if avatar:
            # FIXME: later, add an option to render the resized avatar dynamically
            # instead of redirecting to an already created static file. This could
            # be useful in certain situations, particulary if there is a CDN and
            # we want to minimize the storage usage on our static server, letting
            # the CDN store those files instead
            url = avatar.avatar_url(size)
        else:
            url = get_default_avatar_url()

        return url
